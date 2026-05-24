"""TrueNAS Controller."""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import UTC, datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_API_KEY,
    CONF_HOST,
    CONF_NAME,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import TrueNASAPI
from .apiparser import parse_api
from .const import DEFAULT_USERNAME, DOMAIN

_LOGGER = logging.getLogger(__name__)

# Conversion factor: kilobits per second to kibibytes per second
# (1000 / 8192 = ~0.12207)
KILOBITS_TO_KIBIBYTES_FACTOR = 0.12207


# ---------------------------
#   TrueNASControllerData
# ---------------------------
class TrueNASCoordinator(DataUpdateCoordinator[dict[str, Any]]):
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
            "alerts": {
                "count": 0,
                "messages": [],
                "critical": 0,
                "warning": 0,
                "info": 0,
            },
        }

        self.api = TrueNASAPI(
            config_entry.data[CONF_HOST],
            config_entry.data.get(CONF_USERNAME, DEFAULT_USERNAME),
            config_entry.data[CONF_API_KEY],
            config_entry.data[CONF_VERIFY_SSL],
        )

        self._systemstats_errored: dict[str, datetime] = {}
        self._systemstats_error_cooldown = timedelta(minutes=10)
        self._disk_temp_graph = None
        self.datasets_hass_device_id = None
        self.last_updatecheck_update = datetime(1970, 1, 1, tzinfo=UTC)

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
        # Migrate legacy `cronjob_skip_disabled` stored in data to options
        if (
            "cronjob_skip_disabled" in self.config_entry.data
            and "cronjob_skip_disabled" not in self.config_entry.options
        ):
            new_options = {
                **self.config_entry.options,
                "cronjob_skip_disabled": self.config_entry.data[
                    "cronjob_skip_disabled"
                ],
            }
            self.hass.config_entries.async_update_entry(
                self.config_entry,
                options=new_options,
            )

        if not self.api.connected():
            try:
                await self.hass.async_add_executor_job(self.api.connect)
            except Exception as e:
                raise UpdateFailed(f"Error connecting to TrueNAS: {e}") from e

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
            self.get_alerts,
            self.get_smb,
        ]

        if self.api.connected():

            async def _run_job(job):
                try:
                    await self.hass.async_add_executor_job(job)
                except Exception as err:
                    _LOGGER.error(
                        "Error running TrueNAS job %s: %s",
                        getattr(job, "__name__", job),
                        err,
                    )

            await asyncio.gather(*(_run_job(job) for job in jobs))

        now = datetime.now(UTC).replace(microsecond=0)
        delta = now - self.last_updatecheck_update
        if self.api.connected() and delta.total_seconds() > 60 * 60 * 12:
            await self.hass.async_add_executor_job(self.get_updatecheck)
            self.last_updatecheck_update = now

        if not self.api.connected():
            raise UpdateFailed("TrueNAS disconnected")

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
                {"name": "smb_connections", "default": 0},
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

        # Parsing logic to prevent "0.0.0" display and avoid misrepresenting
        # the system version on malformed or missing input.
        version_str = str(self.ds["system_info"].get("version", "") or "")
        clean_version = version_str.replace("TrueNAS-", "").replace("SCALE-", "")

        self._version_major = 0
        self._version_minor = 0

        if match := re.search(r"(\d+)\.(\d+)", clean_version):
            self._version_major = int(match[1])
            self._version_minor = int(match[2])
        elif clean_version:
            _LOGGER.debug(
                "Failed to parse TrueNAS version from string: %s", version_str
            )

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
            now = datetime.now(UTC).replace(microsecond=0)
            now_epoch = int(now.timestamp())
            self.ds["system_info"]["uptimeEpoch"] = now_epoch - int(
                self.ds["system_info"]["uptime_seconds"]
            )

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

    # ---------------------------
    #   get_updatecheck
    # ---------------------------
    def get_updatecheck(self) -> None:
        """Check for updates using the new 25.10/26.04 API structure."""
        update_data = self.api.query("update.status")

        # Initialize default values to prevent invalid entity IDs
        self.ds.setdefault("system_info", {})
        self.ds["system_info"].setdefault("update_available", False)
        self.ds["system_info"].setdefault("update_status", "IDLE")
        if "update_version" not in self.ds["system_info"] or self.ds["system_info"][
            "update_version"
        ] in [None, "unknown", ""]:
            self.ds["system_info"]["update_version"] = self.ds["system_info"].get(
                "version", "up-to-date"
            )

        # If API returns nothing, we already set defaults above, but we must clear
        # any potentially stale update metadata before returning.
        if not update_data or not isinstance(update_data, dict):
            _LOGGER.warning(
                "TrueNAS update status returned malformed or empty data: %s",
                update_data,
            )
            self._reset_update_status(status="IDLE")
            return

        # According to your PS-test, the data is in: result -> status -> new_version
        # Since api.py extracts 'result', we access 'status' directly
        status_obj = update_data.get("status")

        if isinstance(status_obj, dict):
            raw_status = status_obj.get("state") or status_obj.get("status")
            if isinstance(raw_status, str):
                self.ds["system_info"]["update_status"] = raw_status

        new_version_obj = (
            status_obj.get("new_version") if isinstance(status_obj, dict) else None
        )

        # Check if new_version exists and contains a version string
        if isinstance(new_version_obj, dict) and new_version_obj.get("version"):
            self._updatecheck_process_new_version(new_version_obj)
        else:
            # No new version in status object, keep current
            self._reset_update_status()

    def _updatecheck_process_new_version(self, new_version_obj: dict) -> None:
        """Process new version data for updatecheck."""
        self.ds["system_info"]["update_version"] = new_version_obj["version"]
        self.ds["system_info"]["update_available"] = True

        # ADD EXTRA INFO AS ATTRIBUTES
        manifest = new_version_obj.get("manifest", {})
        self.ds["system_info"]["update_date"] = manifest.get("date")
        self.ds["system_info"]["update_profile"] = manifest.get("profile")
        self.ds["system_info"]["update_train"] = manifest.get("train")
        self.ds["system_info"]["update_filename"] = manifest.get("filename")

        _LOGGER.debug("TrueNAS Update found: %s", new_version_obj["version"])

    def _reset_update_status(self, status: str | None = None) -> None:
        """Reset update status to idle/up-to-date."""
        self.ds["system_info"]["update_available"] = False
        if status is not None:
            self.ds["system_info"]["update_status"] = status
        self.ds["system_info"]["update_version"] = self.ds["system_info"].get(
            "version", "up-to-date"
        )
        self.ds["system_info"]["update_date"] = None
        self.ds["system_info"]["update_profile"] = None
        self.ds["system_info"]["update_train"] = None
        self.ds["system_info"]["update_filename"] = None

    # ---------------------------
    #   get_systemstats
    # ---------------------------
    def get_systemstats(self) -> None:
        """Get system statistics."""
        report_epoch = int(datetime.now(UTC).replace(microsecond=0).timestamp())
        graph_names = ["load", "cputemp", "cpu", "arcsize", "memory"]

        if self.ds["interface"]:
            graph_names.append("interface")

        if self._is_virtual and "cputemp" in graph_names:
            graph_names.remove("cputemp")

        now = datetime.now(UTC)
        self._systemstats_errored = {
            name: ts
            for name, ts in self._systemstats_errored.items()
            if now - ts < self._systemstats_error_cooldown
        }

        graph_names = [
            graph_name
            for graph_name in graph_names
            if graph_name not in self._systemstats_errored
        ]

        if not graph_names:
            return

        graph_query = {
            "start": report_epoch - 90,
            "end": report_epoch - 30,
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

        # Only log when a graph transitions into a failed state (i.e. was not
        # already in _systemstats_errored), to avoid spamming the log on every
        # coordinator update while the graph remains broken.
        if failed_graphs:
            newly_failed_graphs: list[str] = []
            now = datetime.now(UTC)
            for graph_name in failed_graphs:
                if graph_name not in self._systemstats_errored:
                    newly_failed_graphs.append(graph_name)
                self._systemstats_errored[graph_name] = now

            if newly_failed_graphs:
                _LOGGER.warning(
                    "TrueNAS %s failed to fetch graphs: %s",
                    self.host,
                    newly_failed_graphs,
                )

        if not tmp_graph:
            return

        for item in tmp_graph:
            if not isinstance(item, dict):
                continue
            self._process_system_stat(item)

    def _process_system_stat(self, item: dict) -> None:
        """Process a single system statistic item."""
        name = item.get("name")
        if not name:
            return

        # CPU temperature
        if name == "cputemp":
            mean_vals = item.get("aggregations", {}).get("mean", {})
            valid_means = [v for v in mean_vals.values() if isinstance(v, (int, float))]
            self.ds["system_info"]["cpu_temperature"] = (
                round(max(valid_means), 2) if valid_means else 0.0
            )

        # CPU load
        elif name == "load":
            tmp_arr = ("shortterm", "midterm", "longterm")
            self._systemstats_process(tmp_arr, item, "load")

        # CPU usage
        elif name == "cpu":
            tmp_arr = "cpu"
            self._systemstats_process(tmp_arr, item, "cpu")
            self.ds["system_info"]["cpu_usage"] = round(
                self.ds["system_info"]["cpu_cpu"], 2
            )

        # Interface
        elif name == "interface":
            tmp_etc = item["identifier"]
            if tmp_etc in self.ds["interface"]:
                self._process_system_stat_interface(item, tmp_etc)

        # memory
        elif name == "memory":
            tmp_arr = "available"
            self.ds["system_info"]["memory-total_value"] = round(
                self.ds["system_info"]["physmem"]
            )

            self._systemstats_process(tmp_arr, item, "memory")
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
        elif name == "arcsize":
            tmp_arr = "arc_size"
            self._systemstats_process(tmp_arr, item, "arcsize")

    def _process_system_stat_interface(self, item: dict, tmp_etc: str) -> None:
        """Process interface system statistics."""
        item["legend"] = [tmp.replace("received", "rx") for tmp in item["legend"]]
        item["legend"] = [tmp.replace("sent", "tx") for tmp in item["legend"]]
        item["aggregations"]["mean"] = {
            k.replace("received", "rx"): v
            for k, v in item["aggregations"]["mean"].items()
        }
        item["aggregations"]["mean"] = {
            k.replace("sent", "tx"): v for k, v in item["aggregations"]["mean"].items()
        }

        tmp_arr = ("rx", "tx")
        if "aggregations" in item:
            for tmp_var in item["legend"]:
                if tmp_var in tmp_arr:
                    tmp_val = (
                        item.get("aggregations", {}).get("mean", {}).get(tmp_var) or 0.0
                    )
                    self.ds["interface"][tmp_etc][tmp_var] = round(
                        (tmp_val * KILOBITS_TO_KIBIBYTES_FACTOR), 2
                    )

        else:
            for tmp_load in tmp_arr:
                self.ds["interface"][tmp_etc][tmp_load] = 0.0

    # ---------------------------
    #   _systemstats_process
    # ---------------------------
    def _systemstats_process(self, arr, graph, t) -> None:
        arr = (arr,) if isinstance(arr, str) else tuple(arr)
        if "aggregations" in graph:
            for tmp_var in graph["legend"]:
                if tmp_var in arr:
                    tmp_val = (
                        graph.get("aggregations", {}).get("mean", {}).get(tmp_var)
                        or 0.0
                    )
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
        service_names = {
            "afp": "AFP",
            "cifs": "SMB",
            "dynamicdns": "Dynamic DNS",
            "ftp": "FTP",
            "iscsitarget": "iSCSI",
            "lldp": "LLDP",
            "nfs": "NFS",
            "openvpn_client": "OpenVPN Client",
            "openvpn_server": "OpenVPN Server",
            "rsync": "Rsync",
            "s3": "S3",
            "smart": "SMART",
            "smartd": "SMART",
            "snmp": "SNMP",
            "ssh": "SSH",
            "tftp": "TFTP",
            "ups": "UPS",
            "webdav": "WebDAV",
        }

        self.ds["service"] = parse_api(
            data=self.ds["service"],
            source=self.api.query("service.query"),
            key="id",
            vals=[
                {"name": "id", "default": 0},
                {"name": "service", "default": "unknown"},
                {"name": "name", "default": ""},
                {"name": "enable", "type": "bool", "default": False},
                {"name": "state", "default": "unknown"},
            ],
            ensure_vals=[
                {"name": "running", "type": "bool", "default": False},
                {"name": "display_name", "default": "unknown"},
            ],
        )

        for uid, vals in self.ds["service"].items():
            self.ds["service"][uid]["running"] = vals["state"] == "RUNNING"
            name = vals.get("name")
            if not name or name == "unknown":
                name = service_names.get(
                    vals.get("service"), vals.get("service", "unknown")
                )
            self.ds["service"][uid]["display_name"] = name

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
            if vals.get("free") is not None:
                self.ds["pool"][uid]["available"] = vals["free"]

            if vals.get("size") is not None:
                self.ds["pool"][uid]["total"] = vals["size"]
            elif vals.get("allocated") is not None or vals.get("free") is not None:
                self.ds["pool"][uid]["total"] = vals.get("allocated", 0) + vals.get(
                    "free", 0
                )

            path = vals.get("path")
            if (
                path
                and path in tmp_dataset_available
                and not self.ds["pool"][uid]["available"]
            ):
                self.ds["pool"][uid]["available"] = tmp_dataset_available[path]

            if path and path in tmp_dataset_total and not self.ds["pool"][uid]["total"]:
                self.ds["pool"][uid]["total"] = tmp_dataset_total[path]

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
                {"name": "temperature", "default": None},
            ],
        )

        self._update_disk_temperatures()

    def _update_disk_temperatures(self) -> None:
        """Update disk temperatures from netdata and fallback to API."""
        netdata_temps = self._disk_temps_from_netdata()
        if netdata_temps:
            self._apply_netdata_disk_temps(netdata_temps)

        if missing_disks := [
            uid
            for uid, vals in self.ds["disk"].items()
            if vals.get("temperature") is None
        ]:
            self._fallback_disk_temperatures(missing_disks, bool(netdata_temps))

    def _apply_netdata_disk_temps(self, netdata_temps: dict[str, float]) -> None:
        """Map netdata temperatures to disk entities."""
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

    def _fallback_disk_temperatures(
        self, missing_disks: list[str], has_netdata: bool
    ) -> None:
        """Fetch fallback temperatures from API and map them to missing disks."""
        temps = self.api.query(
            "disk.temperatures",
            params={},
        )

        if isinstance(temps, dict) and "error" not in temps:
            for uid in missing_disks:
                self._map_single_disk_api_temp(uid, temps)
        elif not has_netdata:
            _LOGGER.warning(
                "Failed to update disk temperatures from API 'disk.temperatures': %s",
                temps,
            )

    def _map_single_disk_api_temp(self, uid: str, temps: dict[str, Any]) -> None:
        """Map a single disk's temperature from the API payload."""
        vals = self.ds["disk"][uid]
        candidate_keys: list[str] = []
        for key in ("name", "devname", "identifier"):
            value = vals.get(key)
            if isinstance(value, str) and value:
                candidate_keys.append(value)

        matched_temp: float | None = next(
            (temps[key] for key in candidate_keys if key in temps), None
        )

        if matched_temp is not None:
            self.ds["disk"][uid]["temperature"] = matched_temp
        else:
            _LOGGER.debug(
                "No matching temperature entry in 'disk.temperatures' "
                "for disk uid=%s (candidates: %s)",
                uid,
                candidate_keys,
            )

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
                    if ("disk" in name or "disk" in title) and (
                        "temp" in name or "temp" in title or "celsius" in vertical
                    ):
                        graph_name = name
                        break
            self._disk_temp_graph = graph_name

        if not self._disk_temp_graph:
            return None

        report_epoch = int(datetime.now(UTC).replace(microsecond=0).timestamp())
        graph_query = {
            "start": report_epoch - 90,
            "end": report_epoch - 30,
            "aggregate": True,
        }
        graph_data = self.api.query(
            "reporting.netdata_graph",
            params=[self._disk_temp_graph, graph_query],
        )
        if not isinstance(graph_data, list):
            return None

        temps = {}
        # Sanity bounds for temperatures in °C to avoid clearly invalid readings
        min_temp_c = 0.0
        max_temp_c = 100.0

        for entry in graph_data:
            identifier = entry.get("identifier")
            mean = entry.get("aggregations", {}).get("mean", {})
            if not identifier or not isinstance(mean, dict) or not mean:
                continue

            # Collect numeric mean values and discard values outside sane bounds
            valid_means = [
                v
                for v in mean.values()
                if isinstance(v, (int, float)) and min_temp_c <= v <= max_temp_c
            ]
            if not valid_means:
                continue

            # Use median to reduce the impact of transient spikes/outliers
            sorted_vals = sorted(valid_means)
            n = len(sorted_vals)
            mid = n // 2
            median_val = (
                sorted_vals[mid]
                if n % 2 == 1
                else (sorted_vals[mid - 1] + sorted_vals[mid]) / 2
            )
            temps[str(identifier)] = median_val

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
    #   get_alerts
    # ---------------------------
    def get_alerts(self) -> None:
        """Get alerts from TrueNAS."""
        alerts = self.api.query("alert.list")
        if not isinstance(alerts, list):
            _LOGGER.warning("Unexpected response from alert.list: %r", alerts)
            return

        active_alerts = [alert for alert in alerts if not alert.get("dismissed", False)]

        self.ds["alerts"] = {
            "count": len(active_alerts),
            "messages": [
                alert.get("formatted", "Unknown alert") for alert in active_alerts
            ],
            "critical": sum(a.get("level") == "CRITICAL" for a in active_alerts),
            "warning": sum(a.get("level") == "WARNING" for a in active_alerts),
            "info": sum(a.get("level") == "INFO" for a in active_alerts),
        }

    # ---------------------------
    #   get_smb
    # ---------------------------
    def get_smb(self) -> None:
        """Get active SMB connections."""
        smb_status = self.api.query("smb.status")

        if isinstance(smb_status, list):
            self.ds["system_info"]["smb_connections"] = len(smb_status)
        elif isinstance(smb_status, dict) and "sessions" in smb_status:
            self.ds["system_info"]["smb_connections"] = len(
                smb_status.get("sessions", [])
            )
        else:
            self.ds["system_info"]["smb_connections"] = 0

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

        skip_disabled = self.config_entry.options.get("cronjob_skip_disabled", False)

        for uid, vals in list(self.ds["cronjob"].items()):
            if skip_disabled and not vals.get("enabled", True):
                self.ds["cronjob"].pop(uid)
                continue

            description = (vals.get("description") or "").strip()
            command = (vals.get("command") or "").strip()
            if description:
                display_name = description
            elif command:
                display_name = command
            else:
                display_name = f"Cronjob {uid}"

            self.ds["cronjob"][uid]["display_name"] = display_name
