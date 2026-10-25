"""Voice-pack channel: the Tuya `voice_data` datapoint (commands 0x34 / 0x35).

Provenance (see docs/VOICE.md for the full story):

* Tuya's "Laser Robot Vacuum Template" docs name the ``voice_data`` DP and tell
  panel developers to call ``encodeVoice0x34`` / ``decodeVoice0x35`` from
  ``@ray-js/robot-protocol``.
* The byte layout below was read from that package, v1.0.6, ``dist/index.mjs``::

      encodeVoice0x34({id, md5, url})  =  extended("34", data)
      data = id:u32be | len(md5):u8 | md5:ascii | len(url):u32be | url:utf8

  and the *extended* frame (a sibling of the AA frame in :mod:`popelka.aa`) is::

      AB 00 | len:u32be | cmd:u8 | data | checksum:u8
      len      = 1 + len(data)            # cmd + data, checksum excluded
      checksum = sum(cmd + data) & 0xFF

* The robot downloads the ZIP itself over HTTP(S), verifies the MD5, installs
  it and reports progress with 0x35::

      report data = pack_id:u32be | status:u8 | progress:u8

This has **not** been observed on the VR3125 yet. The sibling Eufy L50 (also
Tuya) uses the same idea with a different encoding (base64 protobuf in DP162),
which is strong evidence that the mechanism - not necessarily the DP id - is
right. See docs/VOICE.md for the experiment that confirms it.
"""

from __future__ import annotations

import string
from dataclasses import dataclass

EXT_MAGIC = 0xAB
EXT_VERSION = 0x00

CMD_VOICE_SET = 0x34
CMD_VOICE_REPORT = 0x35

#: Hypothesised DP id for ``voice_data`` on Tuya vacuums. Eufy's Tuya build uses
#: 162 for exactly this; LDROBOT may renumber. Confirm from the cloud DP schema.
DP_VOICE_DATA = 162

_HEX = set(string.hexdigits)


class VoiceError(ValueError):
    """Raised when a voice request is malformed."""


@dataclass(frozen=True)
class VoiceRequest:
    """A 0x34 "install this voice pack" command."""

    pack_id: int
    md5: str
    url: str

    def data(self) -> bytes:
        if not 0 <= self.pack_id <= 0xFFFFFFFF:
            raise VoiceError(f"pack_id out of u32 range: {self.pack_id}")
        md5 = self.md5.strip().lower()
        if len(md5) != 32 or not set(md5) <= _HEX:
            raise VoiceError("md5 must be 32 hex characters (of the ZIP bytes)")
        if not self.url:
            raise VoiceError("url is required - the robot downloads the pack itself")
        md5_bytes = md5.encode("ascii")
        url_bytes = self.url.encode("utf-8")
        if len(md5_bytes) > 0xFF:
            raise VoiceError("md5 too long")
        if len(url_bytes) > 0xFFFFFFFF:
            raise VoiceError("url too long")
        return (
            self.pack_id.to_bytes(4, "big")
            + bytes([len(md5_bytes)])
            + md5_bytes
            + len(url_bytes).to_bytes(4, "big")
            + url_bytes
        )

    def frame(self) -> bytes:
        return encode_extended(CMD_VOICE_SET, self.data())

    def dp_value(self) -> str:
        """The hex string the ``voice_data`` DP carries (what the app sends)."""
        return self.frame().hex()


@dataclass(frozen=True)
class VoiceReport:
    """A 0x35 install-progress report from the robot."""

    pack_id: int
    status: int
    progress: int

    def describe(self) -> str:
        # Status labels are unverified on this robot; keep the number visible.
        return f"voice pack {self.pack_id}: status={self.status} progress={self.progress}%"


@dataclass(frozen=True)
class ExtendedFrame:
    cmd: int
    data: bytes
    raw: bytes
    offset: int = 0


