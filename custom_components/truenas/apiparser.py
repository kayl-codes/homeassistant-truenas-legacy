"""API parser for JSON APIs."""

from collections.abc import Hashable
from datetime import datetime
from logging import getLogger
from typing import Any, TypedDict

from homeassistant.components.diagnostics import async_redact_data
from pytz import utc

from .const import TO_REDACT

_LOGGER = getLogger(__name__)


MILLIS_TIMESTAMP_THRESHOLD: int = 100_000_000_000
"""Threshold used to distinguish second-based from millisecond-based Unix timestamps.

Values greater than this are assumed to be in milliseconds and will be divided by 1000
before conversion.
"""


# ---------------------------
#   ApiValueSpec
# ---------------------------
class ApiValueSpec(TypedDict, total=False):
    """Specification for values parsed from the API."""

    name: str
    type: str
    source: str
    default: Any
    default_val: str
    reverse: bool
    convert: str


# ---------------------------
#   utc_from_timestamp
# ---------------------------
def utc_from_timestamp(timestamp: float) -> datetime:
    """Return a UTC time from a timestamp."""
    return utc.localize(datetime.utcfromtimestamp(timestamp))


# ---------------------------
#   from_entry
# ---------------------------
def from_entry(
    entry: dict[str, Any] | None,
    param: str,
    default: Any = "",
    max_len: int | None = 255,
    round_digits: int | None = None,
) -> Any:
    """Validate and return value from an API dict."""
    if entry is None:
        return default

    if "/" in param:
        current: Any = entry
        for tmp_param in param.split("/"):
            if isinstance(current, dict) and tmp_param in current:
                current = current[tmp_param]
            else:
                return default
        ret: Any = current
    elif isinstance(entry, dict) and param in entry:
        ret = entry[param]
    else:
        return default

    if isinstance(ret, float) and round_digits is not None:
        ret = round(ret, round_digits)

    if isinstance(ret, str) and max_len is not None and len(ret) > max_len:
        return ret[:max_len]
    return ret


# ---------------------------
#   from_entry_bool
# ---------------------------
def from_entry_bool(entry, param, default=False, reverse=False) -> bool:
    """Validate and return a bool value from an API dict."""
    if "/" in param:
        for tmp_param in param.split("/"):
            if isinstance(entry, dict) and tmp_param in entry:
                entry = entry[tmp_param]
            else:
                return default

        ret = entry
    elif isinstance(entry, dict) and param in entry:
        ret = entry[param]
    else:
        return default

    if isinstance(ret, str):
        normalized = ret.strip().lower()
        if normalized in {"on", "yes", "up", "true", "1"}:
            ret = True
        elif normalized in {"off", "no", "down", "false", "0"}:
            ret = False

    if not isinstance(ret, bool):
        ret = default

    return not ret if reverse else ret


