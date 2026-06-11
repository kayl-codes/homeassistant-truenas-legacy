"""Repairs for the TrueNAS integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.repairs import RepairsFlow
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import issue_registry as ir

from .const import CONF_STATISTICS_CLEANUP_IGNORED, DOMAIN, ISSUE_STATISTICS_ORPHANED


class StatisticsCleanupRepairFlow(RepairsFlow):
    """Repair flow for orphaned statistics: delete them or ignore the issue."""

    def __init__(self, entry_id: str) -> None:
        """Remember which config entry this issue belongs to."""
        self._entry_id = entry_id

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Show the fix/ignore menu."""
        coordinator = self.hass.data.get(DOMAIN, {}).get(self._entry_id)
        count = len(coordinator.orphaned_statistics) if coordinator else 0
        return self.async_show_menu(
            step_id="init",
            menu_options=["fix", "ignore"],
            description_placeholders={"count": str(count)},
        )

    async def async_step_fix(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Delete the orphaned statistics."""
        coordinator = self.hass.data.get(DOMAIN, {}).get(self._entry_id)
        if coordinator is not None:
            await coordinator.async_clear_orphaned_statistics()
        return self.async_create_entry(title="", data={})

    async def async_step_ignore(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Suppress the issue for this config entry."""
        entry = self.hass.config_entries.async_get_entry(self._entry_id)
        if entry is not None:
            self.hass.config_entries.async_update_entry(
                entry,
                options={**entry.options, CONF_STATISTICS_CLEANUP_IGNORED: True},
            )
        ir.async_delete_issue(
            self.hass, DOMAIN, f"{ISSUE_STATISTICS_ORPHANED}_{self._entry_id}"
        )
        return self.async_create_entry(title="", data={})


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, Any] | None,
) -> RepairsFlow:
    """Create the fix flow for an orphaned-statistics issue.

    The issue id is ``statistics_orphaned_<entry_id>``; the entry id is parsed
    back out so the flow can act on the right coordinator/config entry.
    """
    entry_id = issue_id.removeprefix(f"{ISSUE_STATISTICS_ORPHANED}_")
    return StatisticsCleanupRepairFlow(entry_id)
