"""TrueNAS API."""

import json
import re
import socket
import ssl
import time
from logging import getLogger
from threading import RLock
from typing import Any

from websockets.exceptions import (
    InvalidStatusCode,
    NegotiationError,
    WebSocketException,
)
from websockets.sync.client import ClientConnection, connect

from .const import (
    ERR_API_NOT_FOUND,
    ERR_CERT_VERIFY_FAILED,
    ERR_CONNECTION_REFUSED,
    ERR_HANDSHAKE_TIMEOUT,
    ERR_HTTP_USED,
    ERR_INVALID_HOSTNAME,
    ERR_INVALID_KEY,
    ERR_LOST_LOGIN,
    ERR_LOST_QUERY,
    ERR_MALFORMED_RESULT,
    ERR_TIMEOUT,
    ERR_TLS_NOT_SUPPORTED,
    ERR_UNKNOWN,
    ERR_UNKNOWN_HOSTNAME,
    ERR_WS_NOT_SUPPORTED,
    QUERY_TIMEOUT,
)

_LOGGER = getLogger(__name__)


# ---------------------------
#   TrueNASAPI
# ---------------------------
class TrueNASAPI:
    """Handle all communication with TrueNAS."""

    def __init__(
        self,
        host: str,
        username: str,
        api_key: str,
        verify_ssl: bool = True,
        scheme: str = "wss",
    ) -> None:
        """Initialize the TrueNAS API."""
        scheme = scheme.lower()
        if scheme not in ("ws", "wss"):
            raise ValueError(
                f"Invalid WebSocket scheme '{scheme}'. Expected 'ws' or 'wss'."
            )
        self._host = host
        self._username = username
        self._api_key = api_key
        self._scheme = scheme
        self._url = f"{self._scheme}://{self._host}/websocket"

        if self._scheme == "wss":
            self._ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            self._ssl_context.minimum_version = ssl.TLSVersion.TLSv1_2
            if verify_ssl:
                self._ssl_context.check_hostname = True
                self._ssl_context.verify_mode = ssl.CERT_REQUIRED
            else:
                # Insecure configuration: certificate validation and hostname
                # checking are disabled. This must only be used in trusted
                # environments (e.g. local networks) and never exposed to
                # untrusted networks, as it is vulnerable to MITM attacks.
                _LOGGER.warning(
                    "TrueNAS WebSocket configured with verify_ssl=False for '%s'. "
                    "This disables TLS certificate verification and hostname "
                    "checking and should only be used in trusted environments.",
                    self._host,
                )
                self._ssl_context.check_hostname = False
                self._ssl_context.verify_mode = ssl.CERT_NONE
        else:
            self._ssl_context = None

        self._lock = RLock()
        # Lock ordering: If both locks are needed, _io_lock MUST be acquired
        # BEFORE _lock to prevent deadlocks. _lock is for fast state updates only.
        self._io_lock = RLock()
        self._connected = False
        self._error = ""
        self._error_logged = False
        self._next_rpc_id = 1
        self._ws: ClientConnection | None = None

    def _extract_status_code(self, exc: BaseException) -> int | None:
        """Try to extract a numeric status code from a known exception shape.

        Only use attributes that are known to represent HTTP-like status codes
        to avoid misinterpreting unrelated numeric codes (e.g. errno values).
        """
        if isinstance(exc, InvalidStatusCode):
            return exc.status_code

        if isinstance(exc, WebSocketException):
            status = getattr(exc, "status", None)
            if isinstance(status, int):
                return status
            status_code = getattr(exc, "status_code", None)
            if isinstance(status_code, int):
                return status_code
        return None

    def _get_connection_error(self, exception: Exception) -> str | None:
        if isinstance(exception, ssl.SSLCertVerificationError):
            return ERR_CERT_VERIFY_FAILED
        if isinstance(exception, socket.gaierror):
            return ERR_UNKNOWN_HOSTNAME
        if isinstance(exception, ConnectionRefusedError):
            return ERR_CONNECTION_REFUSED
        if isinstance(exception, TimeoutError):
            return ERR_HANDSHAKE_TIMEOUT

        status = self._extract_status_code(exception)
        if status in (401, 403):
            return ERR_INVALID_KEY
        if status == 404:
            return ERR_API_NOT_FOUND

        msg = str(exception)
        normalized = msg.strip().lower()

        if "certificate_verify_failed" in normalized:
            return ERR_CERT_VERIFY_FAILED
        if "plain http request was sent to https port" in normalized:
            return ERR_HTTP_USED
        if "tlsv1_unrecognized_name" in normalized:
            return ERR_TLS_NOT_SUPPORTED
        if "no websocket upgrade" in normalized:
            return ERR_WS_NOT_SUPPORTED
        if "connection refused" in normalized:
            return ERR_CONNECTION_REFUSED
        if "no route to host" in normalized:
            return ERR_INVALID_HOSTNAME
        if "timed out while waiting for handshake response" in normalized:
            return ERR_HANDSHAKE_TIMEOUT

        return None

    def _log_error(
        self,
        message: str,
        exception: Exception,
        *,
        logged_flag: dict | None = None,
    ) -> None:
        """Log an error only once per scope.

        Uses a fixed format to avoid formatting issues.
        """
        if logged_flag is not None:
            if logged_flag.get("logged"):
                return
            _LOGGER.error(
                "Error while communicating with host %s: %s",
                self._host,
                message,
                exc_info=exception,
            )
            logged_flag["logged"] = True
            return

        if not self._error_logged:
            _LOGGER.error(
                "Error while communicating with host %s: %s",
                self._host,
                message,
                exc_info=exception,
            )

        self._error_logged = True

    def _fail_connection(
        self, message: str, error: Exception, error_state: dict
    ) -> bool:
        """Log fatal error and disconnect."""
        self._log_error(message, error, logged_flag=error_state)
        self.disconnect()
        return False

    def _handle_query_error(self, res: dict) -> bool:
        """Handle JSON-RPC query error response."""
        error = res.get("error")
        if not error:
            return False

        if not isinstance(error, dict):
            with self._lock:
                self._error = str(error)
            _LOGGER.error("TrueNAS %s API error: %s", self._host, error)
            return True

        err_message = error.get("message")
        data = error.get("data")
        reason = data.get("reason") if isinstance(data, dict) else None

        with self._lock:
            self._error = reason or err_message or ERR_UNKNOWN

        if err_message and reason:
            _LOGGER.error(
                "TrueNAS %s API error: %s (%s)",
                self._host,
                err_message,
                reason,
            )
        elif err_message:
            _LOGGER.error(
                "TrueNAS %s API error: %s",
                self._host,
                err_message,
            )
        else:
            _LOGGER.error(
                "TrueNAS %s API error: %s",
                self._host,
                error,
            )

        return True

    # ---------------------------
    #   _establish_websocket
    # ---------------------------
    def _establish_websocket(self, kwargs: dict[str, Any]) -> ClientConnection:
        """Establish the WebSocket connection, handling subprotocol negotiation."""
        try:
            return connect(self._url, **kwargs)
        except NegotiationError as e:
            if "no subprotocols supported" not in str(e):
                raise e

            kwargs["subprotocols"] = ["__extract__"]
            try:
                return connect(self._url, **kwargs)
            except NegotiationError as e2:
                return self._handle_negotiation_error(e, e2, kwargs)

    def _handle_negotiation_error(
        self, e: Exception, e2: NegotiationError, kwargs: dict[str, Any]
    ) -> ClientConnection:
        """Extract the expected subprotocol and retry the connection."""
        msg2 = str(e2)

        # We currently have to rely on the error message format from the
        # websockets library. Parse this defensively and bail out if we cannot
        # safely extract a reasonable subprotocol token.
        marker = "unsupported subprotocol: "
        parts = msg2.split(marker, 1)
        if len(parts) < 2:
            _LOGGER.warning(
                "Failed to parse NegotiationError subprotocol (missing '%s'): %s",
                marker,
                msg2,
            )
            raise e2 from e

        tail = parts[1].strip()
        # Strip at common delimiters to avoid feeding arbitrary or composite
        # values back into connect. This keeps only the first token-like value.
        for sep in (",", ";", " "):
            if sep in tail:
                tail = tail.split(sep, 1)[0].strip()

        subp = tail
        if not subp or not re.match(r"^[a-zA-Z0-9_\-\.]+$", subp):
            _LOGGER.warning(
                "Extracted NegotiationError subprotocol is invalid: %r (msg: %s)",
                subp,
                msg2,
            )
            raise e2 from e

        kwargs["subprotocols"] = [subp]
        return connect(self._url, **kwargs)

    def _wait_for_message(
        self,
        ws: ClientConnection,
        match_key: str,
        match_val: str,
        timeout_msg: str,
        error_state: dict,
        timeout: float = 10.0,
    ) -> dict[str, Any] | None:
        """Wait for a specific message from WebSocket.

        Note: The caller holds _io_lock, ensuring no concurrent RPCs are in flight.
        Any unmatched messages are unsolicited server events and can be safely ignored.
        """
        deadline = time.time() + timeout
        while True:
            timeout = deadline - time.time()
            try:
                if timeout <= 0:
                    raise TimeoutError
                message = ws.recv(timeout=timeout)
            except TimeoutError as e:
                self._fail_connection(timeout_msg, e, error_state)
                return None

            if not isinstance(message, str):
                continue

            try:
                candidate = json.loads(message)
            except json.JSONDecodeError:
                continue

            if str(candidate.get(match_key)) == match_val:
                return candidate

    def _log_login_failure(self, result: dict) -> None:
        """Extract and log login failure details."""
        error_reason = result.get("reason")
        error_message = result.get("message")

        if not error_reason or not error_message:
            error_obj = result.get("error") or result.get("errors")
            if isinstance(error_obj, dict):
                error_reason = (
                    error_reason or error_obj.get("reason") or error_obj.get("code")
                )
                error_message = (
                    error_message or error_obj.get("message") or error_obj.get("detail")
                )
            elif (
                isinstance(error_obj, list)
                and error_obj
                and isinstance(error_obj[0], dict)
            ):
                error_reason = (
                    error_reason
                    or error_obj[0].get("reason")
                    or error_obj[0].get("code")
                )
                error_message = (
                    error_message
                    or error_obj[0].get("message")
                    or error_obj[0].get("detail")
                )

        response_type = (
            result.get("response_type") if isinstance(result, dict) else None
        )

        if error_reason or error_message or response_type:
            _LOGGER.warning(
                "TrueNAS login failed for %s. Check API key and permissions.",
                self._host,
            )
            _LOGGER.debug(
                "TrueNAS login failure details for %s: response_type=%s, %s%s",
                self._host,
                response_type,
                f"{error_reason}: " if error_reason else "",
                error_message or "",
            )
        else:
            _LOGGER.warning(
                "TrueNAS login failed for %s with non-success response.",
                self._host,
            )
            res_str = str(result)
            _LOGGER.debug(
                "TrueNAS login failure payload for %s: %s",
                self._host,
                f"{res_str[:250]}..." if len(res_str) > 250 else res_str,
            )

    # ---------------------------
    #   _perform_login
    # ---------------------------
    def _perform_login(self, error_state: dict) -> bool:
        """Perform login and return boolean success."""
        with self._lock:
            rpc_id = self._next_rpc_id
            self._next_rpc_id += 1
            ws = self._ws

        if not ws:
            return False

        with self._io_lock:
            # Acquire _lock inside _io_lock (following lock ordering)
            with self._lock:
                if self._ws is not ws:
                    self._error = ERR_LOST_LOGIN
                    _LOGGER.warning(
                        "TrueNAS %s WebSocket changed mid-login", self._host
                    )
                    return False

            try:
                ws.send(
                    json.dumps({"msg": "connect", "version": "1", "support": ["1"]})
                )
            except (OSError, TimeoutError, WebSocketException) as e:
                return self._fail_connection(
                    "failed to send connect message", e, error_state
                )

            if not self._wait_for_message(
                ws,
                "msg",
                "connected",
                "timeout while waiting for connect response",
                error_state,
                timeout=30.0,
            ):
                return False

            payload = {
                "msg": "method",
                "method": "auth.login_ex",
                "id": str(rpc_id),
                "params": [
                    {
                        "mechanism": "API_KEY_PLAIN",
                        "username": self._username,
                        "api_key": self._api_key,
                        "login_options": {"user_info": False},
                    }
                ],
            }

            try:
                ws.send(json.dumps(payload))
            except (OSError, TimeoutError, WebSocketException) as e:
                return self._fail_connection(
                    "failed to send login message", e, error_state
                )

            res = self._wait_for_message(
                ws,
                "id",
                str(rpc_id),
                "timeout while waiting for login response",
                error_state,
                timeout=30.0,
            )
            if res is None:
                return False

        result = res.get("result")
        connected = False

        if isinstance(result, dict):
            if result.get("response_type") == "SUCCESS":
                connected = True
            else:
                self._log_login_failure(result)
        elif isinstance(result, bool):
            connected = result
        else:
            _LOGGER.warning(
                "Unexpected TrueNAS login result type for %s: %r",
                self._host,
                result,
            )

        if not connected:
            with self._lock:
                self._error = ERR_INVALID_KEY
            self.disconnect()

        return connected

    # ---------------------------
    #   connect
    # ---------------------------
    def connect(self) -> bool:
        """Return connected boolean."""
        with self._lock:
            if self._connected:
                return True
            self._error = ""
            self._error_logged = False

        error_state = {"logged": False}

        try:
            kwargs = {
                "max_size": 16777216,
                "ping_interval": 20,
                "open_timeout": 60,
            }
            if self._scheme == "wss":
                kwargs["ssl"] = self._ssl_context

            ws = self._establish_websocket(kwargs)
        except (OSError, TimeoutError, WebSocketException) as e:
            with self._lock:
                self._error = self._get_connection_error(e) or ERR_UNKNOWN
            self._log_error("failed to connect", e, logged_flag=error_state)
            return False

        with self._lock:
            self._ws = ws

        try:
            connected = self._perform_login(error_state)
        except (OSError, TimeoutError, WebSocketException) as e:
            return self._fail_connection("failed to login", e, error_state)

        if not connected:
            self.disconnect()
            return False

        with self._lock:
            self._connected = True
            return True

    # ---------------------------
    #   disconnect
    # ---------------------------
    def disconnect(self) -> None:
        """Close the WebSocket connection."""
        with self._lock:
            ws = self._ws
            self._ws = None
            self._connected = False

        if ws:
            try:
                ws.close()
            except Exception as exc:
                _LOGGER.debug("Error while closing WebSocket connection: %s", exc)

    # ---------------------------
    #   reconnect
    # ---------------------------
    def reconnect(self) -> bool:
        """Return connected boolean."""
        self.disconnect()
        return self.connect()

    # ---------------------------
    #   connected
    # ---------------------------
    def connected(self) -> bool:
        """Return connected boolean."""
        with self._lock:
            return self._connected

    # ---------------------------
    #   connection_test
    # ---------------------------
    def connection_test(self) -> tuple[bool, str]:
        """Test connection."""
        if not self.connect():
            with self._lock:
                return self._connected, self._error

        try:
            result = self.query("system.info")
        except (OSError, TimeoutError, WebSocketException) as exc:
            with self._lock:
                self._connected = False
                self._error = self._get_connection_error(exc) or ERR_UNKNOWN
                return self._connected, self._error

        if result is None:
            with self._lock:
                self._connected = False
                if not self._error:
                    self._error = ERR_MALFORMED_RESULT

        with self._lock:
            return self._connected, self._error

    # ---------------------------
    #   query
    # ---------------------------
    def query(
        self,
        service: str,
        params: dict[str, Any] | list[Any] | None = None,
    ) -> list | dict | str | None:
        """Retrieve data from TrueNAS.

        Uses _io_lock to ensure only one in-flight RPC exists at a time. Unrelated
        messages received during the wait are unsolicited events and are ignored.
        """
        if params is None:
            params = []

        if not self.connected() and not self.connect():
            return None

        with self._lock:
            self._error = ""
            ws = self._ws
            if not self._connected or not ws:
                return None

            rpc_id = self._next_rpc_id
            self._next_rpc_id += 1

        try:
            _LOGGER.debug(
                "TrueNAS %s query: %s, %s",
                self._host,
                service,
                params,
            )

            payload = {
                "msg": "method",
                "method": service,
                "id": str(rpc_id),
                "params": [],
            }
            if params:
                if not isinstance(params, list):
                    params = [params]
                payload["params"] = params

            with self._io_lock:
                # Acquire _lock inside _io_lock (following lock ordering)
                with self._lock:
                    if self._ws is not ws:
                        self._error = ERR_LOST_QUERY
                        _LOGGER.warning(
                            "TrueNAS %s WebSocket changed mid-query for %s",
                            self._host,
                            service,
                        )
                        return None

                ws.send(json.dumps(payload))

                res: dict[str, Any] | None = None
                deadline = time.time() + QUERY_TIMEOUT
                while True:
                    timeout = deadline - time.time()
                    try:
                        if timeout <= 0:
                            raise TimeoutError
                        message = ws.recv(timeout=timeout)
                    except TimeoutError:
                        _LOGGER.error(
                            "TrueNAS %s timeout while waiting for query response",
                            self._host,
                        )
                        with self._lock:
                            self._error = ERR_TIMEOUT
                        self.disconnect()
                        return None

                    if not isinstance(message, str):
                        _LOGGER.debug(
                            "TrueNAS %s: ignoring non-string WebSocket message: %r",
                            self._host,
                            message,
                        )
                        continue

                    try:
                        candidate = json.loads(message)
                    except json.JSONDecodeError as exc:
                        _LOGGER.debug(
                            "TrueNAS %s: ignoring malformed JSON WebSocket "
                            "message: %r (%s)",
                            self._host,
                            message,
                            exc,
                        )
                        continue

                    if str(candidate.get("id")) != str(rpc_id):
                        _LOGGER.debug(
                            "TrueNAS %s: received unrelated WebSocket message "
                            "(id=%r) while waiting for id=%r: %s",
                            self._host,
                            candidate.get("id"),
                            rpc_id,
                            candidate,
                        )
                        continue

                    res = candidate
                    break

            if res is not None and self._handle_query_error(res):
                return None

            data = res.get("result") if res else None
            if data is None:
                return None

            _LOGGER.debug(
                "TrueNAS %s query (%s) response: %s", self._host, service, data
            )
        except (OSError, TimeoutError, WebSocketException) as e:
            # Catch only real system errors, e.g., connection loss
            _LOGGER.warning(
                'TrueNAS %s unable to fetch data "%s" (%s)',
                self._host,
                service,
                e,
            )
            self.disconnect()
            with self._lock:
                self._error = self._get_connection_error(e) or ERR_UNKNOWN
            return None

        return data

    @property
    def error(self):
        """Return error."""
        with self._lock:
            return self._error
