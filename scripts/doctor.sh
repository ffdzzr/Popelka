#!/usr/bin/env bash
# Environment + project state check.
#
# Answers the questions a fresh session should not have to guess:
#   - is the toolchain here?
#   - is the working tree clean and everything pushed?
#   - do the tests pass?
#   - do we have credentials, a local key, an APK, a capture?
#   - can we reach the robot?
#
# Usage: bash scripts/doctor.sh
set -uo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$ROOT"
OK=$'\033[32m'; WARN=$'\033[33m'; BAD=$'\033[31m'; OFF=$'\033[0m'
ok()   { printf '  %s[ok]%s   %s\n' "$OK" "$OFF" "$1"; }
warn() { printf '  %swarn%s  %s\n' "$WARN" "$OFF" "$1"; }
bad()  { printf '  %smiss%s  %s\n' "$BAD" "$OFF" "$1"; }

echo "== environment =="
for tool in uv python3 git make; do
  if command -v "$tool" >/dev/null; then ok "$tool"; else bad "$tool not installed"; fi
done
for tool in mitmdump apktool jadx adb apksigner openssl age; do
  if command -v "$tool" >/dev/null; then ok "$tool"; else warn "$tool not installed (needed for: $(case $tool in
      mitmdump) echo capture;; apktool|jadx) echo APK analysis;; adb) echo pulling the APK from the phone;;
      apksigner) echo re-signing;; openssl|age) echo vault;; esac))"; fi
done

echo
echo "== repository =="
if [[ -n "$(git status --porcelain)" ]]; then
  warn "uncommitted changes:"
  git status --short | sed 's/^/        /'
else
  ok "working tree clean"
fi
UNPUSHED="$(git log --oneline @{u}..HEAD 2>/dev/null | wc -l | tr -d ' ')"
if [[ "$UNPUSHED" == "0" ]]; then
  ok "everything pushed to $(git rev-parse --abbrev-ref @{u} 2>/dev/null || echo '?')"
else
  warn "$UNPUSHED commit(s) not pushed - run 'make push MESSAGE=\"...\"'"
fi
if git config core.hooksPath >/dev/null 2>&1; then
  ok "secret-leak guard installed (core.hooksPath=$(git config core.hooksPath))"
else
  warn "leak guard not installed - run 'make hooks'"
fi

echo
echo "== tests =="
if command -v uv >/dev/null; then
  LOG="$(mktemp)"
  if uv run pytest -q >"$LOG" 2>&1; then
    ok "pytest green ($(tail -n 1 "$LOG"))"
  else
    bad "pytest failing - see $LOG"
    tail -n 5 "$LOG" | sed 's/^/        /'
  fi
  rm -f "$LOG"
fi

echo
echo "== artifacts =="
if [[ -f .env ]]; then
  if grep -q '^TUYA_USER=..*' .env 2>/dev/null; then ok ".env present with credentials"; else warn ".env present but TUYA_USER empty"; fi
else
  warn ".env missing - copy .env.example and fill in the Concept account (needed for 'make cloud-dump')"
fi
if [[ -f data/devices.json ]]; then
  ok "data/devices.json present (device list + local key, gitignored)"
  python3 - <<'PY' 2>/dev/null
import json
d = json.load(open("data/devices.json"))
for x in d:
    k = x.get("local_key") or ""
    masked = (k[:4] + "..." + k[-2:]) if len(k) > 8 else ("set" if k else "-")
    print(f"        {x.get('id')}  {x.get('name')}  local_key={masked}  ip={x.get('ip','-')}")
PY
else
  warn "data/devices.json missing - run 'make cloud-dump' to get the device list and local key"
fi
APKS="$(find . -maxdepth 2 -name '*.apk' -not -path './.git/*' 2>/dev/null | head -3)"
if [[ -n "$APKS" ]]; then
  ok "APK present: $(echo "$APKS" | tr '\n' ' ')"
  warn "APKs are gitignored - never commit them"
else
  warn "no APK found - pull com.concept.www (adb shell pm path com.concept.www && adb pull ...)"
fi
if [[ -d captures ]] && [[ -n "$(ls -A captures 2>/dev/null)" ]]; then
  ok "captures present: $(ls captures | tail -n 3 | tr '\n' ' ')"
else
  warn "no captures yet - run 'make capture' while driving the app"
fi
if [[ -f data/app_secrets.json ]]; then
  ok "app_secrets.json present (Tuya app key from the APK)"
else
  warn "app_secrets.json missing - run 'make scan APK=...'"
fi

echo
echo "== robot reachability =="
IP=""
if [[ -n "${POPELKA_IP:-}" ]]; then
  IP="$POPELKA_IP"
elif [[ -f data/devices.json ]]; then
  IP="$(python3 -c "import json;d=json.load(open('data/devices.json'));print((d[0].get('ip') or '') if d else '')" 2>/dev/null)"
fi
if [[ -n "$IP" ]]; then
  if command -v ping >/dev/null && ping -c 1 -W 2 "$IP" >/dev/null 2>&1; then
    ok "robot $IP answers ping"
  else
    warn "robot $IP does not answer ping (may be asleep - wake it with the remote)"
  fi
  if command -v nc >/dev/null; then
    if nc -z -w 3 "$IP" 6668 2>/dev/null; then
      ok "TCP 6668 open - local Tuya protocol reachable"
    else
      warn "TCP 6668 closed - the local protocol may be disabled or the robot is off"
    fi
  fi
else
  warn "robot IP unknown (set POPELKA_IP or run 'make cloud-dump')"
fi

echo
echo "== next step =="
if [[ ! -f data/app_secrets.json ]] && [[ -n "$APKS" ]]; then
  echo "  make scan APK=<the apk>"
elif [[ ! -f data/devices.json ]]; then
  echo "  make cloud-dump      # needs .env"
elif [[ -n "$IP" ]]; then
  echo "  make replay ARGS=\"status\""
else
  echo "  read docs/JOURNAL.md (tail) and docs/HANDOFF.md, then continue the phase you were on"
fi
