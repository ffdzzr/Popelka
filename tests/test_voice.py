"""Tests for the voice-pack channel (Tuya `voice_data`, 0x34/0x35).

The expected bytes were derived from the reference implementation in
``@ray-js/robot-protocol@1.0.6`` (see the module docstring in
:mod:`popelka.voice`); they are hard-coded here so a refactor cannot quietly
change the wire format.
"""

from __future__ import annotations

import pytest
from popelka import voice

MD5 = "0" * 32
URL = "http://x/y"


def test_encode_voice_request_matches_reference_implementation():
    request = voice.VoiceRequest(pack_id=502, md5=MD5, url=URL)
    # AB 00 | len=0x34 | cmd=34 | id=502 | md5len=32 | md5 | urllen=10 | url | sum
    expected = (
        "ab000000003434"
        "000001f6"
        "20"
        + "30" * 32
        + "0000000a"
        + URL.encode().hex()
        + "cd"
    )
    assert request.frame().hex() == expected


def test_dp_value_is_the_hex_string_the_app_sends():
    request = voice.VoiceRequest(pack_id=1, md5=MD5, url=URL)
    assert request.dp_value() == request.frame().hex()
    assert all(c in "0123456789abcdef" for c in request.dp_value())


def test_request_roundtrip():
    request = voice.VoiceRequest(pack_id=77, md5="a" * 32, url="https://example.test/a.zip")
    decoded = voice.decode_requests(voice.from_hex(request.dp_value()))
    assert decoded == [request]


def test_report_decode():
    data = (502).to_bytes(4, "big") + bytes([2, 100])
    frame = voice.encode_extended(voice.CMD_VOICE_REPORT, data)
    reports = voice.decode_reports(frame)
    assert reports == [voice.VoiceReport(pack_id=502, status=2, progress=100)]
    assert "status=2" in reports[0].describe()


def test_rejects_bad_md5_and_bad_hex():
    with pytest.raises(voice.VoiceError):
        voice.VoiceRequest(pack_id=1, md5="abc", url=URL).frame()
    with pytest.raises(voice.VoiceError):
        voice.VoiceRequest(pack_id=1, md5="z" * 32, url=URL).frame()
    with pytest.raises(voice.VoiceError):
        voice.from_hex("not hex")


def test_decoder_resyncs_on_garbage():
    request = voice.VoiceRequest(pack_id=5, md5=MD5, url=URL)
    blob = b"\xde\xad" + request.frame() + b"\x00\x01" + request.frame()
    assert len(voice.decode_frames(blob)) == 2
    assert voice.decode_requests(blob) == [request, request]


def test_checksum_is_validated():
    frame = bytearray(voice.VoiceRequest(pack_id=5, md5=MD5, url=URL).frame())
    frame[-1] ^= 0xFF
    assert voice.decode_frames(bytes(frame)) == []
