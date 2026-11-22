"""Encrypted seed vault & automated free cloud sync for Sellbird.

Provides two tiers of free persistence without requiring paid Render disks:
1. Baseline Encrypted Seed (seed.enc): Encrypted snapshot of the database committed to
   the repository. Automatically restored on boot when starting from scratch.
2. Continuous Free Cloud Backup (GitHub Private Gist):
   If GITHUB_BACKUP_TOKEN is set in Render environment variables, Sellbird automatically
   syncs the encrypted database to a private Gist on your GitHub account every 30 minutes
   and pulls the latest copy on every startup. 100% free, permanent, and private.
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import json
import logging
import os
import sys
from pathlib import Path

from cryptography.fernet import Fernet
import httpx

logger = logging.getLogger("sellbird.seed_vault")

DEFAULT_SECRET = "cartnova-sellbird-prod-vault-key-2026"
GIST_FILENAME = "sellbird_vault.enc"
GIST_DESC = "Sellbird Automated Encrypted Database Vault (Private)"


def derive_key(secret: str | None = None) -> bytes:
    """Derive a URL-safe 32-byte Fernet key from any arbitrary passphrase."""
    raw = (secret or os.getenv("SELLBIRD_SECRET") or DEFAULT_SECRET).strip()
    digest = hashlib.sha256(raw.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def encrypt_database(src_db: Path | str, dst_enc: Path | str, secret: str | None = None) -> int:
    """Compress with gzip and encrypt with Fernet."""
    src = Path(src_db)
    dst = Path(dst_enc)
    if not src.is_file():
        raise FileNotFoundError(f"Source database not found: {src}")

    data = src.read_bytes()
    compressed = gzip.compress(data, compresslevel=9)
    fernet = Fernet(derive_key(secret))
    encrypted = fernet.encrypt(compressed)

    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(encrypted)
    return len(encrypted)


def decrypt_database(src_enc: Path | str, dst_db: Path | str, secret: str | None = None) -> int:
    """Decrypt with Fernet and decompress with gzip."""
    src = Path(src_enc)
    dst = Path(dst_db)
    if not src.is_file():
        raise FileNotFoundError(f"Encrypted seed not found: {src}")

    encrypted = src.read_bytes()
    fernet = Fernet(derive_key(secret))
    compressed = fernet.decrypt(encrypted)
    data = gzip.decompress(compressed)

    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(data)
    return len(data)


def restore_database(target_db: Path | str, seed_enc: Path | str | None = None, secret: str | None = None) -> bool:
    """Restore database from remote private Gist if available, otherwise from seed.enc."""
    target = Path(target_db)
    target.parent.mkdir(parents=True, exist_ok=True)

    # 1. Try pulling from remote private Gist if token is set
    token = os.getenv("GITHUB_BACKUP_TOKEN", "").strip()
    if token:
        try:
            print("Checking remote private Gist for latest database backup...")
            if pull_gist_backup(target, token, secret):
                print(f"Successfully restored latest database from private Gist to {target}")
                return True
        except Exception as e:
            logger.warning("Gist backup restore failed: %s", e)
            print(f"Notice: Remote Gist sync check failed ({e}); falling back to local seed.")

    # 2. Try restoring from local encrypted seed.enc
    seed = Path(seed_enc) if seed_enc else Path("seed.enc")
    if not seed.is_file():
        # Check parent or current directory
        for candidate in [Path("/app/seed.enc"), Path(__file__).resolve().parent.parent / "seed.enc"]:
            if candidate.is_file():
                seed = candidate
                break

    if seed.is_file():
        try:
            size = decrypt_database(seed, target, secret)
            print(f"Restored database from encrypted seed ({size:,} bytes) -> {target}")
            return True
        except Exception as e:
            logger.error("Failed to decrypt seed: %s", e)
            print(f"Error decrypting seed: {e}")

    return False


def pull_gist_backup(dst_db: Path | str, token: str, secret: str | None = None) -> bool:
    """Fetch encrypted backup from private Gist and decrypt to dst_db."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    with httpx.Client(timeout=30.0) as client:
        # Find existing sellbird backup gist
        r = client.get("https://api.github.com/gists", headers=headers)
        if r.status_code != 200:
            return False

        gists = r.json()
        target_gist = None
        for g in gists:
            if GIST_FILENAME in g.get("files", {}) or g.get("description") == GIST_DESC:
                target_gist = g
                break

        if not target_gist:
            return False

        file_info = target_gist["files"].get(GIST_FILENAME)
        if not file_info:
            return False

        raw_url = file_info.get("raw_url")
        content_resp = client.get(raw_url, headers=headers)
        if content_resp.status_code != 200:
            return False

        enc_b64 = content_resp.text.strip()
        encrypted_bytes = base64.b64decode(enc_b64)

        fernet = Fernet(derive_key(secret))
        compressed = fernet.decrypt(encrypted_bytes)
        data = gzip.decompress(compressed)

        dst = Path(dst_db)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(data)
        return True


