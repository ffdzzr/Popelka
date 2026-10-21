# Roadmap

Ordered by "value per hour of work". Everything is software-only.

## Phase 0 - Recon (30 min)

* [ ] Confirm which app you actually use (`Concept Robot` vs `Concept Home`) and
      which Tuya region it talks to (check the app's traffic / the account
      country).
* [ ] Note the robot's LAN IP (router DHCP lease, or `arp -a` / `nmap`).
* [ ] `nmap -sV -p 6668,80,443,8888 <robot-ip>` - is the local Tuya socket open?
* [ ] Pull the APK and look for the Tuya app key/secret and API hosts:
      `jadx` on the APK, grep for `appKey`, `appSecret`, `openapi`, `aistudio`.

## Phase 1 - Cloud API access (1-2 h)

* [ ] Log in to the Tuya IoT API with your Concept account
      (`POST /v1.0/token?grant_type=1`, username + password hashed per Tuya
      rules) and list devices (`GET /v2.0/iot/users/{uid}/devices`).
* [ ] Fetch the full DP list and schema for the robot:
      `GET /v2.0/iot/users/-/devices/{did}/status` and the device spec.
* [ ] Record: which DP ids exist, their types, and the mode/status enums the
      robot actually reports. Update `popelka/dp.py` with the real schema -
      this is the first genuine finding for *your* robot.
* [ ] Try to pull the **local key** from the device detail response (older Tuya
      flows include it). With it you get LAN-only control.

## Phase 2 - Capture the real binary protocol (2-4 h)

* [ ] Set up `mitmproxy` and capture the app's HTTPS traffic while you run a
      cleaning job from the app. Look for `command_trans` / DP15 writes.
* [ ] If the app pins certificates: re-sign the APK with a debug CA
      (apktool + `uber-apk-signer`), or use `frida` to hook the OkHttp
      trust manager. `tools/mitm_dp15.py` prints and decodes DP15 payloads
      automatically.
* [ ] Alternatively, capture the **local** socket: point the app at a
      transparent TCP proxy (`mitmproxy --mode transparent` or a `socat`
      forwarder) sitting between phone and robot:6668.
* [ ] Dump every captured DP15 payload through `tools/decode_payloads.py`
      and compare with `docs/RE.md`. Note any frames that do not match the
      Philips-derived reference (LDROBOT may add its own opcodes).

## Phase 3 - Talk to the robot yourself (2 h)

* [ ] Build a `LocalDevice` (`popelka.tuya`) with the local key and read
      `battery`, `status`, `mode`.
* [ ] Replay a captured DP15 bundle verbatim -> the robot should react
      identically to the app. This is the "I control the thing" milestone.
* [ ] Capture the per-room `b1`/`b2` bytes: clean one room from the app and
      read the device->app `0x53` status frame (same layout as `0x51`).
      Store them per room id.
* [ ] Write your own room cleaner with **named** rooms (`kitchen`, `bathroom`),
      using your captured room table.

## Phase 4 - Maps (4-8 h)

* [ ] List and download a map file from the cloud; run `popelka map`.
* [ ] Reverse the 24 byte header: figure out which fields are width, height,
      compressed length, and what the rest are.
* [ ] Render the grid, overlay room ids, and match the app's map to calibrate
      orientation (mirrored? rotated? origin at dock?).
* [ ] Decode the room-name section (UTF-8? UTF-16? length-prefixed?).
* [ ] Store maps in a git-friendly format (PNG + JSON) and diff them between
      runs - you get floor-plan change detection for free.

## Phase 5 - Local control without the app (2-4 h)

* [ ] Implement the local DP15 write path end-to-end: zone clean by
      coordinates, spot clean, fault recovery, pause/resume.
* [ ] Wrap it in a small CLI: `popelka clean --room kitchen`, `popelka zone
      --from 1.0,1.5 --to 2.0,2.0`.
* [ ] Optional: Home Assistant integration (custom component, or reuse
      `make-all/tuya-local` + your own extra commands).

## Phase 6 - The fun stuff (open ended)

* [ ] **P2P reverse engineering**: the live cleaning path never appears on the
      local socket - it goes over Tuya's P2P (UDP, session key from the cloud).
      Capture the UDP flow, find the session key exchange, decode the path
      packets. This is the hardest and most satisfying target.
* [ ] **Path planning**: reconstruct the robot's route from the path data and
      compute coverage %, then compare with its own "area cleaned" number.
* [ ] **Telemetry logger**: log every DP change to SQLite/InfluxDB, then
      Grafana dashboards (battery vs time, area per run, faults per week).
* [ ] **Behaviour scripting**: "when the kitchen floor gets dirty, clean just
      the kitchen twice" - webhooks from a door sensor or a lightbulb.
* [ ] **Coordinate calibration**: figure out exactly how the app's pixel
      coordinates map to robot units, so you can script "clean under the sofa".
* [ ] **Anti-stuck watchdog**: a script that detects repeated `fault` DP
      transitions and sends the `0x4C` recovery frame automatically.
* [ ] **Security review**: what does the device accept from the network? Can
      anyone on your LAN command it? Does the cloud app allow remote command
      without a session check? (Test only on your own device.)
