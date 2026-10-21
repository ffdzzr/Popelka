"""Transport layers: local (tinytuya) and cloud (Tuya IoT API).

Two ways to talk to the Concept VR3125:

* **local** - the robot exposes the Tuya local protocol on TCP/6668.  With the
  device's local key you can read and write DPs straight from your LAN, no
  cloud involved.  This is the interesting one for reverse engineering because
  DP15 payloads are the actual binary commands.
* **cloud** - the Tuya IoT API.  Needed for the map files, which the robot
  uploads over the P2P channel and never sends over the local socket.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from .commands import CommandPlan

#: Tuya regional API hosts.
REGION_HOSTS = {
    "eu": "openapi.tuyaeu.com",
    "us": "openapi.tuyaus.com",
    "cn": "openapi.tuyaeu.com",
    "in": "openapi-ueazh.tuyaus.com",
    "we": "openapi-ueazh.tuyaus.com",
}


class TuyaError(RuntimeError):
    pass


# --------------------------------------------------------------------------
# Local protocol (port 6668)
# --------------------------------------------------------------------------
@dataclass
class LocalDevice:
    """Thin wrapper over tinytuya's local connection."""

    ip: str
    local_key: str
    device_id: str = ""
    port: int = 6668
    version: str = "3.3"

    def _connect(self):
        try:
            import tinytuya
        except ImportError as exc:  # pragma: no cover
            raise TuyaError("tinytuya is not installed") from exc
        client = tinytuya.TuyaDevice(
            self.device_id,
            self.ip,
            self.local_key,
            connection_timeout=5,
            retries=1,
            protocol_version=int(self.version.replace(".", "")),
            port=self.port,
        )
        if not client.connect():
            raise TuyaError(f"cannot connect to {self.ip}:{self.port}")
        return client

    def status(self) -> dict:
        client = self._connect()
        try:
            return client.status() or {}
        finally:
            client.disconnect()

    def dps(self) -> dict[int, str]:
        """Return {dp_id: raw value} as strings (raw DPs stay hex)."""
        out: dict[int, str] = {}
        status = self.status()
        for dp_id, payload in status.items():
            try:
                value = payload.get("value")
            except AttributeError:
                continue
            if isinstance(value, (bytes, bytearray)):
                out[int(dp_id)] = value.hex()
            else:
                out[int(dp_id)] = value
        return out

    def set_dp(self, dp_id: int, value, raw: bool = False) -> None:
        client = self._connect()
        try:
            ok = client.set_dp_value(
                dp_id,
                value,
                raw_type="raw" if raw else None,
                value_type=None if raw else None,
            )
            if ok is False:
                raise TuyaError(f"failed to set DP{dp_id}")
        finally:
            client.disconnect()

    def send_raw_dp15(self, payload: bytes) -> None:
        """Write a raw DP15 payload (the binary protocol channel)."""
        self.set_dp(15, payload, raw=True)

    def execute_plan(self, plan: CommandPlan, delay: float = 0.25) -> None:
        """Run a command plan: write each DP15 payload, then DP1/DP4."""
        client = self._connect()
        try:
            for payload in plan.dp15:
                client.set_dp_value(15, payload, raw_type="raw")
                time.sleep(delay)
            client.set_dp_value(1, plan.power_go)
            time.sleep(delay)
            client.set_dp_value(4, plan.mode)
        finally:
            client.disconnect()


# --------------------------------------------------------------------------
# Cloud (Tuya IoT API)
# --------------------------------------------------------------------------
class CloudClient:
    """Minimal Tuya IoT API client (token + a few read-only endpoints)."""

    def __init__(self, access_token: str, region: str = "eu", host: str | None = None):
        self.access_token = access_token
        self.host = host or REGION_HOSTS.get(region, REGION_HOSTS["eu"])

    def _request(self, method: str, path: str, params: dict | None = None, body: dict | None = None) -> dict:
        url = f"https://{self.host}{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", f"Bearer {self.access_token}")
        if data:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            raise TuyaError(f"{method} {url} -> HTTP {exc.code}: {exc.read().decode(errors='replace')}") from exc
        except urllib.error.URLError as exc:
            raise TuyaError(f"{method} {url} -> {exc.reason}") from exc

    def devices(self, user_id: str = "") -> list[dict]:
        path = f"/v2.0/iot/users/{user_id}/devices" if user_id else "/v1.0/users/devices"
        result = self._request("GET", path)
        return result.get("result") or []

    def device_status(self, device_id: str) -> dict:
        return (self._request("GET", f"/v2.0/iot/users/-/devices/{device_id}/status") or {}).get("result", {})

    def realtime_map(self, device_id: str) -> list[dict]:
        return (
            self._request("GET", f"/v1.0/users/sweepers/file/{device_id}/realtime-map") or {}
        ).get("result", []) or []

    def map_files(self, device_id: str, page: int = 1, size: int = 20) -> list[dict]:
        result = (
            self._request(
                "GET",
                f"/v1.0/users/sweepers/file/{device_id}/list",
                {"file_type": "pic", "page_no": page, "page_size": size},
            )
            or {}
        ).get("result", {}) or {}
        return result.get("file_list", []) if isinstance(result, dict) else []

    def download_map(self, device_id: str, file_id: str) -> dict:
        return (
            self._request("GET", f"/v1.0/users/sweepers/file/{device_id}/download", {"id": file_id}) or {}
        ).get("result", {}) or {}
