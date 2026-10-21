#!/usr/bin/env bash
# Install the git pre-commit hook that blocks accidental secret commits.
# Run this once per machine (PC and phone).
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
HOOKS="$ROOT/.githooks"
mkdir -p "$HOOKS"

cat > "$HOOKS/pre-commit" <<'HOOK'
#!/usr/bin/env bash
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel)"
if ! bash "$ROOT/scripts/check_secrets.sh"; then
  echo
  echo "commit aborted: possible secret or capture staged."
  echo "If this is a false positive, adjust scripts/check_secrets.sh."
  exit 1
fi
HOOK
chmod +x "$HOOKS/pre-commit"

git config core.hooksPath .githooks
echo "installed: $HOOKS/pre-commit (core.hooksPath=.githooks)"
echo "run 'bash scripts/check_secrets.sh --all' for a full worktree audit"
