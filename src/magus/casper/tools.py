"""대화 기록 넣기(idea_add_conversation) — Casper · 몰약. 보존하는 창고.

#96: 생각은 여느 책의 글이 됐다. 한 조각 넣기·찾기·지우기는 category_put·category_search·category_trash가 한다.
여기에는 대화 기록 한 편을 발화로 나눠 책에 넣는 도구 하나만 남는다. 누가 말했는지를 보존한다:
사용자 발화는 author=me, 바로 뒤의 AI 발화는 author=ai이고 parent_id(응답한 사용자 발화)가 붙는다.
"""

from __future__ import annotations

from collections.abc import Callable

from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.mcpserver.tools import Tool

from magus.casper.conversation import split_conversation
from magus.category.books import writable_book
from magus.contexts import view_for_book
from magus.ids import new_id
from magus.inbox import FileResolver, ResolveFile
from magus.project_args import floor_name
from magus.search import Embedder
from magus.store import CategoryItem, Store


def add_conversation(store: Store, user_id: str, markdown: str, origin: str | None, book: str) -> tuple[str, list[CategoryItem]]:
    """대화 기록 → 책(카테고리 id)의 글. (리포트, 넣은 글)."""
    split = split_conversation(markdown)
    items: list[CategoryItem] = []
    for u in split.utterances:
        parent = items[u.parent].id if u.parent is not None else None
        item = CategoryItem(new_id(), book, u.text, u.speaker, parent_id=parent, origin=origin, kind="conversation")
        items.append(store.put_category_item(user_id, item))
    return split.render(), items


def build_tools(
    store: Store, current_user: Callable[[], str], embedder: Embedder | None = None, files: ResolveFile | None = None
) -> list[Tool]:
    resolve_file = files or FileResolver(store)

    def idea_add_conversation(book: str, markdown: str | None = None, path: str | None = None, origin: str | None = None,
                              project: str | None = None) -> str:
        if bool(markdown) == bool(path):
            raise ToolError("markdown(대화 기록 본문)과 path(올린 .md 파일 이름) 중 하나만 준다")
        user = current_user()
        target = writable_book(store, user, book, project)
        key, name = target.key, target.name
        if path:
            try:
                file = resolve_file(user, path)[0]
            except (FileNotFoundError, ValueError) as e:
                raise ToolError(str(e)) from e
            markdown, origin = file.read_text(encoding="utf-8"), origin or file.stem
        report, items = add_conversation(store, user, markdown or "", origin, key)
        if not items:
            raise ToolError("발화를 하나도 나누지 못했다. 지원 마커: **사용자:**/**Claude:**, 질문:/답변:, > 인용 뒤 **Claude 요지**\n" + report)
        category = store.get_category(user, key)
        return (view_for_book(store, user, key).header() + "\n" + report
                + f"\n넣음: 「{name}」({floor_name(store, user, category.floor if category else '')})에 발화 {len(items)}개 "
                f"(origin={origin or '-'}). AI 발화에는 응답한 사용자 발화의 id(parent_id)가 붙어 있다.")

    return [
        Tool.from_function(
            idea_add_conversation,
            name="idea_add_conversation",
            description=(
                "대화 기록 markdown을 발화 단위로 나눠 책(book)에 글로 넣는다. markdown 본문 또는 올린 .md 파일 이름(path) 중 하나. "
                "마커: **사용자:**/**Claude:**, 질문:/답변:, '> 인용' 뒤의 **Claude 요지**. "
                "사용자 발화 → author=me, 바로 뒤 AI 발화 → author=ai(응답한 발화를 parent_id로). 리포트: me N건, ai N건, 분리 실패 구간."
            ),
            structured_output=False,
        ),
    ]
