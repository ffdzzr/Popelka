#!/usr/bin/env bash
# Start mitmproxy with the DP15 capture addon.
#
# Usage:
#   bash scripts/capture.sh [listen_port]
#
# Then point the phone's Wi-Fi proxy at <pc-ip>:<listen_port> and drive the app.
# Captured payloads are written to captures/dp15-<timestamp>.txt (hex) so they
# can be replayed through tools/decode_payloads.py later.
set -euo pipefail

PORT="${1:-8080}"
OUT_DIR="${CAPTURE_DIR:-captures}"
ADDON="$(cd "$(dirname "$0")/.." && pwd)/tools/mitm_dp15.py"
mkdir -p "$OUT_DIR"
STAMP="$(date +%Y%m%d-%H%M%S)"
LOG="$OUT_DIR/dp15-$STAMP.txt"

IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
cat <<EOF
==> mitmproxy on 0.0.0.0:$PORT
    phone Wi-Fi proxy -> ${IP:-<this-machine-ip>}:$PORT
    CA:                $HOME/.mitmproxy/mitmproxy-ca-cert.crt  (install it on the phone)
    log:               $LOG
    press Ctrl+C to stop
EOF

command -v mitmdump >/dev/null || { echo "mitmdump not found" >&2; exit 1; }

mitmdump -s "$ADDON" --listen-host 0.0.0.0 --listen-port "$PORT" \
         --set flow_detail=1 --set console_eventlog_verbosity=info \
  2>&1 | tee -a "$LOG"

echo
echo "captured to $LOG"
echo "decode with: python tools/decode_payloads.py $LOG"
