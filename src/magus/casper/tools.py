"""생각(idea_*) MCP 도구 — Casper · 몰약. 보존하는 창고. 저자에게 보이는 글(설명·응답)에는 "생각"만 쓴다(#85·#87).

누가 말했는지를 보존한다: idea_add는 언제나 author=me, 대화 기록은 사용자 발화(me)와 AI 발화(ai)를 나눠
ai에 parent_id(응답한 사용자 발화)를 단다. 검색은 기본 me만, all이면 me를 먼저 놓는다.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.mcpserver.tools import Tool

from magus.casper.conversation import split_conversation
from magus.category.titles import TITLE_RULE, decide_title
from magus.ids import local_time, new_id
from magus.inbox import FileResolver, ResolveFile
from magus.search import Embedder, hybrid_search
from magus.store import Idea, Store
from magus.store.base import IdeaKind, Lane
from magus.store.formats import one_line

ASK = ("'저장해 줘'처럼 넣을 곳이 정해지지 않았으면 부르지 말고 생각·문체·문헌과 저자의 카테고리(category_list) 중 어디인지 먼저 묻는다"
       "(원고는 선택지에 넣지 않는다). ")
DELETE_RULE = '저자가 그 항목을 지우라고 분명히 말했을 때만 부른다. 여러 개면 목록을 보여 주고 확인받는다. '


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


def build_tools(
    store: Store, current_user: Callable[[], str], embedder: Embedder | None = None, files: ResolveFile | None = None
) -> list[Tool]:
    resolve_file = files or FileResolver(store)

    def idea_add(
        text: str,
        kind: Literal["thought", "ai", "article", "conversation", "tv", "other"],
        origin: str | None = None,
        title: str | None = None,
        title_by: Literal["ai", "author"] = "ai",
        untitled: bool = False,
    ) -> str:
        if not text.strip():
            raise ToolError("text가 비어 있다")
        kind_: IdeaKind = kind
        user = current_user()
        name, by, said = decide_title(store, user, title, title_by, untitled)  # 제목(#92): 기본값이 '매번 묻기'면 먼저 묻게 한다
        [idea] = store.add_ideas(user, [Idea(new_id(), text.strip(), kind_, "me", origin, title=name, title_by=by)])
        return f"기록함 [me] {idea.id} · {kind}" + (f" · {origin}" if origin else "") + f" · {said}"

    def idea_add_conversation(markdown: str | None = None, path: str | None = None, origin: str | None = None) -> str:
        if bool(markdown) == bool(path):
            raise ToolError("markdown(대화 기록 본문)과 path(로컬 .md 파일) 중 하나만 준다")
        if path:
            try:
                file = resolve_file(current_user(), path)[0]
            except (FileNotFoundError, ValueError) as e:
                raise ToolError(str(e)) from e
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
            head += (f" · 제목 「{idea.title}」" + (" (AI가 지은 제목)" if idea.title_by == "ai" else "")) if idea.title else ""
            lines += [head, f"   “{one_line(idea.text)[:300]}”"]
            if idea.parent_id and idea.parent_id in parents:
                lines.append(f"   ↳ 이 AI 발화가 응답한 사용자 발화: “{one_line(parents[idea.parent_id].text)[:80]}”")
        return "\n".join(lines)

    def idea_delete(id: str, note: str) -> str:
        user = current_user()
        try:
            moved = store.trash_idea(user, id.strip(), note.strip())
        except ValueError as e:
            raise ToolError(str(e)) from e
        if not moved:
            raise ToolError(f"생각 {id}가 없다. idea_search 결과의 id를 준다.")
        replies = len(moved) - 1
        return (f"휴지통으로 옮김: 생각 {moved[0].id} “{one_line(moved[0].text)[:60]}”"
                + (f" · 이 생각에 응답한 AI 발화 {replies}건도 함께" if replies else "")
                + ". 지운 것이 아니라 옮긴 것이라 운영자가 되살릴 수 있다.")

    return [
        Tool.from_function(
            idea_add,
            name="idea_add",
            description=(
                "저자가 '생각'에 넣으라고 분명히 말했을 때만 부른다. " + ASK
                + "저자의 생각 한 조각을 생각에 기록한다(author=me). kind=thought|ai|article|conversation|tv|other, "
                "origin은 출처(책·기사·방송 이름 등). " + TITLE_RULE
            ),
            structured_output=False,
        ),
        Tool.from_function(
            idea_add_conversation,
            name="idea_add_conversation",
            description=(
                "대화 기록 markdown을 발화 단위로 나눠 생각에 저장한다. markdown 본문 또는 받은함의 .md 파일 이름(path, files_list로 확인) 중 하나를 준다. "
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
                "생각에서 찾는다. author=me(기본, 저자의 생각만)|ai|all(me를 먼저). k=10. 결과마다 id가 있다. "
                "author=me 결과가 사용자의 주장이다. ai 결과에는 응답한 사용자 발화를 함께 보여 준다."
            ),
            structured_output=False,
        ),
        Tool.from_function(
            idea_delete,
            name="idea_delete",
            description=(
                DELETE_RULE + "생각 하나를 휴지통으로 옮긴다(지우지 않는다. 운영자가 되살릴 수 있다). "
                "id는 idea_search 결과의 id, note에는 지우는 이유를 쓴다. 그 생각에 응답한 AI 발화도 함께 옮긴다. "
                "휴지통의 생각은 검색·목록·웹 화면에서 빠진다."
            ),
            structured_output=False,
        ),
    ]
