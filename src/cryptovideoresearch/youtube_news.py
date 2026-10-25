"""YouTube-first market news discovery. yt-dlp search -> ranked links -> optional summarize.

Zero API-key usage unless --analyze-top > 0. No RSS feeds, auto trading, or
hidden scheduled polling. Upload times missing in flat search stay unknown.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .pipeline import (
    PipelineError, analyze_transcript, checked_run, extract_captions,
    find_ytdlp, write_report,
)

VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
TOPIC_TERMS = {
    "BTC 与加密市场": ("bitcoin", "btc", "比特币", "加密", "crypto", "币圈", "etf", "美联储", "利率"),
    "美联储与宏观": ("fed", "美联储", "降息", "加息", "通胀", "cpi", "ppi", "fomc", "利率", "非农", "就业", "inflation"),
    "AI 与半导体": ("ai", "人工智能", "英伟达", "nvidia", "nvda", "美光", "micron", "mu", "半导体", "芯片", "存储", "dram"),
}
NEWS_TERMS = ("新闻", "最新", "快讯", "市场", "解读", "分析", "走势", "突发",
              "news", "market", "breaking", "update", "fed", "财报")
HYPE_TERMS = ("暴富", "稳赚", "无脑买", "百分百", "带单", "会员群", "翻百倍", "100x", "必涨",
              "骗局", "暴涨", "崩盘", "救你的命", "千万别", "必赚", "彻底崩塌")


@dataclass
class Video:
    id: str
    title: str
    channel: str
    url: str
    topic: str
    published_at_utc: str | None
    duration_seconds: int | None
    views: int | None
    relevance_score: int
    time_status: str
    matched_queries: list[str] = field(default_factory=list)


def _date(value: dict) -> str | None:
    # yt-dlp flat playlist may not include any date; never invent one.
    timestamp = value.get("release_timestamp") or value.get("timestamp")
    if isinstance(timestamp, (float, int)) and 0 < timestamp < 20_000_000_000:
        return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat(timespec="seconds")
    raw = value.get("upload_date")
    if isinstance(raw, str) and re.fullmatch(r"\d{8}", raw):
        try:
            return datetime.strptime(raw, "%Y%m%d").replace(tzinfo=timezone.utc).date().isoformat()
        except ValueError:
            return None
    return None


def parse_results(raw: dict, *, topic: str, query: str, hours: int, now: datetime,
                  min_seconds: int = 90) -> list[Video]:
    if not isinstance(raw, dict):
        raise ValueError("YouTube search did not return a JSON object")
    output: list[Video] = []
    cutoff = now - timedelta(hours=hours)
    for entry in raw.get("entries") or []:
        if not isinstance(entry, dict):
            continue
        vid = entry.get("id")
        if not isinstance(vid, str) or not VIDEO_ID.fullmatch(vid):
            continue
        title = re.sub(r"\s+", " ", str(entry.get("title") or "")).strip()
        if not title:
            continue
        duration = entry.get("duration")
        duration = int(duration) if isinstance(duration, (int, float)) and 0 <= duration < 10**7 else None
        if duration is not None and duration < min_seconds:
            continue
        published = _date(entry)
        if published:
            # A YYYY-MM-DD upload date carries no timezone/time-of-day.
            # Compare dates to dates; never pretend it is midnight UTC.
            if len(published) == 10:
                dt_date = datetime.fromisoformat(published).date()
                if dt_date < cutoff.date() or dt_date > (now + timedelta(hours=24)).date():
                    continue
            else:
                dt = datetime.fromisoformat(published)
                if dt < cutoff or dt > now + timedelta(hours=24):
                    continue
        lower = title.casefold()
        relevant = sum(token in lower for token in TOPIC_TERMS.get(topic, ()))
        news = sum(token in lower for token in NEWS_TERMS)
        hype = sum(token in lower for token in HYPE_TERMS)
        # Keep ordinary news explainers even if they lack the exact topic keywords.
        # Search is the first filter. Score is a ranking, not factual accuracy.
        score = min(relevant, 5) * 3 + min(news, 3) * 2 - hype * 6
        if score < -3:
            continue
        channel = str(entry.get("channel") or entry.get("uploader") or "未知频道")
        views = entry.get("view_count")
        views = int(views) if isinstance(views, int) and views >= 0 else None
        output.append(Video(
            id=vid, title=title[:300], channel=channel[:150],
            url=f"https://www.youtube.com/watch?v={vid}", topic=topic,
            published_at_utc=published, duration_seconds=duration, views=views,
            relevance_score=score, time_status=("date-only" if published and len(published) == 10 else "timestamp") if published else "unknown",
            matched_queries=[query],
        ))
    return output


def merge_videos(items: list[Video], limit: int) -> list[Video]:
    seen: dict[str, Video] = {}
    for item in items:
        if item.id not in seen:
            seen[item.id] = item
        else:
            original = seen[item.id]
            if item.relevance_score > original.relevance_score:
                original.relevance_score = item.relevance_score
                original.topic = item.topic
            for query in item.matched_queries:
                if query not in original.matched_queries:
                    original.matched_queries.append(query)
    # Dated first within same relevance score; undated videos are never
    # falsely described as timely, and their time status remains explicit.
    ranked = sorted(seen.values(), key=lambda v: (
        v.relevance_score,
        v.published_at_utc is not None,
        v.published_at_utc or "",
    ), reverse=True)
    # Many different channels post identical clickbait headlines.
    unique_titles: set[str] = set()
    output: list[Video] = []
    for video in ranked:
        key = re.sub(r"[^\w\u4e00-\u9fff]+", "", video.title.casefold())
        if key in unique_titles:
            continue
        unique_titles.add(key)
        output.append(video)
        if len(output) >= limit:
            break
    return output


def _within_window(date_value: str, *, now: datetime, hours: int) -> bool:
    """Validate known dates without making YYYY-MM-DD look like a UTC instant."""
    cutoff = now - timedelta(hours=hours)
    if len(date_value) == 10:
        dt_date = datetime.fromisoformat(date_value).date()
        return cutoff.date() <= dt_date <= (now + timedelta(hours=24)).date()
    dt = datetime.fromisoformat(date_value)
    return cutoff <= dt <= now + timedelta(hours=24)


def fetch_video_metadata(video: Video, *, cookies: str = "none") -> dict:
    """Query complete YouTube metadata; does NOT download or analyze media."""
    executable = find_ytdlp()
    if not executable:
        raise PipelineError("yt-dlp missing")
    if cookies not in ("none", "chrome", "firefox", "chromium", "brave"):
        raise PipelineError("Unsupported cookie browser")
    command = [
        executable, "--no-playlist", "--skip-download",
        "--dump-single-json", "--no-warnings",
        "--js-runtimes", "node", video.url,
    ]
    if cookies != "none":
        command[1:1] = ["--cookies-from-browser", cookies]
    result = checked_run(command, timeout=80)
    try:
        data = json.loads(result.stdout)
        if not isinstance(data, dict) or data.get("id") != video.id:
            raise ValueError("Invalid video metadata or mismatched video ID")
        return data
    except json.JSONDecodeError as exc:
        raise PipelineError("YouTube metadata is not valid JSON") from exc


def verify_video_dates(videos: list[Video], *, count: int, cookies: str,
                       hours: int, now: datetime, errors: list[str]) -> list[Video]:
    """Verify the highest-ranked candidates, remove confirmed-old videos.

    Unverified candidates remain explicitly undated but are never selected
    automatically for paid analysis unless the user opts in.
    """
    kept: list[Video] = []
    for index, video in enumerate(videos):
        if index >= count or video.published_at_utc is not None:
            kept.append(video)
            continue
        try:
            data = fetch_video_metadata(video, cookies=cookies)
            published = _date(data)
            if published is not None:
                if not _within_window(published, now=now, hours=hours):
                    print(f"[SKIP] {video.id}: verified outside {hours}h window")
                    continue
                video.published_at_utc = published
                video.time_status = "date-only" if len(published) == 10 else "timestamp"
            if not video.channel or video.channel == "未知频道":
                video.channel = str(data.get("channel") or data.get("uploader") or "未知频道")
            if video.duration_seconds is None and isinstance(data.get("duration"), (int, float)):
                video.duration_seconds = int(data["duration"])
        except (PipelineError, OSError, ValueError, TypeError) as exc:
            errors.append(f"Metadata {video.id}: {str(exc)[:160]}")
        kept.append(video)
    # Verified freshness ranks above merely relevant undated titles.
    return sorted(kept, key=lambda v: (
        v.published_at_utc is not None, v.relevance_score,
        v.published_at_utc or "",
    ), reverse=True)


def find_videos(query: str, count: int, *, cookies: str = "none") -> dict:
    ytdlp = find_ytdlp()
    if not ytdlp:
        raise PipelineError("yt-dlp missing; rerun the bootstrap installer")
    if cookies not in ("none", "chrome", "firefox", "chromium", "brave"):
        raise PipelineError("Unknown browser cookie source")
    # ytsearchdate was removed in 2026; ytsearch is the supported extractor.
    command = [
        ytdlp, "--flat-playlist", "--dump-single-json", "--skip-download",
        "--no-warnings", "--ignore-errors",
        f"ytsearch{count}:{query}",
    ]
    if cookies != "none":
        command[1:1] = ["--cookies-from-browser", cookies]
    result = checked_run(command, timeout=150)
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise PipelineError("yt-dlp search returned invalid JSON") from exc


def remember(path: Path, videos: list[Video]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with sqlite3.connect(path) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS seen_videos (
            video_id TEXT PRIMARY KEY, first_seen_utc TEXT NOT NULL,
            last_seen_utc TEXT NOT NULL
        )""")
        added = 0
        for video in videos:
            result = db.execute(
                "INSERT OR IGNORE INTO seen_videos VALUES (?, ?, ?)",
                (video.id, now, now),
            )
            added += result.rowcount
            db.execute(
                "UPDATE seen_videos SET last_seen_utc = ? WHERE video_id = ?",
                (now, video.id),
            )
    return added