def encode_extended(cmd: int, data: bytes) -> bytes:
    """Build an ``AB 00`` extended frame (used by voice packs and other features)."""
    body = bytes([cmd & 0xFF]) + bytes(data)
    if len(body) > 0xFFFFFFFF:
        raise VoiceError("payload too long")
    return (
        bytes([EXT_MAGIC, EXT_VERSION])
        + len(body).to_bytes(4, "big")
        + body
        + bytes([sum(body) & 0xFF])
    )


def decode_frames(buf: bytes) -> list[ExtendedFrame]:
    """Find every valid extended frame in ``buf``.

    Bad checksums are skipped and the scanner resyncs, exactly like
    :func:`popelka.aa.decode_frames`, because captures are cut arbitrarily.
    """
    frames: list[ExtendedFrame] = []
    i = 0
    n = len(buf)
    while i + 6 <= n:
        if buf[i] != EXT_MAGIC or buf[i + 1] != EXT_VERSION:
            i += 1
            continue
        length = int.from_bytes(buf[i + 2 : i + 6], "big")
        if length < 1:
            i += 1
            continue
        end = i + 6 + length
        if end >= n:  # no room for the checksum
            break
        body = buf[i + 6 : end]
        checksum = buf[end]
        if checksum != sum(body) & 0xFF:
            i += 1
            continue
        frames.append(ExtendedFrame(cmd=body[0], data=body[1:], raw=buf[i : end + 1], offset=i))
        i = end + 1
    return frames


def decode_requests(buf: bytes) -> list[VoiceRequest]:
    """Decode all 0x34 frames - handy when reading a capture or a DP dump."""
    out: list[VoiceRequest] = []
    for frame in decode_frames(buf):
        if frame.cmd != CMD_VOICE_SET:
            continue
        data = frame.data
        if len(data) < 5:
            continue
        pack_id = int.from_bytes(data[0:4], "big")
        md5_len = data[4]
        pos = 5
        if pos + md5_len + 4 > len(data):
            continue
        md5 = data[pos : pos + md5_len].decode("ascii", errors="replace")
        pos += md5_len
        url_len = int.from_bytes(data[pos : pos + 4], "big")
        pos += 4
        if pos + url_len > len(data):
            continue
        url = data[pos : pos + url_len].decode("utf-8", errors="replace")
        out.append(VoiceRequest(pack_id=pack_id, md5=md5, url=url))
    return out


def decode_reports(buf: bytes) -> list[VoiceReport]:
    """Decode all 0x35 frames (robot -> app install progress)."""
    out: list[VoiceReport] = []
    for frame in decode_frames(buf):
        if frame.cmd != CMD_VOICE_REPORT or len(frame.data) < 6:
            continue
        out.append(
            VoiceReport(
                pack_id=int.from_bytes(frame.data[0:4], "big"),
                status=frame.data[4],
                progress=frame.data[5],
            )
        )
    return out


def from_hex(text: str) -> bytes:
    """Parse hex as written by the app / Wireshark (spaces, colons, 0x allowed)."""
    cleaned = text.strip().replace(" ", "").replace(":", "").replace("-", "").replace("\n", "")
    if cleaned.lower().startswith("0x"):
        cleaned = cleaned[2:]
    try:
        return bytes.fromhex(cleaned)
    except ValueError as exc:
        raise VoiceError(f"not valid hex: {exc}") from exc


def describe(buf: bytes) -> str:
    """Human-readable dump for a captured voice payload."""
    lines: list[str] = []
    for frame in decode_frames(buf):
        lines.append(
            f"@{frame.offset:04X} cmd=0x{frame.cmd:02X} len={len(frame.data):<3} "
            f"data={frame.data.hex(' ')}"
        )
    for request in decode_requests(buf):
        lines.append(f"  install: {request.url} (id={request.pack_id}, md5={request.md5})")
    for report in decode_reports(buf):
        lines.append(f"  report: {report.describe()}")
    if not lines:
        return "<no valid extended frames found>"
    return "\n".join(lines)
