"""mitmproxy addon: log every `command_trans` (DP15) payload the app sends.

Usage:

    mitmdump -s tools/mitm_dp15.py --set ssl_insecure=true -w flows.mitm
    # then drive the Concept Robot / Concept Home app

Each hit is printed as hex and immediately decoded with the AA-frame parser.

If the app pins certificates, re-sign the APK with a debug CA (see docs/RE.md).
"""

from __future__ import annotations

import base64
import binascii
import json
import re

from popelka import aa

HEX_RE = re.compile(rb"^[0-9a-fA-F\s:]+$")


def _decode_value(value) -> tuple[bytes, str]:
    """Try to turn a JSON value into bytes, guessing hex vs base64."""
    if isinstance(value, (bytes, bytearray)):
        return bytes(value), "raw"
    if isinstance(value, str):
        raw = value.encode()
        if HEX_RE.match(raw) and len(raw) % 2 == 0:
            try:
                return binascii.unhexlify(re.sub(rb"[^0-9a-fA-F]", b"", raw)), "hex"
            except binascii.Error:
                pass
        try:
            return base64.b64decode(raw, validate=True), "base64"
        except (binascii.Error, ValueError):
            return b"", "unknown"
    return b"", "unknown"


def _walk(node, path: str = ""):
    if isinstance(node, dict):
        for key, value in node.items():
            if key in ("command_trans", "dp_15", "15") or "command_trans" in str(key):
                yield path + "/" + str(key), value
            else:
                yield from _walk(value, path + "/" + str(key))
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield from _walk(value, f"{path}[{i}]")


def response(flow):  # noqa: D401 - mitmproxy hook
    body = flow.response.get_content(strict=False) if flow.response else b""
    if not body:
        return
    try:
        doc = json.loads(body)
    except ValueError:
        return
    for path, value in _walk(doc):
        data, kind = _decode_value(value)
        if not data:
            continue
        frames = aa.decode_frames(data)
        if not frames:
            continue
        print(f"\n=== {flow.request.method} {flow.request.url}  ({path}, {kind}, {len(data)} bytes)")
        print(aa.describe(data))
