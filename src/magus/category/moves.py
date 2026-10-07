"""책 옮기기·되돌리기와 지도 바꾸기(#93 → #95). 도구(category_*)와 웹 지도가 함께 쓴다.

- 책은 노드에 꽂힌다. 같은 프로젝트 안에서는 노드만 바꾸고, 다른 프로젝트로 옮기면 항목이 모두 함께 간다
  (받는 프로젝트에 같은 기본 책이 있으면 합친다, 같은 이름의 저자 카테고리가 있으면 옮기지 않는다). 마지막 옮기기 하나는 되돌린다.
- 연결 노드로 옮기면 그 원본 노드로 간다. 원고 책은 가운데 노드 자체라 옮기지 않는다.
- 문헌이 움직이거나 연결 노드가 생기고 사라지면 인용 점검이 보는 문헌(자기 + 연결 노드가 가리키는 문헌)이 바뀌므로
  그 자리에서 장별 집계를 다시 계산하고, 그 문헌을 더는 보지 않게 된 원고가 있으면 알린다.
문장은 둘: 도구 응답(Claude에게, '-다')과 웹 안내(저자에게, '-습니다'). 둘 다 용어집 이름만 쓴다.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from magus.floors import josa
from magus.ids import new_id, utcnow
from magus.maps import BOOK_NAMES, CENTER, MAX_BOOKS_PER_NODE, MAX_NODES, NODE_NAME_MAX, local_key
from magus.melchior.check import after_refs_changed
from magus.project_args import floor_name
from magus.store import FloorMove, MapNode, Store
from magus.store.floors import KINDS, MoveError
from magus.store.maps import MapError

BUILTIN_NAMES = BOOK_NAMES


def book_name(store: Store, user: str, key: str) -> str:
    """책 주소 이름 → 책 이름(원고 책은 원고 제목)."""
    floor, local = local_key(key)
    if local in BOOK_NAMES:
        return BOOK_NAMES[local]
    if local == "ms":
        project = store.get_project(user, floor) if floor else None
        return project.title if project else ""
    if local.startswith("doc."):
        doc = store.get_document(user, local[4:])
        return doc.title if doc else ""
    try:
        category = store.get_category(user, local)
    except ValueError:
        category = None
    return category.name if category else ""


def _scopes(store: Store, user: str) -> dict[str, tuple[str, ...]]:
    """원고가 있는 프로젝트마다 인용 점검이 보는 문헌의 프로젝트."""
    return {f.id: store.cite_scope(user, f.id) for f in store.list_floors(user) if f.has_manuscript}


def _lost(before: dict[str, tuple[str, ...]], after: dict[str, tuple[str, ...]], source: str | None = None,
          target: str | None = None) -> list[str]:
    """이전엔 보던 문헌을 이제 보지 않는 원고(프로젝트 id). source·target을 주면 그 문헌 책이 source에서 target으로 간 경우:
    전에는 source를 보던 원고가 이제 target을 보지 않으면. 주지 않으면(연결 노드를 치웠을 때) 보던 프로젝트가 줄어든 원고."""
    if source is None:
        return [p for p, scope in before.items() if set(scope) - set(after.get(p, ()))]
    return [p for p, scope in before.items() if source in scope and target not in after.get(p, ())]


def resolve_target(store: Store, user: str, floor: str, node: str | None) -> tuple[str, str | None]:
    """옮길 곳(프로젝트, 노드). 연결 노드면 그 원본."""
    if not node:
        return floor, None
    found = store.get_map(user, floor)
    target = found.node(node) if found else None
    if target is None:
        raise MoveError("unknown_node", f"노드 {node!r}가 없다")
    if target.link:
        if target.missing:
            raise MoveError("link_missing", "연결 노드의 원본이 없다")
        return target.link
    return floor, node


def move_book(store: Store, user: str, book: str, to_floor: str, to_node: str | None = None) -> tuple[FloorMove, list[str]]:
    """book: 책 주소 이름(ideas.<프로젝트>·<카테고리 id>·doc.<id>·ms.<프로젝트>). to_node가 없으면 받는 프로젝트에서
    이름이 같은 노드(없으면 새 노드)에 꽂힌다. (옮기기, 이 문헌을 더는 보지 않게 된 원고의 프로젝트 id)."""
    if book.startswith("ms."):
        raise MoveError("fixed", "원고 책은 가운데 노드 자체라 옮기지 않는다")
    from_floor = store.book_floor(user, book)
    if from_floor is None:
        raise MoveError("unknown_category", f"책 {book}가 없다")
    to_floor, to_node = resolve_target(store, user, to_floor, to_node)
    where = store.node_of_book(user, book)
    from_node = where[1] if where else None
    _, local = local_key(book)
    kind = local if local in KINDS else None
    name = book_name(store, user, book)
    before = _scopes(store, user) if kind == "refs" else {}
    if to_floor == from_floor:
        if not to_node or to_node == from_node:
            raise MoveError("same", "이미 그 노드에 있다", name=name)
        try:
            store.place_book(user, from_floor, book, to_node)
        except MapError as e:
            raise MoveError(e.code, str(e), **e.info) from e
        move = store.record_move(user, FloorMove(new_id(), utcnow(), kind or local, name, from_floor, to_floor,
                                                 from_node=from_node, to_node=to_node))
    else:
        target_map = store.get_map(user, to_floor)
        known = {n.id for n in target_map.nodes} if target_map else set()
        if book.startswith("doc."):
            move = store.move_document(user, book[4:], to_floor, to_node)
        elif kind:
            move = store.move_builtin(user, kind, from_floor, to_floor, to_node)
        else:
            move = store.move_category(user, book, to_floor, to_node)
        placed = store.node_of_book(user, f"{kind}.{to_floor}" if kind else book)
        move = store.record_move(user, replace(move, from_node=from_node, to_node=placed[1] if placed else None,
                                               made_node=bool(placed) and placed[1] not in known))
    if kind != "refs":
        return move, []
    after_refs_changed(store, user)
    return move, _lost(before, _scopes(store, user), from_floor, to_floor)


def undo_move(store: Store, user: str, move_id: str) -> FloorMove:
    """마지막 옮기기 되돌리기(저장소가 원래 프로젝트·원래 노드로 돌려 놓는다)."""
    last = store.last_move(user)
    refs = bool(last and last.book == "refs")
    move = store.undo_move(user, move_id)
    if refs:
        after_refs_changed(store, user)
    return move


# ---- 노드·선 ---------------------------------------------------------------------------------------

def _refs_changed(store: Store, user: str, before: dict[str, tuple[str, ...]]) -> list[str]:
    after_refs_changed(store, user)
    return _lost(before, _scopes(store, user))


def add_link(store: Store, user: str, floor: str, target_floor: str, target_node: str, *,
             x: float | None = None, y: float | None = None) -> MapNode:
    node = store.add_link_node(user, floor, target_floor, target_node, x=x, y=y)
    after_refs_changed(store, user)  # 연결한 노드에 문헌이 꽂혀 있으면 이 원고의 인용 점검 범위가 넓어진다
    return node


def trash_node(store: Store, user: str, floor: str, node_id: str, note: str) -> tuple[MapNode, list[str]]:
    """(옮긴 노드, 그 문헌을 더는 보지 않게 된 원고)."""
    before = _scopes(store, user)
    node = store.trash_node(user, floor, node_id, note)
    return node, _refs_changed(store, user, before) if node.link else []


def scope_names(store: Store, user: str, projects: list[str]) -> str:
    return "·".join(floor_name(store, user, p) for p in projects)


# ---- 문장 ----------------------------------------------------------------------------------------

def _node_name(store: Store, user: str, floor: str, node: str | None) -> str:
    if not node:
        return ""
    found = store.get_map(user, floor)
    target = found.node(node) if found else None
    if target is None or node == CENTER:
        return ""
    return f" · 노드 「{target.name}」"


def _where(store: Store, user: str, floor: str, node: str | None) -> str:
    return floor_name(store, user, floor) + _node_name(store, user, floor, node)


def tool_message(store: Store, user: str, move: FloorMove, undone: bool = False, lost: list[str] | None = None) -> str:
    src = _where(store, user, move.from_floor, move.from_node)
    if undone:
        return f"되돌림: 「{move.name}」 → {src}(옮기기 전 자리)."
    if move.from_floor == move.to_floor:
        out = f"옮김: 「{move.name}」 {src} → {_node_name(store, user, move.to_floor, move.to_node).lstrip(' ·') or '가운데 노드'}."
    else:
        merged = f"({floor_name(store, user, move.to_floor)}의 {move.name}과 합침, 항목 {len(move.items)}개)" if move.merged else (
            f"(항목 {len(move.items)}개 함께)" if move.book in KINDS else "" if move.book.startswith("doc.") else "(항목 모두 함께)")
        out = f"옮김: 「{move.name}」 {src} → {_where(store, user, move.to_floor, move.to_node)}{merged}."
    out += " 되돌리려면 저자에게 확인하고 같은 책으로 category_edit(undo_move=true)."
    if lost:
        out += f" 주의: {scope_names(store, user, lost)} 원고의 인용 점검은 이제 이 문헌을 보지 않는다(자기 문헌과 연결 노드가 가리키는 문헌만 본다)."
    return out


def web_message(store: Store, user: str, move: FloorMove, undone: bool = False, lost: list[str] | None = None) -> str:
    """저자에게 보이는 한 줄(이스케이프는 부르는 쪽에서)."""
    name = f"「{move.name}」"
    if undone:
        return f"{josa(name, '을/를')} 원래 자리({_where(store, user, move.from_floor, move.from_node)})로 되돌렸습니다."
    if move.merged:
        out = f"{josa(name, '을/를')} {floor_name(store, user, move.to_floor)}의 {josa(move.name, '과/와')} 합쳤습니다(항목 {len(move.items)}개)."
    elif move.from_floor == move.to_floor:
        target = _node_name(store, user, move.to_floor, move.to_node).lstrip(" ·") or "가운데 노드"
        out = f"{josa(name, '을/를')} {josa(target, '으로/로')} 옮겼습니다."
    else:
        out = f"{josa(name, '을/를')} {josa(_where(store, user, move.to_floor, move.to_node), '으로/로')} 옮겼습니다."
    if lost:
        out += f" {scope_names(store, user, lost)} 원고의 인용 점검은 이제 이 문헌을 보지 않습니다(자기 문헌과 연결된 문헌만 봅니다)."
    return out


def error_message(e: MoveError | MapError, polite: bool) -> str:
    """옮기기·되돌리기·지도 바꾸기를 하지 못한 까닭."""
    info: dict[str, Any] = e.info
    name, floor = str(info.get("name", "")), str(info.get("floor", ""))
    texts = {
        "same": ("이미 그 노드에 있습니다.", "이미 그 노드에 있다."),
        "clash": (f"{floor}에 같은 이름 「{name}」이 있어 옮기지 못했습니다. 이름을 바꾼 뒤 옮겨 주세요.",
                  f"{floor}에 같은 이름 「{name}」이 있어 옮기지 않았다. 저자에게 알리고, 이름을 바꾼 뒤 옮긴다."),
        "undo_clash": (f"{floor}에 같은 이름 「{name}」이 생겨 되돌리지 못했습니다.",
                       f"{floor}에 같은 이름 「{name}」이 생겨 되돌리지 않았다."),
        "not_last": ("되돌릴 수 있는 것은 마지막으로 옮긴 것뿐입니다.", "되돌릴 수 있는 것은 마지막 옮기기뿐이다."),
        "unknown_floor": ("없는 프로젝트입니다.", "없는 프로젝트다."),
        "no_builtin": ("그 프로젝트에 그 책이 없습니다.", "그 프로젝트에 그 책이 없다."),
        "unknown_category": ("없는 책입니다.", "없는 책이다."),
        "common_only": ("문서 책은 원고가 있는 프로젝트에만 둘 수 있습니다.", "문서 책은 원고가 있는 프로젝트에만 둔다."),
        "fixed": ("원고 책은 가운데 노드 자체라 옮길 수 없습니다. 다른 원고면 새 프로젝트를 만들어 올려 주세요.",
                  "원고 책은 가운데 노드 자체라 옮기지 않는다."),
        "unknown_node": ("없는 노드입니다.", "없는 노드다."),
        "center": ("가운데 노드는 휴지통으로 옮길 수 없습니다.", "가운데 노드는 휴지통으로 옮기지 않는다."),
        "center_name": ("가운데 노드 이름은 프로젝트 제목입니다.", "가운데 노드 이름은 프로젝트 제목이라 바꾸지 않는다."),
        "link_name": ("연결 노드 이름은 원본 노드 이름을 따릅니다.", "연결 노드 이름은 원본 노드 이름을 따른다."),
        "not_empty": ("책이 꽂힌 노드는 휴지통으로 옮길 수 없습니다. 책을 다른 노드로 옮긴 뒤 해 주세요.",
                      "책이 꽂힌 노드는 휴지통으로 옮기지 않는다. 책을 먼저 다른 노드로 옮긴다."),
        "node_full": (f"노드 하나에는 책을 {MAX_BOOKS_PER_NODE}권까지 둘 수 있습니다.", f"노드 하나에 책은 {MAX_BOOKS_PER_NODE}권까지다."),
        "nodes_full": (f"노드는 프로젝트마다 {MAX_NODES}개까지 만들 수 있습니다.", f"노드는 프로젝트마다 {MAX_NODES}개까지다."),
        "name_taken": (f"같은 이름의 노드 {josa(f'「{name}」', '이/가')} 이미 있습니다.", f"같은 이름의 노드 {josa(f'「{name}」', '이/가')} 이미 있다."),
        "bad_name": (f"노드 이름을 1~{NODE_NAME_MAX}자로 적어 주세요.", f"노드 이름은 1~{NODE_NAME_MAX}자다."),
        "bad_color": ("색은 #RRGGBB로 적어 주세요.", "색은 #RRGGBB다."),
        "same_node": ("같은 노드끼리는 이을 수 없습니다.", "같은 노드끼리는 잇지 않는다."),
        "link_self": ("같은 프로젝트의 노드는 연결 노드로 만들지 않습니다. 선으로 이어 주세요.",
                      "같은 프로젝트의 노드는 연결 노드로 만들지 않는다(선으로 잇는다)."),
        "link_exists": ("이미 이 지도에 연결돼 있습니다.", "이미 이 지도에 연결돼 있다."),
        "link_missing": ("연결 노드의 원본이 없습니다.", "연결 노드의 원본이 없다."),
        "link_node": ("연결 노드에는 책을 놓지 않습니다. 원본 노드에 놓입니다.", "연결 노드에는 책을 놓지 않는다."),
        "ms_center": ("원고 책은 가운데 노드에만 둡니다.", "원고 책은 가운데 노드에만 둔다."),
        "unknown_book": ("그 책이 이 프로젝트에 없습니다.", "그 책이 이 프로젝트에 없다."),
    }
    polite_text, plain = texts.get(e.code, (str(e), str(e)))
    return polite_text if polite else plain

