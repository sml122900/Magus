"""카테고리(category_*) MCP 도구(#92). 카테고리 이름을 인자로 받는 범용 도구 일곱 개로 끝낸다.

카테고리마다 도구를 만들지 않는다: 사용자마다 도구 목록이 달라지고, instructions 조립(등록된 도구만 언급)이 깨진다.
생각·문체·문헌은 기본 카테고리다. 넣는 것·찾는 것은 각자의 도구(idea_*·style_*·ref_*)로 하고, 여기서는 책 색과 층만 바꾼다.
층(#93): 카테고리는 공용 층이나 작업물 층에 꽂힌다. 이름은 층마다 하나라서, 같은 이름이 여러 층에 있으면 floor로 가린다.
옮기기·되돌리기는 도구 수를 늘리지 않고 category_edit의 move_to·undo_move로 한다.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.mcpserver.tools import Tool

from magus.category.rules import (
    BUILTIN_TOOLS, BUILTINS, CONTENT_MAX, DEFAULT_COLORS, FIELD_MAX, MAX_CATEGORIES, NEW_COLOR_ORDER, PALETTE_BY_NAME,
    TEMPLATE_BY_KEY, TEMPLATE_NAMES, TITLE_MODES, check_name, clean_name, clean_tags, color_label, name_key, parse_color,
    template_of,
)
from magus.category.moves import error_message, move_book, tool_message, undo_move as undo_last
from magus.category.titles import TITLE_RULE, decide_title
from magus.floor_args import FLOOR_PUT, floors_text, match_floor, resolve_floor, search_floors, short
from magus.floors import COMMON
from magus.store.floors import MoveError
from magus.ids import local_time, new_id
from magus.search import Embedder, hybrid_search
from magus.store import Category, CategoryItem, Idea, ShelfSettings, Store
from magus.store.formats import one_line

WHERE = ("'저장해 줘'처럼 넣을 곳이 정해지지 않았으면 부르지 말고 생각·문체·문헌과 저자의 카테고리(category_list) 중 어디인지 먼저 묻는다"
         "(원고는 선택지에 넣지 않는다). ")
WHO = {"me": "저자의 말", "ai": "Claude가 쓴 글"}
BUILTIN_BY_KEY = {name_key(name): key for key, name in BUILTINS.items()}
# 생각·문체·문헌은 기본 카테고리다. 도구를 그때그때 찾아 불러오는 클라이언트에서는 Claude가 idea_add 대신 category_put을 부르기도 한다
# (2026-10-06 비밀 대화 시험). 생각은 여기서도 idea_add와 같은 규칙으로 받고, 문체·문헌은 맞는 도구 이름을 알려 준다.
BUILTIN_LINE = "생각·문체·문헌은 기본 카테고리다. 생각은 이 도구로도 들어가지만, 문체는 style_add, 문헌은 ref_add로 넣는다. "
BUILTIN_PUT = {
    "styles": "문체는 이 도구로 넣지 않는다. style_add 도구를 찾아 쓴다(구절과 저자가 말한 이유가 필요하다).",
    "refs": "문헌은 이 도구로 넣지 않는다. ref_add 도구를 찾아 쓴다(서지와, 원문에서 고른 발췌와 그 이유가 필요하다).",
}
BUILTIN_SEARCH = {"ideas": "idea_search", "styles": "style_search", "refs": "ref_search"}


def _template_line(c: Category) -> str:
    template = TEMPLATE_BY_KEY.get(c.template)
    name = template.name if template else c.template
    return f"{name} 템플릿" + (f"(칸: {', '.join(c.fields)})" if c.fields else "(칸 없음: 제목·내용만)")


def build_tools(store: Store, current_user: Callable[[], str], embedder: Embedder | None = None) -> list[Tool]:
    def resolve(category: str, floor: str | None = None) -> Category | str:
        """카테고리 이름(또는 id) → 저자의 카테고리, 또는 기본 카테고리의 주소 이름(ideas|styles|refs).
        같은 이름이 여러 층에 있으면 floor로 가린다(#93)."""
        key = name_key(clean_name(category))
        if key in BUILTIN_BY_KEY:
            return BUILTIN_BY_KEY[key]
        user = current_user()
        found = [c for c in store.list_categories(user, floors=search_floors(store, user, floor))
                 if name_key(c.name) == key or c.id == category.strip()]
        if len(found) == 1:
            return found[0]
        if not found:
            raise ToolError(f"'{category}' 카테고리가 없다. category_list로 이름을 확인한다.")
        order = [f for f in store.list_floors(user) if any(c.floor == f.id for c in found)]  # 위에서 아래로(공용 먼저)
        raise ToolError(f"「{found[0].name}」 카테고리가 여러 층에 있다({', '.join(f.label for f in order)}). "
                        "floor로 어느 층의 것인지 준다.")

    def builtin_floor(user: str, kind: str, floor: str | None, put: bool = False) -> str:
        """기본 카테고리(kind)의 층. put이면 넣을 층(규칙 12: 그 층에 없으면 공용의 것)."""
        floors = store.list_floors(user)
        where = [f for f in floors if kind in f.builtins]
        if floor and floor.strip():
            found = match_floor(floors, floor)
            if found is None:
                raise ToolError(f"'{floor}' 층을 찾지 못했다. 층: {floors_text(floors)}")
            if put:
                return store.place(user, kind, found.id)
            if kind not in found.builtins:
                raise ToolError(f"{found.label}에는 {BUILTINS[kind]}이 없다. {BUILTINS[kind]}이 있는 층: "
                                f"{', '.join(f.label for f in where) or '없음'}")
            return found.id
        if put:
            return store.place(user, kind, resolve_floor(store, user, None))
        if len(where) == 1:
            return where[0].id
        raise ToolError(f"{BUILTINS[kind]}이 여러 층에 있다({', '.join(f.label for f in where)}). floor로 어느 층의 것인지 준다."
                        if where else f"{BUILTINS[kind]}이 꽂힌 층이 없다.")

    def own(category: str, action: str, tools: dict[str, str] = BUILTIN_TOOLS, floor: str | None = None) -> Category:
        found = resolve(category, floor)
        if isinstance(found, str):
            raise ToolError(f"'{BUILTINS[found]}'은 기본 카테고리라 {action} 수 없다. {tools[found]} 도구를 찾아 쓴다.")
        return found

    def summary(item: CategoryItem) -> str:
        """항목을 한 줄로: 내용, 없으면 채워진 칸(예: 장소: 엘알토)."""
        return one_line(item.content) or " · ".join(f"{k}: {v}" for k, v in item.fields.items() if v)

    def chapter_refs(chapters: list[int] | None, project_id: str | None) -> tuple[tuple[str, int], ...]:
        if not chapters:
            return ()
        user = current_user()
        project = store.get_project(user, project_id)
        if project is None:
            raise ToolError(f"프로젝트 {project_id!r}가 없다." if project_id else "원고가 없어 장을 이을 수 없다.")
        known = {c.number for c in store.list_chapters(user, project.id)}
        if missing := sorted(set(chapters) - known):
            raise ToolError(f"『{project.title}』에 없는 장 번호: {missing}. book_outline의 장 번호를 쓴다.")
        return tuple((project.id, n) for n in dict.fromkeys(chapters))

    def category_list(floor: str | None = None) -> str:
        user = current_user()
        settings = store.get_shelf_settings(user)
        floors = store.list_floors(user)
        show = [f for f in floors if f.id in (search_floors(store, user, floor) or [f.id])]
        mine = store.list_categories(user)
        verified = {f.id: 0 for f in floors}
        counts: dict[tuple[str, str], int] = {}
        for kind, items in (("ideas", store.list_ideas(user)), ("styles", store.list_styles(user)), ("refs", store.list_refs(user))):
            for item in items:
                counts[(kind, item.floor or COMMON)] = counts.get((kind, item.floor or COMMON), 0) + 1
                if kind == "refs" and item.status == "verified":
                    verified[item.floor or COMMON] = verified.get(item.floor or COMMON, 0) + 1
        total = sum(len(f.builtins) for f in floors) + len(mine)
        lines = [f"책장: 층 {len(floors)}개({floors_text(floors)}) · 카테고리 {total}개 · 제목 기본값: {TITLE_MODES[settings.title_default]}"]
        lines.append(BUILTIN_LINE.strip() + " 저자가 만든 카테고리는 category_put으로 넣는다(이름 그대로).")
        for f in show:
            lines.append(f"## {f.label}" + ("" if f.common else f" 「{short(f.title)}」({f.id}) · 원고 {'있음' if f.has_manuscript else '없음'}"))
            for k in f.builtins:
                n = counts.get((k, f.id), 0)
                extra = f"(확인 {verified.get(f.id, 0)})" if k == "refs" else ""
                lines.append(f"- {BUILTINS[k]} {n}개{extra} · 기본({BUILTIN_TOOLS[k]}) · 색 "
                             f"{color_label(settings.colors.get(k, DEFAULT_COLORS[k]))}")
            lines += [f"- {c.name} · {_template_line(c)} · 항목 {c.items} · 색 {color_label(c.color)}" for c in mine if c.floor == f.id]
            if not f.builtins and not any(c.floor == f.id for c in mine):
                lines.append("- (비어 있음)")
        if not mine:
            lines.append("저자가 만든 카테고리는 아직 없다(category_create로 만든다).")
        if settings.title_default == "ask":
            lines.append("제목: 저자가 제목을 말하지 않았으면 저장하기 전에 직접 지을지·지어 드릴지·비워 둘지 묻는다.")
        elif settings.title_default == "ai":
            lines.append("제목: 저자가 제목을 말하지 않았으면 Claude가 지어 title_by=ai로 넣는다(묻지 않는다).")
        else:
            lines.append("제목: 저자가 제목을 말하지 않았으면 비워 둔다(묻지 않는다).")
        return "\n".join(lines)

    def category_create(name: str, template: Literal["빈 카테고리", "인물", "사례", "수치", "용어"] = "빈 카테고리",
                        color: str | None = None, floor: str | None = None) -> str:
        user = current_user()
        mine = store.list_categories(user)
        if len(mine) >= MAX_CATEGORIES:
            raise ToolError(f"카테고리는 {MAX_CATEGORIES}개까지 만들 수 있다(기본 셋 빼고). 쓰지 않는 카테고리를 휴지통으로 옮긴 뒤 만든다.")
        where = resolve_floor(store, user, floor)
        try:
            clean = check_name(name, {name_key(c.name): c.name for c in mine if c.floor == where})
            kind = template_of(template)
            hex_ = parse_color(color) if color else PALETTE_BY_NAME[NEW_COLOR_ORDER[len(mine) % len(NEW_COLOR_ORDER)]]
            made = store.create_category(user, clean, kind.key, hex_, tuple(f for f, _ in kind.fields), where)
        except ValueError as e:
            raise ToolError(str(e)) from e
        return (f"카테고리를 만듦: 「{made.name}」 · {_template_line(made)} · 색 {color_label(made.color)}. "
                f"{floor_label(user, where)}에 꽂혔다.")

    def floor_label(user: str, floor_id: str) -> str:
        found = store.get_floor(user, floor_id)
        return found.label if found else floor_id

    def category_edit(category: str, new_name: str | None = None, color: str | None = None, floor: str | None = None,
                      move_to: str | None = None, undo_move: bool = False) -> str:
        if not new_name and not color and not move_to and not undo_move:
            raise ToolError("바꿀 것(new_name·color·move_to) 또는 undo_move를 준다.")
        user = current_user()
        found = resolve(category, floor)
        book = found if isinstance(found, str) else found.id
        if undo_move:  # 마지막 옮기기 되돌리기(#93). 그 카테고리를 옮긴 것일 때만
            last = store.last_move(user)
            if last is None or last.book != book:
                raise ToolError(f"되돌릴 수 있는 것은 마지막 옮기기뿐이다. 마지막으로 옮긴 것: 「{last.name}」." if last else "되돌릴 옮기기가 없다.")
            try:
                return tool_message(store, user, undo_last(store, user, last.id), undone=True)
            except MoveError as e:
                raise ToolError(error_message(e, polite=False)) from e
        done: list[str] = []
        try:
            hex_ = parse_color(color) if color else None
            if isinstance(found, str):  # 기본 카테고리: 색과 층만
                if new_name:
                    raise ToolError(f"'{BUILTINS[found]}'은 기본 카테고리라 이름을 바꿀 수 없다(색·층은 바꿀 수 있다).")
                if hex_:
                    settings = store.get_shelf_settings(user)
                    store.save_shelf_settings(user, ShelfSettings({**settings.colors, found: hex_}, settings.my_colors,
                                                                  settings.title_default))
                    done.append(f"「{BUILTINS[found]}」 책 색을 {color_label(hex_)}으로 바꿈")  # 색은 종류마다 하나(모든 층의 생각)
            elif new_name or hex_:
                taken = {name_key(c.name): c.name for c in store.list_categories(user, floors=[found.floor]) if c.id != found.id}
                clean = check_name(new_name, taken) if new_name else None
                changed = store.update_category(user, found.id, name=clean, color=hex_)
                done += ([f"이름 「{found.name}」 → 「{changed.name}」"] if clean else []) + (
                    [f"책 색 {color_label(changed.color)}"] if hex_ else [])
        except ValueError as e:
            raise ToolError(str(e)) from e
        if move_to:  # 기본 카테고리는 어느 층의 것인지 알아야 한다(색은 종류마다 하나라 층이 필요 없다)
            source = builtin_floor(user, found, floor) if isinstance(found, str) else found.floor
            target = match_floor(store.list_floors(user), move_to)
            if target is None:
                raise ToolError(f"'{move_to}' 층을 찾지 못했다. 층: {floors_text(store.list_floors(user))}")
            try:
                done.append(tool_message(store, user, move_book(store, user, book, source, target.id)))
            except MoveError as e:
                raise ToolError(" · ".join([*done, error_message(e, polite=False)])) from e
        return (" · ".join(done) + "." if isinstance(found, str) else "카테고리를 고침: " + " · ".join(done) + ".").replace("..", ".")

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
        project_id: str | None = None,
        floor: str | None = None,
    ) -> str:
        user = current_user()
        found = resolve(category, floor)
        if found == "ideas":
            return put_idea(user, author, content, title, title_by, untitled, fields, tags, chapters, item_id,
                            builtin_floor(user, "ideas", floor, put=True))
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
        if chapters and not project_id and target.floor != COMMON:  # 작업물 층의 카테고리면 그 작업물의 장
            project_id = target.floor
        links = chapter_refs(chapters, project_id) if chapters is not None else (old.chapters if old else ())
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
        return f"생각에 저장함 [{author}] {idea.id} · {said} · {floor_label(user, where)}의 생각{skipped}"

    def category_search(query: str, category: str | None = None, k: int = 8, floor: str | None = None) -> str:
        user = current_user()
        k = max(1, min(k, 30))
        only = own(category, "category_search로 찾을", BUILTIN_SEARCH, floor) if category else None
        cats = {c.id: c for c in store.list_categories(user, floors=search_floors(store, user, floor))}
        labels = {f.id: f.label for f in store.list_floors(user)} if len({c.floor for c in store.list_categories(user)}) > 1 else {}
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

    def category_trash(category: str, note: str, item_id: str | None = None, floor: str | None = None) -> str:
        user = current_user()
        found = resolve(category, floor)
        if isinstance(found, str):  # 생각·문체 항목도 여기서(#94: idea_delete·style_delete를 합쳤다)
            return trash_builtin(user, found, note, item_id)
        target = found
        try:
            if item_id:
                moved = store.trash_category_item(user, target.id, item_id.strip(), note.strip())
                if moved is None:
                    raise ToolError(f"「{target.name}」에 항목 {item_id}가 없다. category_search 결과의 id를 준다.")
                return (f"휴지통으로 옮김: 「{target.name}」의 항목 {moved.id} “{(moved.title or summary(moved))[:60]}”. "
                        "지운 것이 아니라 옮긴 것이라 운영자가 되살릴 수 있다.")
            gone = store.trash_category(user, target.id, note.strip())
        except ValueError as e:
            raise ToolError(str(e)) from e
        assert gone is not None
        return (f"휴지통으로 옮김: 카테고리 「{gone.name}」 통째(항목 {gone.items}개). 책장에서 빠졌다. "
                "지운 것이 아니라 옮긴 것이라 운영자가 되살릴 수 있다.")

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
                        + (f" · 이 생각에 응답한 AI 발화 {replies}건도 함께" if replies else "")
                        + ". 지운 것이 아니라 옮긴 것이라 운영자가 되살릴 수 있다.")
            entry = store.trash_style(user, item_id.strip(), note.strip())
        except ValueError as e:
            raise ToolError(str(e)) from e
        if entry is None:
            raise ToolError(f"문체 {item_id}가 없다. style_search 결과의 id를 준다.")
        return f"휴지통으로 옮김: 문체 {entry.id} “{one_line(entry.passage)[:60]}”. 지운 것이 아니라 옮긴 것이라 운영자가 되살릴 수 있다."

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
                "책장의 층(공용·작업물마다 한 층)과 층마다 꽂힌 카테고리: 기본 카테고리(생각·문체·문헌)와 저자가 만든 카테고리의 "
                "이름·템플릿·칸·항목 수·책 색, 그리고 저자의 제목 기본값. 넣을 곳을 되묻거나 카테고리에 넣기 전에 먼저 부른다. "
                "floor를 주면 그 층만."
            ),
            structured_output=False,
        ),
        Tool.from_function(
            category_create, name="category_create",
            description=(
                "저자가 새 카테고리를 만들자고 분명히 말했을 때만 부른다. 이름과 템플릿을 저자에게 확인받은 뒤 부른다. "
                f"template: {template_names}(칸은 템플릿마다 몇 개뿐이고, 모든 항목에 제목·내용이 있다). "
                "color는 기본 색 이름(빨강·주황·노랑·초록·파랑·남색·보라·분홍·갈색·회색·검정·미색·자주·짙은 초록·청록·겨자·하늘·먹색) "
                "또는 #RRGGBB이고, 주지 않으면 차례대로 정해진다. 색에 뜻을 붙이지 않는다(뜻은 저자가 정한다). "
                "이름은 12자까지이고, 정해진 이름(생각·문체·문헌·원고·전체·확인 요청 등)과 그 층에 이미 있는 이름은 쓸 수 없다. "
                + FLOOR_PUT
            ),
            structured_output=False,
        ),
        Tool.from_function(
            category_edit, name="category_edit",
            description=(
                "저자가 카테고리의 이름·책 색·층을 바꾸라고 분명히 말했을 때만 부른다. category는 지금 이름, "
                "같은 이름이 여러 층에 있으면 floor로 가린다. "
                "기본 카테고리(생각·문체·문헌)는 이름은 못 바꾸고 색·층만 바꾼다. color는 기본 색 이름 또는 #RRGGBB "
                "(예: '사례 카테고리를 빨간색으로' → category=사례, color=빨강). "
                "move_to: 옮길 층(공용·1층·작업물 id). 항목이 모두 함께 간다. 받는 층에 같은 기본 카테고리가 있으면 합치고, "
                "같은 이름의 저자 카테고리가 있으면 옮기지 않는다. "
                "undo_move=true: 저자가 방금 옮긴 것을 되돌리라고 할 때(마지막 옮기기만)."
            ),
            structured_output=False,
        ),
        Tool.from_function(
            category_put, name="category_put",
            description=(
                "저자가 그 카테고리에 넣으라고 분명히 말했을 때만 부른다. " + BUILTIN_LINE + WHERE
                + "저자가 만든 카테고리에 항목을 넣거나(item_id를 주면) 고친다. "
                "내용·제목·칸 중 하나만 있어도 된다(빈 카테고리는 제목이나 내용). "
                "category는 category_list의 이름 그대로. author: 저자의 말을 옮긴 것이면 me, Claude가 쓴 글(요약·설명)이면 ai. "
                "fields는 그 카테고리의 칸 이름: 값이다. 저자가 말하지 않은 칸은 지어내지 말고 비워 둔다. "
                "수치·출처는 저자가 말했거나 확인한 것만 넣고, Claude의 기억으로 채우지 않는다. "
                "chapters는 연결할 장 번호(그 카테고리가 꽂힌 작업물 또는 지금 책, book_outline의 번호). tags는 짧은 낱말 목록. "
                "floor: 같은 이름이 여러 층에 있을 때 가린다(생각이면 넣을 층). " + TITLE_RULE
            ),
            structured_output=False,
        ),
        Tool.from_function(
            category_search, name="category_search",
            description=(
                "저자가 만든 카테고리의 항목을 찾는다(category를 주면 그 카테고리만). k=8. 결과마다 카테고리·id·누가·작성 날짜·제목·내용 앞부분·칸·연결된 장. "
                "생각·문체·문헌은 각자의 검색 도구로 찾는다. floor를 주면 그 층의 카테고리에서만 찾는다."
            ),
            structured_output=False,
        ),
        Tool.from_function(
            category_trash, name="category_trash",
            description=(
                "저자가 그 항목(또는 저자가 만든 카테고리)을 지우라고 분명히 말했을 때만 부른다. 여러 개면 목록을 보여 주고 확인받는다. "
                "item_id를 주면 그 항목만 휴지통으로 옮긴다(생각·문체 항목도 여기서: category=생각이면 idea_search의 id, 그 생각에 응답한 AI 발화도 함께. "
                "category=문체면 style_search의 id). item_id가 없으면 저자가 만든 카테고리를 통째로 옮긴다(항목 수를 말하고 확인받은 뒤). "
                "지우지 않는다(운영자가 되살릴 수 있다). note에는 지우는 이유. 같은 이름이 여러 층에 있으면 floor로 가린다."
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
