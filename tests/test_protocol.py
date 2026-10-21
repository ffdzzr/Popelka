import pytest

from popelka import aa, commands, dp


def test_roundtrip():
    frame = aa.encode(0x4D, bytes([0x01, 0x3B]))
    assert frame[0] == 0xAA
    assert frame[1] == 0
    assert frame[2] == 3  # cmd + 2 payload bytes
    assert frame[-1] == (0x4D + 0x01 + 0x3B) & 0xFF


def test_decode_bundle():
    bundle = commands.sync_bundle()
    frames = aa.decode_frames(bundle)
    assert [f.cmd for f in frames] == [0x57, 0x55, 0x39, 0x13, 0x53]


def test_decode_skips_garbage():
    frames = aa.decode_frames(b"\x00\x11\x22" + aa.encode(0x27, [1, 2]))
    assert len(frames) == 1
    assert frames[0].cmd == 0x27
    assert frames[0].payload == bytes([1, 2])


def test_room_block_layout():
    room = commands.Room(room_id=3, passes=1, suction=0x03, water=0x02)
    assert room.block() == bytes([0x03, 0x05, 0x00, 0x00, 0x00, 0x01, 0x03, 0x02, 0x01, 0x00])


def test_room_plan_sequence():
    plan = commands.plan_room_clean([commands.Room(0), commands.Room(4)])
    assert plan.mode == "selectroom"
    assert plan.power_go is True
    frames = [aa.decode_frames(p)[0] for p in plan.dp15]
    assert [f.cmd for f in frames] == [0x4D, 0x57, 0x51, 0x27]
    # 0x51 payload: version, count, then two 10 byte blocks
    assert frames[2].payload[0] == 0x01
    assert frames[2].payload[1] == 2
    assert len(frames[2].payload) == 2 + 20
    # 0x27 payload: version, count, ids
    assert frames[3].payload == bytes([0x01, 0x02, 0x00, 0x04])


def test_fault_recovery_frame():
    assert commands.fault_recovery() == bytes([0xAA, 0x00, 0x01, 0x4C, 0x4C])


def test_zone_payload_coordinates():
    zone = commands.Zone(corners=[(0, 0), (338, 0)], passes=1, suction=2, water=0)
    payload = aa.decode_frames(commands.zone_command([zone]))[0].payload
    assert payload[0] == 0x01
    assert payload[1] == 1
    assert payload[2] == 2  # corner count
    assert int.from_bytes(payload[3:5], "big", signed=True) == 0
    assert int.from_bytes(payload[7:9], "big", signed=True) == 338
    assert abs(aa.units_to_metres(338) - 1.69) < 0.01


def test_int16_roundtrip():
    for v in (-32768, -1, 0, 1, 32767):
        assert aa.parse_int16(aa.pack_int16(v), 0) == v


def test_metres_units():
    assert aa.metres_to_units(1.7) == 340
    assert aa.units_to_metres(400) == 2.0


def test_dp_table():
    assert dp.dp_name(15) == "command_trans"
    assert dp.fault_text(0x04000000).startswith("robot stuck")
