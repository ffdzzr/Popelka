#!/usr/bin/env python3
"""Dump everything the Tuya cloud knows about the robot.

    export TUYA_USER=... TUYA_PASS=... TUYA_REGION=eu
    python tools/cloud_dump.py --out data/

Writes:
    devices.json    device list (ids, names, local_key, ip)
    status.json     current datapoint values
    specs.json      DP id -> code/name
    maps.json       stored map file list
    maps/*.bin      downloaded map files
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from popelka import dp as dps  # noqa: E402
from popelka.cloud import CloudError, load_account  # noqa: E402


def pick_device(devices: list[dict], wanted: str = "") -> dict | None:
    if not devices:
        return None
    if wanted:
        for d in devices:
            if wanted in (d.get("id", ""), d.get("name", "").lower()):
                return d
        return None
    # Prefer something that looks like a robot vacuum.
    for d in devices:
        blob = f"{d.get('name','')} {d.get('product_name','')} {d.get('category','')}".lower()
        if any(k in blob for k in ("vacuum", "robot", "sweeper", "vysava")):
            return d
    return devices[0]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="data", help="output directory")
    ap.add_argument("--device", default="", help="device id or name substring")
    ap.add_argument("--download-maps", action="store_true")
    args = ap.parse_args()

    account = load_account()
    if not account.username:
        print("Set TUYA_USER / TUYA_PASS (or TUYA_CLIENT_ID / TUYA_CLIENT_SECRET).", file=sys.stderr)
        return 1

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    try:
        account.login()
    except CloudError as exc:
        print(f"login failed: {exc}", file=sys.stderr)
        return 1
    print(f"logged in, uid={account.uid}")

    devices = account.devices()
    (out / "devices.json").write_text(json.dumps(devices, indent=2))
    for d in devices:
        # The local key is a credential: keep the full value in the gitignored
        # data/ directory, but never print it.
        key = d.get("local_key", "")
        masked = f"{key[:4]}...{key[-2:]}" if len(key) > 8 else ("set" if key else "-")
        print(f"  {d.get('id')}  {d.get('name')}  local_key={masked}  ip={d.get('ip', '-')}")

    device = pick_device(devices, args.device)
    if device is None:
        print("no device found")
        return 1
    device_id = device["id"]
    print(f"\nusing device {device_id} ({device.get('name')})")

    try:
        status = account.status(device_id)
    except CloudError as exc:
        print(f"status failed: {exc}", file=sys.stderr)
        status = {}
    (out / "status.json").write_text(json.dumps(status, indent=2))

    print("\ndatapoints:")
    for key, payload in sorted(status.items(), key=lambda kv: int(kv[0])):
        value = payload.get("value") if isinstance(payload, dict) else payload
        name = dps.dp_name(int(key))
        extra = ""
        if isinstance(value, str) and len(value) > 40:
            extra = " (long payload)"
        print(f"  DP{key:<5} {name:<16} {value!r}{extra}")

    try:
        specs = account.dp_names(device_id)
        (out / "specs.json").write_text(json.dumps(specs, indent=2))
        print(f"\nspecs: {len(specs)} datapoints described")
    except CloudError as exc:
        print(f"specs failed: {exc}")

    try:
        files = account.map_files(device_id)
        (out / "maps.json").write_text(json.dumps(files, indent=2))
        print(f"\nmap files: {len(files)}")
        for f in files[:10]:
            print(f"  {f.get('id')}  {f.get('time')}  {f.get('name')}")
        if args.download_maps:
            maps_dir = out / "maps"
            maps_dir.mkdir(exist_ok=True)
            for f in files:
                data = account.fetch_map_bytes(device_id, f["id"])
                path = maps_dir / f"{f.get('time', f['id'])}.bin"
                path.write_bytes(data)
                print(f"  downloaded {path} ({len(data)} bytes)")
    except CloudError as exc:
        print(f"maps failed: {exc}")

    print(f"\nwritten to {out}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