def render(output: Path, videos: list[Video], *, new_count: int,
           errors: list[str], requested: int, analyzed: list[dict]) -> None:
    output.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "0.4-youtube-news-preview",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "youtube-search",
        "requested_queries": requested,
        "discovery_new": new_count,
        "verification_status": "unverified-video-metadata-and-commentary",
        "disclaimer": "Video commentary is not independently verified market news or investment advice.",
        "errors": errors,
        "videos": [asdict(item) for item in videos],
        "analyses": analyzed,
    }
    tmp = output / "latest.json.tmp"
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(output / "latest.json")
    lines = [
        "# YouTube 市场新闻视频候选（未核实）", "",
        f"生成（UTC）：{payload['generated_at_utc']}｜视频：{len(videos)} 条｜本轮首次发现：{new_count} 条",
        "", "> YouTube 搜索结果是视频线索；发布时间可能未知。标题与博主解读均不代表已核实的市场事实。", "",
    ]
    for index, video in enumerate(videos, start=1):
        time_label = (video.published_at_utc + "（仅日期）") if video.time_status == "date-only" else (video.published_at_utc or "未知（不能确认是否最新）")
        duration = str(video.duration_seconds) + " 秒" if video.duration_seconds is not None else "未知"
        lines += [
            f"{index}. [{video.title.replace(chr(10), ' ')}]({video.url})",
            f"   - 频道：{video.channel}｜类别：{video.topic}｜发布时间：{time_label}｜时长：{duration}｜检索相关度：{video.relevance_score}",
            f"   - 匹配检索：{'; '.join(video.matched_queries)}",
        ]
    if analyzed:
        lines += ["", "## 已提取的视频观点（摘要仍未事实核验）", ""]
        for item in analyzed:
            path = item.get("analysis_file") or "—"
            lines.append(f"- {item['video_id']}：{item['status']}｜{path}")
    if errors:
        lines += ["", "## 检索或分析错误", ""]
        lines += [f"- {err[:240]}" for err in errors]
    if not videos:
        lines += ["", "未检索到合适的视频。"]
    tmp = output / "latest.md.tmp"
    tmp.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    tmp.replace(output / "latest.md")


