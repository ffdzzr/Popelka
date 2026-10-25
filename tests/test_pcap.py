"""Tests for the pcap helper (tools/pcap_dp15.py)."""

from __future__ import annotations

import base64
import importlib.util
import json
import struct
import sys
from pathlib import Path

from popelka import aa, commands, voice

TOOL = Path(__file__).resolve().parents[1] / "tools" / "pcap_dp15.py"


def load_tool():
    spec = importlib.util.spec_from_file_location("pcap_dp15", TOOL)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    # dataclasses needs the module registered while it executes
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def tcp_packet(payload: bytes, sport: int = 45678, dport: int = 6668) -> bytes:
    eth = b"\xaa" * 6 + b"\xbb" * 6 + b"\x08\x00"
    total = 20 + 20 + len(payload)
    ip = (
        bytes([0x45, 0])
        + struct.pack("!H", total)
        + b"\x00\x00\x00\x00"
        + bytes([64, 6])
        + b"\x00\x00"
        + bytes([192, 168, 1, 10])
        + bytes([192, 168, 1, 50])
    )
    tcp = (
        struct.pack("!HH", sport, dport)
        + struct.pack("!II", 1, 0)
        + bytes([0x50, 0x18])
        + struct.pack("!H", 64240)
        + b"\x00\x00\x00\x00"
    )
    return eth + ip + tcp + payload


def tuya_wrap(payload: bytes, cmd: int = 0x08) -> bytes:
    return (
        b"\x00\x00\x55\xaa"
        + struct.pack("!III", 1, cmd, len(payload) + 8)
        + payload
        + b"\x00\x00\x00\x00"
        + b"\x00\x00\xaa\x55"
    )


def write_pcap(path: Path, packets: list[bytes]) -> None:
    header = b"\xd4\xc3\xb2\xa1" + struct.pack("<HHIIII", 2, 4, 0, 0, 65535, 1)
    body = b""
    for i, pkt in enumerate(packets):
        body += struct.pack("<IIII", 1700000000 + i, 0, len(pkt), len(pkt)) + pkt
    path.write_bytes(header + body)


def test_pcap_roundtrip_and_frame_decode(tmp_path):
    tool = load_tool()
    payload = commands.wake() + aa.encode(0x27, bytes([1, 2, 0, 4]))
    pcap = tmp_path / "test.pcap"
    write_pcap(pcap, [tcp_packet(tuya_wrap(payload))])

    packets = list(tool.read_pcap(pcap))
    assert len(packets) == 1
    parsed = tool.parse_packet(packets[0][1])
    assert parsed is not None
    src, dst, sport, dport, data = parsed
    assert (src, dst, sport, dport) == ("192.168.1.10", "192.168.1.50", 45678, 6668)

    frames = list(tool.tuya_frames(data))
    assert len(frames) == 1
    assert frames[0]["cmd"] == 0x08
    decoded = aa.decode_frames(frames[0]["payload"])
    assert [f.name for f in decoded] == ["wake", "room_order"]


def test_non_tuya_port_ignored(tmp_path):
    tool = load_tool()
    pcap = tmp_path / "test.pcap"
    write_pcap(pcap, [tcp_packet(b"hello", sport=1234, dport=443)])
    parsed = tool.parse_packet(list(tool.read_pcap(pcap))[0][1])
    assert parsed is not None
    assert parsed[3] == 443


def test_frame_splitter_resyncs_on_garbage():
    tool = load_tool()
    payload = commands.wake()
    stream = b"\xde\xad\xbe\xef" + tuya_wrap(payload) + b"\x00\x01" + tuya_wrap(payload)
    frames = list(tool.tuya_frames(stream))
    assert len(frames) == 2
    assert all(f["cmd"] == 0x08 for f in frames)


def test_json_dp15_value_is_base64_decoded():
    """On the wire a raw DP is base64 inside the protocol JSON (unlike the panel's hex)."""
    tool = load_tool()
    payload = commands.wake()
    body = json.dumps({"dps": {"15": base64.b64encode(payload).decode()}}).encode()
    joined = "\n".join(tool.describe_payload(body))
    assert "DP15" in joined
    assert "wake" in joined


def test_json_voice_dp_is_decoded_and_shows_the_url():
    tool = load_tool()
    frame = voice.VoiceRequest(502, "0" * 32, "http://192.168.1.10/pack.zip").frame()
    body = json.dumps({"dps": {"162": base64.b64encode(frame).decode()}}).encode()
    joined = "\n".join(tool.describe_payload(body))
    assert "AB cmd=0x34" in joined
    assert "voice install: id=502" in joined
    assert "http://192.168.1.10/pack.zip" in joined


def test_dp_value_accepts_hex_strings_too():
    tool = load_tool()
    payload = commands.fault_recovery()
    body = json.dumps({"dps": {"15": payload.hex()}}).encode()
    assert "fault_recovery" in "\n".join(tool.describe_payload(body))

