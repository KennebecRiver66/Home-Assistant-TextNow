"""Reading and clearing the sign-in prompts Home Assistant holds for an entry.

`ConfigEntry.async_get_active_flows` has two traps, and this integration fell
into both of them.

It returns a *generator*, so it is truthy even when it yields nothing. Home
Assistant only ever uses it inside `any()`; used directly in an `if`, it means
"always" rather than "there is a prompt waiting".

It also includes uninitialized flows. A flow that has not reached a step has
nothing to render, so it cannot be shown to the user or dismissed by them, and
the integrations page does not list it. A flow left in that state -- by a step
that raised, say -- is invisible wreckage, but it is enough to make Home
Assistant's own reauth de-duplication refuse to open a real prompt.

So flows are read through here, never directly, and they are treated as a UI
mechanism rather than as a signal about the health of the session.
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntry
from homeassistant.core import DOMAIN as HOMEASSISTANT_DOMAIN, HomeAssistant, callback
from homeassistant.data_entry_flow import UnknownFlow
from homeassistant.helpers import issue_registry as ir

_LOGGER = logging.getLogger(__name__)


@callback
def async_reauth_flows(hass: HomeAssistant, entry: ConfigEntry) -> list[dict[str, Any]]:
    """Return every reauth flow held for an entry, wreckage included."""
    return list(entry.async_get_active_flows(hass, {SOURCE_REAUTH}))


@callback
def async_visible_reauth_flows(
    hass: HomeAssistant, entry: ConfigEntry
) -> list[dict[str, Any]]:
    """Return the sign-in prompts the user can actually answer.

    A flow result carries a step_id only once the flow has a step to show,
    which is the same view the integrations page uses. Filtering on it is what
    stops the panel and Home Assistant disagreeing about whether a sign-in is
    being asked for.
    """
    return [
        flow for flow in async_reauth_flows(hass, entry) if flow.get("step_id")
    ]


@callback
def async_clear_reauth_flows(hass: HomeAssistant, entry: ConfigEntry) -> int:
    """Drop the sign-in prompts for an entry and return how many went.

    Home Assistant aborts in-progress reauth flows when an entry sets up
    successfully, but nothing aborts them when a later refresh succeeds --
    which is this integration's whole recovery path. Without this, a session
    that started working again left the prompt standing, and the prompt was
    enough to keep the panel insisting a sign-in was needed.
    """
    cleared = 0
    for flow in async_reauth_flows(hass, entry):
        try:
            hass.config_entries.flow.async_abort(flow["flow_id"])
        except UnknownFlow:
            # It finished between listing and aborting, which is the outcome
            # this was after anyway.
            continue
        cleared += 1

    if not cleared:
        return 0

    # Aborting a flow through the manager skips the step machinery, so the
    # repair item Home Assistant files alongside a reauth prompt is left
    # behind -- a card with a button that opens a flow that no longer exists.
    # Home Assistant pairs the two the same way when it removes an entry.
    ir.async_delete_issue(
        hass,
        HOMEASSISTANT_DOMAIN,
        f"config_entry_reauth_{entry.domain}_{entry.entry_id}",
    )
    _LOGGER.debug(
        "Cleared %s stale TextNow sign-in prompt(s) for %s", cleared, entry.title
    )
    return cleared
