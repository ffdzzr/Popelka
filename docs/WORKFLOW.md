# Workflow: phone <-> PC <-> Termux

You will move between machines a lot. This is how to do it without losing
context and without leaking anything sensitive.

## Roles

| Machine | Runs | Holds secrets? |
|---|---|---|
| **Linux PC** | jadx/apktool, mitmproxy, Wireshark, the heavy analysis | yes: `.env`, re-signed APKs, captures, map dumps |
| **Android phone** | the Concept Home app, and nothing else | no - it only talks to the PC proxy or the robot |
| **Termux** | always-on client on the LAN, the robot control CLI, git | yes: `.env` if you set it up |

## The loop

```
        (a) APK pulled from phone          (b) captures flow phone -> PC proxy
phone  ───────────────────────────►  PC  ◄──────────────────────────────►  robot
                                        │                                      ▲
                                        │ (c) local control on TCP 6668        │
                                        ▼                                      │
                                     Termux ────────────────────────────────────┘
```

1. **Phone -> PC**: pull the APK with `adb`, or export it with an APK extractor
   app, or download it from APKMirror on the PC.
2. **PC**: `make scan APK=...` then `make cloud-dump` (needs `.env`).
3. **PC**: `make capture` -> phone Wi-Fi proxy -> `<pc-ip>:8080`, install the
   mitm CA, drive a cleaning job.
4. **PC -> robot**: `make replay ARGS="status"` (works from Termux too, if the
   LAN allows it).
5. **Termux**: stays available as a fallback client for the robot, and is where
   git lives if the PC is not handy.

## Switching machines mid-task

* **Context**: `AGENTS.md` is auto-loaded by OpenCode in the repo. `docs/HANDOFF.md`
  holds the narrative, `docs/JOURNAL.md` is the append-only log of what was done.
  Read the tail of the journal first.
* **Code**: `git pull` on the other machine. Commit and push after every
  meaningful step (`make push MESSAGE="..."`).
* **Sensitive stuff**: never in git. Use the vault.

## Moving sensitive artifacts without leaking them

`.env`, `data/` (device list, local key, map dumps), `private/` (re-signing
workspace, keystores) and `captures/` are gitignored **and** refused by the
pre-commit hook.

To move them between machines:

```bash
bash scripts/vault.sh pack          # -> vault/popelka-<stamp>.tar.gz.enc (encrypted)
scp vault/popelka-*.enc <other-host>:~/vault/     # over the LAN, not via the cloud
bash scripts/vault.sh unpack vault/popelka-<stamp>.tar.gz.enc
```

The archive is encrypted (age if installed, otherwise openssl AES-256 with
PBKDF2), so even if it ends up in the wrong place it is inert without the
passphrase. The passphrase is entered interactively, so it never lands in a
shell history or a file.

**Rule of thumb**: code and findings go to GitHub; credentials, keys, captures,
APKs and map dumps travel over the LAN in the encrypted vault.

## Leak guard

```bash
bash scripts/install_hooks.sh     # once per machine
bash scripts/check_secrets.sh     # runs automatically before every commit
bash scripts/check_secrets.sh --all   # full worktree audit
```

The guard blocks staged paths that look like credentials or captures
(`*.apk`, `*.keystore`, `*.pem`, `.env`, `data/`, `private/`, `captures/`,
`*.bin`) and credential-shaped content (local keys, `TUYA_PASS`, bearer
tokens, password fields).

If it fires on a false positive, fix the pattern in `scripts/check_secrets.sh`
rather than bypassing it.

## Output hygiene

* `tools/cloud_dump.py` prints the device list; the **local key** is written to
  `data/devices.json` (gitignored) and masked in stdout.
* Never paste a raw `data/devices.json`, a `.env`, or a capture file into a
  chat, a commit message, or a GitHub issue. If you need to show a fragment,
  redact it.
* GitHub issues: the repo is public-facing by default - assume anything you
  paste there is public.

## If you push the wrong thing

```bash
git reset --soft HEAD~1        # undo the commit, keep the files
git restore --staged <file>    # unstage the offending file
bash scripts/check_secrets.sh  # confirm
```

If a real credential was committed and pushed, **rotate it** (change the
Concept account password, regenerate the mitm CA, re-issue the local key by
re-pairing the robot) - deleting the commit does not un-push it.
