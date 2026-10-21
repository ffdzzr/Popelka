#!/usr/bin/env bash
# Toolchain setup for the Linux PC (the "lab" half of the workflow).
# Usage: bash scripts/setup_linux.sh
set -euo pipefail

say() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }

have() { command -v "$1" >/dev/null 2>&1; }

# --- python / uv ---------------------------------------------------------
if ! have uv; then
  say "installing uv"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi
say "uv: $(uv --version)"

# --- mitmproxy -----------------------------------------------------------
if ! have mitmdump; then
  say "installing mitmproxy"
  if have pipx; then
    pipx install mitmproxy
  else
    python3 -m venv "$HOME/.venvs/mitmproxy"
    "$HOME/.venvs/mitmproxy/bin/pip" install -U mitmproxy
    echo 'export PATH="$HOME/.venvs/mitmproxy/bin:$PATH"' >> "$HOME/.bashrc"
  fi
fi

# --- jadx / apktool ------------------------------------------------------
if ! have jadx; then
  say "installing jadx"
  if have sdk || [[ -f "$HOME/Android/Sdk/cmdline-tools/latest/bin/sdkmanager" ]]; then
    "$HOME/Android/Sdk/cmdline-tools/latest/bin/sdkmanager" "cmdline-tools;latest" >/dev/null 2>&1 || true
    SDKMANAGER="$HOME/Android/Sdk/cmdline-tools/latest/bin/sdkmanager"
  else
    SDKMANAGER=$(command -v sdkmanager || true)
  fi
  if [[ -n "${SDKMANAGER:-}" ]]; then
    "$SDKMANAGER" "build-tools;34.0.0" >/dev/null
    echo 'export PATH="$PATH:$HOME/Android/Sdk/build-tools/34.0.0"' >> "$HOME/.bashrc"
    say "jadx: unzip https://github.com/skylot/jadx/releases -> ~/jadx"
  else
    say "jadx: see https://github.com/skylot/jadx/releases (unzip, add jadx to PATH)"
  fi
fi
if ! have apktool; then
  say "installing apktool"
  if have sdk; then sdk "apktool" >/dev/null || true; fi
  say "apktool: https://apktool.org - download apktool.jar"
fi

# --- android tooling -----------------------------------------------------
if ! have adb; then
  say "installing adb"
  if have apt-get; then sudo apt-get update && sudo apt-get install -y adb android-tools-adb; fi
fi

# --- capture / misc ------------------------------------------------------
if have apt-get; then
  say "installing capture tools"
  sudo apt-get install -y tcpdump tshark wireshark-common || true
fi

cat <<'EOF'

Next steps:
  1. Get the Concept Home APK:
       - on the phone: install "APK Extractor" / "Obtainium" and export
         com.concept.www, or use `adb shell pm path com.concept.www` + `adb pull`
       - on the PC: download from APKMirror (pick an "Android 9+" variant)
  2. Scan it:
       python tools/apk_scan.py concept-home.apk --secrets-out data/app_secrets.json
  3. Log into the cloud and dump the robot:
       export TUYA_USER=... TUYA_PASS=... TUYA_REGION=eu
       python tools/cloud_dump.py --out data/ --download-maps
EOF
