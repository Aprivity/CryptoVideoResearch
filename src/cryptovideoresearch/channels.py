"""YouTube channel discovery and bounded upload listing for the B workflow.

Accept only official YouTube channel URLs / handles; resolve display names
through channel IDs from YouTube search, always with user confirmation.
No shell invocation, no API key, no paid AI operations in this module.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import quote, urlsplit, unquote

from .pipeline import PipelineError, checked_run, find_ytdlp

CHANNEL_ID = re.compile(r"UC[A-Za-z0-9_-]{22}$")
HANDLE = re.compile(r"@[\w.\-]{2,40}$", re.UNICODE)
CHANNEL_PATH = re.compile(r"/(?:channel|user|c)/[A-Za-z0-9_.\-]+(?:/videos)?/?$")
ALLOWED_HOSTS = frozenset(("youtube.com", "www.youtube.com", "m.youtube.com"))


@dataclass(frozen=True)
class Channel:
    name: str
    url: str


def normalize_channel(value: str) -> str:
    """Normalize a handle/channel URL to the channel's Videos tab.

    Arbitrary search queries or video watch pages cannot be used as a channel.
    This reduces accidental mixing of unrelated authors and URL abuse.
    """
    value = value.strip()
    if HANDLE.fullmatch(value):
        return f"https://www.youtube.com/{quote(value, safe='@._-')}/videos"
    parts = urlsplit(value)
    if parts.scheme != "https" or (parts.hostname or "").lower() not in ALLOWED_HOSTS:
        raise ValueError("输入 @handle 或 https://www.youtube.com/@handle / channel/UC... 频道链接")
    if parts.username or parts.password or parts.port or parts.query or parts.fragment:
        raise ValueError("频道链接不可携带登录信息、端口、参数或片段")
    path = unquote(parts.path).rstrip("/")
    if path.endswith("/videos"):
        path = path.removesuffix("/videos")
    if path.startswith("/@") and HANDLE.fullmatch(path[1:]):
        return f"https://www.youtube.com/{quote(path[1:], safe='@._-')}/videos"
    if CHANNEL_PATH.fullmatch(path) and path.count("/") in (2, 3):
        core = path.removesuffix("/videos")
        if core.startswith("/channel/") and not CHANNEL_ID.fullmatch(core.split("/")[-1]):
            raise ValueError("无效的 YouTube 频道 ID")
        return f"https://www.youtube.com{core}/videos"
    raise ValueError("仅支持 YouTube 频道主页或频道 ID，不能输入单个视频链接")



def channel_slug(url: str) -> str:
    """Safe predictable directory name for isolated creator reports."""
    path = urlsplit(normalize_channel(url)).path.removesuffix("/videos").strip("/")
    name = path.split("/")[-1].lstrip("@")
    # ASCII label + hash avoids collisions between Unicode channel handles.
    import hashlib
    short_hash = hashlib.sha256(normalize_channel(url).encode("utf-8")).hexdigest()[:8]
    label = re.sub(r"[^A-Za-z0-9_-]", "_", name)[:45] or "channel"
    return f"{label}-{short_hash}"


def list_channel_uploads(url: str, *, count: int = 30, cookies: str = "none") -> dict:
    """Flat playlist of a single channel's video uploads, newest first."""
    url = normalize_channel(url)
    if not 1 <= count <= 100:
        raise ValueError("count must be between 1 and 100")
    if cookies not in ("none", "chrome", "firefox", "chromium", "brave"):
        raise ValueError("Unsupported browser cookies")
    executable = find_ytdlp()
    if not executable:
        raise PipelineError("yt-dlp missing; run cryptovideo doctor")
    command = [
        executable, "--flat-playlist", "--dump-single-json", "--skip-download",
        "--playlist-end", str(count), "--no-warnings", "--ignore-errors", url,
    ]
    if cookies != "none":
        command[1:1] = ["--cookies-from-browser", cookies]
    result = checked_run(command, timeout=180)
    import json
    try:
        info = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise PipelineError("Channel lookup returned invalid JSON") from exc
    if not isinstance(info, dict) or not isinstance(info.get("entries"), list):
        raise PipelineError("Channel playlist could not be read or contains no video listing")
    return info


def find_channels_by_name(name: str, *, count: int = 18,
                          cookies: str = "none") -> list[Channel]:
    """Find possible channels through videos; caller must select the identity.

    Search results are NOT assumed to identify the requested YouTuber. Only
    entries with a provider-issued channel ID are offered as options.
    """
    name = name.strip()
    if not name or len(name) > 100:
        raise ValueError("请输入 1 到 100 字符的 YouTuber 名称")
    from .youtube_news import find_videos
    results = find_videos(name, count, cookies=cookies)
    seen: dict[str, Channel] = {}
    for entry in results.get("entries") or []:
        if not isinstance(entry, dict):
            continue
        channel_id = entry.get("channel_id")
        if not isinstance(channel_id, str) or not CHANNEL_ID.fullmatch(channel_id):
            continue
        display = str(entry.get("channel") or entry.get("uploader") or channel_id)[:100]
        if channel_id not in seen:
            seen[channel_id] = Channel(
                name=display,
                url=f"https://www.youtube.com/channel/{channel_id}/videos",
            )
    options = list(seen.values())
    name_lower = name.casefold()
    return sorted(options, key=lambda x: (
        name_lower == x.name.casefold(),
        name_lower in x.name.casefold(),
    ), reverse=True)[:15]
