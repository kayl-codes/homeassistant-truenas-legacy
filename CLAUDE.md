# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

This is a Home Assistant **custom integration** (HACS-distributed) that monitors and controls a TrueNAS device. All integration code lives under [custom_components/truenas/](custom_components/truenas/). It targets TrueNAS 25.04+ and Home Assistant 2024.8.0+, and communicates with TrueNAS exclusively over its JSON-RPC **WebSocket** API (`local_polling`, 60s interval).

## Commands

Linting/formatting and tooling mirror CI ([.github/workflows/ci.yml](.github/workflows/ci.yml)):

```bash
ruff check .            # lint (rules E, F, W, I, UP, ASYNC; py313, line-length 88)
ruff format --check .   # formatting check; drop --check to auto-format
bandit -r custom_components/truenas   # security scan (part of CI)
```

- Python target is **3.13**.
- `pytest` is configured in [pyproject.toml](pyproject.toml) (`asyncio_mode=auto`, `testpaths=["tests"]`), but there is currently **no `tests/` directory** and the pytest step in CI is commented out. If adding tests, create `tests/` and re-enable that CI step.
- CI also runs Home Assistant **hassfest** validation and HACS validation on push/PR.
- Runtime deps come from [manifest.json](custom_components/truenas/manifest.json) (`websockets>=15.0.1`); dev deps are in the [Pipfile](Pipfile). `.github/generate_requirements.py` regenerates `requirements*.txt` from the Pipfile during CI.
- Bumping the release: `version` in [manifest.json](custom_components/truenas/manifest.json) is the source of truth (`.github/update_version.py` updates it during release).

## Architecture

Data flows in one direction: **API → Coordinator → `coordinator.ds` dict → entities**.

### Layers

- **[api.py](custom_components/truenas/api.py) — `TrueNASAPI`**: Synchronous (thread-based, not asyncio) WebSocket client. `query(method, params)` issues a JSON-RPC call and returns the unwrapped `result` (or `None` on any error). It handles `connect`/login (`auth.login_with_api_key`), subprotocol negotiation quirks, and a large catalogue of connection-error classification (see `ERR_*` constants in [const.py](custom_components/truenas/const.py)). Because it is synchronous, the coordinator always calls it via `hass.async_add_executor_job(...)`. **Concurrency:** two reentrant locks — `_io_lock` (all websocket recv/send) must always be acquired **before** `_lock` (fast state writes). All websocket I/O goes through `_recv_locked`/`_send_locked`; preserve this discipline when editing.

- **[coordinator.py](custom_components/truenas/coordinator.py) — `TrueNASCoordinator`**: A `DataUpdateCoordinator`. `_async_update_data` runs a list of `get_*` jobs concurrently via `asyncio.gather` (each wrapped to swallow/log exceptions), then runs `get_pool` last because it depends on dataset data. Every `get_*` method calls one or more `self.api.query(...)` and stores normalized results into `self.ds[<domain>]` (e.g. `system_info`, `disk`, `pool`, `dataset`, `vm`, `app`, `service`, `cloudsync`, `replication`, `snapshottask`, `cronjob`, `alerts`, `interface`). The update check (`get_updatecheck`) runs at most every 12 hours. The whole `self.ds` dict is the coordinator's `data`.

- **[apiparser.py](custom_components/truenas/apiparser.py) — `parse_api`**: The central normalization helper used by nearly every `get_*` method. It maps raw API entries into a flat dict keyed by `key` (e.g. `id`, `guid`, `identifier`). Field specs (`vals`) support nested source paths via `/` (e.g. `"scan/start_time/$date"`), type coercion (`"bool"`), defaults, and `convert: "utc_from_timestamp"`. `ensure_vals` guarantees keys exist with defaults even when absent from the source. When adding a new monitored field, add a spec entry here rather than post-processing.

- **[entity.py](custom_components/truenas/entity.py) — `TrueNASEntity` + `async_add_entities`**: Shared base entity (a `CoordinatorEntity`) and the generic platform setup. `async_add_entities` is reused by all platforms: it reads each platform module's `SENSOR_TYPES`/`SENSOR_SERVICES`, uses a per-platform **`dispatcher`** dict (string class-name → class) to instantiate entities, dynamically creates entities for each `uid` under `data_path`, and registers entity services. New entities appear on the fly via the `"update_sensors"` dispatcher signal. Device grouping and unique IDs are derived from the entity description's `ha_group`/`ha_connection`/`data_reference` fields.

### Platforms and the entity-description pattern

Platforms registered in `PLATFORMS` ([const.py](custom_components/truenas/const.py)): `SENSOR`, `BINARY_SENSOR`, `UPDATE`, `SWITCH`. Each platform has two files:

- `<platform>.py` — the entity classes and `async_setup_entry` (which only builds the `dispatcher` and calls the shared `async_add_entities`/`setup_entities`).
- `<platform>_types.py` — exports `SENSOR_TYPES` (a tuple of frozen-dataclass entity descriptions subclassing the HA `*EntityDescription`) and `SENSOR_SERVICES`.

Entity descriptions are **declarative**: each carries `data_path` (which `coordinator.ds` key to read), `data_attribute`/`data_is_on` (which field is the value), `data_reference` (field used for the unique id when iterating multiple objects), `data_attributes_list` (extra state attributes), `ha_group` (device grouping), and `func` (the dispatcher key naming the entity class to instantiate). To add a sensor/switch, you usually only add a description entry plus, if needed, a new class in the dispatcher — no changes to `entity.py`.

### Services (actions)

User-facing actions (start/stop VMs and apps, service control, cloudsync run/abort, dataset snapshot, system reboot/shutdown) are defined as `SERVICE_*`/`SCHEMA_SERVICE_*` constants in [const.py](custom_components/truenas/const.py), declared in [services.yaml](custom_components/truenas/services.yaml)/[actions.yaml](custom_components/truenas/actions.yaml), and registered per-platform through the `SENSOR_SERVICES` list consumed by `async_add_entities`. The corresponding entity methods (`start`/`stop`/`restart`/`reload`/`snapshot`) are stubs in `TrueNASEntity` overridden by concrete entity classes, which call `self.coordinator.api.query(...)` and then `async_request_refresh()`.

### Config flow

[config_flow.py](custom_components/truenas/config_flow.py) collects host (bare hostname/IP, no scheme/path — enforced by `TrueNASAPI`), API key, SSL verification, and a `data_unit` option (`GB` vs `GiB`). The GB/GiB preference auto-migrates existing `DATA_SIZE` sensor units on setup (see `async_setup_entry` in [\_\_init\_\_.py](custom_components/truenas/__init__.py)).

## Conventions

- Code is heavily defensive about malformed/empty API responses: `query` returns `None` on error and `parse_api` is invoked with `isinstance` guards. Match this style — never assume an API response shape; check types and fall back to defaults.
- Sensitive fields are redacted in diagnostics/debug logs via `TO_REDACT` ([const.py](custom_components/truenas/const.py)); add new sensitive keys there.
- UI strings live in [strings.json](custom_components/truenas/strings.json) and `translations/`; translations are managed via Lokalise (see [README.md](README.md)), so prefer editing `strings.json` / `en.json` and let Lokalise handle other locales.
- Enable debug logging in HA via `logger: logs: custom_components.truenas: debug`.
