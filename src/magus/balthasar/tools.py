"""문체(style_*) MCP 도구 — Balthasar · 유향. 글에 배는 것. 저자에게 보이는 글(설명·응답)에는 "문체"만 쓴다(#85·#87)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.mcpserver.tools import Tool
from pydantic import BaseModel, ConfigDict, Field

from magus.project_args import PROJECT_FIND, PROJECT_PUT, floor_name, labels_for, resolve_put, search_projects
from magus.balthasar.style import tags_text, validate_tags
from magus.ids import new_id
from magus.search import Embedder, hybrid_search
from magus.store import Store, StyleEntry
from magus.store.formats import one_line
from magus.casper.tools import ASK


class StyleTags(BaseModel):
    """구절과 이유에서 호출자가 추출해 넘기는 문체 태그."""

    model_config = ConfigDict(extra="forbid")
    호흡: str = Field(description="문장 길이·리듬. 예: 짧고 끊김, 긴 만연체")
    시점: str = Field(description="예: 1인칭, 3인칭 관찰, 2인칭 호명")
    열기: str = Field(description="단락·장을 여는 방식. 예: 장면, 질문, 인용, 수치")
    장치: list[str] = Field(default_factory=list, description="수사 장치 목록. 예: 반복, 대구, 생략, 비유")
    어미: str = Field(description="예: -다 체, -요 체, 명사형 종결")
    톤: str = Field(description="예: 건조함, 다정함, 아이러니")


NO_REASON = "'(저자가 이유를 밝히지 않음)'"  # 이유를 지어내지 않는다. 비워 둔 표시만 남긴다
TAGS_BY = {"ai": "태그는 AI가 뽑음", "author": "태그는 저자가 정함"}  # #89


def build_tools(store: Store, current_user: Callable[[], str], embedder: Embedder | None = None) -> list[Tool]:
    def style_add(
        passage: str, reason: str, tags: StyleTags, work: str | None = None, tags_by: Literal["ai", "author"] = "ai",
        project: str | None = None,
    ) -> str:
        if not passage.strip() or not reason.strip():
            raise ToolError("passage(구절)와 reason(왜 좋은지)이 모두 필요하다. 저자가 이유를 말하지 않았으면 " + NO_REASON + "이라고 쓴다")
        try:
            clean = validate_tags(tags.model_dump())
        except ValueError as e:
            raise ToolError(str(e)) from e
        user = current_user()
        where = resolve_put(store, user, "styles", project)  # 그 프로젝트의 문체, 없으면 연결 노드가 가리키는 문체(#95)
        entry = store.add_style(user, StyleEntry(new_id(), passage.strip(), reason.strip(), clean, work, tags_by=tags_by, floor=where))
        return (f"문체에 기록함 {entry.id}" + (f" · {work}" if work else "") + f" · {floor_name(store, user, where)}의 문체"
                + f" · {tags_text(clean)} ({TAGS_BY[tags_by]})")

    def style_search(query: str, k: int = 5, project: str | None = None) -> str:
        user = current_user()
        k = max(1, min(k, 20))
        only = search_projects(store, user, project, "styles")
        ids: list[str] = []
        for chunk in hybrid_search(store, user, query, ["style"], k * (6 if only else 2), embedder):
            if chunk.owner_id not in ids:
                ids.append(chunk.owner_id)
        entries = store.get_styles(user, ids)
        found = [entries[i] for i in ids if i in entries and (only is None or entries[i].floor in only)][:k]
        labels = labels_for(store, user, "styles")
        if not found:
            return f"style_search {query!r}: 결과 없음"
        lines = [f"style_search {query!r} — {len(found)}건. 제안할 때 이 취향을 근거로 밝힌다."]
        for n, e in enumerate(found, 1):
            lines += [
                f"{n}. {e.id}" + (f" · {e.work}" if e.work else "") + (f" · {labels[e.floor]}" if e.floor in labels else ""),
                f"   구절: “{one_line(e.passage)[:300]}”",
                f"   이유: {one_line(e.reason)[:200]}",
                f"   태그: {tags_text(e.tags)}" + (f" ({TAGS_BY[e.tags_by]})" if e.tags_by else ""),
            ]
        return "\n".join(lines)

    return [
        Tool.from_function(
            style_add,
            name="style_add",
            description=(
                "저자가 '문체'에 넣으라고 분명히 말했을 때만 부른다. " + ASK
                + "저자가 좋아하는 구절을 문체에 기록한다. passage(구절), reason(왜 좋은지), work(출처 작품). "
                "reason에는 저자가 말한 이유만 쓴다. 말하지 않았으면 지어내지 말고 " + NO_REASON + "이라고 남긴다(저자가 나중에 더할 수 있다). "
                "tags는 구절과 이유에서 먼저 추출해 넘긴다: {호흡, 시점, 열기, 장치: [], 어미, 톤}. 서버는 스키마만 검증한다. "
                "tags_by: Claude가 뽑았으면 ai(기본), 저자가 직접 말한 태그면 author. "
                + PROJECT_PUT
            ),
            structured_output=False,
        ),
        Tool.from_function(
            style_search,
            name="style_search",
            description="문체에서 찾는다(reason + tags 기준). id, passage, reason, tags를 돌려준다. k=5. 문체 작업 전에 먼저 부른다. " + PROJECT_FIND,
            structured_output=False,
        ),
    ]
