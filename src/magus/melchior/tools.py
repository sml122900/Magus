"""문헌(ref_*) MCP 도구 — Melchior · 황금. 검증된 근거만. 저자에게 보이는 글(설명·응답)에는 "문헌"만 쓴다(#85·#87)."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, Literal

from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.mcpserver.tools import Tool
from pydantic import BaseModel, Field

from magus.ids import utcnow
from magus.project_args import PROJECT_FIND, PROJECT_PUT, floor_name, labels_for, resolve_project, resolve_put, search_projects
from magus.melchior.bibliography import import_bibliography
from magus.melchior.check import after_refs_changed, chapters_citing, check_chapter
from magus.melchior.refs import add_ref
from magus.inbox import FileResolver, ResolveFile
from magus.search import Embedder, hybrid_search
from magus.store import Passage, Store
from magus.store.base import Lane
from magus.store.formats import one_line
from magus.casper.tools import ASK


class PassageIn(BaseModel):
    text: str = Field(description="발췌 원문")
    reason: str = Field(description="왜 이 구절을 골랐는지")
    locator: str | None = Field(default=None, description="쪽수·장 등 위치(예: p.45)")


def build_tools(
    store: Store, current_user: Callable[[], str], embedder: Embedder | None = None, files: ResolveFile | None = None
) -> list[Tool]:
    resolve_file = files or FileResolver(store)

    def ref_import_bibliography(text: str, project: str | None = None) -> str:
        user = current_user()
        report = import_bibliography(store, user, text, resolve_project(store, user, project))
        linked = after_refs_changed(store, user)
        return (
            report.render()
            + f"\n문헌 확인 요청과의 연결 변경 {linked}건. 모두 status=unverified다. 실제로 읽고 발췌한 문헌만 ref_add로 verified가 된다."
        )

    def ref_add(
        bib: dict[str, Any],
        passages: list[PassageIn],
        file_path: str | None = None,
        full_text: str | None = None,
        aliases: list[str] | None = None,
        project: str | None = None,
    ) -> str:
        user = current_user()
        started = utcnow()
        try:
            given = resolve_project(store, user, project) if project else None
            path, label = resolve_file(user, file_path) if file_path else (None, None)
            ref, before, added = add_ref(
                store,
                user,
                bib,
                [Passage(p.text, p.reason, p.locator) for p in passages],
                file_path=str(path) if path else None,
                file_label=label,
                full_text=full_text,
                aliases=aliases,
                floor=given,
                default_floor=lambda: resolve_put(store, user, "refs", None),  # 새 문헌만: 프로젝트가 여럿이면 묻게 한다
            )
        except (ValueError, FileNotFoundError) as e:
            raise ToolError(str(e)) from e
        linked = after_refs_changed(store, user)
        citing = chapters_citing(store, user, ref.key)
        total = len(store.get_passages(user, ref.key))
        where = "; ".join(f"{pid}: {', '.join(f'{n}장' for n in chapters)}" for pid, chapters in citing.items())
        return (
            f"{ref.key}: {before or '새 문헌'} → verified · 발췌 {added}건 추가(총 {total}건) · "
            f"전문 {'있음' if ref.has_fulltext else '없음'} · aliases {list(ref.aliases) or '없음'} · "
            f"{floor_name(store, user, ref.floor or '')}의 문헌"
            + (f" (방금 옮김: {ref.moved['reason']}. 저자에게 알린다)" if ref.moved and ref.moved.get("at", "") >= started else "")
            + "\n"
            f"문헌 확인 요청과의 연결 변경 {linked}건 · 이 문헌을 인용하는 장: {where or '없음'}"
        )

    def ref_search(query: str, scope: Literal["picked", "full", "both"] = "both", k: int = 8, project: str | None = None) -> str:
        user = current_user()
        k = max(1, min(k, 30))
        only = search_projects(store, user, project, "refs")
        lanes: list[Lane] = {"picked": ["ref_picked"], "full": ["ref_full"], "both": ["ref_picked", "ref_full"]}[scope]  # type: ignore[assignment]
        hits = hybrid_search(store, user, query, lanes, k * (6 if only else 2), embedder)
        if only is not None:
            keys = {r.key for r in store.list_refs(user, floors=only)}
            hits = [h for h in hits if h.owner_id in keys]
        hits = sorted(hits, key=lambda c: c.lane != "ref_picked")[:k]  # 발췌 먼저(같은 레인 안에서는 검색 순위 유지)
        labels = labels_for(store, user, "refs")
        if not hits:
            return f"ref_search {query!r}: 결과 없음. verified 문헌의 발췌·전문에서만 찾는다."
        lines = [f"ref_search {query!r} — 발췌 {sum(h.lane == 'ref_picked' for h in hits)}건 · 전문 {sum(h.lane == 'ref_full' for h in hits)}건"]
        passages_by_key: dict[str, list[Passage]] = {}
        for n, h in enumerate(hits, 1):
            ref = store.get_ref(user, h.owner_id)
            title = one_line(str(ref.bib.get("title", ""))) if ref else ""
            head = f"{n}. {h.owner_id} ({ref.status if ref else '?'}) — {title[:80]}"
            head += f" · {labels[ref.floor]}" if ref and ref.floor in labels else ""
            if h.lane == "ref_picked":
                passages = passages_by_key.setdefault(h.owner_id, store.get_passages(user, h.owner_id))
                p = next((p for p in passages if p.text == h.text), None)
                lines += [
                    f"{head}" + (f" · {p.locator}" if p and p.locator else "") + " [발췌]",
                    f"   “{one_line(h.text)[:300]}”",
                    f"   이유: {one_line(p.reason)[:150]}" if p else "",
                ]
            else:
                lines += [
                    f"{head} [전문 · 발췌되지 않은 부분]",
                    f"   “{one_line(h.text)[:300]}”",
                    "   → 인용하려면 ref_add로 이 구절을 발췌에 추가하세요.",
                ]
        return "\n".join(line for line in lines if line)

    def ref_check(chapter_number: int, project_id: str | None = None) -> str:
        user = current_user()
        project = store.get_project(user, project_id)
        if project is None:
            raise ToolError("프로젝트가 없습니다.")
        result = check_chapter(store, user, project.id, chapter_number)
        if result is None:
            raise ToolError(f"{chapter_number}장이 없습니다.")
        return json.dumps({"project_id": project.id, "chapter": chapter_number, **result.as_dict()}, ensure_ascii=False)

    return [
        Tool.from_function(
            ref_import_bibliography,
            name="ref_import_bibliography",
            description=(
                "참고문헌 목록 텍스트(한 줄에 한 문헌)를 refs에 status=unverified로 넣는다. "
                "key는 첫 저자 성(소문자 영문)+연도(예: daeschler2006)이고, '[국역: …]'이 있으면 한글 성+연도를 aliases에 넣는다. "
                "이미 있는 key는 건드리지 않는다(다른 프로젝트에만 있던 문헌이면 「내 서재」로 옮기고 두 지도에 연결 노드를 붙인다). "
                "파싱 실패 줄은 raw로 보관하고 리포트한다. " + PROJECT_PUT
            ),
            structured_output=False,
        ),
        Tool.from_function(
            ref_add,
            name="ref_add",
            description=(
                "저자가 '문헌'에 넣으라고 분명히 말했을 때만 부른다. " + ASK
                + "저자가 실제로 읽은 문헌을 verified로 넣는다. bib: {authors|author, year, title, …} 또는 {key}. "
                "저자·연도를 모르면 bib를 비우고 file_path만 줘도 된다: 전문 첫머리의 제목으로 참고문헌에서 찾는다. "
                "passages: [{text, reason, locator?}] 하나 이상 필수(직접 고른 발췌와 고른 이유). "
                "file_path(올린 파일 이름, txt/md/pdf/docx. files_list로 확인. 예: kremer1993.pdf) "
                "또는 full_text로 전문을 함께 넣을 수 있다. "
                "같은 key나 alias가 unverified로 있으면 verified로 올린다. aliases로 한글 표기(예: 갤러2022)를 더한다. " + PROJECT_PUT
                + "이미 있는 문헌은 제자리에 둔다."
            ),
            structured_output=False,
        ),
        Tool.from_function(
            ref_search,
            name="ref_search",
            description=(
                "verified 문헌에서 찾는다. scope=picked(발췌)|full(전문)|both, k=8. 발췌 결과를 먼저 보여 주고, "
                "전문 결과에는 '발췌되지 않은 부분'이라고 표시한다(인용하려면 ref_add로 발췌 추가). 인용은 여기서 나온 것만 쓴다. "
                + PROJECT_FIND
            ),
            structured_output=False,
        ),
        Tool.from_function(
            ref_check,
            name="ref_check",
            description=(
                "장 본문의 인용을 refs와 대조한다. JSON: verified / unverified(refs에 있으나 미확인) / "
                "unknown(refs에 없음) 세 목록과 needs_source([출처 필요: …] 표시 수). 그 프로젝트와 연결 노드의 문헌만 본다. "
                "인용 표기: (Daeschler, Shubin & Jenkins, 2006), Clack(2012), Hu et al.(2023), 갤러(2022), (헨릭, 2016)."
            ),
            structured_output=False,
        ),
    ]
