"""Remove echoed retrieval diagnostics while retaining natural evidence prose."""
from __future__ import annotations

import re


def public_answer(text: str) -> str:
    text = str(text or "").strip()
    # Entry syntax survives translated headings and translated metadata labels.
    dump = re.search(r"^[ \t]*(?:[-*][ \t]+)?\[E\d+\][ \t]+ID\s*=", text, re.I | re.M)
    if dump:
        prefix = text[:dump.start()].rstrip()
        last_line = prefix.rsplit("\n", 1)[-1]
        if len(last_line) <= 80 and re.fullmatch(
            r"[ \t]*(?:#{1,6}[ \t]*)?(?:\*{1,2})?[^\n:：]+[:：](?:\*{1,2})?[ \t]*",
            last_line,
        ):
            prefix = prefix[:len(prefix) - len(last_line)].rstrip()
        text = prefix
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
