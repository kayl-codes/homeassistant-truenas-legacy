"""TrueNAS HA shared entity model."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from logging import getLogger
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ATTRIBUTION, CONF_HOST, CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_platform as ep
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo, Entity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import slugify

from .const import (
    ATTRIBUTION,
    BEHAVIOR_REMOVE_INACTIVE_NIC,
    CONF_BEHAVIORS,
    DEFAULT_BEHAVIORS,
    DOMAIN,
    SIGNAL_UPDATE_SENSORS,
)
from .coordinator import TrueNASCoordinator
from .helper import format_attribute

_LOGGER = getLogger(__name__)


# ---------------------------
#   format_unique_id
# ---------------------------
def format_unique_id(inst: str, key: str, reference: object = None) -> str:
    """Build an entity unique_id from instance name, description key and reference.

    Shared so the migration in __init__.py can resolve the same unique_id an
    entity produces.
    """
    base = f"{inst.lower()}-{key}"
    if reference is None:
        return base
    return f"{base}-{slugify(str(reference).lower())}"


# ---------------------------
#   Entity discovery helpers
# ---------------------------
def _skip_keyless_description(entity_description, data) -> bool:
    """Return True if a keyless description has no value to expose."""
    attr_name = getattr(
        entity_description,
        "data_attribute",
        getattr(entity_description, "data_is_on", None),
    )
    return bool(attr_name) and data.get(attr_name) is None


def _is_uid_excluded(entity_description, vals) -> bool:
    """Return True if a referenced object is excluded from entity creation.

    Honors an optional ``data_exclude`` (key, value) on the description, e.g. to
    skip traffic sensors for a network interface whose link is down.
    """
    data_exclude = getattr(entity_description, "data_exclude", None)
    if not data_exclude:
        return False

    key, value = data_exclude
    return isinstance(vals, dict) and vals.get(key) == value


def _collect_new_entities(
    coordinator, descriptions, dispatcher, known: set[str]
) -> list:
    """Return entity objects whose unique_id has not been added yet.

    Runs on initial setup and on every coordinator refresh. ``known`` tracks the
    unique_ids already handed to ``async_add_entities`` for this platform, so each
    entity is added exactly once; genuinely new objects (e.g. a freshly attached
    disk) are picked up on a later refresh without re-adding existing entities.
    """
    behaviors = coordinator.config_entry.options.get(CONF_BEHAVIORS, DEFAULT_BEHAVIORS)
    apply_exclude = BEHAVIOR_REMOVE_INACTIVE_NIC in behaviors
    new_entities: list = []

    for entity_description in descriptions:
        data = coordinator.data.get(entity_description.data_path)
        if data is None:
            continue

        if entity_description.data_reference:
            for uid in data:
                # data is a mapping of uid -> values for reference descriptions;
                # fall back to treating the iterated item itself as the values.
                vals = data[uid] if isinstance(data, dict) else uid
                if apply_exclude and _is_uid_excluded(entity_description, vals):
                    continue
                obj = dispatcher[entity_description.func](
                    coordinator, entity_description, uid
                )
                _append_if_new(obj, known, new_entities)
        elif not _skip_keyless_description(entity_description, data):
            obj = dispatcher[entity_description.func](coordinator, entity_description)
            _append_if_new(obj, known, new_entities)

    return new_entities


def _append_if_new(obj, known: set[str], new_entities: list) -> None:
    """Append the entity to the batch when its unique_id has not been seen yet."""
    if obj.unique_id not in known:
        known.add(obj.unique_id)
        new_entities.append(obj)


async def async_add_entities(
    hass: HomeAssistant, config_entry: ConfigEntry, dispatcher: dict[str, Callable]
):
    """Set up the platform and register dynamic entity discovery.

    ``async_add_entities`` is only ever called for entities that have not been
    added yet. Existing entities refresh themselves through the coordinator and
    are never re-added, which previously caused "Platform truenas does not
    generate unique IDs" spam on every update cycle.
    """
    platform = ep.async_get_current_platform()
    services = getattr(platform.platform, "SENSOR_SERVICES", [])
    descriptions = getattr(platform.platform, "SENSOR_TYPES", [])

    for service in services:
        platform.async_register_entity_service(
            service.name, service.schema, service.action
        )

    known: set[str] = set()

    async def async_update_controller(coordinator):
        """Add entities for newly-appeared objects on each coordinator refresh."""
        new_entities = _collect_new_entities(
            coordinator, descriptions, dispatcher, known
        )
        if new_entities:
            _LOGGER.debug("Adding %d new TrueNAS entities", len(new_entities))
            await platform.async_add_entities(new_entities)

    await async_update_controller(hass.data[DOMAIN][config_entry.entry_id])

    unsub = async_dispatcher_connect(
        hass, SIGNAL_UPDATE_SENSORS, async_update_controller
    )
    config_entry.async_on_unload(unsub)


# ---------------------------
#   TrueNASEntity
# ---------------------------
class TrueNASEntity(CoordinatorEntity[TrueNASCoordinator], Entity):
    """Define entity."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: TrueNASCoordinator,
        entity_description,
        uid: str | None = None,
    ):
        """Initialize entity."""
        super().__init__(coordinator)
        self.entity_description = entity_description
        self._inst = coordinator.config_entry.data[CONF_NAME]
        self._config_entry = self.coordinator.config_entry
        self._attr_extra_state_attributes = {ATTR_ATTRIBUTION: ATTRIBUTION}
        self._uid = uid
        self._refresh_data()

    def _refresh_data(self) -> None:
        """Refresh cached data from the coordinator for this entity."""
        data = self.coordinator.data.get(self.entity_description.data_path, {})
        self._data = data.get(self._uid, {}) if self._uid else data
        if self._uid and not self._data:
            _LOGGER.debug(
                "Data for UID %s is missing or empty in %s",
                self._uid,
                self.entity_description.data_path,
            )

    @callback
    def _handle_coordinator_update(self) -> None:
        self._refresh_data()
        super()._handle_coordinator_update()

    @property
    def name(self) -> str | None:
        """Return the name for this entity."""
        if not self._uid:
            # Return the raw name (may be None) so an entity without its own
            # name falls back to the device name instead of showing "None".
            return self.entity_description.name

        data_value = None
        if self._data is not None and getattr(
            self.entity_description, "data_name", None
        ):
            data_value = self._data.get(self.entity_description.data_name)

        if data_value is None:
            data_value = str(self._uid)

        if self.entity_description.name:
            return f"{data_value} {self.entity_description.name}"

        return f"{data_value}"

    @property
    def unique_id(self) -> str:
        """Return a unique id for this entity."""
        if self._uid:
            data_ref = getattr(self.entity_description, "data_reference", None)
            value = self._data.get(data_ref) if self._data and data_ref else None
            reference = value if value is not None else self._uid
            return format_unique_id(self._inst, self.entity_description.key, reference)

        return format_unique_id(self._inst, self.entity_description.key)

    @property
    def device_info(self) -> DeviceInfo:
        """Return a description for device registry."""
        dev_connection = DOMAIN
        dev_connection_value = f"{self._inst}_{self.entity_description.ha_group}"
        dev_group = self.entity_description.ha_group
        if self.entity_description.ha_group == "System":
            dev_connection_value = (
                f"{self._inst}_{self.coordinator.data['system_info']['hostname']}"
            )

        if self.entity_description.ha_group.startswith("data__"):
            dev_group = self.entity_description.ha_group[6:]
            if dev_group in self._data:
                dev_group = self._data[dev_group]
                dev_connection_value = dev_group

        if self.entity_description.ha_connection:
            dev_connection = self.entity_description.ha_connection

        if self.entity_description.ha_connection_value:
            dev_connection_value = self.entity_description.ha_connection_value
            if dev_connection_value.startswith("data__"):
                data_key = dev_connection_value[6:]
                connection_val = self._data.get(data_key, "unknown")
                dev_connection_value = f"{self._inst}_{connection_val}"

        if self.entity_description.ha_group == "System":
            http_scheme = "https" if self.coordinator.api.scheme == "wss" else "http"
            return DeviceInfo(
                connections={(dev_connection, f"{dev_connection_value}")},
                identifiers={(dev_connection, f"{dev_connection_value}")},
                name=self._inst,
                model=f"{self.coordinator.data['system_info']['system_product']}",
                manufacturer=f"{self.coordinator.data['system_info']['system_manufacturer']}",
                sw_version=f"{self.coordinator.data['system_info']['version']}",
                configuration_url=f"{http_scheme}://{self.coordinator.config_entry.data[CONF_HOST]}",
            )

        return DeviceInfo(
            connections={(dev_connection, f"{dev_connection_value}")},
            default_name=f"{self._inst} {dev_group}",
            default_model=f"{self.coordinator.data['system_info']['system_product']}",
            default_manufacturer=f"{self.coordinator.data['system_info']['system_manufacturer']}",
            via_device=(
                DOMAIN,
                f"{self._inst}_{self.coordinator.data['system_info']['hostname']}",
            ),
        )

    @property
    def extra_state_attributes(self) -> Mapping[str, Any]:
        """Return the state attributes."""
        attributes = dict(super().extra_state_attributes or {})
        for variable in self.entity_description.data_attributes_list:
            if variable in self._data:
                attributes[format_attribute(variable)] = self._data[variable]

        return attributes

    async def start(self):
        """Run function."""
        raise NotImplementedError()

    async def stop(self):
        """Stop function."""
        raise NotImplementedError()

    async def restart(self):
        """Restart function."""
        raise NotImplementedError()

    async def reload(self):
        """Reload function."""
        raise NotImplementedError()

    async def snapshot(self):
        """Snapshot function."""
        raise NotImplementedError()
