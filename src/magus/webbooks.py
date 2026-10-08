"""모든 동작을 책장에서(사용자 결정 #94, 2026-10-07 → #96 종류 없음): 올린 문서 화면, 올린 문서에서 만든 문서 화면,
'+ 프로젝트'의 문서 올리기. Web에 섞는 BookPages.
#96: 화면에 '원고 책·모음 책·문서 책' 같은 종류 이름을 쓰지 않는다. 올린 문서·문서에도 컨텍스트를 붙인다(책 설정, 머리에 표시).

- 2026-10-09: 책장에는 책 목록과 '새 책' 하나(옛 책 추가 /shelf/add는 새 책으로 넘긴다). 웹의 수정본 올리기는 없앴다.
  수정본·나중에 올리는 문서는 게시판에 첨부하고 대화에서 말하면 Claude가 files_list의 첨부를 book_import로 가져간다.
  문서 올리기(/shelf/manuscript)는 프로젝트 목록의 '+ 프로젝트'(새 프로젝트)만. 화면 위에 위치 표시(프로젝트 › 노드 › 책).
- 원고 책(/shelf/book/<id>): 장 목록 · 확인 요청 · 인용 상태(체크리스트 + 답해 주실 질문) · 수정본 이력 탭.
  옛 주소 /book·/issues·/checklist·/questions는 여기로 넘긴다.
- 문서 책(/shelf/doc/<id>): 읽기용. 기준 원고에 새 수정본이 오면 '옛 판 기준'과 '다시 만들기'. docx 내려받기, 인쇄·PDF로 저장(브라우저 인쇄).
- 원고 책·문서 책도 책 색·이름 바꾸기·휴지통은 같은 방식(/shelf/edit/…, /shelf/trash/…). 원고 책은 가운데 노드 자체라 옮기지 않는다.
- #97: 원문 확인 넣기 폼(/shelf/refs/register)은 없앴다. 웹에서는 문헌 글의 '원문 확인' 체크와 첨부로, 쓸 부분은 대화로 넣는다.
  화면의 설명 문장은 도움말(docs/help)로 옮겼다. '올린 문서에서 만든 문서'는 대화로 만든다.
"""

from __future__ import annotations

import html
import tempfile
import urllib.parse
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from magus.book.documents import DOC_TYPES, STALE_WORDS, build_source_check, is_stale, latest_edition
from magus.book.importer import import_manuscript
from magus.book.outline import chapter_count
from magus.contexts import attach_manuscript_context, view_for_book
from magus.webcontexts import CONTEXT_SCRIPT, context_fieldset, contexts_from_form, contexts_view_html, register_row
from magus.ids import local_time
from magus.inbox import LimitError, mb, safe_filename
from magus.mdlite import to_html
from magus.melchior.author_report import cite_label, write_docx
from magus.melchior.check import cite_floors
from magus.melchior.questions import TYPES as QUESTION_TYPES
from magus.melchior.questions import build_questions
from magus.melchior.report import build_cite_report
from magus.store import BookTitles, Store
from magus.store.base import STALE_REASONS
from magus.webshelf import color_fieldset, chosen_color, safe_color, state_url

LIGHTS = {"verified": ("🟢", "확인"), "unverified": ("🟡", "미확인"), "unknown": ("🔴", "참고문헌에 없음"),
          "uncertain": ("⚪", "미연결")}
QUESTION_STATES = {"open": "열림", "waiting": "답함·원본 반영 대기", "answered": "답함"}
ISSUE_KIND_NAMES = {"citation": "문헌 확인", "fact": "사실·수치 확인", "general": "기타"}
TABS = (("chapters", "장 목록"), ("issues", "확인 요청"), ("cites", "인용 상태"), ("editions", "수정본 이력"))
MANUSCRIPT_COLOR = "#4b2e1e"  # 원고 책의 처음 색(짙은 가죽색). 저자가 바꿀 수 있다
WHEN = "%Y-%m-%d %H:%M"
IMPORTING = "가져오는 중…"

