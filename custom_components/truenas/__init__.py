"""The TrueNAS integration."""

from __future__ import annotations

from logging import getLogger

from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfInformation
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN, PLATFORMS
from .coordinator import TrueNASCoordinator

_LOGGER = getLogger(__name__)


# ---------------------------
#   async_setup_entry
# ---------------------------
async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Set up TrueNAS config entry."""
    coordinator = TrueNASCoordinator(hass, config_entry)
    await coordinator.async_config_entry_first_refresh()
    hass.data.setdefault(DOMAIN, {})[config_entry.entry_id] = coordinator

    # --- Auto-Migration for GB/GiB User Preference ---
    data_unit = config_entry.options.get(
        "data_unit", config_entry.data.get("data_unit", "GiB")
    )

    target_unit = (
        UnitOfInformation.GIBIBYTES
        if data_unit == "GiB"
        else UnitOfInformation.GIGABYTES
    )
    ent_reg = er.async_get(hass)
    for entity in er.async_entries_for_config_entry(ent_reg, config_entry.entry_id):
        if (
            entity.domain == "sensor"
            and entity.original_device_class == SensorDeviceClass.DATA_SIZE
        ):
            sensor_options = dict(entity.options.get("sensor", {}))
            if sensor_options.get("unit_of_measurement") != target_unit:
                sensor_options["unit_of_measurement"] = target_unit
                ent_reg.async_update_entity_options(
                    entity.entity_id, "sensor", sensor_options
                )
    # -------------------------------------------------

    await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)
    return True


# ---------------------------
#   async_unload_entry
# ---------------------------
async def async_unload_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Unload TrueNAS config entry."""

    if unload_ok := await hass.config_entries.async_unload_platforms(
        config_entry, PLATFORMS
    ):
        coordinator = hass.data[DOMAIN].pop(config_entry.entry_id)
        await hass.async_add_executor_job(coordinator.api.close)

    return unload_ok
