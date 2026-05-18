"""TrueNAS Controller."""

from __future__ import annotations

import logging

from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from homeassistant.const import (
    CONF_API_KEY,
    CONF_HOST,
    CONF_NAME,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
)

from .api import TrueNASAPI
from .apiparser import parse_api, utc_from_timestamp
from .const import DEFAULT_USERNAME, DOMAIN

_LOGGER = logging.getLogger(__name__)


# ---------------------------
#   TrueNASControllerData
# ---------------------------
class TrueNASCoordinator(DataUpdateCoordinator[None]):
    """TrueNASCoordinator Class."""

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry):
        """Initialize TrueNASCoordinator."""
        self.hass = hass
        self.config_entry: ConfigEntry = config_entry

        super().__init__(
            self.hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=60),
        )

        self.name = config_entry.data[CONF_NAME]
        self.host = config_entry.data[CONF_HOST]

        self.ds = {
            "interface": {},
            "disk": {},
            "pool": {},
            "dataset": {},
            "system_info": {},
            "service": {},
            "vm": {},
            "cloudsync": {},
            "replication": {},
            "snapshottask": {},
            "app": {},
            "cronjob": {},
        }

        self.api = TrueNASAPI(
            config_entry.data[CONF_HOST],
            config_entry.data.get(CONF_USERNAME, DEFAULT_USERNAME),
            config_entry.data[CONF_API_KEY],
            config_entry.data[CONF_VERIFY_SSL],
        )

        self._systemstats_errored = []
        self._disk_temp_graph = None
        self.datasets_hass_device_id = None
        self.last_updatecheck_update = datetime(1970, 1, 1)

        self._is_virtual = False
        self._version_major = 0
        self._version_minor = 0

    # ---------------------------
    #   connected
    # ---------------------------
    def connected(self) -> bool:
        """Return connected state."""
        return self.api.connected()

    # ---------------------------
    #   _async_update_data
    # ---------------------------
    async def _async_update_data(self):
        """Update TrueNAS data."""
        if not self.api.connected():
            self.api.connect()

        jobs = [
            self.get_systeminfo,
            self.get_systemstats,
            self.get_service,
            self.get_disk,
            self.get_dataset,
            self.get_pool,
            self.get_vm,
            self.get_cloudsync,
            self.get_replication,
            self.get_snapshottask,
            self.get_app,
            self.get_cronjob,
        ]

        for job in jobs:
            if self.api.connected():
                await self.hass.async_add_executor_job(job)

        delta = datetime.now().replace(microsecond=0) - self.last_updatecheck_update
        if self.api.connected() and delta.total_seconds() > 60 * 60 * 12:
            await self.hass.async_add_executor_job(self.get_updatecheck)
            self.last_updatecheck_update = datetime.now().replace(microsecond=0)

        if not self.api.connected():
            raise UpdateFailed("TrueNas Disconnected")

        return self.ds

    # ---------------------------
    #   get_systeminfo
    # ---------------------------
    def get_systeminfo(self) -> None:
        """Get system info from TrueNAS."""
        # Fetch raw data and handle potential None response from API
        raw_system_info = self.api.query("system.info")
        if raw_system_info is None:
            raw_system_info = {}

        self.ds["system_info"] = parse_api(
            data=self.ds["system_info"],
            source=raw_system_info,
            vals=[
                {"name": "version", "default": "unknown"},
                {"name": "hostname", "default": "unknown"},
                {"name": "uptime_seconds", "default": 0},
                {"name": "system_serial", "default": "unknown"},
                {"name": "system_product", "default": "unknown"},
                {"name": "system_manufacturer", "default": "unknown"},
                {"name": "physmem", "default": 0},
            ],
            ensure_vals=[
                {"name": "uptimeEpoch", "default": 0},
                {"name": "cpu_temperature", "default": 0.0},
                {"name": "load_shortterm", "default": 0.0},
                {"name": "load_midterm", "default": 0.0},
                {"name": "load_longterm", "default": 0.0},
                {"name": "cpu_interrupt", "default": 0.0},
                {"name": "cpu_system", "default": 0.0},
                {"name": "cpu_user", "default": 0.0},
                {"name": "cpu_nice", "default": 0.0},
                {"name": "cpu_idle", "default": 0.0},
                {"name": "cpu_usage", "default": 0.0},
                {"name": "cache_size-arc_value", "default": 0.0},
                {"name": "memory-used_value", "default": 0.0},
                {"name": "memory-free_value", "default": 0.0},
                {"name": "memory-cached_value", "default": 0.0},
                {"name": "memory-buffered_value", "default": 0.0},
                {"name": "memory-total_value", "default": 0.0},
                {"name": "memory-usage_percent", "default": 0},
                {"name": "update_available", "type": "bool", "default": False},
                {"name": "update_progress", "default": 0},
                {"name": "update_jobid", "default": 0},
                {"name": "update_state", "default": "unknown"},
                {"name": "update_version", "default": "unknown"},
            ],
        )
        
        if not self.api.connected():
            return

        # Ensure update_version is not unknown if no update is available
        if not self.ds["system_info"]["update_available"]:
            self.ds["system_info"]["update_version"] = self.ds["system_info"]["version"]

        # Handle running update jobs
        if self.ds["system_info"]["update_jobid"]:
            self.ds["system_info"] = parse_api(
                data=self.ds["system_info"],
                source=self.api.query(
                    "core.get_jobs",
                    params=[[["id", "=", self.ds["system_info"]["update_jobid"]]]],
                ),
                vals=[
                    {
                        "name": "update_progress",
                        "source": "progress/percent",
                        "default": 0,
                    },
                    {
                        "name": "update_state",
                        "source": "state",
                        "default": "unknown",
                    },
                ],
            )
            if not self.api.connected():
                return

            if (
                self.ds["system_info"]["update_state"] != "RUNNING"
                or not self.ds["system_info"]["update_available"]
            ):
                self.ds["system_info"]["update_progress"] = 0
                self.ds["system_info"]["update_jobid"] = 0
                self.ds["system_info"]["update_state"] = "unknown"

        # Parsing logic to prevent "0.0.0" display
        version_str = str(self.ds["system_info"].get("version", "25.10.0"))
        clean_version = version_str.replace("TrueNAS-", "").replace("SCALE-", "")
        version_parts = clean_version.split(".")

        try:
            self._version_major = int(version_parts[0]) if len(version_parts) > 0 else 25
            self._version_minor = int(version_parts[1]) if len(version_parts) > 1 else 10
        except (ValueError, IndexError):
            self._version_major, self._version_minor = 25, 10

        # Virtualization check
        self._is_virtual = self.ds["system_info"]["system_manufacturer"] in [
            "QEMU",
            "VMware, Inc.",
            "Microsoft Corporation",
            "Xen",
        ] or self.ds["system_info"]["system_product"] in [
            "VirtualBox",
            "Virtual Machine",
        ]

        # Uptime calculation
        if self.ds["system_info"]["uptime_seconds"] > 0:
            from datetime import datetime, timedelta
            from homeassistant.util.dt import utc_from_timestamp
            now = datetime.now().replace(microsecond=0)
            uptime_tm = datetime.timestamp(
                now - timedelta(seconds=int(self.ds["system_info"]["uptime_seconds"]))
            )
            self.ds["system_info"]["uptimeEpoch"] = utc_from_timestamp(uptime_tm)

        # Network interface query
        self.ds["interface"] = parse_api(
            data=self.ds["interface"],
            source=self.api.query("interface.query"),
            key="id",
            vals=[
                {"name": "id", "default": "unknown"},
                {"name": "name", "default": "unknown"},
                {"name": "description", "default": "unknown"},
                {"name": "mtu", "default": "unknown"},
                {
                    "name": "link_state",
                    "source": "state/link_state",
                    "default": "unknown",
                },
                {
                    "name": "active_media_type",
                    "source": "state/active_media_type",
                    "default": "unknown",
                },
                {
                    "name": "active_media_subtype",
                    "source": "state/active_media_subtype",
                    "default": "unknown",
                },
                {
                    "name": "link_address",
                    "source": "state/link_address",
                    "default": "unknown",
                },
            ],
            ensure_vals=[
                {"name": "rx", "default": 0},
                {"name": "tx", "default": 0},
            ],
        )

        # Trigger update check specifically for 25.10
        self.get_updatecheck()

    # ---------------------------
    #   get_updatecheck
    # ---------------------------
    def get_updatecheck(self) -> None:
        """Check for updates using the new 25.10/26.04 API structure."""
        update_data = self.api.query("update.status")
        
        # Initialize default values to prevent invalid entity IDs
        self.ds["system_info"]["update_available"] = False
        self.ds["system_info"]["update_status"] = "IDLE"
        if "update_version" not in self.ds["system_info"] or self.ds["system_info"]["update_version"] in [None, "unknown", ""]:
            self.ds["system_info"]["update_version"] = self.ds["system_info"].get("version", "up-to-date")

        # If API returns nothing, we already set defaults above, so just return
        if not update_data or not isinstance(update_data, dict):
            return

        # According to your PS-test, the data is in: result -> status -> new_version
        # Since api.py extracts 'result', we access 'status' directly
        status_obj = update_data.get("status")
        if isinstance(status_obj, dict):
            new_version_obj = status_obj.get("new_version")
            
            # Check if new_version exists and contains a version string
            if isinstance(new_version_obj, dict) and new_version_obj.get("version"):
                self.ds["system_info"]["update_status"] = "AVAILABLE"
                self.ds["system_info"]["update_version"] = new_version_obj["version"]
                self.ds["system_info"]["update_available"] = True
                
                # ADD EXTRA INFO AS ATTRIBUTES
                manifest = new_version_obj.get("manifest", {})
                self.ds["system_info"]["update_date"] = manifest.get("date")
                self.ds["system_info"]["update_profile"] = manifest.get("profile")
                self.ds["system_info"]["update_train"] = manifest.get("train")
                self.ds["system_info"]["update_filename"] = manifest.get("filename")
                
                _LOGGER.debug("TrueNAS Update found: %s", new_version_obj["version"])
            else:
                # No new version in the status object, keep current version as update_version
                self.ds["system_info"]["update_version"] = self.ds["system_info"].get("version", "up-to-date")

                self.ds["system_info"]["update_date"] = None
                self.ds["system_info"]["update_profile"] = None
                self.ds["system_info"]["update_train"] = None

        # Final safety check: ensure update_available reflects the status
        self.ds["system_info"]["update_available"] = (
            self.ds["system_info"].get("update_status") == "AVAILABLE"
        )

    # ---------------------------
    #   get_systemstats
    # ---------------------------
    def get_systemstats(self) -> None:
        """Get system statistics."""
        report_epoch = int(datetime.now().replace(microsecond=0).timestamp())
        graph_names = ["load", "cputemp", "cpu", "arcsize", "memory"]

        if self.ds["interface"]:
            graph_names.append("interface")

        if self._is_virtual:
            graph_names.remove("cputemp")

        graph_names = [
            graph_name
            for graph_name in graph_names
            if graph_name not in self._systemstats_errored
        ]

        if not graph_names:
            return

        graph_query = {
            "start": report_epoch - 30,
            "end": report_epoch - 90,
            "aggregate": True,
        }
        reporting_path = "reporting.netdata_graph"
        tmp_graph = []
        failed_graphs = []

        for graph_name in graph_names:
            graph_data = self.api.query(
                reporting_path,
                params=[graph_name, graph_query],
            )
            if isinstance(graph_data, list):
                tmp_graph.extend(graph_data)
            else:
                failed_graphs.append(graph_name)

        if failed_graphs:
            for graph_name in failed_graphs:
                if graph_name not in self._systemstats_errored:
                    self._systemstats_errored.append(graph_name)
            _LOGGER.warning(
                "TrueNAS %s failed to fetch graphs: %s",
                self.host,
                failed_graphs,
            )

        if not tmp_graph:
            return

        for i in range(len(tmp_graph)):
            if "name" not in tmp_graph[i]:
                continue

            # CPU temperature
            if tmp_graph[i]["name"] == "cputemp":
                if "aggregations" in tmp_graph[i]:
                    self.ds["system_info"]["cpu_temperature"] = round(
                        max(tmp_graph[i]["aggregations"]["mean"].values()), 2
                    )
                else:
                    self.ds["system_info"]["cpu_temperature"] = 0.0

            # CPU load
            if tmp_graph[i]["name"] == "load":
                tmp_arr = ("shortterm", "midterm", "longterm")
                self._systemstats_process(tmp_arr, tmp_graph[i], "load")

            # CPU usage
            if tmp_graph[i]["name"] == "cpu":
                tmp_arr = "cpu"
                self._systemstats_process(tmp_arr, tmp_graph[i], "cpu")
                self.ds["system_info"]["cpu_usage"] = round(
                    self.ds["system_info"]["cpu_cpu"], 2
                )

            # Interface
            if tmp_graph[i]["name"] == "interface":
                tmp_etc = tmp_graph[i]["identifier"]
                if tmp_etc in self.ds["interface"]:
                    tmp_graph[i]["legend"] = [
                        tmp.replace("received", "rx") for tmp in tmp_graph[i]["legend"]
                    ]
                    tmp_graph[i]["legend"] = [
                        tmp.replace("sent", "tx") for tmp in tmp_graph[i]["legend"]
                    ]
                    tmp_graph[i]["aggregations"]["mean"] = {
                        k.replace("received", "rx"): v
                        for k, v in tmp_graph[i]["aggregations"]["mean"].items()
                    }
                    tmp_graph[i]["aggregations"]["mean"] = {
                        k.replace("sent", "tx"): v
                        for k, v in tmp_graph[i]["aggregations"]["mean"].items()
                    }

                    tmp_arr = ("rx", "tx")
                    if "aggregations" in tmp_graph[i]:
                        for e in range(len(tmp_graph[i]["legend"])):
                            tmp_var = tmp_graph[i]["legend"][e]
                            if tmp_var in tmp_arr:
                                tmp_val = (
                                    tmp_graph[i]["aggregations"]["mean"][tmp_var] or 0.0
                                    if tmp_var in tmp_graph[i]["aggregations"]["mean"]
                                    else 0.0
                                )
                                self.ds["interface"][tmp_etc][tmp_var] = round(
                                    (tmp_val * 0.12207), 2
                                )

                    else:
                        for tmp_load in tmp_arr:
                            self.ds["interface"][tmp_etc][tmp_load] = 0.0

            # memory
            if tmp_graph[i]["name"] == "memory":
                tmp_arr = "available"
                self.ds["system_info"]["memory-total_value"] = round(
                    self.ds["system_info"]["physmem"]
                )

                self._systemstats_process(tmp_arr, tmp_graph[i], "memory")
                if self.ds["system_info"]["memory-total_value"] > 0:
                    self.ds["system_info"]["memory-usage_percent"] = round(
                        100
                        * (
                            float(self.ds["system_info"]["memory-total_value"])
                            - float(self.ds["system_info"]["memory-free_value"])
                        )
                        / float(self.ds["system_info"]["memory-total_value"])
                    )

            # arcsize
            if tmp_graph[i]["name"] == "arcsize":
                tmp_arr = "arc_size"
                self._systemstats_process(tmp_arr, tmp_graph[i], "arcsize")

    # ---------------------------
    #   _systemstats_process
    # ---------------------------
    def _systemstats_process(self, arr, graph, t) -> None:
        if "aggregations" in graph:
            for e in range(len(graph["legend"])):
                tmp_var = graph["legend"][e]
                if tmp_var in arr:
                    e = tmp_var

                    tmp_val = graph["aggregations"]["mean"][e] or 0.0
                    if t == "memory":
                        if tmp_var == "available":
                            self.ds["system_info"]["memory-free_value"] = round(tmp_val)
                    elif t == "cpu":
                        self.ds["system_info"][f"cpu_{tmp_var}"] = round(tmp_val, 2)
                    elif t == "load":
                        self.ds["system_info"][f"load_{tmp_var}"] = round(tmp_val, 2)
                    elif t == "arcsize":
                        self.ds["system_info"]["cache_size-arc_value"] = round(
                            tmp_val, 2
                        )
                    else:
                        self.ds["system_info"][tmp_var] = round(tmp_val, 2)
        else:
            for tmp_load in arr:
                if t == "cpu":
                    self.ds["system_info"][f"cpu_{tmp_load}"] = 0.0
                else:
                    self.ds["system_info"][tmp_load] = 0.0

    # ---------------------------
    #   get_service
    # ---------------------------
    def get_service(self) -> None:
        """Get service info from TrueNAS."""
        self.ds["service"] = parse_api(
            data=self.ds["service"],
            source=self.api.query("service.query"),
            key="id",
            vals=[
                {"name": "id", "default": 0},
                {"name": "service", "default": "unknown"},
                {"name": "enable", "type": "bool", "default": False},
                {"name": "state", "default": "unknown"},
            ],
            ensure_vals=[
                {"name": "running", "type": "bool", "default": False},
            ],
        )

        for uid, vals in self.ds["service"].items():
            self.ds["service"][uid]["running"] = vals["state"] == "RUNNING"

    # ---------------------------
    #   get_pool
    # ---------------------------
    def get_pool(self) -> None:
        """Get pools from TrueNAS."""
        self.ds["pool"] = parse_api(
            data=self.ds["pool"],
            source=self.api.query("pool.query"),
            key="guid",
            vals=[
                {"name": "guid", "default": 0},
                {"name": "id", "default": 0},
                {"name": "name", "default": "unknown"},
                {"name": "path", "default": "unknown"},
                {"name": "status", "default": "unknown"},
                {"name": "healthy", "type": "bool", "default": False},
                {"name": "is_decrypted", "type": "bool", "default": False},
                {"name": "size", "default": 0},
                {"name": "allocated", "default": 0},
                {"name": "free", "default": 0},
                {
                    "name": "autotrim",
                    "source": "autotrim/parsed",
                    "type": "bool",
                    "default": False,
                },
                {
                    "name": "scan_function",
                    "source": "scan/function",
                    "default": "unknown",
                },
                {"name": "scrub_state", "source": "scan/state", "default": "unknown"},
                {
                    "name": "scrub_start",
                    "source": "scan/start_time/$date",
                    "default": 0,
                    "convert": "utc_from_timestamp",
                },
                {
                    "name": "scrub_end",
                    "source": "scan/end_time/$date",
                    "default": 0,
                    "convert": "utc_from_timestamp",
                },
                {
                    "name": "scrub_secs_left",
                    "source": "scan/total_secs_left",
                    "default": 0,
                },
            ],
            ensure_vals=[
                {"name": "available", "default": 0.0},
                {"name": "total", "default": 0.0},
                {"name": "usage", "default": 0.0},
            ],
        )
        if not self.api.connected():
            return

        # Process pools
        tmp_dataset_available = {}
        tmp_dataset_total = {}
        for uid, vals in self.ds["dataset"].items():
            tmp_dataset_available[self.ds["dataset"][uid]["mountpoint"]] = vals[
                "available"
            ]

            tmp_dataset_total[self.ds["dataset"][uid]["mountpoint"]] = (
                vals["available"] + vals["used"]
            )

        for uid, vals in self.ds["pool"].items():
            if vals.get("free"):
                self.ds["pool"][uid]["available"] = vals["free"]

            if vals.get("size"):
                self.ds["pool"][uid]["total"] = vals["size"]
            elif vals.get("allocated") or vals.get("free"):
                self.ds["pool"][uid]["total"] = vals.get("allocated", 0) + vals.get(
                    "free", 0
                )

            if vals["path"] in tmp_dataset_available:
                if not self.ds["pool"][uid]["available"]:
                    self.ds["pool"][uid]["available"] = tmp_dataset_available[
                        vals["path"]
                    ]

            if vals["path"] in tmp_dataset_total:
                if not self.ds["pool"][uid]["total"]:
                    self.ds["pool"][uid]["total"] = tmp_dataset_total[vals["path"]]

            if self.ds["pool"][uid]["total"] > 0:
                self.ds["pool"][uid]["usage"] = round(
                    (
                        (
                            self.ds["pool"][uid]["total"]
                            - self.ds["pool"][uid]["available"]
                        )
                        / self.ds["pool"][uid]["total"]
                    )
                    * 100
                )
            else:
                self.ds["pool"][uid]["usage"] = 0

    # ---------------------------
    #   get_dataset
    # ---------------------------
    def get_dataset(self) -> None:
        """Get datasets from TrueNAS."""
        self.ds["dataset"] = parse_api(
            data={},
            source=self.api.query("pool.dataset.query"),
            key="id",
            vals=[
                {"name": "id", "default": "unknown"},
                {"name": "type", "default": "unknown"},
                {"name": "name", "default": "unknown"},
                {"name": "pool", "default": "unknown"},
                {"name": "mountpoint", "default": "unknown"},
                {"name": "comments", "source": "comments/parsed", "default": ""},
                {
                    "name": "deduplication",
                    "source": "deduplication/parsed",
                    "type": "bool",
                    "default": False,
                },
                {
                    "name": "atime",
                    "source": "atime/parsed",
                    "type": "bool",
                    "default": False,
                },
                {
                    "name": "casesensitivity",
                    "source": "casesensitivity/parsed",
                    "default": "unknown",
                },
                {"name": "checksum", "source": "checksum/parsed", "default": "unknown"},
                {
                    "name": "exec",
                    "source": "exec/parsed",
                    "type": "bool",
                    "default": False,
                },
                {"name": "sync", "source": "sync/parsed", "default": "unknown"},
                {
                    "name": "compression",
                    "source": "compression/parsed",
                    "default": "unknown",
                },
                {
                    "name": "compressratio",
                    "source": "compressratio/parsed",
                    "default": "unknown",
                },
                {"name": "quota", "source": "quota/parsed", "default": "unknown"},
                {"name": "copies", "source": "copies/parsed", "default": 0},
                {
                    "name": "readonly",
                    "source": "readonly/parsed",
                    "type": "bool",
                    "default": False,
                },
                {"name": "recordsize", "source": "recordsize/parsed", "default": 0},
                {
                    "name": "encryption_algorithm",
                    "source": "encryption_algorithm/parsed",
                    "default": "unknown",
                },
                {"name": "used", "source": "used/parsed", "default": 0},
                {"name": "available", "source": "available/parsed", "default": 0},
            ],
        )

        if len(self.ds["dataset"]) == 0:
            return

        # entities_to_be_removed = []
        # if not self.datasets_hass_device_id:
        #     device_registry = dr.async_get(self.hass)
        #     for device in device_registry.devices.values():
        #         if (
        #             self.config_entry.entry_id in device.config_entries
        #             and device.name.endswith("Datasets")
        #         ):
        #             self.datasets_hass_device_id = device.id
        #             _LOGGER.debug(f"datasets device: {device.name}")
        #
        #     if not self.datasets_hass_device_id:
        #         return
        #
        # _LOGGER.debug(f"datasets_hass_device_id: {self.datasets_hass_device_id}")
        # entity_registry = er.async_get(self.hass)
        # entity_entries = async_entries_for_config_entry(
        #     entity_registry, self.config_entry.entry_id
        # )
        # for entity in entity_entries:
        #     if (
        #         entity.device_id == self.datasets_hass_device_id
        #         and entity.unique_id.removeprefix(f"{self.name.lower()}-dataset-")
        #         not in map(
        #             lambda x: str.replace(x, "/", "_"),
        #             map(str.lower, self.ds["dataset"].keys()),
        #         )
        #     ):
        #         _LOGGER.debug(f"dataset to be removed: {entity.unique_id}")
        #         entities_to_be_removed.append(entity.entity_id)
        #
        # for entity_id in entities_to_be_removed:
        #     entity_registry.async_remove(entity_id)

    # ---------------------------
    #   get_disk
    # ---------------------------
    def get_disk(self) -> None:
        """Get disks from TrueNAS."""
        self.ds["disk"] = parse_api(
            data=self.ds["disk"],
            source=self.api.query("disk.query"),
            key="identifier",
            vals=[
                {"name": "name", "default": "unknown"},
                {"name": "devname", "default": "unknown"},
                {"name": "serial", "default": "unknown"},
                {"name": "size", "default": "unknown"},
                {"name": "hddstandby", "default": "unknown"},
                {"name": "hddstandby_force", "type": "bool", "default": False},
                {"name": "advpowermgmt", "default": "unknown"},
                {"name": "acousticlevel", "default": "unknown"},
                {"name": "togglesmart", "type": "bool", "default": False},
                {"name": "model", "default": "unknown"},
                {"name": "rotationrate", "default": "unknown"},
                {"name": "type", "default": "unknown"},
                {"name": "zfs_guid", "default": "unknown"},
                {"name": "identifier", "default": "unknown"},
            ],
            ensure_vals=[
                {"name": "temperature", "default": 0},
            ],
        )

        # Get disk temperatures
        netdata_temps = self._disk_temps_from_netdata()
        if netdata_temps:
            disk_map = {}
            for uid, vals in self.ds["disk"].items():
                for key in (
                    vals.get("name"),
                    vals.get("devname"),
                    vals.get("identifier"),
                ):
                    if key:
                        disk_map[key] = uid

            for disk_name, temp in netdata_temps.items():
                if disk_name in disk_map:
                    self.ds["disk"][disk_map[disk_name]]["temperature"] = round(temp, 2)
            return

        temps = self.api.query(
            "disk.temperatures",
            params={},
        )

        if isinstance(temps, dict) and "error" not in temps:
            for uid, vals in self.ds["disk"].items():
                if vals["name"] in temps:  # looks for devname here
                    self.ds["disk"][uid]["temperature"] = temps[vals["name"]]
                    # return devname temp to uid disk
                    # I feel like this will break in the future when TrueNAS updates to a more sensible system. Currently their own long term stats are broken by the changing devnames.

    def _disk_temps_from_netdata(self) -> dict[str, float] | None:
        """Return disk temperatures from netdata graphs when available."""
        if self._disk_temp_graph is None:
            graphs = self.api.query("reporting.netdata_graphs")
            graph_name = ""
            if isinstance(graphs, list):
                for graph in graphs:
                    name = str(graph.get("name", ""))
                    title = str(graph.get("title", "")).lower()
                    vertical = str(graph.get("vertical_label", "")).lower()
                    if "disk" in name or "disk" in title:
                        if "temp" in name or "temp" in title or "celsius" in vertical:
                            graph_name = name
                            break
            self._disk_temp_graph = graph_name

        if not self._disk_temp_graph:
            return None

        report_epoch = int(datetime.now().replace(microsecond=0).timestamp())
        graph_query = {
            "start": report_epoch - 30,
            "end": report_epoch - 90,
            "aggregate": True,
        }
        graph_data = self.api.query(
            "reporting.netdata_graph",
            params=[self._disk_temp_graph, graph_query],
        )
        if not isinstance(graph_data, list):
            return None

        temps = {}
        for entry in graph_data:
            identifier = entry.get("identifier")
            mean = entry.get("aggregations", {}).get("mean", {})
            if identifier and isinstance(mean, dict) and mean:
                temps[str(identifier)] = max(mean.values())

        return temps or None

    # ---------------------------
    #   get_vm
    # ---------------------------
    def get_vm(self) -> None:
        """Get VMs from TrueNAS."""
        self.ds["vm"] = parse_api(
            data=self.ds["vm"],
            source=self.api.query("vm.query"),
            key="id",
            vals=[
                {"name": "id", "default": 0},
                {"name": "name", "default": "unknown"},
                {"name": "type", "default": "unknown"},
                {"name": "cpu", "source": "vcpus", "default": 0},
                {"name": "memory", "default": 0},
                {"name": "autostart", "type": "bool", "default": False},
                {"name": "image", "source": "description", "default": "unknown"},
                {"name": "status", "source": "status/state", "default": "unknown"},
            ],
            ensure_vals=[
                {"name": "running", "type": "bool", "default": False},
            ],
        )

        for uid, vals in self.ds["vm"].items():
            self.ds["vm"][uid]["memory"] = round(vals["memory"] / 1024)
            self.ds["vm"][uid]["running"] = vals["status"] == "RUNNING"

    # ---------------------------
    #   get_cloudsync
    # ---------------------------
    def get_cloudsync(self) -> None:
        """Get cloudsync from TrueNAS."""
        self.ds["cloudsync"] = parse_api(
            data=self.ds["cloudsync"],
            source=self.api.query("cloudsync.query"),
            key="id",
            vals=[
                {"name": "id", "default": "unknown"},
                {"name": "description", "default": "unknown"},
                {"name": "direction", "default": "unknown"},
                {"name": "path", "default": "unknown"},
                {"name": "enabled", "type": "bool", "default": False},
                {"name": "transfer_mode", "default": "unknown"},
                {"name": "snapshot", "type": "bool", "default": False},
                {"name": "state", "source": "job/state", "default": "unknown"},
                {
                    "name": "time_started",
                    "source": "job/time_started/$date",
                    "default": 0,
                    "convert": "utc_from_timestamp",
                },
                {
                    "name": "time_finished",
                    "source": "job/time_finished/$date",
                    "default": 0,
                    "convert": "utc_from_timestamp",
                },
                {"name": "job_percent", "source": "job/progress/percent", "default": 0},
                {
                    "name": "job_description",
                    "source": "job/progress/description",
                    "default": "unknown",
                },
            ],
        )

    # ---------------------------
    #   get_replication
    # ---------------------------
    def get_replication(self) -> None:
        """Get replication from TrueNAS."""
        self.ds["replication"] = parse_api(
            data=self.ds["replication"],
            source=self.api.query("replication.query"),
            key="id",
            vals=[
                {"name": "id", "default": 0},
                {"name": "name", "default": "unknown"},
                {"name": "source_datasets", "default": "unknown"},
                {"name": "target_dataset", "default": "unknown"},
                {"name": "recursive", "type": "bool", "default": False},
                {"name": "enabled", "type": "bool", "default": False},
                {"name": "direction", "default": "unknown"},
                {"name": "transport", "default": "unknown"},
                {"name": "auto", "type": "bool", "default": False},
                {"name": "retention_policy", "default": "unknown"},
                {"name": "state", "source": "job/state", "default": "unknown"},
                {
                    "name": "time_started",
                    "source": "job/time_started/$date",
                    "default": 0,
                    "convert": "utc_from_timestamp",
                },
                {
                    "name": "time_finished",
                    "source": "job/time_finished/$date",
                    "default": 0,
                    "convert": "utc_from_timestamp",
                },
                {"name": "job_percent", "source": "job/progress/percent", "default": 0},
                {
                    "name": "job_description",
                    "source": "job/progress/description",
                    "default": "unknown",
                },
            ],
        )

    # ---------------------------
    #   get_snapshottask
    # ---------------------------
    def get_snapshottask(self) -> None:
        """Get replication from TrueNAS."""
        self.ds["snapshottask"] = parse_api(
            data=self.ds["snapshottask"],
            source=self.api.query("pool.snapshottask.query"),
            key="id",
            vals=[
                {"name": "id", "default": 0},
                {"name": "dataset", "default": "unknown"},
                {"name": "recursive", "type": "bool", "default": False},
                {"name": "lifetime_value", "default": 0},
                {"name": "lifetime_unit", "default": "unknown"},
                {"name": "enabled", "type": "bool", "default": False},
                {"name": "naming_schema", "default": "unknown"},
                {"name": "allow_empty", "type": "bool", "default": False},
                {"name": "vmware_sync", "type": "bool", "default": False},
                {"name": "state", "source": "state/state", "default": "unknown"},
                {
                    "name": "datetime",
                    "source": "state/datetime/$date",
                    "default": 0,
                    "convert": "utc_from_timestamp",
                },
            ],
        )

    # ---------------------------
    #   get_app
    # ---------------------------
    def get_app(self) -> None:
        """Get Apps from TrueNAS."""
        self.ds["app"] = parse_api(
            data=self.ds["app"],
            source=self.api.query("app.query"),
            key="id",
            vals=[
                {"name": "id", "default": 0},
                {"name": "name", "default": "unknown"},
                {"name": "human_version", "default": "unknown"},
                {"name": "version", "default": "unknown"},
                {"name": "latest_version", "default": "unknown"},
                {"name": "custom_app", "type": "bool", "default": False},
                {
                    "name": "update_available",
                    "source": "upgrade_available",
                    "type": "bool",
                    "default": False,
                },
                {
                    "name": "image_updates_available",
                    "type": "bool",
                    "default": False,
                },
                {
                    "name": "portal",
                    "source": "portals/Web UI",
                    "default": "unknown",
                },
                {"name": "state", "default": "unknown"},
            ],
            ensure_vals=[
                {"name": "running", "type": "bool", "default": False},
            ],
        )

        for uid, vals in self.ds["app"].items():
            self.ds["app"][uid]["running"] = vals["state"] == "RUNNING"

    # ---------------------------
    #   get_cronjob
    # ---------------------------
    def get_cronjob(self) -> None:
        """Get cronjobs from TrueNAS."""
        self.ds["cronjob"] = parse_api(
            data=self.ds["cronjob"],
            source=self.api.query("cronjob.query"),
            key="id",
            vals=[
                {"name": "id", "default": 0},
                {"name": "enabled", "type": "bool", "default": False},
                {"name": "command", "default": "unknown"},
                {"name": "description", "default": ""},
                {"name": "user", "default": "unknown"},
                {"name": "schedule", "default": {}},
                {"name": "stdout", "type": "bool", "default": False},
                {"name": "stderr", "type": "bool", "default": False},
            ],
            ensure_vals=[
                {"name": "display_name", "default": ""},
            ],
        )

        for uid, vals in self.ds["cronjob"].items():
            description = (vals.get("description") or "").strip()
            command = (vals.get("command") or "").strip()
            if description:
                display_name = description
            elif command:
                display_name = command
            else:
                display_name = f"Cronjob {uid}"

            self.ds["cronjob"][uid]["display_name"] = display_name
