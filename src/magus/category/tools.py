"""책·글·지도(category_*) MCP 도구(#92 → #95 지도 → #96 컨텍스트). 책 이름을 인자로 받는 범용 도구 일곱 개로 끝낸다.

#96(종류를 없애고 컨텍스트로): 책에는 글이 쌓이거나 올린 문서가 들어 있고, 그 책을 어떻게 읽을지는 컨텍스트(magus.contexts)가 정한다.
종류별 넣기·찾기 도구(idea_add·style_add·ref_add·idea_search·style_search·ref_search)는 여기 둘로 합쳤다:
category_put = 글 넣기(어느 책에든. 서지·원문 확인을 주면 문헌 글이 된다), category_search = 찾기(글 + 문헌의 쓸 부분·원문).
지우기는 category_trash 하나. 자주 쓰는 컨텍스트 보기는 category_list, 붙이기는 category_create·category_edit의 context.
책을 읽거나 넣는 응답의 머리에는 꽂힌 노드 → 그 책의 컨텍스트 전문을 싣는다(View.header, #96-d).
지도(#95): category_list = 지도 보기, category_create(template=노드|연결 노드) = 노드 만들기, category_edit(node, link, unlink) =
노드 이름·색·컨텍스트·선, category_edit(move_to) = 책 옮기기, category_trash(node) = 노드 휴지통.
책 이름은 프로젝트마다 하나라서, 같은 이름이 여러 프로젝트에 있으면 project로 가린다.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.mcpserver.tools import Tool
from pydantic import BaseModel, Field

from magus.category.books import BookRef, writable_book
from magus.category.books import find_book as find_book_
from magus.category.maptext import Counts, project_block
from magus.category.moves import add_link, error_message, move_book, tool_message, trash_node, undo_move as undo_last
from magus.category.moves import scope_names
from magus.category.rules import (
    CONTENT_MAX, FIELD_MAX, MAX_CATEGORIES, NEW_COLOR_ORDER, PALETTE_BY_NAME, TEMPLATE_BY_KEY, TEMPLATE_NAMES, TITLE_MAX,
    TITLE_MODES, check_name, clean_tags, color_label, name_key, parse_color, template_of,
)
from magus.category.titles import TITLE_RULE, decide_title
from magus.contexts import View, from_values, view_for_book, view_for_node
from magus.ids import local_time, new_id
from magus.inbox import FileResolver, ResolveFile
from magus.maps import LIBRARY, LIBRARY_NAME
from magus.maps import name_key as node_key
from magus.melchior.author_report import cite_label
from magus.melchior.check import after_refs_changed, chapters_citing
from magus.melchior.refs import add_ref
from magus.project_args import (
    PROJECT_PUT, find_project, floor_name, match_project, projects_text, resolve_project, search_projects, short,
)
from magus.search import Embedder, hybrid_search
from magus.attachments import describe, title_from_files
from magus.store import Category, CategoryItem, MapNode, Passage, Ref, ShelfSettings, Store
from magus.store.floors import MoveError
from magus.store.formats import one_line
from magus.store.maps import MapError

WHO = {"me": "저자의 말", "ai": "Claude가 쓴 글"}
NODE_TEMPLATES = ("노드", "연결 노드")
KEPT = "지운 것이 아니라 옮긴 것이라 운영자가 되살릴 수 있다."
SOURCE_LIGHT = {"verified": "원문 확인", "unverified": "원문 확인 전"}


class PartIn(BaseModel):
    text: str = Field(description="원문에서 고른 대목")
    reason: str | None = Field(default=None, description="왜 골랐는지")
    where: str | None = Field(default=None, description="쪽·장 등 위치")


def _template_line(c: Category) -> str:
    template = TEMPLATE_BY_KEY.get(c.template)
    name = template.name if template else c.template
    return f"{name}" + (f"(칸: {', '.join(c.fields)})" if c.fields else "")


def _map_error(e: MapError | MoveError) -> ToolError:
    return ToolError(error_message(e, polite=False))


def build_tools(
    store: Store, current_user: Callable[[], str], embedder: Embedder | None = None, files: ResolveFile | None = None
) -> list[Tool]:
    resolve_file = files or FileResolver(store)

    # ---- 책 찾기(magus.category.books) ------------------------------------------------------------------

    def find_book(user: str, text: str, project: str | None) -> BookRef:
        return find_book_(store, user, text, project)

    def writable(user: str, text: str, project: str | None) -> BookRef:
        return writable_book(store, user, text, project)

    def find_node(user: str, floor: str, text: str) -> tuple[str, MapNode]:
        """노드 이름 → (프로젝트, 노드). '프로젝트 · 노드'로 다른 프로젝트의 노드도. '가운데'는 가운데 노드."""
        raw = " ".join(text.split())
        if "·" in raw:
            head, _, raw = raw.partition("·")
            floor = find_project(store, user, head.strip()).id
            raw = raw.strip()
        raw = raw.strip("「」")
        found = store.get_map(user, floor)
        if found is None:
            raise ToolError("그 프로젝트의 지도가 없다.")
        key = node_key(raw)
        if key in ("가운데", "가운데노드", node_key(found.title)):
            return floor, found.nodes[0]
        if hit := found.node(raw):
            return floor, hit
        for pool in ([n for n in found.nodes if not n.link and not n.center], [n for n in found.nodes if n.link]):
            exact = [n for n in pool if node_key(n.name) == key]
            if len(exact) == 1:
                return floor, exact[0]
            starts = [n for n in pool if key and node_key(n.name).startswith(key)]
            if len(starts) == 1 and not exact:
                return floor, starts[0]
        names = " · ".join("가운데" if n.center else f"연결 {n.name}" if n.link else n.name for n in found.nodes)
        raise ToolError(f"{floor_name(store, user, floor)} 지도에 '{text}' 노드가 없다. 노드: {names}")

    def contexts_of(user: str, values: list[str] | None) -> tuple[Any, ...]:
        try:
            return from_values(store.list_saved_contexts(user), values or [])
        except ValueError as e:
            raise ToolError(str(e)) from e

    def summary(item: CategoryItem) -> str:
        """글을 한 줄로: 내용, 없으면 채워진 칸(예: 장소: 엘알토)."""
        return one_line(item.content) or " · ".join(f"{k}: {v}" for k, v in item.fields.items() if v)

    def chapter_refs(chapters: list[int] | None, project_id: str | None) -> tuple[tuple[str, int], ...]:
        if not chapters:
            return ()
        user = current_user()
        project = store.get_project(user, project_id)
        if project is None:
            raise ToolError(f"프로젝트 {project_id!r}에 올린 문서가 없다." if project_id else "올린 문서가 없어 장을 이을 수 없다.")
        known = {c.number for c in store.list_chapters(user, project.id)}
        if missing := sorted(set(chapters) - known):
            raise ToolError(f"『{project.title}』에 없는 장 번호: {missing}. book_outline의 장 번호를 쓴다.")
        return tuple((project.id, n) for n in dict.fromkeys(chapters))

    def chapter_project(user: str, floor: str, project: str | None) -> str | None:
        """장을 이을 원고: project(원고가 있으면) → 책이 있는 프로젝트 → 가장 최근 원고."""
        for f in (find_project(store, user, project).id if project and project.strip() else None, floor):
            if f and f != LIBRARY and (found := store.get_floor(user, f)) and found.has_manuscript:
                return f
        return None

    def node_said(user: str, floor: str, book: str) -> str:
        """' · 노드 「…」' 또는 ' · 가운데 노드'."""
        where = store.node_of_book(user, book)
        found = store.get_map(user, floor)
        shown = found.node(where[1]) if found and where else None
        return f" · 노드 「{shown.name}」" if shown and not shown.center else " · 가운데 노드" if shown else ""

    def target_node(user: str, floor: str, node: str | None) -> tuple[str, str | None]:
        """새 책을 꽂을 (프로젝트, 노드). 노드를 주지 않으면 (프로젝트, None): 이름이 같은 노드, 없으면 새 노드. 연결 노드면 원본에."""
        if not node or not node.strip():
            return floor, None
        target_floor, target = find_node(user, floor, node)
        if target.link:
            if target.missing:
                raise ToolError("그 연결 노드의 원본이 없다.")
            return target.link
        return target_floor, target.id

    # ---- 지도 보기 -----------------------------------------------------------------------------------

    def category_list(project: str | None = None) -> str:
        user = current_user()
        settings = store.get_shelf_settings(user)
        floors = store.list_floors(user)
        only = find_project(store, user, project).id if project and project.strip() else None
        counts = Counts(store, user)
        saved = store.list_saved_contexts(user)
        lines = [f"책장: 프로젝트 {len(floors)}개({projects_text(floors)}) · 제목 기본값: {TITLE_MODES[settings.title_default]}",
                 "자주 쓰는 컨텍스트(context에 이름으로 붙인다): "
                 + (" · ".join(f"「{c.name}」 {one_line(c.text)[:24]}…" if len(one_line(c.text)) > 24 else f"「{c.name}」 {one_line(c.text)}"
                               for c in saved) or "없음"),
                 "[ ]는 컨텍스트 이름(그 책을 읽는 방법, 전문은 글을 읽거나 넣는 응답 머리에 실린다). 글은 category_put으로 책 이름 그대로 넣는다. "
                 "연결 노드에서 보거나 넣으면 원본에 들어간다."]
        for f in floors:
            if only and f.id != only:
                continue
            head = f"## {LIBRARY_NAME}" if f.common else f"## 「{short(f.title)}」({f.id}) · 올린 문서 {'있음' if f.has_manuscript else '없음'}"
            lines += project_block(store, user, f.id, counts, header=head)
        if not counts.categories and not any(f.has_manuscript for f in floors):
            lines.append("책이 아직 없다(저자가 만들자고 하면 category_create로 만든다).")
        starred = sum(1 for i in store.list_category_items(user) if i.scrap) + sum(1 for r in store.list_refs(user) if r.scrap)
        if starred:
            lines.append(f"스크랩(★)한 글 {starred}개 — category_search(scrap_only=true)로 본다.")
        if settings.title_default == "ask":
            lines.append("제목: 저자가 제목을 말하지 않았으면 저장하기 전에 직접 지을지·지어 드릴지·비워 둘지 묻는다.")
        elif settings.title_default == "ai":
            lines.append("제목: 저자가 제목을 말하지 않았으면 Claude가 지어 title_by=ai로 넣는다(묻지 않는다).")
        else:
            lines.append("제목: 저자가 제목을 말하지 않았으면 비워 둔다(묻지 않는다).")
        return "\n".join(lines)

    # ---- 만들기 ---------------------------------------------------------------------------------------

    def category_create(name: str, template: Literal["빈 책", "인물", "사례", "수치", "용어", "노드", "연결 노드"] = "빈 책",
                        color: str | None = None, project: str | None = None, node: str | None = None,
                        context: list[str] | None = None) -> str:
        user = current_user()
        where = resolve_project(store, user, project)
        contexts = contexts_of(user, context)
        try:
            if template == "노드":
                made = store.add_node(user, where, name, color=parse_color(color) if color else None, contexts=contexts)
                return (view_for_node(store, user, where, made.id).header() + "\n"
                        f"노드를 만듦: 「{made.name}」({floor_name(store, user, where)} 지도, 가운데 노드와 이음).")
            if template == "연결 노드":  # name = 원본 '프로젝트 · 노드'
                if contexts:
                    raise ToolError("연결 노드에는 컨텍스트를 붙이지 않는다(원본 노드의 것을 따른다).")
                source_floor, source = find_node(user, where, name)
                if source.link and source.missing:
                    raise ToolError("그 연결 노드의 원본이 없다.")
                target = source.link or (source_floor, source.id)
                made = add_link(store, user, where, target[0], target[1])
                return (f"연결 노드를 만듦: {floor_name(store, user, where)} 지도에 {floor_name(store, user, made.link[0])}의 "  # type: ignore[index]
                        f"「{made.name}」(가운데 노드와 이음). 여기서 보거나 넣으면 원본에 들어간다.")
        except (MapError, MoveError) as e:
            raise _map_error(e) from e
        except ValueError as e:
            raise ToolError(str(e)) from e
        mine = store.list_categories(user)
        if len(mine) >= MAX_CATEGORIES:
            raise ToolError(f"책은 {MAX_CATEGORIES}권까지 만들 수 있다. 쓰지 않는 책을 휴지통으로 옮긴 뒤 만든다.")
        try:
            clean = check_name(name, {name_key(c.name): c.name for c in mine if c.floor == where})
            kind = template_of(template)
            hex_ = parse_color(color) if color else PALETTE_BY_NAME[NEW_COLOR_ORDER[len(mine) % len(NEW_COLOR_ORDER)]]
            target = target_node(user, where, node)
            made_cat = store.create_category(user, clean, kind.key, hex_, tuple(f for f, _ in kind.fields), target[0], target[1],
                                             contexts=contexts)
        except ValueError as e:
            raise ToolError(str(e)) from e
        return (view_for_book(store, user, made_cat.id).header() + "\n"
                f"책을 만듦: 「{made_cat.name}」 · {_template_line(made_cat)} · 색 {color_label(made_cat.color)} · "
                f"{floor_name(store, user, made_cat.floor)}{node_said(user, made_cat.floor, made_cat.id)}에 꽂혔다.")

    # ---- 고치기 ---------------------------------------------------------------------------------------

    def category_edit(book: str | None = None, new_name: str | None = None, color: str | None = None,
                      context: list[str] | None = None, project: str | None = None, move_to: str | None = None,
                      undo_move: bool = False, node: str | None = None, link: str | None = None,
                      unlink: str | None = None, item_id: str | None = None, checked: bool | None = None,
                      scrap: bool | None = None) -> str:
        user = current_user()
        if scrap is not None:  # 글의 스크랩(★) 켜고 끄기(2026-10-09). 파일의 표시 하나만
            return set_scrap(user, book, project, item_id, scrap)
        if checked is not None:  # 문헌 글의 원문 확인 표시 켜고 끄기(2026-10-09). 쓸 부분·서지·전문은 그대로
            return set_checked(user, book, project, item_id, checked)
        if node and not book:
            return edit_node(user, node, project, new_name, color, context, link, unlink)
        if not book:
            raise ToolError("book(책) 또는 node(노드)를 준다.")
        if not new_name and not color and not move_to and not undo_move and context is None:
            raise ToolError("바꿀 것(new_name·color·context·move_to) 또는 undo_move를 준다.")
        found = find_book(user, book, project)
        if undo_move:  # 마지막 옮기기 되돌리기. 그 책을 옮긴 것일 때만
            last = store.last_move(user)
            if last is None or last.book != found.key:
                raise ToolError(f"되돌릴 수 있는 것은 마지막 옮기기뿐이다. 마지막으로 옮긴 것: 「{last.name}」." if last else "되돌릴 옮기기가 없다.")
            try:
                return tool_message(store, user, undo_last(store, user, last.id), undone=True)
            except MoveError as e:
                raise _map_error(e) from e
        done: list[str] = []
        try:
            hex_ = parse_color(color) if color else None
            if found.category is not None and (new_name or hex_):
                taken = {name_key(c.name): c.name for c in store.list_categories(user, floors=[found.floor]) if c.id != found.key}
                clean = check_name(new_name, taken) if new_name else None
                changed = store.update_category(user, found.key, name=clean, color=hex_)
                done += ([f"이름 「{found.name}」 → 「{changed.name}」"] if clean else []) + (
                    [f"책 색 {color_label(changed.color)}"] if hex_ else [])
            elif found.upload and (new_name or hex_):
                if found.key.startswith("ms."):
                    if new_name:
                        raise ToolError("올린 문서가 든 책의 이름은 프로젝트 제목이다(바꾸지 않는다).")
                    store.set_project_color(user, found.key[3:], hex_)
                else:
                    store.update_document(user, found.key[4:], title=one_line(new_name or "")[:TITLE_MAX] or None,
                                          color=hex_, title_by="author" if new_name else None)
                done += ([f"이름 → 「{one_line(new_name)}」"] if new_name else []) + ([f"책 색 {color_label(hex_)}"] if hex_ else [])
            if context is not None:
                store.set_book_contexts(user, found.key, contexts_of(user, context))
                done.append("컨텍스트를 바꿈" if context else "컨텍스트를 뗌")
        except ValueError as e:
            raise ToolError(str(e)) from e
        if move_to:  # 노드 이름, '프로젝트 · 노드', 또는 프로젝트 이름
            source = store.book_floor(user, found.key) or LIBRARY
            to_floor, to_node = move_target(user, source, move_to)
            try:
                move, lost = move_book(store, user, found.key, to_floor, to_node)
                done.append(tool_message(store, user, move, lost=lost))
            except MoveError as e:
                raise ToolError(" · ".join([*done, error_message(e, polite=False)])) from e
        head = view_for_book(store, user, found.key).header() + "\n" if context is not None else ""
        return head + (f"책 「{found.name}」을 고침: " + " · ".join(done) + ".").replace("..", ".")

    def set_scrap(user: str, book: str | None, project: str | None, item_id: str | None, on: bool) -> str:
        if not item_id or not item_id.strip():
            raise ToolError("scrap에는 item_id(category_search 결과의 글 id 또는 문헌 글 key)를 함께 준다.")
        ident = item_id.strip()
        cats = [find_book(user, book, project).category] if book else store.list_categories(user)
        owner, label, was = None, "", False
        for c in cats:
            if c is None:
                continue
            item = store.get_category_item(user, c.id, ident)
            if item is not None:
                owner, was = f"{c.id}/{item.id}", item.scrap
                files = (a.name for a in store.list_attachments(user, owner))
                label = f"「{c.name}」의 글 “{(item.title or title_from_files(files) or summary(item))[:60]}”"
                break
        if owner is None:
            ref = store.get_ref(user, ident)
            if ref is None or (book and cats and cats[0] is not None and ref.book != cats[0].id):
                raise ToolError(f"글 {ident!r}이 없다. category_search 결과의 id(문헌 글은 key)를 준다.")
            owner, was, label = f"ref:{ref.key}", ref.scrap, f"문헌 글 {cite_label(ref, ref.key)}"
        if was == on:
            return f"{label}: 스크랩(★)은 이미 {'붙어' if on else '떨어져'} 있다(바꾸지 않음)."
        store.set_scrap(user, owner, on)
        return f"{label}: {'스크랩(★)했다' if on else '스크랩(★)을 뗐다'}. 저자는 게시판의 '★ 스크랩만'으로 모아 본다."

    def set_checked(user: str, book: str | None, project: str | None, key: str | None, checked: bool) -> str:
        if not key:
            raise ToolError("checked에는 item_id(문헌 글의 key, 예: clack2012)를 함께 준다.")
        ref = store.get_ref(user, key.strip())
        if ref is None:
            raise ToolError(f"문헌 글 {key!r}이 없다. category_search로 key를 확인한다.")
        if book and ref.book and find_book(user, book, project).key != ref.book:
            raise ToolError(f"그 문헌 글은 「{book}」 책에 있지 않다.")
        label = cite_label(ref, ref.key)
        if checked and ref.status != "verified" and not store.get_passages(user, ref.key):
            raise ToolError(f"{label}에는 쓸 부분이 없다. 원문 확인 글로 넣으려면 저자가 고른 대목을 parts에 담아 "
                            "category_put(source, checked=true)로 넣는다.")
        before = ref.status == "verified"
        store.set_ref_status(user, ref.key, "verified" if checked else "unverified", via="chat")
        after_refs_changed(store, user)  # 장별 미확인 수·확인 요청 연결을 다시 센다
        if before == checked:
            return f"{label}: 원문 확인 표시는 이미 {'붙어' if checked else '떨어져'} 있다(바꾸지 않음)."
        return (f"{label}: 원문 확인 표시를 {'붙였다' if checked else '뗐다'}(쓸 부분·서지는 그대로). "
                "인용 점검 수를 다시 셌다.")

    def move_target(user: str, source: str, text: str) -> tuple[str, str | None]:
        """move_to → (프로젝트, 노드 또는 None). 프로젝트 이름이면 그 프로젝트(이름이 같은 노드), 아니면 이 프로젝트의 노드."""
        raw = " ".join(text.split())
        if "·" not in raw:
            if (found := match_project(store.list_floors(user), raw)) is not None and found.id != source:
                return found.id, None
        floor, node = find_node(user, source, raw)
        return floor, node.id

    def edit_node(user: str, node: str, project: str | None, new_name: str | None, color: str | None,
                  context: list[str] | None, link: str | None, unlink: str | None) -> str:
        floor = resolve_project(store, user, project)
        floor, target = find_node(user, floor, node)
        if not (new_name or color or link or unlink or context is not None):
            raise ToolError("노드에서 바꿀 것(new_name·color·context·link·unlink)을 준다.")
        done = []
        try:
            if new_name or color:
                changed = store.update_node(user, floor, target.id, name=new_name, color=parse_color(color) if color else None)
                done.append(f"노드 「{target.name}」" + (f" → 「{changed.name}」" if new_name else "") + (f" · 색 {color_label(changed.color or '')}" if color else ""))
            if context is not None:
                store.set_node_contexts(user, floor, target.id, contexts_of(user, context))
                done.append("노드 컨텍스트를 바꿈" if context else "노드 컨텍스트를 뗌")
            for other, join in ((link, True), (unlink, False)):
                if not other:
                    continue
                other_floor, peer = find_node(user, floor, other)
                if other_floor != floor:
                    raise ToolError("선은 같은 프로젝트의 노드끼리만 잇는다. 다른 프로젝트의 노드는 연결 노드로 만든다(category_create, template=연결 노드).")
                pair = f"「{'가운데' if target.center else target.name}」–「{'가운데' if peer.center else peer.name}」"
                if join:
                    done.append(f"선 이음 {pair}" if store.connect_nodes(user, floor, target.id, peer.id) else f"이미 이어져 있음 {pair}")
                else:
                    done.append(f"선 끊음 {pair}" if store.disconnect_nodes(user, floor, target.id, peer.id) else f"선이 없음 {pair}")
        except (MapError, MoveError) as e:
            raise ToolError(" · ".join([*done, error_message(e, polite=False)])) from e
        except ValueError as e:
            raise ToolError(str(e)) from e
        head = view_for_node(store, user, floor, target.id).header() + "\n" if context is not None else ""
        return head + f"{floor_name(store, user, floor)} 지도: " + " · ".join(done) + "."

    # ---- 글 넣기 --------------------------------------------------------------------------------------

    def category_put(
        book: str,
        author: Literal["me", "ai"],
        content: str | None = None,
        title: str | None = None,
        title_by: Literal["ai", "author"] | None = None,
        untitled: bool = False,
        reason: str | None = None,
        where: str | None = None,
        parts: list[PartIn] | None = None,
        source: dict[str, Any] | None = None,
        checked: bool = False,
        file: str | None = None,
        aliases: list[str] | None = None,
        fields: dict[str, str] | None = None,
        tags: list[str] | None = None,
        chapters: list[int] | None = None,
        item_id: str | None = None,
        project: str | None = None,
    ) -> str:
        user = current_user()
        target = writable(user, book, project)
        category = target.category
        assert category is not None
        head = view_for_book(store, user, target.key).header()
        if source or checked or file or aliases:  # 서지·원문 확인이 있으면 문헌 글(인용 점검이 본다)
            return head + "\n" + put_source(user, category, author, content, reason, where, parts or [], source or {}, checked,
                                            file, aliases)
        old = store.get_category_item(user, category.id, item_id.strip()) if item_id else None
        if item_id and old is None:
            raise ToolError(f"「{category.name}」에 글 {item_id}가 없다. category_search 결과의 id를 준다.")
        text = (content or "").strip()
        if len(text) > CONTENT_MAX:
            raise ToolError(f"내용은 {CONTENT_MAX}자까지다.")
        values = dict(old.fields) if old else {}
        for key, value in (fields or {}).items():
            if key not in category.fields:
                raise ToolError(f"「{category.name}」에는 '{key}' 칸이 없다. 칸: {', '.join(category.fields) or '없음'}. "
                                "이유·위치는 reason·where로 준다.")
            value = one_line(str(value))[:FIELD_MAX]
            if value:
                values[key] = value
            else:
                values.pop(key, None)
        try:
            clean_tag_list = clean_tags(tags) if tags is not None else list(old.tags if old else ())
        except ValueError as e:
            raise ToolError(str(e)) from e
        picked = tuple(Passage(one_line(p.text)[:FIELD_MAX * 4], one_line(p.reason or "")[:FIELD_MAX], one_line(p.where or "") or None)
                       for p in (parts or []) if p.text.strip())
        if old is None and not text and not (title or "").strip() and not values and not picked:
            raise ToolError("내용·제목·칸·쓸 부분 중 하나는 있어야 한다.")
        links = (chapter_refs(chapters, chapter_project(user, category.floor, project)) if chapters is not None
                 else (old.chapters if old else ()))
        if old is not None and not title and not untitled:  # 고칠 때 제목을 주지 않으면 그대로
            name, by, said = old.title, old.title_by, "제목 그대로"
        else:
            name, by, said = decide_title(store, user, title, title_by, untitled)
        item = store.put_category_item(user, CategoryItem(
            id=old.id if old else new_id(), category_id=category.id, content=text or (old.content if old else ""), author=author,
            title=name, title_by=by, fields=values, tags=tuple(clean_tag_list), chapters=links,
            created_at=old.created_at if old else "",
            reason=one_line(reason or "")[:FIELD_MAX] or (old.reason if old else None),
            where=one_line(where or "")[:FIELD_MAX] or (old.where if old else None),
            passages=picked or (old.passages if old else ()), parent_id=old.parent_id if old else None,
            origin=old.origin if old else None, kind=old.kind if old else None, tags_by=old.tags_by if old else None,
        ))
        bits = [said, f"누가: {WHO[author]}({author})"]
        bits += [f"칸 {len(values)}"] if values else []
        bits += [f"쓸 부분 {len(item.passages)}"] if item.passages else []
        bits += [f"연결된 장 {', '.join(str(n) for _, n in links)}"] if links else []
        return f"{head}\n{'고침' if old else '넣음'}: 「{category.name}」 {item.id} · " + " · ".join(bits)

    def put_source(user: str, category: Category, author: str, content: str | None, reason: str | None, where: str | None,
                   parts: list[PartIn], bib: dict[str, Any], checked: bool, file: str | None, aliases: list[str] | None) -> str:
        """문헌 글: 서지(source)·원문 확인(checked: 쓸 부분 하나 이상)·원문 파일. 옛 ref_add(#96)."""
        from magus.ids import utcnow  # noqa: PLC0415

        started = utcnow()
        passages = [Passage(p.text, (p.reason or reason or "").strip(), p.where or where or None) for p in parts]
        try:
            path, label = resolve_file(user, file) if file else (None, None)
            ref, before, added, moved = add_ref(store, user, bib, passages, book=category.id, file_path=str(path) if path else None,
                                                file_label=label, aliases=aliases, verified=checked, memo=content)
        except (ValueError, FileNotFoundError) as e:
            raise ToolError(str(e)) from e
        linked = after_refs_changed(store, user)
        citing = chapters_citing(store, user, ref.key)
        total = len(store.get_passages(user, ref.key))
        cites = "; ".join(f"{floor_name(store, user, pid)} {', '.join(f'{n}장' for n in chapters)}" for pid, chapters in citing.items())
        shelf = store.get_category(user, ref.book or "")
        state = SOURCE_LIGHT[ref.status]
        return (
            f"{ref.key}: {SOURCE_LIGHT.get(before or '', '새 문헌 글')} → {state} · 쓸 부분 {added}개 더함(모두 {total}개) · "
            f"원문 파일 {'있음' if ref.has_fulltext else '없음'} · 한글 표기 {list(ref.aliases) or '없음'} · "
            f"책 「{shelf.name if shelf else '?'}」({floor_name(store, user, ref.floor or '')})"
            + (f" · 옮김: {ref.moved['reason']}(저자에게 알린다)" if ref.moved and ref.moved.get("at", "") >= started
               else " · 저자가 고른 책으로 옮김" if moved else "")
            + f"\n확인 요청과의 연결 변경 {linked}건 · 이 문헌을 인용하는 장: {cites or '없음'}"
            + ("" if checked else "\n원문 확인 전이라 인용 점검은 아직 확인으로 보지 않는다(저자가 원문을 읽고 쓸 부분을 고르면 checked=true).")
        )

    # ---- 찾기 ---------------------------------------------------------------------------------------

    def category_search(query: str = "", book: str | None = None, project: str | None = None,
                        author: Literal["me", "ai", "all"] = "all", full: bool = False, k: int = 8, scrap_only: bool = False) -> str:
        user = current_user()
        k = max(1, min(k, 30))
        query = " ".join((query or "").split())
        if not query and not scrap_only:
            return "category_search: 검색어가 비었다(찾을 말을 준다. 스크랩한 글만 보려면 scrap_only=true)."
        only = find_book(user, book, project) if book else None
        if only is not None and only.upload:
            raise ToolError(f"「{only.name}」에는 올린 문서가 들어 있다. 장은 book_read_chapter, 확인 요청은 book_issues로 본다.")
        scope = search_projects(store, user, project)
        books = {c.id: c for c in store.list_categories(user, floors=scope)}
        lanes: list[Any] = ["category", "ref_picked", *(["ref_full"] if full else [])]
        hits: list[tuple[str, Any, Any]] = []  # (책 id, 글 또는 문헌, 맞은 청크)
        seen: set[str] = set()
        if not query:  # 스크랩한 글 전체(최근 것부터)
            starred: list[tuple[str, Any, Any]] = [
                *((i.category_id, i, None) for i in store.list_category_items(user)
                  if i.scrap and i.category_id in books and (not only or i.category_id == only.key) and author in ("all", i.author)),
                *((r.book, r, None) for r in store.list_refs(user)
                  if r.scrap and r.book in books and (not only or r.book == only.key) and author != "ai")]
            hits = sorted(starred, key=lambda h: h[1].created_at, reverse=True)
        for chunk in (hybrid_search(store, user, query, lanes, k * 6, embedder) if query else []):
            if chunk.lane == "category":
                cid, _, iid = chunk.owner_id.partition("/")
                if cid not in books or (only and cid != only.key) or chunk.owner_id in seen:
                    continue
                item = store.get_category_item(user, cid, iid)
                if item is None or (author != "all" and item.author != author) or (scrap_only and not item.scrap):
                    continue
                seen.add(chunk.owner_id)
                hits.append((cid, item, chunk))
            else:
                ref = store.get_ref(user, chunk.owner_id)
                if ref is None or ref.book not in books or (only and ref.book != only.key) or author == "ai" or (scrap_only and not ref.scrap):
                    continue
                mark = f"{ref.key}/{chunk.lane}/{chunk.text[:40]}"
                if mark in seen:
                    continue
                seen.add(mark)
                hits.append((ref.book, ref, chunk))
            if len(hits) >= k * 2:
                break
        if author == "all":  # 저자의 말을 먼저(같은 쪽 안에서는 검색 순위 그대로)
            hits.sort(key=lambda h: isinstance(h[1], CategoryItem) and h[1].author == "ai")
        hits = hits[:k]
        where = (f"「{only.name}」" if only else "모든 책") + (" · 스크랩만" if scrap_only else "")
        asked = f"category_search {query!r}" if query else "category_search"
        if not hits:
            return f"{asked} ({where}): 결과 없음." + (" 스크랩(★)한 글이 없다." if scrap_only and not query else "")
        lines = [f"{asked} ({where}) — {len(hits)}건. author=me 글이 저자의 말이다. 인용은 '원문 확인' 문헌 글의 쓸 부분만 쓴다."
                 + (" ★는 저자가 스크랩(중요 표시)한 글이다." if any(h[1].scrap for h in hits) else "")]
        multi = len({books[h[0]].floor for h in hits}) > 1
        names: dict[str, dict[int, str]] = {}
        groups: dict[str, list[tuple[Any, Any]]] = {}
        for cid, obj, chunk in hits:
            groups.setdefault(cid, []).append((obj, chunk))
        n = 0
        for cid, members in groups.items():
            c = books[cid]
            lines.append(f"## 「{c.name}」" + (f"({floor_name(store, user, c.floor)})" if multi else "") + " — "
                         + view_for_book(store, user, cid).header())
            for obj, chunk in members:
                n += 1
                if isinstance(obj, CategoryItem):
                    lines += item_lines(user, n, obj, names)
                else:
                    lines += source_lines(user, n, obj, chunk)
        return "\n".join(lines)

    def item_lines(user: str, n: int, item: CategoryItem, names: dict[str, dict[int, str]]) -> list[str]:
        head = f"{n}. {item.id} · [{item.author}] {local_time(item.created_at, '%Y-%m-%d')}" + (" · ★스크랩" if item.scrap else "")
        head += f" · 제목 「{item.title}」" + (" (AI가 지은 제목)" if item.title_by == "ai" else "") if item.title else ""
        if not item.title and (stem := title_from_files(a.name for a in store.list_attachments(user, f"{item.category_id}/{item.id}"))):
            head += f" · 제목 「{stem}」(첫 첨부의 파일 이름)"  # 제목 없는 글은 보일 때만 첫 첨부 이름(파일은 그대로)
        out = [head, f"   “{summary(item)[:300]}”"]
        out += [f"   이유: {one_line(item.reason)[:150]}"] if item.reason else []
        out += [f"   위치: {one_line(item.where)[:80]}"] if item.where else []
        out += [f"   쓸 부분: “{one_line(p.text)[:120]}”" for p in item.passages[:2]]
        out += ["   " + " · ".join(f"{k}: {v[:60]}" for k, v in item.fields.items())] if item.fields else []
        out += [f"   태그: {', '.join(item.tags)}" + (" (AI가 뽑음)" if item.tags_by == "ai" else "")] if item.tags else []
        if item.chapters:
            pid = item.chapters[0][0]
            if pid not in names:
                names[pid] = {c.number: c.display for c in store.list_chapters(user, pid)}
            out.append("   연결된 장: " + ", ".join(names.get(p, {}).get(num, f"{num}") for p, num in item.chapters))
        if item.parent_id:
            parent = store.get_category_item(user, item.category_id, item.parent_id)
            if parent is not None:
                out.append(f"   ↳ 이 글이 응답한 저자의 말: “{summary(parent)[:80]}”")
        out += attached(user, f"{item.category_id}/{item.id}")
        return out

    def attached(user: str, owner: str) -> list[str]:
        """첨부(#97): 이름·종류·크기만. 내용은 읽지 않는다."""
        files = store.list_attachments(user, owner)
        if not files:
            return []
        shown = " · ".join(describe(a.name, a.size) for a in files[:5])
        return [f"   첨부 {len(files)}개: {shown}" + (f" 외 {len(files) - 5}개" if len(files) > 5 else "")]

    def source_lines(user: str, n: int, ref: Ref, chunk: Any) -> list[str]:
        title = one_line(str(ref.bib.get("title") or ref.bib.get("raw") or ""))[:80]
        head = f"{n}. {ref.key} · 문헌 글 · {SOURCE_LIGHT[ref.status]}" + (" · ★스크랩" if ref.scrap else "") + f" · {title}"
        if chunk is None:  # 스크랩 목록(검색어 없이): 쓸 부분 하나만
            picked = store.get_passages(user, ref.key)[:1]
            return [head, *(f"   쓸 부분 “{one_line(p.text)[:300]}”" for p in picked), *attached(user, f"ref:{ref.key}")]
        if chunk.lane == "ref_picked":
            passage = next((p for p in store.get_passages(user, ref.key) if p.text == chunk.text), None)
            return [head + (f" · {passage.locator}" if passage and passage.locator else ""), f"   쓸 부분 “{one_line(chunk.text)[:300]}”",
                    *([f"   이유: {one_line(passage.reason)[:150]}"] if passage and passage.reason else []),
                    *attached(user, f"ref:{ref.key}")]
        return [head + " · 원문(쓸 부분으로 고르지 않은 곳)", f"   “{one_line(chunk.text)[:300]}”",
                "   → 인용하려면 저자가 확인한 뒤 이 대목을 parts에 더해 다시 넣는다(category_put, checked=true).",
                *attached(user, f"ref:{ref.key}")]

    # ---- 지우기 -------------------------------------------------------------------------------------

    def category_trash(note: str, book: str | None = None, item_id: str | None = None, project: str | None = None,
                       node: str | None = None) -> str:
        user = current_user()
        if node and not book:
            floor, target = find_node(user, resolve_project(store, user, project), node)
            try:
                gone, lost = trash_node(store, user, floor, target.id, note.strip())
            except MapError as e:
                raise _map_error(e) from e
            warn = f" 주의: {scope_names(store, user, lost)} 올린 문서의 인용 점검은 이제 그 문헌을 보지 않는다." if lost else ""
            return (f"휴지통으로 옮김: {floor_name(store, user, floor)} 지도의 " + (f"연결 노드 「{gone.name}」(원본은 그대로)" if gone.link
                    else f"노드 「{gone.name}」") + f". {KEPT}{warn}")
        if not book:
            raise ToolError("book(책·글) 또는 node(노드)를 준다.")
        found = find_book(user, book, project)
        if found.upload:
            raise ToolError(f"「{found.name}」에는 올린 문서가 들어 있다. 이 책은 저자가 웹 책장의 책 설정에서 휴지통으로 옮긴다.")
        category = found.category
        assert category is not None
        try:
            if item_id:
                if store.get_ref(user, item_id.strip()) is not None and store.get_ref(user, item_id.strip()).book == category.id:  # type: ignore[union-attr]
                    raise ToolError("문헌 글(서지·원문 확인)은 휴지통으로 옮기지 않는다(인용 점검이 보는 기록이다).")
                moved = store.trash_item_with_replies(user, category.id, item_id.strip(), note.strip())
                if not moved:
                    raise ToolError(f"「{category.name}」에 글 {item_id}가 없다. category_search 결과의 id를 준다.")
                replies = len(moved) - 1
                return (f"휴지통으로 옮김: 「{category.name}」의 글 {moved[0].id} “{(moved[0].title or summary(moved[0]))[:60]}”"
                        + (f" · 이 글에 응답한 글 {replies}개도 함께" if replies else "") + f". {KEPT}")
            gone = store.trash_category(user, category.id, note.strip())
        except ValueError as e:
            raise ToolError(str(e)) from e
        assert gone is not None
        return f"휴지통으로 옮김: 책 「{gone.name}」 통째(글 {gone.items}개). 책장에서 빠졌다. {KEPT}"

    def category_title_default(mode: Literal["ask", "ai", "none"]) -> str:
        user = current_user()
        settings = store.get_shelf_settings(user)
        store.save_shelf_settings(user, ShelfSettings(settings.colors, settings.my_colors, mode))
        then = {"ask": "저장하기 전에 직접 지을지·지어 드릴지·비워 둘지 묻는다",
                "ai": "Claude가 제목을 지어 넣는다(AI가 지은 제목으로 표시된다)", "none": "제목 없이 넣는다"}[mode]
        return f"제목 기본값을 '{TITLE_MODES[mode]}'로 저장함. 앞으로 글을 넣을 때 저자가 제목을 말하지 않으면 {then}."

    template_names = "·".join(TEMPLATE_NAMES)
    return [
        Tool.from_function(
            category_list, name="category_list",
            description=(
                "프로젝트마다 지도(노드·선·연결 노드)와 노드에 꽂힌 책(글 수, [ ]는 컨텍스트 이름), 자주 쓰는 컨텍스트, 제목 기본값. "
                "'지도·책장 보여 줘', 넣을 곳을 묻기 전에 부른다. project를 주면 그 프로젝트만."
            ),
            structured_output=False,
        ),
        Tool.from_function(
            category_create, name="category_create",
            description=(
                "저자가 새 책이나 노드를 만들자고 분명히 말했을 때만 부른다(이름을 확인받은 뒤). "
                f"template: {template_names}(책. 템플릿마다 칸 몇 개) · 노드 · 연결 노드(다른 프로젝트의 노드를 잇는다. name에 '프로젝트 · 노드'). "
                "node: 책을 꽂을 노드(없으면 이름이 같은 새 노드). context: 붙일 컨텍스트(자주 쓰는 컨텍스트 이름이나 저자가 말한 글, 순서대로). "
                "color: 색 이름(빨강·파랑·겨자 등) 또는 #RRGGBB. 책 이름은 12자까지. " + PROJECT_PUT
            ),
            structured_output=False,
        ),
        Tool.from_function(
            category_edit, name="category_edit",
            description=(
                "저자가 책·노드의 이름·색·컨텍스트·위치나 선, 문헌 글의 원문 확인 표시, 또는 글의 스크랩을 바꾸라고 분명히 말했을 때만 부른다. "
                "book(책 이름) 또는 node(노드 이름). "
                "context: 새 컨텍스트 목록(자주 쓰는 컨텍스트 이름이나 글, []이면 뗀다). move_to: 책을 옮길 노드('프로젝트 · 노드'나 프로젝트). "
                "undo_move=true: 마지막 옮기기 되돌리기. node와 함께 link=이을 노드, unlink=끊을 노드. 같은 이름이 여러 프로젝트에 있으면 project. "
                "checked=true|false와 item_id(문헌 글 key): 원문 확인 표시를 붙이거나 뗀다(저자가 그렇게 말했을 때만. 쓸 부분·서지는 그대로). "
                "scrap=true|false와 item_id(글 id 또는 문헌 글 key): 글을 스크랩(★)하거나 뗀다(저자가 '스크랩해 줘'라고 했을 때만)."
            ),
            structured_output=False,
        ),
        Tool.from_function(
            category_put, name="category_put",
            description=(
                "글 넣기. 저자가 그 책에 넣으라고 분명히 말했을 때만 부른다. 넣을 책이 대화에서 분명하지 않으면 부르지 말고 "
                "책 이름과 컨텍스트를 보여 주며 묻는다(category_list). item_id를 주면 그 글을 고친다. 응답 머리의 컨텍스트를 따른다. "
                "author: 저자의 말이면 me, Claude가 쓴 글(요약·설명)이면 ai. reason(이유)·where(위치: 출전·쪽)·tags·fields(그 책의 칸)·"
                "chapters(장 번호)는 저자가 말한 것만 넣고 지어내지 않는다. "
                "문헌이면 source에 서지({authors, year, title…} 또는 {key}). checked=true는 저자가 원문을 읽고 확인한 것이고 "
                "parts([{text, reason, where}], 원문에서 고른 대목) 하나 이상이 필요하다. 인용 점검은 checked 글만 확인으로 본다. "
                "file: 원문 파일(올린 파일 이름), aliases: 한글 표기(예: 갤러2022). " + TITLE_RULE
            ),
            structured_output=False,
        ),
        Tool.from_function(
            category_search, name="category_search",
            description=(
                "책의 글에서 찾는다(문헌 글의 쓸 부분 포함, full=true면 원문 전체도). book을 주면 그 책만, project를 주면 그 프로젝트와 연결 노드. "
                "author=me|ai|all(기본, 저자의 말을 먼저). k=8. scrap_only=true면 저자가 스크랩(★)한 글만(query 없이 부르면 스크랩 전체, "
                "최근 것부터). 결과는 책마다 컨텍스트와 함께."
            ),
            structured_output=False,
        ),
        Tool.from_function(
            category_trash, name="category_trash",
            description=(
                "저자가 그 글·책·노드를 지우라고 분명히 말했을 때만 부른다. 여러 개면 목록을 보여 주고 확인받는다. "
                "item_id면 그 글(응답한 글도 함께), 없으면 책 통째(글 수를 말하고 확인받은 뒤), node만 주면 그 노드(책이 있으면 먼저 옮긴다). "
                "문헌 글과 문헌이 든 책은 옮기지 않는다. 휴지통으로 옮길 뿐 지우지 않는다. note: 이유."
            ),
            structured_output=False,
        ),
        Tool.from_function(
            category_title_default, name="category_title_default",
            description=(
                "저자가 앞으로 제목을 어떻게 할지 정해 말했을 때만 부른다: '매번 물어봐' → ask, '앞으로는 제목 지어 줘' → ai, "
                "'앞으로는 비워 둬' → none. 글을 넣을 때 이 기본값을 따른다(대화가 바뀌어도 서버에 남는다)."
            ),
            structured_output=False,
        ),
    ]


def context_header(store: Store, user: str, key: str) -> str:
    """도구 응답 머리 한 줄(다른 도구 모듈이 쓴다): 그 책에 걸린 컨텍스트."""
    return view_for_book(store, user, key).header()


__all__ = ["build_tools", "context_header", "View"]
