"""Extract and decode DP traffic from a packet capture.

Captures the phone <-> robot **local** Tuya socket (TCP 6668), which is the
cheapest interception point: no TLS, and the payloads are the exact datapoint
writes - including `command_trans` (DP15, AA frames) and `voice_data`
(DP162, AB frames).

    sudo tcpdump -i any -w captures/robot.pcap 'host 192.168.1.50 and port 6668'
    python tools/pcap_dp15.py captures/robot.pcap
    python tools/pcap_dp15.py captures/robot.pcap --key <local_key>

Without ``--key`` it prints the Tuya frame structure. With ``--key`` it
AES-128-ECB-decrypts protocol 3.3 payloads, parses the DP JSON and decodes both
frame families inside (raw DP values are base64 on the wire).

Protocol 3.4 (session-key handshake) is not decrypted yet - the tool reports it
so a future session knows what it is looking at.

Requires only the stdlib for plaintext mode; ``cryptography`` (or
``pycryptodome``) only for ``--key``.
"""

from __future__ import annotations

import argparse
import base64
import json
import string
import struct
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from popelka import aa, voice  # noqa: E402

TUYA_PREFIX = b"\x00\x00\x55\xaa"
TUYA_SUFFIX = b"\x00\x00\xaa\x55"

# Tuya local command ids (the interesting subset).
TUYA_CMDS = {
    0x01: "DP_QUERY",
    0x02: "CONTROL",
    0x03: "DP_QUERY_NEW / SESS_KEY_NEG_START",
    0x04: "DP_QUERY_NEW",
    0x05: "SESS_KEY_NEG_RESP",
    0x06: "SESS_KEY_NEG_FINISH",
    0x07: "UNBIND",
    0x08: "CONTROL_NEW",
    0x09: "DP_QUERY",
    0x0A: "HEART_BEAT",
    0x0D: "DP_QUERY",
    0x10: "DP_REFRESH",
}


@dataclass
class Segment:
    src: str
    sport: int
    dst: str
    dport: int
    data: bytearray = field(default_factory=bytearray)


def read_pcap(path: Path):
    """Yield raw packet bytes from a classic pcap file."""
    raw = path.read_bytes()
    if raw[:4] == b"\x0a\x0d\x0d\x0a":
        raise SystemExit("pcapng is not supported - convert it: editcap -F pcap in.pcapng out.pcap")
    magic = raw[:4]
    if magic == b"\xd4\xc3\xb2\xa1":
        endian, nano = "<", False
    elif magic == b"\xa1\xb2\xc3\xd4":
        endian, nano = ">", False
    elif magic == b"\x4d\x3c\xb2\xa1":
        endian, nano = "<", True
    elif magic == b"\xa1\xb2\x3c\x4d":
        endian, nano = ">", True
    else:
        raise SystemExit(f"not a pcap file (magic {magic.hex()})")

    off = 24
    while off + 16 <= len(raw):
        ts_sec, ts_frac, incl_len, _orig_len = struct.unpack(endian + "IIII", raw[off : off + 16])
        off += 16
        pkt = raw[off : off + incl_len]
        off += incl_len
        yield ts_sec + ts_frac / (1e9 if nano else 1e6), pkt


def parse_packet(pkt: bytes) -> tuple[str, str, int, int, bytes] | None:
    """Return (src, dst, sport, dport, payload) for TCP/IPv4 packets."""
    if len(pkt) < 14:
        return None
    ethertype = struct.unpack("!H", pkt[12:14])[0]
    offset = 14

    if ethertype == 0x0800:  # IPv4
        ip = pkt[offset:]
    elif ethertype == 0x86DD:  # IPv6
        return None
    elif pkt[0:2] in (b"\x00\x00", b"\x00\x04"):  # Linux cooked capture (tcpdump -i any)
        linktype = struct.unpack("!H", pkt[0:2])[0]
        offset = 16 if linktype == 0 else 20
        if len(pkt) < offset:
            return None
        ip = pkt[offset:]
    else:
        return None

    if len(ip) < 20 or (ip[0] >> 4) != 4:
        return None
    ihl = (ip[0] & 0x0F) * 4
    if ip[9] != 6:  # TCP only
        return None
    total_len = struct.unpack("!H", ip[2:4])[0]
    src = ".".join(str(b) for b in ip[12:16])
    dst = ".".join(str(b) for b in ip[16:20])
    tcp = ip[ihl:total_len]
    if len(tcp) < 20:
        return None
    sport, dport = struct.unpack("!HH", tcp[0:4])
    data_off = (tcp[12] >> 4) * 4
    payload = tcp[data_off:]
    return src, dst, sport, dport, payload


def tuya_frames(stream: bytes):
    """Split a TCP stream into Tuya local-protocol frames."""
    i = 0
    while True:
        start = stream.find(TUYA_PREFIX, i)
        if start < 0:
            return
        if start + 16 > len(stream):
            return
        seq, cmd, length = struct.unpack("!III", stream[start + 4 : start + 16])
        end = start + 16 + length
        if length < 8 or end > len(stream):
            i = start + 4
            continue
        payload = stream[start + 16 : end - 8]
        yield {
            "seq": seq,
            "cmd": cmd,
            "payload": payload,
            "raw_len": end - start,
        }
        i = end