BOOK_STYLE = """
.tabs{display:flex;flex-wrap:wrap;gap:4px 8px;margin:12px 0 16px;border-bottom:2px solid var(--line)}
.tabs a{display:inline-flex;align-items:center;min-height:44px;padding:8px 16px;text-decoration:none;color:var(--ink2);font-weight:600;
border-bottom:3px solid transparent;margin-bottom:-2px}
.tabs a[aria-current=page]{color:var(--primary);border-bottom-color:var(--primary)}
a.button{display:inline-flex;align-items:center;min-height:44px;padding:8px 16px;border-radius:999px;background:var(--primary);color:#fff;
text-decoration:none;font-weight:600}a.button:hover{background:var(--press);color:#fff}
.progress{display:none;margin:12px 0}.progress.on{display:block}
.progress .bar{height:12px;border-radius:6px;background:var(--line);overflow:hidden}
.progress .bar i{display:block;height:100%;width:0;background:var(--primary);transition:width .2s}
.progress .say{margin:8px 0 0;font-weight:600}
.doc{background:var(--canvas);border:1px solid var(--line);border-radius:12px;padding:4px 28px 24px;box-shadow:var(--shadow);max-width:880px}
.doc-history{max-width:880px;box-sizing:border-box}
.doc h2{font-size:24px}.doc h3{font-size:19px;margin-top:28px}.doc li{margin:6px 0}.doc blockquote{margin:8px 0;color:var(--ink2)}
.doc-actions{display:flex;flex-wrap:wrap;gap:8px 16px;align-items:center;margin:12px 0}
.msg.stale{border-left:4px solid #b8923a}
.report{background:var(--canvas);border:1px solid var(--line);border-radius:12px;padding:4px 20px 12px;margin:12px 0}
.qlist{list-style:none;padding:0}
@media print{.site,.crumb,.floor-meta,.doc-actions,.tabs,.no-print{display:none!important}body{background:#fff}main{max-width:none;padding:0}
.doc{border:0;box-shadow:none;padding:0;max-width:none}h1{margin-top:0}}
"""

# 파일을 고르고 올리면: 올리는 % → 가져오는 중 → 끝난 화면으로. 자바스크립트가 꺼져 있으면 보통 폼으로 보낸다(같은 결과).
UPLOAD_PROGRESS = """<script>
(function () {
  document.querySelectorAll("form[data-progress]").forEach(function (form) {
    form.addEventListener("submit", function (e) {
      var file = form.querySelector("input[type=file]");
      if (!window.FormData || !window.XMLHttpRequest || !file || !file.files.length) return;
      e.preventDefault();
      var box = form.querySelector(".progress"), bar = box.querySelector("i"), say = box.querySelector(".say");
      var button = form.querySelector("button");
      box.classList.add("on"); if (button) button.disabled = true;
      var xhr = new XMLHttpRequest();
      xhr.open("POST", form.getAttribute("action"));
      xhr.upload.onprogress = function (ev) {
        if (!ev.lengthComputable) return;
        var p = Math.round(ev.loaded * 100 / ev.total); bar.style.width = p + "%"; say.textContent = "올리는 중 " + p + "%";
      };
      xhr.upload.onload = function () { bar.style.width = "100%"; say.textContent = form.getAttribute("data-progress"); };
      xhr.onload = function () {
        var done = xhr.status === 200 && xhr.responseURL && xhr.responseURL.indexOf(form.getAttribute("action")) < 0;
        if (done) { location.href = xhr.responseURL; return; }
        document.open(); document.write(xhr.responseText); document.close();
      };
      xhr.onerror = function () { say.textContent = "올리지 못했습니다."; if (button) button.disabled = false; };
      xhr.send(new FormData(form));
    });
  });
})();
</script>"""


def progress_box() -> str:
    return '<div class="progress" role="status" aria-live="polite"><div class="bar"><i></i></div><p class="say"></p></div>'


def short_name(title: str, width: int = 12) -> str:
    """책등에 들어갈 짧은 이름: 부제(— 뒤, : 뒤)를 떼고 width자까지."""
    head = title.split(" — ")[0].split(":")[0].strip() or title
    return head if len(head) <= width else head[: width - 1] + "…"


