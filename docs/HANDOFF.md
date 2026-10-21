# Handoff - Concept VR3125 reverse engineering

Written at the end of the Termux session so that a fresh OpenCode session on the Linux PC
can continue immediately. Companion to `AGENTS.md` (auto-loaded context) and `docs/RE.md`
(protocol notes).

## 1. The story so far

The user asked "what can I do with my robot vacuum on the software side?". Questions
established:

* **Device**: Concept VR3125 2v1 Perfect Clean Laser.
* **Constraint**: software only, no disassembly.
* **Motivation**: learning / reverse engineering (also: own UI, get rid of the vendor app,
  custom sounds).
* **Network**: phone (Android) + Linux PC + this Termux box, all on one flat LAN.

Research established that the VR3125 is an **LDROBOT** machine running the **Tuya**
platform, so the protocol family is known and the work is mostly *confirmation and
extension* rather than blind reverse engineering. A prior RE project (Philips HomeRun
XU3100, same Tuya laser-vacuum solution) documented the DP layout, the AA-frame binary
protocol, the coordinate system, the fault codes and the cloud map endpoints - that
document is the current hypothesis set, and this repo encodes it as code so it can be
tested and extended.

The repo went from empty to: protocol codec, command builders, cloud client, APK scanner,
cloud dumper, mitmproxy capture addon, CLI, tests (14 passing), and docs.

## 2. Where the protocol stands

**Inherited from upstream RE work (unverified on this device):**

| Item | Value | Confidence |
|---|---|---|
| Frame layout | `AA len_hi len_lo cmd payload checksum`, `checksum = sum(cmd+payload)&0xFF` | high |
| Command channel | DP15 `command_trans`, often a *bundle* of frames in one write | high |
| Wake | cmd `0x4D`, payload `01 3B 9A CA 03` | high |
| Sync bundle | `0x57`/`0x55`/`0x39`/`0x13`/`0x53` stubs | high |
| Room config | cmd `0x51`, 10-byte block: `id 05 00 b1 b2 passes suction water 01 00` | high for layout, `b1`/`b2` unknown |
| Room order | cmd `0x27`, `01 <count> <ids...>` | high |
| Zone | cmd `0x55`, corners as int16 BE, 200 units = 1 m, origin at dock | high |
| Spot | cmd `0x57` (roles swapped vs. zone) | high |
| Fault recovery | cmd `0x4C` | medium |
| DP ids | 1..132 as listed in `src/popelka/dp.py` | medium - LDROBOT may differ |
| Fault codes | 0 / 0x80 / 0x4000000 | medium |
| Map file | 24-byte header (12 x uint16 BE) + LZ4 block; grid then room names | medium |

**Verified by construction** (our encoders reproduce the upstream captures byte for byte,
unit-tested): the wake frame, the fault-recovery frame, the room block, the room order.

**The single most valuable unknown**: the *real* DP schema of this robot. The cloud status
dump settles it in one command. Everything else keys off that.

## 3. Open questions (numbered, so they can be ticked off)

1. Does the VR3125 expose the same DP ids and enums as the Philips unit?
2. What are the per-room `b1`/`b2` bytes on this device, and what do they encode?
3. Is room cleaning exposed as `mode=part` or `mode=selectroom` here?
4. Does the robot answer on TCP 6668, and does the cloud user-device list include
   `local_key` and the LAN `ip`?
5. Does `path_data` (DP14) ever carry the live path over the local socket, or is it P2P-only?
6. What are the 12 header fields of a downloaded map file, and how do map coordinates
   relate to robot coordinates (origin, mirroring, rotation)?
7. Are the room names in the map tail UTF-8, UTF-16 or GB18030?
8. Does LDROBOT add its own opcodes beyond the Tuya reference set?

## 4. What the user must provide

| # | Artifact | How |
|---|---|---|
| 1 | APK of "Concept Home" (`com.concept.www`) | `adb shell pm path com.concept.www` + `adb pull`, or APK Extractor app, or APKMirror |
| 2 | Concept account credentials | `.env` on the PC: `TUYA_USER`, `TUYA_PASS`, `TUYA_REGION=eu` (never commit) |
| 3 | Robot's LAN IP | router DHCP list |
| 4 | OK to re-sign the app with a mitm CA | needed for Android MITM (Play updates for that app stop working) |
| 5 | Whether a clean can be started remotely | decides whether captures need someone at home |
| 6 | A known landmark for coordinate calibration | e.g. "the kitchen table leg is at x=..., y=..." once the map renders |

## 5. The plan, in order

### Phase A - APK (no robot needed)

```bash
python tools/apk_scan.py concept-home.apk --secrets-out data/app_secrets.json
```

Look for: Tuya `appKey`/`appSecret` (needed to sign cloud calls if plain login fails), the
region host, P2P endpoints, and DP name strings. Cross-check the DP names against
`src/popelka/dp.py`.

### Phase B - Cloud (the big unlock)

```bash
export TUYA_USER=... TUYA_PASS=... TUYA_REGION=eu
python tools/cloud_dump.py --out data/ --download-maps
```

