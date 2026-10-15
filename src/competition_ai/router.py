from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

from .models import RouteResult


def load_catalog(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    text = text.replace("\u200b", "").replace("\ufeff", "")
    return re.sub(r"\s+", " ", text).strip().casefold()


def _token_hit(question: str, token: str) -> bool:
    q = _norm(question)
    t = _norm(token)
    return bool(
        re.search(
            rf"(?<![A-Za-z0-9_]){re.escape(t)}(?![A-Za-z0-9_])",
            q,
            flags=re.I,
        )
    )


def _alias_hit(question: str, alias: str) -> bool:
    q = _norm(question)
    a = _norm(alias)
    if a in {"it", "ait", "dsba", "bit"}:
        return _token_hit(q, a)
    return a in q


# The faculty's name contains the IT degree's aliases. Remove the institution
# name as a phrase before finding degree names, while retaining any separate
# mention of IT, IT2565, or IT International elsewhere in the question.
_FACULTY_NAME_RE = re.compile(
    r"(?:"
    r"คณะ\s*(?:เทคโนโลยีสารสนเทศ|it(?![a-z0-9_]))|"
    r"(?<![a-z0-9_])(?:faculty|school)\s+of\s+(?:information\s+technology|it)(?![a-z0-9_])|"
    r"(?<![a-z0-9_])(?:information\s+technology|it)\s+(?:faculty|school)(?![a-z0-9_])|"
    r"(?:信息技术|信息科技|資訊科技)(?:\s*[（(]\s*it\s*[）)])?\s*[学學]院|"
    r"(?<![a-z0-9_])it\s*[学學]院"
    r")"
    r"(?:\s*[（(]\s*(?:it|information\s+technology|เทคโนโลยีสารสนเทศ)\s*[）)])?",
    re.I,
)


_EXPLICIT_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "IT_INTER",
        (
            r"(?<![A-Za-z0-9_])it[\s_-]*(?:inter|international)(?![A-Za-z0-9_])",
            r"(?<![A-Za-z0-9_])bit(?![A-Za-z0-9_])",
            r"เทคโนโลยีสารสนเทศทางธุรกิจ",
            r"business\s+information\s+technology",
        ),
    ),
    (
        "AIT",
        (
            r"(?<![A-Za-z0-9_])ait(?![A-Za-z0-9_])",
            r"เทคโนโลยีปัญญาประดิษฐ์",
            r"artificial\s+intelligence\s+technology",
            r"人工智能技术",
        ),
    ),
    (
        "DSBA",
        (
            r"(?<![A-Za-z0-9_])dsba(?![A-Za-z0-9_])",
            r"วิทยาการข้อมูลและการวิเคราะห์เชิงธุรกิจ",
            r"data\s+science\s+and\s+business\s+analytics",
            r"数据科学",
        ),
    ),
    (
        "IT",
        (
            # Organizer benchmark uses the compact token IT2565 in both Thai
            # and Chinese questions. Match it before the plain IT boundary rule.
            r"(?<![A-Za-z0-9_])it[\s_-]*2565(?![A-Za-z0-9_])",
            r"(?<![A-Za-z0-9_])it(?![A-Za-z0-9_])",
            r"หลักสูตร\s*it(?:[\s_-]*2565)?(?:\s|$)",
            r"สาขาวิชาเทคโนโลยีสารสนเทศ",
            r"bachelor\s+of\s+science\s+program\s+in\s+information\s+technology",
        ),
    ),
)


def detect_programs(question: str, catalog: dict) -> list[str]:
    q = _FACULTY_NAME_RE.sub(" ", _norm(question))
    hits: list[str] = []

    for code, patterns in _EXPLICIT_PATTERNS:
        if any(re.search(p, q, flags=re.I) for p in patterns):
            hits.append(code)

    for code in ("IT_INTER", "AIT", "DSBA", "IT"):
        if code in hits or code not in catalog:
            continue
        if any(_alias_hit(q, alias) for alias in catalog[code].get("aliases", [])):
            hits.append(code)

    if "IT_INTER" in hits and "IT" in hits:
        explicit_plain_it = bool(
            re.search(
                # Test each IT occurrence. An international-program mention
                # elsewhere must not erase a separate plain IT in a comparison.
                r"(?<![A-Za-z0-9_])it(?:[\s_-]*2565)?(?![A-Za-z0-9_])"
                r"(?![\s_-]*(?:inter|international)(?![A-Za-z0-9_]))",
                q,
            )
        )
        if not explicit_plain_it:
            hits.remove("IT")

    order = ["IT_INTER", "AIT", "DSBA", "IT"]
    return [code for code in order if code in hits]


def route_question(
    question: str,
    catalog: dict,
    forced_program: str | None = None,
    available_programs: list[str] | None = None,
) -> RouteResult:
    if forced_program and forced_program != "AUTO":
        return RouteResult([forced_program], reason="ผู้ใช้กำหนดบริบทหลักสูตร")

    hits = detect_programs(question, catalog)

    comparison_words = [
        "เปรียบเทียบ", "ต่างกัน", "แตกต่าง", "เทียบ", "กับ",
        "มากกว่า", "น้อยกว่า", "หลักสูตรไหน", "which",
        "compare", "difference", "vs", "versus", "比较", "区别",
    ]
    q = _norm(question)
    comparison = any(w.casefold() in q for w in comparison_words)

    if hits:
        return RouteResult(
            programs=hits,
            comparison=(comparison or len(hits) > 1),
            reason="ตรวจพบชื่อ รหัส หรือ alias ของหลักสูตร",
        )

    available = available_programs or list(catalog.keys())

    if len(available) == 1:
        return RouteResult(available, reason="มีหลักสูตรเดียวในบริบท")

    if comparison:
        return RouteResult(
            available,
            comparison=True,
            reason="คำถามเปรียบเทียบโดยไม่ระบุชื่อหลักสูตร",
        )

    return RouteResult(
        [],
        ambiguous=True,
        reason="ไม่สามารถระบุหลักสูตรจากคำถามได้",
    )
