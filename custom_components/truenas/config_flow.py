"""Config flow to configure TrueNAS."""

from __future__ import annotations

import contextlib
import socket
from collections.abc import Mapping
from logging import getLogger
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    CONN_CLASS_LOCAL_POLL,
    ConfigFlow,
    ConfigFlowResult,
)
from homeassistant.const import (
    CONF_API_KEY,
    CONF_HOST,
    CONF_NAME,
    CONF_VERIFY_SSL,
)
from homeassistant.core import callback

from .api import TrueNASAPI
from .const import (
    ALLOWED_DATA_UNITS,
    CONF_CRONJOB_SKIP_DISABLED,
    CONF_DATA_UNIT,
    DEFAULT_CRONJOB_SKIP_DISABLED,
    DEFAULT_DATA_UNIT,
    DEFAULT_DEVICE_NAME,
    DEFAULT_HOST,
    DEFAULT_SSL_VERIFY,
    DOMAIN,
    ERR_API_NOT_FOUND,
    ERR_CERT_VERIFY_FAILED,
    ERR_CONNECTION_REFUSED,
    ERR_HANDSHAKE_TIMEOUT,
    ERR_HTTP_USED,
    ERR_INVALID_HOSTNAME,
    ERR_INVALID_KEY,
    ERR_MALFORMED_RESULT,
    ERR_TLS_NOT_SUPPORTED,
    ERR_UNKNOWN_HOSTNAME,
    ERR_WS_NOT_SUPPORTED,
    KNOWN_DOMAINS,
)

_LOGGER = getLogger(__name__)


def _base_schema(truenas_config: Mapping[str, Any]) -> vol.Schema:
    """Generate base schema."""
    base_schema = {
        vol.Required(
            CONF_NAME, default=truenas_config.get(CONF_NAME, DEFAULT_DEVICE_NAME)
        ): str,
        vol.Required(
            CONF_HOST, default=truenas_config.get(CONF_HOST, DEFAULT_HOST)
        ): str,
        vol.Required(CONF_API_KEY, default=truenas_config.get(CONF_API_KEY, "")): str,
        vol.Required(
            CONF_VERIFY_SSL,
            default=truenas_config.get(CONF_VERIFY_SSL, DEFAULT_SSL_VERIFY),
        ): bool,
        vol.Required(
            CONF_CRONJOB_SKIP_DISABLED,
            default=truenas_config.get(
                CONF_CRONJOB_SKIP_DISABLED, DEFAULT_CRONJOB_SKIP_DISABLED
            ),
        ): bool,
        vol.Required(
            CONF_DATA_UNIT,
            default=truenas_config.get(CONF_DATA_UNIT, DEFAULT_DATA_UNIT),
        ): vol.In(ALLOWED_DATA_UNITS),
    }

    return vol.Schema(base_schema)


def _reconfigure_schema(truenas_config: Mapping[str, Any]) -> vol.Schema:
    """Generate base schema."""
    base_schema = {
        vol.Required(
            CONF_HOST, default=truenas_config.get(CONF_HOST, DEFAULT_HOST)
        ): str,
        vol.Optional(CONF_API_KEY): str,
        vol.Required(
            CONF_VERIFY_SSL,
            default=truenas_config.get(CONF_VERIFY_SSL, DEFAULT_SSL_VERIFY),
        ): bool,
        vol.Required(
            CONF_CRONJOB_SKIP_DISABLED,
            default=truenas_config.get(
                CONF_CRONJOB_SKIP_DISABLED, DEFAULT_CRONJOB_SKIP_DISABLED
            ),
        ): bool,
        vol.Required(
            CONF_DATA_UNIT,
            default=truenas_config.get(CONF_DATA_UNIT, DEFAULT_DATA_UNIT),
        ): vol.In(ALLOWED_DATA_UNITS),
    }

    return vol.Schema(base_schema)


# ---------------------------
#   _map_error_to_ha
# ---------------------------
def _map_error_to_ha(errorcode: str) -> str:
    """Map TrueNAS connection error codes to Home Assistant config flow errors."""
    valid_errors = {
        ERR_CERT_VERIFY_FAILED,
        ERR_HTTP_USED,
        ERR_TLS_NOT_SUPPORTED,
        ERR_WS_NOT_SUPPORTED,
        ERR_INVALID_KEY,
        ERR_INVALID_HOSTNAME,
        ERR_UNKNOWN_HOSTNAME,
        ERR_CONNECTION_REFUSED,
        ERR_HANDSHAKE_TIMEOUT,
        ERR_API_NOT_FOUND,
        ERR_MALFORMED_RESULT,
    }
    return errorcode if errorcode in valid_errors else "unknown"


