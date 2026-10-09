"""문헌(ref_*) MCP 도구 — Melchior · 황금. 검증된 근거만.

#96: 문헌 한 편 넣기(옛 ref_add)·찾기(옛 ref_search)는 글 넣기·찾기(category_put·category_search)에 합쳤다.
여기에는 참고문헌 목록 가져오기와 장의 인용 점검이 남는다(올린 문서의 기능이라 컨텍스트와 상관없다)."""

from __future__ import annotations

import json
from collections.abc import Callable

from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.mcpserver.tools import Tool

from magus.category.books import writable_book
from magus.contexts import view_for_book
from magus.project_args import PROJECT_PUT, floor_name, resolve_project
from magus.melchior.bibliography import import_bibliography
from magus.melchior.check import after_refs_changed, check_chapter
from magus.inbox import ResolveFile
from magus.search import Embedder
from magus.store import Store


def build_tools(
    store: Store, current_user: Callable[[], str], embedder: Embedder | None = None, files: ResolveFile | None = None
) -> list[Tool]:
    def ref_import_bibliography(text: str, project: str | None = None, book: str | None = None) -> str:
        user = current_user()
        floor = resolve_project(store, user, project)
        target = writable_book(store, user, book, project).key if book else None
        report = import_bibliography(store, user, text, floor, target)
        linked = after_refs_changed(store, user)
        head = view_for_book(store, user, report.book).header() + "\n" if report.book else ""
        shelf = store.get_category(user, report.book) if report.book else None
        return (
            head + report.render()
            + (f"\n새 항목을 넣은 책: 「{shelf.name}」({floor_name(store, user, shelf.floor)})." if shelf else "")
            + f"\n확인 요청과의 연결 변경 {linked}건. 모두 원문 확인 전이다. 저자가 원문을 읽고 고른 대목이 있는 문헌만 "
            "category_put(checked=true)으로 원문 확인이 된다."
        )

    def ref_check(chapter_number: int, project_id: str | None = None) -> str:
        user = current_user()
        project = store.get_project(user, project_id)
        if project is None:
            raise ToolError("프로젝트가 없습니다.")
        from magus.book.tools import check_number  # noqa: PLC0415

        check_number(chapter_number)  # 범위 밖 장 번호(2026-10-09 점검 15-2)
        result = check_chapter(store, user, project.id, chapter_number)
        if result is None:
            raise ToolError(f"{chapter_number}장이 없습니다.")
        context = view_for_book(store, user, f"ms.{project.id}").header()
        return json.dumps({"context": context, "project_id": project.id, "chapter": chapter_number, **result.as_dict()},
                          ensure_ascii=False)

    return [
        Tool.from_function(
            ref_import_bibliography,
            name="ref_import_bibliography",
            description=(
                "참고문헌 목록 텍스트(한 줄에 한 문헌)를 원문 확인 전의 문헌 글로 넣는다(book을 주면 그 책, 없으면 그 프로젝트의 문헌이 든 책). "
                "key는 첫 저자 성(소문자 영문)+연도(예: daeschler2006)이고, '[국역: …]'이 있으면 한글 성+연도를 aliases에 넣는다. "
                "이미 있는 key는 건드리지 않는다(다른 프로젝트에만 있던 문헌이면 「내 서재」로 옮기고 두 지도에 연결 노드를 붙인다). "
                "파싱 실패 줄은 raw로 보관하고 리포트한다. " + PROJECT_PUT
            ),
            structured_output=False,
        ),
        Tool.from_function(
            ref_check,
            name="ref_check",
            description=(
                "장 본문의 인용을 문헌 글과 대조한다. JSON: verified(원문 확인) / unverified(원문 확인 전) / "
                "unknown(문헌 글에 없음) 세 목록과 needs_source([출처 필요: …] 표시 수). 그 프로젝트와 연결 노드의 문헌만 본다. "
                "인용 표기: (Daeschler, Shubin & Jenkins, 2006), Clack(2012), Hu et al.(2023), 갤러(2022), (헨릭, 2016)."
            ),
            structured_output=False,
        ),
    ]
