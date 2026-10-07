"""카테고리(category_*) MCP 도구(#92) + 지도(#95). 카테고리 이름을 인자로 받는 범용 도구 일곱 개로 끝낸다.

카테고리마다 도구를 만들지 않는다: 사용자마다 도구 목록이 달라지고, instructions 조립(등록된 도구만 언급)이 깨진다.
생각·문체·문헌은 기본 책이다. 넣는 것·찾는 것은 각자의 도구(idea_*·style_*·ref_*)로 하고, 여기서는 책 색과 위치만 바꾼다.
지도(#95): 프로젝트마다 노드와 선이 있고 책은 노드에 꽂힌다. 도구 수를 늘리지 않으려고 지도 일은 여기에 합쳤다:
category_list = 지도 보기, category_create(template=노드|연결 노드) = 노드 만들기, category_edit(node, link, unlink) = 노드
이름·색·선, category_edit(move_to) = 책 옮기기, category_trash(node) = 노드 휴지통.
카테고리 이름은 프로젝트마다 하나라서, 같은 이름이 여러 프로젝트에 있으면 project로 가린다.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.mcpserver.tools import Tool

from magus.category.maptext import Counts, project_block
from magus.category.moves import add_link, error_message, move_book, tool_message, trash_node, undo_move as undo_last
from magus.category.moves import scope_names
from magus.category.rules import (
    BUILTIN_TOOLS, BUILTINS, CONTENT_MAX, FIELD_MAX, MAX_CATEGORIES, NEW_COLOR_ORDER, PALETTE_BY_NAME,
    TEMPLATE_BY_KEY, TEMPLATE_NAMES, TITLE_MODES, check_name, clean_name, clean_tags, color_label, name_key, parse_color,
    template_of,
)
from magus.category.titles import TITLE_RULE, decide_title
from magus.floors import josa
from magus.ids import local_time, new_id
from magus.maps import LIBRARY, LIBRARY_NAME
from magus.maps import name_key as node_key
from magus.project_args import (
    PROJECT_PUT, find_project, floor_name, match_project, projects_text, resolve_project, resolve_put, search_projects, short,
)
from magus.search import Embedder, hybrid_search
from magus.store import Category, CategoryItem, Floor, Idea, MapNode, ProjectMap, ShelfSettings, Store
from magus.store.floors import MoveError
from magus.store.formats import one_line
from magus.store.maps import MapError

WHERE = ("'저장해 줘'처럼 넣을 곳이 정해지지 않았으면 부르지 말고 생각·문체·문헌과 저자의 카테고리(category_list) 중 어디인지 먼저 묻는다"
         "(원고는 선택지에 넣지 않는다). ")
WHO = {"me": "저자의 말", "ai": "Claude가 쓴 글"}
BUILTIN_BY_KEY = {name_key(name): key for key, name in BUILTINS.items()}
# 생각·문체·문헌은 기본 책이다. 도구를 그때그때 찾아 불러오는 클라이언트에서는 Claude가 idea_add 대신 category_put을 부르기도 한다
# (2026-10-06 비밀 대화 시험). 생각은 여기서도 idea_add와 같은 규칙으로 받고, 문체·문헌은 맞는 도구 이름을 알려 준다.
BUILTIN_LINE = "생각·문체·문헌은 기본 카테고리다. 생각은 이 도구로도 들어가지만, 문체는 style_add, 문헌은 ref_add로 넣는다. "
BUILTIN_PUT = {
    "styles": "문체는 이 도구로 넣지 않는다. style_add 도구를 찾아 쓴다(구절과 저자가 말한 이유가 필요하다).",
    "refs": "문헌은 이 도구로 넣지 않는다. ref_add 도구를 찾아 쓴다(서지와, 원문에서 고른 발췌와 그 이유가 필요하다).",
}
BUILTIN_SEARCH = {"ideas": "idea_search", "styles": "style_search", "refs": "ref_search"}
NODE_TEMPLATES = ("노드", "연결 노드")
KEPT = "지운 것이 아니라 옮긴 것이라 운영자가 되살릴 수 있다."


def _template_line(c: Category) -> str:
    template = TEMPLATE_BY_KEY.get(c.template)
    name = template.name if template else c.template
    return f"{name} 템플릿" + (f"(칸: {', '.join(c.fields)})" if c.fields else "(칸 없음: 제목·내용만)")


def _map_error(e: MapError | MoveError) -> ToolError:
    return ToolError(error_message(e, polite=False))


def build_tools(store: Store, current_user: Callable[[], str], embedder: Embedder | None = None) -> list[Tool]:
    def resolve(category: str, project: str | None = None) -> Category | str:
        """카테고리 이름(또는 id) → 저자의 카테고리, 또는 기본 책 종류(ideas|styles|refs).
        같은 이름이 여러 프로젝트에 있으면 project(그 프로젝트, 그다음 그 지도의 연결 노드가 가리키는 노드)로 가린다."""
        key = name_key(clean_name(category))
        if key in BUILTIN_BY_KEY:
            return BUILTIN_BY_KEY[key]
        user = current_user()
        found = [c for c in store.list_categories(user) if name_key(c.name) == key or c.id == category.strip()]
        if project and project.strip() and len(found) > 1:
            here = find_project(store, user, project).id
            own = [c for c in found if c.floor == here]
            if len(own) == 1:
                return own[0]
            linked_books = {b for n in (store.get_map(user, here) or ProjectMap('', '', (), ())).nodes if n.link for b in n.books}
            linked = [c for c in found if c.id in linked_books]
            if len(linked) == 1:
                return linked[0]
        if len(found) == 1:
            return found[0]
        if not found:
            raise ToolError(f"'{category}' 카테고리가 없다. category_list로 이름을 확인한다.")
        raise ToolError(f"「{found[0].name}」 카테고리가 여러 프로젝트에 있다"
                        f"({', '.join(dict.fromkeys(floor_name(store, user, c.floor) for c in found))}). project로 어느 것인지 준다.")

    def builtin_floor(user: str, kind: str, project: str | None) -> str:
        """기본 책(kind)이 있는 프로젝트(색·옮기기용). project를 주면 그 프로젝트의 책(없으면 연결 노드로 이어진 하나)."""
        if project and project.strip():
            floor = find_project(store, user, project).id
            targets = store.book_targets(user, kind, floor)
            if len(targets) == 1:
                return targets[0]
            raise ToolError(f"{floor_name(store, user, floor)}에는 {BUILTINS[kind]} 책이 "
                            + ("여럿 연결돼 있다. 원본 프로젝트를 project로 준다." if targets else "없다."))
        where = [f for f in store.list_floors(user) if kind in f.builtins]
        if len(where) == 1:
            return where[0].id
        raise ToolError(f"{BUILTINS[kind]} 책이 여러 프로젝트에 있다({', '.join(floor_name(store, user, f.id) for f in where)}). "
                        "project로 어느 것인지 준다." if where else f"{BUILTINS[kind]} 책이 없다.")

    def own(category: str, action: str, tools: dict[str, str] = BUILTIN_TOOLS, project: str | None = None) -> Category:
        found = resolve(category, project)
        if isinstance(found, str):
            raise ToolError(f"'{BUILTINS[found]}'은 기본 카테고리라 {action} 수 없다. {tools[found]} 도구를 찾아 쓴다.")
        return found

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

    def summary(item: CategoryItem) -> str:
        """항목을 한 줄로: 내용, 없으면 채워진 칸(예: 장소: 엘알토)."""
        return one_line(item.content) or " · ".join(f"{k}: {v}" for k, v in item.fields.items() if v)

    def chapter_refs(chapters: list[int] | None, project_id: str | None) -> tuple[tuple[str, int], ...]:
        if not chapters:
            return ()
        user = current_user()
        project = store.get_project(user, project_id)
        if project is None:
            raise ToolError(f"프로젝트 {project_id!r}에 원고가 없다." if project_id else "원고가 없어 장을 이을 수 없다.")
        known = {c.number for c in store.list_chapters(user, project.id)}
        if missing := sorted(set(chapters) - known):
            raise ToolError(f"『{project.title}』에 없는 장 번호: {missing}. book_outline의 장 번호를 쓴다.")
        return tuple((project.id, n) for n in dict.fromkeys(chapters))

    def category_list(project: str | None = None) -> str:
        user = current_user()
        settings = store.get_shelf_settings(user)
        floors = store.list_floors(user)
        only = find_project(store, user, project).id if project and project.strip() else None
        counts = Counts(store, user)
        lines = [f"책장: 프로젝트 {len(floors)}개({projects_text(floors)}) · 제목 기본값: {TITLE_MODES[settings.title_default]}",
                 BUILTIN_LINE.strip() + " 저자가 만든 카테고리는 category_put으로 넣는다(이름 그대로). "
                 "연결 노드에서 보거나 넣으면 원본에 들어간다."]
        for f in floors:
            if only and f.id != only:
                continue
            head = f"## {LIBRARY_NAME}" if f.common else f"## 「{short(f.title)}」({f.id}) · 원고 {'있음' if f.has_manuscript else '없음'}"
            lines += project_block(store, user, f.id, counts, header=head)
        if not counts.categories:
            lines.append("저자가 만든 카테고리는 아직 없다(category_create로 만든다).")
        if settings.title_default == "ask":
            lines.append("제목: 저자가 제목을 말하지 않았으면 저장하기 전에 직접 지을지·지어 드릴지·비워 둘지 묻는다.")
        elif settings.title_default == "ai":
            lines.append("제목: 저자가 제목을 말하지 않았으면 Claude가 지어 title_by=ai로 넣는다(묻지 않는다).")
        else:
            lines.append("제목: 저자가 제목을 말하지 않았으면 비워 둔다(묻지 않는다).")
        return "\n".join(lines)

    def category_create(name: str, template: Literal["빈 카테고리", "인물", "사례", "수치", "용어", "노드", "연결 노드"] = "빈 카테고리",
                        color: str | None = None, project: str | None = None, node: str | None = None) -> str:
        user = current_user()
        where = resolve_project(store, user, project)
        try:
            if template == "노드":
                made = store.add_node(user, where, name, color=parse_color(color) if color else None)
                return f"노드를 만듦: 「{made.name}」({floor_name(store, user, where)} 지도, 가운데 노드와 이음)."
            if template == "연결 노드":  # name = 원본 '프로젝트 · 노드'
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
        key = name_key(clean_name(name))
        if key in BUILTIN_BY_KEY:  # 기본 책을 이 프로젝트에 다시 꽂는다(옮겨 비웠거나 처음부터 없을 때)
            kind = BUILTIN_BY_KEY[key]
            if kind in (store.get_floor(user, where) or Floor('', -1, '')).builtins:
                raise ToolError(f"{floor_name(store, user, where)}에는 이미 {josa(BUILTINS[kind], '이/가')} 있다(기본 카테고리).")
            target = target_node(user, where, node)
            if target[0] != where:
                raise ToolError("기본 책은 이 프로젝트의 노드에 꽂는다(연결 노드가 아닌 노드).")
            store.add_builtin(user, kind, where, target[1])
            return f"{floor_name(store, user, where)}에 {josa(BUILTINS[kind], '을/를')} 다시 꽂음{node_said(user, where, f'{kind}.{where}')}."
        mine = store.list_categories(user)
        if len(mine) >= MAX_CATEGORIES:
            raise ToolError(f"카테고리는 {MAX_CATEGORIES}개까지 만들 수 있다(기본 셋 빼고). 쓰지 않는 카테고리를 휴지통으로 옮긴 뒤 만든다.")
        try:
            clean = check_name(name, {name_key(c.name): c.name for c in mine if c.floor == where})
            kind_ = template_of(template)
            hex_ = parse_color(color) if color else PALETTE_BY_NAME[NEW_COLOR_ORDER[len(mine) % len(NEW_COLOR_ORDER)]]
            target = target_node(user, where, node)
            made_cat = store.create_category(user, clean, kind_.key, hex_, tuple(f for f, _ in kind_.fields), target[0], target[1])
        except ValueError as e:
            raise ToolError(str(e)) from e
        return (f"카테고리를 만듦: 「{made_cat.name}」 · {_template_line(made_cat)} · 색 {color_label(made_cat.color)}. "
                f"{floor_name(store, user, made_cat.floor)}{node_said(user, made_cat.floor, made_cat.id)}에 꽂혔다.")

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

    def node_said(user: str, floor: str, book: str) -> str:
        """' · 노드 「…」' 또는 ' · 가운데 노드'."""
        where = store.node_of_book(user, book)
        found = store.get_map(user, floor)
        shown = found.node(where[1]) if found and where else None
        return f" · 노드 「{shown.name}」" if shown and not shown.center else " · 가운데 노드" if shown else ""

    def category_edit(category: str | None = None, new_name: str | None = None, color: str | None = None,
                      project: str | None = None, move_to: str | None = None, undo_move: bool = False,
                      node: str | None = None, link: str | None = None, unlink: str | None = None) -> str:
        user = current_user()
        if node and not category:
            return edit_node(user, node, project, new_name, color, link, unlink)
        if not category:
            raise ToolError("category(책) 또는 node(노드)를 준다.")
        if not new_name and not color and not move_to and not undo_move:
            raise ToolError("바꿀 것(new_name·color·move_to) 또는 undo_move를 준다.")
        found = resolve(category, project)
        if undo_move:  # 마지막 옮기기 되돌리기. 그 책을 옮긴 것일 때만
            last = store.last_move(user)
            if last is None or last.book != (found if isinstance(found, str) else found.id):
                raise ToolError(f"되돌릴 수 있는 것은 마지막 옮기기뿐이다. 마지막으로 옮긴 것: 「{last.name}」." if last else "되돌릴 옮기기가 없다.")
            try:
                return tool_message(store, user, undo_last(store, user, last.id), undone=True)
            except MoveError as e:
                raise _map_error(e) from e
        done: list[str] = []
        try:
            hex_ = parse_color(color) if color else None
            if isinstance(found, str):  # 기본 책: 색과 위치만
                if new_name:
                    raise ToolError(f"'{BUILTINS[found]}'은 기본 카테고리라 이름을 바꿀 수 없다(색·위치는 바꿀 수 있다).")
                if hex_:
                    settings = store.get_shelf_settings(user)
                    store.save_shelf_settings(user, ShelfSettings({**settings.colors, found: hex_}, settings.my_colors,
                                                                  settings.title_default))
                    done.append(f"「{BUILTINS[found]}」 책 색을 {color_label(hex_)}으로 바꿈")  # 색은 종류마다 하나(모든 프로젝트의 생각)
            elif new_name or hex_:
                taken = {name_key(c.name): c.name for c in store.list_categories(user, floors=[found.floor]) if c.id != found.id}
                clean = check_name(new_name, taken) if new_name else None
                changed = store.update_category(user, found.id, name=clean, color=hex_)
                done += ([f"이름 「{found.name}」 → 「{changed.name}」"] if clean else []) + (
                    [f"책 색 {color_label(changed.color)}"] if hex_ else [])
        except ValueError as e:
            raise ToolError(str(e)) from e
        if move_to:  # 노드 이름, '프로젝트 · 노드', 또는 프로젝트 이름
            book = f"{found}.{builtin_floor(user, found, project)}" if isinstance(found, str) else found.id
            source = store.book_floor(user, book) or LIBRARY
            to_floor, to_node = move_target(user, source, move_to)
            try:
                move, lost = move_book(store, user, book, to_floor, to_node)
                done.append(tool_message(store, user, move, lost=lost))
            except MoveError as e:
                raise ToolError(" · ".join([*done, error_message(e, polite=False)])) from e
        return (" · ".join(done) + "." if isinstance(found, str) else "카테고리를 고침: " + " · ".join(done) + ".").replace("..", ".")

    def move_target(user: str, source: str, text: str) -> tuple[str, str | None]:
        """move_to → (프로젝트, 노드 또는 None). 프로젝트 이름이면 그 프로젝트(이름이 같은 노드), 아니면 이 프로젝트의 노드."""
        raw = " ".join(text.split())
        if "·" not in raw:
            if (found := match_project(store.list_floors(user), raw)) is not None and found.id != source:
                return found.id, None
        floor, node = find_node(user, source, raw)
        return floor, node.id

    def edit_node(user: str, node: str, project: str | None, new_name: str | None, color: str | None,
                  link: str | None, unlink: str | None) -> str:
        floor = resolve_project(store, user, project)
        floor, target = find_node(user, floor, node)
        if not (new_name or color or link or unlink):
            raise ToolError("노드에서 바꿀 것(new_name·color·link·unlink)을 준다.")
        done = []
        try:
            if new_name or color:
                changed = store.update_node(user, floor, target.id, name=new_name, color=parse_color(color) if color else None)
                done.append(f"노드 「{target.name}」" + (f" → 「{changed.name}」" if new_name else "") + (f" · 색 {color_label(changed.color or '')}" if color else ""))
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
        return f"{floor_name(store, user, floor)} 지도: " + " · ".join(done) + "."

    def category_put(
        category: str,
        author: Literal["me", "ai"],
        content: str | None = None,
        title: str | None = None,
        title_by: Literal["ai", "author"] | None = None,
        untitled: bool = False,
        fields: dict[str, str] | None = None,
        tags: list[str] | None = None,
        chapters: list[int] | None = None,
        item_id: str | None = None,
        project: str | None = None,
    ) -> str:
        user = current_user()
        found = resolve(category, project)
        if found == "ideas":
            return put_idea(user, author, content, title, title_by, untitled, fields, tags, chapters, item_id,
                            resolve_put(store, user, "ideas", project))
        if isinstance(found, str):
            raise ToolError(BUILTIN_PUT[found])
        target = found
        old = store.get_category_item(user, target.id, item_id.strip()) if item_id else None
        if item_id and old is None:
            raise ToolError(f"「{target.name}」에 항목 {item_id}가 없다. category_search 결과의 id를 준다.")
        text = (content or "").strip()
        if len(text) > CONTENT_MAX:
            raise ToolError(f"내용은 {CONTENT_MAX}자까지다.")
        values = dict(old.fields) if old else {}
        for key, value in (fields or {}).items():
            if key not in target.fields:
                raise ToolError(f"「{target.name}」에는 '{key}' 칸이 없다. 칸: {', '.join(target.fields) or '없음(제목·내용만)'}")
            value = one_line(str(value))[:FIELD_MAX]
            if value:
                values[key] = value
            else:
                values.pop(key, None)
        try:
            clean_tag_list = clean_tags(tags) if tags is not None else list(old.tags if old else ())
        except ValueError as e:
            raise ToolError(str(e)) from e
        if old is None and not text and not (title or "").strip() and not values:  # 내용·제목·칸이 모두 비었을 때만 거부
            raise ToolError("제목이나 내용 중 하나는 있어야 한다." if not target.fields else
                            f"내용·제목·칸({', '.join(target.fields)}) 중 하나는 있어야 한다.")
        links = chapter_refs(chapters, chapter_project(user, target, project)) if chapters is not None else (old.chapters if old else ())
        if old is not None and not title and not untitled:  # 고칠 때 제목을 주지 않으면 그대로
            name, by, said = old.title, old.title_by, "제목 그대로"
        else:
            name, by, said = decide_title(store, user, title, title_by, untitled)
        item = store.put_category_item(user, CategoryItem(
            id=old.id if old else new_id(), category_id=target.id, content=text or (old.content if old else ""), author=author,
            title=name, title_by=by, fields=values, tags=tuple(clean_tag_list), chapters=links,
            created_at=old.created_at if old else "",
        ))
        parts = [said, f"누가: {WHO[author]}({author})"]
        parts += [f"칸 {len(values)}"] if values else []
        parts += [f"연결된 장 {', '.join(str(n) for _, n in links)}"] if links else []
        return f"{'고침' if old else '넣음'}: 카테고리 「{target.name}」 {item.id} · " + " · ".join(parts)

    def chapter_project(user: str, target: Category, project: str | None) -> str | None:
        """장을 이을 원고: project(원고가 있으면) → 카테고리가 있는 프로젝트 → 가장 최근 원고."""
        for floor in (find_project(store, user, project).id if project and project.strip() else None, target.floor):
            if floor and floor != LIBRARY and (found := store.get_floor(user, floor)) and found.has_manuscript:
                return floor
        return None

    def put_idea(user: str, author: Literal["me", "ai"], content: str | None, title: str | None,
                 title_by: Literal["ai", "author"] | None, untitled: bool, fields: dict[str, str] | None,
                 tags: list[str] | None, chapters: list[int] | None, item_id: str | None, where: str) -> str:
        """category_put(category=생각): idea_add와 같은 규칙(제목 기본값·title_by)으로 생각에 넣는다. 누가는 author를 따른다."""
        if item_id:
            raise ToolError("생각은 이 도구로 고치지 않는다. 저자가 웹 책장에서 고치거나, 새로 넣는다.")
        extra = [f"{k}: {one_line(str(v))}" for k, v in (fields or {}).items() if str(v).strip()]
        text = "\n".join([*([content.strip()] if content and content.strip() else []), *extra]) or (title or "").strip()
        if not text:
            raise ToolError("생각에 넣을 내용(content)이 비어 있다.")
        name, by, said = decide_title(store, user, title, title_by, untitled)
        [idea] = store.add_ideas(user, [Idea(new_id(), text[:CONTENT_MAX], "thought" if author == "me" else "ai", author,
                                             title=name, title_by=by, floor=where)])
        skipped = " · 생각에는 장 연결·태그가 없어 넣지 않았다" if chapters or tags else ""
        return f"생각에 저장함 [{author}] {idea.id} · {said} · {floor_name(store, user, where)}의 생각{skipped}"

    def category_search(query: str, category: str | None = None, k: int = 8, project: str | None = None) -> str:
        user = current_user()
        k = max(1, min(k, 30))
        only = own(category, "category_search로 찾을", BUILTIN_SEARCH, project) if category else None
        scope = search_projects(store, user, project)
        cats = {c.id: c for c in store.list_categories(user, floors=scope)}
        labels = ({f.id: (LIBRARY_NAME if f.common else short(f.title, 16)) for f in store.list_floors(user)}
                  if len({c.floor for c in store.list_categories(user)}) > 1 else {})
        found: list[CategoryItem] = []
        for chunk in hybrid_search(store, user, query, ["category"], k * 4, embedder):
            cid, _, iid = chunk.owner_id.partition("/")
            if (only and cid != only.id) or cid not in cats or any(i.id == iid and i.category_id == cid for i in found):
                continue
            if item := store.get_category_item(user, cid, iid):
                found.append(item)
            if len(found) >= k:
                break
        where = f"「{only.name}」" if only else "저자가 만든 카테고리"
        if not found:
            return f"category_search {query!r} ({where}): 결과 없음. 생각·문체·문헌은 각자의 검색 도구로 찾는다."
        names: dict[str, dict[int, str]] = {}
        lines = [f"category_search {query!r} ({where}) — {len(found)}건. author=me 항목이 저자의 말이다."]
        for n, item in enumerate(found, 1):
            cat = cats.get(item.category_id)
            if item.chapters and item.chapters[0][0] not in names:
                names[item.chapters[0][0]] = {c.number: c.display for c in store.list_chapters(user, item.chapters[0][0])}
            head = f"{n}. 「{cat.name if cat else '?'}」" + (f"({labels[cat.floor]})" if cat and cat.floor in labels else "")
            head += f" {item.id} · [{item.author}] {local_time(item.created_at, '%Y-%m-%d')}"
            head += f" · 제목 「{item.title}」" + (" (AI가 지은 제목)" if item.title_by == "ai" else "") if item.title else ""
            lines += [head, f"   “{summary(item)[:200]}”"]
            if item.fields:
                lines.append("   " + " · ".join(f"{k}: {v[:60]}" for k, v in item.fields.items()))
            if item.chapters:
                lines.append("   연결된 장: " + ", ".join(names.get(p, {}).get(num, f"{num}") for p, num in item.chapters))
        return "\n".join(lines)

    def category_trash(note: str, category: str | None = None, item_id: str | None = None, project: str | None = None,
                       node: str | None = None) -> str:
        user = current_user()
        if node and not category:
            floor, target = find_node(user, resolve_project(store, user, project), node)
            try:
                gone, lost = trash_node(store, user, floor, target.id, note.strip())
            except MapError as e:
                raise _map_error(e) from e
            warn = f" 주의: {scope_names(store, user, lost)} 원고의 인용 점검은 이제 그 문헌을 보지 않는다." if lost else ""
            return (f"휴지통으로 옮김: {floor_name(store, user, floor)} 지도의 " + (f"연결 노드 「{gone.name}」(원본은 그대로)" if gone.link
                    else f"노드 「{gone.name}」") + f". {KEPT}{warn}")
        if not category:
            raise ToolError("category(책·항목) 또는 node(노드)를 준다.")
        found = resolve(category, project)
        if isinstance(found, str):  # 생각·문체 항목도 여기서(#94: idea_delete·style_delete를 합쳤다)
            return trash_builtin(user, found, note, item_id)
        target = found
        try:
            if item_id:
                moved = store.trash_category_item(user, target.id, item_id.strip(), note.strip())
                if moved is None:
                    raise ToolError(f"「{target.name}」에 항목 {item_id}가 없다. category_search 결과의 id를 준다.")
                return f"휴지통으로 옮김: 「{target.name}」의 항목 {moved.id} “{(moved.title or summary(moved))[:60]}”. {KEPT}"
            gone_cat = store.trash_category(user, target.id, note.strip())
        except ValueError as e:
            raise ToolError(str(e)) from e
        assert gone_cat is not None
        return f"휴지통으로 옮김: 카테고리 「{gone_cat.name}」 통째(항목 {gone_cat.items}개). 책장에서 빠졌다. {KEPT}"

    def trash_builtin(user: str, kind: str, note: str, item_id: str | None) -> str:
        if not item_id:
            raise ToolError(f"'{BUILTINS[kind]}'은 기본 카테고리라 통째로 옮길 수 없다. 항목 하나면 item_id를 준다.")
        if kind == "refs":
            raise ToolError("문헌은 휴지통으로 옮기지 않는다(확인한 문헌과 참고문헌 항목은 남긴다).")
        try:
            if kind == "ideas":
                moved = store.trash_idea(user, item_id.strip(), note.strip())
                if not moved:
                    raise ToolError(f"생각 {item_id}가 없다. idea_search 결과의 id를 준다.")
                replies = len(moved) - 1
                return (f"휴지통으로 옮김: 생각 {moved[0].id} “{one_line(moved[0].text)[:60]}”"
                        + (f" · 이 생각에 응답한 AI 발화 {replies}건도 함께" if replies else "") + f". {KEPT}")
            entry = store.trash_style(user, item_id.strip(), note.strip())
        except ValueError as e:
            raise ToolError(str(e)) from e
        if entry is None:
            raise ToolError(f"문체 {item_id}가 없다. style_search 결과의 id를 준다.")
        return f"휴지통으로 옮김: 문체 {entry.id} “{one_line(entry.passage)[:60]}”. {KEPT}"

    def category_title_default(mode: Literal["ask", "ai", "none"]) -> str:
        user = current_user()
        settings = store.get_shelf_settings(user)
        store.save_shelf_settings(user, ShelfSettings(settings.colors, settings.my_colors, mode))
        then = {"ask": "저장하기 전에 직접 지을지·지어 드릴지·비워 둘지 묻는다",
                "ai": "Claude가 제목을 지어 넣는다(AI가 지은 제목으로 표시된다)", "none": "제목 없이 넣는다"}[mode]
        return f"제목 기본값을 '{TITLE_MODES[mode]}'로 저장함. 앞으로 생각과 카테고리에 넣을 때 저자가 제목을 말하지 않으면 {then}."

    template_names = "·".join(TEMPLATE_NAMES)
    return [
        Tool.from_function(
            category_list, name="category_list",
            description=(
                "프로젝트마다 지도(노드·선·연결 노드)와 노드에 꽂힌 책(항목 수, 카테고리는 칸), 저자의 제목 기본값. "
                "'지도·책장 보여 줘', 넣을 곳을 되묻거나 카테고리에 넣기 전에 부른다. project를 주면 그 프로젝트만."
            ),
            structured_output=False,
        ),
        Tool.from_function(
            category_create, name="category_create",
            description=(
                "저자가 새 카테고리나 노드를 만들자고 분명히 말했을 때만 부른다(이름·템플릿을 확인받은 뒤). "
                f"template: {template_names}(카테고리. 템플릿마다 칸 몇 개) · 노드(빈 노드) · "
                "연결 노드(다른 프로젝트의 노드를 이 지도에 잇는다. name에 원본 '프로젝트 · 노드'). "
                "node: 카테고리를 꽂을 노드(없으면 이름이 같은 새 노드). name이 생각·문체·문헌이면 이 프로젝트에 그 기본 카테고리를 다시 꽂는다. "
                "color: 기본 색 이름(빨강·파랑·겨자 등 18색) 또는 #RRGGBB, 없으면 차례대로. 색에 뜻을 붙이지 않는다. "
                "카테고리 이름은 12자까지(정해진 이름·이미 있는 이름은 안 된다). " + PROJECT_PUT
            ),
            structured_output=False,
        ),
        Tool.from_function(
            category_edit, name="category_edit",
            description=(
                "저자가 책·노드의 이름·색·위치나 선을 바꾸라고 분명히 말했을 때만 부른다. category(책 이름) 또는 node(노드 이름). "
                "기본 카테고리(생각·문체·문헌)는 색·위치만. color: 기본 색 이름 또는 #RRGGBB. "
                "move_to: 책을 옮길 노드('프로젝트 · 노드'나 프로젝트 이름도). 다른 프로젝트로 가면 항목이 모두 함께 가고 같은 기본 카테고리와는 합친다. "
                "undo_move=true: 마지막 옮기기 되돌리기. node와 함께: new_name·color, link=이을 노드, unlink=끊을 노드. "
                "같은 이름이 여러 프로젝트에 있으면 project."
            ),
            structured_output=False,
        ),
        Tool.from_function(
            category_put, name="category_put",
            description=(
                "저자가 그 카테고리에 넣으라고 분명히 말했을 때만 부른다. " + BUILTIN_LINE + WHERE
                + "저자가 만든 카테고리에 항목을 넣거나(item_id를 주면) 고친다. "
                "내용·제목·칸 중 하나만 있어도 된다. "
                "category는 category_list의 이름 그대로. author: 저자의 말을 옮긴 것이면 me, Claude가 쓴 글(요약·설명)이면 ai. "
                "fields는 그 카테고리의 칸 이름: 값이다. 저자가 말하지 않은 칸은 지어내지 말고 비워 둔다. "
                "수치·출처는 저자가 말했거나 확인한 것만 넣고, Claude의 기억으로 채우지 않는다. "
                "chapters: 연결할 장 번호(book_outline의 번호). tags는 짧은 낱말 목록. "
                "project: 이 대화의 프로젝트(같은 이름을 가리고, 장을 잇는 원고, 생각이면 넣을 곳). " + TITLE_RULE
            ),
            structured_output=False,
        ),
        Tool.from_function(
            category_search, name="category_search",
            description=(
                "저자가 만든 카테고리의 항목을 찾는다(category를 주면 그 카테고리만). k=8. 결과마다 카테고리·id·누가·작성 날짜·제목·내용 앞부분·칸·연결된 장. "
                "생각·문체·문헌은 각자의 검색 도구로 찾는다. project를 주면 그 프로젝트(와 연결 노드)에서만."
            ),
            structured_output=False,
        ),
        Tool.from_function(
            category_trash, name="category_trash",
            description=(
                "저자가 그 항목·카테고리·노드를 지우라고 분명히 말했을 때만 부른다. 여러 개면 목록을 보여 주고 확인받는다. "
                "item_id면 그 항목만(category=생각이면 idea_search의 id, 응답한 AI 발화도 함께. 문체면 style_search의 id). "
                "item_id가 없으면 저자의 카테고리 통째(항목 수를 말하고 확인받은 뒤). node만 주면 그 노드(책이 있으면 먼저 옮긴다. 연결 노드는 원본 그대로). "
                "휴지통으로 옮길 뿐 지우지 않는다(운영자가 되살린다). note: 이유. 같은 이름이 여러 프로젝트에 있으면 project."
            ),
            structured_output=False,
        ),
        Tool.from_function(
            category_title_default, name="category_title_default",
            description=(
                "저자가 앞으로 제목을 어떻게 할지 정해 말했을 때만 부른다: '매번 물어봐' → ask, '앞으로는 제목 지어 줘' → ai, "
                "'앞으로는 비워 둬' → none. 생각과 저자의 카테고리에 넣을 때 이 기본값을 따른다(대화가 바뀌어도 서버에 남는다)."
            ),
            structured_output=False,
        ),
    ]

