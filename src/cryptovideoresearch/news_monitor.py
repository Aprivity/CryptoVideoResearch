"""Research-only RSS news intake: one-shot collection, provenance, SQLite de-duplication.

Run: python -m cryptovideoresearch.news_monitor --config news_sources.json
Standard library only; no background process, LLM calls, or trading actions.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sqlite3
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

MAX_FEED_BYTES = 2_000_000
USER_AGENT = "CryptoVideoResearch/0.2 (research RSS reader)"
GOOGLE_NEWS = "https://news.google.com/rss/search"
TRACKERS = {"fbclid", "gclid", "mc_cid", "mc_eid", "ref", "source"}


@dataclass(frozen=True)
class Article:
    fingerprint: str
    topic: str
    source: str
    title: str
    url: str
    published_at_utc: str
    excerpt: str


def _clean(value: str | None) -> str:
    value = html.unescape(value or "")
    value = re.sub(r"<[^>]*>", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _utc(value: str | None) -> str | None:
    if not value:
        return None
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        return None  # Do not invent a publisher timezone.
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def canonical_url(value: str) -> str:
    parts = urlsplit(value.strip())
    if parts.scheme.lower() != "https" or not parts.hostname or parts.username or parts.password:
        raise ValueError("Expected public https article URL")
    if parts.hostname.lower() in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("Local URLs are not news sources")
    query = sorted(
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith("utm_") and k.lower() not in TRACKERS
    )
    return urlunsplit(("https", parts.netloc.lower(), parts.path or "/", urlencode(query), ""))


def feed_url(source: dict) -> str:
    if source.get("type") == "google_news":
        query = str(source.get("query", "")).strip()
        if not query:
            raise ValueError("Google News source needs a query")
        return GOOGLE_NEWS + "?" + urlencode({
            "q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"
        })
    if source.get("type") == "rss":
        return canonical_url(str(source["url"]))
    raise ValueError("Source type must be google_news or rss")


def download(url: str, timeout: int = 15) -> bytes:
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/rss+xml, application/atom+xml, text/xml, application/xml",
    })
    with urllib.request.urlopen(req, timeout=timeout) as response:
        data = response.read(MAX_FEED_BYTES + 1)
    if len(data) > MAX_FEED_BYTES:
        raise ValueError("RSS feed too large")
    return data


def _child_text(node: ET.Element, *tags: str) -> str:
    for tag in tags:
        found = node.find(tag)
        if found is not None and found.text:
            return found.text.strip()
    return ""


def parse_feed(xml: bytes, source: dict) -> list[Article]:
    """Parse RSS 2.0 or Atom, skipping missing/invalid dates conservatively."""
    if len(xml) > MAX_FEED_BYTES:
        raise ValueError("RSS feed too large")
    root = ET.fromstring(xml)
    articles: list[Article] = []
    rss_items = root.findall("./channel/item")
    is_atom = not rss_items and root.tag.endswith("}feed")
    if is_atom:
        entries = root.findall("{http://www.w3.org/2005/Atom}entry")
    else:
        entries = rss_items
    for item in entries[: min(int(source.get("limit", 25)), 100)]:
        if is_atom:
            ns = "{http://www.w3.org/2005/Atom}"
            title = _clean(_child_text(item, ns + "title"))
            link = ""
            for el in item.findall(ns + "link"):
                if el.attrib.get("rel", "alternate") == "alternate":
                    link = el.attrib.get("href", "")
                    break
            when = _utc(_child_text(item, ns + "published", ns + "updated"))
            excerpt = _clean(_child_text(item, ns + "summary"))
        else:
            title = _clean(_child_text(item, "title"))
            link = _child_text(item, "link")
            when = _utc(_child_text(item, "pubDate", "{http://purl.org/dc/elements/1.1/}date"))
            excerpt = _clean(_child_text(item, "description"))
        if not title or not link or not when:
            continue
        try:
            clean_url = canonical_url(link)
        except ValueError:
            continue
        norm_title = re.sub(r"[^\w\u4e00-\u9fff]+", "", title.casefold())
        key = (norm_title + "|" + when[:10]).encode("utf-8")
        articles.append(Article(
            fingerprint=hashlib.sha256(key).hexdigest(),
            topic=str(source["topic"]), source=str(source["name"]),
            title=title[:300], url=clean_url, published_at_utc=when,
            excerpt=excerpt[:500],
        ))
    return articles


def _db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("""CREATE TABLE IF NOT EXISTS articles (
        fingerprint TEXT PRIMARY KEY,
        topic TEXT NOT NULL,
        source TEXT NOT NULL,
        title TEXT NOT NULL,
        url TEXT NOT NULL,
        published_at_utc TEXT NOT NULL,
        excerpt TEXT NOT NULL,
        first_seen_utc TEXT NOT NULL
    )""")
    return conn


def save_articles(db_path: Path, articles: list[Article]) -> int:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    added = 0
    with _db(db_path) as db:
        for article in articles:
            cur = db.execute("""INSERT OR IGNORE INTO articles VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                             (*asdict(article).values(), now))
            added += cur.rowcount
    return added


