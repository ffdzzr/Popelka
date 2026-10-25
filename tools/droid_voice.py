"""Generate original astromech-style chirps for the voice pack.

No Star Wars audio is used - :mod:`popelka.droid` synthesises new whistles from
frequency sweeps and vibrato. Seeds are stable per prompt name, so a pack can
be rebuilt byte-for-byte (the robot checks the ZIP's MD5).

    python tools/droid_voice.py --out droid.wav --seed 7
    python tools/droid_voice.py --names power_on,start_clean,error --out-dir sounds
    python tools/droid_voice.py --manifest prompts.json --out-dir sounds --mp3

``--mp3`` shells out to ffmpeg with the Eufy sibling's settings
(16 kHz mono, 16 kbps). Those are a hypothesis for the VR3125 - confirm the
real format from an official pack before using it (docs/VOICE.md).
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from popelka import droid  # noqa: E402


def seed_for(name: str) -> int:
    """Stable, cross-platform seed for a prompt name."""
    return zlib.crc32(name.encode("utf-8"))


def to_mp3(wav: Path) -> Path:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise SystemExit("--mp3 needs ffmpeg on PATH (pkg install ffmpeg)")
    mp3 = wav.with_suffix(".mp3")
    subprocess.run(
        [ffmpeg, "-y", "-loglevel", "error", "-i", str(wav),
         "-ar", "16000", "-ac", "1", "-b:a", "16k", str(mp3)],
        check=True,
    )
    wav.unlink(missing_ok=True)
    return mp3


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", help="single output WAV (with --seed)")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--parts", type=int, help="number of chirps per phrase")
    ap.add_argument("--names", help="comma-separated prompt names -> one file each")
    ap.add_argument("--manifest", help="JSON list of prompt names")
    ap.add_argument("--out-dir", default="sounds", help="directory for --names/--manifest")
    ap.add_argument("--mp3", action="store_true", help="convert with ffmpeg (16 kHz mono)")
    args = ap.parse_args()

    names: list[str] = []
    if args.names:
        names = [n.strip() for n in args.names.split(",") if n.strip()]
    if args.manifest:
        data = json.loads(Path(args.manifest).read_text())
        if isinstance(data, dict):
            data = list(data)
        names = [str(n) for n in data]

    if not names:
        out = Path(args.out or "droid.wav")
        samples = droid.phrase(args.seed, parts=args.parts)
        path = droid.write_wav(out, samples)
        print(f"wrote {path} ({droid.duration(samples):.2f}s, seed={args.seed})")
        if args.mp3:
            print(f"wrote {to_mp3(path)}")
        return 0

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"generating {len(names)} chirps into {out_dir}/")
    for name in names:
        samples = droid.phrase(seed_for(name), parts=args.parts)
        path = droid.write_wav(out_dir / f"{name}.wav", samples)
        if args.mp3:
            path = to_mp3(path)
        print(f"  {path}  ({droid.duration(samples):.2f}s, seed={seed_for(name)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
