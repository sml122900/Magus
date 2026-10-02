"""문체(style_*) MCP 도구 — Balthasar · 유향. 글에 배는 것."""

from __future__ import annotations

from collections.abc import Callable

from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.mcpserver.tools import Tool
from pydantic import BaseModel, ConfigDict, Field

from magus.balthasar.style import tags_text, validate_tags
from magus.ids import new_id
from magus.search import Embedder, hybrid_search
from magus.store import Store, StyleEntry
from magus.store.formats import one_line


class StyleTags(BaseModel):
    """구절과 이유에서 호출자가 추출해 넘기는 문체 태그."""

    model_config = ConfigDict(extra="forbid")
    호흡: str = Field(description="문장 길이·리듬. 예: 짧고 끊김, 긴 만연체")
    시점: str = Field(description="예: 1인칭, 3인칭 관찰, 2인칭 호명")
    열기: str = Field(description="단락·장을 여는 방식. 예: 장면, 질문, 인용, 수치")
    장치: list[str] = Field(default_factory=list, description="수사 장치 목록. 예: 반복, 대구, 생략, 비유")
    어미: str = Field(description="예: -다 체, -요 체, 명사형 종결")
    톤: str = Field(description="예: 건조함, 다정함, 아이러니")


def build_tools(store: Store, current_user: Callable[[], str], embedder: Embedder | None = None) -> list[Tool]:
    def style_add(passage: str, reason: str, tags: StyleTags, work: str | None = None) -> str:
        if not passage.strip() or not reason.strip():
            raise ToolError("passage(구절)와 reason(왜 좋은지)이 모두 필요하다")
        try:
            clean = validate_tags(tags.model_dump())
        except ValueError as e:
            raise ToolError(str(e)) from e
        entry = store.add_style(current_user(), StyleEntry(new_id(), passage.strip(), reason.strip(), clean, work))
        return f"기록함 {entry.id}" + (f" · {work}" if work else "") + f" · {tags_text(clean)}"

    def style_search(query: str, k: int = 5) -> str:
        user = current_user()
        k = max(1, min(k, 20))
        ids: list[str] = []
        for chunk in hybrid_search(store, user, query, ["style"], k * 2, embedder):
            if chunk.owner_id not in ids:
                ids.append(chunk.owner_id)
        entries = store.get_styles(user, ids)
        found = [entries[i] for i in ids if i in entries][:k]
        if not found:
            return f"style_search {query!r}: 결과 없음"
        lines = [f"style_search {query!r} — {len(found)}건. 제안할 때 이 취향을 근거로 밝힌다."]
        for n, e in enumerate(found, 1):
            lines += [
                f"{n}. {e.id}" + (f" · {e.work}" if e.work else ""),
                f"   구절: “{one_line(e.passage)[:300]}”",
                f"   이유: {one_line(e.reason)[:200]}",
                f"   태그: {tags_text(e.tags)}",
            ]
        return "\n".join(lines)

    return [
        Tool.from_function(
            style_add,
            name="style_add",
            description=(
                "사용자가 좋아하는 문체 구절을 기록한다. passage(구절), reason(왜 좋은지), work(출처 작품). "
                "tags는 구절과 이유에서 먼저 추출해 넘긴다: {호흡, 시점, 열기, 장치: [], 어미, 톤}. 서버는 스키마만 검증한다. "
                "검색은 reason + tags로 한다(구절의 주제가 아니라 문체로 찾기 위해)."
            ),
            structured_output=False,
        ),
        Tool.from_function(
            style_search,
            name="style_search",
            description="문체 취향을 찾는다(reason + tags 기준). passage, reason, tags를 돌려준다. k=5. 문체 작업 전에 먼저 부른다.",
            structured_output=False,
        ),
    ]