def recent_articles(db_path: Path, cutoff_utc: str, limit: int = 100) -> list[Article]:
    with _db(db_path) as db:
        rows = db.execute("""SELECT fingerprint, topic, source, title, url,
              published_at_utc, excerpt FROM articles
              WHERE published_at_utc >= ? ORDER BY published_at_utc DESC LIMIT ?""",
              (cutoff_utc, limit)).fetchall()
    return [Article(*row) for row in rows]


def _md(value: str) -> str:
    return value.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]").replace("\n", " ")


def write_brief(output: Path, items: list[Article], counts: dict, errors: list[str],
                hours: int, now: datetime) -> None:
    output.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "0.2.0-news-preview",
        "generated_at_utc": now.isoformat(timespec="seconds"),
        "lookback_hours": hours, "counts": counts,
        "feed_errors": errors, "items": [asdict(it) for it in items],
        "verification_status": "headline-only-unverified",
        "disclaimer": "Research index only; no investment advice or trade signals.",
    }
    (output / "latest.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# 市场新闻线索（非事实核验）", "",
             f"生成时间（UTC）：{payload['generated_at_utc']}",
             f"检索窗口：最近 {hours} 小时｜本轮新增：{counts['new']} 条｜库内窗口条目：{len(items)} 条", "",
             "> 本文件仅整理 RSS 标题、发布时间、来源及原始链接；未核查正文和事件因果。不是投资建议。", ""]
    for topic in sorted({it.topic for it in items}):
        lines.extend([f"## {topic}", ""])
        for article in (a for a in items if a.topic == topic):
            lines.append(f"- [{_md(article.title)}]({article.url})  ")
            lines.append(f"  来源：{_md(article.source)}｜发布（UTC）：{article.published_at_utc}")
        lines.append("")
    if not items:
        lines.extend(["暂无符合时间窗口且带可靠发布时间的新闻条目。", ""])
    if errors:
        lines.extend(["## 数据源失败（未静默忽略）", ""])
        lines.extend(f"- {_md(err)}" for err in errors)
        lines.append("")
    (output / "latest.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="RSS news discovery, offline fixture supported; no LLM")
    parser.add_argument("--config", default="news_sources.json")
    parser.add_argument("--output", default="outputs/news")
    parser.add_argument("--hours", type=int, default=72)
    parser.add_argument("--limit", type=int, default=100, help="Maximum saved headlines in brief")
    parser.add_argument("--fixture", help="Read a local RSS XML fixture instead of making network calls")
    args = parser.parse_args(argv)
    if not 1 <= args.hours <= 1_000_000 or not 1 <= args.limit <= 1000:
        parser.error("--hours must be 1..1000000 and --limit 1..1000")
    try:
        if args.fixture:
            sources = [{"name": "OFFLINE FIXTURE", "topic": "demo", "limit": 100}]
            fixtures = Path(args.fixture).read_bytes()
        else:
            cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
            sources = cfg["sources"]
            if not isinstance(sources, list) or not sources:
                raise ValueError("sources must be a non-empty list")
    except (OSError, KeyError, json.JSONDecodeError, ValueError) as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(hours=args.hours)).isoformat(timespec="seconds")
    gathered: list[Article] = []
    errors: list[str] = []
    worked = 0
    for source in sources:
        name = str(source.get("name", "unknown"))
        try:
            raw = fixtures if args.fixture else download(feed_url(source))
            parsed = parse_feed(raw, source)
            kept = [a for a in parsed if cutoff <= a.published_at_utc <= now.isoformat(timespec="seconds")]
            gathered.extend(kept)
            worked += 1
            print(f"[OK] {name}: {len(kept)} news items in time window")
        except (OSError, ValueError, KeyError, ET.ParseError, urllib.error.URLError) as exc:
            errors.append(f"{name}: {str(exc)[:160]}")
            print(f"[WARN] {errors[-1]}", file=sys.stderr)
    if not worked:
        print("[FAIL] All feeds failed; previous reports are preserved.", file=sys.stderr)
        return 1
    output = Path(args.output).expanduser()
    new_count = save_articles(output / "news.db", gathered)
    recent = recent_articles(output / "news.db", cutoff, args.limit)
    write_brief(output, recent, {"fetched": len(gathered), "new": new_count,
                                  "feed_success": worked, "feed_failure": len(errors)},
                errors, args.hours, now)
    print(f"[PASS] added={new_count}, recent={len(recent)}, feed_failures={len(errors)}")
    print(f"Report: {output / 'latest.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
