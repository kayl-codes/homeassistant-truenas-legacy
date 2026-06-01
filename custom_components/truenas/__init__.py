"""The TrueNAS integration."""

from __future__ import annotations

from logging import getLogger

from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .binary_sensor_types import SENSOR_TYPES as BINARY_SENSOR_TYPES
from .const import (
    CONF_DATA_UNIT,
    DEFAULT_DATA_UNIT,
    DOMAIN,
    PLATFORMS,
    SIGNAL_UPDATE_SENSORS,
)
from .coordinator import TrueNASCoordinator
from .entity import _is_uid_excluded, format_unique_id
from .helper import scaled_data_unit
from .sensor_types import SENSOR_TYPES
from .switch_types import SENSOR_TYPES as SWITCH_SENSOR_TYPES
from .update_types import SENSOR_TYPES as UPDATE_SENSOR_TYPES

_LOGGER = getLogger(__name__)

# All entity descriptions across platforms, used to compute the set of unique_ids
# that legitimately exist for the current TrueNAS objects (orphan cleanup).
_ALL_DESCRIPTIONS = (
    *SENSOR_TYPES,
    *BINARY_SENSOR_TYPES,
    *SWITCH_SENSOR_TYPES,
    *UPDATE_SENSOR_TYPES,
)


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
#   _collect_active_unique_ids / _cleanup_orphaned_entities
# ---------------------------
def _referenced_unique_ids(inst: str, description, data: dict) -> set[str]:
    """Unique_ids the integration would create for one referenced description.

    Mirrors entity creation, honoring the ``data_exclude`` filter (e.g. traffic
    sensors of a down interface are skipped).
    """
    ids: set[str] = set()
    for uid, vals in data.items():
        if _is_uid_excluded(description, vals):
            continue
        ref = vals.get(description.data_reference) if isinstance(vals, dict) else None
        reference = ref if ref is not None else uid
        ids.add(format_unique_id(inst, description.key, reference))

    return ids


def _collect_active_unique_ids(
    inst: str, coordinator: TrueNASCoordinator
) -> tuple[set[str], set[str]]:
    """Return (active unique_ids, live bases) for the current TrueNAS objects.

    ``active`` is every unique_id the integration would create right now (see
    ``_referenced_unique_ids``), so entities filtered out by ``data_exclude``
    get cleaned up. ``live bases`` are the per-description id prefixes whose data
    domain currently holds data, so cleanup never wipes a whole group on a
    transient empty fetch.
    """
    active: set[str] = set()
    live_bases: set[str] = set()

    for description in _ALL_DESCRIPTIONS:
        base = format_unique_id(inst, description.key)
        if not getattr(description, "data_reference", None):
            # Keyless single entity: always protect it from removal.
            active.add(base)
            continue

        data = coordinator.data.get(description.data_path)
        if not isinstance(data, dict) or not data:
            continue

        live_bases.add(base)
        active |= _referenced_unique_ids(inst, description, data)

    return active, live_bases


def _cleanup_orphaned_entities(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    coordinator: TrueNASCoordinator,
) -> None:
    """Remove registry entities the integration would no longer create.

    An entity is deleted when it is not in the active set yet belongs to a data
    domain that currently holds data. This covers both true orphans (the object
    is gone) and entities filtered out by ``data_exclude`` (e.g. traffic sensors
    of a down interface). A transient empty fetch of a whole domain never wipes
    the corresponding group, and cleanup is skipped unless the last update
    succeeded.
    """
    if not coordinator.last_update_success:
        return

    inst = config_entry.data[CONF_NAME]
    active, live_bases = _collect_active_unique_ids(inst, coordinator)

    ent_reg = er.async_get(hass)
    for entity_entry in er.async_entries_for_config_entry(
        ent_reg, config_entry.entry_id
    ):
        unique_id = entity_entry.unique_id
        if unique_id in active:
            continue
        if any(
            unique_id == base or unique_id.startswith(f"{base}-") for base in live_bases
        ):
            _LOGGER.info(
                "Removing orphaned TrueNAS entity %s (unique_id=%s)",
                entity_entry.entity_id,
                unique_id,
            )
            ent_reg.async_remove(entity_entry.entity_id)


# ---------------------------
#   async_setup_entry
# ---------------------------
async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Set up TrueNAS config entry."""
    coordinator = TrueNASCoordinator(hass, config_entry)
    await coordinator.async_config_entry_first_refresh()
    hass.data.setdefault(DOMAIN, {})[config_entry.entry_id] = coordinator

    _migrate_data_size_units(hass, config_entry, coordinator)
    _cleanup_orphaned_entities(hass, config_entry, coordinator)

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
