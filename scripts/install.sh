#!/usr/bin/env bash
# Ubuntu bootstrap. Does not access user secrets or bypass browser verification.
set -Eeuo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
info() { printf '[install] %s\n' "$*"; }

command -v python3 >/dev/null || fail 'Python 3.10+ required'
command -v node >/dev/null || fail 'Node.js 24+ required; use nvm to install it'
command -v npm >/dev/null || fail 'npm is required'
node_major="$(node -p 'process.versions.node.split(".")[0]')"
(( node_major >= 24 )) || fail "Node.js $(node -v) is too old; install Node.js 24+"
python3 - <<'PY'
import sys
if sys.version_info < (3, 10):
    raise SystemExit("Python 3.10+ is required")
PY

if ! command -v summarize >/dev/null 2>&1; then
  info 'Installing the tested Summarize CLI version'
  npm install -g '@steipete/summarize@0.25.3' \
    || fail 'npm install failed; use nvm or a user-writable npm prefix'
fi

if ! command -v pipx >/dev/null 2>&1; then
  info 'Installing pipx (sudo may ask for a password)'
  sudo apt-get update
  sudo apt-get install -y pipx
fi

if [[ ! -x "$HOME/.local/bin/yt-dlp" ]]; then
  info 'Installing yt-dlp with its default JS/EJS dependencies via pipx'
  pipx install 'yt-dlp[default]'
fi

if ! pipx runpip yt-dlp show yt-dlp-ejs >/dev/null 2>&1; then
  info 'Adding missing yt-dlp EJS components'
  pipx runpip yt-dlp install -U 'yt-dlp[default]'
fi
if ! pipx runpip yt-dlp show secretstorage >/dev/null 2>&1; then
  info 'Adding secretstorage for Linux browser Cookie decryption'
  pipx inject yt-dlp secretstorage
fi

if ! python3 -m venv .venv; then
  fail 'Unable to create .venv; install python3-venv with apt then rerun'
fi
info 'Installing the project CLI in .venv'
.venv/bin/python -m pip install --disable-pip-version-check -e .

info 'Done. Next steps:'
printf '%s\n' \
  '  source .venv/bin/activate' \
  '  cryptovideo setup' \
  '  cryptovideo doctor' \
  "  cryptovideo analyze 'https://www.youtube.com/watch?v=ZWrgUWKOq_0' --cookies chrome"
