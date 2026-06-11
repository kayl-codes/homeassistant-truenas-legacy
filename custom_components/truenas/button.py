"""TrueNAS button platform."""

from __future__ import annotations

from logging import getLogger

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .button_types import (  # noqa: F401
    SENSOR_SERVICES,
    SENSOR_TYPES,
)
from .const import BUTTON_STATISTICS_CLEANUP, DOMAIN
from .coordinator import TrueNASCoordinator
from .entity import TrueNASEntity, async_add_entities, format_unique_id

_LOGGER = getLogger(__name__)


# ---------------------------
#   async_setup_entry
# ---------------------------
async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    _async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up TrueNAS buttons."""
    dispatcher = {
        "TrueNASButton": TrueNASButton,
    }
    await async_add_entities(hass, config_entry, dispatcher)

    # The orphaned-statistics cleanup button is a single diagnostic entity per
    # config entry, not tied to a TrueNAS object, so it is added directly.
    coordinator: TrueNASCoordinator = hass.data[DOMAIN][config_entry.entry_id]
    _async_add_entities([TrueNASStatisticsCleanupButton(coordinator)])


# ---------------------------
#   TrueNASButton
# ---------------------------
class TrueNASButton(TrueNASEntity, ButtonEntity):
    """Define a TrueNAS run button (one-tap trigger for an on-demand task)."""

    async def async_press(self) -> None:
        """Trigger the configured JSON-RPC method for this object."""
        method = self.entity_description.api_method
        object_id = self._data.get("id")
        if not method or object_id is None:
            _LOGGER.warning(
                "TrueNAS button %s has no api_method or object id; skipping",
                self.entity_id,
            )
            return

        # Trigger the run and show RUNNING immediately (re-synced on next poll).
        await self.coordinator.async_run_task(
            method, object_id, self.entity_description.data_path
        )


# ---------------------------
#   TrueNASStatisticsCleanupButton
# ---------------------------
class TrueNASStatisticsCleanupButton(
    CoordinatorEntity[TrueNASCoordinator], ButtonEntity
):
    """Diagnostic button to delete orphaned recorder statistics.

    Available only while orphans are actually present — independent of whether
    the Repairs issue has been ignored.
    """

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = BUTTON_STATISTICS_CLEANUP
    _attr_icon = "mdi:database-remove"

    def __init__(self, coordinator: TrueNASCoordinator) -> None:
        """Initialize the cleanup button."""
        super().__init__(coordinator)
        inst = coordinator.config_entry.data[CONF_NAME]
        self._attr_unique_id = format_unique_id(inst, BUTTON_STATISTICS_CLEANUP)
        hostname = coordinator.data.get("system_info", {}).get("hostname", inst)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{inst}_{hostname}")},
        )

    @property
    def available(self) -> bool:
        """Available only while orphaned statistics exist."""
        return bool(self.coordinator.orphaned_statistics)

    async def async_press(self) -> None:
        """Clear the orphaned statistics."""
        await self.coordinator.async_clear_orphaned_statistics()
