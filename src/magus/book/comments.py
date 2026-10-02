"""원고 코멘트 → 미해결 분류. book_import(2단계)가 코멘트를 이슈로 만들 때 쓴다."""

from __future__ import annotations

import re

from magus.melchior.citations import find_citations
from magus.store.base import IssueKind

# 이 표현이 들어 있으면 출처 확인 코멘트로 본다. 공백 차이("확인필요")는 무시한다.
CITATION_MARKERS = ("확인 필요", "인용 확인 필요", "서지", "원문 대조")
_SQUEEZED_MARKERS = tuple(re.sub(r"\s+", "", m) for m in CITATION_MARKERS if m != "서지")
# "서지"는 다른 낱말 속("일어서지", "세우지 않았어서지")에 흔히 들어 있다.
# 앞에 한글이 없고, 뒤가 한글이 아니거나 서지 관련 낱말일 때만 인정한다.
_SEOJI = re.compile(r"(?<![가-힣])서지(?:(?![가-힣])|(?=정보|사항|확인|누락|오류|표기|데이터|학))")


def is_citation_comment(text: str) -> bool:
    squeezed = re.sub(r"\s+", "", text)
    return any(marker in squeezed for marker in _SQUEEZED_MARKERS) or bool(_SEOJI.search(text))


def classify_comment(text: str, anchor: str | None = None) -> tuple[IssueKind, str | None]:
    """(kind, ref_key 후보). ref_key는 코멘트 본문에서 먼저 찾고, 없으면 코멘트가 달린 원문(anchor)에서 찾는다."""
    if not is_citation_comment(text):
        return "general", None
    for source in (text, anchor or ""):
        if cites := find_citations(source, bare=True):
            return "citation", cites[0].key
    return "citation", None