class BookPages:
    """Web에 섞어 쓰는 책 화면들(#94)."""

    store: Store
    settings: Any
    base_url: str
    user_of: Callable[[Request], tuple[str, str] | None]
    _need_login: Callable[[Request], Response]
    _csrf_input: Callable[[tuple[str, str]], str]
    _form: Callable[[Request, tuple[str, str]], Awaitable[Any]]
    _page: Callable[..., Response]
    export_link: Callable[[str, str], str]
    location_form: Callable[..., str]
    _keep_color: Callable[[str, Any, str], str]
    trail: Callable[..., str]  # BoardPages

    def book_routes(self) -> list[tuple[str, list[str], Callable[..., Any]]]:
        return [
            ("/shelf/add", ["GET"], self.add_book),
            ("/shelf/manuscript", ["POST"], self.manuscript_upload),
            ("/shelf/book/{project}", ["GET"], self.manuscript_page),
            ("/shelf/doc/{doc}", ["GET"], self.document_page),
            ("/shelf/doc/{doc}/redo", ["POST"], self.document_redo),
            ("/shelf/doc/{doc}/docx", ["GET"], self.document_docx),
        ]

    def _book_page(self, title: str, body: str, session: tuple[str, str], status: int = 200, *, lead: str = "") -> Response:
        from magus.webboard import BOARD_STYLE  # noqa: PLC0415  (위치 표시)
        from magus.webcontexts import CONTEXT_STYLE  # noqa: PLC0415
        from magus.webshelf import SHELF_STYLE

        return self._page(title, body, session, status, current="프로젝트", css=SHELF_STYLE + BOOK_STYLE + CONTEXT_STYLE + BOARD_STYLE,
                          lead=lead)

    # ---- 책 추가(옛 주소)·문서 올리기 ------------------------------------------------------------------
    async def add_book(self, request: Request) -> Response:
        """옛 '책 추가'(새 책·문서 올리기 두 칸)는 없앴다(2026-10-09). 같은 자리의 새 책으로 넘긴다."""
        query = urllib.parse.urlencode([(k, v) for k, v in request.query_params.items() if k in ("project", "floor", "node")])
        return RedirectResponse("/shelf/new" + (f"?{query}" if query else ""), status_code=303)

    async def _uploaded(self, request: Request, session: tuple[str, str]) -> tuple[Any, bytes, str]:
        """(폼, 파일 내용, 안전한 파일 이름). 한도·형식이 맞지 않으면 ValueError(저자에게 보일 문장)."""
        limit = self.settings.max_upload_bytes + 1_000_000
        if int(request.headers.get("content-length") or 0) > limit:
            raise ValueError(f"파일이 너무 큽니다(한 개 한도 {mb(self.settings.max_upload_bytes)}).")
        form = await self._form(request, session)
        item = form.get("file")
        if not isinstance(item, UploadFile) or not item.filename:
            raise ValueError("올릴 문서 파일을 골라 주세요.")
        name = safe_filename(item.filename)
        if Path(name).suffix.lower() not in (".docx", ".pdf"):
            raise ValueError("올릴 문서는 docx 또는 pdf 파일이어야 합니다.")
        data = await item.read()
        if len(data) > self.settings.max_upload_bytes:
            raise ValueError(f"파일이 너무 큽니다: {mb(len(data))}(한 개 한도 {mb(self.settings.max_upload_bytes)}).")
        used = await run_in_threadpool(self.store.usage_bytes, session[0])
        if used + len(data) > self.settings.max_user_bytes:
            raise ValueError(f"저장 용량을 넘습니다: 지금 {mb(used)} + 새 파일 {mb(len(data))} > 한도 {mb(self.settings.max_user_bytes)}.")
        return form, data, name

    async def manuscript_upload(self, request: Request) -> Response:
        session = self.user_of(request)
        if not session:
            return self._need_login(request)
        uid = session[0]
        try:
            _, data, name = await self._uploaded(request, session)
            with tempfile.TemporaryDirectory() as tmp:  # 프로젝트 목록의 '+ 프로젝트': 올린 문서로 새 프로젝트를 만든다
                path = Path(tmp) / name
                path.write_bytes(data)
                report = await run_in_threadpool(import_manuscript, self.store, uid, path)
                await run_in_threadpool(attach_manuscript_context, self.store, uid, report.project_id)  # 「원고」 컨텍스트(#96)
        except PermissionError:
            return self._book_page("문서 올리기", '<p class="msg err">잘못된 요청입니다.</p>', session, 403)
        except (ValueError, FileNotFoundError, LimitError) as e:
            return self._book_page("문서 올리기", f'<p class="msg err">{html.escape(str(e))}</p><p><a href="/shelf">프로젝트</a></p>',
                                   session, 400)
        return RedirectResponse(f"/shelf/book/{report.project_id}?done=imported", status_code=303)

    # ---- 원고 책 ------------------------------------------------------------------------------
    def _manuscript_head(self, uid: str, project: Any, tab: str) -> str:
        chapters = self.store.list_chapters(uid, project.id)
        issues = self.store.list_issues(uid, project.id, "open")
        last = latest_edition(self.store, uid, project.id)
        parts = len(self.store.list_parts(uid, project.id))
        gear = (f'<a class="gear" href="/shelf/edit/ms.{html.escape(project.id)}" aria-label="책 설정" title="책 설정">⚙</a>')
        meta = (f"{chapter_count(chapters)}" + (f" · {parts}부" if parts else "") + f" · {sum(c.char_count for c in chapters):,}자 · "
                + (f"수정본 E{last}" if last else "수정본 기록 없음") + f" · 열린 확인 요청 {len(issues)} {gear}")
        base = f"/shelf/book/{urllib.parse.quote(project.id)}"
        tabs = "".join(f'<a href="{base}?tab={key}"{" aria-current=page" if key == tab else ""}>{name}</a>' for key, name in TABS)
        context = contexts_view_html(view_for_book(self.store, uid, f"ms.{project.id}"))
        return f'<p class="floor-meta">{meta}</p>{context}<nav class="tabs" aria-label="올린 문서">{tabs}</nav>'

    def _manuscript_done(self, uid: str, project: Any, request: Request) -> str:
        done = request.query_params.get("done")
        if done == "imported":
            chapters = self.store.list_chapters(uid, project.id)
            issues = self.store.list_issues(uid, project.id, None)
            refs = self.store.list_refs(uid, floors=cite_floors(self.store, uid, project.id))
            return (f'<p class="msg">올렸습니다: {chapter_count(chapters)} · {len(self.store.list_parts(uid, project.id))}부 · '
                    f"확인 요청 {len(issues)} · 문헌 {len(refs)}</p>")
        if done == "edit":
            return '<p class="msg">저장했습니다.</p>'
        return ""

    async def manuscript_page(self, request: Request) -> Response:
        session = self.user_of(request)
        if not session:
            return self._need_login(request)
        uid = session[0]
        try:
            project = await run_in_threadpool(self.store.get_project, uid, request.path_params["project"])
        except ValueError:
            project = None
        if project is None or not await run_in_threadpool(self.store.list_chapters, uid, project.id):
            return self._book_page("올린 문서", '<p class="msg err">올린 문서가 없습니다. <a href="/shelf">프로젝트</a>로 돌아가세요.</p>', session, 404)
        tab = request.query_params.get("tab") if request.query_params.get("tab") in dict(TABS) else "chapters"
        body = await run_in_threadpool(self._manuscript_body, uid, session, project, tab, request)
        lead = await run_in_threadpool(self.trail, uid, f"ms.{project.id}")
        return self._book_page(project.title, body, session, lead=lead)

    def _manuscript_body(self, uid: str, session: tuple[str, str], project: Any, tab: str, request: Request) -> str:
        head = self._manuscript_head(uid, project, tab) + self._manuscript_done(uid, project, request)
        params = request.query_params
        if tab == "issues":
            return head + self._issues_html(uid, project, params)
        if tab == "cites":
            return head + (self._questions_html(uid, project, params) if params.get("view") == "questions"
                           else self._checklist_html(uid, project, params))
        if tab == "editions":
            return head + self._editions_html(uid, project, params)
        return head + self._chapters_html(uid, session, project)

    def _chapters_html(self, uid: str, session: tuple[str, str], project: Any) -> str:
        issues = self.store.list_issues(uid, project.id, "open")
        per = {}
        for i in issues:
            per[i.chapter_number] = per.get(i.chapter_number, 0) + 1
        parts = {p.number: p.title for p in self.store.list_parts(uid, project.id)}
        rows, current = [], None
        for c in self.store.list_chapters(uid, project.id):
            if c.part_number is not None and c.part_number != current:
                rows.append(f'<tr><th colspan="6">제{c.part_number}부 {html.escape(parts.get(c.part_number, ""))}</th></tr>')
            current = c.part_number
            rows.append(f"<tr><td>{html.escape(c.display)}</td><td>{html.escape(c.title)}</td><td>{html.escape(c.status)}</td>"
                        f'<td class="num">{c.char_count:,}</td><td class="num">{per.get(c.number, 0)}</td>'
                        f'<td class="num">{c.unverified_cite_count}</td></tr>')
        return (
            f'<form method="post" action="/book/export" class="doc-actions">{self._csrf_input(session)}'
            f'<input type="hidden" name="project_id" value="{html.escape(project.id)}"><button>내려받기(docx)</button></form>'
            '<table><tr><th>장</th><th>제목</th><th>상태</th><th class="num">글자</th><th class="num">확인 요청</th>'
            f'<th class="num">미확인 인용</th></tr>{"".join(rows)}</table>'
        )

    def _issues_html(self, uid: str, project: Any, params: Any) -> str:
        """열린 확인 요청 목록(조회 전용). AI가 원고에 단 코멘트에서 온 것은 'AI 확인 요청'으로 드러낸다(#71)."""
        status = params.get("status") if params.get("status") in ("open", "closed", "all") else "open"
        kind = params.get("kind") if params.get("kind") in ISSUE_KIND_NAMES else None
        issues = self.store.list_issues(uid, project.id, None if status == "all" else status, kind=kind)  # type: ignore[arg-type]
        names = {c.number: c.display for c in self.store.list_chapters(uid, project.id)}
        base = f"/shelf/book/{urllib.parse.quote(project.id)}?tab=issues"

        def who(i: Any) -> str:
            if i.origin == "import_comment":
                name = f"({html.escape(i.author)})" if i.author else ""
                return f'<span class="tag">🤖 AI 확인 요청{name}</span>' if i.by_ai else f"문서 코멘트{name}"
            return "직접 남김" if i.origin == "user" else "Claude가 남김"

        rows = "".join(
            f"<tr><td>I{i.id}{'' if i.status == 'open' else ' (닫힘)'}</td>"
            f"<td>{html.escape(names.get(i.chapter_number, f'{i.chapter_number}장') if i.chapter_number is not None else '장 밖')}</td>"
            f"<td>{who(i)}</td><td>{ISSUE_KIND_NAMES[i.kind]}"
            + (f"<br><small>해결됐을 수 있음: {STALE_REASONS[i.stale]}</small>" if i.stale else "") + "</td>"
            f"<td>{html.escape(i.text).replace(chr(10), '<br>')}</td></tr>"
            for i in issues
        )
        ai = sum(1 for i in issues if i.by_ai)
        filters = " · ".join(f'<a href="{base}&status={status}&kind={k}">{name}</a>' for k, name in ISSUE_KIND_NAMES.items())
        return (f"<p>확인 요청 {len(issues)}" + (f" · 🤖 AI 확인 요청 {ai}" if ai else "") + "</p>"
                f'<p><a href="{base}&status=open">열린 것</a> · <a href="{base}&status=closed">닫힌 것</a> · '
                f'<a href="{base}&status=all">전체</a> | {filters}</p>'
                f"<table><tr><th>번호</th><th>장</th><th>누가</th><th>종류</th><th>내용</th></tr>{rows or '<tr><td colspan=\"5\">없음</td></tr>'}</table>")

    def _checklist_html(self, uid: str, project: Any, params: Any) -> str:
        report = build_cite_report(self.store, uid, project.id)
        refs = {r.key: r for r in self.store.list_refs(uid, floors=cite_floors(self.store, uid, project.id))}  # 그 프로젝트 + 연결 노드가 가리키는 문헌(#95)
        status = params.get("status") or ""
        docs = [d for d in report.docs.values() if not status or d.status == status]
        order = {"unknown": 0, "unverified": 1, "uncertain": 2, "verified": 3}
        docs.sort(key=lambda d: (order[d.status], -d.count, d.key))
        counts = {s: len(report.of(s)) for s in LIGHTS}
        base = f"/shelf/book/{urllib.parse.quote(project.id)}?tab=cites"
        filters = " · ".join(f'<a href="{base}&status={s}">{LIGHTS[s][0]} {LIGHTS[s][1]} {counts[s]}</a>' for s in LIGHTS)
        questions = [q for q in build_questions(self.store, uid, project.id) if q.state == "open"]
        doc_rows = "".join(
            f"<tr><td>{LIGHTS[d.status][0]} {LIGHTS[d.status][1]}</td><td>{html.escape(cite_label(refs.get(d.key), d.key))}"
            + (f"<br><small>후보: {html.escape(' / '.join(d.candidates))}</small>" if d.candidates else "")
            + f'</td><td class="num">{d.count}</td><td>{html.escape(", ".join(d.chapters))}</td></tr>'
            for d in docs
        )
        chapter_rows = "".join(
            f'<tr><td>{html.escape(disp)}</td><td>{html.escape(title)}</td><td class="num">{unique}</td><td class="num">{occ}</td></tr>'
            for disp, title, unique, occ, _ in report.per_chapter
        )
        return (f"<p>문헌 {len(report.docs) - counts['uncertain']}편(확인 {counts['verified']} · 미확인 {counts['unverified']} · "
                f"참고문헌에 없음 {counts['unknown']}) · 미연결 {counts['uncertain']} · <a href=\"{base}\">전체</a></p>"
                f'<p><a href="{base}&view=questions"><b>답해 주실 질문 {len(questions)}</b></a></p>'
                f"<p>{filters}</p>"
                f"<table><tr><th>상태</th><th>문헌</th><th class=\"num\">인용</th><th>장</th></tr>{doc_rows or '<tr><td colspan=\"4\">없음</td></tr>'}</table>"
                "<h2>장별</h2><table><tr><th>장</th><th>제목</th><th class=\"num\">미확인 문헌</th><th class=\"num\">인용 출현</th></tr>"
                f"{chapter_rows}</table>")

    def _questions_html(self, uid: str, project: Any, params: Any) -> str:
        status = params.get("status") if params.get("status") in ("open", "waiting", "all") else "open"
        kind = params.get("type") if params.get("type") in QUESTION_TYPES else None
        everything = build_questions(self.store, uid, project.id)
        chosen = [q for q in everything if (status == "all" or q.state == status) and (kind is None or q.type == kind)]
        counts = {s: sum(1 for q in everything if q.state == s) for s in QUESTION_STATES}
        base = f"/shelf/book/{urllib.parse.quote(project.id)}?tab=cites&view=questions"

        def options(question: Any) -> str:  # 저자에게는 코드 대신 설명만(다른 문헌 고르기는 대화로)
            return " / ".join(html.escape(label.replace("(그 key)", "")) for _, label in question.options)

        def answered(question: Any) -> str:
            if not question.answer:
                return ""
            label = dict(question.options).get(question.answer.get("choice", ""), question.answer.get("choice", ""))
            return (f'<p class="muted">답: {html.escape(label.replace("(그 key)", ""))}'
                    + (f" · 결정 {html.escape(question.answer['decision'])}" if question.answer.get("decision") else "")
                    + f" · {QUESTION_STATES[question.state]}</p>")

        cards = "".join(
            f'<li class="card"><p><b>{QUESTION_TYPES[x.type]}</b> · {QUESTION_STATES[x.state]}</p>'
            f"<p>{html.escape(x.text)}</p><p class=\"muted\">{options(x)}</p>{answered(x)}</li>"
            for x in chosen
        )
        types = " · ".join(f'<a href="{base}&status={status}&type={t}">{name} {sum(1 for x in everything if x.type == t)}</a>'
                           for t, name in QUESTION_TYPES.items() if any(x.type == t for x in everything))
        return (f'<p><a href="/shelf/book/{urllib.parse.quote(project.id)}?tab=cites">← 인용 상태</a></p>'
                f"<h2>답해 주실 질문 {len(everything)}</h2>"
                f"<p>열림 {counts['open']} · 원본 반영 대기 {counts['waiting']} · 답함 {counts['answered']}</p>"
                f'<p><a href="{base}&status=open">열린 것</a> · <a href="{base}&status=waiting">원본 반영 대기</a> · '
                f'<a href="{base}&status=all">전체</a>' + (f" | {types}" if types else "") + "</p>"
                + (f'<ol class="qlist">{cards}</ol>' if cards else '<p class="msg">없음</p>'))

    def _editions_html(self, uid: str, project: Any, params: Any) -> str:
        """수정본 이력(조회). 수정본은 게시판에 첨부하고 대화에서 올린다(2026-10-09, 도움말)."""
        editions = self.store.list_editions(uid, project.id)
        base = f"/shelf/book/{urllib.parse.quote(project.id)}?tab=editions"
        def counts(e: Any) -> str:  # changed에는 새 장이 들어 있다. 처음 올린 문서는 견줄 것이 없다
            if e.number == 1:
                return f'<td class="num">—</td><td class="num">{e.added or "—"}</td><td class="num">—</td><td class="num">—</td>'
            return (f'<td class="num">{e.changed - e.added}</td><td class="num">{e.added}</td>'
                    f'<td class="num">{e.removed}</td><td class="num">{e.unchanged}</td>')

        rows = "".join(
            f"<tr><td>{'처음 올린 문서 E1' if e.number == 1 else f'수정본 E{e.number}'}</td><td>{html.escape(e.file)}</td>"
            f'<td class="num">{local_time(e.uploaded_at, WHEN)}</td>{counts(e)}'
            f'<td><a href="{base}&report={e.number}">리포트</a></td></tr>'
            for e in reversed(editions)
        )
        wanted = params.get("report") or ""
        report = ""
        if wanted.isdigit():
            name = "import-report.md" if wanted == "1" else f"E{wanted}-reupload-report.md"
            text = self.store.read_original(uid, project.id, name)
            if text:
                report = f'<section class="report"><h2>리포트 — {"처음 올린 문서" if wanted == "1" else f"수정본 E{wanted}"}</h2>{to_html(text)}</section>'
        table = ('<table><tr><th>수정본</th><th>파일</th><th class="num">올린 시각</th><th class="num">바뀐 장</th><th class="num">새 장</th>'
                 f'<th class="num">빠진 장</th><th class="num">그대로</th><th></th></tr>{rows}</table>' if rows
                 else '<p class="empty">기록 없음</p>')
        return "<h2>수정본 이력</h2>" + table + report

    # ---- 문서 책 ------------------------------------------------------------------------------
    async def document_page(self, request: Request) -> Response:
        session = self.user_of(request)
        if not session:
            return self._need_login(request)
        uid = session[0]
        doc = await run_in_threadpool(self.store.get_document, uid, request.path_params["doc"])
        if doc is None:
            return self._book_page("문서", '<p class="msg err">없는 문서입니다. <a href="/shelf">프로젝트</a>로 돌아가세요.</p>', session, 404)
        number = request.query_params.get("v")
        number_i = int(number) if number and number.isdigit() else doc.versions[-1].number
        content = await run_in_threadpool(self.store.read_document, uid, doc.id, number_i)
        if content is None:
            return self._book_page(doc.title, '<p class="msg err">없는 이력입니다.</p>', session, 404)
        body = await run_in_threadpool(self._document_body, uid, session, doc, number_i, content, request)
        return self._book_page(doc.title, body, session, lead=await run_in_threadpool(self.trail, uid, f"doc.{doc.id}"))

    def _document_body(self, uid: str, session: tuple[str, str], doc: Any, number: int, content: str, request: Request) -> str:
        version = next(v for v in doc.versions if v.number == number)
        current = doc.versions[-1]
        project = self.store.get_project(uid, doc.project_id)
        gear = f'<a class="gear" href="/shelf/edit/doc.{html.escape(doc.id)}" aria-label="책 설정" title="책 설정">⚙</a>'
        meta = (f"{DOC_TYPES.get(doc.doc_type, doc.doc_type)} · "
                + (f"『{html.escape(project.title)}』" if project else "—") + (f" E{version.edition}" if version.edition else "")
                + f" · {local_time(version.at, WHEN)} {gear}")
        notices = ""
        if request.query_params.get("done") == "redo":
            notices += '<p class="msg">다시 만들었습니다.</p>'
        if request.query_params.get("done") == "edit":
            notices += '<p class="msg">저장했습니다.</p>'
        if number != current.number:
            notices += (f'<p class="msg">{number}번째 · {local_time(version.at, WHEN)} · '
                        f'<a href="/shelf/doc/{html.escape(doc.id)}">지금 것</a></p>')
        elif is_stale(self.store, uid, doc):
            now = latest_edition(self.store, uid, doc.project_id)
            notices += (f'<div class="msg stale">{STALE_WORDS} · '
                        + (f"E{current.edition}" if current.edition else "수정본 기록 전") + f" → E{now} "
                        f'<form method="post" action="/shelf/doc/{html.escape(doc.id)}/redo" class="inline">{self._csrf_input(session)}'
                        "<button>다시 만들기</button></form></div>")
        actions = (f'<div class="doc-actions"><a href="/shelf/doc/{html.escape(doc.id)}/docx?v={number}">내려받기(docx)</a>'
                   '<button type="button" onclick="window.print()">인쇄</button>'
                   + ("" if number != current.number or is_stale(self.store, uid, doc) else
                      f'<form method="post" action="/shelf/doc/{html.escape(doc.id)}/redo" class="inline">{self._csrf_input(session)}'
                      "<button>다시 만들기</button></form>") + "</div>")
        history = "".join(
            f'<li><a href="/shelf/doc/{html.escape(doc.id)}?v={v.number}">{v.number}번째</a> · {local_time(v.at, WHEN)} · '
            + (f"E{v.edition} 기준" if v.edition else "수정본 기록 전") + (" · 지금 것" if v.number == current.number else "") + "</li>"
            for v in reversed(doc.versions)
        )
        context = contexts_view_html(view_for_book(self.store, uid, f"doc.{doc.id}"))
        return (f'<p class="floor-meta">{meta}</p>{context}{notices}{actions}'
                f'<article class="doc">{to_html(content)}</article>'
                f'<details class="card no-print doc-history"><summary>만든 이력 {len(doc.versions)}</summary><ol>{history}</ol></details>')

    async def document_redo(self, request: Request) -> Response:
        session = self.user_of(request)
        if not session:
            return self._need_login(request)
        uid = session[0]
        try:
            await self._form(request, session)
        except PermissionError:
            return self._book_page("문서", '<p class="msg err">잘못된 요청입니다.</p>', session, 403)
        doc = await run_in_threadpool(self.store.get_document, uid, request.path_params["doc"])
        if doc is None:
            return self._book_page("문서", '<p class="msg err">없는 문서입니다.</p>', session, 404)

        def redo() -> None:
            content, version = build_source_check(self.store, uid, doc.project_id, doc.title, previous=doc.versions[-1])
            self.store.add_document_version(uid, doc.id, version, content)

        await run_in_threadpool(redo)
        return RedirectResponse(f"/shelf/doc/{urllib.parse.quote(doc.id)}?done=redo", status_code=303)

    async def document_docx(self, request: Request) -> Response:
        session = self.user_of(request)
        if not session:
            return self._need_login(request)
        uid = session[0]
        doc = await run_in_threadpool(self.store.get_document, uid, request.path_params["doc"])
        number = request.query_params.get("v")
        content = await run_in_threadpool(self.store.read_document, uid, doc.id, int(number) if number and number.isdigit() else None) if doc else None
        if doc is None or content is None:
            return self._book_page("문서", '<p class="msg err">없는 문서입니다.</p>', session, 404)

        def build() -> bytes:
            with tempfile.TemporaryDirectory() as tmp:
                out = write_docx(content, Path(tmp) / "doc.docx")
                return out.read_bytes()

        data = await run_in_threadpool(build)
        name = urllib.parse.quote(f"{doc.title}.docx")
        return Response(data, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{name}"})

    # ---- 올린 문서·문서 설정(이름·색·컨텍스트·위치)과 휴지통 ----------------------------------------------
    async def book_edit(self, request: Request, key: str) -> Response:
        session = self.user_of(request)
        if not session:
            return self._need_login(request)
        uid = session[0]
        kind, ident = key.split(".", 1)
        if kind == "ms":
            project = await run_in_threadpool(self.store.get_project, uid, ident)
            if project is None:
                return self._book_page("책 설정", '<p class="msg err">없는 책입니다.</p>', session, 404)
            name, color, floor_id, back = project.title, project.color or MANUSCRIPT_COLOR, project.id, f"/shelf/book/{ident}"
            attached = project.contexts
        else:
            doc = await run_in_threadpool(self.store.get_document, uid, ident)
            if doc is None:
                return self._book_page("책 설정", '<p class="msg err">없는 책입니다.</p>', session, 404)
            name, color, floor_id, back = doc.title, doc.color, doc.floor, f"/shelf/doc/{ident}"
            attached = doc.contexts
        error = ""
        saved = await run_in_threadpool(self.store.list_saved_contexts, uid)
        if request.method == "POST":
            try:
                form = await self._form(request, session)
            except PermissionError:
                return self._book_page("책 설정", '<p class="msg err">잘못된 요청입니다.</p>', session, 403)
            new_name = " ".join(str(form.get("name") or "").split())[:120]
            if form.get("register") is not None:  # 자주 쓰는 컨텍스트로 등록만 하고 이 화면을 다시 보인다
                error = await run_in_threadpool(register_row, self.store, uid, form)
                saved = await run_in_threadpool(self.store.list_saved_contexts, uid)
                try:
                    attached = contexts_from_form(form, saved)
                except ValueError:
                    pass
                name, color = new_name or name, safe_color(str(form.get("hex") or ""), color)
                form = None
        if request.method == "POST" and form is not None:
            try:
                attached = contexts_from_form(form, saved)
                new_color = chosen_color(form)
                if not new_name:
                    raise ValueError("이름을 적어 주세요.")
                if kind == "ms":
                    if new_name != name:
                        await run_in_threadpool(self.store.set_titles, uid, ident, BookTitles(title=new_name, subtitle=project.subtitle,
                                                                                               title_en=project.title_en,
                                                                                               subtitle_en=project.subtitle_en))
                    await run_in_threadpool(self.store.set_project_color, uid, ident, new_color)
                else:
                    await run_in_threadpool(lambda: self.store.update_document(
                        uid, ident, title=new_name if new_name != name else None, color=new_color,
                        title_by="author" if new_name != name else None))
                await run_in_threadpool(self.store.set_book_contexts, uid, key, attached)
                note = await run_in_threadpool(self._keep_color, uid, form, new_color)
                return RedirectResponse(f"{back}?done=edit" + note, status_code=303)
            except ValueError as e:
                error = f'<p class="msg err">{html.escape(str(e))}</p>'
                name, color = new_name or name, safe_color(str(form.get("hex") or ""), color)
        settings = await run_in_threadpool(self.store.get_shelf_settings, uid)
        if kind == "ms":
            place = ""  # 올린 문서는 가운데 노드 자체라 옮기지 않는다(도움말)
        else:
            from magus.webshelf import Kind  # noqa: PLC0415

            place = await run_in_threadpool(self.location_form, uid, session, Kind(key, name, [], "", None, floor_id, "doc"))
        body = (
            f'{error}'
            f'<form method="post" action="/shelf/edit/{html.escape(key)}" class="colors">{self._csrf_input(session)}'
            f'<label class="block">이름 <input name="name" value="{html.escape(name)}" maxlength="120" required></label>'
            + context_fieldset(saved, attached)
            + color_fieldset(color, settings.my_colors)
            + f'<p><button class="primary">저장</button> <a href="{html.escape(back)}">취소</a></p></form>'
            + place + f'<p><a href="/shelf/trash/{html.escape(key)}">휴지통</a></p>'
        )
        from magus.webshelf import COLOR_SCRIPT  # noqa: PLC0415

        return self._book_page("책 설정", body + COLOR_SCRIPT + CONTEXT_SCRIPT, session,
                               400 if error.startswith('<p class="msg err">') else 200,
                               lead=await run_in_threadpool(self.trail, uid, key, "책 설정"))

    async def book_trash(self, request: Request, key: str) -> Response:
        session = self.user_of(request)
        if not session:
            return self._need_login(request)
        uid = session[0]
        kind, ident = key.split(".", 1)
        if kind == "ms":
            project = await run_in_threadpool(self.store.get_project, uid, ident)
            if project is None:
                return self._book_page("휴지통으로", '<p class="msg err">없는 책입니다.</p>', session, 404)
            name, floor_id, back = project.title, project.id, f"/shelf/book/{ident}"
            chapters = await run_in_threadpool(self.store.list_chapters, uid, ident)
            issues = await run_in_threadpool(self.store.list_issues, uid, ident, None)
            decisions = await run_in_threadpool(self.store.list_decisions, uid, ident)
            what = f" · 장 {len(chapters)} · 확인 요청 {len(issues)} · 결정 {len(decisions)}"
        else:
            doc = await run_in_threadpool(self.store.get_document, uid, ident)
            if doc is None:
                return self._book_page("휴지통으로", '<p class="msg err">없는 책입니다.</p>', session, 404)
            name, floor_id, back = doc.title, doc.floor, f"/shelf/doc/{ident}"
            what = f" · 만든 이력 {len(doc.versions)}"
        if request.method == "POST":
            try:
                await self._form(request, session)
            except PermissionError:
                return self._book_page("휴지통", '<p class="msg err">잘못된 요청입니다.</p>', session, 403)
            if kind == "ms":
                await run_in_threadpool(self.store.trash_manuscript, uid, ident, "웹 책장에서 옮김")
            else:
                await run_in_threadpool(self.store.trash_document, uid, ident, "웹 책장에서 옮김")
            return RedirectResponse(state_url(floor_id, done="trash"), status_code=303)
        body = (f'<div class="card"><p>「{html.escape(name)}」{what}</p>'
                f'<form method="post" action="/shelf/trash/{html.escape(key)}">{self._csrf_input(session)}'
                f'<p><button>휴지통으로 옮기기</button> <a href="{html.escape(back)}">취소</a></p></form></div>')
        return self._book_page("휴지통", body, session, lead=await run_in_threadpool(self.trail, uid, key, "휴지통"))
