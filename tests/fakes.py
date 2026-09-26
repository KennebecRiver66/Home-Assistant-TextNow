"""Stand-ins for the Home Assistant objects the coordinator reaches for.

These deliberately copy Home Assistant's own awkward shapes rather than
convenient ones. `ConfigEntry.async_get_active_flows` returns a *generator* of
flow-result dicts and includes flows that never reached a step; a stub that
returned a plain list of strings is why a bug that made the panel demand a
sign-in forever got through a green test suite.
"""
from __future__ import annotations

import tempfile
from types import SimpleNamespace
from typing import Any

from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.data_entry_flow import UnknownFlow


class FakeFlowManager:
    """The flow bookkeeping, with Home Assistant's visible/invisible split."""

    def __init__(self) -> None:
        self.flows: list[dict[str, Any]] = []
        self.aborted: list[str] = []

    def add_flow(
        self,
        *,
        flow_id: str = "flow-1",
        entry_id: str = "entry-1",
        source: str = SOURCE_REAUTH,
        step_id: str | None = "reauth_confirm",
    ) -> dict[str, Any]:
        """Register a flow. step_id=None is one that never reached a step."""
        flow: dict[str, Any] = {
            "flow_id": flow_id,
            "handler": "textnow",
            "context": {"source": source, "entry_id": entry_id},
        }
        # Home Assistant only puts step_id in the result once the flow has a
        # step, which is what makes it visible on the integrations page.
        if step_id is not None:
            flow["step_id"] = step_id
        self.flows.append(flow)
        return flow

    def async_abort(self, flow_id: str) -> None:
        for index, flow in enumerate(self.flows):
            if flow["flow_id"] == flow_id:
                del self.flows[index]
                self.aborted.append(flow_id)
                return
        raise UnknownFlow

    def async_progress_by_handler(
        self,
        handler: str,
        include_uninitialized: bool = False,
        match_context: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        return [
            flow
            for flow in self.flows
            if flow["handler"] == handler
            and all(
                flow["context"].get(key) == value
                for key, value in (match_context or {}).items()
            )
            and (include_uninitialized or "step_id" in flow)
        ]


class FakeEntry:
    """A config entry with Home Assistant's real flow lookup semantics."""

    def __init__(
        self,
        hass: "FakeHass",
        *,
        entry_id: str = "entry-1",
        state: ConfigEntryState = ConfigEntryState.LOADED,
        data: dict[str, Any] | None = None,
        title: str = "demo_account",
        reason: str = "",
    ) -> None:
        self._hass = hass
        self.entry_id = entry_id
        self.domain = "textnow"
        self.state = state
        self.data = data or {}
        self.title = title
        self.reason = reason
        self.disabled_by = None
        self.unique_id = title
        self.reauth_starts = 0

    def async_get_active_flows(self, hass: Any, sources: set[str]):
        """Return a generator, exactly as Home Assistant does.

        This is the shape that matters: a generator is truthy even when it
        yields nothing, so any caller testing it for truth is wrong.
        """
        return (
            flow
            for flow in hass.config_entries.flow.async_progress_by_handler(
                self.domain,
                match_context={"entry_id": self.entry_id},
                include_uninitialized=True,
            )
            if flow["context"].get("source") in sources
        )

    def async_start_reauth(self, hass: Any) -> None:
        """Open a prompt, with Home Assistant's own de-duplication."""
        self.reauth_starts += 1
        if any(self.async_get_active_flows(hass, {SOURCE_REAUTH})):
            return
        hass.config_entries.flow.add_flow(
            flow_id=f"flow-started-{self.reauth_starts}", entry_id=self.entry_id
        )


class FakeConfigEntries:
    def __init__(self) -> None:
        self.flow = FakeFlowManager()
        self._entries: dict[str, FakeEntry] = {}
        self.reloaded: list[str] = []
        self.updates: list[dict[str, Any]] = []

    def add(self, entry: FakeEntry) -> FakeEntry:
        self._entries[entry.entry_id] = entry
        return entry

    def async_get_entry(self, entry_id: str) -> FakeEntry | None:
        return self._entries.get(entry_id)

    def async_entries(self, domain: str) -> list[FakeEntry]:
        return [e for e in self._entries.values() if e.domain == domain]

    def async_update_entry(self, entry: FakeEntry, *, data: dict[str, Any]) -> None:
        entry.data = data
        self.updates.append(data)

    async def async_reload(self, entry_id: str) -> None:
        self.reloaded.append(entry_id)


class FakeHass:
    """Just enough Home Assistant for the coordinator and the panel API."""

    def __init__(self) -> None:
        self.config_entries = FakeConfigEntries()
        self.data: dict[str, Any] = {}
        # The issue registry builds a Store, which wants somewhere to write
        self.config = SimpleNamespace(config_dir=tempfile.gettempdir())

    def verify_event_loop_thread(self, _what: str) -> None:
        """The registries assert they are on the event loop; the tests are."""

    def make_entry(self, **kwargs: Any) -> FakeEntry:
        return self.config_entries.add(FakeEntry(self, **kwargs))

    @property
    def flow(self) -> FakeFlowManager:
        return self.config_entries.flow
