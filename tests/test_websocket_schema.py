"""Tests for the WebSocket commands the panel calls.

The panel is the only caller, so a command whose schema rejects a realistic
message is invisible until someone clicks the button. These tests send the
message the panel sends.
"""
from __future__ import annotations

import pytest

from custom_components.textnow import websocket

COMMANDS = [
    ("textnow/get_entries", {}),
    ("textnow/contacts_list", {"entry_id": "abc123"}),
    ("textnow/contacts_add", {"entry_id": "abc123", "name": "Sam", "phone": "5555550100"}),
    (
        "textnow/contacts_update",
        {
            "entry_id": "abc123",
            "contact_id": "contact_sam",
            "name": "Sam",
            "phone": "5555550100",
        },
    ),
    ("textnow/contacts_delete", {"entry_id": "abc123", "contact_id": "contact_sam"}),
    (
        "textnow/send_test",
        {"entry_id": "abc123", "contact_id": "contact_sam", "message": "Hello"},
    ),
    ("textnow/refresh", {"entry_id": "abc123"}),
    ("textnow/keepalive_now", {"entry_id": "abc123"}),
    ("textnow/start_reauth", {"entry_id": "abc123"}),
]


def _schema(command: str):
    for name in dir(websocket):
        func = getattr(websocket, name)
        if getattr(func, "_ws_command", None) == command:
            return func._ws_schema
    raise AssertionError(f"{command} is not registered")


@pytest.mark.parametrize(("command", "payload"), COMMANDS)
def test_the_message_the_panel_sends_is_accepted(command: str, payload: dict) -> None:
    """The WebSocket envelope uses a numeric id, which payloads must not shadow."""
    schema = _schema(command)
    if schema is False:
        # Home Assistant skips validation for commands that take no arguments.
        assert not payload
        return

    validated = schema({"id": 7, "type": command, **payload})

    assert validated["id"] == 7
