# Popelka

Reverse-engineering toolkit for a **Concept VR3125** robot vacuum (Concept VR3125
2v1 Perfect Clean Laser).

The VR3125 is an LDROBOT-built, laser-navigation vacuum that runs the Tuya
cloud stack: its app is `com.ldrobot.tyw2concept` ("Concept Robot"), and the
newer `com.concept.www` ("Concept Home") is built on the Tuya Smart Life SDK.
That means the robot speaks the well-documented **Tuya laser-vacuum protocol**:

* a flat datapoint (DP) interface for status and simple commands,
* a binary "AA frame" protocol multiplexed through **DP15 `command_trans`**,
* a cloud **Sweeper** API for maps, and a **P2P** channel for live map/path.

Nothing here needs the robot opened up - it is all software.

## Install

```bash
uv sync
uv run popelka dps          # datapoint catalogue
uv run popelka frames AA00064D013B9ACA03F0
```

`tinytuya` (needed only for local TCP control on port 6668) is an optional
extra because its `cryptography` dependency has no Android wheel:

```bash
pkg install python-cryptography   # Termux
uv pip install tinytuya
```

## What is implemented

| Module | Purpose |
|---|---|
| `popelka.aa` | AA frame encode/decode, checksum, coordinate conversion |
| `popelka.dp` | Datapoint catalogue, enums, fault codes, app presets |
| `popelka.commands` | Builders for wake, sync bundle, room/zone/spot commands, fault recovery |
| `popelka.maps` | Decoder for the LZ4-compressed map files from the cloud |
| `popelka.tuya` | Local (tinytuya) + cloud (IoT API) transports |
| `popelka.cli` | `popelka frames|build|map|dps|faults` |

## Quick examples

Decode captured traffic:

```bash
uv run popelka frames "AA 00 06 4D 01 3B 9A CA 03 F0"
```

Build a room-clean command (room 0 = global settings, room 4 = strong/high suction,
2 passes):

```bash
uv run popelka build room --rooms 0:ff:ff:1 4:3:2:2
```

Decode a map file pulled from the cloud:

```bash
uv run popelka map map.bin --out map.pgm
```

## Documentation

* [`docs/RE.md`](docs/RE.md) - findings, protocol notes, and the step-by-step
  plan for your specific robot.
* [`docs/ROADMAP.md`](docs/ROADMAP.md) - what to try next, in order.
