"""도구가 받는 프로젝트(project) 인자(#95, 옛 floor 인자 #93). 서버 instructions의 프로젝트 규칙과 같은 규칙이다.

- 넣을 때: project를 주면 그 프로젝트(「내 서재」·프로젝트 id·제목). 주지 않았으면 프로젝트가 하나면 그것, 없으면 「내 서재」,
  둘 이상이면 넣지 않고 묻게 한다(서버는 대화를 모르므로 '지금 다루는 프로젝트'는 Claude가 project로 넘긴다).
- 책(#96)은 이름으로 가리킨다. 같은 이름이 여러 프로젝트에 있으면 project(그 프로젝트, 그다음 연결 노드가 가리키는 책)로 가린다.
- 찾을 때: project가 없으면 모든 프로젝트에서 찾는다(있으면 그 프로젝트와 연결 노드가 가리키는 프로젝트).
"""

from __future__ import annotations

from mcp.server.mcpserver.exceptions import ToolError

from magus.floors import COMMON
from magus.maps import LIBRARY, LIBRARY_NAME
from magus.store import Floor, Ref, Store

_LIBRARY_WORDS = {"내서재", COMMON, "공용", "공용층", "library"}


def short(title: str, width: int = 24) -> str:
    title = " ".join(title.split())
    return title if len(title) <= width else title[: width - 1] + "…"


def projects_text(floors: list[Floor]) -> str:
    """'내 서재 · 「제목」(id) · …'."""
    return " · ".join(LIBRARY_NAME if f.common else f"「{short(f.title)}」({f.id})" for f in floors)


def match_project(floors: list[Floor], text: str) -> Floor | None:
    """'내 서재'·프로젝트 id·제목(그대로 또는 앞부분이 하나만 맞으면). 옛 이름 '공용'도 받는다."""
    raw = " ".join(text.split()).strip("「」")
    key = raw.replace(" ", "").lower()
    if key in _LIBRARY_WORDS:
        return next((f for f in floors if f.common), None)
    if found := next((f for f in floors if f.id == raw), None):
        return found
    norm = [(f, f.title.replace(" ", "").lower()) for f in floors if not f.common]
    exact = [f for f, t in norm if t == key]
    if len(exact) == 1:
        return exact[0]
    starts = [f for f, t in norm if key and t.startswith(key)]
    return starts[0] if len(starts) == 1 else None


def find_project(store: Store, user: str, project: str) -> Floor:
    floors = store.list_floors(user)
    if found := match_project(floors, project):
        return found
    raise ToolError(f"'{project}' 프로젝트를 찾지 못했다. 프로젝트: {projects_text(floors)}")


def resolve_project(store: Store, user: str, project: str | None) -> str:
    """넣을 프로젝트의 id. 모르면 ToolError(프로젝트 목록과 함께)."""
    if project and project.strip():
        return find_project(store, user, project).id
    floors = store.list_floors(user)
    works = [f for f in floors if not f.common]
    if len(works) == 1:
        return works[0].id
    if not works:
        return LIBRARY
    raise ToolError(
        f"프로젝트가 {len(works)}개라 어디에 넣을지 모른다: {projects_text(floors)}. "
        "이 대화에서 다루는 프로젝트(마지막으로 본 전체 현황)면 그것을 project로 넘기고, 분명하지 않으면 저자에게 묻는다."
    )


def search_projects(store: Store, user: str, project: str | None) -> list[str] | None:
    """찾을 프로젝트: project가 없으면 None(모두). 있으면 그 프로젝트와, 지도의 연결 노드가 가리키는 프로젝트."""
    if not project or not project.strip():
        return None
    floor = find_project(store, user, project).id
    found = store.get_map(user, floor)
    linked = [n.link[0] for n in (found.nodes if found else ()) if n.link and not n.missing]
    return list(dict.fromkeys([floor, *linked]))


def floor_name(store: Store, user: str, floor_id: str) -> str:
    """'「내 서재」' 또는 '「제목」'."""
    found = store.get_floor(user, floor_id)
    return f"「{short(found.title)}」" if found else floor_id


def shared_reason(store: Store, user: str, before: str | None, now: str) -> str:
    """두 프로젝트가 같은 문헌을 쓰게 되어 「내 서재」로 옮길 때 남기는 이유(#93-a, #95)."""
    names = [floor_name(store, user, f) for f in dict.fromkeys(f for f in (before, now) if f and f != LIBRARY)]
    return f"{'·'.join(names)} 올린 문서가 함께 쓰는 문헌이라 「{LIBRARY_NAME}」로 옮김"


def share_ref(store: Store, user: str, key: str, before: str | None, now: str) -> Ref:
    """두 프로젝트가 함께 쓰게 된 문헌을 「내 서재」의 문헌 책(없으면 「참고문헌」을 만든다)으로 옮기고, 두 프로젝트 지도에
    그 책이 꽂힌 노드로 가는 연결 노드를 붙인다(없을 때만). 그래서 두 원고의 인용 점검 모두 그 문헌을 본다(#95, #96: 책 단위)."""
    book = store.source_book(user, LIBRARY, create=True)
    assert book is not None
    ref = store.set_ref_book(user, key, book, shared_reason(store, user, before, now))
    for floor in dict.fromkeys(f for f in (before, now) if f):
        store.ensure_link(user, floor, LIBRARY, book)
    return ref


def needs_share(store: Store, user: str, ref_floor: str | None, floor: str) -> bool:
    """이 프로젝트(floor) 원고의 인용 점검이 그 문헌을 보지 못하나(다른 프로젝트에만 있나)."""
    return bool(ref_floor) and ref_floor not in store.cite_scope(user, floor)
