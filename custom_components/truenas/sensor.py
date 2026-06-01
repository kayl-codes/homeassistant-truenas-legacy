"""TrueNAS sensor platform."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from logging import getLogger

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfInformation
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.util.dt import utc_from_timestamp

from .const import CONF_DATA_UNIT, DEFAULT_DATA_UNIT
from .coordinator import TrueNASCoordinator
from .entity import TrueNASEntity, async_add_entities
from .helper import scaled_data_unit
from .sensor_types import (  # noqa: F401
    SENSOR_SERVICES,
    SENSOR_TYPES,
)

_LOGGER = getLogger(__name__)


# ---------------------------
#   async_setup_entry
# ---------------------------
async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    _async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up entry for TrueNAS component."""
    dispatcher = {
        "TrueNASSensor": TrueNASSensor,
        "TrueNASUptimeSensor": TrueNASUptimeSensor,
        "TrueNASCloudsyncSensor": TrueNASCloudsyncSensor,
        "TrueNASDatasetSensor": TrueNASDatasetSensor,
        "TrueNASRsyncSensor": TrueNASRsyncSensor,
        "TrueNASReplicationSensor": TrueNASReplicationSensor,
    }
    await async_add_entities(hass, config_entry, dispatcher)


# ---------------------------
#   TrueNASSensor
# ---------------------------
class TrueNASSensor(TrueNASEntity, SensorEntity):
    """Define an TrueNAS sensor."""

    def __init__(
        self,
        coordinator: TrueNASCoordinator,
        entity_description,
        uid: str | None = None,
    ):
        super().__init__(coordinator, entity_description, uid)
        self._attr_suggested_unit_of_measurement = (
            self.entity_description.suggested_unit_of_measurement
        )

        if self._attr_suggested_unit_of_measurement in (
            UnitOfInformation.GIGABYTES,
            UnitOfInformation.GIBIBYTES,
        ):
            data_unit = self.coordinator.config_entry.options.get(
                CONF_DATA_UNIT,
                self.coordinator.config_entry.data.get(
                    CONF_DATA_UNIT, DEFAULT_DATA_UNIT
                ),
            )
            value = (
                self._data.get(self.entity_description.data_attribute)
                if self._data
                else None
            )
            unit, precision = scaled_data_unit(value, data_unit == "GiB")
            self._attr_suggested_unit_of_measurement = unit
            if precision is not None:
                self._attr_suggested_display_precision = precision

    @property
    def native_value(self) -> StateType | date | datetime | Decimal:
        """Return the value reported by the sensor."""
        return self._data[self.entity_description.data_attribute]

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Return the unit the value is expressed in."""
        if self.entity_description.native_unit_of_measurement:
            if self.entity_description.native_unit_of_measurement.startswith("data__"):
                uom = self.entity_description.native_unit_of_measurement[6:]
                if uom in self._data:
                    return self._data[uom]

            return self.entity_description.native_unit_of_measurement

        return None


# ---------------------------
#   TrueNASUptimeSensor
# ---------------------------
class TrueNASUptimeSensor(TrueNASSensor):
    """Define an TrueNAS Uptime sensor."""

    @property
    def native_value(self) -> StateType | date | datetime | Decimal:
        """Return the value reported by the sensor."""
        val = self._data.get(self.entity_description.data_attribute)
        if isinstance(val, (int, float)) and val > 0:
            return utc_from_timestamp(val)
        return None

    async def restart(self) -> None:
        """Restart TrueNAS systen."""
        await self.hass.async_add_executor_job(
            self.coordinator.api.query,
            "system.reboot",
            ["Home Assistant Integration"],
        )

    async def stop(self) -> None:
        """Shutdown TrueNAS systen."""
        await self.hass.async_add_executor_job(
            self.coordinator.api.query,
            "system.shutdown",
            ["Home Assistant Integration"],
        )


# ---------------------------
#   TrueNASDatasetSensor
# ---------------------------
class TrueNASDatasetSensor(TrueNASSensor):
    """Define an TrueNAS Dataset sensor."""

    async def snapshot(self) -> None:
        """Create dataset snapshot."""
        ts = datetime.now().isoformat(sep="_", timespec="microseconds")
        payload = {"dataset": f"{self._data['name']}", "name": f"custom-{ts}"}
        result = await self.hass.async_add_executor_job(
            self.coordinator.api.query,
            "pool.snapshot.create",
            payload,
        )
        if result is None:
            await self.hass.async_add_executor_job(
                self.coordinator.api.query,
                "zfs.snapshot.create",
                payload,
            )


# ---------------------------
#   TrueNASRsyncSensor
# ---------------------------
class TrueNASRsyncSensor(TrueNASSensor):
    """Define a TrueNAS Rsync task sensor."""

    async def start(self) -> None:
        """Run an rsync task."""
        if self._data.get("state") in ("RUNNING", "WAITING"):
            _LOGGER.warning(
                "Rsync task %s (%s) is already running",
                self._data.get("desc"),
                self._data.get("id"),
            )
            return

        await self.hass.async_add_executor_job(
            self.coordinator.api.query,
            "rsynctask.run",
            [self._data["id"]],
        )
        await self.coordinator.async_request_refresh()


# ---------------------------
#   TrueNASReplicationSensor
# ---------------------------
class TrueNASReplicationSensor(TrueNASSensor):
    """Define a TrueNAS Replication task sensor."""

    async def start(self) -> None:
        """Run a replication task."""
        if self._data.get("state") in ("RUNNING", "WAITING"):
            _LOGGER.warning(
                "Replication %s (%s) is already running",
                self._data.get("name"),
                self._data.get("id"),
            )
            return

        await self.hass.async_add_executor_job(
            self.coordinator.api.query,
            "replication.run",
            [self._data["id"]],
        )
        await self.coordinator.async_request_refresh()


# ---------------------------
#   TrueNASCloudsyncSensor
# ---------------------------
class TrueNASCloudsyncSensor(TrueNASSensor):
    """Define an TrueNAS Cloudsync sensor."""

    async def start(self) -> None:
        """Run cloudsync job."""
        jobs = await self.hass.async_add_executor_job(
            self.coordinator.api.query,
            "cloudsync.query",
            [[["id", "=", self._data["id"]]]],
        )
        tmp_job = jobs[0] if isinstance(jobs, list) and jobs else None

        if not isinstance(tmp_job, dict) or "job" not in tmp_job:
            _LOGGER.error(
                "Cloudsync job %s (%s) invalid",
                self._data["description"],
                self._data["id"],
            )
            return
        job_state = tmp_job.get("job")
        state = job_state.get("state") if isinstance(job_state, dict) else None
        if state in ["WAITING", "RUNNING"]:
            _LOGGER.warning(
                "Cloudsync job %s (%s) is already running",
                self._data["description"],
                self._data["id"],
            )
            return

        await self.hass.async_add_executor_job(
            self.coordinator.api.query,
            "cloudsync.sync",
            [self._data["id"]],
        )

    async def stop(self) -> None:
        """Abort cloudsync job."""
        jobs = await self.hass.async_add_executor_job(
            self.coordinator.api.query,
            "cloudsync.query",
            [[["id", "=", self._data["id"]]]],
        )
        tmp_job = jobs[0] if isinstance(jobs, list) and jobs else None

        if not isinstance(tmp_job, dict) or "job" not in tmp_job:
            _LOGGER.error(
                "Cloudsync job %s (%s) invalid",
                self._data["description"],
                self._data["id"],
            )
            return
        job_state = tmp_job.get("job")
        state = job_state.get("state") if isinstance(job_state, dict) else None
        if state not in ["WAITING", "RUNNING"]:
            _LOGGER.warning(
                "Cloudsync job %s (%s) is not running",
                self._data["description"],
                self._data["id"],
            )
            return

        await self.hass.async_add_executor_job(
            self.coordinator.api.query,
            "cloudsync.abort",
            [self._data["id"]],
        )
