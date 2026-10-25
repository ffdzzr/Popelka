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

## 2026-10-22 - session 4 (Termux) - capture the ground truth

* Added `tools/pcap_dp15.py`: parses tcpdump pcaps, splits Tuya local-protocol
  frames on TCP 6668, AES-decrypts protocol 3.3 payloads with the local key, and
  decodes the AA frames inside. Protocol 3.4 is detected but not decrypted yet.
  Tested with synthetic pcaps (17 tests pass).
* Added `docs/CAPTURE.md`: the three interception points (app<->cloud,
  phone<->robot TCP 6668, robot<->cloud) with pros/cons, the "block the robot's
  internet and see if the app still works" LAN-mode test, capture procedure
  (manual drive first), safety rules, and the capture -> document -> encode -> test
  -> replay loop.
* Added `make sniff` / `make decode-pcap`; `popelka/__init__.py` now imports
  lz4-dependent modules lazily so the capture tools run in a minimal environment.
* Provenance note restated: nothing has been measured on the VR3125 yet; every
  protocol value is inherited (docs/RE.md).

## 2026-10-25 - session 5 (Termux) - voice packs: the R2-D2 route

* Goal from the user: replace the robot's prompts with R2-D2-like sounds, starting
  from the Concept Home app on this phone.
* Phone recon: Termux (uid `u0_a411`) cannot list `/data/app` or `/sdcard/Android/data`,
  and Android 11 package-visibility filtering hides the Concept package from
  `pm list packages`. A known APK path *is* readable (base.apk is 0644), so
  `adb shell pm path com.concept.www` + `adb pull` on the PC remains the way in.
  More importantly: the voice clips live in the robot, not the APK.
* Found the real mechanism: Tuya's `voice_data` DP with `encodeVoice0x34` /
  `decodeVoice0x35`. Read the frame layout from `@ray-js/robot-protocol@1.0.6`
  (AB-extended frame; pack id + ASCII MD5 + URL). The robot downloads a ZIP,
  verifies the MD5 and installs it - no firmware patching.
* Added `popelka.voice` (encode/decode 0x34/0x35, resyncing scanner), `popelka.droid`
  (original astromech chirps: sweeps + vibrato + noise, stdlib only, deterministic
  seeds), `popelka voice build|decode`, `popelka droid`, `replay voice` (with
  `--dry-run`), `tools/voice_pack.py` (deterministic ZIP -> MD5 + DP value) and
  `tools/droid_voice.py` (one chirp per prompt name, optional ffmpeg MP3).
* `tools/pcap_dp15.py` now parses the DP JSON and base64-decodes raw DP values
  before decoding AA *and* AB frames - without that it would never see a voice
  install in a real capture.
* Added `docs/VOICE.md` (byte table, worked example, the four unknowns, the
  capture experiment, build/push/rollback) and `DP_VOICE_DATA = 162` as an explicit
  hypothesis. 30 tests pass.
* Unverified: the DP id, whether the firmware implements 0x34, accepted pack ids,
  and the ZIP layout/audio format. Next: `make cloud-dump` for the real spec, then
  one captured voice change for the official pack URL.
