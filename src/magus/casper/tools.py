"""영감(idea_*) MCP 도구 — Casper · 몰약. 보존하는 창고.

누가 말했는지를 보존한다: idea_add는 언제나 author=me, 대화 기록은 사용자 발화(me)와 AI 발화(ai)를 나눠
ai에 parent_id(응답한 사용자 발화)를 단다. 검색은 기본 me만, all이면 me를 먼저 놓는다.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Literal

from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.mcpserver.tools import Tool

from magus.casper.conversation import split_conversation
from magus.ids import local_time, new_id
from magus.search import Embedder, hybrid_search
from magus.store import Idea, Store
from magus.store.base import IdeaKind, Lane
from magus.store.formats import one_line


def add_conversation(store: Store, user_id: str, markdown: str, origin: str | None) -> tuple[str, list[Idea]]:
    split = split_conversation(markdown)
    ideas: list[Idea] = []
    for u in split.utterances:
        parent = ideas[u.parent].id if u.parent is not None else None
        ideas.append(Idea(new_id(), u.text, "conversation", u.speaker, origin, parent))
    return split.render(), store.add_ideas(user_id, ideas)


def search_ideas(
    store: Store, user_id: str, query: str, author: str, k: int, embedder: Embedder | None = None
) -> list[Idea]:
    lanes_by_author: list[list[Lane]] = {"me": [["idea_me"]], "ai": [["idea_ai"]], "all": [["idea_me"], ["idea_ai"]]}[author]
    ordered: list[str] = []
    for lanes in lanes_by_author:  # all이면 me 결과를 먼저 다 놓고 ai를 잇는다
        for chunk in hybrid_search(store, user_id, query, lanes, k * 3, embedder):
            if chunk.owner_id not in ordered:
                ordered.append(chunk.owner_id)
    ideas = store.get_ideas(user_id, ordered)
    me_first = sorted((i for i in ordered if i in ideas), key=lambda i: ideas[i].author != "me")
    return [ideas[i] for i in me_first[:k]]


def build_tools(store: Store, current_user: Callable[[], str], embedder: Embedder | None = None) -> list[Tool]:
    def idea_add(
        text: str,
        kind: Literal["thought", "ai", "article", "conversation", "tv", "other"],
        origin: str | None = None,
    ) -> str:
        if not text.strip():
            raise ToolError("text가 비어 있다")
        kind_: IdeaKind = kind
        [idea] = store.add_ideas(current_user(), [Idea(new_id(), text.strip(), kind_, "me", origin)])
        return f"기록함 [me] {idea.id} · {kind}" + (f" · {origin}" if origin else "")

    def idea_add_conversation(markdown: str | None = None, path: str | None = None, origin: str | None = None) -> str:
        if bool(markdown) == bool(path):
            raise ToolError("markdown(대화 기록 본문)과 path(로컬 .md 파일) 중 하나만 준다")
        if path:
            file = Path(path).expanduser()
            if not file.exists():
                raise ToolError(f"파일이 없다: {file}")
            markdown, origin = file.read_text(encoding="utf-8"), origin or file.stem
        report, ideas = add_conversation(store, current_user(), markdown or "", origin)
        if not ideas:
            raise ToolError("발화를 하나도 나누지 못했다. 지원 마커: **사용자:**/**Claude:**, 질문:/답변:, > 인용 뒤 **Claude 요지**\n" + report)
        return report + f"\n저장: me·ai 발화 {len(ideas)}건 (origin={origin or '-'}). ai 발화에는 응답한 사용자 발화의 id(parent_id)가 붙어 있다."

    def idea_search(query: str, author: Literal["me", "ai", "all"] = "me", k: int = 10) -> str:
        user = current_user()
        k = max(1, min(k, 30))
        ideas = search_ideas(store, user, query, author, k, embedder)
        if not ideas:
            return f"idea_search {query!r} (author={author}): 결과 없음"
        parents = store.get_ideas(user, [i.parent_id for i in ideas if i.parent_id])
        lines = [f"idea_search {query!r} (author={author}) — {len(ideas)}건. author=me 항목이 사용자의 주장이다."]
        for n, idea in enumerate(ideas, 1):
            head = f"{n}. [{idea.author}] {local_time(idea.created_at, '%Y-%m-%d')} · {idea.kind}"
            head += (f" · {idea.origin}" if idea.origin else "") + f" · {idea.id}"
            lines += [head, f"   “{one_line(idea.text)[:300]}”"]
            if idea.parent_id and idea.parent_id in parents:
                lines.append(f"   ↳ 이 AI 발화가 응답한 사용자 발화: “{one_line(parents[idea.parent_id].text)[:80]}”")
        return "\n".join(lines)

    return [
        Tool.from_function(
            idea_add,
            name="idea_add",
            description=(
                "사용자의 생각 한 조각을 기록한다(author=me). kind=thought|ai|article|conversation|tv|other, "
                "origin은 출처(책·기사·방송 이름 등)."
            ),
            structured_output=False,
        ),
        Tool.from_function(
            idea_add_conversation,
            name="idea_add_conversation",
            description=(
                "대화 기록 markdown을 발화 단위로 나눠 저장한다. markdown 본문 또는 로컬 .md 파일 path 중 하나를 준다. "
                "마커: **사용자:**/**Claude:**, 질문:/답변:, '> 인용' 뒤의 **Claude 요지**. "
                "사용자 발화 → author=me, 바로 뒤 AI 발화 → author=ai(parent_id=그 사용자 발화). "
                "리포트: me N건, ai N건, 분리 실패 구간."
            ),
            structured_output=False,
        ),
        Tool.from_function(
            idea_search,
            name="idea_search",
            description=(
                "영감 책장에서 찾는다. author=me(기본, 사용자의 생각만)|ai|all(me를 먼저). k=10. "
                "author=me 결과가 사용자의 주장이다. ai 결과에는 응답한 사용자 발화를 함께 보여 준다."
            ),
            structured_output=False,
        ),
    ]
