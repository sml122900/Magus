"""도구가 받는 층(floor) 인자(#93). 서버 instructions 규칙 12와 같은 규칙이다.

- 넣을 때: floor를 주면 그 층(공용·'1층'·작업물 id·작업물 제목). 주지 않았으면 작업물이 하나면 그 층, 없으면 공용,
  둘 이상이면 넣지 않고 묻게 한다(서버는 대화를 모르므로 '지금 다루는 작업물'은 Claude가 floor로 넘긴다).
- 찾을 때: floor가 없으면 모든 층에서 찾고, 같은 종류가 여러 층에 있으면 결과마다 층을 적는다.
"""

from __future__ import annotations

import re

from mcp.server.mcpserver.exceptions import ToolError

from magus.floors import COMMON, COMMON_NAME
from magus.store import Floor, Store

# 도구 설명에 붙이는 한 줄(자세한 규칙은 instructions)
FLOOR_PUT = ("floor: 넣을 층(공용·1층·작업물 id). 저자가 말하지 않았으면 이 대화에서 다루는 작업물의 층을 주고, "
             "모르면 비워 둔다(작업물이 하나면 그 층). ")
FLOOR_FIND = "floor를 주면 그 층에서만 찾는다(없으면 모든 층). "


def short(title: str, width: int = 24) -> str:
    title = " ".join(title.split())
    return title if len(title) <= width else title[: width - 1] + "…"


def floors_text(floors: list[Floor]) -> str:
    """'공용 · 1층 「제목」(id) · 2층 …'."""
    return " · ".join(f.label if f.common else f"{f.label} 「{short(f.title)}」({f.id})" for f in floors)


def match_floor(floors: list[Floor], text: str) -> Floor | None:
    """'공용'·'common'·'1층'·작업물 id·작업물 제목(그대로 또는 앞부분이 하나만 맞으면)."""
    raw = " ".join(text.split())
    key = raw.replace(" ", "").lower()
    if key in (COMMON_NAME, COMMON, "공용층"):
        return floors[0]
    if m := re.fullmatch(r"(\d+)층", key):
        return next((f for f in floors if f.number == int(m.group(1)) and not f.common), None)
    if found := next((f for f in floors if f.id == raw), None):
        return found
    norm = [(f, f.title.replace(" ", "").lower()) for f in floors if not f.common]
    exact = [f for f, t in norm if t == key]
    if len(exact) == 1:
        return exact[0]
    starts = [f for f, t in norm if key and t.startswith(key)]
    return starts[0] if len(starts) == 1 else None


def resolve_floor(store: Store, user: str, floor: str | None) -> str:
    """넣을 층의 id. 모르면 ToolError(층 목록과 함께)."""
    floors = store.list_floors(user)
    if floor and floor.strip():
        if found := match_floor(floors, floor):
            return found.id
        raise ToolError(f"'{floor}' 층을 찾지 못했다. 층: {floors_text(floors)}")
    works = [f for f in floors if not f.common]
    if len(works) == 1:
        return works[0].id
    if not works:
        return COMMON
    raise ToolError(
        f"작업물이 {len(works)}개라 어느 층에 넣을지 모른다: {floors_text(floors)}. "
        "이 대화에서 다루는 작업물(마지막으로 본 전체 현황)이면 그 층을 floor로 넘기고, 분명하지 않으면 저자에게 묻는다."
    )


def search_floors(store: Store, user: str, floor: str | None) -> list[str] | None:
    """찾을 층: floor가 없으면 None(모든 층). 있으면 그 층 하나."""
    if not floor or not floor.strip():
        return None
    floors = store.list_floors(user)
    if found := match_floor(floors, floor):
        return [found.id]
    raise ToolError(f"'{floor}' 층을 찾지 못했다. 층: {floors_text(floors)}")


def labels_for(store: Store, user: str, kind: str) -> dict[str, str]:
    """같은 기본 카테고리(kind)가 둘 이상의 층에 있을 때만 {층 id: '1층'}. 하나면 빈 dict(결과에 층을 적지 않는다)."""
    floors = store.list_floors(user)
    if sum(1 for f in floors if kind in f.builtins) < 2:
        return {}
    return {f.id: f.label for f in floors}


def floor_name(store: Store, user: str, floor_id: str) -> str:
    """'공용' 또는 '1층 「제목」'."""
    found = store.get_floor(user, floor_id)
    if found is None:
        return floor_id
    return found.label if found.common else f"{found.label} 「{short(found.title)}」"
