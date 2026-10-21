"""Datapoint (DP) catalogue for the Tuya laser-vacuum solution.

Deps are what the cloud/app sees. DP15 (`command_trans`) is the interesting
one: it carries the whole binary protocol described in :mod:`popelka.aa`.

Sources: Tuya developer docs for the "Robot Vacuum (laser navigation)" solution,
plus captures from the Philips HomeRun XU3100 / Concept VR3125 family.
"""

from __future__ import annotations

from dataclasses import dataclass

# --- datapoint ids -------------------------------------------------------
DP_POWER_GO = 1
DP_PAUSE = 2
DP_SWITCH_CHARGE = 3
DP_MODE = 4
DP_STATUS = 5
DP_CLEAN_TIME = 6
DP_CLEAN_AREA = 7
DP_BATTERY = 8
DP_SUCTION = 9
DP_CISTERN = 10
DP_LOCATE = 11
DP_PATH_DATA = 14
DP_COMMAND_TRANS = 15
DP_FAULT = 28
DP_TOTAL_AREA = 29
DP_TOTAL_COUNT = 30
DP_TOTAL_TIME = 31
DP_DP107 = 107
DP_SENSOR_LIFE = 132


@dataclass(frozen=True)
class DPInfo:
    id: int
    name: str
    kind: str
    description: str = ""


DP_TABLE: dict[int, DPInfo] = {
    dp.id: dp
    for dp in [
        DPInfo(DP_POWER_GO, "power_go", "bool", "Start/stop trigger"),
        DPInfo(DP_PAUSE, "pause", "bool", "Pause cleaning"),
        DPInfo(DP_SWITCH_CHARGE, "switch_charge", "bool", "Return to dock"),
        DPInfo(DP_MODE, "mode", "enum", "smart|zone|pose|part|chargego"),
        DPInfo(DP_STATUS, "status", "enum", "standby|cleaning|paused|charging|..."),
        DPInfo(DP_CLEAN_TIME, "clean_time", "int", "Minutes in current session"),
        DPInfo(DP_CLEAN_AREA, "clean_area", "int", "m2 cleaned in current session"),
        DPInfo(DP_BATTERY, "battery", "int", "Battery percent"),
        DPInfo(DP_SUCTION, "suction", "enum", "gentle|normal|strong|strong_plus"),
        DPInfo(DP_CISTERN, "cistern", "enum", "closed|low|middle|high (water level)"),
        DPInfo(DP_LOCATE, "locate", "bool", "Play locating sound"),
        DPInfo(DP_PATH_DATA, "path_data", "raw", "Map/path data (P2P only, not local)"),
        DPInfo(DP_COMMAND_TRANS, "command_trans", "raw", "Main binary command channel"),
        DPInfo(DP_FAULT, "fault", "int", "0 ok, 128 generic, 67108864 stuck/lidar"),
        DPInfo(DP_TOTAL_AREA, "total_area", "int", "Cumulative m2"),
        DPInfo(DP_TOTAL_COUNT, "total_count", "int", "Total sessions"),
        DPInfo(DP_TOTAL_TIME, "total_time", "int", "Cumulative minutes"),
        DPInfo(DP_DP107, "dp_107", "int", "Unknown; grows slowly (lidar counter?)"),
        DPInfo(DP_SENSOR_LIFE, "sensor_life", "int", "Remaining sensor life (minutes)"),
    ]
}

# --- enum values ---------------------------------------------------------
MODES = {
    "smart": "smart",
    "zone": "zone",
    "pose": "pose",
    "part": "part",
    "chargego": "chargego",
}

STATUSES = [
    "standby",
    "cleaning",
    "paused",
    "charging",
    "charge_done",
    "selectroom",
    "zone_clean",
    "goto_pos",
    "repositing",
    "fault",
    "emptying",
]

SUCTION_LEVELS = {0x01: "gentle", 0x02: "normal", 0x03: "strong", 0x04: "strong_plus"}
WATER_LEVELS = {0x00: "off", 0x01: "low", 0x02: "middle", 0x03: "high"}

#: 0xFF means "inherit the global DP9 / DP10 setting".
INHERIT = 0xFF

FAULTS = {
    0x00000000: "ok",
    0x00000080: "generic fault (bin full / side brush stuck)",
    0x04000000: "robot stuck / lidar blocked",
}

#: App presets: suction level, water level, passes.
PRESETS = {
    "wee_and_dry": (0x02, 0x03, 1),
    "vacuum_only": (0x02, 0x00, 1),
    "silent": (0x01, 0x01, 1),
    "intensive": (0x04, 0x03, 5),
}


def dp_name(dp_id: int) -> str:
    info = DP_TABLE.get(dp_id)
    return info.name if info else f"dp_{dp_id}"


def fault_text(code: int) -> str:
    return FAULTS.get(code, f"unknown fault 0x{code:08X}")
