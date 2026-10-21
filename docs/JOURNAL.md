# Working journal

Append-only log of what was actually done, in order, so that any new session
(phone or PC) can read the tail and know where the work stands. One short
entry per meaningful step. Newest at the bottom.

## 2026-10-21 - session 1 (Termux)

* Research: identified the VR3125 as an LDROBOT `TYW2` machine on the Tuya
  platform. Apps: `com.concept.www` ("Concept Home", the one in use) and
  `com.ldrobot.tyw2concept` ("Concept Robot").
* Built the toolkit from scratch: AA frame codec, DP catalogue, room/zone/spot
  command builders, LZ4 map decoder, Tuya cloud client, APK scanner, cloud
  dumper, mitmproxy DP15 addon, CLI. 14 tests.
* Wrote `AGENTS.md` + `docs/HANDOFF.md` so a fresh session on the PC can
  continue without re-deriving the context.
* Added the cross-machine workflow: `scripts/resign_apk.sh`,
  `scripts/capture.sh`, `scripts/vault.sh` (encrypted transfer),
  `scripts/check_secrets.sh` + `scripts/install_hooks.sh` (leak guard),
  `Makefile`, `popelka.replay` (send real commands to the robot).

### Open items waiting on the user

* Concept Home APK (`com.concept.www`)
* Concept account credentials in `.env`
* Robot LAN IP
* Permission to re-sign the app with a mitm CA

### Next actions

1. `make scan APK=concept-home.apk`
2. `make cloud-dump` -> updates `src/popelka/dp.py` with the real schema
3. `make replay ARGS="status"` from either machine

## 2026-10-21 - session 2 (Termux) - seamless phone <-> PC workflow

* Added `Makefile` (one command per step), `scripts/capture.sh`,
  `scripts/resign_apk.sh` (Android 7+ user-CA workaround), `scripts/vault.sh`
  (encrypted pack/unpack for moving secrets over the LAN),
  `scripts/check_secrets.sh` + `scripts/secret_patterns.txt` (leak guard) and
  `scripts/install_hooks.sh` (install it as a git pre-commit hook).
* Added `src/popelka/replay.py`: send real commands to the robot from any machine
  (`status`, `room`, `zone`, `spot`, `fault`, `raw`).
* Added `docs/WORKFLOW.md` (machine roles, the loop, hygiene rules) and
  `docs/JOURNAL.md` (this log). Updated `AGENTS.md` and `docs/HANDOFF.md`.
* Verified locally: the leak guard blocks a staged fake local key and allows a
  clean commit; the vault round-trips (openssl AES-256) and the archive is
  ciphertext; `cloud_dump.py` now masks the local key in stdout.
* The pre-commit hook is installed on this machine; run
  `bash scripts/install_hooks.sh` on the PC as well.

### Still waiting on the user

APK, `.env` credentials, robot IP, OK to re-sign the app.

## 2026-10-21 - session 3 (Termux) - make a session start verifiable

* Added `scripts/doctor.sh` + `make doctor` / `make start`: prints toolchain status,
  repo cleanliness, unpushed commits, test result, which credentials/artifacts exist
  (masked), robot reachability (ping + TCP 6668), and the **next command to run**.
* `AGENTS.md` now opens with a SESSION START checklist (make start -> read HANDOFF +
  journal tail -> check git status), so a new session on any machine starts from
  verified state instead of guessing.
