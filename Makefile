# Popelka - Concept VR3125 reverse engineering
# Every step is one command. Run `make help` for the list.

SHELL := /bin/bash
PY := uv run python
.DEFAULT_GOAL := help

.PHONY: help setup start doctor test lint scan cloud-dump capture resign replay check-secrets audit hooks vault-push vault-pull push journal

help: ## show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "};{printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

setup: ## install the toolchain (Linux PC: jadx, mitmproxy, adb, tshark) + leak guard
	@bash scripts/setup_linux.sh
	@bash scripts/install_hooks.sh

doctor: ## check the environment, repo state and next step
	@bash scripts/doctor.sh

start: ## session start: doctor + journal tail + repo state
	@bash scripts/doctor.sh
	@echo
	@echo "== journal tail =="
	@tail -n 25 docs/JOURNAL.md

test: ## run the test suite
	@uv run pytest -q

scan: ## mine the Concept Home APK (APK=path/to.apk)
	@test -n "$(APK)" || { echo "usage: make scan APK=concept-home.apk"; exit 1; }
	@mkdir -p data
	@$(PY) tools/apk_scan.py "$(APK)" --secrets-out data/app_secrets.json

cloud-dump: ## dump devices, live DPs, specs and maps from the Tuya cloud
	@mkdir -p data
	@$(PY) tools/cloud_dump.py --out data --download-maps

capture: ## run mitmproxy with the DP15 decoder (PORT=8080)
	@bash scripts/capture.sh $(PORT)

resign: ## re-sign an APK with the mitm CA so the app trusts it (APK=..., OUT=...)
	@bash scripts/resign_apk.sh "$(APK)" "$(OUT)"

replay: ## send a built command to the robot over the local socket
	@$(PY) -m popelka.replay $(ARGS)

hooks: ## install the secret-leak guard as a git pre-commit hook
	@bash scripts/install_hooks.sh

check-secrets: ## scan the staged diff for credentials
	@bash scripts/check_secrets.sh

audit: ## scan the whole worktree for credentials and stray captures
	@bash scripts/check_secrets.sh --all

vault-push: ## pack sensitive artifacts into an encrypted archive
	@bash scripts/vault.sh pack

vault-pull: ## restore from an encrypted archive (ARCHIVE=...)
	@bash scripts/vault.sh unpack "$(ARCHIVE)"

journal: ## show the tail of the working journal
	@tail -n 40 docs/JOURNAL.md

push: ## commit and push (MESSAGE="...")
	@bash scripts/check_secrets.sh
	@git add -A
	@git commit -m "$(or $(MESSAGE),chore: wip)"
	@git push origin main
