#!/usr/bin/env bash
# Local ZIP/download launcher for Ubuntu.
# First execution installs dependencies and prompts for API key if missing.
# Subsequent executions search YouTube and produce individual reports.
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PATH="$HOME/.local/bin:$PATH"

if [[ ! -x "$ROOT/.venv/bin/cryptovideo" ]]; then
  echo "[CryptoVideoResearch] First start: installing required components ..."
  CVR_INSTALL_DIR="$ROOT" CVR_SKIP_INITIAL_RUN=1 bash "$ROOT/scripts/bootstrap.sh"
fi

cd "$ROOT"
# No arguments: launch interactive B menu. Legacy flag-only usage remains
# supported, e.g. bash run.sh --count 1 --cookies chrome.
if [[ "$#" -eq 0 ]]; then
  exec "$ROOT/.venv/bin/cryptovideo" menu
fi
case "$1" in
  menu|run|doctor|setup|analyze|analyze-file|youtube-news|news|login)
    exec "$ROOT/.venv/bin/cryptovideo" "$@" ;;
  *)
    exec "$ROOT/.venv/bin/cryptovideo" run "$@" ;;
esac
