# AGENTS.md - working notes for OpenCode in this repo

Read this first. It is the context handover for the Concept VR3125 reverse-engineering project.

## SESSION START - do these three things before anything else

1. **Run `make start`** (or `bash scripts/doctor.sh` then read the tail of
   `docs/JOURNAL.md`). It prints: toolchain status, whether the tree is clean and
   pushed, whether tests pass, which credentials/artifacts exist (credentials are
   masked), whether the robot answers, and **the next command to run**.
2. **Read `docs/HANDOFF.md`** (narrative state, open questions, gotchas) and the tail of
   `docs/JOURNAL.md` (what actually happened, in order).
3. **Check `git status` / `git log --oneline -5`.** If the tree is dirty, the previous
   session stopped mid-step - finish that step before starting a new one.

Then continue with the "Next steps" section at the bottom of this file. Do not
re-derive the protocol from scratch: it is already encoded in `src/popelka/`, with
confidence levels marked in `docs/RE.md`.

If the user switches machines mid-task: `git pull` on the new machine, and the same
three steps above apply. `AGENTS.md` is in the repo, so it travels with the code.

## Project in one paragraph

The user owns a **Concept VR3125 2v1 Perfect Clean Laser** robot vacuum (3300 Pa, LiDAR
navigation, mop) and wants to reverse-engineer it **software-only - no disassembly**. Goal:
own the device, own the data, own the UI, get rid of the vendor app/cloud. The user is
explicitly doing this to *learn*, so explain the "why" and keep the reasoning visible in
code comments and docs.

## Device facts (verified by research, not yet by capture)

* OEM is **LDROBOT** (Shenzhen LD Technology), product line `TYW2`.
* Apps: **`com.concept.www` ("Concept Home") - the one the user actually uses**;
  older `com.ldrobot.tyw2concept` ("Concept Robot").
* Both are built on the **Tuya Smart Life SDK** -> the robot speaks the Tuya
  laser-vacuum protocol: flat datapoints (DPs), a binary **AA frame** protocol inside
  **DP15 `command_trans`**, a cloud **Sweeper API** for maps, and a **P2P** channel for
  live map/path.
* Local Tuya protocol on **TCP 6668**; needs the device's **local key**.

## Environment / roles

