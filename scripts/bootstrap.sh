#!/usr/bin/env bash
# Fresh Ubuntu 22.04/24.04 bootstrap. Requires network, curl and sudo/root.
# The API key is requested securely by the existing cryptovideo setup command.
set -Eeuo pipefail

APP="CryptoVideoResearch"
BRANCH="${CVR_BRANCH:-feat/v0.3-one-command-bootstrap}"
REPO="https://github.com/Aprivity/CryptoVideoResearch.git"
TARGET="${CVR_INSTALL_DIR:-$HOME/CryptoVideoResearch}"
LOCAL_BIN="$HOME/.local/bin"
MANAGED="$HOME/.local/share/cryptovideoresearch"
NODE_APPS="$MANAGED/npm"
TMP=""

note() { printf '\n[%s] %s\n' "$APP" "$*"; }
warn() { printf '\n[WARN] %s\n' "$*" >&2; }
die()  { printf '\n[ERROR] %s\n' "$*" >&2; exit 1; }
cleanup() { if [[ -n "$TMP" && -d "$TMP" ]]; then rm -rf "$TMP"; fi; }
trap cleanup EXIT

[[ -r /etc/os-release ]] || die "Only Ubuntu 22.04/24.04 is supported"
source /etc/os-release
[[ "$ID" == ubuntu ]] || die "Only Ubuntu is supported (found $ID)"
case "$VERSION_ID" in
  22.04|24.04) ;;
  *) die "Ubuntu 22.04/24.04 required; found $VERSION_ID" ;;