# ---------------------------
#   configured_instances
# ---------------------------
@callback
def configured_instances(hass):
    """Return a set of configured instances."""
    return {
        entry.data[CONF_NAME] for entry in hass.config_entries.async_entries(DOMAIN)
    }


# ---------------------------
#   TrueNASConfigFlow
# ---------------------------
class TrueNASConfigFlow(ConfigFlow, domain=DOMAIN):
    """TrueNASConfigFlow class."""

    VERSION = 1
    CONNECTION_CLASS = CONN_CLASS_LOCAL_POLL

    def __init__(self) -> None:
        """Initialize the config flow."""
        self.truenas_config: dict[str, Any] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a flow initialized by the user."""
        truenas_config = self.truenas_config
        errors = {}

        if user_input is None and not truenas_config.get(CONF_HOST):

            def guess_ip():
                """Try to guess TrueNAS IP."""
                for domain in [""] + KNOWN_DOMAINS:
                    test_host = f"truenas.{domain}" if domain else "truenas"
                    with contextlib.suppress(OSError):
                        return socket.gethostbyname(test_host)
                return DEFAULT_HOST

            default_host = await self.hass.async_add_executor_job(guess_ip)
            _LOGGER.debug("Auto-discovered default host: %s", default_host)
            truenas_config[CONF_HOST] = default_host

        if user_input is not None:
            truenas_config.update(user_input)

            # Check if instance with this name already exists
            if truenas_config[CONF_NAME] in configured_instances(self.hass):
                errors["base"] = "name_exists"

            if not errors:
                # Test API connection
                api = await self.hass.async_add_executor_job(
                    TrueNASAPI,
                    truenas_config[CONF_HOST],
                    truenas_config[CONF_API_KEY],
                    truenas_config[CONF_VERIFY_SSL],
                )

                conn, errorcode = await self.hass.async_add_executor_job(
                    api.connection_test
                )

                await self.hass.async_add_executor_job(api.disconnect)

                if not conn:
                    ha_error = _map_error_to_ha(errorcode)
                    errors[CONF_HOST] = ha_error
                    _LOGGER.error(
                        "TrueNAS connection error (%s) mapped to HA error '%s'",
                        errorcode,
                        ha_error,
                    )

            # Save instance
            if not errors:
                return self.async_create_entry(
                    title=truenas_config[CONF_NAME], data=truenas_config
                )

        return self.async_show_form(
            step_id="user",
            data_schema=_base_schema(truenas_config),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        reconfigure_entry = self._get_reconfigure_entry()
        if not self.truenas_config:
            self.truenas_config.update(reconfigure_entry.data)

        truenas_config = self.truenas_config
        reconfigure_entry = self._get_reconfigure_entry()
        errors = {}

        if user_input is not None:
            # Do not overwrite existing API key if the field is left blank
            if not user_input.get(CONF_API_KEY):
                user_input.pop(CONF_API_KEY, None)

            truenas_config.update(user_input)

            # Only test the connection when settings that actually affect
            # the WebSocket transport have changed. Non-connection settings
            # (e.g. data_unit, cronjob_skip_disabled) must not trigger a new
            # connection attempt because TrueNAS may refuse it while the
            # coordinator already holds active connections, causing a spurious
            # handshake_timeout error.
            _CONNECTION_KEYS = {CONF_HOST, CONF_API_KEY, CONF_VERIFY_SSL}
            connection_changed = any(
                truenas_config.get(k) != reconfigure_entry.data.get(k)
                for k in _CONNECTION_KEYS
            )

            if connection_changed:
                # Test API connection
                api = await self.hass.async_add_executor_job(
                    TrueNASAPI,
                    truenas_config[CONF_HOST],
                    truenas_config[CONF_API_KEY],
                    truenas_config[CONF_VERIFY_SSL],
                )

                conn, errorcode = await self.hass.async_add_executor_job(
                    api.connection_test
                )

                await self.hass.async_add_executor_job(api.disconnect)

                if not conn:
                    ha_error = _map_error_to_ha(errorcode)
                    errors[CONF_HOST] = ha_error
                    _LOGGER.error(
                        "TrueNAS connection error (%s) mapped to HA error '%s'",
                        errorcode,
                        ha_error,
                    )

            # Save instance
            if not errors:
                return self.async_update_reload_and_abort(
                    reconfigure_entry,
                    title=reconfigure_entry.data[CONF_NAME],
                    data_updates=truenas_config,
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_reconfigure_schema(truenas_config),
            errors=errors,
        )