def analyze_selected(videos: list[Video], output: Path, n: int, cookies: str,
                     refresh: bool, model: str, errors: list[str]) -> list[dict]:
    from .config import DEFAULT_MODEL
    prompt = Path(__file__).resolve().parents[2] / "prompts/youtube_news_zh.md"
    folder = output / "videos"
    results: list[dict] = []
    completed = 0
    model_attempts = 0
    # Try replacements if captions fail; never exceed N model API attempts.
    max_candidates = min(len(videos), max(n * 3, n + 2))
    for video in videos[:max_candidates]:
        if completed >= n:
            break
        target = folder / video.id / "analysis.md"
        if target.is_file() and not refresh:
            results.append({"video_id": video.id, "status": "cached", "analysis_file": str(target)})
            completed += 1
            continue
        try:
            transcript, source = extract_captions(video.url, folder, cookies=cookies, refresh=refresh)
            if model_attempts >= n:
                errors.append(f"Model call limit ({n}) reached; remaining videos skipped.")
                break
            model_attempts += 1
            summary = analyze_transcript(transcript, model=model or DEFAULT_MODEL, prompt=prompt)
            report = write_report(
                output_root=folder, video_id=video.id,
                source_url=video.url, transcript=transcript,
                subtitle_source=source, summary=summary,
                model=model or DEFAULT_MODEL,
            )
            results.append({"video_id": video.id, "status": "analyzed", "analysis_file": str(report)})
            completed += 1
        except (PipelineError, OSError, ValueError, RuntimeError) as exc:
            msg = f"{video.id} analysis failed: {exc}"
            errors.append(msg[:300])
            results.append({"video_id": video.id, "status": "failed"})
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="YouTube market-news video discovery and optional Summarize analysis")
    parser.add_argument("--config", default="youtube_news_queries.json")
    parser.add_argument("--output", default="outputs/youtube-news")
    parser.add_argument("--fixture", help="Use local yt-dlp search JSON for offline testing")
    parser.add_argument("--per-query", type=int, default=8)
    parser.add_argument("--max-results", type=int, default=15)
    parser.add_argument("--hours", type=int, default=168, help="Exclude dated videos older than N hours; undated results are labeled")
    parser.add_argument("--min-seconds", type=int, default=90)
    parser.add_argument("--verify-top", type=int, default=5, help="Check upload dates of N top videos (extra YouTube requests; 0 disables)")
    parser.add_argument("--allow-unknown-age", action="store_true", help="Explicitly allow paid analysis of videos without verified dates")
    parser.add_argument("--cookies", choices=("none", "chrome", "firefox", "chromium", "brave"), default="none")
    parser.add_argument("--analyze-top", type=int, default=0, help="Explicitly call Summarize + DeepSeek for top N results; costs API credits")
    parser.add_argument("--model", help="Model used only if --analyze-top is nonzero")
    parser.add_argument("--refresh", action="store_true", help="Re-analyze already processed videos")
    args = parser.parse_args(argv)
    if not (1 <= args.per_query <= 30 and 1 <= args.max_results <= 100
            and 1 <= args.hours <= 8760 and 0 <= args.min_seconds <= 3600
            and 0 <= args.analyze_top <= 10 and 0 <= args.verify_top <= 30):
        parser.error("Invalid query/results/hours/min-seconds/analyze-top setting")
    try:
        if args.fixture:
            sources = [{"topic": "BTC 与加密市场", "query": "fixture"}]
            fixture_data = json.loads(Path(args.fixture).read_text(encoding="utf-8"))
        else:
            sources = json.loads(Path(args.config).read_text(encoding="utf-8"))["queries"]
            if not isinstance(sources, list) or not sources:
                raise ValueError("queries must be a non-empty array")
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2
    now = datetime.now(timezone.utc)
    found: list[Video] = []
    errors: list[str] = []
    succeeded = 0
    for source in sources:
        query = str(source.get("query") or "").strip()
        topic = str(source.get("topic") or "").strip()
        if not query or not topic:
            errors.append("Empty topic or query skipped")
            continue
        try:
            raw = fixture_data if args.fixture else find_videos(query, args.per_query, cookies=args.cookies)
            items = parse_results(raw, topic=topic, query=query, hours=args.hours,
                                  now=now, min_seconds=args.min_seconds)
            succeeded += 1
            found.extend(items)
            print(f"[OK] {topic}: {len(items)} video candidates")
        except (PipelineError, OSError, ValueError, TypeError) as exc:
            errors.append(f"{topic}: {str(exc)[:200]}")
            print(f"[WARN] {errors[-1]}", file=sys.stderr)
    if not succeeded:
        print("[FAIL] All YouTube searches failed; old report preserved.", file=sys.stderr)
        return 1
    # Retain some replacements in case high-ranked search results turn out old.
    videos = merge_videos(found, min(100, args.max_results + args.verify_top))
    if not args.fixture and args.verify_top:
        videos = verify_video_dates(videos, count=args.verify_top,
                                   cookies=args.cookies, hours=args.hours,
                                   now=now, errors=errors)
    videos = videos[:args.max_results]
    output = Path(args.output).expanduser().resolve()
    new_count = remember(output / "seen.db", videos)
    candidates_for_analysis = (
        videos if args.allow_unknown_age else
        [v for v in videos if v.published_at_utc is not None]
    )
    if args.analyze_top and not args.allow_unknown_age and not candidates_for_analysis:
        errors.append("No confirmed recent videos for paid analysis; use --allow-unknown-age to override.")
    analyzed = analyze_selected(candidates_for_analysis, output, args.analyze_top,
                                args.cookies, args.refresh, args.model or "",
                                errors) if args.analyze_top and candidates_for_analysis else []
    render(output, videos, new_count=new_count, errors=errors,
           requested=len(sources), analyzed=analyzed)
    successful = sum(a['status'] in ('analyzed', 'cached') for a in analyzed)
    print(f"[PASS] videos={len(videos)} new={new_count} analyzed={sum(a['status'] == 'analyzed' for a in analyzed)} cached={sum(a['status'] == 'cached' for a in analyzed)}")
    print(f"Report: {output / 'latest.md'}")
    if args.analyze_top and successful == 0:
        print("[WARN] No independent video report was generated; see latest.md for reasons.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
