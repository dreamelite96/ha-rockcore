"""🔌 Async client for the Rockcore RC-C cloud API.

The RC-C mobile app (``studio.yanxinalircc.com``) is a thin wrapper around the
web app hosted at ``https://app.rc-ess.com``. That web app talks to a JowoIoT
backend under ``/jowoiot-proxy/api/project/rc``. This module speaks the same
protocol, using only the read-only endpoints.

🔐 Authentication
-----------------
``POST /auth/login`` takes the e-mail/username and the *plain* password and
returns a JWT (valid for a year) plus the numeric owner id.

* It also requires the ``oem`` header to pick the tenant. Without it the login
  fails with ``code 500 / "Not a null user"``, which reads like a
  bad-credentials error but is not.
* Every later request needs both ``Authorization: Bearer <token>`` and an
  ``OwnerId`` header. Without the latter the backend answers
  ``400 / "Ownerid in http header can't be null"``.
* An expired or invalid token yields a bare ``401``.

⚠️ The backend locks the account after ten consecutive bad passwords, so
callers must never retry a :class:`RockcoreAuthError` in a loop.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import logging
import time
from typing import Any
from urllib.parse import quote

import aiohttp
from aiohttp import ClientError, ClientResponseError, ClientSession

from .const import (
    ALARM_MAX_PAGES,
    ALARM_PAGE_SIZE,
    API_BASE,
    API_OEM,
    API_SCOPE,
    REQUEST_TIMEOUT,
)

_LOGGER = logging.getLogger(__name__)


def _path_id(value: Any) -> str:
    """🧱 Make an id returned by the cloud safe to embed in a URL path.

    The ids come from the backend, not from the user, but nothing guarantees
    they never contain ``/`` or ``..``. Quoting keeps each one a single path
    segment, so it can never point at a different endpoint.
    """
    return quote(str(value), safe="")


# ─────────────────────────────────────────────────────────────────────────────
# 🚦 Exceptions
# ─────────────────────────────────────────────────────────────────────────────


class RockcoreError(Exception):
    """Base error for the Rockcore cloud API."""


class RockcoreConnectionError(RockcoreError):
    """📡 The cloud could not be reached, or answered with something unusable."""


class RockcoreAuthError(RockcoreError):
    """🔒 The credentials were rejected.

    Never retried automatically: the backend counts failed attempts and locks
    the account after ten of them.
    """


# ─────────────────────────────────────────────────────────────────────────────
# 🌐 Client
# ─────────────────────────────────────────────────────────────────────────────


class RockcoreClient:
    """Minimal async client covering the read-only endpoints of the RC-C app."""

    def __init__(
        self,
        session: ClientSession,
        email: str,
        password: str,
        *,
        timezone_offset: Callable[[], float] | None = None,
    ) -> None:
        """Initialise the client. No I/O happens here.

        ``timezone_offset`` is a callable returning the local UTC offset in
        hours. It is evaluated on every request, so a daylight saving change is
        followed without reloading the integration.
        """
        self._session = session
        self._email = email
        self._password = password
        self._timezone_offset = timezone_offset or (lambda: 0)

        # 🔒 Serialises logins, so a burst of 401s triggers a single re-login.
        self._login_lock = asyncio.Lock()
        # 📣 The "alarm list truncated" warning is logged only once.
        self._alarm_truncation_warned = False

        # 🔑 Filled in by a successful login.
        self._token: str | None = None
        self._user_id: str | None = None
        self._owner_id: str | None = None
        self._user_name: str | None = None
        self._area_id: str | None = None

    # ── 👤 Account details learned at login ──────────────────────────────────

    @property
    def user_id(self) -> str | None:
        """IoT user id (``usr_...``), stable per account."""
        return self._user_id

    @property
    def owner_id(self) -> str | None:
        """Numeric owner id required in the ``OwnerId`` header."""
        return self._owner_id

    @property
    def user_name(self) -> str | None:
        """Display name of the logged-in account."""
        return self._user_name

    @property
    def area_id(self) -> str | None:
        """Region id of the account, needed to filter alarms server-side."""
        return self._area_id

    # ── 🔐 Authentication ────────────────────────────────────────────────────

    def _headers(self, token: str | None = None) -> dict[str, str]:
        """Build the request headers; pass ``token`` for authenticated calls.

        💡 The token is handed in instead of being read from ``self``, so a
        concurrent re-login can never make a request go out as ``Bearer None``.
        """
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US",
            "Content-Type": "application/json;charset=utf-8",
            # ⚠️ Mandatory on /auth/login (it selects the OEM tenant). Dropping
            # it fails the login with a misleading code 500 "Not a null user".
            "oem": API_OEM,
            "scope": API_SCOPE,
            "Timezone-Offset": str(self._timezone_offset()),
        }
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
            headers["OwnerId"] = str(self._owner_id)
            if self._user_id:
                headers["userId"] = self._user_id
        return headers

    async def async_login(self) -> None:
        """Authenticate and cache the token, owner id and user id."""
        async with self._login_lock:
            await self._async_login_locked()

    async def _async_ensure_login(self, stale_token: str | None) -> None:
        """Log in, unless somebody else already replaced ``stale_token``.

        Requests run concurrently, so when the token expires they all see the
        401 together. Only the first one to get the lock performs a login; the
        others find a fresh token and simply reuse it.
        """
        async with self._login_lock:
            if self._token is not None and self._token != stale_token:
                return
            await self._async_login_locked()

    @staticmethod
    async def _async_read_body(resp: aiohttp.ClientResponse, what: str) -> dict[str, Any]:
        """📦 Decode a JSON object, turning anything else into a connection error.

        A proxy or maintenance page can answer ``200`` with HTML, and nothing
        stops the cloud from returning a bare list. Neither should surface as
        an unhandled ``ValueError`` or ``AttributeError``.
        """
        try:
            body = await resp.json(content_type=None)
        except ValueError as err:
            raise RockcoreConnectionError(f"{what} returned an unreadable response") from err
        if not isinstance(body, dict):
            raise RockcoreConnectionError(f"{what} returned an unexpected response")
        return body

    async def _async_login_locked(self) -> None:
        """Perform the login. The caller must already hold ``_login_lock``."""
        payload = {
            "channelType": 2,
            "content": self._email,
            "password": self._password,
            "type": "2",
        }
        try:
            async with self._session.post(
                f"{API_BASE}/auth/login",
                json=payload,
                headers=self._headers(),
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            ) as resp:
                if resp.status == 401:
                    raise RockcoreAuthError("Invalid e-mail or password")
                resp.raise_for_status()
                body = await self._async_read_body(resp, "Login")
        except ClientResponseError as err:
            raise RockcoreConnectionError(f"Login failed: HTTP {err.status}") from err
        except (ClientError, asyncio.TimeoutError) as err:
            raise RockcoreConnectionError(f"Cannot reach the Rockcore cloud: {err}") from err

        # 🔒 A rejected password comes back as HTTP 200 with code 500 in the body.
        # Every non-200 code is deliberately treated as a credentials problem:
        # the account locks after ten bad passwords, so a false "please
        # re-authenticate" prompt is much cheaper than a silent retry loop that
        # keeps sending a password the backend may already be rejecting.
        if body.get("code") != 200:
            message = body.get("message") or "Login rejected by the Rockcore cloud"
            raise RockcoreAuthError(message)

        data = body.get("data") or {}
        response = data.get("response") or {}
        token = response.get("accessToken")
        owner_id = (data.get("loginUser") or {}).get("id")
        if not token or not owner_id:
            raise RockcoreAuthError("Login response did not contain a token")

        self._token = token
        self._owner_id = str(owner_id)
        login_user = data.get("loginUser") or {}
        user = response.get("user") or {}
        self._user_id = user.get("userId")
        self._user_name = user.get("userName") or login_user.get("userName")
        area_id = login_user.get("areaId")
        self._area_id = str(area_id) if area_id is not None else None
        _LOGGER.debug("Logged in to the Rockcore cloud as %s", self._user_name)

    # ── 📨 Generic request ───────────────────────────────────────────────────

    async def _async_request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """Perform a request, logging in (once) if the token is missing or stale.

        Flow: log in if needed → send → on a 401 re-authenticate and retry once
        → unwrap the ``{"code": 200, "data": ...}`` envelope.
        """
        token = self._token
        if token is None:
            await self._async_ensure_login(None)
            token = self._token
        if token is None:
            raise RockcoreAuthError("Not authenticated")

        for attempt in range(2):
            try:
                async with self._session.request(
                    method,
                    f"{API_BASE}{path}",
                    json=json,
                    params=params,
                    headers=self._headers(token),
                    timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
                ) as resp:
                    if resp.status == 401:
                        # 🔁 Token expired or revoked: re-authenticate once,
                        # unless a concurrent request already did it for us.
                        if attempt == 0:
                            _LOGGER.debug("Token rejected on %s, re-authenticating", path)
                            await self._async_ensure_login(token)
                            token = self._token
                            if token is None:
                                raise RockcoreAuthError("Not authenticated")
                            continue
                        raise RockcoreAuthError("Token rejected after re-authentication")
                    resp.raise_for_status()
                    body = await self._async_read_body(resp, path)
            except ClientResponseError as err:
                raise RockcoreConnectionError(f"{path} failed: HTTP {err.status}") from err
            except (ClientError, asyncio.TimeoutError) as err:
                raise RockcoreConnectionError(f"{path} failed: {err}") from err

            if body.get("code") != 200:
                message = body.get("message") or f"code {body.get('code')}"
                raise RockcoreError(f"{path} rejected: {message}")
            return body.get("data")

        raise RockcoreConnectionError(f"{path} failed")

    # ── ☀️ Plants ────────────────────────────────────────────────────────────

    async def async_get_stations(self) -> list[dict[str, Any]]:
        """Return every plant visible to the account."""
        data = await self._async_request(
            "POST", "/station/overview/searchStation", json={"page": 1, "size": 100}
        )
        if not isinstance(data, dict):
            return []
        content = data.get("content")
        return content if isinstance(content, list) else []

    async def async_get_station(self, station_id: str) -> dict[str, Any]:
        """Return the live summary of one plant."""
        data = await self._async_request("GET", f"/station/item/show/{_path_id(station_id)}")
        return data if isinstance(data, dict) else {}

    async def async_get_station_info(self, station_id: str) -> dict[str, Any]:
        """Return the static configuration of one plant (location, timezone...).

        ℹ️ Not used by the integration at the moment; kept as a documented
        endpoint for future device metadata.
        """
        data = await self._async_request(
            "GET",
            f"/station/item/info/{_path_id(station_id)}",
            params={"commHost": "", "commPort": ""},
        )
        return data if isinstance(data, dict) else {}

    async def async_get_station_devices(self, station_id: str) -> list[dict[str, Any]]:
        """Return every inverter of a plant with its live power and daily yield."""
        devices: list[dict[str, Any]] = []
        page = 1
        while True:
            data = await self._async_request(
                "POST",
                "/station/item/page",
                json={"page": page, "size": 50, "stationId": str(station_id)},
            )
            if not isinstance(data, dict):
                break
            content = data.get("content")
            if not isinstance(content, list) or not content:
                break
            devices.extend(content)
            try:
                total = int(data.get("total", len(devices)))
            except (TypeError, ValueError):
                total = len(devices)
            if len(devices) >= total:
                break
            page += 1
        return devices

    # ── 🔋 Inverters ─────────────────────────────────────────────────────────

    async def async_get_device_data(self, org_id: str) -> dict[str, Any]:
        """Return the energy counters of one inverter."""
        data = await self._async_request("GET", f"/device/data/{_path_id(org_id)}")
        return data if isinstance(data, dict) else {}

    async def async_get_device_detail(self, org_id: str) -> dict[str, Any]:
        """Return live electrical values of one inverter, including its PV inputs."""
        data = await self._async_request("GET", f"/device/detail/{_path_id(org_id)}")
        return data if isinstance(data, dict) else {}

    # ── 🚨 Alarms ────────────────────────────────────────────────────────────

    async def async_get_active_alarms(self) -> list[dict[str, Any]]:
        """Return the alarms that have not recovered yet.

        Only ``/alarm-notice-set/pageByAreaId`` can filter on ``recovered``
        server-side, and it takes its filters as query parameters rather than a
        JSON body. Despite the name it is still scoped to what the account may
        see, so no foreign plants leak in.

        💡 The window starts at the epoch on purpose: alarms can stay active for
        weeks (the oldest one here dates from commissioning day), and a rolling
        window would silently drop them and under-report the count.
        """
        return await self._async_list_alarms(start_ms=0, recovered="false")

    async def async_get_recent_alarms(self, days: int) -> list[dict[str, Any]]:
        """Return every alarm of the last ``days``, recovered or not.

        The isolation analysis cannot reuse :meth:`async_get_active_alarms`: the
        alarms it needs are mostly the recovered ones (98% of the level 1 events
        on the reference plant), and they clear in about three minutes, far too
        fast for any poll interval to sample them as they happen.
        """
        start_ms = int((time.time() - days * 86400) * 1000)
        return await self._async_list_alarms(start_ms=start_ms, recovered=None)

    async def _async_list_alarms(
        self, *, start_ms: int, recovered: str | None
    ) -> list[dict[str, Any]]:
        """Page through ``pageByAreaId``, the only listing with server-side filters."""
        if not self._area_id:
            # Without a region the server-side filter cannot be used at all.
            return []

        alarms: list[dict[str, Any]] = []
        params: dict[str, Any] = {
            "size": ALARM_PAGE_SIZE,
            "start": start_ms,
            "end": int(time.time() * 1000),
            "areaId": self._area_id,
        }
        if recovered is not None:
            params["recovered"] = recovered

        for page in range(1, ALARM_MAX_PAGES + 1):
            data = await self._async_request(
                "POST", "/alarm-notice-set/pageByAreaId", params={**params, "page": page}
            )
            if not isinstance(data, dict):
                break
            content = data.get("content")
            if not isinstance(content, list) or not content:
                break
            alarms.extend(content)
            try:
                total = int(data.get("total", len(alarms)))
            except (TypeError, ValueError):
                total = len(alarms)
            if len(alarms) >= total:
                break
        else:
            # 📣 Logged once only: this runs on a timer and would otherwise
            # repeat forever.
            log = _LOGGER.debug if self._alarm_truncation_warned else _LOGGER.warning
            self._alarm_truncation_warned = True
            log(
                "Stopped after %s pages of alarms; the list may be truncated",
                ALARM_MAX_PAGES,
            )
        return alarms

    async def async_get_latest_alarm(self) -> dict[str, Any] | None:
        """Return the most recent alarm, recovered or not.

        ⚠️ ``orderByField`` only accepts 0 (time); 1 and 2 make the backend throw.
        """
        now_ms = int(time.time() * 1000)
        data = await self._async_request(
            "POST",
            "/alarm-notice-set/page",
            json={
                "page": 1,
                "row": 1,
                "start": 0,
                "end": now_ms,
                "orderByField": 0,
                "orderByAscOrDesc": 0,
            },
        )
        if not isinstance(data, dict):
            return None
        content = data.get("content")
        if isinstance(content, list) and content:
            return content[0]
        return None
