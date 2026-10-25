#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
if [[ -x .venv/bin/cryptovideo ]]; then
  exec .venv/bin/cryptovideo doctor
fi
echo 'Project virtualenv missing: run bash scripts/install.sh first.' >&2
exit 1
