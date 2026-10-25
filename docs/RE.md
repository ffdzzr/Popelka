# Reverse-engineering notes: Concept VR3125

## 1. What the device is

| Property | Value |
|---|---|
| Model | Concept VR3125 2v1 Perfect Clean Laser (3300 Pa, LiDAR nav, mop) |
| OEM | LDROBOT (Shenzhen LD Technology), product line `TYW2` |
| Apps | `com.ldrobot.tyw2concept` ("Concept Robot"), `com.concept.www` ("Concept Home") |
| Platform | Tuya Smart Life SDK / Tuya IoT cloud |
| Local protocol | Tuya local protocol, TCP **6668** |
| Cloud | Tuya IoT API (region `eu`) + Tuya Sweeper API for maps + Tuya P2P for live path |
| Next gen models | VR34xx/VR40xx use the same Tuya stack, so findings should transfer |

Useful upstream references:

* Tuya developer docs - *Robot Vacuum (laser navigation)* protocol and the
  `command_trans` / DP15 command scheme
  <https://developer.tuya.com/en/miniapp/solution-ai/ability/sweeper-solution/robot-vacuum-laser/ability-set/protocol.md>
* `Tkd-Alex/tuya-vacuum-local` - reverse-engineered notes for the Philips
  HomeRun XU3100 (same Tuya laser-vacuum solution family) plus a
  `vacuum_listener.py` that sniffs local traffic:
  <https://github.com/Tkd-Alex/tuya-vacuum-local>
* `make-all/tuya-local` - Home Assistant integration for Tuya vacuums
* Valetudo - the same idea for the Xiaomi/Roborock ecosystem (not applicable
  here, but good reference for what "full local control" looks like)

## 2. Datapoints

See `popelka/dp.py` for the full table. The important ones:

| DP | Meaning |
|---|---|
| 1 `power_go` | start/stop trigger |
| 2 `pause` | pause |
| 3 `switch_charge` | return to dock |
| 4 `mode` | `smart` / `zone` / `pose` / `part` / `chargego` |
| 5 `status` | `standby`, `cleaning`, `paused`, `charging`, `selectroom`, `zone_clean`, `goto_pos`, `repositing`, `fault`, `emptying` |
| 8 `battery` | percent |
| 9 / 10 | global suction / water level |
| 14 `path_data` | map/path - **P2P only**, never seen on the local socket |
| 15 `command_trans` | **raw binary protocol channel** |
| 28 `fault` | 0 ok, 0x80 generic, 0x4000000 stuck/lidar blocked |
| 29/30/31 | cumulative area / count / minutes |

## 3. The AA frame protocol (DP15)

```
AA  len_hi  len_lo  cmd  payload...  checksum
```

* `len` = big-endian count of bytes after it (cmd + payload), checksum excluded.
* `checksum` = `sum(cmd + payload) & 0xFF`.
* The app sends **bundles**: several frames concatenated into one DP15 write.

Verified against captured app traffic:

```
wake           AA 00 06 4D 01 3B 9A CA 03 F0
sync bundle    AA 00 02 57 01 58 | AA 00 03 55 01 00 56 | AA 00 03 39 01 00 3A
               AA 00 03 13 01 00 14 | AA 00 03 53 01 00 54
room config    AA 00 17 51 01 02 00 05 00 00 00 01 FF FF 01 00
                            04 05 00 00 00 02 03 02 01 00 6A
room order     AA 00 05 27 01 02 00 04 2E
fault recovery AA 00 01 4C 4C
```

### Room block (cmd 0x51)

10 bytes per room:

```
room_id | 0x05 | 0x00 | b1 | b2 | passes | suction | water | 0x01 | 0x00
```

* `suction`: 1 gentle, 2 normal, 3 strong, 4 strong_plus, `0xFF` = inherit DP9
* `water`: 0 off, 1 low, 2 middle, 3 high, `0xFF` = inherit DP10
* `b1`/`b2`: device-specific bytes stored per room in the robot's memory.
  **They must be captured from your own robot** - do not copy them from
  another device.

