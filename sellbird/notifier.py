"""Email notifications when high-intent leads are ready for a call."""

import logging
import os
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

import aiosmtplib

logger = logging.getLogger("sellbird.notifier")

DEFAULT_NOTIFICATION_EMAIL = "cartnova.co@gmail.com"


async def notify_lead_ready_for_call(
    config,
    env,
    state,
    prospect,
    reply_text: str,
    intent: str,
    conversation_id: str = "",
) -> bool:
    """Send an instant email notification to the user's Gmail when a lead is ready for a call."""
    dest_email = (
        os.getenv("NOTIFICATION_EMAIL")
        or getattr(env, "notification_email", "")
        or os.getenv("ALERT_EMAIL")
        or DEFAULT_NOTIFICATION_EMAIL
    ).strip()

    if not dest_email:
        logger.warning("No notification email configured; cannot send alert.")
        return False

    # Prevent duplicate alerts for the same conversation
    alert_key = f"lead_alert_sent:{conversation_id or prospect.id}"
    if await state.get_setting(alert_key):
        logger.info(f"Notification already sent for {prospect.email}; skipping duplicate.")
        return True

    smtp_host = getattr(env, "smtp_host", "") or os.getenv("SMTP_HOST", "")
    smtp_port = int(getattr(env, "smtp_port", 465) or os.getenv("SMTP_PORT", 465) or 465)
    smtp_user = getattr(env, "smtp_username", "") or os.getenv("SMTP_USERNAME", "")
    smtp_pass = getattr(env, "smtp_password", "") or os.getenv("SMTP_PASSWORD", "")

    if not (smtp_host and smtp_user and smtp_pass):
        logger.warning("SMTP credentials not configured; cannot send lead notification.")
        return False

    sender_name = getattr(config.persona, "name", "Pratyush")
    company_name = getattr(prospect, "company", "") or "a target company"
    prospect_name = f"{getattr(prospect, 'first_name', '')} {getattr(prospect, 'last_name', '')}".strip() or prospect.email

    subject = f"🔥 Ready for a call: {prospect_name} ({company_name})"

    body = f"""Hey {sender_name},

Great news! A lead has responded with high intent and is ready for a quick call.

Lead Details:
• Name: {prospect_name}
• Title: {getattr(prospect, 'title', 'N/A')}
• Company: {company_name}
• Email: {prospect.email}
• Intent: {intent}
• Received: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}

Their Reply:
--------------------------------------------------
{reply_text.strip()}
--------------------------------------------------

Sellbird has already drafted and queued the response in autopilot.
You can reply directly to {prospect.email} or view the conversation on your live dashboard:
https://sellbird.onrender.com/#conversations
"""

    msg = EmailMessage()
    msg["To"] = dest_email
    msg["From"] = formataddr(("Sellbird AI Alerts", smtp_user))
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid(domain=smtp_user.split("@")[-1])
    msg.set_content(body)

    try:
        await aiosmtplib.send(
            msg,
            hostname=smtp_host,
            port=smtp_port,
            username=smtp_user,
            password=smtp_pass,
            start_tls=(smtp_port == 587),
            use_tls=(smtp_port == 465),
            timeout=30,
        )
        await state.set_setting(alert_key, datetime.now(timezone.utc).isoformat())
        await state.log_action(
            action_type="lead_notification_sent",
            agent="handler",
            details={
                "prospect_id": getattr(prospect, "id", ""),
                "prospect_email": prospect.email,
                "dest_email": dest_email,
                "intent": intent,
            },
        )
        logger.info(f"Dispatched high-intent lead email notification to {dest_email} for {prospect.email}")
        return True
    except Exception as e:
        logger.error(f"Failed to dispatch lead notification to {dest_email}: {e}")
        return False
