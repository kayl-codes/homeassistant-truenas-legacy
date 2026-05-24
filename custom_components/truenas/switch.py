"""TrueNAS switch platform."""

from __future__ import annotations

from logging import getLogger

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import TrueNASEntity, async_add_entities
from .switch_types import SENSOR_SERVICES, SENSOR_TYPES  # noqa: F401

_LOGGER = getLogger(__name__)


# ---------------------------
#   async_setup_entry
# ---------------------------
async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    _async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up switches for TrueNAS component."""
    dispatcher = {
        "TrueNASServiceSwitch": TrueNASServiceSwitch,
    }
    await async_add_entities(hass, config_entry, dispatcher)


# ---------------------------
#   TrueNASServiceSwitch
# ---------------------------
class TrueNASServiceSwitch(TrueNASEntity, SwitchEntity):
    """Define a TrueNAS Service Switch."""

    @property
    def is_on(self) -> bool:
        """Return true if device is on."""
        return self._data[self.entity_description.data_is_on]

    async def async_turn_on(self, **kwargs) -> None:
        """Turn the entity on."""
        await self.hass.async_add_executor_job(
            self.coordinator.api.query,
            "service.start",
            [self._data["service"]],
        )
        await self.coordinator.async_refresh()

    async def async_turn_off(self, **kwargs) -> None:
        """Turn the entity off."""
        await self.hass.async_add_executor_job(
            self.coordinator.api.query,
            "service.stop",
            [self._data["service"]],
        )
        await self.coordinator.async_refresh()
