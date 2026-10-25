"""Build a voice-pack ZIP and the `voice_data` DP value that installs it.

The robot downloads the ZIP itself and verifies the MD5, so the file must be
reachable over HTTP from the robot's network. This tool only:

1. zips a directory deterministically (same input -> same MD5),
2. hashes it,
3. prints the DP value to write.

It does **not** invent the pack layout. Extract an official pack first
(docs/VOICE.md explains how) and mirror its structure - directory names,
config file and audio format are all firmware-specific.

    python tools/voice_pack.py --dir pack --id 502 --url http://192.168.1.10/pack.zip
    python tools/voice_pack.py --zip pack.zip --hash-only
    python tools/voice_pack.py --zip pack.zip --id 502 --url http://192.168.1.10/pack.zip
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from popelka import voice  # noqa: E402


def build_zip(src: Path, out: Path, prefix: str = "") -> Path:
    """Deterministic ZIP: sorted entries, fixed timestamps, stored permissions."""
    files = sorted(p for p in src.rglob("*") if p.is_file())
    if not files:
        raise SystemExit(f"no files under {src}")
    prefix = prefix.strip("/")
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in files:
            name = path.relative_to(src).as_posix()
            if prefix:
                name = f"{prefix}/{name}"
            info = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, path.read_bytes())
    return out


def hash_file(path: Path) -> tuple[str, int]:
    digest = hashlib.md5()
    size = 0
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    source = ap.add_mutually_exclusive_group(required=True)
    source.add_argument("--dir", help="directory to zip (contents become the zip root)")
    source.add_argument("--zip", help="use an existing zip")
    ap.add_argument("--out", help="output zip path when using --dir (default: <dir>.zip)")
    ap.add_argument("--prefix", default="", help="optional top-level folder name inside the zip")
    ap.add_argument("--id", dest="pack_id", type=int, help="voice pack id the robot knows")
    ap.add_argument("--url", help="HTTP(S) URL the robot will download the zip from")
    ap.add_argument("--dp", dest="dp_id", type=int, default=voice.DP_VOICE_DATA)
    ap.add_argument("--hash-only", action="store_true", help="only print md5 and size")
    args = ap.parse_args()

    if args.dir:
        src = Path(args.dir)
        if not src.is_dir():
            raise SystemExit(f"not a directory: {src}")
        out = Path(args.out) if args.out else Path(f"{src.name}.zip")
        pack = build_zip(src, out, args.prefix)
        print(f"built {pack} from {src}")
    else:
        pack = Path(args.zip)

    md5, size = hash_file(pack)
    print(f"file : {pack}")
    print(f"size : {size} bytes")
    print(f"md5  : {md5}")

    if args.hash_only:
        return 0
    if args.pack_id is None or not args.url:
        raise SystemExit("need --id and --url (or use --hash-only)")

    request = voice.VoiceRequest(args.pack_id, md5, args.url)
    frame = request.frame()
    print(f"\nDP{args.dp_id} value ({len(frame)} bytes):")
    print(frame.hex())
    print()
    print(voice.describe(frame))
    print(
        "\nserve the zip (the robot connects to port 80):"
        f"\n  cd {pack.parent} && sudo python3 -m http.server 80"
        "\nthen:"
        f"\n  uv run python -m popelka.replay voice --pack-id {args.pack_id} "
        f"--md5 {md5} --url {args.url} --dp {args.dp_id}"
    )
    print(
        "\nreminder: the pack id must be one the firmware knows, and the internal\n"
        "config version must be higher than the installed one - see docs/VOICE.md."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