### Coordinates (zones / spot)

* Origin at the dock, **200 units = 1 m** (1 unit = 5 mm), signed int16 BE.
* Verified on the Philips unit across 5 measurements (<1.5% deviation).

### Command sequence for a room clean

```
DP15 <- wake (0x4D)
DP15 <- sync bundle
DP15 <- room config (0x51)
DP15 <- room order  (0x27)
DP1  <- True
DP4  <- "selectroom"
```

## 4. Maps

The robot uploads maps over the P2P channel and they are fetched from the
cloud:

| Endpoint | Purpose |
|---|---|
| `GET /v1.0/users/sweepers/file/{did}/realtime-map` | live map URLs (1 h TTL) |
| `GET /v1.0/users/sweepers/file/{did}/list?file_type=pic` | stored map files |
| `GET /v1.0/users/sweepers/file/{did}/download?id={file_id}` | download a map |

File format: 24 byte header (12 x uint16 BE) + LZ4 block-compressed payload.
Decompressed: first `width*height` bytes are the grid, the rest is the
room-name section. Grid cell values:

```
0xF4 free   0xF9 wall   0xFF background   0x04*room_id = room
```

The header layout is not public, so `popelka.maps` infers it heuristically and
reports every inference - **verify against the app's own map** before
trusting it.

## 5. Voice pack channel (`voice_data`, 0x34 / 0x35)

*Provenance: Tuya developer docs + the published `@ray-js/robot-protocol@1.0.6`
source (`dist/index.mjs`). **Not captured on this robot yet.***

Tuya vacuums can download a voice pack: the app sends pack id + MD5 + URL, the
robot fetches the ZIP itself, verifies the MD5 and installs it. No firmware
patching involved. The frame is the *extended* (AB) family, a sibling of the AA
frames above:

```
AB 00 | len:u32be | cmd:u8 | data | checksum:u8
len = 1 + len(data)                 checksum = sum(cmd + data) & 0xFF
```

`cmd = 0x34` (app -> robot), data:

```
pack_id:u32be | len(md5):u8 | md5:ascii(32) | len(url):u32be | url:utf8
```

`cmd = 0x35` (robot -> app): `pack_id:u32be | status:u8 | progress:u8`.

Unknowns on the VR3125: the DP id (the Eufy L50 uses 162 - a hypothesis here),
whether the firmware implements 0x34 at all, accepted pack ids, and the ZIP
layout/audio format. `docs/VOICE.md` has the experiment that resolves all four.
The sibling Eufy L50 (also Tuya) uses the same idea with a base64-protobuf
payload in DP162 instead, so the capture decides which encoding to implement.

## 6. Open questions for *this* robot

1. Are the `b1`/`b2` room bytes present on the VR3125, and what do they mean?
2. Does the VR3125 use `mode=part` (room) as well, and are room IDs 0..N?
3. Does the LDROBOT build use the same DP numbering as the Philips unit, or
   its own schema? (Read the DP list from the cloud: `GET /v2.0/iot/users/-/devices/{did}/status`.)
4. Does the VR3125 answer on TCP 6668, and is the local key obtainable from
   the cloud API?
5. What is the DP14 `path_data` payload, and is there a *local* (non-P2P)
   way to get the live path?
6. Are the map files really LZ4 block with the same header on LDROBOT?
7. Does the device spec expose `voice_data`, under which DP id, and does a
   voice change in the app produce an AB `0x34` frame (Tuya) or a base64
   protobuf (Eufy style)?

## 7. Legal / safety

* Keep your own firmware intact - all of this is read/write access over the
  documented device interface, no disassembly, no firmware patching.
* The robot moves and mops. Test zone/spot commands **only after** you have
  verified the coordinate system against a known landmark in the app's map,
  and keep the physical remote control within reach.
* Vacuum motors and LiDAR are cheap; water pumps are not. Test water-level
  commands with the dock's water tank removed first.