def push_gist_backup(src_db: Path | str, token: str, secret: str | None = None) -> bool:
    """Compress, encrypt, and push database to a private GitHub Gist."""
    src = Path(src_db)
    if not src.is_file():
        return False

    data = src.read_bytes()
    compressed = gzip.compress(data, compresslevel=9)
    fernet = Fernet(derive_key(secret))
    encrypted = fernet.encrypt(compressed)
    enc_b64 = base64.b64encode(encrypted).decode("ascii")

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    with httpx.Client(timeout=30.0) as client:
        # Search for existing gist
        r = client.get("https://api.github.com/gists", headers=headers)
        if r.status_code != 200:
            return False

        target_gist_id = None
        for g in r.json():
            if GIST_FILENAME in g.get("files", {}) or g.get("description") == GIST_DESC:
                target_gist_id = g.get("id")
                break

        payload = {
            "description": GIST_DESC,
            "files": {
                GIST_FILENAME: {
                    "content": enc_b64
                }
            }
        }

        if target_gist_id:
            # Update existing gist
            patch_r = client.patch(f"https://api.github.com/gists/{target_gist_id}", headers=headers, json=payload)
            return patch_r.status_code == 200
        else:
            # Create new private gist
            payload["public"] = False
            post_r = client.post("https://api.github.com/gists", headers=headers, json=payload)
            return post_r.status_code == 201


def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python -m sellbird.seed_vault restore [dst_db] [seed_enc] [secret]")
        print("  python -m sellbird.seed_vault backup [src_db] [secret]")
        print("  python -m sellbird.seed_vault encrypt <src> <dst> [secret]")
        print("  python -m sellbird.seed_vault decrypt <src> <dst> [secret]")
        sys.exit(1)

    cmd = sys.argv[1].lower()

    if cmd == "restore":
        dst = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("data/sellbird.db")
        seed = Path(sys.argv[3]) if len(sys.argv) > 3 else None
        secret = sys.argv[4] if len(sys.argv) > 4 else None
        ok = restore_database(dst, seed, secret)
        sys.exit(0 if ok else 1)

    elif cmd == "backup":
        src = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("data/sellbird.db")
        secret = sys.argv[3] if len(sys.argv) > 3 else None
        token = os.getenv("GITHUB_BACKUP_TOKEN", "").strip()
        if token:
            ok = push_gist_backup(src, token, secret)
            print("Remote Gist backup:", "SUCCESS" if ok else "FAILED")
            sys.exit(0 if ok else 1)
        else:
            print("Notice: GITHUB_BACKUP_TOKEN not set; skipping remote Gist backup.")
            sys.exit(0)

    elif cmd in ("encrypt", "decrypt"):
        if len(sys.argv) < 4:
            print(f"Usage: python -m sellbird.seed_vault {cmd} <src> <dst> [secret]")
            sys.exit(1)
        src = Path(sys.argv[2])
        dst = Path(sys.argv[3])
        secret = sys.argv[4] if len(sys.argv) > 4 else None
        if cmd == "encrypt":
            size = encrypt_database(src, dst, secret)
            print(f"Encrypted {src} -> {dst} ({size:,} bytes)")
        else:
            size = decrypt_database(src, dst, secret)
            print(f"Decrypted {src} -> {dst} ({size:,} bytes)")
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
