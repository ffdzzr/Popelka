# Capturing the truth from the app

The repo currently encodes **hypotheses** inherited from public RE work on the same
Tuya vacuum family (`docs/RE.md` has the provenance table). This document is how to
replace them with measurements from *your* VR3125.

There are three wires. They are not equivalent.

```
  phone app  ──(1) HTTPS──►  Tuya cloud  ──(3) MQTT/HTTPS──►  robot
      │                                                          ▲
      └──────────(2) TCP 6668, LAN, AES with local key───────────┘
```

| # | Wire | What you learn | Difficulty | Verdict |
|---|---|---|---|---|
| 1 | app ↔ cloud | command payloads, device list, local key, DP schema | needs TLS MITM (re-signed APK) | useful, but noisy |
| 2 | **phone ↔ robot, TCP 6668** | the exact binary frames, unencrypted after one AES layer | easy: same LAN + local key | **start here** |
| 3 | robot ↔ cloud | live path/P2P data | TLS, keys in firmware | out of scope (software-only) |

Wire 2 is the winner: it is the same `command_trans` frames that travel through the
cloud, with one AES layer that the local key unwraps. No TLS, no certificate pinning.

## Step 0 - does the app even use the LAN?

Cheap, decisive experiment, do it first:

1. Log into your router and **block the robot's internet access** (or pull the WAN
   cable for a minute). Keep the LAN up.
2. Open the app and press "start".
3. Does the robot move?

* **Yes** → the app uses local control; wire 2 will be full of good stuff.
* **No, it errors** → the app is cloud-only; go to wire 1 (MITM), or accept polling
  the cloud instead.

While you are there, note the robot's **IP** (DHCP list) - you need it for everything
that follows.

## Step 1 - get the local key

You cannot read wire 2 without it. Two routes, try them in order:

```bash
cp .env.example .env      # fill in TUYA_USER / TUYA_PASS / TUYA_REGION=eu
make cloud-dump           # prints masked keys, writes data/devices.json (gitignored)
```

`data/devices.json` contains `local_key` and `ip`. If the plain login is refused,
`make scan APK=...` gives you the app key/secret and `cloud.py` retries with the
signed v2.0 flow.

If the key never shows up in the cloud response, wire 1 (or the app's own pairing
handshake) is the fallback.

## Step 2 - capture wire 2

Two ways. The PC-as-hotspot one is clean and needs no ARP tricks.

### Option A - phone on the PC's hotspot (recommended)

The PC becomes the phone's gateway, so every phone→robot packet is visible.

```bash
# on the PC, create a hotspot (GNOME: Settings -> Wi-Fi -> Hotspot; or hostapd)
# connect the phone to it, then:
sudo tcpdump -i any -w captures/robot.pcap "host <robot-ip> and port 6668"
make decode-pcap PCAP=captures/robot.pcap KEY=<local_key>
```

The phone and robot must still be able to reach each other: enable IP forwarding +
NAT on the PC (`net.ipv4.ip_forward=1`, `iptables -t nat -A POSTROUTING -o <uplink> -j MASQUERADE`)
if the hotspot is a different subnet.

### Option B - ARP spoofing on the flat LAN (faster to set up)

```bash
sudo bettercap -iface wlan0
# in bettercap:
#   set arp.spoof.targets <phone-ip>
#   arp.spoof on
#   net.sniff on
```

This puts the PC in the middle of phone↔robot. Be aware: it will disrupt the phone's
traffic if misconfigured, and it is a MITM on your own LAN only - do not point it at
anything you do not own.

### What to do while capturing

Do it in one session, narrating out loud (or in the journal) what you press:

1. open the app, let the map load
2. **manual drive** - forward, back, turn left, turn right, stop
   ← this is the gold: simple, high-frequency frames, and the effect is obvious
3. spot clean
4. room clean, two rooms in a specific order
5. zone clean (draw a rectangle)
6. pause, resume
7. stop, return to dock
8. trigger a fault on purpose (lift the robot) and recover

Label the timestamps in the journal; that is how you map "the frame at 14:32:07"
to "turn left".

### Safety while testing movement

* The robot must be on the **floor**, in a room with the door closed - not on a
  table (cliff sensors will fire a fault and you will learn nothing).
* Clear cables, socks and pets.
* Keep the physical remote in your hand the first time you replay anything.
* Manual-drive frames are the safest thing to replay: they are momentary, and a
  wrong direction just bumps into furniture.

## Step 3 - decode

```bash
make decode-pcap PCAP=captures/robot.pcap KEY=<local_key>
# or directly:
python tools/pcap_dp15.py captures/robot.pcap --key <local_key>
```

Output looks like:

```
=== 192.168.1.10:45678 -> 192.168.1.50:6668  (43 bytes, 1 tuya frames)
    tuya cmd=0x08 (CONTROL_NEW) seq=1 payload=19B
      payload (aes-3.3):
        wake           cmd=0x4d payload=01 3b 9a ca 03
        room_order     cmd=0x27 payload=01 02 00 04
```

Anything that decodes into **checksum-valid AA frames** is real. Our parser validates
the checksum, so random bytes will not fake a hit.

If you see `(encrypted/unknown layout)` on every frame, the robot uses Tuya protocol
**3.4** (session-key handshake) and `--key` alone is not enough - capture the
handshake frames (`cmd 0x03/0x05/0x06`) too and note it in the journal; that is the
next thing to implement.

## Step 4 - turn captures into code

For every new frame:

1. add it to `docs/RE.md` under a "captured on VR3125" heading with the timestamp,
   the app action and the raw bytes;
2. add a builder in `src/popelka/commands.py` if it is a command;
3. add a test with the raw bytes as a fixture, so a refactor cannot silently change
   the protocol;
4. replay it with `make replay ARGS="raw <hex>"` and confirm the same behaviour.

That loop - capture, document, encode, test, replay - is the whole project.

## Wire 1 (only if you need it)

* `make resign APK=concept-home.apk OUT=concept-home-mitm.apk`
* `adb install -r concept-home-mitm.apk`
* `make capture`, set the phone's Wi-Fi proxy to `<pc-ip>:8080`, install the mitm CA
  (Settings → Security → Install certificate → CA certificate).
* Note: the Tuya app SDK sometimes wraps request bodies in its own AES layer; if the
  JSON looks opaque, the `command_trans` value may still be visible as a base64 field,
  and `tools/mitm_dp15.py` will decode it.

Remember: the re-signed APK replaces the Play version and stops receiving updates.
Keep a copy of the original APK (`com.concept.www` from `adb pull`) so you can go back.
