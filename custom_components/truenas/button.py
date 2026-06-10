"""TrueNAS button platform."""

from __future__ import annotations

from logging import getLogger

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .button_types import (  # noqa: F401
    SENSOR_SERVICES,
    SENSOR_TYPES,
)
from .entity import TrueNASEntity, async_add_entities

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

        await self.hass.async_add_executor_job(
            self.coordinator.api.query,
            method,
            [object_id],
        )
        # Show RUNNING immediately so the press has visible feedback; the next
        # regular poll re-syncs to the real TrueNAS state.
        self.coordinator.set_optimistic_running(
            self.entity_description.data_path, object_id
        )
