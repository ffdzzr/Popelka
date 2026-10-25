"""Send real commands to the robot over the local Tuya socket.

    uv run python -m popelka.replay status
    uv run python -m popelka.replay room --room 0 --room 4
    uv run python -m popelka.replay zone --from 1,1 --to 2,2
    uv run python -m popelka.replay spot --at 1,2
    uv run python -m popelka.replay fault          # clear a stuck/lidar fault
    uv run python -m popelka.replay raw AA00064D...
    uv run python -m popelka.replay voice --pack-id 502 --md5 <md5> --url http://<pc>/pack.zip

Connection details come from the environment or from ``data/devices.json``:

    POPELKA_IP, POPELKA_LOCAL_KEY, POPELKA_DEVICE_ID
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import aa, commands, dp, voice
from .tuya import LocalDevice, TuyaError


def load_device() -> LocalDevice:
    ip = os.environ.get("POPELKA_IP", "")
    key = os.environ.get("POPELKA_LOCAL_KEY", "")
    device_id = os.environ.get("POPELKA_DEVICE_ID", "")

    devices_file = Path(os.environ.get("POPELKA_DEVICES_FILE", "data/devices.json"))
    if (not ip or not key) and devices_file.exists():
        try:
            devices = json.loads(devices_file.read_text())
        except ValueError:
            devices = []
        for d in devices:
            blob = f"{d.get('name','')} {d.get('product_name','')}".lower()
            if any(k in blob for k in ("vacuum", "robot", "sweeper")) or len(devices) == 1:
                ip = ip or d.get("ip", "")
                key = key or d.get("local_key", "")
                device_id = device_id or d.get("id", "")
                break

    if not ip or not key:
        raise SystemExit(
            "need POPELKA_IP and POPELKA_LOCAL_KEY (or data/devices.json from tools/cloud_dump.py)"
        )
    return LocalDevice(ip=ip, local_key=key, device_id=device_id)


def show_status(device: LocalDevice) -> int:
    status = device.status()
    print(f"device {device.ip}:{device.port} ({device.device_id})")
    for dp_id, payload in sorted(status.items(), key=lambda kv: int(kv[0])):
        if not isinstance(payload, dict):
            continue
        value = payload.get("value")
        if isinstance(value, (bytes, bytearray)):
            value = value.hex()
        text = str(value)
        if len(text) > 60:
            text = text[:60] + "..."
        print(f"  DP{dp_id:<5} {dp.dp_name(int(dp_id)):<16} {text}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="popelka.replay", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="read all datapoints")

    p = sub.add_parser("room", help="clean specific rooms")
    p.add_argument("--room", action="append", type=int, default=[], help="room id (repeatable)")
    p.add_argument("--suction", type=lambda v: int(v, 0), default=dp.INHERIT)
    p.add_argument("--water", type=lambda v: int(v, 0), default=dp.INHERIT)
    p.add_argument("--passes", type=int, default=0)
    p.add_argument("--dry-run", action="store_true", help="print the frames, send nothing")

    p = sub.add_parser("zone", help="clean a rectangular zone (metres)")
    p.add_argument("--from", dest="corner1", required=True, help="x1,y1 in metres")
    p.add_argument("--to", dest="corner2", required=True, help="x2,y2 in metres")
    p.add_argument("--dry-run", action="store_true")

    p = sub.add_parser("spot", help="go to a point (metres)")
    p.add_argument("--at", required=True, help="x,y in metres")
    p.add_argument("--dry-run", action="store_true")

    sub.add_parser("fault", help="clear a stuck fault and resume")

    p = sub.add_parser("raw", help="send a raw DP15 payload (hex)")
    p.add_argument("payload")

    p = sub.add_parser("voice", help="install a voice pack (writes the voice_data DP)")
    p.add_argument("--pack-id", type=int, required=True, help="pack/language id the robot knows")
    p.add_argument("--md5", required=True, help="MD5 of the ZIP (32 hex chars)")
    p.add_argument("--url", required=True, help="HTTP(S) URL the robot downloads the ZIP from")
    p.add_argument(
        "--dp",
        dest="dp_id",
        type=int,
        default=voice.DP_VOICE_DATA,
        help=f"voice_data DP id (default {voice.DP_VOICE_DATA}, a hypothesis - verify first)",
    )
    p.add_argument("--dry-run", action="store_true", help="print the DP value, send nothing")

    args = parser.parse_args(argv)

    try:
        if args.cmd == "voice":
            request = voice.VoiceRequest(args.pack_id, args.md5, args.url)
            payload = request.frame()
            print(f"DP{args.dp_id} value ({len(payload)} bytes):")
            print(payload.hex())
            print(voice.describe(payload))
            if args.dry_run:
                return 0
            device = load_device()
            device.send_raw_dp(args.dp_id, payload)
            print(f"sent - the robot should download {args.url}")
            return 0

        device = load_device()
        if args.cmd == "status":
            return show_status(device)

        if args.cmd == "room":
            rooms = [
                commands.Room(r, passes=args.passes, suction=args.suction, water=args.water)
                for r in args.room
            ]
            plan = commands.plan_room_clean(rooms)
        elif args.cmd == "zone":
            x1, y1 = (float(v) for v in args.corner1.split(","))
            x2, y2 = (float(v) for v in args.corner2.split(","))
            zone = commands.Zone(
                corners=[
                    (aa.metres_to_units(x1), aa.metres_to_units(y1)),
                    (aa.metres_to_units(x2), aa.metres_to_units(y2)),
                ],
                passes=1,
            )
            plan = commands.plan_zone_clean([zone])
        elif args.cmd == "spot":
            x, y = (float(v) for v in args.at.split(","))
            plan = commands.plan_spot_clean(
                commands.Spot(aa.metres_to_units(x), aa.metres_to_units(y), passes=1)
            )
        elif args.cmd == "fault":
            plan = commands.CommandPlan(dp15=[commands.fault_recovery()], mode="smart", power_go=False)
        else:  # raw
            payload = bytes.fromhex(args.payload.replace(" ", ""))
            for f in aa.decode_frames(payload):
                print(f"  {f.name} payload={f.payload.hex(' ')}")
            if not args.__dict__.get("dry_run"):
                device.send_raw_dp15(payload)
            print("sent")
            return 0

        for payload in plan.dp15:
            print(f"--- DP15 ({len(payload)} bytes)")
            print(aa.hexdump(payload))
        print(f"then DP1={plan.power_go} DP4={plan.mode}")
        if args.dry_run:
            return 0

        device.execute_plan(plan)
        print("sent")
        return 0
    except TuyaError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