esac
[[ "$TARGET" == /* && "$TARGET" != "/" ]] || die "Install directory must be absolute and not /"
command -v curl >/dev/null 2>&1 || die "curl is required for bootstrap"
command -v sha256sum >/dev/null 2>&1 || die "sha256sum is required for integrity checks"

# Replace a nonstandard proxy scheme without guessing whether its port is HTTP.
for var in ALL_PROXY all_proxy HTTP_PROXY HTTPS_PROXY http_proxy https_proxy; do
  value="${!var:-}"
  if [[ "$value" == socks://* ]]; then
    warn "$var: replacing nonstandard socks:// with socks5h:// for this run"
    export "$var=socks5h://${value#socks://}"
  fi
done

if [[ "$(id -u)" -eq 0 ]]; then
  APT=(apt-get)
else
  command -v sudo >/dev/null 2>&1 || die "sudo permission is needed to install Ubuntu packages"
  APT=(sudo apt-get)
fi
note "Installing Ubuntu prerequisites (sudo may ask for your password)"
"${APT[@]}" update
"${APT[@]}" install -y --no-install-recommends \
  ca-certificates curl git python3 python3-venv python3-pip pipx xz-utils

python3 - <<'PY'
import sys
if sys.version_info < (3, 10):
    raise SystemExit("Python 3.10 or newer is required")
PY

mkdir -p "$LOCAL_BIN" "$MANAGED"
export PATH="$LOCAL_BIN:$PATH"
TMP="$(mktemp -d)"

link_managed() {
  local source="$1" destination="$2"
  if [[ -L "$destination" && "$(readlink "$destination")" == "$source" ]]; then return; fi
  [[ ! -e "$destination" && ! -L "$destination" ]] ||
    die "Cannot replace an existing unrelated command: $destination"
  ln -s "$source" "$destination"
}

node_major=0
if command -v node >/dev/null 2>&1; then
  node_major="$(node -p 'parseInt(process.versions.node.split(".")[0], 10)' 2>/dev/null || echo 0)"
fi
if ! [[ "$node_major" =~ ^[0-9]+$ ]] || (( node_major < 24 )) || ! command -v npm >/dev/null 2>&1; then
  note "Installing official Node.js 24 binary (verified with upstream SHA-256)"
  case "$(uname -m)" in
    x86_64) node_arch=x64 ;;
    aarch64|arm64) node_arch=arm64 ;;
    *) die "Unsupported Linux CPU architecture" ;;
  esac
  base=https://nodejs.org/dist/latest-v24.x
  curl -fLsS --retry 3 "$base/SHASUMS256.txt" -o "$TMP/SHASUMS256.txt"
  entry="$(grep -E "  node-v24[.][0-9]+[.][0-9]+-linux-$node_arch[.]tar[.]xz$" "$TMP/SHASUMS256.txt" | head -n 1 || true)"
  [[ -n "$entry" ]] || die "Node.js 24 release not found in SHASUMS256.txt"
  archive="${entry##* }"
  curl -fLsS --retry 3 "$base/$archive" -o "$TMP/$archive"
  (cd "$TMP" && printf '%s\n' "$entry" | sha256sum -c -) || die "Node.js checksum failed"
  staging="$MANAGED/node24.tmp.$$"
  mkdir -p "$staging"
  tar -xJf "$TMP/$archive" -C "$staging" --strip-components=1
  [[ ! -e "$MANAGED/node24" ]] || die "Existing Node.js directory is not usable: $MANAGED/node24"
  mv "$staging" "$MANAGED/node24"
  link_managed "$MANAGED/node24/bin/node" "$LOCAL_BIN/node"
  link_managed "$MANAGED/node24/bin/npm" "$LOCAL_BIN/npm"
  link_managed "$MANAGED/node24/bin/npx" "$LOCAL_BIN/npx"
fi
note "Using Node.js $(node -v), npm $(npm -v)"

note "Installing pinned Summarize CLI (user-local npm directory)"
if [[ ! -x "$LOCAL_BIN/summarize" ]]; then
  npm install --prefix "$NODE_APPS" --no-audit --no-fund '@steipete/summarize@0.25.3'
  link_managed "$NODE_APPS/node_modules/.bin/summarize" "$LOCAL_BIN/summarize"
fi
summarize --version || die "Summarize CLI failed to start"

note "Installing yt-dlp with pipx"
if [[ ! -x "$LOCAL_BIN/yt-dlp" ]]; then
  pipx install 'yt-dlp[default]'
fi
if ! pipx runpip yt-dlp show yt-dlp-ejs >/dev/null 2>&1; then
  pipx runpip yt-dlp install -U 'yt-dlp[default]'
fi
if ! pipx runpip yt-dlp show secretstorage >/dev/null 2>&1; then
  pipx inject yt-dlp secretstorage || warn "Optional Chrome Cookie helper could not be installed"
fi
"$LOCAL_BIN/yt-dlp" --version || die "yt-dlp installation could not be verified"

note "Installing project from $BRANCH"
if [[ -e "$TARGET" ]]; then
  [[ -d "$TARGET/.git" ]] || die "$TARGET already exists and is not a Git repository"
  current="$(git -C "$TARGET" branch --show-current)"
  [[ "$current" == "$BRANCH" ]] || die "Existing checkout is on $current. Not switching branches."
  if ! git -C "$TARGET" diff --quiet || ! git -C "$TARGET" diff --cached --quiet; then
    die "Uncommitted changes detected; installer will not overwrite them"
  fi
  git -C "$TARGET" pull --ff-only origin "$BRANCH"
else
  git clone --depth 1 --single-branch --branch "$BRANCH" "$REPO" "$TARGET"
fi

note "Creating project virtual environment"
python3 -m venv "$TARGET/.venv"
"$TARGET/.venv/bin/python" -m pip install --disable-pip-version-check -e "$TARGET"
link_managed "$TARGET/.venv/bin/cryptovideo" "$LOCAL_BIN/cryptovideo"

# Persist only the user-local CLI path, not secrets, browser state, or proxy config.
marker='# CryptoVideoResearch user CLI path'
profile="$HOME/.profile"
if ! grep -Fq "$marker" "$profile" 2>/dev/null; then
  printf '\n%s\n%s\n' "$marker" \
    'case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) export PATH="$HOME/.local/bin:$PATH";; esac' >> "$profile"
fi

note "Configuring DeepSeek API Key (hidden input; preserves existing key)"
if [[ -t 0 ]]; then
  "$TARGET/.venv/bin/cryptovideo" setup
elif [[ -r /dev/tty ]]; then
  "$TARGET/.venv/bin/cryptovideo" setup < /dev/tty
elif [[ -n "${DEEPSEEK_API_KEY:-}" ]]; then
  "$TARGET/.venv/bin/cryptovideo" setup
else
  die "An interactive terminal is required to enter the API key"
fi

note "Running local self-check"
"$TARGET/.venv/bin/cryptovideo" doctor ||
  warn "Doctor reported missing components; review the output above"

note "Running B: news intake once (no scheduled background monitoring)"
if "$TARGET/.venv/bin/cryptovideo" news --hours 72; then
  note "Report created: $TARGET/outputs/news/latest.md"
else
  warn "Network RSS scan failed; install succeeded. Retry: cryptovideo news --hours 72"
fi

note "Ready"
printf 'Project: %s\nNews: cryptovideo news --hours 72\nVideo: cryptovideo analyze URL --cookies chrome\nStatus: cryptovideo doctor\n' "$TARGET"
