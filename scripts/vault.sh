#!/usr/bin/env bash
# Encrypted vault for moving sensitive artifacts between machines
# (phone <-> PC <-> Termux) without touching the cloud.
#
# Everything it packs is encrypted with a passphrase before it leaves the
# machine, so even a stray copy of the archive is useless without that phrase.
#
# Usage:
#   bash scripts/vault.sh pack                     # -> vault/popelka-<stamp>.tar.gz.enc
#   bash scripts/vault.sh unpack <archive>         # restore into ./
#   bash scripts/vault.sh list                     # show local archives
#
# Encryption: age (preferred) or openssl aes-256-cbc/pbkdf2 as fallback.
set -euo pipefail

VAULT_DIR="${VAULT_DIR:-vault}"
# What gets packed. Keep this list explicit - it is the definition of
# "sensitive" for this project.
INCLUDE=(
  "private"
  "data"
  ".env"
  "captures"
)

cmd_pack() {
  command -v age >/dev/null && BACKEND=age || BACKEND=openssl
  command -v openssl >/dev/null || { echo "need age or openssl" >&2; exit 1; }

  local stamp archive tmp
  stamp="$(date +%Y%m%d-%H%M%S)"
  mkdir -p "$VAULT_DIR"
  archive="$VAULT_DIR/popelka-$stamp.tar.gz.enc"
  tmp="$(mktemp -d)"

  echo "==> collecting sensitive paths"
  local manifest="$tmp/manifest.txt"
  : > "$manifest"
  for p in "${INCLUDE[@]}"; do
    [[ -e "$p" ]] || continue
    # never pack the vault into itself
    [[ "$p" == "$VAULT_DIR" ]] && continue
    tar -czf "$tmp/$(basename "$p").tgz" -C "$(dirname "$p")" "$(basename "$p")" 2>/dev/null || continue
    echo "$p" >> "$manifest"
    echo "    $p"
  done
  if [[ ! -s "$manifest" ]]; then
    echo "nothing to pack"
    rm -rf "$tmp"
    return 0
  fi

  echo "==> encrypting ($BACKEND)"
  if [[ "$BACKEND" == "age" ]]; then
    age -p -o "$archive" "$tmp"/*.tgz
  else
    # -md sha256 keeps it portable; pbkdf2 iteration count is high on purpose
    local names
    names="$(cd "$tmp" && ls *.tgz 2>/dev/null | tr '\n' ' ')"
    tar -czf "$tmp/bundle.tar.gz" -C "$tmp" $names
    if [[ -n "${POPELKA_VAULT_PASSPHRASE:-}" ]]; then
      openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt \
        -pass env:POPELKA_VAULT_PASSPHRASE -in "$tmp/bundle.tar.gz" -out "$archive"
    else
      openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt \
        -in "$tmp/bundle.tar.gz" -out "$archive"
    fi
  fi
  rm -rf "$tmp"

  chmod 600 "$archive"
  echo
  echo "packed: $archive"
  echo "transfer it over the LAN (never via a public repo):"
  echo "  scp $archive <other-host>:~/$VAULT_DIR/"
  echo "or copy it by hand to a USB stick"
  echo
  echo "note: $VAULT_DIR/ is gitignored - it is intentionally not pushed anywhere"
}

cmd_unpack() {
  local archive="${1:-}"
  [[ -n "$archive" ]] || { echo "usage: vault.sh unpack <archive>" >&2; exit 1; }
  [[ -f "$archive" ]] || { echo "no such archive: $archive" >&2; exit 1; }

  local tmp
  tmp="$(mktemp -d)"
  echo "==> decrypting (you will be asked for the passphrase)"
  if age -d -o "$tmp/bundle.tar.gz" "$archive" 2>/dev/null; then
    :
  else
    if [[ -n "${POPELKA_VAULT_PASSPHRASE:-}" ]]; then
      openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 \
        -pass env:POPELKA_VAULT_PASSPHRASE -in "$archive" -out "$tmp/bundle.tar.gz"
    else
      openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -in "$archive" -out "$tmp/bundle.tar.gz"
    fi
  fi
  echo "==> restoring"
  tar -xzf "$tmp/bundle.tar.gz" -C "$tmp"
  for tgz in "$tmp"/*.tgz; do
    [[ -f "$tgz" ]] || continue
    tar -xzf "$tgz" -C "$(pwd)"
  done
  rm -rf "$tmp"
  echo "restored into $(pwd)"
  echo "run 'bash scripts/check_secrets.sh --all' to confirm nothing sensitive is tracked"
}

cmd_list() {
  if [[ -d "$VAULT_DIR" ]]; then
    ls -lh "$VAULT_DIR" 2>/dev/null || true
  else
    echo "no vault directory yet ($VAULT_DIR)"
  fi
}

case "${1:-}" in
  pack) cmd_pack ;;
  unpack) shift; cmd_unpack "$@" ;;
  list) cmd_list ;;
  *)
    sed -n '2,12p' "$0"
    exit 1
    ;;
esac
