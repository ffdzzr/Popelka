"""AA-frame codec for the Tuya laser-vacuum serial protocol (DP15 `command_trans`).

All binary commands sent to the robot travel inside DP15 as one or more
concatenated "AA frames":

    AA  len_hi  len_lo  cmd  payload...  checksum

* ``len`` is big-endian and counts the bytes that follow it, i.e. the cmd byte
  plus the payload (the checksum is *not* counted).
* ``checksum`` is ``sum(cmd + payload) & 0xFF``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Sequence

HEADER = 0xAA

# Command bytes seen on the wire (app -> robot and robot -> app).
CMD_WAKE = 0x4D
CMD_FAULT_RECOVERY = 0x4C
CMD_ROOM_CONFIG = 0x51
CMD_ROOM_STATUS = 0x53
CMD_ROOM_ORDER = 0x27
CMD_ZONE = 0x55
CMD_SPOT = 0x57
CMD_SYNC = 0x39
CMD_SYNC2 = 0x13
CMD_SYNC3 = 0x53
CMD_VOLUME = 0x5B

CMD_NAMES = {
    CMD_WAKE: "wake",
    CMD_FAULT_RECOVERY: "fault_recovery",
    CMD_ROOM_CONFIG: "room_config",
    CMD_ROOM_STATUS: "room_status",
    CMD_ROOM_ORDER: "room_order",
    CMD_ZONE: "zone",
    CMD_SPOT: "spot",
    CMD_SYNC: "sync_0x39",
    CMD_SYNC2: "sync_0x13",
    CMD_SYNC3: "sync_0x53",
    CMD_VOLUME: "volume",
}


class ProtocolError(ValueError):
    """Raised when a buffer cannot be parsed as AA frames."""


@dataclass(frozen=True)
class Frame:
    """A single decoded AA frame."""

    cmd: int
    payload: bytes
    raw: bytes
    offset: int = 0
    trailer: bytes = field(default=b"", repr=False)

    @property
    def name(self) -> str:
        return CMD_NAMES.get(self.cmd, f"0x{self.cmd:02X}")

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<Frame {self.name} payload={self.payload.hex(' ')}>"


def encode(cmd: int, payload: bytes | bytearray | Sequence[int] = b"") -> bytes:
    """Build one AA frame."""
    data = bytes([cmd]) + bytes(payload)
    if len(data) > 0xFFFF:
        raise ProtocolError(f"payload too long: {len(data)} bytes")
    return bytes([HEADER, (len(data) >> 8) & 0xFF, len(data) & 0xFF]) + data + bytes([sum(data) & 0xFF])


def decode_frames(buf: bytes) -> list[Frame]:
    """Decode every AA frame found in ``buf``.

    Trailing garbage (partial frames) is skipped rather than raising, because
    real captures are cut at arbitrary boundaries.
    """
    frames: list[Frame] = []
    i = 0
    n = len(buf)
    while i < n:
        if buf[i] != HEADER:
            i += 1
            continue
        if i + 3 > n:
            break
        length = (buf[i + 1] << 8) | buf[i + 2]
        # length counts cmd + payload; checksum follows
        end = i + 3 + length
        if end >= n:  # need one more byte for the checksum
            break
        body = buf[i + 3 : end]
        cmd = body[0]
        payload = body[1:]
        checksum = buf[end]
        expected = sum(body) & 0xFF
        if checksum != expected:
            # Not a frame (or a corrupted one) - resync on the next header byte.
            i += 1
            continue
        frames.append(Frame(cmd=cmd, payload=payload, raw=buf[i : end + 1], offset=i))
        i = end + 1
    return frames


def describe(buf: bytes) -> str:
    """Human readable dump of a buffer of frames."""
    out: list[str] = []
    for f in decode_frames(buf):
        out.append(f"@{f.offset:04X} {f.name:<14} cmd=0x{f.cmd:02X} len={len(f.payload):<3} payload={f.payload.hex(' ')}")
    if not out:
        return "<no valid AA frames found>"
    return "\n".join(out)


def hexdump(data: bytes, width: int = 16) -> str:
    """Classic hexdump, handy when reading Wireshark/pcap extracts."""
    lines = []
    for off in range(0, len(data), width):
        chunk = data[off : off + width]
        hexpart = " ".join(f"{b:02X}" for b in chunk)
        text = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"{off:08X}  {hexpart:<{width * 3}} |{text}|")
    return "\n".join(lines)


def parse_int16(data: bytes, offset: int) -> int:
    """Signed big-endian int16 (the robot's coordinate encoding)."""
    return int.from_bytes(data[offset : offset + 2], "big", signed=True)


def pack_int16(value: int) -> bytes:
    """Signed big-endian int16."""
    if not -32768 <= value <= 32767:
        raise ProtocolError(f"value out of int16 range: {value}")
    return int(value).to_bytes(2, "big", signed=True)


def units_to_metres(units: int) -> float:
    """Robot coordinate units -> metres (200 units = 1 m, i.e. 5 mm per unit)."""
    return units / 200.0


def metres_to_units(metres: float) -> int:
    """Metres -> robot coordinate units."""
    return round(metres * 200.0)


def iter_bytes(data: Iterable[int]) -> bytes:
    return bytes(data)
