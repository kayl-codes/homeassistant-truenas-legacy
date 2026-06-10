# Changelog

This integration is a **maintained fork** of the original
[tomaae/homeassistant-truenas](https://github.com/tomaae/homeassistant-truenas).
This file summarizes everything that has changed under the current maintainer
([kayl-codes](https://github.com/kayl-codes)) since taking over the fork, newest first.

The full, curated notes for each version live on the
[Releases page](https://github.com/kayl-codes/homeassistant-truenas/releases).
Items reference the related issue/PR as `(#NN)` where applicable.

The format is loosely based on [Keep a Changelog](https://keepachangelog.com/).
Minimum requirements throughout this fork: **Home Assistant 2024.8.0**, **TrueNAS 25.04**.

---

## [1.8.1] — Multi-instance unique-ID fix

### Fixed
- **Unique-ID error spam with multiple TrueNAS instances (#34):** With more than one
  TrueNAS config entry, the global entity-discovery dispatcher signal made every
  instance's platform also try to create the *other* instance's entities, flooding the
  log with `Platform truenas does not generate unique IDs … already exists` (endlessly,
  since the rejected entities never enter the platform and are retried each refresh).
  Each platform now ignores refreshes coming from other config entries.
  Single-instance setups were unaffected.

## [1.8.0] — Directory Services

### Added
- **Directory Services (#22):** Monitor the TrueNAS Directory Services connection
  (Active Directory / LDAP / IPA) via the unified `directoryservices.*` API
  (TrueNAS 25.04+). A connectivity binary sensor reports whether the service is
  healthy, and a companion status sensor exposes the raw state (`HEALTHY`,
  `FAULTED`, …). Domain, Kerberos realm, site, account-cache and DNS-update
  settings are exposed as attributes. The entity only appears when a directory
  service is actually configured and enabled. New monitored group
  **Directory Services** (enabled by default).

---

## [1.7.0] — TrueNAS Containers + Restart Actions

### Added
- **Containers (#26):** Each TrueNAS Container (Incus instance) is a binary sensor
  (running on/off) with type, status, CPU, memory, autostart, image and IP address
  attributes, grouped under their own device.
- **Start / Stop / Restart** actions for containers (`container_start/stop/restart`,
  `virt.instance.*`); the live state is checked before start/stop.
- **`vm_restart`** action — VMs and containers now share the same start/stop/restart trio.

### Changed
- Robust entity discovery: the "seen" set is derived from the platform's live
  entities (recreate on startup, no re-add spam, runtime-removed objects reappear).
- Monitored-group checks use shared constants; container CPU normalized to a number;
  virt stop options centralized; mis-shaped API responses are logged.

## [1.6.1] — Stability: Entity Spam, Blocking Call & Replication State

### Fixed
- Entities no longer stuck `unavailable` on startup (late fix to the #33 discovery rework).
- No more "non-unique ID" log spam (#33): discovery adds only genuinely new entities.
- No blocking call in the event loop (#33): the WebSocket SSL context is built lazily.
- Replication task state (#34): read from the task's persistent `state` object
  (matching the WebUI), with the last job's state as a fallback.

## [1.6.0] — Options Flow, Live Interface Values & Masked Credentials

### Added
- **Options flow (#14):** Configure under *Settings → Devices & Services → TrueNAS →
  Configure*, applied immediately via reload — poll interval (5/10/30/60/120/300 s),
  monitored groups, behaviour toggles (skip disabled cronjobs, hide RX/TX for
  disconnected NICs) and the GB/GiB data-size unit.

### Changed
- Live interface throughput averaged over a window matching the poll interval.
- Empty devices are cleaned up when a group/interface is removed.
- Disabling a group skips its API query entirely.

### Security
- API key field is now a masked password input (setup + reconfigure).

## [1.5.5] — Hotfix: Phantom App Image Update

### Fixed
- Phantom "Update available" for catalog apps (#31): the `image_updates_available`
  fallback is now correctly gated on `custom_app`, so catalog apps rely solely on
  `upgrade_available` (matching TrueNAS' own state).

## [1.5.4] — Network Group, Boot-Pool & Task Actions

### Added
- Dedicated **"TrueNAS Network"** device for per-interface RX/TX sensors (#25).
- Per-interface link connectivity binary sensor (up/down), even for down interfaces.
- Boot-pool exposed as a regular pool via `boot.get_state` (#23).
- Status sensors for each rsync task in a dedicated **"Rsync tasks"** group (#16).
- `rsync_run` and `replication_run` on-demand actions, guarded against running jobs (#16).

### Changed
- Automatic orphan cleanup of entities whose TrueNAS object no longer exists
  (transient empty fetches never wipe a group; skipped unless the last update succeeded).
- `get_systeminfo` runs before the concurrent jobs, so the first poll has correct values.
- All GitHub Actions pinned to commit SHAs, least-privilege permissions, off Node.js 20.

### Notes
- Closed as not feasible: UPS power/energy + full NUT variables (#17) and SMART test
  results (#15) are not exposed by the TrueNAS JSON-RPC API.

## [1.5.3] — ARC & raidz Fixes, Live Entity Discovery

### Added
- Live entity discovery: new objects appear automatically without a reload.

### Fixed
- ARC sensor no longer stuck at 0; corrected size/allocated for raidz pools.
- Traffic sensors hidden for interfaces whose link is down; null-safe pool totals.

## [1.5.2] — Pool Capacity, UPS Sensors & Auto-Scaled Units

### Added
- Pool capacity sensors (free / size / allocated).
- UPS monitoring: charge, runtime, load, voltage, current, frequency, temperature.
- Auto-scaled data-size units (MB/GB/TB/PB or MiB/GiB/TiB/PiB) per GB/GiB preference.

### Changed
- Pool figures derived from the root dataset, matching the UI for raidz layouts.
- Modern SSL context defaults; generic default host (removed hardcoded IP).
- `system_uptime` uses the `UPTIME` device class; CI moved to Node.js 24.

## [1.5.1] — Cloudsync Control, Disk Health & Stability

### Added
- Cloudsync start/stop switch entities.
- Per-disk health sensor.

### Changed
- Hardened WebSocket layer; fixed leaked connections; more defensive API parsing.

## [1.5.0] — Massive Core Overhaul & New Features

### Added
- TrueNAS Alerts diagnostic sensor (messages + severity).
- SMB connections diagnostic sensor.
- Setup auto-discovery of the TrueNAS IP via local DNS.

### Changed
- Migrated to the modern TrueNAS DDP WebSocket protocol (`auth.login_with_api_key`).
- Pre-flight TCP port check (IPv6-ready) and smarter handshake/query timeouts.
- Dual-lock thread-safety (`_lock` + `_io_lock`); exception-type-based error handling.

### Fixed
- Service controls use modern `service.start/stop/restart/reload`.
- Robust version parsing; reduced stat-graph log spam; entity naming via
  `_attr_has_entity_name`; redundant read-only service binary sensors disabled by default.

### Notes
- Minimum TrueNAS version raised to **25.04** (modernized WebSocket API).

## [1.4.2] — Logic Fixes & API Stability

### Fixed
- RPC errors now preserve detailed backend context in the logs.
- Snapshot fallback (`pool.snapshot.create` → `zfs.snapshot.create`) triggers correctly.
- `cronjob_skip_disabled` is respected during updates.
- Fixed a mutable default-argument bug in the API query method.

## [1.4.1] — TrueNAS SCALE 25.10 & HA 2024.8+ Compatibility

### Changed
- Migrated `services.yaml` → `actions.yaml` (HA "Services" → "Actions").
- Minimum Home Assistant version: **2024.8.0**.
- Replaced Flake8/Black with **Ruff**; native Bandit security checks; cleaned CI.

### Fixed
- Handle JSON-RPC parsing errors to prevent crashes on unexpected API formats.
- Modern type hints and `.get()` fallbacks to avoid `KeyError` crashes.

[1.8.1]: https://github.com/kayl-codes/homeassistant-truenas/releases/tag/1.8.1
[1.8.0]: https://github.com/kayl-codes/homeassistant-truenas/releases/tag/1.8.0
[1.7.0]: https://github.com/kayl-codes/homeassistant-truenas/releases/tag/1.7.0
[1.6.1]: https://github.com/kayl-codes/homeassistant-truenas/releases/tag/1.6.1
[1.6.0]: https://github.com/kayl-codes/homeassistant-truenas/releases/tag/1.6.0
[1.5.5]: https://github.com/kayl-codes/homeassistant-truenas/releases/tag/1.5.5
[1.5.4]: https://github.com/kayl-codes/homeassistant-truenas/releases/tag/1.5.4
[1.5.3]: https://github.com/kayl-codes/homeassistant-truenas/releases/tag/1.5.3
[1.5.2]: https://github.com/kayl-codes/homeassistant-truenas/releases/tag/1.5.2
[1.5.1]: https://github.com/kayl-codes/homeassistant-truenas/releases/tag/1.5.1
[1.5.0]: https://github.com/kayl-codes/homeassistant-truenas/releases/tag/1.5.0
[1.4.2]: https://github.com/kayl-codes/homeassistant-truenas/releases/tag/1.4.2
[1.4.1]: https://github.com/kayl-codes/homeassistant-truenas/releases/tag/1.4.1
