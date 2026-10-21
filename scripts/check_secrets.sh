#!/usr/bin/env bash
# Guard against committing secrets or captures.
#
# Scans the *staged* diff for credential-shaped strings and for files that
# should never be committed (APKs, key stores, captured traffic, map dumps).
#
# Usage: bash scripts/check_secrets.sh            (checks the staged diff)
#        bash scripts/check_secrets.sh --all      (scans the whole worktree)
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
RAW_PATTERNS="$HERE/secret_patterns.txt"
# Strip comments and blank lines: grep -f would otherwise treat them as
# patterns (a "#" line matches every shebang, an empty line matches everything).
PATTERNS="$(mktemp)"
trap 'rm -f "$PATTERNS"' EXIT
grep -v -e '^[[:space:]]*#' -e '^[[:space:]]*$' "$RAW_PATTERNS" > "$PATTERNS"

FAIL=0
RED=$'\033[31m'; GRN=$'\033[32m'; OFF=$'\033[0m'

# Paths that must never be committed.
FORBIDDEN_PATHS='(\.apk$|\.aab$|\.keystore$|\.jks$|\.pem$|\.key$|\.env$|\.mitm$|flows\.mitm$|^data/|^private/|^vault/|^captures/|\.bin$|\.pgm$)'

report() { printf '%s%s%s\n' "$RED" "$1" "$OFF"; FAIL=1; }

scan_file() {
  # $1 = path on disk, $2 = label for messages
  local path="$1" label="$2"
  [[ -f "$path" ]] || return 0
  # Templates and samples are supposed to contain placeholder values.
  case "$label" in
    *.example|*.example.*|*.sample|*.sample.*|*/secret_patterns.txt) return 0 ;;
  esac
  if grep -aEqf "$PATTERNS" "$path" 2>/dev/null; then
    report "credential-shaped content in: $label"
    grep -aEnf "$PATTERNS" "$path" 2>/dev/null | sed -n '1,3p' | sed 's/^/      /'
  fi
}

if [[ "${1:-}" == "--all" ]]; then
  echo "==> scanning worktree (excluding .git, .venv, data, private, vault, captures)"
  while IFS= read -r -d '' f; do
    case "$f" in
      ./data/*|./private/*|./vault/*|./captures/*|./.git/*|./.venv/*) continue ;;
    esac
    if [[ "$f" =~ $FORBIDDEN_PATHS ]]; then
      report "forbidden file present (keep it out of git): $f"
    fi
    scan_file "$f" "$f"
  done < <(find . -path ./.git -prune -o -path ./.venv -prune -o -path ./data -prune \
             -o -path ./private -prune -o -path ./vault -prune -o -path ./captures -prune \
             -o -type f -print0)
else
  echo "==> scanning staged changes"
  while IFS= read -r -d '' f; do
    if [[ "$f" =~ $FORBIDDEN_PATHS ]]; then
      report "forbidden file staged: $f"
    fi
    tmp="$(mktemp)"
    if git show ":$f" > "$tmp" 2>/dev/null; then
      scan_file "$tmp" "$f"
    fi
    rm -f "$tmp"
  done < <(git diff --cached --name-only --diff-filter=ACM -z)
fi

if [[ $FAIL -eq 0 ]]; then
  printf '%sno secrets detected%s\n' "$GRN" "$OFF"
else
  echo
  echo "If a hit is a false positive, adjust scripts/secret_patterns.txt"
  echo "(do not disable the check)"
fi
exit $FAIL
