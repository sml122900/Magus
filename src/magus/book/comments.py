"""원고 코멘트 → 미해결 분류. book_import가 코멘트를 이슈로 만들 때 쓴다.

kind
- citation: 출처 확인 코멘트이고 문헌이 지목된 것(코멘트 본문이나, 인용이 하나뿐인 앵커에서 저자·연도를 찾음)
- fact: 출처 확인 코멘트지만 문헌이 지목되지 않은 것(사실·수치 확인 요청). 인용처럼 보인 것이 모두 프로젝트의
  비인용 용어(지명·사건)여도 fact다. "확인 필요"가 붙어 있으면 무엇이든 확인 요청이다(사용자 결정 #36: I46 → fact).
- general: 확인 요청이 아닌 코멘트(작업 안내, 검토 메모 등).

출처 확인 표현: "확인 필요", "인용 확인 필요", "서지", "원문 대조"와 그 실제 변형
("확인필요", "확인할 필요", "원문과 대조해", "원문으로 대조해" — 실원고 코멘트에서 확인).
"""

from __future__ import annotations

import re

from magus.melchior.citations import Citation, find_citations
from magus.store.base import IssueKind

CITATION_MARKERS = ("확인 필요", "인용 확인 필요", "서지", "원문 대조")
_MARKER = re.compile(
    r"확인\s*(?:할|이)?\s*필요"  # 확인 필요 · 확인필요 · 확인할 필요 · 인용 확인 필요
    r"|원문\s*(?:과|으로|을|의\s*표현을)?\s*대조"  # 원문 대조 · 원문과 대조해 · 원문으로 대조해
)
# "서지"는 다른 낱말 속("일어서지")에 흔히 들어 있다. 앞에 한글이 없고, 뒤가 한글이 아니거나 서지 관련 낱말일 때만 인정한다.
_SEOJI = re.compile(r"(?<![가-힣])서지(?:(?![가-힣])|(?=정보|사항|확인|누락|오류|표기|데이터|학))")
COMMENT_ANCHOR_SPLIT = "\n— 원문: "
NO_TERMS: frozenset[str] = frozenset()


def is_citation_comment(text: str) -> bool:
    return bool(_MARKER.search(text) or _SEOJI.search(text))


def comment_citation(text: str, anchor: str | None = None, exclude: frozenset[str] = NO_TERMS) -> Citation | None:
    """코멘트가 가리키는 인용. 코멘트 본문에서 먼저 찾고, 없으면 앵커(코멘트가 달린 원문)에서 찾는다.
    앵커에서는 서로 다른 인용이 하나뿐일 때만 쓴다. 앵커가 문단 전체라 인용이 여럿이면 어느 것인지 알 수 없다."""
    if cites := find_citations(text, bare=True, exclude=exclude):
        return cites[0]
    cites = find_citations(anchor or "", bare=True, exclude=exclude)
    return cites[0] if len({c.key for c in cites}) == 1 else None


def classify_comment(
    text: str, anchor: str | None = None, exclude: frozenset[str] = NO_TERMS
) -> tuple[IssueKind, str | None]:
    """(kind, ref_key 후보)."""
    if not is_citation_comment(text):
        return "general", None
    if cite := comment_citation(text, anchor, exclude):
        return "citation", cite.key
    return "fact", None
