"""원고 코멘트 → 미해결 분류. book_import(2단계)가 코멘트를 이슈로 만들 때 쓴다."""

from __future__ import annotations

import re

from magus.melchior.citations import find_citations
from magus.store.base import IssueKind

# 이 표현이 들어 있으면 출처 확인 코멘트로 본다. 공백 차이("확인필요")는 무시한다.
CITATION_MARKERS = ("확인 필요", "인용 확인 필요", "서지", "원문 대조")
_SQUEEZED_MARKERS = tuple(re.sub(r"\s+", "", m) for m in CITATION_MARKERS)


def classify_comment(text: str, anchor: str | None = None) -> tuple[IssueKind, str | None]:
    """(kind, ref_key 후보). ref_key는 코멘트 본문에서 먼저 찾고, 없으면 코멘트가 달린 원문(anchor)에서 찾는다."""
    squeezed = re.sub(r"\s+", "", text)
    if not any(marker in squeezed for marker in _SQUEEZED_MARKERS):
        return "general", None
    for source in (text, anchor or ""):
        if cites := find_citations(source, bare=True):
            return "citation", cites[0].key
    return "citation", None
