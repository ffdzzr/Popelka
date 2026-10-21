"""Builders for the binary commands carried inside DP15 (`command_trans`).

The Tuya app never sends a single frame: it sends a *bundle*. The canonical
sequence for a room clean is:

    DP15 <- wake        (cmd 0x4D)
    DP15 <- sync bundle (0x57 / 0x55 / 0x39 / 0x13 / 0x53 stubs)
    DP15 <- room config (cmd 0x51, one 10-byte block per room)
    DP15 <- room order  (cmd 0x27)
    DP1  <- True
    DP4  <- "selectroom"

Everything here returns raw bytes suitable for a DP15 write.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import aa
from .aa import (
    CMD_FAULT_RECOVERY,
    CMD_ROOM_CONFIG,
    CMD_ROOM_ORDER,
    CMD_SPOT,
    CMD_SYNC,
    CMD_SYNC2,
    CMD_SYNC3,
    CMD_VOLUME,
    CMD_WAKE,
    CMD_ZONE,
)
from .dp import INHERIT

#: Fixed wake payload captured from the app.
WAKE_PAYLOAD = bytes([0x01, 0x3B, 0x9A, 0xCA, 0x03])


@dataclass
class Room:
    """One room in a room-clean request."""

    room_id: int
    passes: int = 0
    suction: int = INHERIT
    water: int = INHERIT
    b1: int = 0x00
    b2: int = 0x00
    name: str = ""

    def block(self) -> bytes:
        return bytes(
            [
                self.room_id & 0xFF,
                0x05,
                0x00,
                self.b1 & 0xFF,
                self.b2 & 0xFF,
                self.passes & 0xFF,
                self.suction & 0xFF,
                self.water & 0xFF,
                0x01,
                0x00,
            ]
        )


@dataclass
class Zone:
    """A rectangular zone in robot coordinates (200 units = 1 m)."""

    corners: list[tuple[int, int]]
    passes: int = 0
    suction: int = INHERIT
    water: int = INHERIT
    carpet: int = 0
    b: bytes = bytes([0x05, 0x00, 0x00, 0x00])

    def payload(self) -> bytes:
        """One zone block (the surrounding ``01 <num_zones>`` prefix is added by
        :func:`zone_command`)."""
        out = bytearray([len(self.corners)])
        for x, y in self.corners:
            out += aa.pack_int16(x)
            out += aa.pack_int16(y)
        out += self.b
        out += bytes([self.passes & 0xFF, self.suction & 0xFF, self.water & 0xFF])
        out += bytes([0xFF, 0x00, 0xFF, self.carpet & 0xFF])
        return bytes(out)


@dataclass
class Spot:
    """A single-point (go-to) clean request in robot coordinates."""

    x: int
    y: int
    passes: int = 0
    suction: int = INHERIT
    water: int = INHERIT
    b: bytes = bytes([0x05, 0x00, 0x00, 0x00])

    def payload(self) -> bytes:
        out = bytearray([0x01])
        out += aa.pack_int16(self.x)
        out += aa.pack_int16(self.y)
        out += self.b
        out += bytes([self.passes & 0xFF, self.suction & 0xFF, self.water & 0xFF])
        out += bytes([0xFF, 0xFF, 0xFF, 0x01])
        return bytes(out)


@dataclass
class CommandPlan:
    """Everything needed to run one cleaning job.

    ``dp15`` is the list of raw DP15 payloads to write, in order.
    ``mode`` is the DP4 value and ``power_go`` the DP1 value to finish.
    """

    dp15: list[bytes] = field(default_factory=list)
    mode: str = "smart"
    power_go: bool = True

    def summary(self) -> str:
        lines = [f"mode={self.mode} power_go={self.power_go}"]
        for i, payload in enumerate(self.dp15, 1):
            lines.append(f"DP15 #{i}: {aa.hexdump(payload)}")
        return "\n".join(lines)


def wake() -> bytes:
    """cmd 0x4D - session ping, required before room/zone/spot commands."""
    return aa.encode(CMD_WAKE, WAKE_PAYLOAD)


def sync_bundle() -> bytes:
    """The stub bundle the app sends right after waking."""
    return b"".join(
        [
            aa.encode(CMD_SPOT, bytes([0x01])),
            aa.encode(CMD_ZONE, bytes([0x01, 0x00])),
            aa.encode(CMD_SYNC, bytes([0x01, 0x00])),
            aa.encode(CMD_SYNC2, bytes([0x01, 0x00])),
            aa.encode(CMD_SYNC3, bytes([0x01, 0x00])),
        ]
    )


def room_config(rooms: list[Room]) -> bytes:
    """cmd 0x51 - per-room suction/water/pass settings."""
    body = bytearray([0x01, len(rooms)])
    for room in rooms:
        body += room.block()
    return aa.encode(CMD_ROOM_CONFIG, body)


def room_order(room_ids: list[int]) -> bytes:
    """cmd 0x27 - the order rooms should be cleaned in."""
    body = bytearray([0x01, len(room_ids)])
    body += bytes(r & 0xFF for r in room_ids)
    return aa.encode(CMD_ROOM_ORDER, body)


def zone_command(zones: list[Zone]) -> bytes:
    """cmd 0x55 - zone cleaning payload (usually sent inside a bundle)."""
    body = bytearray([0x01, len(zones)])
    for zone in zones:
        body += zone.payload()
    return aa.encode(CMD_ZONE, body)


def spot_command(spot: Spot) -> bytes:
    """cmd 0x57 - spot (go-to) cleaning payload (usually sent inside a bundle)."""
    return aa.encode(CMD_SPOT, spot.payload())


def zone_bundle(zones: list[Zone]) -> bytes:
    """Full bundle the app sends for a zone clean."""
    return b"".join(
        [
            aa.encode(CMD_SPOT, bytes([0x01])),
            zone_command(zones),
            aa.encode(CMD_SYNC, bytes([0x01, 0x00])),
            aa.encode(CMD_SYNC2, bytes([0x01, 0x00])),
            aa.encode(CMD_SYNC3, bytes([0x01, 0x00])),
        ]
    )


def spot_bundle(spot: Spot) -> bytes:
    """Full bundle the app sends for a spot clean (0x57/0x55 roles swapped)."""
    return b"".join(
        [
            spot_command(spot),
            aa.encode(CMD_ZONE, bytes([0x01, 0x00])),
            aa.encode(CMD_SYNC, bytes([0x01, 0x00])),
            aa.encode(CMD_SYNC2, bytes([0x01, 0x00])),
            aa.encode(CMD_SYNC3, bytes([0x01, 0x00])),
        ]
    )


def fault_recovery() -> bytes:
    """cmd 0x4C - clears a stuck/lidar fault and resumes cleaning."""
    return aa.encode(CMD_FAULT_RECOVERY)


def volume_step(step: int) -> bytes:
    """cmd 0x5B - volume control step."""
    return aa.encode(CMD_VOLUME, bytes([0x01, step & 0xFF]))


def plan_room_clean(rooms: list[Room]) -> CommandPlan:
    """Full room-clean plan: wake, sync, config, order."""
    return CommandPlan(
        dp15=[wake(), sync_bundle(), room_config(rooms), room_order([r.room_id for r in rooms])],
        mode="selectroom",
        power_go=True,
    )


def plan_zone_clean(zones: list[Zone]) -> CommandPlan:
    return CommandPlan(dp15=[wake(), zone_bundle(zones)], mode="zone", power_go=True)


def plan_spot_clean(spot: Spot) -> CommandPlan:
    return CommandPlan(dp15=[wake(), spot_bundle(spot)], mode="pose", power_go=True)
