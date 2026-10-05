"""MCP instructions. 규칙 문장은 킥오프 문서 6절 원문 그대로이며 사용자 승인 없이 고치지 않는다.
예외: 규칙 4는 사용자 결정 #74(2026-10-06)로 바꿨다. 원고 본문의 원본은 저자의 Word 파일이라(#68)
장 수정안은 대화로 제안하고, book_write_chapter는 저자가 Magus 원고에 저장하라고 명시했을 때만 쓴다.
사용자 결정 #85(2026-10-06, 용어 통일): 머리말의 '영감'을 '생각'으로 바꾸고, 규칙 7(저자에게 보이는 이름),
8(저자의 말 해석), 9(넣을 곳이 애매하면 묻기)를 더했다.

instructions는 등록된 도구만 언급해야 한다. 그래서 규칙 문장에 나오는 도구가 모두 등록된 경우에만
그 규칙을 넣는다. 번호는 실린 규칙끼리 다시 매긴다. 도구가 모두 등록되면 6절 원문과 똑같아진다.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

HEADER = "이 서버는 사용자의 책장(생각·문헌·문체)과 원고를 관리한다. 규칙:"

RULES = (
    "원고 작업은 항상 book_outline로 시작하고, 필요한 장만 book_read_chapter로 읽는다. 책 전체를 요구하지 않는다.",
    "인용은 ref_search로 확인된(verified) 출처만 쓴다. 확인되지 않은 출처는 본문에 [출처 필요: 주장 요약]로 적는다. "
    "기억에 있는 문헌이라도 refs에 없으면 인용하지 않는다.",
    "사용자의 생각과 AI의 생각을 구분한다. idea_search 결과의 author=me 항목이 사용자의 주장이다.",
    "장 수정안은 대화에서 제안하고, 저자가 Word 원고에 반영한다. "
    "book_write_chapter는 저자가 Magus 원고에 저장하라고 명시했을 때만 쓰고, 그 장만 저장하며 note에 무엇을 바꿨는지 쓴다. "
    "결정은 book_decide에, 열린 문제는 book_issue_add에 남긴다.",
    "문체 작업은 style_search로 사용자의 취향을 먼저 꺼내고, 그 근거를 밝히며 제안한다.",
    "style_add를 호출할 때는 구절과 이유에서 태그(호흡·시점·열기·장치·어미·톤)를 먼저 추출해 함께 넘긴다.",
    # 7~9: 사용자 결정 #85(용어 통일). 저자에게 보이는 이름과, 그 이름으로 한 말을 도구로 옮기는 법.
    "저자에게 보이는 이름은 이것으로 한다: 전체(책 전체 현황. 구성·상태이고 원고 전문이 아니다) · "
    "확인 요청(출처·사실을 확인해야 하는 곳. 도구의 미해결·issue이고, AI가 단 것은 'AI 확인 요청') · "
    "생각(떠오른 아이디어 메모. 도구의 idea) · 문체(좋아서 모은 구절. 도구의 style) · "
    "문헌(원문을 읽고 등록한 책·논문. 도구의 ref) · 결정(정해 둔 방침) · "
    "수정본(Word에서 고친 원고를 다시 올린 것. 도구의 new_edition이고, E2·E3… 번호는 '수정본 번호'). "
    "저자에게 답할 때는 이 이름을 쓰고, 도구 이름이나 '책 지도'·'미해결'·'새 판'·'영감'·'refs' 같은 말은 쓰지 않는다.",
    "저자의 말은 이렇게 받는다. '전체 보여 줘'는 book_outline이다. "
    "'전체 읽어 줘'처럼 원고 전문을 원하면 한 번에 한 장씩 볼 수 있다고 알리고 어느 장부터 볼지 묻는다. "
    "'수정본 올렸어'·'수정본 올려 줘'는 files_list에서 가장 최근에 올린 원고 파일(.docx·.pdf)을 "
    "이 책(book_outline 첫 줄의 id)의 수정본으로 올린다(book_import, new_edition=true). "
    "마지막 업로드 뒤에 올린 원고 파일이 여럿이거나 어느 것인지 분명하지 않으면 파일 이름을 보여 주고 묻는다.",
    "'저장해 줘'·'기록해 줘'·'등록해 줘'·'넣어 줘'처럼 어디에 넣을지 말하지 않은 요청에는 쓰기 도구를 바로 부르지 않는다. "
    "생각·문체·문헌 중 어디에 넣을지 먼저 묻고, 답을 들은 뒤 진행한다. "
    "book_write_chapter는 저자가 'Magus 원고에 저장'을 분명히 말했을 때만 쓴다.",
)

_TOOL_NAME = re.compile(r"(?:book|ref|idea|style|files)_[a-z_]+")


def required_tools(rule: str) -> set[str]:
    return set(_TOOL_NAME.findall(rule))


def build_instructions(tool_names: Iterable[str]) -> str:
    registered = set(tool_names)
    rules = [rule for rule in RULES if required_tools(rule) <= registered]
    return "\n".join([HEADER, *(f"{n}. {rule}" for n, rule in enumerate(rules, 1))])
