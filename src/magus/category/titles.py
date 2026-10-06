"""항목 제목(#92): 생각과 저자의 카테고리 항목에 붙이는 선택 제목. 저자가 직접 짓거나, AI에게 짓게 하거나, 비워 둔다.

저자가 제목을 말하지 않았을 때는 저자의 기본값(shelf/settings.json의 title_default)을 따른다.
- ask(기본): 저장하지 않고 "먼저 묻는다"는 오류를 돌려준다. 대화 메모리에 기대지 않고 서버가 매번 지킨다.
- ai: 저장하지 않고 "제목을 지어 다시 부른다"는 오류를 돌려준다(서버는 글을 짓지 않는다).
- none: 제목 없이 저장한다.
AI가 지은 제목은 title_by=ai로 남기고 화면에 'AI가 지은 제목'으로 보인다(문체 태그의 tags_by와 같은 방식).
제목을 넣을 때는 title_by(author|ai)를 반드시 받는다. 기본값으로 AI를 넣지 않는다: 저자가 지은 제목이 AI 것으로 기록되지 않게(#92-e).
"""

from __future__ import annotations

from typing import Literal

from mcp.server.mcpserver.exceptions import ToolError

from magus.category.rules import TITLE_MAX, TITLE_MODES
from magus.store import Store
from magus.store.formats import one_line

TITLE_RULE = (
    "제목: 제목을 넣을 때는 title_by를 반드시 함께 준다(저자가 말한 제목이면 author, Claude가 지었으면 ai). "
    "저자가 제목을 말하지 않았으면 저장하기 전에 직접 지을지·지어 드릴지·비워 둘지 묻는다"
    "(저자의 제목 기본값이 정해져 있으면 묻지 않고 따른다. category_list에 보인다). 비워 두기로 했으면 untitled=true. "
    "저자가 '앞으로는 …'이라고 정하면 category_title_default로 기본값을 저장한다. "
)
NEED_BY = ("제목을 넣을 때는 title_by를 함께 준다: 저자가 말한 제목이면 author, Claude가 지었으면 ai. "
           "기본값은 없다(저자가 지은 제목이 AI 것으로, 또는 그 반대로 기록되지 않게). 저장하지 않았다.")
ASK_TITLE = (
    "제목을 정하지 않아 저장하지 않았다. 저자의 제목 기본값은 '매번 묻기'다. 저자에게 제목을 직접 지을지, 지어 드릴지, 비워 둘지 묻고 "
    "답을 들은 뒤 다시 부른다(직접 → title과 title_by=author, 지어 드림 → title과 title_by=ai, 비워 둠 → untitled=true). "
    "저자가 '앞으로는 …'이라고 정하면 category_title_default로 기본값을 저장한다."
)
MAKE_TITLE = "제목을 정하지 않아 저장하지 않았다. 저자의 제목 기본값은 'AI가 짓기'다. 내용에 맞는 짧은 제목을 지어 title과 title_by=ai로 다시 부른다."


def decide_title(
    store: Store, user_id: str, title: str | None, title_by: Literal["ai", "author"] | None, untitled: bool
) -> tuple[str | None, Literal["ai", "author"] | None, str]:
    """(제목, 누가 지었나, 응답에 붙일 말). 저장하지 말아야 하면 ToolError(누가 지었는지 없음, 기본값이 묻기·AI가 짓기)."""
    clean = one_line(title or "")[:TITLE_MAX]
    if clean:
        if title_by not in ("ai", "author"):
            raise ToolError(NEED_BY)
        return clean, title_by, f"제목 「{clean}」" + (" (AI가 지은 제목)" if title_by == "ai" else "")
    if untitled:
        return None, None, "제목 없음"
    mode = store.get_shelf_settings(user_id).title_default
    if mode == "none":
        return None, None, f"제목 없음(저자의 제목 기본값: {TITLE_MODES['none']})"
    raise ToolError(MAKE_TITLE if mode == "ai" else ASK_TITLE)
