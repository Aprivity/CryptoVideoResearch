"""Conservative finance term screening for caption/ASR quality control.

A dictionary match is only a spelling candidate, NEVER verified market news or
a calibrated Whisper acoustic confidence. Suspicious aliases are flagged rather
than silently corrected. Original time-coded VTT data are never modified.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

LEXICON = Path(__file__).resolve().parent / "data" / "finance_entities.json"
TIMING = re.compile(r"(?m)^((?:\d{2}:)?\d{2}:\d{2}\.\d{3})\s+-->\s+")
NUMBER_UNITS = re.compile(
    r"(?<![A-Za-z0-9])\d+(?:[,.]\d+)*\s*"
    r"(?:%|％|亿美元|億美元|万美元|萬美元|基点|基點|bps|[GMTP]W|万亿|萬億|亿美元)"
)


@lru_cache(maxsize=1)
def load_lexicon() -> dict:
    data = json.loads(LEXICON.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("entities"), list):
        raise ValueError("Invalid finance_entities.json lexicon")
    return data


def candidate_present(text: str, alias: str) -> bool:
    """Match Latin terms as whole tokens; Chinese phrases as literal substrings."""
    if not alias:
        return False
    escaped = re.escape(alias)
    if re.search(r"[a-zA-Z]", alias):
        return re.search(r"(?<![a-zA-Z0-9])" + escaped + r"(?![a-zA-Z0-9])",
                         text, re.IGNORECASE) is not None
    return alias in text


def vtt_cues(content: str) -> list[tuple[str, str]]:
    """Parse time-coded blocks without counting metadata as spoken words."""
    cues = []
    for block in re.split(r"\n\s*\n", content.replace("\r\n", "\n")):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        for i, line in enumerate(lines):
            timing = TIMING.match(line)
            if timing:
                spoken = " ".join(lines[i + 1:])
                if spoken:
                    cues.append((timing.group(1), spoken))
                break
    return cues


def assess_transcript(transcript: Path, *, subtitle_source: str = "unknown") -> dict:
    """Return bounded, inspectable candidate names and review alerts.

    Does not assign invented Whisper probabilities or rewrite transcript.
    The confidence label describes dictionary *match certainty*, not whether
    a company/news/event actually exists or was named correctly in audio.
    """
    content = transcript.read_text(encoding="utf-8-sig")
    data = load_lexicon()
    cues = vtt_cues(content) if transcript.suffix.lower() == ".vtt" else [("未知", content)]
    is_asr = subtitle_source.startswith("local-asr")
    found = []
    flagged = []
    numbers = []
    seen: set[tuple[str, str]] = set()
    for timestamp, spoken in cues:
        for entity in data["entities"]:
            names = sorted(((a, "candidate") for a in entity["aliases"]), key=lambda p: -len(p[0]))
            suspects = sorted(((a, "suspect") for a in entity["suspect_aliases"]), key=lambda p: -len(p[0]))
            # A single alias per canonical entity/cue avoids redundant matches.
            matched = next(((alias, kind) for alias, kind in [*suspects, *names]
                            if candidate_present(spoken, alias)), None)
            if not matched:
                continue
            alias, kind = matched
            key = (entity["id"], kind)
            if key in seen:
                continue
            seen.add(key)
            item = {
                "canonical": entity["name"], "ticker": entity.get("ticker"),
                "category": entity["type"], "observed": alias,
                "timestamp": timestamp, "match_kind": kind,
                "label": "needs-listening-review" if kind == "suspect"
                         else "lexicon-exact-candidate",
                "lexicon_match_certainty": "low-text-heuristic" if kind == "suspect"
                                           else "exact-spelling-candidate",
            }
            if kind == "suspect":
                flagged.append(item)
            else:
                found.append(item)
        for raw in data.get("uncertain_phrases", []):
            if candidate_present(spoken, raw["term"]):
                key = ("ambiguous:" + raw["term"], "ambiguous")
                if key not in seen:
                    seen.add(key)
                    flagged.append({
                        "observed": raw["term"], "canonical": None,
                        "ticker": None, "timestamp": timestamp,
                        "match_kind": "ambiguous", "label": "needs-listening-review",
                        "reason": raw["reason"],
                    })
        if len(numbers) < 12:
            for match in NUMBER_UNITS.finditer(spoken):
                value = match.group().strip()
                if value not in [row["observed"] for row in numbers]:
                    numbers.append({"observed": value, "timestamp": timestamp,
                                    "label": "source-number-unverified"})
                if len(numbers) >= 12:
                    break
    return {
        "schema_version": "0.8.0", "subtitle_source": subtitle_source,
        "is_asr": is_asr,
        "confidence_meaning": (
            "Dictionary matching and conservative ambiguity heuristics ONLY; "
            "not an ASR acoustic probability, source reliability score, "
            "or independent verification of any event"
        ),
        "recognized_candidates": found[:60],
        "needs_review": flagged[:40],
        "number_mentions_to_check": numbers,
        "verification_status": "unverified",
    }


def context_for_model(review: dict) -> str:
    """Bounded reference hints that must not be treated as original captions."""
    clean = review.get("recognized_candidates", [])[:18]
    uncertain = review.get("needs_review", [])[:12]
    if not clean and not uncertain:
        return ""
    lines = [
        "[自动生成的金融实体词表辅助提示——不是视频原文，也没有外部事实核验]",
        "下列只是候选英文拼写；只有原视频语境支持时才使用。"
        "疑似识别错误需标记“待核对”，不能自动纠正为确定事实。",
    ]
    if clean:
        lines.append("匹配词候选：" + "；".join(
            item["observed"] + " → " + item["canonical"]
            + (" (" + item["ticker"] + ")" if item.get("ticker") else "")
            for item in clean
        ))
    if uncertain:
        lines.append("低确定性识别片段（禁止直接替换）：" + "；".join(
            item["observed"] + "，候选 " + (item.get("canonical") or "未知")
            + "（" + item["timestamp"] + "）"
            for item in uncertain
        ))
    lines += ["[辅助提示结束，以下为原始字幕，时间戳与转写文本未改动]", ""]
    return "\n".join(lines)


def quality_markdown(review: dict, *, max_items: int = 4) -> list[str]:
    """Human-facing warning lines for both reports."""
    result = []
    flags = review.get("needs_review", [])
    if flags:
        details = "；".join(
            f"{item['observed']}（{item['timestamp']}，"
            f"{'疑似 ' + item['canonical'] if item.get('canonical') else '实体不明确'}）"
            for item in flags[:max_items]
        )
        result.append("**低置信度术语（词表启发式，需回听）：**" + details
                      + ("；另有更多见 finance_quality.json" if len(flags) > max_items else ""))
    num = review.get("number_mentions_to_check", [])
    if num:
        result.append("**数字需核对：**" + "、".join(
            f"{item['observed']}（{item['timestamp']}）" for item in num[:3]
        ) + "。以上数值仅来自视频字幕。")
    result.append(
        "**可信度说明：**仅为博主视频及字幕转述，未经外部核验；"
        "词表置信标记是文本匹配启发式，**不代表 Whisper 音频置信度**。"
    )
    return result
