#!/usr/bin/env bash
# Optional: launch Claude Code against DeepSeek's Anthropic-compatible endpoint.
# Applies to this process only. No persistent config edits.
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if ! command -v claude >/dev/null 2>&1; then
  echo 'Claude Code CLI missing (not required for the standard pipeline).' >&2
  exit 1
fi
if [[ -n "${DEEPSEEK_API_KEY:-}" ]]; then
  key="$DEEPSEEK_API_KEY"
elif [[ -x "$ROOT/.venv/bin/python" ]]; then
  key="$("$ROOT/.venv/bin/python" -c 'from cryptovideoresearch.config import load_key; print(load_key())')"
else
  echo 'Run install and cryptovideo setup, or export DEEPSEEK_API_KEY.' >&2
  exit 1
fi
[[ -n "$key" ]] || { echo 'DeepSeek API Key missing' >&2; exit 1; }
unset ANTHROPIC_API_KEY
export ANTHROPIC_AUTH_TOKEN="$key"
export ANTHROPIC_BASE_URL="https://api.deepseek.com/anthropic"
export ANTHROPIC_MODEL="deepseek-flash[1m]"
export ANTHROPIC_DEFAULT_OPUS_MODEL="deepseek-flash[1m]"
export ANTHROPIC_DEFAULT_SONNET_MODEL="deepseek-flash[1m]"
export ANTHROPIC_DEFAULT_HAIKU_MODEL="deepseek-flash"
export CLAUDE_CODE_SUBAGENT_MODEL="deepseek-flash"
if [[ -n "${HTTPS_PROXY:-}${https_proxy:-}" ]]; then
  export NODE_USE_ENV_PROXY=1
fi
unset key
exec claude "$@"
