"""원고 코멘트 → 미해결 분류. book_import가 코멘트를 이슈로 만들 때 쓴다.

kind
- citation: 출처 확인 코멘트이고 문헌이 지목된 것(코멘트 본문이나, 인용이 하나뿐인 앵커에서 저자·연도를 찾음)
- fact: 출처 확인 코멘트지만 문헌이 지목되지 않은 것(사실·수치 확인 요청). 인용처럼 보인 것이 모두 프로젝트의
  비인용 용어(지명·사건)여도 fact다. "확인 필요"가 붙어 있으면 무엇이든 확인 요청이다(사용자 결정 #36: I46 → fact).
- general: 확인 요청이 아닌 코멘트(작업 안내, 검토 메모 등).

출처 확인 표현: "확인 필요", "인용 확인 필요", "서지", "원문 대조"와 그 실제 변형
("확인필요", "확인할 필요", "원문과 대조해", "원문으로 대조해" — 실원고 코멘트에서 확인).
태그(#72, 최신본): [점검·인용]·[점검·서지]는 출처 확인, [점검·통계|수치|연도|사실|사례|계산]은 fact다. 태그가 표현보다 먼저다.
"""

from __future__ import annotations

import hashlib
import re

from magus.melchior.citations import Citation, find_citations
from magus.store.base import AuthorKind, Issue, IssueKind

CITATION_MARKERS = ("확인 필요", "인용 확인 필요", "서지", "원문 대조")
_MARKER = re.compile(
    r"확인\s*(?:할|이)?\s*필요"  # 확인 필요 · 확인필요 · 확인할 필요 · 인용 확인 필요
    r"|원문\s*(?:과|으로|을|의\s*표현을)?\s*대조"  # 원문 대조 · 원문과 대조해 · 원문으로 대조해
)
# "서지"는 다른 낱말 속("일어서지")에 흔히 들어 있다. 앞에 한글이 없고, 뒤가 한글이 아니거나 서지 관련 낱말일 때만 인정한다.
_SEOJI = re.compile(r"(?<![가-힣])서지(?:(?![가-힣])|(?=정보|사항|확인|누락|오류|표기|데이터|학))")
# 최신본 코멘트의 태그: "[점검·인용] …", "[점검·통계] …". "확인 필요"가 없어도 확인 요청이다(#72).
# 인용·서지는 출처 확인(문헌이 지목되면 citation, 아니면 fact), 나머지 여섯은 사실·수치 확인(fact).
# 모르는 태그([점검·표현] 등)와 [사진]은 지금처럼 본문의 표현으로 가른다.
_CHECK_TAG = re.compile(r"^\s*\[\s*점검\s*[·・.‧ ]\s*(?P<what>[^\]\s]{1,8})\s*\]")
CHECK_SOURCE = frozenset({"인용", "서지"})
CHECK_FACT = frozenset({"통계", "수치", "연도", "사실", "사례", "계산"})
COMMENT_ANCHOR_SPLIT = "\n— 원문: "
NO_TERMS: frozenset[str] = frozenset()


# 이 이름(또는 이 이름이 낱말로 든 이름)으로 단 코멘트는 AI의 확인 요청이다(#71). 프로젝트의 book/ai_authors.txt로 더한다.
AI_AUTHOR_NAMES = (
    "claude", "클로드", "anthropic", "chatgpt", "gpt", "openai", "챗지피티", "copilot", "코파일럿", "gemini", "제미나이",
    "bard", "perplexity", "clova", "클로바", "wrtn", "뤼튼", "ai", "magus",
)


def author_kind(author: str | None, extra: list[str] | tuple[str, ...] = ()) -> AuthorKind | None:
    """코멘트 작성자 → ai | person. 이름이 없으면(PDF 말풍선 등) None."""
    name = (author or "").strip().lower()
    if not name:
        return None
    names = {n.strip().lower() for n in (*AI_AUTHOR_NAMES, *extra) if n.strip()}
    words = set(re.findall(r"[a-z0-9]+|[가-힣]+", name))
    return "ai" if name in names or words & names else "person"


def comment_fingerprint(author: str | None, date: str | None, text: str) -> str:
    """같은 Word 코멘트인지 가리는 지문(#76): 작성자 + 날짜 + 본문(공백 정리). Word의 코멘트 id는 저장할 때마다
    다시 매겨질 수 있어 쓰지 않는다. 다시 올릴 때 이 지문이 같으면 새 미해결을 만들지 않는다."""
    raw = "\x1f".join([(author or "").strip(), (date or "").strip(), " ".join((text or "").split())])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def source_label(issue: Issue) -> str:
    """미해결이 어디서 왔는지 사람이 읽는 말로. AI가 단 코멘트는 'AI 확인 요청'으로 드러낸다(#71)."""
    if issue.origin != "import_comment":
        return issue.origin
    who = f"({issue.author})" if issue.author else ""
    return f"AI 확인 요청{who}" if issue.by_ai else f"원고 코멘트{who}"


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
    if m := _CHECK_TAG.match(text):  # [점검·수치] 같은 태그가 무엇을 확인하라는지 먼저 본다(#72)
        if m.group("what") in CHECK_SOURCE:
            cite = comment_citation(text, anchor, exclude)
            return ("citation", cite.key) if cite else ("fact", None)
        if m.group("what") in CHECK_FACT:
            return "fact", None
    if not is_citation_comment(text):
        return "general", None
    if cite := comment_citation(text, anchor, exclude):
        return "citation", cite.key
    return "fact", None
