"""MCP instructions. 규칙 문장은 킥오프 문서 6절 원문 그대로이며 고치지 않는다.

instructions는 등록된 도구만 언급해야 한다. 그래서 규칙 문장에 나오는 도구가 모두 등록된 경우에만
그 규칙을 넣는다. 번호는 실린 규칙끼리 다시 매긴다. 도구가 모두 등록되면 6절 원문과 똑같아진다.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

HEADER = "이 서버는 사용자의 책장(영감·문헌·문체)과 원고를 관리한다. 규칙:"

RULES = (
    "원고 작업은 항상 book_outline로 시작하고, 필요한 장만 book_read_chapter로 읽는다. 책 전체를 요구하지 않는다.",
    "인용은 ref_search로 확인된(verified) 출처만 쓴다. 확인되지 않은 출처는 본문에 [출처 필요: 주장 요약]로 적는다. "
    "기억에 있는 문헌이라도 refs에 없으면 인용하지 않는다.",
    "사용자의 생각과 AI의 생각을 구분한다. idea_search 결과의 author=me 항목이 사용자의 주장이다.",
    "장을 고치면 book_write_chapter로 그 장만 저장하고 note에 무엇을 바꿨는지 쓴다. "
    "결정은 book_decide에, 열린 문제는 book_issue_add에 남긴다.",
    "문체 작업은 style_search로 사용자의 취향을 먼저 꺼내고, 그 근거를 밝히며 제안한다.",
    "style_add를 호출할 때는 구절과 이유에서 태그(호흡·시점·열기·장치·어미·톤)를 먼저 추출해 함께 넘긴다.",
)

_TOOL_NAME = re.compile(r"(?:book|ref|idea|style)_[a-z_]+")


def required_tools(rule: str) -> set[str]:
    return set(_TOOL_NAME.findall(rule))


def build_instructions(tool_names: Iterable[str]) -> str:
    registered = set(tool_names)
    rules = [rule for rule in RULES if required_tools(rule) <= registered]
    return "\n".join([HEADER, *(f"{n}. {rule}" for n, rule in enumerate(rules, 1))])
