# Voice packs: making the robot speak R2-D2

The goal: replace the robot's spoken prompts with droid chirps. **No firmware
patching and no disassembly** - the Tuya platform has a voice-pack channel where
the robot downloads a ZIP, verifies its MD5 and installs it.

Provenance warning, same as everywhere else in this repo: the *mechanism* is
documented by Tuya and proven on a sibling device, but **nothing about it has
been observed on the VR3125 yet**. Four details are unknown and listed below
with the experiment that resolves each.

## TL;DR

```bash
make droid                                  # hear the kind of chirps we can make
make cloud-dump                             # does the device spec have voice_data?
make sniff ROBOT=192.168.1.50               # change the voice in the app while this runs
make decode-pcap PCAP=captures/robot.pcap KEY=<local_key>   # id + md5 + official URL
# download that URL, inspect the ZIP, rebuild it with droid sounds, serve it, push it
make voice DIR=pack ID=502 URL=http://192.168.1.10/pack.zip
make replay ARGS="voice --pack-id 502 --md5 <md5> --url http://192.168.1.10/pack.zip"
```

## Why the app on your phone does not contain the sounds

Verified on this phone (Termux, uid `u0_a411`):

* `/data/app` cannot be listed, and `pm list packages` is filtered by Android's
  package-visibility rules, so the Concept Home package is invisible to Termux.
* `/sdcard/Android/data` is unreadable (`Permission denied`).
* The APK itself **is** readable *if* you know the exact path (`base.apk` is
  mode 0644), but you need `adb shell pm path com.concept.www` on a PC to learn it.

More importantly: the app is a generic Tuya client. The voice clips live in the
robot's flash, not in the APK. The app only sends "download pack *N* from *this
URL*". Pulling the APK is still useful for the app key/secret and API hosts, but
it will not give you the robot's audio.

## What is known (and where it comes from)

| Fact | Source | Confidence |
|---|---|---|
| DP code `voice_data` carries voice-pack installs | Tuya *Laser Robot Vacuum Template* docs | high |
| Commands `0x34` (app → robot) and `0x35` (progress) | same docs + `@ray-js/robot-protocol` | high |
| Exact byte layout of 0x34 | read from `@ray-js/robot-protocol@1.0.6`, `dist/index.mjs` | high (source code) |
| Robot downloads a ZIP, verifies MD5 | same code + the Eufy L50 write-up | high |
| DP id **162** | Eufy L50's Tuya build uses 162 for the same job | **hypothesis for VR3125** |
| ZIP internal layout / audio format | firmware-specific; unknown for LDROBOT | **unknown** |
| Accepted pack ids | firmware-specific; unknown | **unknown** |
| VR3125 implements 0x34 at all | not tested | **unknown** |

The Eufy L50 is a useful sibling but not a blueprint: it encodes the same idea as
a **base64 protobuf in DP162** (id, url, md5, version, size), while the Tuya
standard - and therefore probably this robot - uses the `0x34` frame below. A
capture tells us which one the VR3125 speaks.

## The 0x34 frame, byte by byte

Voice frames are the `AB` family, a sibling of the AA frames in `popelka.aa`
(same checksum idea, different length field):

```
AB 00 | len:u32be | cmd:u8 | data | checksum:u8
len      = 1 + len(data)          # cmd + data; the checksum is NOT counted
checksum = sum(cmd + data) & 0xFF
```

`data` for cmd `0x34`:

| Field | Size | Encoding |
|---|---|---|
| pack id | 4 | big-endian u32 (the "language id" the firmware knows) |
| md5 length | 1 | u8 (32 for a hex MD5) |
| md5 | N | **ASCII hex string**, not the 16 raw bytes |
| url length | 4 | big-endian u32 |
| url | M | UTF-8 |

Worked example (`pack_id=502`, `md5="0"*32`, `url="http://x/y"`):

```
ab00 00000034 34 000001f6 20 3030…30 0000000a 687474703a2f2f782f79 cd
^    ^        ^  ^        ^  ^        ^        ^                    ^
AB00 len=52  34 id=502   md5len  md5      urllen  http://x/y         sum
```

The `0x35` report is `pack_id:u32be status:u8 progress:u8`. Status labels are
unverified; keep the number.

## What the robot does with it

1. validates the checksum and the MD5 format;
2. HTTP GETs the URL **itself** (the Eufy sibling only accepted port 80, not
   non-standard ports - unverified here);
3. verifies the ZIP's MD5, unzips it, installs the clips;
4. reports progress on 0x35;
5. plays the new prompts on the next event (or after a reboot).

