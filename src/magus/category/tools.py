"""카테고리(category_*) MCP 도구(#92). 카테고리 이름을 인자로 받는 범용 도구 일곱 개로 끝낸다.

카테고리마다 도구를 만들지 않는다: 사용자마다 도구 목록이 달라지고, instructions 조립(등록된 도구만 언급)이 깨진다.
생각·문체·문헌은 기본 카테고리다. 넣는 것·찾는 것은 각자의 도구(idea_*·style_*·ref_*)로 하고, 여기서는 책 색만 바꾼다.
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
from magus.category.titles import TITLE_RULE, decide_title
from magus.ids import local_time, new_id
from magus.search import Embedder, hybrid_search
from magus.store import Category, CategoryItem, ShelfSettings, Store
from magus.store.formats import one_line

WHERE = ("'저장해 줘'처럼 넣을 곳이 정해지지 않았으면 부르지 말고 생각·문체·문헌과 저자의 카테고리(category_list) 중 어디인지 먼저 묻는다"
         "(원고는 선택지에 넣지 않는다). ")
WHO = {"me": "저자의 말", "ai": "Claude가 쓴 글"}
BUILTIN_BY_KEY = {name_key(name): key for key, name in BUILTINS.items()}


def _template_line(c: Category) -> str:
    template = TEMPLATE_BY_KEY.get(c.template)
    name = template.name if template else c.template
    return f"{name} 템플릿" + (f"(칸: {', '.join(c.fields)})" if c.fields else "(칸 없음: 제목·내용만)")


def build_tools(store: Store, current_user: Callable[[], str], embedder: Embedder | None = None) -> list[Tool]:
    def resolve(category: str) -> Category | str:
        """카테고리 이름(또는 id) → 저자의 카테고리, 또는 기본 카테고리의 주소 이름(ideas|styles|refs)."""
        key = name_key(clean_name(category))
        if key in BUILTIN_BY_KEY:
            return BUILTIN_BY_KEY[key]
        for c in store.list_categories(current_user()):
            if name_key(c.name) == key or c.id == category.strip():
                return c
        raise ToolError(f"'{category}' 카테고리가 없다. category_list로 이름을 확인한다.")

    def own(category: str, action: str) -> Category:
        found = resolve(category)
        if isinstance(found, str):
            raise ToolError(f"'{BUILTINS[found]}'은 기본 카테고리라 {action} 수 없다. {BUILTINS[found]}에 넣는 것은 {BUILTIN_TOOLS[found]}로 한다.")
        return found

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

    def category_list() -> str:
        user = current_user()
        settings = store.get_shelf_settings(user)
        counts = {"ideas": len(store.list_ideas(user)), "styles": len(store.list_styles(user)), "refs": len(store.list_refs(user))}
        mine = store.list_categories(user)
        lines = [f"책장의 카테고리 {3 + len(mine)}개(기본 3 + 저자가 만든 {len(mine)}) · 제목 기본값: {TITLE_MODES[settings.title_default]}"]
        lines.append("기본 카테고리(넣을 때는 각자의 도구): " + " · ".join(
            f"{BUILTINS[k]} {counts[k]}개({BUILTIN_TOOLS[k]}, 색 {color_label(settings.colors.get(k, DEFAULT_COLORS[k]))})"
            for k in BUILTINS))
        if mine:
            lines.append("저자가 만든 카테고리(넣을 때는 category_put, 이름 그대로):")
            lines += [f"- {c.name} · {_template_line(c)} · 항목 {c.items} · 색 {color_label(c.color)}" for c in mine]
        else:
            lines.append("저자가 만든 카테고리는 아직 없다(category_create로 만든다).")
        if settings.title_default == "ask":
            lines.append("제목: 저자가 제목을 말하지 않았으면 저장하기 전에 직접 지을지·지어 드릴지·비워 둘지 묻는다.")
        elif settings.title_default == "ai":
            lines.append("제목: 저자가 제목을 말하지 않았으면 Claude가 지어 title_by=ai로 넣는다(묻지 않는다).")
        else:
            lines.append("제목: 저자가 제목을 말하지 않았으면 비워 둔다(묻지 않는다).")
        return "\n".join(lines)

    def category_create(name: str, template: Literal["빈 카테고리", "인물", "사례", "수치", "용어"] = "빈 카테고리",
                        color: str | None = None) -> str:
        user = current_user()
        mine = store.list_categories(user)
        if len(mine) >= MAX_CATEGORIES:
            raise ToolError(f"카테고리는 {MAX_CATEGORIES}개까지 만들 수 있다(기본 셋 빼고). 쓰지 않는 카테고리를 휴지통으로 옮긴 뒤 만든다.")
        try:
            clean = check_name(name, {name_key(c.name): c.name for c in mine})
            kind = template_of(template)
            hex_ = parse_color(color) if color else PALETTE_BY_NAME[NEW_COLOR_ORDER[len(mine) % len(NEW_COLOR_ORDER)]]
            made = store.create_category(user, clean, kind.key, hex_, tuple(f for f, _ in kind.fields))
        except ValueError as e:
            raise ToolError(str(e)) from e
        return f"카테고리를 만듦: 「{made.name}」 · {_template_line(made)} · 색 {color_label(made.color)}. 책장에 꽂혔다."

    def category_edit(category: str, new_name: str | None = None, color: str | None = None) -> str:
        if not new_name and not color:
            raise ToolError("바꿀 것(new_name 또는 color)을 준다.")
        user = current_user()
        found = resolve(category)
        try:
            hex_ = parse_color(color) if color else None
            if isinstance(found, str):  # 기본 카테고리: 색만
                if new_name:
                    raise ToolError(f"'{BUILTINS[found]}'은 기본 카테고리라 이름을 바꿀 수 없다(색은 바꿀 수 있다).")
                settings = store.get_shelf_settings(user)
                assert hex_ is not None
                store.save_shelf_settings(user, ShelfSettings({**settings.colors, found: hex_}, settings.my_colors,
                                                              settings.title_default))
                return f"「{BUILTINS[found]}」 책 색을 {color_label(hex_)}으로 바꿈."
            taken = {name_key(c.name): c.name for c in store.list_categories(user) if c.id != found.id}
            clean = check_name(new_name, taken) if new_name else None
            changed = store.update_category(user, found.id, name=clean, color=hex_)
        except ValueError as e:
            raise ToolError(str(e)) from e
        done = ([f"이름 「{found.name}」 → 「{changed.name}」"] if clean else []) + ([f"책 색 {color_label(changed.color)}"] if hex_ else [])
        return f"카테고리를 고침: {' · '.join(done)}."

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
    ) -> str:
        user = current_user()
        target = own(category, "category_put으로 넣을")
        old = store.get_category_item(user, target.id, item_id.strip()) if item_id else None
        if item_id and old is None:
            raise ToolError(f"「{target.name}」에 항목 {item_id}가 없다. category_search 결과의 id를 준다.")
        text = (content or "").strip()
        if not text and old is None:
            raise ToolError("content(내용)가 비어 있다.")
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

    def category_search(query: str, category: str | None = None, k: int = 8) -> str:
        user = current_user()
        k = max(1, min(k, 30))
        only = own(category, "category_search로 찾을") if category else None
        cats = {c.id: c for c in store.list_categories(user)}
        found: list[CategoryItem] = []
        for chunk in hybrid_search(store, user, query, ["category"], k * 4, embedder):
            cid, _, iid = chunk.owner_id.partition("/")
            if (only and cid != only.id) or any(i.id == iid and i.category_id == cid for i in found):
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
            head = f"{n}. 「{cat.name if cat else '?'}」 {item.id} · [{item.author}] {local_time(item.created_at, '%Y-%m-%d')}"
            head += f" · 제목 「{item.title}」" + (" (AI가 지은 제목)" if item.title_by == "ai" else "") if item.title else ""
            lines += [head, f"   “{one_line(item.content)[:200]}”"]
            if item.fields:
                lines.append("   " + " · ".join(f"{k}: {v[:60]}" for k, v in item.fields.items()))
            if item.chapters:
                lines.append("   연결된 장: " + ", ".join(names.get(p, {}).get(num, f"{num}") for p, num in item.chapters))
        return "\n".join(lines)

    def category_trash(category: str, note: str, item_id: str | None = None) -> str:
        user = current_user()
        target = own(category, "휴지통으로 옮길")
        try:
            if item_id:
                moved = store.trash_category_item(user, target.id, item_id.strip(), note.strip())
                if moved is None:
                    raise ToolError(f"「{target.name}」에 항목 {item_id}가 없다. category_search 결과의 id를 준다.")
                return (f"휴지통으로 옮김: 「{target.name}」의 항목 {moved.id} “{one_line(moved.title or moved.content)[:60]}”. "
                        "지운 것이 아니라 옮긴 것이라 운영자가 되살릴 수 있다.")
            gone = store.trash_category(user, target.id, note.strip())
        except ValueError as e:
            raise ToolError(str(e)) from e
        assert gone is not None
        return (f"휴지통으로 옮김: 카테고리 「{gone.name}」 통째(항목 {gone.items}개). 책장에서 빠졌다. "
                "지운 것이 아니라 옮긴 것이라 운영자가 되살릴 수 있다.")

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
                "책장의 카테고리 목록: 기본 카테고리(생각·문체·문헌)와 저자가 만든 카테고리의 이름·템플릿·칸·항목 수·책 색, "
                "그리고 저자의 제목 기본값. 넣을 곳을 되묻거나 카테고리에 넣기 전에 먼저 부른다."
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
                "이름은 12자까지이고, 정해진 이름(생각·문체·문헌·원고·전체·확인 요청 등)과 이미 있는 이름은 쓸 수 없다."
            ),
            structured_output=False,
        ),
        Tool.from_function(
            category_edit, name="category_edit",
            description=(
                "저자가 카테고리의 이름이나 책 색을 바꾸라고 분명히 말했을 때만 부른다. category는 지금 이름. "
                "기본 카테고리(생각·문체·문헌)는 색만 바꿀 수 있다. color는 기본 색 이름 또는 #RRGGBB "
                "(예: '사례 카테고리를 빨간색으로' → category=사례, color=빨강)."
            ),
            structured_output=False,
        ),
        Tool.from_function(
            category_put, name="category_put",
            description=(
                "저자가 그 카테고리에 넣으라고 분명히 말했을 때만 부른다. " + WHERE
                + "저자가 만든 카테고리에 항목을 넣거나(item_id를 주면) 고친다. 생각·문체·문헌은 각자의 도구(idea_add·style_add·ref_add)로 넣는다. "
                "category는 category_list의 이름 그대로. author: 저자의 말을 옮긴 것이면 me, Claude가 쓴 글(요약·설명)이면 ai. "
                "fields는 그 카테고리의 칸 이름: 값이다. 저자가 말하지 않은 칸은 지어내지 말고 비워 둔다. "
                "수치·출처는 저자가 말했거나 확인한 것만 넣고, Claude의 기억으로 채우지 않는다. "
                "chapters는 연결할 장 번호(지금 책, book_outline의 번호). tags는 짧은 낱말 목록. " + TITLE_RULE
            ),
            structured_output=False,
        ),
        Tool.from_function(
            category_search, name="category_search",
            description=(
                "저자가 만든 카테고리의 항목을 찾는다(category를 주면 그 카테고리만). k=8. 결과마다 카테고리·id·누가·작성 날짜·제목·내용 앞부분·칸·연결된 장. "
                "생각·문체·문헌은 각자의 검색 도구로 찾는다."
            ),
            structured_output=False,
        ),
        Tool.from_function(
            category_trash, name="category_trash",
            description=(
                "저자가 그 카테고리(또는 그 안의 항목)를 지우라고 분명히 말했을 때만 부른다. 여러 개면 목록을 보여 주고 확인받는다. "
                "item_id를 주면 그 항목만, 없으면 카테고리를 통째로 휴지통으로 옮긴다(지우지 않는다. 운영자가 되살릴 수 있다). "
                "통째로 옮길 때는 항목 수를 저자에게 말하고 확인받은 뒤 부른다. note에는 지우는 이유를 쓴다. "
                "기본 카테고리(생각·문체·문헌)는 통째로 옮길 수 없다."
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
