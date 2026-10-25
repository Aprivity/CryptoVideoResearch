"""Local credentials and process-scoped DeepSeek configuration."""
from __future__ import annotations

import os
from pathlib import Path

DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_MODEL = "deepseek-flash"


def config_dir() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    return base.expanduser() / "cryptovideoresearch"


def key_path() -> Path:
    return config_dir() / "deepseek.key"


def save_key(value: str) -> Path:
    key = value.strip()
    if not key or "\n" in key or "\r" in key:
        raise ValueError("Invalid API key")
    directory = config_dir()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.chmod(0o700)
    path = key_path()
    if path.is_symlink():
        raise ValueError("Refusing to write through a symbolic link")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            file.write(key + "\n")
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        raise
    return path


def load_key() -> str:
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if key:
        return key
    path = key_path()
    if not path.is_file() or path.is_symlink():
        raise RuntimeError("DeepSeek API Key not configured. Run: cryptovideo setup")
    key = path.read_text(encoding="utf-8").strip()
    if not key:
        raise RuntimeError("DeepSeek API Key file is empty")
    return key


def make_model_env() -> dict[str, str]:
    env = os.environ.copy()
    # Summarize's OpenAI-compatible provider points only to DeepSeek.
    env["OPENAI_API_KEY"] = load_key()
    env["OPENAI_BASE_URL"] = DEEPSEEK_BASE_URL
    env["OPENAI_USE_CHAT_COMPLETIONS"] = "true"
    if any(env.get(name) for name in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy")):
        env["NODE_USE_ENV_PROXY"] = "1"
    return env