This is why the pack must be on a host the robot can reach - your PC, not the
phone, unless the phone runs a server.

## Resolve the unknowns, in this order

### 1. Does the firmware support it? (no robot traffic needed)

```bash
make cloud-dump
jq '."162", (to_entries[] | select(.value|test("voice";"i")))' data/specs.json
```

`data/specs.json` is the device's real DP schema. If a `voice_data` DP exists,
the firmware implements the feature; its **id** is right there. If there is no
voice DP at all, the feature is not implemented and the only remaining route is
firmware-level (out of scope, and risky).

### 2. Which encoding? (one capture)

```bash
make sniff ROBOT=<robot-ip>
# in the app: Settings -> Voice / Language -> pick another voice
make decode-pcap PCAP=captures/robot.pcap KEY=<local_key>
```

Look for either:

```
DP162:
  AB cmd=0x34 len=69 data=00 00 01 f6 20 …
     voice install: id=502 md5=<32 hex> url=http://…
```

or a base64 protobuf (Eufy style) that does not decode into an AB frame. The
first means Tuya standard; the second means we port the Eufy encoder instead.

The capture also gives the **official pack URL** - the most valuable artifact,
because it is a working, firmware-accepted ZIP.

### 3. What is inside a pack? (download it)

```bash
curl -O <official-url>
unzip -l pack.zip
unzip -p pack.zip '*/config.*'
ffprobe -hide_banner <extracted-clip>
```

Record in `docs/RE.md`: top-level folder name, config file name/format, file
names and count, codec/sample-rate/bitrate. *That* is the spec we must match -
Eufy's numbers (16 kHz mono 16 kbps MP3, `A####.mp3`, `config.yaml` with
`id`/`version`) are a hint, not a promise.

### 4. Which pack ids are accepted?

Use an id from the official capture. The Eufy firmware silently fails on
made-up ids (state=3); assume the same until proven otherwise.

## Build and push the droid pack

1. Mirror the official ZIP layout exactly, filenames included.
2. Generate one chirp per speech clip, keeping chimes where they exist:

   ```bash
   python tools/droid_voice.py --names power_on,start_clean,going_home \
       --out-dir pack/main --mp3
   ```

   `--names` seeds the synthesiser with a hash of the name, so re-running
   produces identical bytes - important because the robot checks the MD5.

3. Bump the version inside the config (if the layout has one). Same or lower
   version = the robot ignores the install.
4. Build and announce:

   ```bash
   make voice DIR=pack ID=502 URL=http://192.168.1.10/pack.zip
   ```

5. Serve it on port 80 (the robot must reach this host):

   ```bash
   cd pack && sudo python3 -m http.server 80
   ```

6. Push, watching the 0x35 reports:

   ```bash
   make replay ARGS="voice --pack-id 502 --md5 <md5> --url http://192.168.1.10/pack.zip"
   ```

## The R2-D2 part

`popelka.droid` synthesises **new** astromech-style whistles (frequency sweeps,
vibrato, a little noise). It does not sample Star Wars audio, so there is no
copyrighted material in the pack or in this repo.

```bash
uv run popelka droid --out droid.wav --seed 7     # single sample
python tools/droid_voice.py --names a,b,c --out-dir sounds --mp3
```

Speech prompts become chirps; chimes (start/stop/error) become the most
characterful chirps. If a prompt is "low battery, returning to charge", an
urgent descending whistle fits; if it is "cleaning complete", a satisfied rising
one. Once the official file list is known, mapping is just a name list.

## Safety and rollback

* Keep the official pack ZIP and its original URL/MD5. Rollback = select the
  official voice in the app, or push the original URL/MD5 back.
* Do not cut power during an install; the voice partition is separate from the
  motor/LiDAR firmware, so a failed install should not stop the robot cleaning,
  but there is no guarantee until we see the partition scheme.
* Use `--dry-run` on the replay command to inspect the DP value first.
* Confirm the DP id before writing: a raw write to the wrong raw DP sends
  arbitrary bytes to another subsystem. `make cloud-dump` is the authority.

## Cheat sheet

| Command | Purpose |
|---|---|
| `uv run popelka voice build --id 502 --md5 <md5> --url <url>` | print the DP value + decode it |
| `uv run popelka voice decode <hex>` | decode a captured 0x34/0x35 payload |
| `uv run python -m popelka.replay voice ... --dry-run` | same, through the replay path |
| `make voice DIR=... ID=... URL=...` | deterministic ZIP + MD5 + frame |
| `make droid OUT=... SEED=...` | one chirp WAV |
| `make sniff` / `make decode-pcap` | capture and decode the app's voice change |
