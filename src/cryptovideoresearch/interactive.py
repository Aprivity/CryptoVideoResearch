"""Interactive B workflow TUI with numbered and arrow-key navigation.

Uses Python stdlib only. State is private, local and independent of reports.
Entering without a YouTuber always defaults to market-news discovery; repeat
runs are permitted and old reports stay cached unless refresh is selected.
"""
from __future__ import annotations

import json
import os
import select
import sys
import tempfile
import termios
import tty
from pathlib import Path

from .channels import Channel, find_channels_by_name, normalize_channel
from .config import config_dir

CHOICES_COOKIES = ("none", "chrome", "firefox", "chromium", "brave")
DEFAULTS = {
    "count": 2, "hours": 168, "cookies": "none", "strict_dates": False,
    "verify_top": 10, "channels": [], "last_channel": "",
}


def settings_path() -> Path:
    return config_dir() / "b_menu.json"


def load_settings(path: Path | None = None) -> dict:
    path = path or settings_path()
    config = {**DEFAULTS, "channels": []}
    if not path.is_file():
        return config
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(stored, dict):
            return config
        count, hours = stored.get("count"), stored.get("hours")
        if type(count) is int and 1 <= count <= 5:
            config["count"] = count
        if type(hours) is int and 1 <= hours <= 8760:
            config["hours"] = hours
        if stored.get("cookies") in CHOICES_COOKIES:
            config["cookies"] = stored["cookies"]
        if type(stored.get("strict_dates")) is bool:
            config["strict_dates"] = stored["strict_dates"]
        valid = []
        for entry in stored.get("channels", [])[:50]:
            if not isinstance(entry, dict):
                continue
            try:
                url = normalize_channel(str(entry.get("url", "")))
            except ValueError:
                continue
            if not any(x["url"] == url for x in valid):
                valid.append({"name": str(entry.get("name") or url)[:100], "url": url})
        config["channels"] = valid
        config["last_channel"] = str(stored.get("last_channel") or "")[:200]
    except (ValueError, OSError, TypeError, AttributeError):
        pass
    return config


