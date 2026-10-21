"""Decoder for the map files the robot uploads to the Tuya cloud.

The map files fetched from
``GET /v1.0/users/sweepers/file/{device_id}/download`` use a 24 byte header
(12 big-endian uint16) followed by LZ4-compressed data.  After decompression
the first ``width * height`` bytes are the occupancy grid, the remainder holds
the room-name section.

The exact header layout is not publicly documented, so :func:`decode_map`
*infers* it by trying the candidate field combinations and validating the
result against the known cell values.  Every inference is reported so the
output can be checked against the app's own map rendering.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import lz4.block
import lz4.frame

# Cell values observed in the decompressed grid.
CELL_FREE = 0xF4
CELL_WALL = 0xF9
CELL_BACKGROUND = 0xFF
#: Room cells are 0x04 * room_id (0x00, 0x04, 0x08, 0x0C, 0x10).
ROOM_STRIDE = 4
KNOWN_CELLS = {0x00, 0x04, 0x08, 0x0C, 0x10, CELL_FREE, CELL_WALL, CELL_BACKGROUND}

HEADER_SIZE = 24
HEADER_FIELDS = 12


@dataclass
class MapData:
    """A decoded floor plan."""

    width: int
    height: int
    grid: bytes
    names: bytes = b""
    header: list[int] = field(default_factory=list)
    compressed_length: int = 0
    notes: list[str] = field(default_factory=list)

    def cell(self, x: int, y: int) -> int:
        return self.grid[y * self.width + x]

    def room_ids(self) -> set[int]:
        return {c // ROOM_STRIDE for c in self.grid if c in {0x00, 0x04, 0x08, 0x0C, 0x10}}

    def decode_names(self) -> dict[int, str]:
        """Best-effort decode of the trailing room-name section."""
        names: dict[int, str] = {}
        if not self.names:
            return names
        for encoding in ("utf-8", "utf-16-le", "gb18030", "latin-1"):
            try:
                text = self.names.decode(encoding)
            except UnicodeDecodeError:
                continue
            parts = [p for p in text.replace("\x00", "\n").split("\n") if p.strip()]
            if parts:
                for i, part in enumerate(parts):
                    names[i] = part.strip()
                return names
        return names

    def to_pgm(self) -> bytes:
        """Portable graymap render of the grid (walls dark, free light)."""
        out = bytearray(f"P5\n{self.width} {self.height}\n255\n".encode())
        for y in range(self.height):
            for x in range(self.width):
                c = self.cell(x, y)
                if c == CELL_WALL:
                    out.append(0)
                elif c == CELL_BACKGROUND:
                    out.append(255)
                elif c == CELL_FREE:
                    out.append(220)
                else:
                    out.append(60 + (c // ROOM_STRIDE) * 30)
        return bytes(out)


def _plausible(grid: bytes) -> bool:
    if not grid:
        return False
    unknown = set(grid) - KNOWN_CELLS
    return not unknown


def _candidate_sizes(fields: list[int]) -> set[int]:
    sizes: set[int] = set()
    for a in fields:
        if a:
            sizes.add(a)
        for b in fields:
            if a and b and a * b <= 4_000_000:
                sizes.add(a * b)
    return sizes


def decode_map(data: bytes, width: int | None = None, height: int | None = None) -> MapData:
    """Decode a downloaded map file.

    If ``width``/``height`` are given they are used directly, otherwise they
    are inferred from the header.
    """
    if len(data) < HEADER_SIZE:
        raise ValueError("map file too short")

    fields = [int.from_bytes(data[i : i + 2], "big") for i in range(0, HEADER_SIZE, 2)]
    body = data[HEADER_SIZE:]
    notes: list[str] = []

    decompressed: bytes | None = None
    used_cl = 0

    # 1) LZ4 frame format (self describing size).
    for cl in sorted({len(body), *(f for f in fields if 0 < f <= len(body))}):
        try:
            decompressed = lz4.frame.decompress(body[:cl])
            used_cl = cl
            notes.append(f"lz4 frame, compressed_length={cl}")
            break
        except Exception:  # noqa: BLE001 - try the next candidate
            continue

    # 2) Raw LZ4 block, guessing the uncompressed size.
    if decompressed is None:
        sizes = _candidate_sizes(fields)
        for cl in sorted({f for f in fields if 0 < f <= len(body)} | {len(body)}):
            chunk = body[:cl]
            for size in sorted(sizes):
                try:
                    out = lz4.block.decompress(chunk, uncompressed_size=size)
                except Exception:  # noqa: BLE001
                    continue
                if len(out) < size:
                    continue
                if width and height:
                    grid_len = width * height
                else:
                    grid_len = None
                if grid_len is None:
                    # Find a plausible grid length: the tail is the name section.
                    grid_len = _guess_grid_len(out, sizes)
                    if grid_len is None:
                        continue
                grid = out[:grid_len]
                if not _plausible(grid):
                    continue
                decompressed = out
                used_cl = cl
                notes.append(f"lz4 block, compressed_length={cl}, size={size}")
                break
            if decompressed is not None:
                break

    if decompressed is None:
        raise ValueError("could not decompress map payload (unknown header layout?)")

    if width and height:
        w, h = width, height
    else:
        w, h = _guess_dims(decompressed, fields)
        notes.append(f"inferred dimensions {w}x{h}")

    grid = decompressed[: w * h]
    names = decompressed[w * h :]
    return MapData(
        width=w,
        height=h,
        grid=grid,
        names=names,
        header=fields,
        compressed_length=used_cl,
        notes=notes,
    )


def _guess_grid_len(out: bytes, sizes: set[int]) -> int | None:
    for n in sorted(sizes):
        if 0 < n <= len(out) and _plausible(out[:n]):
            return n
    return None


def _guess_dims(out: bytes, fields: list[int]) -> tuple[int, int]:
    for a in fields:
        for b in fields:
            if a and b and a * b == len(out):
                return max(a, b), min(a, b)
    # Fall back to the largest square that fits.
    side = int(len(out) ** 0.5)
    return side, side
