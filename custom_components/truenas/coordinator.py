"""TrueNAS Controller."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_API_KEY,
    CONF_HOST,
    CONF_NAME,
    CONF_VERIFY_SSL,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import TrueNASAPI
from .apiparser import parse_api
from .const import (
    DOMAIN,
    KILOBITS_TO_KIBIBYTES_FACTOR,
    UPTIME_EPOCH_TOLERANCE_SECONDS,
)

_LOGGER = logging.getLogger(__name__)


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
                "disk_issues": False,
            },
        }

        self.api = TrueNASAPI(
            config_entry.data[CONF_HOST],
            config_entry.data[CONF_API_KEY],
            config_entry.data[CONF_VERIFY_SSL],
        )

        self._systemstats_errored: dict[str, datetime] = {}
        self._systemstats_error_cooldown = timedelta(minutes=10)
        self._disk_temp_graph = None
        self.datasets_hass_device_id = None
        self.last_updatecheck_update = datetime(1970, 1, 1, tzinfo=UTC)

        self._is_virtual = False
        self._version_major: int = 0
        self._version_minor: int = 0
        self._unknown_system_stat_names: set[str] = set()

        self._last_disk_temp_total: int = 0
        self._last_disk_temp_matched: int = 0

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
                    _LOGGER.exception(
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
        raw_system_info = self.api.query("system.info")

        if not isinstance(raw_system_info, dict):
            _LOGGER.debug(
                "Skipping system_info update due to invalid/empty API response: %r",
                raw_system_info,
            )
        else:
            self._update_system_info_data(raw_system_info)

        if not self.api.connected():
            return

        # Update-Logik abhandeln
        self._handle_system_updates()
        if not self.api.connected():
            return

        # Version parsen
        self._parse_version_strings()

        # Virtualisierung prüfen
        sys_info = self.ds["system_info"]
        self._is_virtual = sys_info.get("system_manufacturer") in [
            "QEMU",
            "VMware, Inc.",
            "Microsoft Corporation",
            "Xen",
        ] or sys_info.get("system_product") in ["VirtualBox", "Virtual Machine"]

        # Uptime berechnen
        self._calculate_uptime()

        # Netzwerk-Interfaces abfragen
        self._query_network_interfaces()

    def _update_system_info_data(self, raw_system_info: dict) -> None:
        """Parse the raw system info dict into the data structure."""
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
                {"name": "cpu_temperature", "default": None},
                {"name": "load_shortterm", "default": 0.0},
                {"name": "load_midterm", "default": 0.0},
                {"name": "load_longterm", "default": 0.0},
                {"name": "cpu_usage", "default": 0.0},
                {"name": "cache_size-arc_value", "default": 0.0},
                {"name": "memory-free_value", "default": 0.0},
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

    def _handle_system_updates(self) -> None:
        """Handle version string overrides and active update jobs."""
        sys_info = self.ds["system_info"]

        if not sys_info.get("update_available"):
            sys_info["update_version"] = sys_info.get("version", "unknown")

        job_id = sys_info.get("update_jobid")
        if not job_id:
            return

        self.ds["system_info"] = parse_api(
            data=sys_info,
            source=self.api.query("core.get_jobs", params=[[["id", "=", job_id]]]),
            vals=[
                {"name": "update_progress", "source": "progress/percent", "default": 0},
                {"name": "update_state", "source": "state", "default": "unknown"},
            ],
        )

        if not self.api.connected():
            return

        updated_info = self.ds["system_info"]
        if updated_info.get("update_state") != "RUNNING" or not updated_info.get(
            "update_available"
        ):
            updated_info["update_progress"] = 0
            updated_info["update_jobid"] = 0
            updated_info["update_state"] = "unknown"

    def _parse_version_strings(self) -> None:
        """Extract major and minor version numbers without ReDoS risk."""
        version_str = str(self.ds["system_info"].get("version", "") or "")
        clean_version = version_str.replace("TrueNAS-", "").replace("SCALE-", "")

        base_version = clean_version.split()[0].split("-")[0]
        parts = base_version.split(".")

        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            self._version_major = int(parts[0])
            self._version_minor = int(parts[1])
        elif clean_version:
            _LOGGER.debug(
                "Failed to parse TrueNAS version from string: %s", version_str
            )

    def _calculate_uptime(self) -> None:
        """Calculate and smooth out the uptime epoch timestamp."""
        uptime_seconds = self.ds["system_info"].get("uptime_seconds", 0)
        if uptime_seconds <= 0:
            return

        now = datetime.now(UTC).replace(microsecond=0)
        new_uptime_epoch = int(now.timestamp()) - int(uptime_seconds)
        old_uptime_epoch = self.ds["system_info"].get("uptimeEpoch", 0)

        if (
            old_uptime_epoch == 0
            or abs(new_uptime_epoch - old_uptime_epoch) > UPTIME_EPOCH_TOLERANCE_SECONDS
        ):
            self.ds["system_info"]["uptimeEpoch"] = new_uptime_epoch
        else:
            self.ds["system_info"]["uptimeEpoch"] = old_uptime_epoch

    def _query_network_interfaces(self) -> None:
        """Fetch and parse network interface statistics."""
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
        self.ds["system_info"].setdefault("update_state", "IDLE")
        if "update_version" not in self.ds["system_info"] or self.ds["system_info"][
            "update_version"
        ] in [None, "unknown", ""]:
            self.ds["system_info"]["update_version"] = self.ds["system_info"].get(
                "version", "up-to-date"
            )

        # If API returns nothing, we already set defaults above, but we must clear
        # any potentially stale update metadata before returning.
        if not isinstance(update_data, dict):
            _LOGGER.warning(
                "TrueNAS update status returned malformed data: %s",
                update_data,
            )
            self._reset_update_status(status="IDLE")
            return

        if not update_data:
            self._reset_update_status()
            return

        # According to your PS-test, the data is in: result -> status -> new_version
        # Since api.py extracts 'result', we access 'status' directly
        status_obj = update_data.get("status")

        if isinstance(status_obj, dict):
            raw_status = status_obj.get("state") or status_obj.get("status")
            if isinstance(raw_status, str):
                # Normalize to uppercase so downstream comparisons (e.g. "RUNNING")
                # are consistent
                self.ds["system_info"]["update_state"] = raw_status.upper()

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
            self.ds["system_info"]["update_state"] = status
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

        # 1. Liste der abzufragenden Graphen ermitteln
        graph_names = self._determine_graph_names()
        if not graph_names:
            return

        graph_query = {
            "start": report_epoch - 90,
            "end": report_epoch - 30,
            "aggregate": True,
        }

        # 2. API abfragen und fehlgeschlagene Graphen sammeln
        tmp_graph, failed_graphs = self._fetch_graph_data(graph_names, graph_query)

        # 3. Fehlerbehandlung und Logging für neue Fehler
        if failed_graphs:
            self._handle_failed_graphs(failed_graphs)

        if not tmp_graph:
            return

        # 4. Statistiken verarbeiten
        for item in tmp_graph:
            if isinstance(item, dict):
                self._process_system_stat(item)

    def _determine_graph_names(self) -> list[str]:
        """Determine which graphs to fetch based on state and error cooldowns."""
        graph_names = ["load", "cputemp", "cpu", "arcsize", "memory"]

        if self.ds["interface"]:
            graph_names.append("interface")

        # Virtuelle Maschinen von CPU-Temperatur ausschließen
        if self._is_virtual and "cputemp" in graph_names:
            graph_names.remove("cputemp")

        # Fehler-Cooldowns aufräumen
        now = datetime.now(UTC)
        self._systemstats_errored = {
            name: ts
            for name, ts in self._systemstats_errored.items()
            if now - ts < self._systemstats_error_cooldown
        }

        # Nur Graphen zurückgeben, die aktuell nicht im Cooldown sind
        return [name for name in graph_names if name not in self._systemstats_errored]

    def _fetch_graph_data(
        self, graph_names: list[str], graph_query: dict
    ) -> tuple[list, list[str]]:
        """Query the TrueNAS API for each graph and separate successes from failures."""
        tmp_graph = []
        failed_graphs = []
        reporting_path = "reporting.netdata_graph"

        for graph_name in graph_names:
            graph_data = self.api.query(
                reporting_path, params=[graph_name, graph_query]
            )
            if isinstance(graph_data, list):
                tmp_graph.extend(graph_data)
            else:
                failed_graphs.append(graph_name)

        return tmp_graph, failed_graphs

    def _handle_failed_graphs(self, failed_graphs: list[str]) -> None:
        """Track failed graphs and log warnings only for newly failed ones.

        This prevents log spam.
        """
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

    def _process_system_stat(self, item: dict) -> None:
        """Process a single system statistic item."""
        name = item.get("name")
        if not name:
            return

        # Mapping von Namen zu den jeweiligen Verarbeitungs-Methoden
        stat_handlers = {
            "cputemp": self._process_stat_cputemp,
            "load": self._process_stat_load,
            "cpu": self._process_stat_cpu,
            "interface": self._process_stat_interface_entry,
            "memory": self._process_stat_memory,
            "arcsize": self._process_stat_arcsize,
        }

        if handler := stat_handlers.get(name):
            handler(item)
        else:
            self._handle_unknown_stat(name)

    def _process_stat_cputemp(self, item: dict) -> None:
        """Process CPU temperature statistics."""
        mean_vals = item.get("aggregations", {}).get("mean", {})
        valid_means = [v for v in mean_vals.values() if isinstance(v, (int, float))]
        self.ds["system_info"]["cpu_temperature"] = (
            round(max(valid_means), 2) if valid_means else None
        )

    def _process_stat_load(self, item: dict) -> None:
        """Process CPU load statistics."""
        self._systemstats_process(("shortterm", "midterm", "longterm"), item, "load")

    def _process_stat_cpu(self, item: dict) -> None:
        """Process CPU usage statistics."""
        self._systemstats_process("cpu", item, "cpu")
        cpu_cpu = self.ds["system_info"].get("cpu_cpu", 0.0)
        self.ds["system_info"]["cpu_usage"] = round(cpu_cpu, 2)

    def _process_stat_interface_entry(self, item: dict) -> None:
        """Process network interface statistics."""
        tmp_etc = item.get("identifier")
        if tmp_etc in self.ds["interface"]:
            self._process_system_stat_interface(item, tmp_etc)

    def _process_stat_memory(self, item: dict) -> None:
        """Process RAM memory statistics."""
        self.ds["system_info"]["memory-total_value"] = round(
            self.ds["system_info"].get("physmem", 0)
        )
        self._systemstats_process("available", item, "memory")

        total_mem = self.ds["system_info"].get("memory-total_value", 0.0)
        free_mem = self.ds["system_info"].get("memory-free_value", 0.0)
        if total_mem > 0:
            self.ds["system_info"]["memory-usage_percent"] = round(
                100 * (float(total_mem) - float(free_mem)) / float(total_mem)
            )

    def _process_stat_arcsize(self, item: dict) -> None:
        """Process ZFS ARC size statistics."""
        self._systemstats_process("arc_size", item, "arcsize")

    def _handle_unknown_stat(self, name: str) -> None:
        """Log a warning and look for near-misses for unknown stat names."""
        if name in self._unknown_system_stat_names:
            return

        self._unknown_system_stat_names.add(name)
        _LOGGER.warning(
            "TrueNAS %s returned unknown system stat graph name '%s'; "
            "this may indicate a TrueNAS API change or misconfiguration",
            self.host,
            name,
        )

        known_names = {"cputemp", "load", "cpu", "interface", "memory", "arcsize"}
        if near_misses := [
            k for k in known_names if self._is_similar_stat_name(name, k)
        ]:
            _LOGGER.debug(
                "Unknown system stat graph name '%s' from TrueNAS %s "
                "is similar to known names: %s",
                name,
                self.host,
                ", ".join(sorted(near_misses)),
            )

    def _is_similar_stat_name(self, a: str, b: str) -> bool:
        """Check if two stat names are similar (near-miss detection)."""
        a_l, b_l = a.lower(), b.lower()
        if a_l == b_l:
            return False
        if a_l.replace("_", "") == b_l.replace("_", ""):
            return True
        if (
            a_l.startswith(b_l)
            or a_l.endswith(b_l)
            or b_l.startswith(a_l)
            or b_l.endswith(a_l)
        ):
            return True
        return abs(len(a_l) - len(b_l)) <= 2 and a_l[:3] == b_l[:3]

    def _process_system_stat_interface(self, item: dict, tmp_etc: str) -> None:
        """Process interface system statistics."""
        tmp_arr = ("rx", "tx")
        legend = item.get("legend")
        if not isinstance(legend, list):
            for tmp_load in tmp_arr:
                self.ds["interface"][tmp_etc][tmp_load] = 0.0
            return

        item["legend"] = [
            tmp.replace("received", "rx").replace("sent", "tx")
            for tmp in legend
            if isinstance(tmp, str)
        ]

        aggregations = item.get("aggregations")
        if isinstance(aggregations, dict) and isinstance(
            aggregations.get("mean"), dict
        ):
            aggregations["mean"] = {
                k.replace("received", "rx").replace("sent", "tx"): v
                for k, v in aggregations["mean"].items()
                if isinstance(k, str)
            }

            for tmp_var in item["legend"]:
                if tmp_var in tmp_arr:
                    tmp_val = aggregations["mean"].get(tmp_var) or 0.0
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
        """Process system statistics and map to data structures."""
        targets = (arr,) if isinstance(arr, str) else tuple(arr)
        aggregations = graph.get("aggregations")
        legend = graph.get("legend")

        # Fallback-Path: if API-Stuctur nok
        if not isinstance(aggregations, dict) or not isinstance(legend, list):
            self._fill_fallback_stats(targets, t)
            return

        mean_data = aggregations.get("mean", {})
        if not isinstance(mean_data, dict):
            mean_data = {}

        for metric_name in legend:
            if metric_name not in targets:
                continue

            raw_val = mean_data.get(metric_name)
            val = float(raw_val) if isinstance(raw_val, (int, float)) else 0.0

            self._assign_stat_value(t, metric_name, val)

    def _assign_stat_value(self, stat_type: str, name: str, val: float) -> None:
        """Map the processed value to the correct field in system_info."""
        sys_info = self.ds["system_info"]

        if stat_type == "memory" and name == "available":
            sys_info["memory-free_value"] = round(val)
        elif stat_type == "cpu":
            sys_info[f"cpu_{name}"] = round(val, 2)
        elif stat_type == "load":
            sys_info[f"load_{name}"] = round(val, 2)
        elif stat_type == "arcsize":
            sys_info["cache_size-arc_value"] = round(val, 2)
        else:
            sys_info[name] = round(val, 2)

    def _fill_fallback_stats(self, targets: tuple, stat_type: str) -> None:
        """Fill fallback values (0.0) when API response is invalid."""
        sys_info = self.ds["system_info"]
        for metric_name in targets:
            if stat_type == "cpu":
                sys_info[f"cpu_{metric_name}"] = 0.0
            else:
                sys_info[metric_name] = 0.0

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

        # Mappings aus den Datasets vorbereiten
        dataset_avail, dataset_total = self._build_dataset_mappings()

        # Pools einzeln verarbeiten
        for uid, vals in self.ds["pool"].items():
            self._process_single_pool(uid, vals, dataset_avail, dataset_total)

    def _build_dataset_mappings(self) -> tuple[dict[str, float], dict[str, float]]:
        """Build lookup maps for available and total space from datasets."""
        dataset_avail = {}
        dataset_total = {}

        for uid, vals in self.ds["dataset"].items():
            mountpoint = self.ds["dataset"][uid]["mountpoint"]
            dataset_avail[mountpoint] = vals["available"]
            dataset_total[mountpoint] = vals["available"] + vals["used"]

        return dataset_avail, dataset_total

    def _process_single_pool(
        self, uid: str, vals: dict, dataset_avail: dict, dataset_total: dict
    ) -> None:
        """Calculate storage stats and capacity usage for a single pool."""
        pool_entry = self.ds["pool"][uid]

        # Basis-Werte setzen
        if vals.get("free") is not None:
            pool_entry["available"] = vals["free"]

        if vals.get("size") is not None:
            pool_entry["total"] = vals["size"]
        elif vals.get("allocated") is not None or vals.get("free") is not None:
            pool_entry["total"] = vals.get("allocated", 0) + vals.get("free", 0)

        # Fallback auf Dataset-Werte falls Pool-Werte fehlen/null sind
        path = vals.get("path")
        if path and not pool_entry["available"]:
            pool_entry["available"] = dataset_avail.get(path, pool_entry["available"])

        if path and not pool_entry["total"]:
            pool_entry["total"] = dataset_total.get(path, pool_entry["total"])

        # Prozentuale Belegung berechnen
        total = pool_entry["total"]
        if total > 0:
            pool_entry["usage"] = round(
                ((total - pool_entry["available"]) / total) * 100
            )
        else:
            pool_entry["usage"] = 0

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

    def _log_disk_mapping_collision(
        self, key: str, existing_uid: str, colliding_uid: str
    ) -> None:
        """Log a warning when two disks share the same mapping key."""
        existing_vals = self.ds["disk"].get(existing_uid, {})
        colliding_vals = self.ds["disk"].get(colliding_uid, {})
        _LOGGER.warning(
            "Disk mapping collision for key '%s': existing disk %s "
            "(identifier=%s, devname=%s, name=%s, serial=%s) and "
            "colliding disk %s (identifier=%s, devname=%s, name=%s, "
            "serial=%s). Netdata temperatures may be mapped to the "
            "wrong disk.",
            key,
            existing_uid,
            existing_vals.get("identifier"),
            existing_vals.get("devname"),
            existing_vals.get("name"),
            existing_vals.get("serial"),
            colliding_uid,
            colliding_vals.get("identifier"),
            colliding_vals.get("devname"),
            colliding_vals.get("name"),
            colliding_vals.get("serial"),
        )

    def _apply_netdata_disk_temps(self, netdata_temps: dict[str, float]) -> None:
        """Map netdata temperatures to disk entities."""
        identifier_map: dict[str, str] = {}
        devname_map: dict[str, str] = {}
        name_map: dict[str, str] = {}

        # 1. Maps befüllen über flache Hilfsmethode
        for uid, vals in self.ds["disk"].items():
            self._map_disk_key(vals.get("identifier"), uid, identifier_map)
            self._map_disk_key(vals.get("devname"), uid, devname_map)
            self._map_disk_key(vals.get("name"), uid, name_map)

        # 2. Netdata-Keys auflösen mithilfe von Dict-Lookups (.get) statt If-Kaskaden
        for key, temp in netdata_temps.items():
            # Nutzt die implizite Priorität: identifier_map > devname_map > name_map
            uid = identifier_map.get(key) or devname_map.get(key) or name_map.get(key)

            if uid and (disk_vals := self.ds["disk"].get(uid)):
                disk_vals["temperature"] = round(temp, 2)

    def _map_disk_key(
        self, key: str | None, uid: str, target_map: dict[str, str]
    ) -> None:
        """Safely map a disk key to its UID and log collisions if they occur."""
        if not key:
            return

        existing_uid = target_map.get(key)
        if existing_uid and existing_uid != uid:
            self._log_disk_mapping_collision(key, existing_uid, uid)
        else:
            target_map[key] = uid

    def _fallback_disk_temperatures(
        self, missing_disks: list[str], has_netdata: bool
    ) -> None:
        """Fetch fallback temperatures from API and map them to missing disks."""
        temps = self.api.query(
            "disk.temperatures",
        )

        if self._is_valid_disk_temperature_payload(temps):
            self._reset_disk_temp_match_counters()
            for uid in missing_disks:
                self._map_single_disk_api_temp(uid, temps)
            self._log_disk_temp_mapping_summary()
        elif not has_netdata:
            _LOGGER.warning(
                "Failed to update disk temperatures from API 'disk.temperatures': %s",
                temps,
            )

    def _reset_disk_temp_match_counters(self) -> None:
        """Reset disk temperature mapping counters at the start of a refresh."""
        self._last_disk_temp_total = 0
        self._last_disk_temp_matched = 0

    def _record_disk_temp_match(self, matched: bool) -> None:
        """Record the result of a single disk temperature mapping."""
        self._last_disk_temp_total += 1
        if matched:
            self._last_disk_temp_matched += 1

    def _log_disk_temp_mapping_summary(self) -> None:
        """Log a summary of disk temperature mapping results after a refresh."""
        if self._last_disk_temp_total == 0:
            return

        if self._last_disk_temp_matched == 0:
            # No disks matched at all: likely configuration or API naming mismatch.
            _LOGGER.warning(
                "Failed to match temperature data for any of the %d disks returned by "
                "the TrueNAS API. This may indicate a configuration issue or a change "
                "in the API's disk naming scheme. Check that disk identifiers in "
                "Home Assistant match those exposed by TrueNAS.",
                self._last_disk_temp_total,
            )
        elif self._last_disk_temp_matched < self._last_disk_temp_total:
            # Some disks matched, some did not: keep it at debug level for now.
            _LOGGER.debug(
                "Matched temperature data for %d of %d disks from the TrueNAS API.",
                self._last_disk_temp_matched,
                self._last_disk_temp_total,
            )

    def _is_valid_disk_temperature_payload(self, temps: Any) -> bool:
        """Validate the shape of the disk temperature API payload.

        Delegates specific value validation to per-disk mapping.
        """
        return isinstance(temps, dict)

    def _map_single_disk_api_temp(self, uid: str, temps: dict[str, Any]) -> None:
        """Map a single disk's temperature from the API payload."""
        vals = self.ds["disk"][uid]
        candidate_keys: list[str] = []
        for key in ("identifier", "devname", "name"):
            value = vals.get(key)
            if isinstance(value, str) and value:
                candidate_keys.append(value)

        matched_temp = next(
            (temps[key] for key in candidate_keys if key in temps), None
        )

        matched = False
        if matched_temp is None:
            _LOGGER.debug(
                "No matching temperature entry in 'disk.temperatures' "
                "for disk uid=%s (candidates: %s)",
                uid,
                candidate_keys,
            )
        elif isinstance(matched_temp, (int, float)):
            self.ds["disk"][uid]["temperature"] = matched_temp
            matched = True
        else:
            _LOGGER.debug(
                "Invalid temperature value %r for disk uid=%s",
                matched_temp,
                uid,
            )

        # Record the mapping result for higher-level summary logging.
        self._record_disk_temp_match(matched)

    def _disk_temps_from_netdata(self) -> dict[str, float] | None:
        """Return disk temperatures from netdata graphs when available."""
        if self._disk_temp_graph is None:
            graphs = self.api.query("reporting.netdata_graphs")
            self._disk_temp_graph = self._find_disk_temp_graph(graphs)

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
        min_temp_c = getattr(self, "_disk_temp_min_c", -20.0)
        max_temp_c = getattr(self, "_disk_temp_max_c", 120.0)

        for entry in graph_data:
            identifier = entry.get("identifier")
            mean = entry.get("aggregations", {}).get("mean", {})
            if not identifier or not isinstance(mean, dict) or not mean:
                continue

            if (
                median_val := self._process_entry_temperature(
                    identifier, mean, min_temp_c, max_temp_c
                )
            ) is not None:
                temps[str(identifier)] = median_val

        return temps or None

    def _find_disk_temp_graph(self, graphs: any) -> str:
        """Scan available netdata graphs to find the disk temperature graph name."""
        if not isinstance(graphs, list):
            return ""

        for graph in graphs:
            name = str(graph.get("name", ""))
            title = str(graph.get("title", "")).lower()
            vertical = str(graph.get("vertical_label", "")).lower()

            if ("disk" in name or "disk" in title) and (
                "temp" in name or "temp" in title or "celsius" in vertical
            ):
                return name
        return ""

    def _process_entry_temperature(
        self, identifier: str, mean: dict, min_temp: float, max_temp: float
    ) -> float | None:
        """Validate temperature values and calculate the median.

        Calculates the median for a single disk entry.
        """
        raw_means = [v for v in mean.values() if isinstance(v, (int, float))]
        valid_means = [v for v in raw_means if min_temp <= v <= max_temp]

        if raw_means and not valid_means:
            _LOGGER.debug(
                "Discarding out-of-range disk temperature readings "
                "for %s: %s (bounds: %.1f–%.1f °C)",
                identifier,
                raw_means,
                min_temp,
                max_temp,
            )

        if not valid_means:
            return None

        # Median-Berechnung
        sorted_vals = sorted(valid_means)
        n = len(sorted_vals)
        mid = n // 2

        return (
            sorted_vals[mid]
            if n % 2 == 1
            else (sorted_vals[mid - 1] + sorted_vals[mid]) / 2
        )

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
            _LOGGER.warning(
                "Unexpected response from alert.list (expected list, got %s)",
                type(alerts).__name__,
            )
            self.ds["alerts"] = {
                "count": 0,
                "messages": [],
                "critical": 0,
                "warning": 0,
                "info": 0,
                "disk_issues": False,
            }
            return

        active_alerts = [alert for alert in alerts if not alert.get("dismissed", False)]

        disk_issues = False
        for alert in active_alerts:
            klass = str(alert.get("klass", "")).lower()
            title = str(alert.get("title", "")).lower()
            if "disk" in klass or "pool" in klass or "smart" in title:
                disk_issues = True
                break

        self.ds["alerts"] = {
            "count": len(active_alerts),
            "messages": [
                alert.get("formatted", "Unknown alert") for alert in active_alerts
            ],
            "critical": sum(a.get("level") == "CRITICAL" for a in active_alerts),
            "warning": sum(a.get("level") == "WARNING" for a in active_alerts),
            "info": sum(a.get("level") == "INFO" for a in active_alerts),
            "disk_issues": disk_issues,
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
            sessions = smb_status.get("sessions")
            if isinstance(sessions, list):
                self.ds["system_info"]["smb_connections"] = len(sessions)
            else:
                _LOGGER.debug(
                    "Unexpected type for 'sessions' in smb.status response: %s",
                    type(sessions).__name__,
                )
                self.ds["system_info"]["smb_connections"] = 0
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

        skip_disabled = self.config_entry.options.get(
            "cronjob_skip_disabled",
            self.config_entry.data.get("cronjob_skip_disabled", True),
        )

        # FIX: Wir holen uns vorab die IDs als Tuple. Das ist ein unveränderbares
        # Iterable, weshalb .pop(uid) danach keinen RuntimeError mehr wirft.
        for uid in tuple(self.ds["cronjob"]):
            vals = self.ds["cronjob"][uid]

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