Produces `data/devices.json` (ids, names, **local_key**, ip), `data/status.json` (live DPs),
`data/specs.json` (DP id -> code), `data/maps.json` + `data/maps/*.bin`.

Then: **update `src/popelka/dp.py` with the real schema and commit it** - that is the
first genuine finding of this project.

### Phase C - Local control

`local_key` + `ip` from `data/devices.json` are enough to talk to the robot directly:

```python
from popelka.tuya import LocalDevice
dev = LocalDevice(ip="<ip>", local_key="<key>", device_id="<id>")
print(dev.status())
```

Then replay a captured bundle. If a raw DP15 write is needed, `dev.send_raw_dp15(payload)`
takes bytes straight from `popelka.commands`.

### Phase D - Capture the truth (MITM)

Phone Wi-Fi proxy -> `PC:8080`; `mitmdump -s tools/mitm_dp15.py`. Drive a full cleaning job
from the app: start, pause, room select, zone, spot, stop, dock, and let it hit a fault.
Every `command_trans` payload is printed decoded.

Then diff against the hypothesis set and fix `src/popelka/commands.py` where LDROBOT
differs. Capture the per-room `b1`/`b2` bytes from the device->app `0x53` status frame.

### Phase E - Maps

Reverse the 24-byte header, render the grid, calibrate against the app's map, decode room
names. Output: PNG/JSON floor plans in git, diffable between runs.

### Phase F - The good stuff

Home Assistant integration, own web UI, per-room named cleaning, "angry Austrian painter"
sound hacks (the user's own idea), telemetry dashboards, the anti-stuck watchdog using
cmd `0x4C`, and finally the P2P protocol for the live path.

## 6. Gotchas learned the hard way

* `tinytuya` depends on `cryptography`, which has **no Android wheel** - on Termux use
  `pkg install python-cryptography` and `uv pip install tinytuya`; that is why it is an
  optional extra in `pyproject.toml`.
* Tuya login has two flows: `POST /v1.0/token?grant_type=1` with base64 credentials
  (what the vendor apps use), and the signed `POST /v2.0/auth/token` (HMAC-SHA256 over
  sorted params, needs the app key). `popelka.cloud.Account.login()` tries the first and
  falls back to the second.
* The Tuya user-device list is where the **local key** lives; that is the single most
  valuable credential in this project.
* The map never arrives over TCP 6668 - it goes up through P2P and comes back via the
  cloud Sweeper API. Do not waste time hunting for it on the local socket.
* Coordinate conversions in `popelka/aa.py` assume 200 units = 1 m. That is upstream
  evidence; verify before sending any motion command.

## 7. Git / workflow

* Remote: `git@github.com:ffdzzr/Popelka.git`, branch `main`, SSH key authorised.
* Push after each meaningful step (`make push MESSAGE="..."`).
* **Secrets never in git.** `.env`, `data/`, `private/`, `vault/`, `captures/`, `*.apk`,
  `*.bin` are gitignored *and* blocked by the pre-commit hook
  (`bash scripts/install_hooks.sh` once per machine). The guard lives in
  `scripts/check_secrets.sh` + `scripts/secret_patterns.txt`.
* Move sensitive artifacts between machines with `scripts/vault.sh pack` ->
  encrypted archive -> `scp` over the LAN -> `vault.sh unpack`. Never through a public
  repo.
* Mask credentials in anything shown to the user (the local key is masked in
  `tools/cloud_dump.py` stdout).
* Keep `uv run pytest -q` green.
* Record every new fact with its provenance in `docs/RE.md` ("captured on VR3125" vs.
  "inherited from XU3100 work").
* Append a line to `docs/JOURNAL.md` after each step; it is the fastest way for the next
  session to know where things stand.

## 8. Seamless phone <-> PC switching (what was built for this)

| Need | Tool |
|---|---|
| one command per step | `Makefile` (`make help`) |
| run the app's traffic through the PC | `scripts/capture.sh` (mitmproxy + DP15 decoder) |
| make the Android app trust the mitm CA | `scripts/resign_apk.sh` (apktool + network security config + re-sign) |
| send real commands to the robot from any machine | `uv run python -m popelka.replay status|room|zone|spot|fault|raw` |
| carry credentials/APKs/captures between machines safely | `scripts/vault.sh` (encrypted, LAN only) |
| never commit a secret by accident | `scripts/install_hooks.sh` (pre-commit) + `scripts/check_secrets.sh --all` |
| know where the work stands | `docs/JOURNAL.md` (tail) + `AGENTS.md` (auto-loaded) |

Full loop, roles and hygiene rules: `docs/WORKFLOW.md`.

## 9. Open items still waiting on the user

1. Concept Home APK (`com.concept.www`) -> `make scan APK=...`
2. Concept account credentials in `.env` -> `make cloud-dump`
3. Robot LAN IP -> `make replay ARGS="status"`
4. OK to re-sign the app with a mitm CA -> `make resign APK=... OUT=...`
5. A known landmark for coordinate calibration, before any motion command.