def _aes_ecb_decrypt(data: bytes, key: bytes) -> bytes:
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

        decryptor = Cipher(algorithms.AES(key), modes.ECB()).decryptor()
        return decryptor.update(data) + decryptor.finalize()
    except ImportError:
        pass
    try:
        from Crypto.Cipher import AES  # type: ignore

        return AES.new(key, AES.MODE_ECB).decrypt(data)
    except ImportError:
        raise SystemExit(
            "--key needs AES support: pip install cryptography "
            "(Termux: pkg install python-cryptography)"
        )


def try_decrypt(payload: bytes, key: str) -> bytes | None:
    """Try the Tuya 3.3 payload layout: AES-128-ECB with local_key[8:24]."""
    if len(payload) < 16 or len(payload) % 16:
        return None
    key_bytes = key[8:24].encode()
    if len(key_bytes) != 16:
        return None
    try:
        plain = _aes_ecb_decrypt(payload, key_bytes)
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001
        return None
    if plain[:3] not in (b"3.1", b"3.2", b"3.3", b"3.4"):
        return None
    return plain[16:] if len(plain) > 16 else plain


def decode_dp_value(value) -> bytes | None:
    """Raw DP values are base64 on the wire; panels show them as hex strings."""
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    if not isinstance(value, str) or not value:
        return None
    text = value.strip()
    is_hex = len(text) % 2 == 0 and all(ch in string.hexdigits for ch in text)
    if is_hex and not text.endswith("="):
        try:
            return bytes.fromhex(text)
        except ValueError:
            pass
    try:
        return base64.b64decode(text, validate=True)
    except Exception:  # noqa: BLE001
        return None


def describe_frames(raw: bytes, indent: str = "        ") -> list[str]:
    """Decode both frame families and fall back to a hex preview."""
    lines: list[str] = []
    aa_frames = aa.decode_frames(raw)
    ab_frames = voice.decode_frames(raw)
    for frame in aa_frames:
        lines.append(f"{indent}AA {frame.name:<14} cmd=0x{frame.cmd:02X} payload={frame.payload.hex(' ')}")
    for frame in ab_frames:
        lines.append(f"{indent}AB cmd=0x{frame.cmd:02X} len={len(frame.data)} data={frame.data.hex(' ')}")
    for request in voice.decode_requests(raw):
        lines.append(f"{indent}   voice install: id={request.pack_id} md5={request.md5} url={request.url}")
    for report in voice.decode_reports(raw):
        lines.append(f"{indent}   voice report: {report.describe()}")
    if not lines:
        preview = raw[:32].hex(" ")
        suffix = "..." if len(raw) > 32 else ""
        lines.append(f"{indent}<no AA/AB frames> {preview}{suffix}")
    return lines


def describe_payload(body: bytes, indent: str = "      ") -> list[str]:
    """Decode a decrypted local-protocol body: JSON DPs or bare frames."""
    try:
        obj = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        obj = None

    if isinstance(obj, dict):
        dps = obj.get("dps")
        if not isinstance(dps, dict) and isinstance(obj.get("data"), dict):
            dps = obj["data"].get("dps")
        if isinstance(dps, dict):
            lines: list[str] = []
            for dp_id, value in dps.items():
                raw = decode_dp_value(value)
                size = f"{len(raw)}B" if raw is not None else "unparsed"
                lines.append(f"{indent}DP{dp_id} ({size}):")
                if raw is not None:
                    lines.extend(describe_frames(raw, indent + "  "))
            return lines
    return describe_frames(body, indent)


def describe_tuya(frame: dict, key: str | None) -> list[str]:
    lines: list[str] = []
    cmd = frame["cmd"]
    name = TUYA_CMDS.get(cmd, f"0x{cmd:02X}")
    payload = frame["payload"]
    lines.append(f"    tuya cmd={cmd:#04x} ({name}) seq={frame['seq']} payload={len(payload)}B")
    body = payload
    note = " (plaintext)"
    if key:
        plain = try_decrypt(payload, key)
        if plain is not None:
            body = plain
            note = " (aes-3.3)"
        else:
            note = " (encrypted/unknown layout)"
    lines.append(f"      payload{note}:")
    lines.extend(describe_payload(body))
    return lines


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pcap")
    ap.add_argument("--key", help="device local key (enables AES decryption)")
    ap.add_argument("--port", type=int, default=6668, help="local Tuya port (default 6668)")
    args = ap.parse_args()

    streams: dict[tuple[str, int, str, int], Segment] = {}
    packets = 0
    for _ts, pkt in read_pcap(Path(args.pcap)):
        parsed = parse_packet(pkt)
        if not parsed:
            continue
        src, dst, sport, dport, payload = parsed
        if args.port not in (sport, dport):
            continue
        packets += 1
        stream_key = (src, sport, dst, dport)
        if stream_key not in streams:
            streams[stream_key] = Segment(src, sport, dst, dport)
        streams[stream_key].data += payload

    if not packets:
        print(f"no TCP/{args.port} packets found", file=sys.stderr)
        return 1

    total_frames = 0
    for seg in streams.values():
        label = f"{seg.src}:{seg.sport} -> {seg.dst}:{seg.dport}"
        frames = list(tuya_frames(bytes(seg.data)))
        print(f"\n=== {label}  ({len(seg.data)} bytes, {len(frames)} tuya frames)")
        for frame in frames:
            total_frames += 1
            for line in describe_tuya(frame, args.key):
                print(line)

    print(f"\n{packets} packets, {total_frames} tuya frames")
    if not args.key:
        print("hint: pass --key <local_key> to decrypt protocol 3.3 payloads")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
