"""Tests for the automation trigger config."""
from __future__ import annotations

import asyncio

import pytest
import voluptuous as vol

from custom_components.textnow.trigger import async_validate_trigger_config


def _validate(config: dict) -> dict:
    return asyncio.run(async_validate_trigger_config(None, config))


def test_the_original_platform_form_still_validates() -> None:
    """Existing automations use platform plus type."""
    config = _validate(
        {"platform": "textnow", "type": "message_received", "contact_id": "sam"}
    )

    assert config["type"] == "message_received"


def test_the_dotted_form_carries_the_type() -> None:
    """The newer trigger syntax names the type in the platform."""
    config = _validate({"platform": "textnow.phrase_received", "phrase": "gate"})

    assert config["type"] == "phrase_received"
    assert config["match_type"] == "contains"


def test_an_unknown_type_is_rejected() -> None:
    """A typo should fail validation rather than silently never fire."""
    with pytest.raises(vol.Invalid):
        _validate({"platform": "textnow", "type": "mesage_received"})
