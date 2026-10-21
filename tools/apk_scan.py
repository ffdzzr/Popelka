#!/usr/bin/env python3
"""Static analysis of the Concept Home / Concept Robot APK.

Pulls printable strings out of the DEX files and hunts for:

* the Tuya **app key / app secret** (needed to sign cloud API calls),
* the API hosts and P2P/region configuration,
* datapoint names that reveal the robot's DP schema,
* interesting URLs.

Usage:

    python tools/apk_scan.py path/to/app.apk
    python tools/apk_scan.py path/to/app.apk --secrets-out data/app_secrets.json
"""

from __future__ import annotations

import argparse
import json
import re
import zipfile
from pathlib import Path

PRINTABLE = re.compile(rb"[\x20-\x7e]{6,}")

#: Tuya app keys are 20 chars, secrets 32 chars (hex-ish).
APPKEY_RE = re.compile(r"^[a-zA-Z0-9_\-]{16,24}$")
APPSECRET_RE = re.compile(r"^[a-zA-Z0-9_\-]{28,40}$")

HOST_RE = re.compile(r"\b[a-z0-9\-\.]+\.(?:tuya[a-z]{0,6}\.com|tuyacn\.com|tuyaus\.com|tuyaeu\.com)\b")
URL_RE = re.compile(r"https?://[a-zA-Z0-9\.\-_/:%]+")

INTERESTING = [
    "command_trans",
    "suction",
    "cistern",
    "clean_area",
    "clean_time",
    "battery",
    "power_go",
    "switch_charge",
    "locate",
    "path_data",
    "selectroom",
    "zone_clean",
    "goto_pos",
    "repositing",
    "emptying",
    "appKey",
    "app_key",
    "appSecret",
    "app_secret",
    "client_id",
    "tuya",
    "aistudio",
    "p2p",
    "mqtt",
    "sign_method",
    "grant_type",
]

DP_NAMES = [
    "command_trans",
    "power_go",
    "switch_charge",
    "clean_area",
    "clean_time",
    "cistern",
    "suction",
    "locate",
    "path_data",
    "repositing",
    "selectroom",
    "zone_clean",
    "goto_pos",
    "emptying",
    "battery",
]


def extract_strings(data: bytes, min_len: int = 6) -> list[str]:
    out = []
    for m in PRINTABLE.finditer(data):
        s = m.group().decode("ascii", "replace")
        if len(s) >= min_len:
            out.append(s)
    return out


def scan(apk: Path) -> dict:
    result: dict = {
        "apk": str(apk),
        "size": apk.stat().st_size,
        "hosts": set(),
        "urls": set(),
        "dp_names": set(),
        "keywords": {},
        "appkeys": set(),
        "appsecrets": set(),
        "dex_files": [],
    }
    with zipfile.ZipFile(apk) as zf:
        names = zf.namelist()
        for name in names:
            if not (name.endswith(".dex") or name.endswith(".arsc") or name.endswith(".xml")):
                continue
            if name.endswith(".dex"):
                result["dex_files"].append(name)
            try:
                data = zf.read(name)
            except KeyError:
                continue
            for s in extract_strings(data):
                low = s.lower()
                for host in HOST_RE.findall(s):
                    result["hosts"].add(host.lower())
                for url in URL_RE.findall(s):
                    result["urls"].add(url)
                for dp in DP_NAMES:
                    if dp.lower() in low:
                        result["dp_names"].add(dp)
                for kw in INTERESTING:
                    if kw.lower() in low:
                        result["keywords"].setdefault(kw, 0)
                        result["keywords"][kw] += 1
    # App key / secret heuristics: strings that look like keys near the
    # "appKey"/"appSecret" markers.
    with zipfile.ZipFile(apk) as zf:
        blob = b"".join(zf.read(n) for n in result["dex_files"] if n in zf.namelist())
    strings = extract_strings(blob)
    for i, s in enumerate(strings):
        if s.lower() in ("appkey", "app_key", "appkey", "appsecret", "app_secret"):
            for neighbour in strings[max(0, i - 3) : i + 4]:
                if neighbour.lower() in ("appkey", "app_key", "appsecret", "app_secret"):
                    continue
                if APPKEY_RE.match(neighbour) and not neighbour.isdigit():
                    result["appkeys"].add(neighbour)
                if APPSECRET_RE.match(neighbour):
                    result["appsecrets"].add(neighbour)
    # Also look for "key":"value" JSON blobs in assets
    with zipfile.ZipFile(apk) as zf:
        for name in zf.namelist():
            if not name.startswith("assets/"):
                continue
            try:
                text = zf.read(name).decode("utf-8", "replace")
            except Exception:  # noqa: BLE001
                continue
            for m in re.finditer(r'"(appkey|appKey|app_secret|appSecret|client_id)"\s*:\s*"([^"]+)"', text):
                key, value = m.group(1), m.group(2)
                if len(value) >= 16:
                    (result["appsecrets"] if "secret" in key.lower() else result["appkeys"]).add(value)
    for key in ("hosts", "urls", "dp_names", "appkeys", "appsecrets"):
        result[key] = sorted(result[key])
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("apk")
    ap.add_argument("--secrets-out", help="write discovered keys/secrets to this JSON file")
    args = ap.parse_args()

    apk = Path(args.apk)
    if not apk.exists():
        print(f"APK not found: {apk}")
        return 1

    res = scan(apk)
    print(f"APK: {res['apk']} ({res['size'] / 1e6:.1f} MB)")
    print(f"dex files: {len(res['dex_files'])}")
    print(f"\nDP names seen ({len(res['dp_names'])}):")
    print("  " + ", ".join(res["dp_names"]))
    print(f"\nHosts ({len(res['hosts'])}):")
    for h in res["hosts"][:40]:
        print("  " + h)
    print(f"\nApp keys ({len(res['appkeys'])}):")
    for k in res["appkeys"][:20]:
        print("  " + k)
    print(f"\nApp secrets ({len(res['appsecrets'])}):")
    for s in res["appsecrets"][:20]:
        print("  " + s)
    interesting_urls = [u for u in res["urls"] if any(k in u.lower() for k in ("p2p", "iot", "sweeper", "mqtt", "api"))]
    print(f"\nInteresting URLs ({len(interesting_urls)}):")
    for u in interesting_urls[:40]:
        print("  " + u)

    if args.secrets_out:
        out = Path(args.secrets_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(
                {
                    "appkeys": res["appkeys"],
                    "appsecrets": res["appsecrets"],
                    "hosts": res["hosts"],
                    "dp_names": res["dp_names"],
                },
                indent=2,
            )
        )
        print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
