# Popelka

[Popelka == Cinderella](https://en.wikipedia.org/wiki/Cinderella)

## About

This project is to tinker with robotic vacuum cleaner **Concept VR3125**

## Ideas

- Make my own UI

- Change sounds to R2D2, maybe some angry Austrian painter

- Get rid of the app that comes with it and enjoy privacy plus own features

---

## vibe coded docs:

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

* [`AGENTS.md`](AGENTS.md) - auto-loaded working notes for OpenCode/agents in this repo.
* [`docs/HANDOFF.md`](docs/HANDOFF.md) - **session handover**: findings, open questions,
  what the user still has to provide, and the exact next commands.
* [`docs/WORKFLOW.md`](docs/WORKFLOW.md) - the phone <-> PC <-> Termux loop and the
  secret-hygiene rules.
* [`docs/JOURNAL.md`](docs/JOURNAL.md) - append-only log of what was done; read the tail
  to pick up where the last session left off.
* [`docs/RE.md`](docs/RE.md) - findings, protocol notes, and the step-by-step
  plan for your specific robot.
* [`docs/ROADMAP.md`](docs/ROADMAP.md) - what to try next, in order.

## One command per step

```bash
make help            # list every task
make setup           # PC toolchain (mitmproxy, jadx, adb, tshark)
make scan APK=concept-home.apk     # mine the APK for the Tuya app key + DP names
make cloud-dump      # devices, live DPs, specs, maps  (needs .env)
make capture         # mitmproxy with the DP15 decoder
make resign APK=...  # re-sign the app so it trusts mitm's CA
make replay ARGS="status"          # talk to the robot over the local socket
make check-secrets   # leak guard (also runs as a pre-commit hook)
make vault-push      # encrypted archive of sensitive artifacts
make push MESSAGE="..."
```

## Lab setup (Linux PC + Android phone)

Division of labour: the **PC is the lab** (APK analysis, mitmproxy, Wireshark),
the **phone is only the app client**, and any machine on the LAN (including a
Termux box) can act as the direct robot client.

```bash
bash scripts/setup_linux.sh          # uv, mitmproxy, jadx/apktool hints, adb, tshark
```

### 1. Get the Concept Home APK (`com.concept.www`)

On the phone: `adb shell pm path com.concept.www` then `adb pull <path> .`
(or export it with "APK Extractor"). On the PC: grab it from APKMirror.

### 2. Static analysis - find the Tuya app key/secret and DP names

```bash
python tools/apk_scan.py concept-home.apk --secrets-out data/app_secrets.json
```

### 3. Cloud access - dump the robot's real datapoint schema

```bash
export TUYA_USER=... TUYA_PASS=... TUYA_REGION=eu
python tools/cloud_dump.py --out data/ --download-maps
```

The device list from the Tuya user API also yields the device's **local key**,
which unlocks direct LAN control on TCP 6668 (no cloud, no app).

### 4. Live capture - see what the app really sends

```bash
mitmdump -s tools/mitm_dp15.py --listen-host 0.0.0.0 --listen-port 8080
# phone: Wi-Fi proxy -> PC:8080, install the mitm CA, then run a clean
```

`tools/mitm_dp15.py` prints and decodes every `command_trans` payload on the
fly. If the app refuses the user CA (Android 7+ default), re-sign the APK with
the mitm CA embedded - the script's README section explains it.

## Security hygiene

`.env`, `data/`, `*.apk` and captures are gitignored. Keep the Concept account
password out of git; `tools/cloud_dump.py` reads it from the environment.
