"""Automated pipeline health and setup verification tests."""

import pytest
from sellbird.main import _needs_setup
from sellbird.config import load_config
from sellbird.collectors.discover import PROVIDERS


def test_system_setup_complete():
    """Verify that first-time setup is complete and not blocked."""
    assert not _needs_setup(), "Sellbird system should not be in needs_setup state"


def test_config_is_valid():
    """Verify that configuration loads without errors and includes required channels."""
    config = load_config()
    assert config is not None
    assert config.persona.company != "Your Company"
    assert config.channels.email.send_to_risky is True


def test_discovery_providers_available():
    """Verify that standard discovery providers are registered."""
    assert "tinyfish" in PROVIDERS
    assert "osm" in PROVIDERS
