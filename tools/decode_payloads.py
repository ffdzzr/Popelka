#!/usr/bin/env python3
"""Decode a file of captured DP15 payloads (hex or base64, one per line).

    python tools/decode_payloads.py captures.txt

Blank lines and lines starting with # are ignored.  Anything that looks like
an AA frame is decoded and annotated.
"""

from __future__ import annotations

import base64
import binascii
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from popelka import aa  # noqa: E402

HEX_RE = re.compile(r"^[0-9a-fA-F\s:]+$")


def to_bytes(line: str) -> bytes:
    line = line.strip()
    if HEX_RE.match(line) and len(line.replace(" ", "").replace(":", "")) % 2 == 0:
        try:
            return binascii.unhexlify(re.sub(r"[^0-9a-fA-F]", "", line))
        except binascii.Error:
            pass
    try:
        return base64.b64decode(line, validate=True)
    except (binascii.Error, ValueError):
        return b""


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    path = Path(sys.argv[1])
    for lineno, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        data = to_bytes(line)
        frames = aa.decode_frames(data)
        if not frames:
            print(f"[{lineno}] no AA frames ({len(data)} bytes)")
            continue
        print(f"[{lineno}] {len(data)} bytes")
        print(aa.describe(data))
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
