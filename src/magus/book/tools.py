"""원고(book_*) MCP 도구. 도구는 얇게 두고, 실제 일은 Store와 이 패키지의 함수가 한다.

front matter는 도구 경계를 넘지 않는다. 읽기는 본문(content)과 메타를 별도 필드로 주고,
쓰기는 본문만 받는다. 호출자가 front matter를 붙여 보내면 벗겨 내고 경고를 돌려준다.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any, Literal

from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.mcpserver.tools import Tool

from magus.book.comments import source_label
from magus.book.export import export_docx
from magus.book.importer import import_manuscript
from magus.book.outline import build_outline
from magus.book.reupload import reupload_manuscript
from magus.contexts import attach_manuscript_context, view_for_book
from magus.melchior.check import CheckResult, Resolver, check_chapter, check_text, terms_of
from magus.inbox import FileResolver, ResolveFile
from magus.store import BookTitles, Issue, Project, Store
from magus.limits import ChapterNumber, Note, Text, Title
from magus.store.base import CHAPTER_RANGE, CHAPTER_STATUS_NAMES, STALE_REASONS, ChapterStatus, chapter_number_ok
from magus.store.formats import one_line, strip_front_matter

FRONT_MATTER_WARNING = (
    "content 앞의 front matter를 벗겨 냈습니다. 메타(제목·상태·버전·note)는 서버가 관리하니 본문만 보내세요. "
    "제목·상태를 바꾸려면 title·status 인자를 쓰세요."
)
ISSUE_LIST_MAX = 200


def check_number(number: int | None) -> None:
    """읽기 도구의 장 번호 범위(2026-10-09 점검 15-2). 스키마는 그대로 두고(커넥터 재연결 없이) 서버에서 안내한다."""
    if number is not None and not chapter_number_ok(number):
        raise ToolError(CHAPTER_RANGE)


def _json(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False)


def _gate(result: CheckResult) -> dict[str, Any]:
    return {"unverified_cites": result.unverified_cites(), "needs_source": result.needs_source}


def _chapter_name(number: int, labels: dict[int, str]) -> str:
    return labels.get(number) or f"{number}장"


def _issue_line(i: Issue, labels: dict[int, str]) -> str:
    parts = [f"I{i.id}", i.status]
    if i.chapter_number is not None:
        parts.append(_chapter_name(i.chapter_number, labels) + (f" ¶{i.paragraph}" if i.paragraph else ""))
    kind = i.kind + (f"→{i.ref_key}" if i.ref_key else "")
    if i.kind == "citation" and i.ref_key:
        kind += f" ⇒ {i.ref_id}" if i.ref_id and i.ref_id != i.ref_key else ("" if i.ref_id else " ⇒ refs 없음")
    parts += [source_label(i), kind]
    if i.stale:  # 다시 올린 뒤 원고에서 코멘트·걸린 문장이 사라짐(#76). 닫지 않고 표시만 한다
        parts.append(f"해결됐을 수 있음({STALE_REASONS[i.stale]}{f', E{i.stale_edition}' if i.stale_edition else ''})")
    line = "- " + " · ".join(parts) + f" · {one_line(i.text)[:300]}"
    return line + (f" · 닫음: {one_line(i.closed_note)}" if i.closed_note else "")


def build_tools(
    store: Store,
    current_user: Callable[[], str],
    files: ResolveFile | None = None,
    export_link: Callable[[str, str], str] | None = None,
) -> list[Tool]:
    resolve_file = files or FileResolver(store)
    def resolve_project(project_id: str | None) -> Project:
        project = store.get_project(current_user(), project_id)
        if project is None:
            raise ToolError(f"프로젝트 {project_id!r}가 없습니다." if project_id else "프로젝트가 없습니다. book_import로 문서를 가져오세요.")
        return project

    def book_outline(project_id: str | None = None) -> str:
        return build_outline(store, current_user(), project_id)

    def book_read_chapter(number: ChapterNumber, project_id: str | None = None) -> str:
        user, project = current_user(), resolve_project(project_id)
        check_number(number)
        chapter = store.read_chapter(user, project.id, number)
        if chapter is None:
            have = ", ".join(str(c.number) for c in store.list_chapters(user, project.id)) or "없음"
            raise ToolError(f"{number}장이 없습니다. 있는 장: {have}")
        m = chapter.meta
        open_issues = store.list_issues(user, project.id, "open", chapter_number=number)
        return _json(
            {
                "context": view_for_book(store, user, f"ms.{project.id}").header(),  # 컨텍스트를 머리에(#96)
                "project_id": project.id,
                "number": m.number,
                "label": m.display,
                "title": m.title,
                "status": CHAPTER_STATUS_NAMES.get(m.status, m.status),  # 웹과 같은 말(초안·고치는 중·완성, 2026-10-10)
                "part_number": m.part_number,
                "version": m.version,
                "last_note": m.last_note,
                "updated_at": m.updated_at,
                "char_count": m.char_count,
                **_gate(check_text(store, user, chapter.content, Resolver(store, user, project.id), terms_of(store, user, project.id))),
                "open_issues": [
                    f"I{i.id}{f' ¶{i.paragraph}' if i.paragraph else ''}{' [AI 확인 요청]' if i.by_ai else ''}"
                    f"{' [해결됐을 수 있음: ' + STALE_REASONS[i.stale] + ']' if i.stale else ''} "
                    f"{one_line(i.text)[:120]}"
                    for i in open_issues
                ],
                "content": chapter.content,
            }
        )

    def book_write_chapter(
        number: ChapterNumber,
        content: str,
        note: Note,
        title: Title | None = None,
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
        # 인용 게이트: 쓰기를 막지 않고, 쓴 뒤에 검사해서 결과를 돌려주고 장별 집계를 갱신한다.
        gate = check_chapter(store, current_user(), project.id, number)
        return _json(
            {
                "context": view_for_book(store, current_user(), f"ms.{project.id}").header(),
                "project_id": project.id,
                "number": meta.number,
                "title": meta.title,
                "status": CHAPTER_STATUS_NAMES.get(meta.status, meta.status),
                "version": meta.version,
                "archived_version": meta.version - 1 if meta.version > 1 else None,
                "char_count": meta.char_count,
                **(_gate(gate) if gate else {"unverified_cites": None, "needs_source": None}),
                "warnings": [FRONT_MATTER_WARNING] if had_front_matter else [],
            }
        )

    def book_issues(
        status: Literal["open", "closed", "all"] = "open",
        chapter_number: ChapterNumber | None = None,
        origin: Literal["import_comment", "user", "agent"] | None = None,
        kind: Literal["citation", "fact", "general"] | None = None,
        limit: int = 50,
        project_id: str | None = None,
        possibly_resolved: bool = False,
    ) -> str:
        project = resolve_project(project_id)
        check_number(chapter_number)
        issues = store.list_issues(
            current_user(),
            project.id,
            None if status == "all" else status,
            chapter_number=chapter_number,
            origin=origin,
            kind=kind,
        )
        if possibly_resolved:
            issues = [i for i in issues if i.stale]
        limit = max(1, min(limit, ISSUE_LIST_MAX))
        filters = [f"status={status}"] + [
            f"{name}={value}"
            for name, value in (("chapter", chapter_number), ("origin", origin), ("kind", kind))
            if value is not None
        ] + (["해결됐을 수 있음만"] if possibly_resolved else [])
        head = f"확인 요청 {len(issues)}건 ({', '.join(filters)})"
        if len(issues) > limit:
            head += f" — 앞 {limit}건만 표시. 조건을 좁히거나 limit을 늘리세요(최대 {ISSUE_LIST_MAX})."
        labels = {c.number: c.label for c in store.list_chapters(current_user(), project.id) if c.label}
        context = view_for_book(store, current_user(), f"ms.{project.id}").header()
        return "\n".join([context, head, *(_issue_line(i, labels) for i in issues[:limit])])

    def book_decide(text: Text, project_id: str | None = None) -> str:
        project = resolve_project(project_id)
        try:
            d = store.add_decision(current_user(), project.id, text)
        except ValueError as e:
            raise ToolError(str(e)) from e
        return f"D{d.id} 기록함 ({project.id}): {one_line(d.text)[:120]}"

    def book_issue_add(
        text: Text,
        chapter_number: ChapterNumber | None = None,
        origin: Literal["user", "agent"] = "user",
        project_id: str | None = None,
    ) -> str:
        project = resolve_project(project_id)
        where = ""
        check_number(chapter_number)
        if chapter_number is not None:
            if (chapter := store.read_chapter(current_user(), project.id, chapter_number)) is None:
                raise ToolError(f"{chapter_number}장이 없습니다.")
            where = f" · {chapter.meta.label or f'{chapter_number}장'}"
        try:
            issue = store.add_issue(current_user(), project.id, text, origin=origin, chapter_number=chapter_number)
        except ValueError as e:
            raise ToolError(str(e)) from e
        return f"I{issue.id} 열림 ({project.id}{where} · {origin}): {one_line(issue.text)[:120]}"

    def book_issue_close(id: str, note: Note | None = None, project_id: str | None = None) -> str:
        project = resolve_project(project_id)
        number = id.strip().upper().removeprefix("I")
        if not re.fullmatch(r"[0-9]+", number):  # isdigit은 '²'·'１'도 참이다(점검 15-4: int('²')에서 내부 오류)
            raise ToolError(f"확인 요청 번호 형식이 아닙니다: {id!r} (예: I3 또는 3)")
        issue = store.close_issue(current_user(), project.id, int(number), note)
        if issue is None:
            raise ToolError(f"I{number}이 없습니다. book_issues로 번호를 확인하세요.")
        return f"I{issue.id} 닫음" + (f": {one_line(issue.closed_note)}" if issue.closed_note else "")

    def book_export(path: str | None = None, project_id: str | None = None) -> str:
        project = resolve_project(project_id)
        user = current_user()
        try:
            location = export_docx(store, user, project, path)
        except ValueError as e:  # 이름이 너무 김 등(점검 15-5)
            raise ToolError(str(e)) from e
        where = f"내려받기(24시간 안, 같은 계정으로 로그인 필요): {export_link(user, location)}" if export_link else location
        return f"docx를 만들었다: {where}\n(코멘트·그림은 복원하지 않는다. 자리표시자 [그림 N]·[수식]이 그대로 남는다. 표는 Word 표로 나간다.)"

    def book_import(
        path: str | None = None,
        project_id: str | None = None,
        title: Title | None = None,
        subtitle: Title | None = None,
        replace: bool = False,
        new_edition: bool = False,
        force: bool = False,
    ) -> str:
        user = current_user()
        if not path or not path.strip():  # 원고 없이 제목만 있는 프로젝트(#93·#95). 원고는 나중에 같은 project_id로 가져온다
            if new_edition or replace:
                raise ToolError("수정본·바꾸기에는 문서 파일(path)이 필요하다.")
            if not title or not title.strip():
                raise ToolError("올린 문서 없이 프로젝트를 만들려면 제목(title)을 준다. 문서를 가져오려면 path에 files_list의 이름을 준다.")
            try:
                made = store.create_project(user, " ".join(title.split())[:120], project_id=project_id or None,
                                            titles=BookTitles(subtitle=subtitle) if subtitle else None)
            except ValueError as e:
                raise ToolError(str(e)) from e
            return (f"올린 문서가 없는 프로젝트를 만듦: 「{made.title}」({made.id}). 지도에 가운데 노드가 있다. "
                    f"문서는 저자가 게시판 글에 첨부한 뒤, book_import(path=files_list의 이름, project_id={made.id})로 가져온다.")
        if new_edition:
            if not project_id:
                raise ToolError("수정본으로 올릴 책의 project_id를 주세요(book_outline 첫 줄의 괄호 안).")
            try:
                again = reupload_manuscript(
                    store, user, resolve_file(user, path)[0], project_id, title=title, subtitle=subtitle, force=force
                )
            except (ValueError, FileNotFoundError) as e:
                raise ToolError(str(e)) from e
            return "\n\n".join(
                [view_for_book(store, user, f"ms.{project_id}").header(),
                 again.summary(), "### 바뀐 장", again.change_table(),
                 f"이 리포트는 올린 문서의 '수정본 이력'(E{again.edition})에서 저자도 볼 수 있다."]
            )
        try:
            report = import_manuscript(
                store, user, resolve_file(user, path)[0], project_id=project_id, title=title, subtitle=subtitle,
                replace=replace,
            )
        except (ValueError, FileNotFoundError) as e:
            raise ToolError(str(e)) from e
        attach_manuscript_context(store, user, report.project_id)
        return "\n\n".join(
            [
                view_for_book(store, user, f"ms.{report.project_id}").header(),
                report.summary(),
                "### ch-NN.md ↔ 장 제목",
                report.mapping_table(),
                "코멘트 분류 전체 표와 이 리포트는 올린 문서의 '수정본 이력'에서 저자도 볼 수 있다(원본 사본도 함께 보관).",
            ]
        )

    return [
        Tool.from_function(
            book_decide,
            name="book_decide",
            description="책에 대한 결정을 기록한다(D번호, 다시 쓰지 않는 일련번호). 최근 10개가 outline에 보인다.",
            structured_output=False,
        ),
        Tool.from_function(
            book_issue_add,
            name="book_issue_add",
            description=(
                "확인 요청(열린 문제)을 남긴다. chapter_number: 장. origin: 저자가 남기라고 했으면 user, 스스로 발견했으면 agent."
            ),
            structured_output=False,
        ),
        Tool.from_function(
            book_issue_close,
            name="book_issue_close",
            description="확인 요청을 닫는다. id는 'I3' 또는 '3', note에 해결 방법. 번호는 다시 쓰지 않는다.",
            structured_output=False,
        ),
        Tool.from_function(
            book_export,
            name="book_export",
            description=(
                "장들을 합쳐 docx를 만든다(path는 파일 이름만, exports/에 저장). 코멘트·그림은 복원하지 않는다."
            ),
            structured_output=False,
        ),
        Tool.from_function(
            book_import,
            name="book_import",
            description=(
                (
                "올린 문서(docx, 없으면 pdf)를 새 프로젝트(또는 올린 문서가 없는 project_id)의 가운데 노드로 가져온다. path: files_list의 이름(첨부는 '첨부:<id>'). 문서 없이 프로젝트만 "
                "만들면 path 없이 title. '제N부'·'제N장'으로 장을 나누고, Word 코멘트는 확인 요청, 참고문헌은 원문 확인 전 문헌 글로 넣는다. 수정본은 new_edition=true와 그 책의 "
                "project_id: 바뀐 장만 바꾸고(E2, E3…), 같은 코멘트는 다시 넣지 않고, 사라진 코멘트는 '해결됐을 수 있음' 표시만 한다(결정·직접 남긴 확인 요청·다른 책은 그대로). 마지막 수정본과 같은 "
                "파일이거나 장 제목이 30% 미만 겹치면 멈춘다(맞으면 force=true). replace=true는 기존 프로젝트를 통째 휴지통으로 보내니 수정본에 쓰지 않는다. title·subtitle을 비우면 문서에서 "
                "읽는다. 리포트와 장 매핑표를 돌려준다."
            )
            ),
            structured_output=False,
        ),
        Tool.from_function(
            book_outline,
            name="book_outline",
            description=(
                (
                "모든 올린 문서 작업의 첫 호출(저자의 '전체'). 프로젝트, 장 목록(상태·글자수·확인 요청·미확인 인용 수), 직접 남긴 열린 확인 요청, 최근 결정 10·변경 5를 3,000토큰 이하로. 코멘트 유래 확인 "
                "요청은 건수만(book_issues). 본문 없음. project_id가 없으면 최근 프로젝트."
            )
            ),
            structured_output=False,
        ),
        Tool.from_function(
            book_read_chapter,
            name="book_read_chapter",
            description=(
                (
                "장 하나를 읽는다(필요한 장만). number: 제N장 N, 서장 0, 맺음 90, 부록 N은 90+N, 제N부 들어가며 100+N(outline 괄호 숫자). JSON: content(본문만), title, "
                "status, part_number, version, last_note, needs_source, unverified_cites(원문 확인이 안 된 인용 {key, status, count, cited_as}. "
                "null은 아직 검사 전, []는 검사했고 없음), open_issues(¶N은 content의 N번째 문단. [AI 확인 요청]은 AI가 단 코멘트라 저자에게도 그렇게 알린다)."
            )
            ),
            structured_output=False,
        ),
        Tool.from_function(
            book_write_chapter,
            name="book_write_chapter",
            description=(
                (
                "저자가 'Magus의 올린 문서에 저장'하라고 분명히 말했을 때만 부른다. 넣을 곳을 되묻는 선택지에도 올린 문서를 넣지 않는다. 그 밖에는 수정안을 대화로 내고 저자가 원본 파일에 반영한다. 장 하나를 "
                "저장한다(다음 수정본이 오면 저자 파일 내용으로 바뀐다). content는 본문만, note에 바꾼 것. 이전 본문은 versions/로, 버전 +1. 없는 번호면 새 장(title). 빈 본문은 거부. 응답: "
                "unverified_cites(null은 아직 검사 전, []는 검사했고 없음)·needs_source."
            )
            ),
            structured_output=False,
        ),
        Tool.from_function(
            book_issues,
            name="book_issues",
            description=(
                (
                "확인 요청 목록(조회 전용). status·chapter_number·origin·kind(citation 문헌 지목|fact 사실·수치|general)로 거른다. 한 줄: "
                "번호·상태·장·출처·종류(→ref_key)·내용. 'AI 확인 요청'은 AI가 단 코멘트라 저자에게도 그렇게 밝힌다. possibly_resolved=true: 수정본 뒤 코멘트·걸린 문장이 사라져 '해결됐을 수 "
                "있음'인 것만(자동으로 닫지 않는다. 저자 확인 뒤 book_issue_close). limit 기본 50, 최대 200."
            )
            ),
            structured_output=False,
        ),
    ]