| Where | What it is | Notes |
|---|---|---|
| Termux (Android, this session) | always-on client on the LAN | can talk to the robot; `tinytuya` needs `pkg install python-cryptography` (no Android wheel for uv) |
| Linux PC | the lab | jadx, apktool, mitmproxy, adb, tshark; `scripts/setup_linux.sh` installs the lot |
| Android phone | app client only | "Concept Home" app; can re-sign the APK with a mitm CA (needs the user's OK) |

All three are on **one flat LAN**: phone -> PC proxy -> internet, robot reachable directly.

Git: remote `git@github.com:ffdzzr/Popelka.git`, branch `main`, SSH key already authorised.
Push freely; the user asked for the work to be pushed.

## Repo layout

```
src/popelka/aa.py        AA frame codec, checksum, robot-unit conversions
src/popelka/dp.py        DP catalogue, enums, fault codes, app presets
src/popelka/commands.py  builders: wake, sync bundle, room/zone/spot, fault recovery
src/popelka/maps.py      LZ4 map-file decoder (header inferred, inferences reported)
src/popelka/cloud.py     Tuya IoT login (grant_type=1 + signed v2.0), devices, DPs, maps
src/popelka/tuya.py      local transport (tinytuya) + thin cloud client
src/popelka/replay.py    send real commands to the robot (python -m popelka.replay ...)
src/popelka/cli.py       popelka frames|build|map|dps|faults
tools/apk_scan.py        DEX string mining -> Tuya app key/secret, hosts, DP names
tools/cloud_dump.py      dump devices, live DPs, specs, map list + downloads
tools/mitm_dp15.py       mitmproxy addon: decodes every command_trans payload live
tools/decode_payloads.py decode a file of captured hex/base64 payloads
tools/pcap_dp15.py       decode tcpdump captures of the phone<->robot TCP 6668 stream
scripts/setup_linux.sh   PC toolchain setup
scripts/resign_apk.sh    re-sign the app so it trusts mitm's CA (Android 7+ workaround)
scripts/capture.sh       run mitmproxy with the DP15 decoder
scripts/vault.sh         encrypted pack/unpack for moving secrets between machines
scripts/check_secrets.sh + scripts/secret_patterns.txt   leak guard (pre-commit)
scripts/install_hooks.sh install the leak guard as a git pre-commit hook
Makefile                 one command per step: make help
docs/RE.md               protocol notes (see the provenance warning below)
docs/ROADMAP.md          phased plan
docs/HANDOFF.md          full session context: findings, open questions, next steps
docs/WORKFLOW.md         phone <-> PC <-> Termux loop, secret hygiene rules
docs/CAPTURE.md          the three interception points + capture procedure (read before Phase D)
docs/JOURNAL.md          append-only log of what was actually done (read the tail!)
```

Working commands: `uv sync` then `uv run pytest -q`, `uv run popelka <cmd>`,
`make help` for the task list.

## Protocol summary (PROVENANCE WARNING)

`docs/RE.md` describes the **Tuya laser-vacuum protocol as reverse-engineered by others for
the Philips HomeRun XU3100** - an OEM sibling on the same Tuya solution. It has **not been
verified against this VR3125 yet**. Treat every specific value as a hypothesis until a
capture proves it:

* AA frame layout `AA len_hi len_lo cmd payload checksum` - high confidence, but verify.
* DP ids 1..132 and their names - from the Philips device; LDROBOT may renumber. **The
  cloud status dump will tell us the truth.**
* Room block bytes `b1`/`b2` in cmd 0x51 - device-specific, must be captured per room
  from *this* robot.
* Coordinate scale 200 units = 1 m, origin at dock - verify against a known landmark.
* Map file = 24 byte header (12 x uint16 BE) + LZ4 block; grid cell values
  `0xF4` free, `0xF9` wall, `0xFF` background, `0x04*room_id` room. Header layout unknown.

Verified-by-construction (matches upstream captures byte for byte):
`wake = AA 00 06 4D 01 3B 9A CA 03 F0`, `fault recovery = AA 00 01 4C 4C`,
room block `00 05 00 00 00 01 FF FF 01 00`, room order `27 01 02 00 04`.

## State of work

Done: protocol codec + command builders + tests; cloud client (login, devices, DP status,
specs, sweeper map endpoints); APK scanner; cloud dumper; mitm DP15 addon; CLI; docs.

**Not started (blocked on artifacts from the user):**
1. APK of "Concept Home" (`com.concept.www`) -> app key/secret + real DP names.
2. Concept account credentials (in `.env` on the PC, never in git).
3. Robot's LAN IP.
4. Real captures -> confirm/extend the protocol, capture per-room `b1`/`b2`.
5. Local connection on :6668 with the local key, then replaying commands.
6. Map header RE + own floor-plan renderer.

## Next steps (do these in order)

```bash
# 1. APK analysis (PC)
python tools/apk_scan.py concept-home.apk --secrets-out data/app_secrets.json

# 2. Cloud dump (PC, needs .env)
export TUYA_USER=... TUYA_PASS=... TUYA_REGION=eu
python tools/cloud_dump.py --out data/ --download-maps

# 3. Update src/popelka/dp.py with the robot's REAL schema -> commit
# 4. Local transport: get local_key from data/devices.json, then
#    LocalDevice(ip, local_key, device_id).status() / .execute_plan(plan)
# 5. MITM capture for exact LDROBOT command sequences (phone -> PC proxy)
python tools/decode_payloads.py capture.txt
# 6. Map RE: popelka map data/maps/*.bin --out map.pgm
```

## Conventions

* Python 3.13, `uv`, src layout, pytest. Keep `uv run pytest -q` green.
* Every reverse-engineered fact goes into `docs/RE.md` **with its provenance**
  (captured here vs. inherited from upstream work) and into `src/popelka/dp.py` if it is a
  datapoint.
* Never commit credentials, APKs, captures or map dumps. `.env`, `data/`, `private/`,
  `vault/`, `captures/`, `*.apk`, `*.bin` are gitignored **and** blocked by the pre-commit
  hook (`scripts/install_hooks.sh` once per machine). Move such artifacts between machines
  with `scripts/vault.sh` (encrypted, LAN transfer only).
* Mask credentials in any output you show the user (the local key is masked in
  `tools/cloud_dump.py` stdout; keep it that way).
* Hardware safety: the robot moves and mops for real. Verify coordinate scaling against a
  known landmark before sending zone/spot commands, and keep the physical remote within
  reach. Test water-level commands with the tank removed first.
* Push to `main` after each meaningful step; the user wants the work visible on GitHub.
* Append a short entry to `docs/JOURNAL.md` after each meaningful step - it is how the
  next session (on any machine) knows where things stand.
* User writes in English; the app UI is Czech. Keep docs in English.
