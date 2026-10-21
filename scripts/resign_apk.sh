#!/usr/bin/env bash
# Re-sign an APK so that mitmproxy's CA is trusted by the app.
#
# Android 7+ ignores user-installed CAs, so we:
#   1. decode the APK with apktool
#   2. write a network_security_config.xml that trusts user CAs
#   3. rebuild, zipalign, sign with a local debug keystore
#
# Usage:
#   bash scripts/resign_apk.sh concept-home.apk [output.apk]
#
# Requires (Linux PC): apktool, apksigner (android build-tools) or uber-apk-signer,
# and mitmproxy's CA at ~/.mitmproxy/mitmproxy-ca-cert.cer
set -euo pipefail

IN_APK="${1:-}"
OUT_APK="${2:-}"
WORKDIR="${RESIGN_WORKDIR:-private/resign}"

if [[ -z "$IN_APK" ]]; then
  cat <<'EOF'
Usage: bash scripts/resign_apk.sh <input.apk> [output.apk]

Prerequisites:
  apktool, apksigner (or uber-apk-signer), openssl
  mitmproxy CA:  ls ~/.mitmproxy/mitmproxy-ca-cert.cer
EOF
  exit 1
fi
[[ -f "$IN_APK" ]] || { echo "no such file: $IN_APK" >&2; exit 1; }
[[ -n "$OUT_APK" ]] || OUT_APK="${IN_APK%.apk}-resigned.apk"

command -v apktool >/dev/null || { echo "apktool not installed" >&2; exit 1; }

CA_CER="$HOME/.mitmproxy/mitmproxy-ca-cert.cer"
CA_PEM="$WORKDIR/mitm-ca.pem"
KEYSTORE="${RESIGN_KEYSTORE:-$HOME/.popelka/debug.keystore}"
KEYTOOL_PASS="${RESIGN_KEY_PASS:-popelka}"

mkdir -p "$WORKDIR"

if [[ ! -f "$CA_CER" ]]; then
  cat <<EOF >&2
mitmproxy CA not found at $CA_CER
Start mitmdump once (it generates the CA), then re-run this script.
EOF
  exit 1
fi
openssl x509 -inform DER -in "$CA_CER" -out "$CA_PEM" 2>/dev/null \
  || cp "$CA_CER" "$CA_PEM"

echo "==> decoding $IN_APK"
rm -rf "$WORKDIR/decoded"
apktool d -f "$IN_APK" -o "$WORKDIR/decoded" >/dev/null

echo "==> injecting network security config"
mkdir -p "$WORKDIR/decoded/res/xml"
cat > "$WORKDIR/decoded/res/xml/network_security_config.xml" <<'XML'
<?xml version="1.0" encoding="utf-8"?>
<network-security-config>
    <base-config cleartextTrafficPermitted="true">
        <trust-anchors>
            <certificates src="system" />
            <certificates src="user" />
        </trust-anchors>
    </base-config>
</network-security-config>
XML

# Point the manifest at the config (skip if the app already declares one).
MANIFEST="$WORKDIR/decoded/AndroidManifest.xml"
if ! grep -q "networkSecurityConfig" "$MANIFEST"; then
  python3 - "$MANIFEST" <<'PY'
import re, sys
path = sys.argv[1]
xml = open(path, encoding="utf-8").read()
xml = re.sub(
    r"<application\b",
    '<application android:networkSecurityConfig="@xml/network_security_config"',
    xml,
    count=1,
)
open(path, "w", encoding="utf-8").write(xml)
PY
fi

echo "==> rebuilding"
apktool b "$WORKDIR/decoded" -o "$WORKDIR/unsigned.apk" >/dev/null

if [[ ! -f "$KEYSTORE" ]]; then
  echo "==> creating debug keystore"
  keytool -genkeypair -v -keystore "$KEYSTORE" -alias popelka \
    -keyalg RSA -keysize 2048 -validity 10000 \
    -storepass "$KEYTOOL_PASS" -keypass "$KEYTOOL_PASS" \
    -dname "CN=Popelka Debug, OU=RE, O=Popelka, C=CZ" >/dev/null
fi

if command -v uber-apk-signer >/dev/null; then
  echo "==> signing (uber-apk-signer)"
  uber-apk-signer --apks "$WORKDIR/unsigned.apk" --out "$WORKDIR/signed" >/dev/null
  cp "$WORKDIR"/signed/*-aligned-signed.apk "$OUT_APK"
else
  APKSIGNER="$(command -v apksigner || true)"
  [[ -n "$APKSIGNER" ]] || { echo "need apksigner or uber-apk-signer" >&2; exit 1; }
  echo "==> zipalign"
  ZIPALIGN="$(command -v zipalign || true)"
  if [[ -n "$ZIPALIGN" ]]; then
    "$ZIPALIGN" -f 4 "$WORKDIR/unsigned.apk" "$WORKDIR/aligned.apk"
  else
    cp "$WORKDIR/unsigned.apk" "$WORKDIR/aligned.apk"
  fi
  echo "==> signing"
  "$APKSIGNER" sign \
    --ks "$KEYSTORE" --ks-pass "pass:$KEYTOOL_PASS" --key-pass "pass:$KEYTOOL_PASS" \
    --ks-key-alias popelka --out "$OUT_APK" "$WORKDIR/aligned.apk"
fi

chmod 600 "$OUT_APK" 2>/dev/null || true
echo
echo "done: $OUT_APK"
echo "install with:  adb install -r $OUT_APK"
echo "(this replaces the Play version - reinstall from Play later if you want updates)"
