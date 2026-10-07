"""문서 책 도구(book_document, 사용자 결정 #94). 도구 하나로 만들기와 다시 만들기를 한다."""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.mcpserver.tools import Tool

from magus.book.documents import DOC_TYPE_BY_NAME, DOC_TYPES, DOCUMENT_COLOR, build_source_check, default_title
from magus.category.titles import decide_title
from magus.maps import CENTER
from magus.project_args import floor_name
from magus.store import Document, Store

PREFACE_MAX = 2000


def build_tools(store: Store, current_user: Callable[[], str]) -> list[Tool]:
    def book_document(
        kind: Literal["출처 확인 문서"] = "출처 확인 문서",
        project_id: str | None = None,
        node: str | None = None,
        title: str | None = None,
        title_by: Literal["ai", "author"] | None = None,
        untitled: bool = False,
        preface: str | None = None,
        document_id: str | None = None,
    ) -> str:
        user = current_user()
        if preface and len(preface) > PREFACE_MAX:
            raise ToolError(f"머리말은 {PREFACE_MAX}자까지다. 수치·목록은 넣지 않는다(서버가 만든다).")
        if document_id:  # 다시 만들기: 같은 문서의 새 판(이전 판은 이력)
            doc = store.get_document(user, document_id.strip())
            if doc is None:
                raise ToolError(f"문서 {document_id}가 없다.")
            content, version = build_source_check(store, user, doc.project_id, doc.title, preface=preface, preface_by="ai",
                                                  previous=doc.versions[-1])
            doc = store.add_document_version(user, doc.id, version, content)
            return _said(doc, "다시 만듦", floor_name(store, user, doc.floor))
        project = store.get_project(user, project_id)
        if project is None:
            raise ToolError(f"원고 책 {project_id!r}가 없다." if project_id else "원고 책이 없다. 먼저 원고를 올린다.")
        if not store.list_chapters(user, project.id):
            raise ToolError(f"『{project.title}』에는 아직 원고가 없다. 저자가 책장에서 원고를 올린 뒤 만든다.")
        where, target = project.id, CENTER
        if node and node.strip():  # 그 원고 프로젝트 지도의 노드(이름). 연결 노드·다른 프로젝트에는 두지 않는다
            found = store.get_map(user, where)
            hit = next((n for n in found.nodes if not n.link and (n.id == node.strip() or (" ".join(n.name.split()) == " ".join(node.split()))
                                                                  or (n.center and node.strip() in ("가운데", "가운데 노드")))), None) if found else None
            if hit is None:
                raise ToolError(f"『{project.title}』 지도에 '{node}' 노드가 없다. 문서 책은 그 원고의 프로젝트 지도에 둔다.")
            target = hit.id
        name, by, _ = decide_title(store, user, title, title_by, untitled)  # 제목 규칙(규칙 10)
        doc_type = DOC_TYPE_BY_NAME[kind]
        name = name or default_title(store, user, project.id, doc_type)  # 비워 두기면 '원고 제목 + 문서 종류'
        content, version = build_source_check(store, user, project.id, name, preface=preface, preface_by="ai")
        doc = store.create_document(user, Document("", name, by, doc_type, where, project.id, DOCUMENT_COLOR, versions=(version,)),
                                    content, None if target == CENTER else target)
        placed = store.node_of_book(user, f"doc.{doc.id}")
        target = placed[1] if placed else CENTER
        shown = store.get_map(user, where)
        node_name = next((n.name for n in shown.nodes if n.id == target and not n.center), "") if shown else ""
        return _said(doc, "만듦", floor_name(store, user, where) + (f" · 노드 「{node_name}」" if node_name else " · 가운데 노드"))

    def _said(doc: Document, verb: str, where: str) -> str:
        v = doc.versions[-1]
        s = v.stats
        basis = f"E{v.edition}" if v.edition else "수정본 기록 없음"
        return (f"문서 책을 {verb}: 「{doc.title}」({doc.id}) · {where}에 꽂힘 · {DOC_TYPES[doc.doc_type]} v{v.number} · 기준 {basis} · "
                f"답해 주실 질문 {s.get('questions', 0)} · 열린 확인 요청 {s.get('open_issues', 0)} · 미확인 문헌 {s.get('unverified', 0)}편. "
                "내용은 서버가 데이터로 만들었다" + ("(머리말은 AI가 쓴 것으로 표시)" if v.preface_by else "")
                + ". 저자에게 책장에서 볼 수 있다고 알린다(수치는 대화에 옮겨 쓰지 않는다).")

    return [
        Tool.from_function(
            book_document,
            name="book_document",
            description=(
                "저자가 원고에서 문서를 만들어 책장에 넣으라고 분명히 말했을 때만 부른다. "
                "kind=출처 확인 문서: 질문·원고 불일치·사실 확인 요청·우선 확인 문헌·장별 미확인 수·바뀐 점을 서버가 데이터로 만든다"
                "(Claude는 그 수치·목록을 쓰거나 preface에 옮기지 않는다). preface: 저자가 원하면 짧은 머리말(AI가 쓴 것으로 표시). "
                "project_id: 기준 원고(없으면 최근). node: 그 원고 프로젝트 지도의 노드(없으면 가운데). 제목은 생각과 같은 규칙. "
                "document_id를 주면 그 문서를 지금 원고로 다시 만든다(이전 것은 이력으로 남는다)."
            ),
            structured_output=False,
        ),
    ]
