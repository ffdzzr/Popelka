"""Tuya IoT cloud client: login, device discovery, DP dumping, map download.

Two login flows are supported:

``grant_type=1`` (what the vendor apps use)
    ``POST /v1.0/token?grant_type=1`` with base64 username/password.  No app
    key needed, returns a token plus the user's ``uid``.

signed v2.0
    ``POST /v2.0/auth/token`` with ``client_id``/``sign`` headers, where the
    signature is HMAC-SHA256 over the sorted params.  Needed when the account
    is only authorised for a specific app (the Concept Home app key).

The interesting part is ``devices()``: the user device list contains the
device's **local key**, which unlocks direct LAN control on TCP 6668.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

#: Regional API hosts.  ``we``/``eu`` both point at the European cluster.
REGION_HOSTS = {
    "eu": "openapi.tuyaeu.com",
    "we": "openapi.tuyaeu.com",
    "us": "openapi.tuyaus.com",
    "in": "openapi-ueazh.tuyaus.com",
    "cn": "openapi.tuyaeu.com",
}

COUNTRY_CODES = {
    "eu": "84",  # Germany
    "we": "44",  # UK
    "us": "1",  # USA
    "cn": "86",
}


class CloudError(RuntimeError):
    pass


@dataclass
class Account:
    """A logged-in Tuya account."""

    username: str = ""
    password: str = ""
    region: str = "eu"
    client_id: str = ""
    client_secret: str = ""
    host: str = ""
    country_code: str = ""
    access_token: str = ""
    uid: str = ""
    extra: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.host:
            self.host = REGION_HOSTS.get(self.region, REGION_HOSTS["eu"])
        if not self.country_code:
            self.country_code = COUNTRY_CODES.get(self.region, "84")

    # -- plumbing ---------------------------------------------------------
    def _url(self, path: str, params: dict | None = None) -> str:
        url = f"https://{self.host}{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        return url

    def _sign(self, params: dict, body: dict | None = None) -> dict:
        """HMAC-SHA256 signature headers for the v2.0 API."""
        ts = str(int(time.time() * 1000))
        payload = {k: str(v) for k, v in (params or {}).items()}
        payload.update({k: str(v) for k, v in (body or {}).items()})
        payload["client_id"] = self.client_id
        payload["t"] = ts
        to_sign = "".join(f"{k}{payload[k]}" for k in sorted(payload))
        sign = hmac.new(
            self.client_secret.encode(), to_sign.encode(), hashlib.sha256
        ).hexdigest().upper()
        return {
            "client_id": self.client_id,
            "sign": sign,
            "t": ts,
            "sign_method": "HMAC-SHA256",
            "nonce": base64.b64encode(time.ctime().encode()).decode()[:16],
        }

    def _http(
        self,
        method: str,
        path: str,
        params: dict | None = None,
        body: dict | None = None,
        signed: bool = False,
    ) -> dict:
        url = self._url(path, params)
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if self.access_token:
            req.add_header("Authorization", f"Bearer {self.access_token}")
        if signed:
            for k, v in self._sign(params or {}, body).items():
                req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")
            raise CloudError(f"{method} {url} -> HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise CloudError(f"{method} {url} -> {exc.reason}") from exc

    # -- api --------------------------------------------------------------
    def login(self) -> dict:
        """Log in and fill in ``access_token`` / ``uid``."""
        body = {
            "username": base64.b64encode(self.username.encode()).decode(),
            "password": base64.b64encode(self.password.encode()).decode(),
            "country_code": self.country_code,
        }
        try:
            res = self._http("POST", "/v1.0/token", {"grant_type": "1"}, body)
        except CloudError:
            if not self.client_id or not self.client_secret:
                raise
            res = self._http(
                "POST",
                "/v2.0/auth/token",
                None,
                {
                    "grant_type": "1",
                    "username": base64.b64encode(self.username.encode()).decode(),
                    "password": base64.b64encode(self.password.encode()).decode(),
                    "country_code": self.country_code,
                },
                signed=True,
            )
        result = res.get("result") or {}
        if not result.get("access_token"):
            raise CloudError(f"login failed: {res}")
        self.access_token = result["access_token"]
        self.uid = str(result.get("uid", ""))
        self.extra = result
        return result

    def _authed(self, method: str, path: str, params: dict | None = None) -> dict:
        if not self.access_token:
            self.login()
        return self._http(method, path, params)

    def devices(self) -> list[dict]:
        """Devices bound to this account.

        Each entry usually carries ``id``, ``name``, ``product_name``,
        ``category`` and - the valuable bit - ``local_key`` and ``ip``.
        """
        res = self._authed("GET", f"/v1.0/users/{self.uid}/devices")
        return res.get("result") or []

    def device(self, device_id: str) -> dict:
        res = self._authed("GET", f"/v1.0/users/{self.uid}/devices/{device_id}")
        return res.get("result") or {}

    def status(self, device_id: str) -> dict:
        """Current datapoint values (DP id -> {code, value})."""
        res = self._authed("GET", f"/v2.0/iot/users/{self.uid}/devices/{device_id}/status")
        return res.get("result") or {}

    def dp_names(self, device_id: str) -> dict:
        """DP id -> human readable name, from the device spec."""
        res = self._authed("GET", f"/v2.0/iot/users/{self.uid}/devices/{device_id}/specs")
        result = res.get("result") or {}
        services = result.get("services") or []
        out: dict[str, str] = {}
        for service in services:
            for dp in service.get("dp") or []:
                out[str(dp.get("id"))] = dp.get("code", "")
        return out

    # -- maps -------------------------------------------------------------
    def realtime_map(self, device_id: str) -> list[dict]:
        res = self._authed("GET", f"/v1.0/users/sweepers/file/{device_id}/realtime-map")
        return res.get("result") or []

    def map_files(self, device_id: str, page: int = 1, size: int = 20) -> list[dict]:
        res = self._authed(
            "GET",
            f"/v1.0/users/sweepers/file/{device_id}/list",
            {"file_type": "pic", "page_no": page, "page_size": size},
        )
        result = res.get("result") or {}
        return result.get("file_list", []) if isinstance(result, dict) else []

    def download_map(self, device_id: str, file_id: str) -> dict:
        res = self._authed(
            "GET", f"/v1.0/users/sweepers/file/{device_id}/download", {"id": file_id}
        )
        return res.get("result") or {}

    def fetch_map_bytes(self, device_id: str, file_id: str) -> bytes:
        info = self.download_map(device_id, file_id)
        url = info.get("robot_map") or info.get("app_map")
        if not url:
            raise CloudError(f"no map url in response: {info}")
        with urllib.request.urlopen(url, timeout=60) as resp:
            return resp.read()


def load_account(env: dict | None = None, **overrides) -> Account:
    """Build an :class:`Account` from environment variables.

    ``TUYA_USER``, ``TUYA_PASS``, ``TUYA_REGION``, ``TUYA_CLIENT_ID``,
    ``TUYA_CLIENT_SECRET``.  Overrides win over the environment.
    """
    import os

    env = env if env is not None else dict(os.environ)
    values = {
        "username": env.get("TUYA_USER", ""),
        "password": env.get("TUYA_PASS", ""),
        "region": env.get("TUYA_REGION", "eu"),
        "client_id": env.get("TUYA_CLIENT_ID", ""),
        "client_secret": env.get("TUYA_CLIENT_SECRET", ""),
    }
    values.update({k: v for k, v in overrides.items() if v})
    return Account(**values)
