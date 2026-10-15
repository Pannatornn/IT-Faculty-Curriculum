"""Public citation presentation, kept separate from retrieval diagnostics."""
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import quote

from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse


DOCUMENT_NAMES = frozenset({"AIT.pdf", "DSBA.pdf", "IT2565.pdf", "IT_inter2565.pdf"})


async def serve_document(req: Request):
    name = req.path_params["filename"]
    if name not in DOCUMENT_NAMES:
        return JSONResponse({"error": "Document not found"}, status_code=404)
    path = Path(__file__).resolve().parent / "data" / "documents" / name
    if not path.is_file():
        return JSONResponse({"error": "Document not found"}, status_code=404)
    return FileResponse(
        path, media_type="application/pdf", content_disposition_type="inline",
        headers={"Cache-Control": "public, max-age=3600", "X-Content-Type-Options": "nosniff"},
    )


def public_answer(text: str) -> str:
    """Remove a model-echoed retrieval dump without removing prose citations."""
    text = str(text or "").strip()
    markers = list(re.finditer(
        r"^[ \t]*(?:#{1,6}[ \t]*)?(?:\*{1,2})?(?:EVIDENCE|RETRIEVAL DETAILS)"
        r"(?:\*{1,2})?[ \t]*:(?:\*{1,2})?[ \t]*",
        text, re.I | re.M,
    ))
    diagnostics = re.compile(r"\b(?:ID|SOURCE|RETRIEVAL_SCORE|KIND)\s*=", re.I)
    for index, marker in enumerate(markers):
        end = markers[index + 1].start() if index + 1 < len(markers) else len(text)
        if diagnostics.search(text[marker.end():end]):
            return text[:marker.start()].rstrip()
    return text


def source_url(source: str, page: int | None) -> str | None:
    if source not in DOCUMENT_NAMES:
        return None
    return f"/documents/{quote(source)}#page={max(1, int(page or 1))}"


def evidence_excerpt(text: str, question: str, answer: str, limit: int = 440) -> str:
    """Select a bounded verbatim passage around question terms, not an LLM summary."""
    clean = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(clean) <= limit:
        return clean
    keywords = set(re.findall(r"[A-Za-z][A-Za-z-]{3,}", question.casefold()))
    keywords -= {"what", "which", "does", "have", "with", "from", "this", "that", "many", "curriculum", "program"}
    for term in ("หมวดวิชาเฉพาะ", "ศึกษาทั่วไป", "หน่วยกิต", "ภาษาอังกฤษ", "ภาษาไทย", "วิชาเลือก", "อาชีพ", "ความเชี่ยวชาญ", "ปัญญาประดิษฐ์", "深度学习", "学分"):
        if term in question:
            keywords.add(term)
    # The passage that shares the most question terms wins; answer numbers help
    # rank ties but cannot supply or rewrite any source text.
    numbers = set(re.findall(r"\b\d{2,3}\b", public_answer(answer)))
    folded = clean.casefold()
    positions = {0}
    for term in keywords:
        for match in re.finditer(re.escape(term), folded):
            positions.add(max(0, match.start() - 90))
    best_start = max(positions, key=lambda start: (
        sum(3 for term in keywords if term in folded[start:start + limit]),
        sum(1 for number in numbers if number in clean[start:start + limit]),
        -start,
    ))
    # Align to nearby whitespace so the preview doesn't start mid English word.
    if best_start:
        space = clean.rfind(" ", max(0, best_start - 25), best_start + 1)
        if space >= 0:
            best_start = space + 1
    excerpt = clean[best_start:best_start + limit].rstrip()
    return ("…" if best_start else "") + excerpt + ("…" if best_start + limit < len(clean) else "")
