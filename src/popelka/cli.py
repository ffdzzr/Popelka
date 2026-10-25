"""Command line helpers for poking at the Concept VR3125."""

from __future__ import annotations

import argparse
import json
import sys

from . import aa, commands, dp, droid, maps, voice


def _int(value: str) -> int:
    """Parse 0x-prefixed, hex (ff) or decimal values."""
    value = value.strip()
    try:
        return int(value, 0)
    except ValueError:
        return int(value, 16)


def cmd_frames(args: argparse.Namespace) -> int:
    data = bytes.fromhex(args.hex.replace(" ", "").replace(":", ""))
    if args.raw:
        print(aa.hexdump(data))
    print(aa.describe(data))
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    plan = None
    if args.kind == "room":
        rooms = []
        for spec in args.rooms:
            parts = spec.split(":")
            room_id = int(parts[0])
            suction = _int(parts[1]) if len(parts) > 1 else dp.INHERIT
            water = _int(parts[2]) if len(parts) > 2 else dp.INHERIT
            passes = _int(parts[3]) if len(parts) > 3 else 0
            rooms.append(commands.Room(room_id, passes=passes, suction=suction, water=water))
        plan = commands.plan_room_clean(rooms)
    elif args.kind == "zone":
        zones = []
        for spec in args.zones or []:
            x1, y1, x2, y2 = (int(v) for v in spec.split(","))
            zones.append(commands.Zone(corners=[(x1, y1), (x2, y2)]))
        plan = commands.plan_zone_clean(zones)
    elif args.kind == "spot":
        x, y = (int(v) for v in args.spot.split(","))
        plan = commands.plan_spot_clean(commands.Spot(x=x, y=y))
    elif args.kind == "fault":
        plan = commands.CommandPlan(dp15=[commands.fault_recovery()], mode="smart", power_go=False)

    assert plan is not None
    for payload in plan.dp15:
        print(f"--- DP15 payload ({len(payload)} bytes) ---")
        print(aa.hexdump(payload))
    print(f"then: DP1 = {plan.power_go}, DP4 = {plan.mode}")
    return 0


def cmd_map(args: argparse.Namespace) -> int:
    with open(args.file, "rb") as fh:
        data = fh.read()
    try:
        m = maps.decode_map(data, width=args.width, height=args.height)
    except ValueError as exc:
        print(f"decode failed: {exc}", file=sys.stderr)
        return 1
    print(f"size: {m.width} x {m.height}")
    print(f"header: {m.header}")
    for note in m.notes:
        print(f"note: {note}")
    print(f"rooms: {sorted(m.room_ids())}")
    names = m.decode_names()
    if names:
        print("names:", json.dumps(names, ensure_ascii=False, indent=2))
    if args.out:
        with open(args.out, "wb") as fh:
            fh.write(m.to_pgm())
        print(f"wrote {args.out}")
    return 0


def cmd_dps(args: argparse.Namespace) -> int:
    for info in dp.DP_TABLE.values():
        print(f"DP{info.id:<4} {info.kind:<6} {info.name:<16} {info.description}")
    return 0


def cmd_faults(args: argparse.Namespace) -> int:
    for code, text in dp.FAULTS.items():
        print(f"0x{code:08X}  {text}")
    return 0


def cmd_voice(args: argparse.Namespace) -> int:
    if args.action == "build":
        request = voice.VoiceRequest(args.pack_id, args.md5, args.url)
        frame = request.frame()
        print(f"DP{args.dp_id} value ({len(frame)} bytes, hex):")
        print(frame.hex())
        print(voice.describe(frame))
        print(
            "send with: uv run python -m popelka.replay voice "
            f"--pack-id {args.pack_id} --md5 {args.md5} --url {args.url} --dp {args.dp_id}"
        )
        return 0
    data = voice.from_hex(args.hex)
    print(voice.describe(data))
    return 0


def cmd_droid(args: argparse.Namespace) -> int:
    samples = droid.phrase(args.seed, parts=args.parts)
    path = droid.write_wav(args.out, samples)
    print(f"wrote {path} ({droid.duration(samples):.2f}s, seed={args.seed})")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="popelka", description="Concept VR3125 protocol toolkit")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("frames", help="decode AA frames from hex")
    p.add_argument("hex")
    p.add_argument("--raw", action="store_true", help="also hexdump the input")
    p.set_defaults(func=cmd_frames)

    p = sub.add_parser("build", help="build binary command payloads")
    p.add_argument("kind", choices=["room", "zone", "spot", "fault"])
    p.add_argument("--rooms", nargs="*", help="room specs id:suction:water:passes")
    p.add_argument("--zones", nargs="*", help="zone specs x1,y1,x2,y2 (robot units)")
    p.add_argument("--spot", help="spot spec x,y (robot units)")
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("map", help="decode a downloaded map file")
    p.add_argument("file")
    p.add_argument("--width", type=int)
    p.add_argument("--height", type=int)
    p.add_argument("--out", help="write a PGM render")
    p.set_defaults(func=cmd_map)

    p = sub.add_parser("dps", help="show the datapoint catalogue")
    p.set_defaults(func=cmd_dps)

    p = sub.add_parser("faults", help="show known fault codes")
    p.set_defaults(func=cmd_faults)

    p = sub.add_parser("voice", help="voice-pack frames: build a 0x34 request or decode a capture")
    voice_sub = p.add_subparsers(dest="action", required=True)
    b = voice_sub.add_parser("build", help="build the voice_data DP value for a pack URL")
    b.add_argument("--id", dest="pack_id", type=int, required=True, help="pack/language id (must be one the robot knows)")
    b.add_argument("--md5", required=True, help="MD5 of the ZIP file, 32 hex chars")
    b.add_argument("--url", required=True, help="HTTP(S) URL the robot will download")
    b.add_argument("--dp", dest="dp_id", type=int, default=voice.DP_VOICE_DATA, help="voice_data DP id (default: hypothesised 162)")
    d = voice_sub.add_parser("decode", help="decode a captured voice payload (hex)")
    d.add_argument("hex")
    p.set_defaults(func=cmd_voice)

    p = sub.add_parser("droid", help="synthesise an original astromech-style chirp WAV")
    p.add_argument("--out", default="droid.wav")
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--parts", type=int, help="number of chirps (default: 3-6 from the seed)")
    p.set_defaults(func=cmd_droid)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