def save_settings(config: dict, path: Path | None = None) -> None:
    path = path or settings_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    if path.is_symlink():
        raise ValueError("拒绝通过符号链接写入设置")
    fd, name = tempfile.mkstemp(prefix=".b-menu-", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(config, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def choose(title: str, options: list[str], *, default: int = 0) -> int:
    """Select via 1..9/0, ↑/↓ + Enter, or plain numbered input fallback."""
    if not options or not 0 <= default < len(options) or len(options) > 10:
        raise ValueError("Invalid interactive menu")
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print("\n" + title)
        for i, label in enumerate(options):
            print(f"  {i + 1 if i < 9 else 0}. {label}")
        while True:
            answer = input(f"选择 [回车默认 {default + 1}]: ").strip()
            if not answer:
                return default
            if answer == "0":
                return len(options) - 1
            if answer.isascii() and answer.isdigit() and 1 <= int(answer) <= len(options):
                return int(answer) - 1
            print("请输入列表中的数字，或直接回车")

    fd = sys.stdin.fileno()
    previous = termios.tcgetattr(fd)
    selected = default
    try:
        tty.setcbreak(fd)
        sys.stdout.write("\x1b[?25l")
        while True:
            sys.stdout.write("\x1b[2J\x1b[H")
            sys.stdout.write(f"{title}\n\n")
            for i, label in enumerate(options):
                number = str(i + 1) if i < 9 else "0"
                mark = "❯" if i == selected else " "
                sys.stdout.write(f" {mark} [{number}] {label}\n")
            sys.stdout.write("\n↑/↓ 移动  ·  数字直接选择  ·  回车确认  ·  0 返回/退出\n")
            sys.stdout.flush()
            ch = os.read(fd, 1)
            if not ch:
                return len(options) - 1
            if ch in (b"\r", b"\n"):
                return selected
            if ch == b"\x03":
                raise KeyboardInterrupt
            if ch == b"\x04":
                return len(options) - 1
            if ch == b"0":
                return len(options) - 1
            if b"1" <= ch <= b"9":
                index = int(ch) - 1
                if index < len(options):
                    return index
            if ch == b"\x1b":
                # Escape sequences arrive as ESC [ A / ESC [ B on Ubuntu.
                if select.select([fd], [], [], 0.09)[0]:
                    first = os.read(fd, 1)
                    if first in (b"[", b"O") and select.select([fd], [], [], 0.09)[0]:
                        arrow = os.read(fd, 1)
                        if arrow == b"A":
                            selected = (selected - 1) % len(options)
                        elif arrow == b"B":
                            selected = (selected + 1) % len(options)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, previous)
        sys.stdout.write("\x1b[?25h\x1b[2J\x1b[H")
        sys.stdout.flush()


def prompt_text(message: str) -> str:
    try:
        return input(message).strip()
    except EOFError:
        return ""


def pause() -> None:
    prompt_text("\n按回车返回菜单…")


def creator_from_input(value: str, config: dict) -> Channel | None:
    """Choose a precise channel, never blindly search across all authors."""
    try:
        url = normalize_channel(value)
        return Channel(name=value.lstrip("@")[:100], url=url)
    except ValueError:
        if value.startswith(("http:", "https:")) or value.startswith("@"):
            print("请输入有效的 @handle 或 YouTube 频道链接")
            return None
        try:
            print("正在寻找 YouTuber 频道（不会调用 DeepSeek）…")
            found = find_channels_by_name(value, cookies=config["cookies"])
        except (RuntimeError, OSError, ValueError) as exc:
            print(f"频道搜索失败：{exc}")
            return None
        if not found:
            print("未找到可核验的频道。请尝试输入 @handle 或官方频道链接。")
            return None
        chosen = choose("请选择与你输入的名称匹配的 YouTuber（需要确认身份）",
                        [f"{x.name} — {x.url}" for x in found] + ["返回"])
        return None if chosen == len(found) else found[chosen]


def remember_channel(channel: Channel, config: dict) -> None:
    if not any(item["url"] == channel.url for item in config["channels"]):
        config["channels"].append({"name": channel.name, "url": channel.url})
    config["last_channel"] = channel.url
    save_settings(config)


def launch(channel: Channel | None, config: dict) -> None:
    from .cli import build_parser
    mode = f"频道：{channel.name}" if channel else "市场新闻"
    print(f"\n运行 B · {mode}")
    print(f"视频范围：{config['hours']} 小时，DeepSeek 最多 {config['count']} 次模型调用")
    print(f"浏览器 Cookies：{config['cookies']}｜严格日期：{'开启' if config['strict_dates'] else '关闭'}")
    if config["cookies"] == "none":
        print("[INFO] 当前匿名访问 YouTube。如果字幕不可用，可在主菜单的「运行设置」中改为 chrome。")
    print("报告按视频独立保存；旧报告保留并复用缓存。")
    args = [
        "run", "--hours", str(config["hours"]),
        "--count", str(config["count"]),
        "--verify-top", str(config["verify_top"]),
        "--cookies", config["cookies"],
    ]
    if config["strict_dates"]:
        args.append("--strict-dates")
    if channel:
        args.extend(["--channel", channel.url])
    command = build_parser().parse_args(args)
    try:
        code = command.handler(command)
        if code:
            print("本轮未完成有效视频报告，请检查上方的 [FAIL]/[HINT] 和 latest.md。")
            if config["cookies"] == "none":
                print("当前未使用浏览器 Cookies；可以返回「运行设置」选择 chrome 后重试。")
    except (RuntimeError, OSError, ValueError) as exc:
        print(f"运行失败：{exc}")
    pause()


def settings_menu(config: dict) -> None:
    while True:
        labels = [
            f"报告数量：{config['count']}（DeepSeek 每轮调用上限）",
            f"时间窗口：{config['hours']} 小时",
            f"浏览器 Cookies：{config['cookies']}",
            f"只要发布时间已确认：{'是' if config['strict_dates'] else '否'}",
            "返回主菜单",
        ]
        index = choose("B 工作流设置（更改后自动保存在本机）", labels)
        if index == 4:
            return
        if index == 0:
            selected = choose("选择每轮最多调用 DeepSeek 的次数",
                              ["1 次", "2 次", "3 次", "4 次", "5 次", "返回"],
                              default=config["count"]-1)
            if selected < 5:
                config["count"] = selected+1
        if index == 1:
            selected = choose("选择视频时效窗口", [
                "24 小时", "72 小时", "168 小时（7 天）", "336 小时（14 天）", "返回"
            ], default={24:0,72:1,168:2,336:3}.get(config["hours"],2))
            if selected < 4:
                config["hours"] = (24,72,168,336)[selected]
        if index == 2:
            selected = choose("Cookies 来源", [*CHOICES_COOKIES, "返回"],
                              default=CHOICES_COOKIES.index(config["cookies"]))
            if selected < len(CHOICES_COOKIES):
                config["cookies"] = CHOICES_COOKIES[selected]
        if index == 3:
            config["strict_dates"] = not config["strict_dates"]
        save_settings(config)


def saved_channels_menu(config: dict) -> None:
    page = 0
    while True:
        channels = config["channels"]
        if not channels:
            print("\n还没有保存的 YouTuber。可以先在主菜单添加。")
            pause()
            return
        size = 7
        total = (len(channels) + size - 1) // size
        page = min(page, total - 1)
        shown = channels[page * size:(page + 1) * size]
        options = [f"{x['name']} — {x['url']}" for x in shown]
        commands = ["下一页" if page + 1 < total else "返回第一页", "删除已保存频道", "返回主菜单"]
        selection = choose(f"已保存 YouTuber · 第 {page+1}/{total} 页", options + commands)
        if selection == len(shown) + 2:
            return
        if selection == len(shown):
            page = (page + 1) % total
            continue
        if selection == len(shown) + 1:
            deleting = choose("选择要删除的频道", [x["name"] for x in shown] + ["取消"])
            if deleting < len(shown):
                removed = channels.pop(page * size + deleting)
                if config["last_channel"] == removed["url"]:
                    config["last_channel"] = ""
                save_settings(config)
            continue
        entry = shown[selection]
        selected = Channel(name=entry["name"], url=entry["url"])
        remember_channel(selected, config)
        launch(selected, config)



def main() -> int:
    if not sys.stdin.isatty():
        print("交互界面需要真实终端；自动脚本请使用 cryptovideo run [--channel @handle]", file=sys.stderr)
        return 2
    config = load_settings()
    try:
        while True:
            selection = choose(
                "CryptoVideoResearch · B 市场新闻与 YouTuber 研究\n"
                "无输入直接回车 = 搜索市场新闻；按数字或 ↑/↓ 选择",
                [
                    "搜索市场新闻（默认；允许重复检索并复用报告）",
                    "输入 YouTuber 名称 / @handle / 频道链接",
                    f"选择已保存 YouTuber（{len(config['channels'])}）",
                    "运行设置（报告数量、时间窗口、Cookies）",
                    "查看报告位置",
                    "退出",
                ],
            )
            if selection == 0:
                launch(None, config)
            elif selection == 1:
                entered = prompt_text("YouTuber 名称、@handle 或 YouTube 频道链接（直接回车=市场新闻）：")
                if not entered:
                    launch(None, config)
                    continue
                channel = creator_from_input(entered, config)
                if channel is not None:
                    remember_channel(channel, config)
                    print(f"已保存：{channel.name} — {channel.url}")
                    launch(channel, config)
            elif selection == 2:
                saved_channels_menu(config)
            elif selection == 3:
                settings_menu(config)
            elif selection == 4:
                print("\n市场新闻：<项目目录>/outputs/youtube-news/")
                print("YouTuber 独立目录：<项目目录>/outputs/youtubers/<频道>/")
                print(f"已保存菜单配置：{settings_path()}")
                pause()
            else:
                print("已退出。")
                return 0
    except (KeyboardInterrupt, EOFError):
        print("\n已退出。")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
