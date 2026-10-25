"""Dual-format reports and conservative per-video transcript quality notes.

Use the SAME DeepSeek response for both files; never call a second model. Old
cached reports without a model-written quick section can be backfilled locally
with an explicitly labeled mechanical excerpt, without paid API requests.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .finance_terms import assess_transcript, quality_markdown

QUICK_HEADER = re.compile(r"(?m)^##[ 	]+一分钟速览[ 	]*$")
SECTION_HEADER = re.compile(r"(?m)^##[ 	]+")
BULLET = re.compile(r"(?m)^[-*][ 	]+(.+?)[ 	]*$")
FULL_SECTIONS = ("新闻事件清单", "博主的解释与观点", "视频核心观点", "1. 视频核心观点",
                 "2. 数据与技术指标", "3. 交易策略")


def split_model_report(summary: str) -> tuple[str, list[str], bool]:
    """Extract a model-ranked 3–5-point fast summary from the one full response."""
    match = QUICK_HEADER.search(summary)
    if match is None:
        return summary.strip() + "\n", [], False
    next_heading = SECTION_HEADER.search(summary, match.end())
    stop = next_heading.start() if next_heading else len(summary)
    block = summary[match.end():stop]
    bullets = [x.strip() for x in BULLET.findall(block) if x.strip()]
    # Keep "新闻相关性：" at the top of analysis.md for old classifying code.
    full = (summary[:match.start()].rstrip() + "\n\n"
            + summary[stop:].lstrip()).strip() + "\n"
    # Some videos genuinely have fewer than three usable claims. Keep their
    # model-selected points instead of manufacturing additional claims.
    return full, bullets[:5], bool(bullets)


def legacy_excerpts(full: str) -> list[str]:
    """No invented ranking: extract existing report bullets and mark that fact."""
    sections: dict[str, list[str]] = {}
    current = ""
    for raw in full.splitlines():
        if raw.startswith("## "):
            current = raw[3:].strip()
            continue
        if raw.startswith(("- ", "* ")) and current:
            sections.setdefault(current, []).append(raw[2:].strip())
    chosen: list[str] = []
    for section in FULL_SECTIONS:
        if section not in sections:
            continue
        # Up to 3 events and up to 2 viewpoints for the old report format.
        capacity = 3 if "新闻事件" in section or "核心观点" in section else 2
        for bullet in sections[section][:capacity]:
            if bullet and bullet not in chosen:
                chosen.append(bullet)
            if len(chosen) >= 5:
                return chosen
    return chosen


def quick_markdown(full: str, ranked_bullets: list[str], *, from_model: bool,
                   review: dict) -> str:
    chosen = ranked_bullets if from_model else legacy_excerpts(full)
    # The model can overrun one-minute length. Truncation is explicitly marked
    # instead of silently rewriting numbers or ticker symbols.
    normalized = []
    for bullet in chosen[:5]:
        if len(bullet) > 135:
            bullet = bullet[:132].rstrip() + "…（详情见完整报告）"
        normalized.append(bullet)
    lines = [
        "# 一分钟快速摘要（未经核验）", "",
        "> 内容是视频转述与作者观点，不是已核实新闻或投资建议。", "",
    ]
    if not from_model:
        lines += [
            "> 本摘要从旧报告的原有条目机械摘录，**未经重要性重新排序**；"
            "更新完整报告后可获得模型挑选的 3–5 项重点。", "",
        ]
    if normalized:
        lines += ["## 最重要的事件与观点" if from_model else "## 报告条目摘录", ""]
        for i, item in enumerate(normalized, 1):
            lines.append(f"{i}. {item}")
        lines += [""]
    else:
        lines += ["这份报告没有可可靠摘录的事件／观点条目，请查看完整报告。", ""]
    lines += ["## 术语与可信度提示", ""]
    lines += [f"- {note}" for note in quality_markdown(review)]
    lines += ["", "[查看完整研究报告](analysis.md)", ""]
    return "\n".join(lines)


def quality_section(review: dict) -> str:
    """Append warnings to the full report, without corrupting source quotations."""
    return ("\n## 金融实体与识别质量提示（自动标记，非事实核验）\n\n"
            + "\n".join(f"- {line}" for line in quality_markdown(review)) + "\n")


def atomic_write(path: Path, data: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(data, encoding="utf-8")
    tmp.replace(path)


def create_companions(report: Path, *, summary: str, transcript: Path,
                      subtitle_source: str, preserve_analysis: bool = False) -> dict:
    """Create quick.md and finance_quality.json for new or cached analyses."""
    report.parent.mkdir(parents=True, exist_ok=True)
    full, bullets, from_model = split_model_report(summary)
    if not transcript.is_file():
        # An old report can refer to a missing VTT; do not invent a review.
        review = {
            "schema_version": "0.8.0", "subtitle_source": subtitle_source,
            "is_asr": subtitle_source.startswith("local-asr"),
            "recognized_candidates": [], "needs_review": [],
            "number_mentions_to_check": [], "verification_status": "unverified",
            "warning": "The original transcript was unavailable; no term scan was done.",
        }
    else:
        review = assess_transcript(transcript, subtitle_source=subtitle_source)
    if not preserve_analysis:
        atomic_write(report, full.rstrip() + "\n" + quality_section(review))
    quick = report.parent / "quick.md"
    atomic_write(quick, quick_markdown(full, bullets, from_model=from_model, review=review))
    review_path = report.parent / "finance_quality.json"
    atomic_write(review_path, json.dumps(review, ensure_ascii=False, indent=2) + "\n")
    return {
        "quick_file": str(quick.resolve()),
        "finance_quality_file": str(review_path.resolve()),
        "fast_summary_origin": "model-ranked" if from_model else "legacy-excerpt",
        "financial_candidate_count": len(review["recognized_candidates"]),
        "financial_review_flag_count": len(review["needs_review"]),
        "source_verification_status": "unverified",
        "report_format": "dual-v0.8",
    }


def backfill_cached_report(report: Path) -> dict:
    """Generate missing V0.8 files for cached V0.7 report without any model calls."""
    meta_path = report.parent / "report.json"
    if not report.is_file():
        return {}
    old = {}
    if meta_path.is_file():
        try:
            obj = json.loads(meta_path.read_text(encoding="utf-8"))
            if isinstance(obj, dict):
                old = obj
        except (OSError, json.JSONDecodeError):
            pass
    source = old.get("subtitle_source") or "unknown"
    transcript = Path(old.get("subtitle_file") or (report.parent / "__missing_vtt__"))
    if (report.parent / "quick.md").is_file() and (report.parent / "finance_quality.json").is_file():
        return {
            "quick_file": str((report.parent / "quick.md").resolve()),
            "finance_quality_file": str((report.parent / "finance_quality.json").resolve()),
        }
    # Never overwrite an existing full analysis just to create companions.
    companions = create_companions(
        report, summary=report.read_text(encoding="utf-8"), transcript=transcript,
        subtitle_source=source, preserve_analysis=True,
    )
    if old:
        old.update(companions)
        atomic_write(meta_path, json.dumps(old, ensure_ascii=False, indent=2) + "\n")
    return companions