# ---------------------------
#   parse_api
# ---------------------------
def parse_api(
    data: dict[str, Any] | None = None,
    source: dict[str, Any] | list[dict[str, Any]] | None = None,
    key: str | None = None,
    key_secondary: str | None = None,
    key_search: str | None = None,
    vals: list[ApiValueSpec] | None = None,
    val_proc: list[list[dict[str, Any]]] | None = None,
    ensure_vals: list[ApiValueSpec] | None = None,
    only: list[dict[str, Any]] | None = None,
    skip: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Get data from API."""
    if data is None:
        data = {}
    debug = _LOGGER.getEffectiveLevel() == 10
    if isinstance(source, dict):
        tmp = source
        source = [tmp]

    if not source:
        if not key and not key_search:
            data = fill_defaults(data, vals)
        return data

    if debug:
        _LOGGER.debug("Processing source %s", async_redact_data(source, TO_REDACT))

    keymap = generate_keymap(data, key_search)
    for entry in source:
        if only and not matches_only(entry, only):
            continue

        if skip and can_skip(entry, skip):
            continue

        uid = None
        if key or key_search:
            uid = get_uid(entry, key, key_secondary, key_search, keymap)
            if uid is None:
                continue

            if uid not in data:
                data[uid] = {}

        if debug:
            _LOGGER.debug("Processing entry %s", async_redact_data(entry, TO_REDACT))

        if vals:
            data = fill_vals(data, entry, uid, vals)

        if ensure_vals:
            data = fill_ensure_vals(data, uid, ensure_vals)

        if val_proc:
            data = fill_vals_proc(data, uid, val_proc)

    return data


# ---------------------------
#   get_uid
# ---------------------------
def get_uid(entry, key, key_secondary, key_search, keymap) -> str | None:
    """Get UID for data list."""
    if not isinstance(entry, dict):
        return None

    uid = None
    if not key_search:
        if key is not None and key in entry:
            uid = entry[key]
        elif key_secondary is not None:
            uid = entry.get(key_secondary)
    elif keymap and key_search is not None and key_search in entry:
        uid = keymap.get(entry[key_search])

    return uid


# ---------------------------
#   generate_keymap
# ---------------------------
def generate_keymap(
    data: dict[str, dict[str, Any]], key_search: str | None
) -> dict[Hashable, str] | None:
    """Generate keymap."""
    if not key_search:
        return None
    return {
        data[uid][key_search]: uid
        for uid in data
        if key_search in data[uid] and isinstance(data[uid][key_search], Hashable)
    }


# ---------------------------
#   matches_only
# ---------------------------
def matches_only(entry: dict[str, Any], only: list[dict[str, Any]]) -> bool:
    """Return True if all variables are matched."""
    for val in only:
        if entry.get(val["key"]) != val["value"]:
            return False

    return True


# ---------------------------
#   can_skip
# ---------------------------
def can_skip(entry, skip) -> bool:
    """Return True if at least one variable matches."""
    ret = False
    for val in skip:
        if val["name"] in entry and entry[val["name"]] == val["value"]:
            ret = True
            break

        if val["value"] == "" and val["name"] not in entry:
            ret = True
            break

    return ret


# ---------------------------
#   fill_defaults
# ---------------------------
def fill_defaults(data, vals) -> dict:
    """Fill defaults if source is not present."""
    if data is None:
        data = {}
    if not vals:
        return data

    for val in vals:
        _name = val["name"]
        _type = val["type"] if "type" in val else "str"

        if _type == "str":
            _default = val["default"] if "default" in val else ""
            if "default_val" in val and val["default_val"] in val:
                _default = val[val["default_val"]]

            if _name not in data:
                data[_name] = _default

        elif _type == "bool":
            _default = val["default"] if "default" in val else False
            _reverse = val["reverse"] if "reverse" in val else False
            if _name not in data:
                data[_name] = not _default if _reverse else _default

    return data


# ---------------------------
#   fill_vals
# ---------------------------
def fill_vals(data, entry, uid, vals) -> dict:
    """Fill all data."""
    for val in vals:
        _name = val["name"]
        _type = val["type"] if "type" in val else "str"
        _source = val["source"] if "source" in val else _name
        _convert = val["convert"] if "convert" in val else None

        if _type == "str":
            _default = val["default"] if "default" in val else ""
            if "default_val" in val and val["default_val"] in val:
                _default = val[val["default_val"]]

            if uid is not None:
                data[uid][_name] = from_entry(entry, _source, default=_default)
            else:
                data[_name] = from_entry(entry, _source, default=_default)

        elif _type == "bool":
            _default = val["default"] if "default" in val else False
            _reverse = val["reverse"] if "reverse" in val else False

            if uid is not None:
                data[uid][_name] = from_entry_bool(
                    entry, _source, default=_default, reverse=_reverse
                )
            else:
                data[_name] = from_entry_bool(
                    entry, _source, default=_default, reverse=_reverse
                )

        if _convert == "utc_from_timestamp":
            if uid is not None:
                if isinstance(data[uid][_name], int) and data[uid][_name] > 0:
                    if data[uid][_name] > MILLIS_TIMESTAMP_THRESHOLD:
                        data[uid][_name] = data[uid][_name] / 1000

                    data[uid][_name] = utc_from_timestamp(data[uid][_name])
            elif isinstance(data[_name], int) and data[_name] > 0:
                if data[_name] > MILLIS_TIMESTAMP_THRESHOLD:
                    data[_name] = data[_name] / 1000

                data[_name] = utc_from_timestamp(data[_name])

    return data


# ---------------------------
#   fill_ensure_vals
# ---------------------------
def fill_ensure_vals(data, uid, ensure_vals) -> dict:
    """Add required keys which are not available in data."""
    if uid is not None and uid not in data:
        data[uid] = {}

    for val in ensure_vals:
        if uid is not None:
            if val["name"] not in data[uid]:
                _default = val["default"] if "default" in val else ""
                data[uid][val["name"]] = _default

        elif val["name"] not in data:
            _default = val["default"] if "default" in val else ""
            data[val["name"]] = _default

    return data


# ---------------------------
#   fill_vals_proc
# ---------------------------
def fill_vals_proc(data, uid, vals_proc) -> dict:
    """Add custom keys."""
    _data = data[uid] if uid is not None else data
    supported_actions = {"combine"}

    for val_sub in vals_proc:
        _name = None
        _action = None
        _value = None
        for val in val_sub:
            if "name" in val:
                _name = val["name"]
                continue

            if "action" in val:
                _action = val["action"]
                if _action not in supported_actions:
                    raise ValueError(
                        f"Unsupported action '{_action}' in vals_proc "
                        f"for name '{_name}'"
                    )
                continue

            if not _name and not _action:
                break

            if _action == "combine":
                if "key" in val:
                    tmp = _data[val["key"]] if val["key"] in _data else "unknown"
                    _value = f"{_value}{tmp}" if _value else tmp

                if "text" in val:
                    tmp = val["text"]
                    _value = f"{_value}{tmp}" if _value else tmp

        if _name and _value is not None:
            if uid is not None:
                data[uid][_name] = _value
            else:
                data[_name] = _value

    return data
