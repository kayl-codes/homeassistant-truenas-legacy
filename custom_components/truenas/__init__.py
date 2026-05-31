"""The TrueNAS integration."""

from __future__ import annotations

from logging import getLogger

from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import (
    CONF_DATA_UNIT,
    DEFAULT_DATA_UNIT,
    DOMAIN,
    PLATFORMS,
    SIGNAL_UPDATE_SENSORS,
)
from .coordinator import TrueNASCoordinator
from .entity import format_unique_id
from .helper import scaled_data_unit
from .sensor_types import SENSOR_TYPES

_LOGGER = getLogger(__name__)


# ---------------------------
#   _migrate_data_size_units
# ---------------------------
def _migrate_data_size_units(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    coordinator: TrueNASCoordinator,
) -> None:
    """Force each DATA_SIZE sensor's display unit from the base and magnitude.

    The unit is derived from the configured base (GB/GiB) and the entity's
    current value, then written directly to the entity registry on every startup
    so the GB/GiB preference takes effect and the unit tracks the value (e.g. a
    pool is shown in TiB once it exceeds 1 TiB).
    """
    data_unit = config_entry.options.get(
        CONF_DATA_UNIT, config_entry.data.get(CONF_DATA_UNIT, DEFAULT_DATA_UNIT)
    )
    binary = data_unit == "GiB"
    inst = config_entry.data[CONF_NAME]
    ent_reg = er.async_get(hass)

    for description in SENSOR_TYPES:
        if getattr(description, "device_class", None) == SensorDeviceClass.DATA_SIZE:
            _migrate_description(ent_reg, coordinator, inst, description, binary)


def _migrate_description(ent_reg, coordinator, inst, description, binary) -> None:
    """Force units for all entities produced by a single DATA_SIZE description."""
    data = coordinator.ds.get(description.data_path)
    if not isinstance(data, dict):
        return

    if not description.data_reference:
        value = data.get(description.data_attribute)
        _force_entity_unit(ent_reg, inst, description, None, value, binary)
        return

    for uid, vals in data.items():
        if not isinstance(vals, dict):
            continue
        ref = vals.get(description.data_reference)
        _force_entity_unit(
            ent_reg,
            inst,
            description,
            ref if ref is not None else uid,
            vals.get(description.data_attribute),
            binary,
        )


def _force_entity_unit(ent_reg, inst, description, reference, value, binary) -> None:
    """Write the magnitude-appropriate display unit of one entity to the registry."""
    entity_id = ent_reg.async_get_entity_id(
        "sensor", DOMAIN, format_unique_id(inst, description.key, reference)
    )
    if entity_id is None:
        return

    unit, _ = scaled_data_unit(value, binary)
    entry = ent_reg.async_get(entity_id)
    options = dict(entry.options.get("sensor", {})) if entry else {}
    if options.get("unit_of_measurement") != unit:
        options["unit_of_measurement"] = unit
        ent_reg.async_update_entity_options(entity_id, "sensor", options)


# ---------------------------
#   async_setup_entry
# ---------------------------
async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Set up TrueNAS config entry."""
    coordinator = TrueNASCoordinator(hass, config_entry)
    await coordinator.async_config_entry_first_refresh()
    hass.data.setdefault(DOMAIN, {})[config_entry.entry_id] = coordinator

    _migrate_data_size_units(hass, config_entry, coordinator)

    await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)

    # Re-run entity discovery on every coordinator refresh so entities for newly
    # appearing objects (e.g. a network interface coming up, a new pool/dataset)
    # are created without requiring an integration reload. The discovery handler
    # (entity.async_add_entities) expects the coordinator as its argument and does
    # not request another refresh, so this does not create a refresh loop.
    @callback
    def _handle_coordinator_refresh() -> None:
        async_dispatcher_send(hass, SIGNAL_UPDATE_SENSORS, coordinator)

    config_entry.async_on_unload(
        coordinator.async_add_listener(_handle_coordinator_refresh)
    )
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
