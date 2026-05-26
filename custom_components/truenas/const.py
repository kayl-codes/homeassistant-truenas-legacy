"""Constants used by the TrueNAS integration."""

import voluptuous as vol
from homeassistant.const import Platform
from homeassistant.helpers import config_validation as cv

PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.UPDATE, Platform.SWITCH]

DOMAIN = "truenas"
DEFAULT_NAME = "root"
ATTRIBUTION = "Data provided by TrueNAS integration"

DEFAULT_HOST = "trueas.local"

# Conversion factor: kilobits per second to kibibytes per second
# (1000 / 8192 = ~0.12207)
KILOBITS_TO_KIBIBYTES_FACTOR = 0.12207

# Tolerance in seconds to prevent Uptime sensor fluctuations
UPTIME_EPOCH_TOLERANCE_SECONDS = 300

# Default per-query timeout in seconds
QUERY_TIMEOUT: float = 30.0

# Error constants
ERR_CERT_VERIFY_FAILED = "certificate_verify_failed"
ERR_HTTP_USED = "http_used"
ERR_TLS_NOT_SUPPORTED = "tlsv1_not_supported"
ERR_WS_NOT_SUPPORTED = "websocket_not_supported"
ERR_UNKNOWN_HOSTNAME = "unknown_hostname"
ERR_CONNECTION_REFUSED = "connection_refused"
ERR_INVALID_HOSTNAME = "invalid_hostname"
ERR_HANDSHAKE_TIMEOUT = "handshake_timeout"
ERR_INVALID_KEY = "invalid_key"
ERR_API_NOT_FOUND = "api_not_found"
ERR_TIMEOUT = "timeout"
ERR_MALFORMED_RESULT = "malformed_result"
ERR_LOST_LOGIN = "connection_lost_mid_login"
ERR_LOST_QUERY = "connection_lost_mid_query"
ERR_UNKNOWN = "unknown_error"

# need for ha ip dns validation, to avoid false positives
KNOWN_DOMAINS = [
    "fritz.box",
    "local",
    "lan",
    "home",
    "speedport.ip",
    "tplinkwifi.net",
    "home.arpa",
    "mshome.net",
    "internal",
]

DEFAULT_DEVICE_NAME = "TrueNAS"
DEFAULT_SSL_VERIFY = False
DEFAULT_CRONJOB_SKIP_DISABLED = True
DEFAULT_DATA_UNIT = "GiB"
ALLOWED_DATA_UNITS = ["GB", "GiB"]

TO_REDACT = {
    "password",
    "encryption_password",
    "encryption_salt",
    "host",
    "api_key",
    "serial",
    "system_serial",
    "ip4_addr",
    "ip6_addr",
    "account",
    "key",
}

SERVICE_CLOUDSYNC_RUN = "cloudsync_run"
SCHEMA_SERVICE_CLOUDSYNC_RUN = {}

SERVICE_CLOUDSYNC_ABORT = "cloudsync_abort"
SCHEMA_SERVICE_CLOUDSYNC_ABORT = {}

SERVICE_DATASET_SNAPSHOT = "dataset_snapshot"
SCHEMA_SERVICE_DATASET_SNAPSHOT = {}

SERVICE_SYSTEM_REBOOT = "system_reboot"
SCHEMA_SERVICE_SYSTEM_REBOOT = {}

SERVICE_SYSTEM_SHUTDOWN = "system_shutdown"
SCHEMA_SERVICE_SYSTEM_SHUTDOWN = {}

CONF_CRONJOB_SKIP_DISABLED = "cronjob_skip_disabled"
CONF_DATA_UNIT = "data_unit"

SERVICE_SERVICE_START = "service_start"
SCHEMA_SERVICE_SERVICE_START = {}
SERVICE_SERVICE_STOP = "service_stop"
SCHEMA_SERVICE_SERVICE_STOP = {}
SERVICE_SERVICE_RESTART = "service_restart"
SCHEMA_SERVICE_SERVICE_RESTART = {}
SERVICE_SERVICE_RELOAD = "service_reload"
SCHEMA_SERVICE_SERVICE_RELOAD = {}

SERVICE_VM_START = "vm_start"
SERVICE_VM_START_OVERCOMMIT = "overcommit"
SCHEMA_SERVICE_VM_START = {
    vol.Optional(SERVICE_VM_START_OVERCOMMIT, default=False): cv.boolean
}
SERVICE_VM_STOP = "vm_stop"
SCHEMA_SERVICE_VM_STOP = {}

SERVICE_APP_START = "app_start"
SCHEMA_SERVICE_APP_START = {}
SERVICE_APP_STOP = "app_stop"
SCHEMA_SERVICE_APP_STOP = {}

ERROR_API_FORMAT = "TrueNAS %s API error: %s"
ICON_GAUGE = "mdi:gauge"
