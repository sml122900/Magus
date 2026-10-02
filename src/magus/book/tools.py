"""원고(book_*) MCP 도구. 도구는 얇게 두고, 실제 일은 Store와 이 패키지의 함수가 한다.

front matter는 도구 경계를 넘지 않는다. 읽기는 본문(content)과 메타를 별도 필드로 주고,
쓰기는 본문만 받는다. 호출자가 front matter를 붙여 보내면 벗겨 내고 경고를 돌려준다.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, Literal

from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.mcpserver.tools import Tool

from magus.book.outline import build_outline
from magus.store import Issue, Project, Store
from magus.store.base import ChapterStatus
from magus.store.formats import one_line, strip_front_matter

FRONT_MATTER_WARNING = (
    "content 앞의 front matter를 벗겨 냈습니다. 메타(제목·상태·버전·note)는 서버가 관리하니 본문만 보내세요. "
    "제목·상태를 바꾸려면 title·status 인자를 쓰세요."
)
UNVERIFIED_CITES_MEANING = "unverified_cites: null은 아직 검사 전(ref_check 전), []는 검사했고 미확인 인용이 없다는 뜻."
ISSUE_LIST_MAX = 200


def _json(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False)


def _issue_line(i: Issue) -> str:
    parts = [f"I{i.id}", i.status]
    if i.chapter_number is not None:
        parts.append(f"{i.chapter_number}장")
    parts += [i.origin, i.kind + (f"→{i.ref_key}" if i.ref_key else "")]
    line = "- " + " · ".join(parts) + f" · {one_line(i.text)[:300]}"
    return line + (f" · 닫음: {one_line(i.closed_note)}" if i.closed_note else "")


def build_tools(store: Store, current_user: Callable[[], str]) -> list[Tool]:
    def resolve_project(project_id: str | None) -> Project:
        project = store.get_project(current_user(), project_id)
        if project is None:
            raise ToolError(f"프로젝트 {project_id!r}가 없습니다." if project_id else "프로젝트가 없습니다. book_import로 원고를 가져오세요.")
        return project

    def book_outline(project_id: str | None = None) -> str:
        return build_outline(store, current_user(), project_id)

    def book_read_chapter(number: int, project_id: str | None = None) -> str:
        user, project = current_user(), resolve_project(project_id)
        chapter = store.read_chapter(user, project.id, number)
        if chapter is None:
            have = ", ".join(str(c.number) for c in store.list_chapters(user, project.id)) or "없음"
            raise ToolError(f"{number}장이 없습니다. 있는 장: {have}")
        m = chapter.meta
        open_issues = store.list_issues(user, project.id, "open", chapter_number=number)
        return _json(
            {
                "project_id": project.id,
                "number": m.number,
                "title": m.title,
                "status": m.status,
                "part_number": m.part_number,
                "version": m.version,
                "last_note": m.last_note,
                "updated_at": m.updated_at,
                "char_count": m.char_count,
                "unverified_cites": None,  # ref_check(4단계) 전에는 검사하지 않는다. null = 미검사
                "open_issues": [f"I{i.id} {one_line(i.text)[:120]}" for i in open_issues],
                "content": chapter.content,
            }
        )

    def book_write_chapter(
        number: int,
        content: str,
        note: str,
        title: str | None = None,
        status: ChapterStatus | None = None,
        project_id: str | None = None,
    ) -> str:
        project = resolve_project(project_id)
        body, had_front_matter = strip_front_matter(content)
        if not body:
            raise ToolError("본문이 비어 있습니다. 장을 지우려는 것이라면 book_issue_add로 남겨 주세요.")
        try:
            meta = store.write_chapter(current_user(), project.id, number, body, note, title=title, status=status)
        except ValueError as e:
            raise ToolError(str(e)) from e
        return _json(
            {
                "project_id": project.id,
                "number": meta.number,
                "title": meta.title,
                "status": meta.status,
                "version": meta.version,
                "archived_version": meta.version - 1 if meta.version > 1 else None,
                "char_count": meta.char_count,
                "unverified_cites": None,  # 4단계에서 ref_check를 자동 실행해 채운다
                "warnings": [FRONT_MATTER_WARNING] if had_front_matter else [],
            }
        )

    def book_issues(
        status: Literal["open", "closed", "all"] = "open",
        chapter_number: int | None = None,
        origin: Literal["import_comment", "user", "agent"] | None = None,
        kind: Literal["citation", "general"] | None = None,
        limit: int = 50,
        project_id: str | None = None,
    ) -> str:
        project = resolve_project(project_id)
        issues = store.list_issues(
            current_user(),
            project.id,
            None if status == "all" else status,
            chapter_number=chapter_number,
            origin=origin,
            kind=kind,
        )
        limit = max(1, min(limit, ISSUE_LIST_MAX))
        filters = [f"status={status}"] + [
            f"{name}={value}"
            for name, value in (("chapter", chapter_number), ("origin", origin), ("kind", kind))
            if value is not None
        ]
        head = f"미해결 {len(issues)}건 ({', '.join(filters)})"
        if len(issues) > limit:
            head += f" — 앞 {limit}건만 표시. 조건을 좁히거나 limit을 늘리세요(최대 {ISSUE_LIST_MAX})."
        return "\n".join([head, *(_issue_line(i) for i in issues[:limit])])

    return [
        Tool.from_function(
            book_outline,
            name="book_outline",
            description=(
                "모든 원고 작업의 첫 호출. 첫 줄에 프로젝트, 장 목록(장별 상태·글자수·미해결 수·미확인 인용 수 집계), "
                "직접 남긴(user·agent) 열린 미해결, 최근 결정 10개, 최근 변경 5개를 3,000 토큰 이하로 돌려준다. "
                "코멘트 유래 미해결은 건수만 싣는다(book_issues로 조회). 본문은 담지 않는다. "
                "project_id를 생략하면 가장 최근 프로젝트."
            ),
            structured_output=False,
        ),
        Tool.from_function(
            book_read_chapter,
            name="book_read_chapter",
            description=(
                "장 하나를 읽는다. JSON: content(본문 markdown만), title, status, part_number, version, last_note, "
                "unverified_cites, open_issues(이 장의 열린 미해결). 필요한 장만 읽는다. " + UNVERIFIED_CITES_MEANING
            ),
            structured_output=False,
        ),
        Tool.from_function(
            book_write_chapter,
            name="book_write_chapter",
            description=(
                "장 하나를 저장한다. content는 본문만(front matter 없이). 이전 본문은 versions/에 보관되고 버전이 1 오른다. "
                "note에 무엇을 바꿨는지 쓴다. 없는 번호면 새 장을 만든다(title로 제목 지정). "
                "제목·상태는 title·status 인자로만 바꾼다. status는 draft|revising|done. 빈 본문은 거부한다. "
                + UNVERIFIED_CITES_MEANING
            ),
            structured_output=False,
        ),
        Tool.from_function(
            book_issues,
            name="book_issues",
            description=(
                "미해결 목록(조회 전용). status=open|closed|all, chapter_number, origin=import_comment|user|agent, "
                "kind=citation|general로 거른다. 한 줄에 하나: 번호·상태·장·출처·종류(citation이면 →ref_key 후보)·내용. "
                f"limit 기본 50, 최대 {ISSUE_LIST_MAX}."
            ),
            structured_output=False,
        ),
    ]
