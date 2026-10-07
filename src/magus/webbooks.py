"""모든 동작을 책장에서(사용자 결정 #94, 2026-10-07): 책 추가(원고·모음·문서), 원고 책 화면, 문서 책 화면, 문헌 등록. Web에 섞는 BookPages.

- 책 추가(/shelf/add?floor=): 종류를 고른다. 원고는 그 자리에서 파일을 고르면 올라가고 가져오기까지 한다(받은함을 거치지 않음, 진행 표시).
  모음은 이름·템플릿·색(/shelf/new). 문서는 Claude 대화로 만든다는 안내만.
- 원고 책(/shelf/book/<id>): 장 목록 · 확인 요청 · 인용 상태(체크리스트 + 답해 주실 질문) · 수정본 이력(수정본 올리기 포함) 탭.
  옛 주소 /book·/issues·/checklist·/questions는 여기로 넘긴다.
- 문서 책(/shelf/doc/<id>): 읽기용. 기준 원고에 새 수정본이 오면 '옛 판 기준'과 '다시 만들기'. docx 내려받기, 인쇄·PDF로 저장(브라우저 인쇄).
- 원고 책·문서 책도 책 색·이름 바꾸기·휴지통은 같은 방식(/shelf/edit/…, /shelf/trash/…). 원고 책은 그 층 자체라 옮기지 않는다.
- 문헌 책에 논문 파일을 넣어 확인한 문헌으로 등록하는 길(/shelf/refs/register)도 여기 있다(쓸 부분과 이유는 저자가 적는다).
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
from magus.book.reupload import reupload_manuscript
from magus.floors import COMMON
from magus.ids import local_time
from magus.inbox import LimitError, mb, safe_filename, save_upload
from magus.mdlite import to_html
from magus.melchior.author_report import cite_label, write_docx
from magus.melchior.check import after_refs_changed, cite_floors
from magus.melchior.questions import TYPES as QUESTION_TYPES
from magus.melchior.questions import build_questions
from magus.melchior.refs import add_ref
from magus.melchior.report import build_cite_report
from magus.store import BookTitles, Floor, Passage, Store
from magus.store.base import STALE_REASONS
from magus.webshelf import color_fieldset, chosen_color, safe_color

LIGHTS = {"verified": ("🟢", "확인"), "unverified": ("🟡", "미확인"), "unknown": ("🔴", "참고문헌에 없음"),
          "uncertain": ("⚪", "미연결")}
QUESTION_STATES = {"open": "열림", "waiting": "답함·원고 반영 대기", "answered": "답함"}
ISSUE_KIND_NAMES = {"citation": "문헌 확인", "fact": "사실·수치 확인", "general": "기타"}
TABS = (("chapters", "장 목록"), ("issues", "확인 요청"), ("cites", "인용 상태"), ("editions", "수정본 이력"))
MANUSCRIPT_COLOR = "#4b2e1e"  # 원고 책의 처음 색(짙은 가죽색). 저자가 바꿀 수 있다
WHEN = "%Y-%m-%d %H:%M"
IMPORTING = "가져오는 중입니다. 장을 나누고 코멘트와 참고문헌을 읽고 있습니다(큰 원고는 몇십 초 걸립니다)."
EDITING = "수정본을 맞춰 보는 중입니다. 바뀐 장을 찾고 확인 요청을 잇고 있습니다(큰 원고는 몇십 초 걸립니다)."

BOOK_STYLE = """
.tabs{display:flex;flex-wrap:wrap;gap:4px 8px;margin:12px 0 16px;border-bottom:2px solid var(--line)}
.tabs a{display:inline-flex;align-items:center;min-height:44px;padding:8px 16px;text-decoration:none;color:var(--ink2);font-weight:600;
border-bottom:3px solid transparent;margin-bottom:-2px}
.tabs a[aria-current=page]{color:var(--primary);border-bottom-color:var(--primary)}
.kinds{display:grid;grid-template-columns:repeat(auto-fit,minmax(270px,1fr));gap:16px;margin:16px 0}
.kind{margin:0}.kind h2{margin-top:4px}.kind .muted{font-size:15px}
.kind input[type=file]{display:block;margin:12px 0;font-size:16px;max-width:100%}
a.button{display:inline-flex;align-items:center;min-height:44px;padding:8px 16px;border-radius:999px;background:var(--primary);color:#fff;
text-decoration:none;font-weight:600}a.button:hover{background:var(--press);color:#fff}
.progress{display:none;margin:12px 0}.progress.on{display:block}
.progress .bar{height:12px;border-radius:6px;background:var(--line);overflow:hidden}
.progress .bar i{display:block;height:100%;width:0;background:var(--primary);transition:width .2s}
.progress .say{margin:8px 0 0;font-weight:600}
.doc{background:var(--canvas);border:1px solid var(--line);border-radius:12px;padding:4px 28px 24px;box-shadow:var(--shadow);max-width:880px}
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
      xhr.onerror = function () { say.textContent = "올리지 못했습니다. 연결을 확인하고 다시 해 주세요."; if (button) button.disabled = false; };
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


REGISTER_ERRORS = {
    "big": "파일이 너무 크거나 저장 용량을 넘었습니다.",
    "passage": "쓸 부분과 고른 이유를 적어 주세요.",
    "bib": "목록에서 문헌을 고르거나, 새 문헌의 저자와 네 자리 연도를 적어 주세요.",
    "other": "등록하지 못했습니다. 적은 것을 다시 확인해 주세요.",
}


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

    def book_routes(self) -> list[tuple[str, list[str], Callable[..., Any]]]:
        return [
            ("/shelf/add", ["GET"], self.add_book),
            ("/shelf/manuscript", ["POST"], self.manuscript_upload),
            ("/shelf/book/{project}", ["GET"], self.manuscript_page),
            ("/shelf/book/{project}/edition", ["POST"], self.edition_upload),
            ("/shelf/doc/{doc}", ["GET"], self.document_page),
            ("/shelf/doc/{doc}/redo", ["POST"], self.document_redo),
            ("/shelf/doc/{doc}/docx", ["GET"], self.document_docx),
            ("/shelf/refs/register", ["POST"], self.ref_register),
        ]

    def _book_page(self, title: str, body: str, session: tuple[str, str], status: int = 200) -> Response:
        from magus.webshelf import SHELF_STYLE

        return self._page(title, body, session, status, current="책장", css=SHELF_STYLE + BOOK_STYLE)

    def _floor_crumb(self, uid: str, floor_id: str) -> str:
        floor = self.store.get_floor(uid, floor_id)
        where = f' · <a href="/shelf/floor/{html.escape(floor_id)}">{floor.label}</a>' if floor else ""
        return f'<p class="crumb"><a href="/shelf">← 책장</a>{where}</p>'

    # ---- 책 추가 ------------------------------------------------------------------------------
    def _add_body(self, uid: str, session: tuple[str, str], floor: Floor, error: str = "") -> str:
        csrf = self._csrf_input(session)
        limit = f"파일 한 개 {mb(self.settings.max_upload_bytes)}까지(docx 또는 pdf)."
        if floor.common:
            manuscript = (
                '<section class="card kind"><h2>원고 책</h2>'
                "<p>공용 층에는 모음 책만 둘 수 있습니다. 원고 파일을 고르면 새 층을 만들고 그 층의 원고 책으로 꽂습니다.</p>"
                f'<form method="post" action="/shelf/manuscript" enctype="multipart/form-data" data-progress="{IMPORTING}">{csrf}'
                '<input type="hidden" name="floor" value="new">'
                f'<label>원고 파일 <input type="file" name="file" accept=".docx,.pdf" required></label><p class="muted">{limit}</p>'
                f'<p><button class="primary">새 층에 올리기</button></p>{progress_box()}</form></section>'
            )
        elif floor.has_manuscript:
            manuscript = (
                '<section class="card kind"><h2>원고 책</h2>'
                "<p>이 층에는 원고 책이 이미 있습니다. Word에서 고친 원고는 원고 책 안의 '수정본 이력'에서 올립니다.</p>"
                f'<p><a href="/shelf/book/{html.escape(floor.id)}?tab=editions">원고 책의 수정본 올리기로 가기</a></p></section>'
            )
        else:
            manuscript = (
                '<section class="card kind"><h2>원고 책</h2>'
                "<p>Word(docx)나 PDF 원고 파일을 고르면 바로 올라가고, 장·확인 요청·참고문헌을 읽어 이 층의 원고 책이 됩니다.</p>"
                f'<form method="post" action="/shelf/manuscript" enctype="multipart/form-data" data-progress="{IMPORTING}">{csrf}'
                f'<input type="hidden" name="floor" value="{html.escape(floor.id)}">'
                f'<label>원고 파일 <input type="file" name="file" accept=".docx,.pdf" required></label><p class="muted">{limit}</p>'
                f'<p><button class="primary">올리기</button></p>{progress_box()}</form></section>'
            )
        collection = (
            '<section class="card kind"><h2>모음 책</h2>'
            "<p>생각·사례·인물·용어처럼 모아 두는 책입니다. 이름·템플릿·색을 정합니다.</p>"
            f'<p><a class="button" href="/shelf/new?floor={urllib.parse.quote(floor.id)}">모음 책 만들기</a></p></section>'
        )
        document = (
            '<section class="card kind"><h2>문서 책</h2>'
            "<p>원고에서 만든 읽기용 문서입니다(첫 종류: 출처 확인 문서). Claude에게 이렇게 말씀하세요.</p>"
            "<p><b>\"이 원고 인용 확인하고 나에게 물어볼 것 정리해서 「… 출처 확인 문서」로 만들어 이 층에 넣어 줘\"</b></p>"
            '<p class="muted">질문·수치·문헌 목록은 Magus가 원고와 문헌에서 그대로 만듭니다. Claude는 원하시면 머리말만 붙입니다.</p></section>'
        )
        if floor.common:
            document = document.replace("<p>원고에서 만든", "<p>문서 책은 작업물 층에 꽂힙니다. 원고에서 만든", 1)
        err = f'<p class="msg err">{html.escape(error)}</p>' if error else ""
        return f'{self._floor_crumb(uid, floor.id)}{err}<div class="kinds">{manuscript}{collection}{document}</div>{UPLOAD_PROGRESS}'

    async def add_book(self, request: Request) -> Response:
        session = self.user_of(request)
        if not session:
            return self._need_login(request)
        uid = session[0]
        floor = await run_in_threadpool(self.store.get_floor, uid, request.query_params.get("floor") or COMMON)
        if floor is None:
            return self._book_page("책 추가", '<p class="msg err">없는 층입니다. <a href="/shelf">책장</a>으로 돌아가세요.</p>', session, 404)
        body = await run_in_threadpool(self._add_body, uid, session, floor)
        return self._book_page(f"책 추가 · {floor.label}", body, session)

    async def _uploaded(self, request: Request, session: tuple[str, str]) -> tuple[Any, bytes, str]:
        """(폼, 파일 내용, 안전한 파일 이름). 한도·형식이 맞지 않으면 ValueError(저자에게 보일 문장)."""
        limit = self.settings.max_upload_bytes + 1_000_000
        if int(request.headers.get("content-length") or 0) > limit:
            raise ValueError(f"파일이 너무 큽니다(한 개 한도 {mb(self.settings.max_upload_bytes)}).")
        form = await self._form(request, session)
        item = form.get("file")
        if not isinstance(item, UploadFile) or not item.filename:
            raise ValueError("올릴 원고 파일을 골라 주세요.")
        name = safe_filename(item.filename)
        if Path(name).suffix.lower() not in (".docx", ".pdf"):
            raise ValueError("원고는 docx 또는 pdf 파일이어야 합니다.")
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
        floor_id = "new"
        try:
            form, data, name = await self._uploaded(request, session)
            floor_id = str(form.get("floor") or "new")
            project_id = None
            if floor_id != "new":
                floor = await run_in_threadpool(self.store.get_floor, uid, floor_id)
                if floor is None or floor.common:
                    raise ValueError("원고 책은 작업물 층에 꽂습니다.")
                if floor.has_manuscript:
                    raise ValueError("이 층에는 원고 책이 이미 있습니다. 고친 원고는 원고 책의 '수정본 이력'에서 올립니다.")
                project_id = floor.id
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / name
                path.write_bytes(data)
                report = await run_in_threadpool(import_manuscript, self.store, uid, path, project_id=project_id)
        except PermissionError:
            return self._book_page("책 추가", '<p class="msg err">잘못된 요청입니다.</p>', session, 403)
        except (ValueError, FileNotFoundError, LimitError) as e:
            floor = await run_in_threadpool(self.store.get_floor, uid, floor_id if floor_id != "new" else COMMON)
            floor = floor or await run_in_threadpool(self.store.get_floor, uid, COMMON)
            body = await run_in_threadpool(self._add_body, uid, session, floor, str(e))
            return self._book_page(f"책 추가 · {floor.label}", body, session, 400)
        return RedirectResponse(f"/shelf/book/{report.project_id}?done=imported", status_code=303)

    # ---- 원고 책 ------------------------------------------------------------------------------
    def _manuscript_head(self, uid: str, project: Any, tab: str) -> str:
        chapters = self.store.list_chapters(uid, project.id)
        issues = self.store.list_issues(uid, project.id, "open")
        last = latest_edition(self.store, uid, project.id)
        parts = len(self.store.list_parts(uid, project.id))
        meta = (f"원고 책 · {chapter_count(chapters)}" + (f" · {parts}부" if parts else "") + f" · {sum(c.char_count for c in chapters):,}자 · "
                + (f"수정본 E{last}" if last else "수정본 기록 없음") + f" · 열린 확인 요청 {len(issues)}건"
                + f' · <a href="/shelf/edit/ms.{html.escape(project.id)}">책 설정</a>')
        base = f"/shelf/book/{urllib.parse.quote(project.id)}"
        tabs = "".join(f'<a href="{base}?tab={key}"{" aria-current=page" if key == tab else ""}>{name}</a>' for key, name in TABS)
        return f'{self._floor_crumb(uid, project.id)}<p class="floor-meta">{meta}</p><nav class="tabs" aria-label="원고 책">{tabs}</nav>'

    def _manuscript_done(self, uid: str, project: Any, request: Request) -> str:
        done = request.query_params.get("done")
        if done == "imported":
            chapters = self.store.list_chapters(uid, project.id)
            issues = self.store.list_issues(uid, project.id, None)
            refs = self.store.list_refs(uid, floors=cite_floors(project.id))
            return (f'<p class="msg">원고 책을 만들었습니다: {chapter_count(chapters)} · 부 {len(self.store.list_parts(uid, project.id))}개 · '
                    f"확인 요청 {len(issues)}건(원고 코멘트에서) · 문헌 {len(refs)}편(참고문헌에서). "
                    "가져온 내용은 '수정본 이력'의 리포트에서 볼 수 있습니다.</p>")
        if done == "edition":
            return f'<p class="msg">수정본 E{latest_edition(self.store, uid, project.id)}을 올렸습니다. 아래 리포트에서 바뀐 것을 보세요.</p>'
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
            return self._book_page("원고 책", '<p class="msg err">없는 원고 책입니다. <a href="/shelf">책장</a>으로 돌아가세요.</p>', session, 404)
        tab = request.query_params.get("tab") if request.query_params.get("tab") in dict(TABS) else "chapters"
        body = await run_in_threadpool(self._manuscript_body, uid, session, project, tab, request)
        return self._book_page(project.title, body, session)

    def _manuscript_body(self, uid: str, session: tuple[str, str], project: Any, tab: str, request: Request, error: str = "") -> str:
        head = self._manuscript_head(uid, project, tab) + self._manuscript_done(uid, project, request)
        head += f'<p class="msg err">{html.escape(error)}</p>' if error else ""
        params = request.query_params
        if tab == "issues":
            return head + self._issues_html(uid, project, params)
        if tab == "cites":
            return head + (self._questions_html(uid, project, params) if params.get("view") == "questions"
                           else self._checklist_html(uid, project, params))
        if tab == "editions":
            return head + self._editions_html(uid, session, project, params)
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
            "<p>원고 본문의 원본은 저자의 Word 파일입니다. 여기는 마지막으로 올린 원고의 사본입니다.</p>"
            f'<form method="post" action="/book/export" class="doc-actions">{self._csrf_input(session)}'
            f'<input type="hidden" name="project_id" value="{html.escape(project.id)}"><button>docx로 내려받기</button>'
            f' <a href="/shelf/book/{urllib.parse.quote(project.id)}?tab=editions">수정본 올리기</a></form>'
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
                return f'<span class="tag">🤖 AI 확인 요청{name}</span>' if i.by_ai else f"원고 코멘트{name}"
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
        return (f"<p>확인 요청 {len(issues)}건" + (f" · 그중 🤖 AI 확인 요청 {ai}건(AI가 원고에 단 코멘트입니다)" if ai else "")
                + " · 답하거나 닫을 때는 Claude에게 번호(I3 등)로 말씀해 주세요.</p>"
                f'<p><a href="{base}&status=open">열린 것</a> · <a href="{base}&status=closed">닫힌 것</a> · '
                f'<a href="{base}&status=all">전체</a> | {filters}</p>'
                f"<table><tr><th>번호</th><th>장</th><th>누가</th><th>종류</th><th>내용</th></tr>{rows or '<tr><td colspan=\"5\">없음</td></tr>'}</table>")

    def _checklist_html(self, uid: str, project: Any, params: Any) -> str:
        report = build_cite_report(self.store, uid, project.id)
        refs = {r.key: r for r in self.store.list_refs(uid, floors=cite_floors(project.id))}  # 그 작업물 층 + 공용(#93)
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
                f'<p><a href="{base}&view=questions"><b>답해 주실 질문 {len(questions)}건</b></a> — 저자만 답할 수 있는 것을 모았습니다.</p>'
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
            f"<p>{html.escape(x.text)}</p><p class=\"muted\">고를 수 있는 답: {options(x)}</p>{answered(x)}</li>"
            for x in chosen
        )
        types = " · ".join(f'<a href="{base}&status={status}&type={t}">{name} {sum(1 for x in everything if x.type == t)}</a>'
                           for t, name in QUESTION_TYPES.items() if any(x.type == t for x in everything))
        return (f'<p><a href="/shelf/book/{urllib.parse.quote(project.id)}?tab=cites">← 인용 상태</a></p>'
                f"<h2>답해 주실 질문 {len(everything)}건</h2>"
                f"<p>열림 {counts['open']} · 원고 반영 대기 {counts['waiting']} · 답함 {counts['answered']}</p>"
                "<p>Magus가 원고와 참고문헌을 맞춰 보다가 저자만 답할 수 있는 것을 모았습니다. "
                "답은 Claude에게 말씀해 주세요. 예: \"답해 주실 질문 보여 줘\", \"그 연도는 본문을 고칠게\"</p>"
                f'<p><a href="{base}&status=open">열린 것</a> · <a href="{base}&status=waiting">원고 반영 대기</a> · '
                f'<a href="{base}&status=all">전체</a>' + (f" | {types}" if types else "") + "</p>"
                + (f'<ol class="qlist">{cards}</ol>' if cards else '<p class="msg">없음</p>'))

    def _editions_html(self, uid: str, session: tuple[str, str], project: Any, params: Any) -> str:
        editions = self.store.list_editions(uid, project.id)
        base = f"/shelf/book/{urllib.parse.quote(project.id)}?tab=editions"
        rows = "".join(
            f"<tr><td>{'처음 올린 원고 E1' if e.number == 1 else f'수정본 E{e.number}'}</td><td>{html.escape(e.file)}</td>"
            f'<td class="num">{local_time(e.uploaded_at, WHEN)}</td>'
            f'<td class="num">{e.changed}</td><td class="num">{e.added}</td><td class="num">{e.removed}</td><td class="num">{e.unchanged}</td>'
            f'<td><a href="{base}&report={e.number}">리포트</a></td></tr>'
            for e in reversed(editions)
        )
        wanted = params.get("report") or ("" if not editions else str(editions[-1].number) if params.get("done") == "edition" else "")
        report = ""
        if wanted.isdigit():
            name = "import-report.md" if wanted == "1" else f"E{wanted}-reupload-report.md"
            text = self.store.read_original(uid, project.id, name)
            if text:
                report = f'<section class="report"><h2>리포트 — {"처음 올린 원고" if wanted == "1" else f"수정본 E{wanted}"}</h2>{to_html(text)}</section>'
        upload = (
            f'<form method="post" action="/shelf/book/{urllib.parse.quote(project.id)}/edition" enctype="multipart/form-data" '
            f'class="card" data-progress="{EDITING}">{self._csrf_input(session)}<h2>수정본 올리기</h2>'
            "<p>Word에서 고친 원고 파일을 고르면 바로 수정본으로 맞춥니다. 바뀐 장만 바뀌고, 결정·확인 요청·생각·문체·문헌은 그대로입니다.</p>"
            '<label>고친 원고 파일 <input type="file" name="file" accept=".docx,.pdf" required></label>'
            '<p><label><input type="checkbox" name="force" value="1"> 장 제목이 많이 달라도 같은 책으로 올리기</label></p>'
            f'<p><button class="primary">수정본 올리기</button></p>{progress_box()}</form>'
        )
        table = ('<table><tr><th>수정본</th><th>파일</th><th class="num">올린 시각</th><th class="num">바뀐 장</th><th class="num">새 장</th>'
                 f'<th class="num">빠진 장</th><th class="num">그대로</th><th></th></tr>{rows}</table>' if rows
                 else "<p>수정본 기록이 없습니다(수정본 기능 전에 가져온 원고).</p>")
        return upload + UPLOAD_PROGRESS + "<h2>수정본 이력</h2>" + table + report

    async def edition_upload(self, request: Request) -> Response:
        session = self.user_of(request)
        if not session:
            return self._need_login(request)
        uid = session[0]
        project = await run_in_threadpool(self.store.get_project, uid, request.path_params["project"])
        if project is None:
            return self._book_page("원고 책", '<p class="msg err">없는 원고 책입니다.</p>', session, 404)
        try:
            form, data, name = await self._uploaded(request, session)
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / name
                path.write_bytes(data)
                await run_in_threadpool(lambda: reupload_manuscript(self.store, uid, path, project.id, force=form.get("force") == "1"))
        except PermissionError:
            return self._book_page(project.title, '<p class="msg err">잘못된 요청입니다.</p>', session, 403)
        except (ValueError, FileNotFoundError, LimitError) as e:
            body = await run_in_threadpool(self._manuscript_body, uid, session, project, "editions", request, str(e))
            return self._book_page(project.title, body, session, 400)
        return RedirectResponse(f"/shelf/book/{urllib.parse.quote(project.id)}?tab=editions&done=edition", status_code=303)

    # ---- 문서 책 ------------------------------------------------------------------------------
    async def document_page(self, request: Request) -> Response:
        session = self.user_of(request)
        if not session:
            return self._need_login(request)
        uid = session[0]
        doc = await run_in_threadpool(self.store.get_document, uid, request.path_params["doc"])
        if doc is None:
            return self._book_page("문서 책", '<p class="msg err">없는 문서 책입니다. <a href="/shelf">책장</a>으로 돌아가세요.</p>', session, 404)
        number = request.query_params.get("v")
        number_i = int(number) if number and number.isdigit() else doc.versions[-1].number
        content = await run_in_threadpool(self.store.read_document, uid, doc.id, number_i)
        if content is None:
            return self._book_page(doc.title, '<p class="msg err">없는 이력입니다.</p>', session, 404)
        body = await run_in_threadpool(self._document_body, uid, session, doc, number_i, content, request)
        return self._book_page(doc.title, body, session)

    def _document_body(self, uid: str, session: tuple[str, str], doc: Any, number: int, content: str, request: Request) -> str:
        version = next(v for v in doc.versions if v.number == number)
        current = doc.versions[-1]
        project = self.store.get_project(uid, doc.project_id)
        made = "서버가 원고·문헌 데이터로 만듦" + {"ai": "(머리말은 Claude가 씀)", "author": "(머리말은 저자가 말함)"}.get(version.preface_by or "", "")
        meta = (f"문서 책 · {DOC_TYPES.get(doc.doc_type, doc.doc_type)} · 기준 원고 "
                + (f"『{html.escape(project.title)}』" if project else "(없음)") + (f" E{version.edition}" if version.edition else "")
                + f" · 만든 시각 {local_time(version.at, WHEN)} · {made}"
                + f' · <a href="/shelf/edit/doc.{html.escape(doc.id)}">책 설정</a>')
        notices = ""
        if request.query_params.get("done") == "redo":
            notices += '<p class="msg">다시 만들었습니다. 이전 것은 아래 \'만든 이력\'에 남아 있습니다.</p>'
        if number != current.number:
            notices += (f'<p class="msg">지금 보고 있는 것은 이력({number}번째, {local_time(version.at, WHEN)})입니다. '
                        f'<a href="/shelf/doc/{html.escape(doc.id)}">지금 것 보기</a></p>')
        elif is_stale(self.store, uid, doc):
            now = latest_edition(self.store, uid, doc.project_id)
            notices += (f'<div class="msg stale">{STALE_WORDS}: 기준 원고에 새 수정본(E{now})이 왔습니다. 이 문서는 '
                        + (f"E{current.edition}" if current.edition else "수정본 기록 전") + " 기준입니다. "
                        f'<form method="post" action="/shelf/doc/{html.escape(doc.id)}/redo" class="inline">{self._csrf_input(session)}'
                        "<button>다시 만들기</button></form></div>")
        actions = (f'<div class="doc-actions"><a href="/shelf/doc/{html.escape(doc.id)}/docx?v={number}">docx로 내려받기</a>'
                   '<button type="button" onclick="window.print()">인쇄·PDF로 저장</button>'
                   + ("" if number != current.number or is_stale(self.store, uid, doc) else
                      f'<form method="post" action="/shelf/doc/{html.escape(doc.id)}/redo" class="inline">{self._csrf_input(session)}'
                      "<button>지금 원고로 다시 만들기</button></form>") + "</div>")
        history = "".join(
            f'<li><a href="/shelf/doc/{html.escape(doc.id)}?v={v.number}">{v.number}번째</a> · {local_time(v.at, WHEN)} · '
            + (f"E{v.edition} 기준" if v.edition else "수정본 기록 전") + (" · 지금 것" if v.number == current.number else "") + "</li>"
            for v in reversed(doc.versions)
        )
        return (f'{self._floor_crumb(uid, doc.floor)}<p class="floor-meta">{meta}</p>{notices}{actions}'
                f'<article class="doc">{to_html(content)}</article>'
                f'<details class="card no-print"><summary>만든 이력 {len(doc.versions)}</summary><ol>{history}</ol>'
                "<p class=\"muted\">다시 만들면 서버가 지금의 원고·문헌으로 질문·수치를 새로 만듭니다(머리말은 넣지 않습니다. "
                "머리말이 필요하면 Claude에게 부탁하세요). 답하고 닫는 일은 원고 책의 확인 요청에서 합니다.</p></details>")

    async def document_redo(self, request: Request) -> Response:
        session = self.user_of(request)
        if not session:
            return self._need_login(request)
        uid = session[0]
        try:
            await self._form(request, session)
        except PermissionError:
            return self._book_page("문서 책", '<p class="msg err">잘못된 요청입니다.</p>', session, 403)
        doc = await run_in_threadpool(self.store.get_document, uid, request.path_params["doc"])
        if doc is None:
            return self._book_page("문서 책", '<p class="msg err">없는 문서 책입니다.</p>', session, 404)

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
            return self._book_page("문서 책", '<p class="msg err">없는 문서 책입니다.</p>', session, 404)

        def build() -> bytes:
            with tempfile.TemporaryDirectory() as tmp:
                out = write_docx(content, Path(tmp) / "doc.docx")
                return out.read_bytes()

        data = await run_in_threadpool(build)
        name = urllib.parse.quote(f"{doc.title}.docx")
        return Response(data, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{name}"})

    # ---- 원고 책·문서 책 설정(이름·색·위치)과 휴지통 ------------------------------------------------
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
        else:
            doc = await run_in_threadpool(self.store.get_document, uid, ident)
            if doc is None:
                return self._book_page("책 설정", '<p class="msg err">없는 책입니다.</p>', session, 404)
            name, color, floor_id, back = doc.title, doc.color, doc.floor, f"/shelf/doc/{ident}"
        error = ""
        if request.method == "POST":
            try:
                form = await self._form(request, session)
            except PermissionError:
                return self._book_page("책 설정", '<p class="msg err">잘못된 요청입니다.</p>', session, 403)
            new_name = " ".join(str(form.get("name") or "").split())[:120]
            try:
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
                note = await run_in_threadpool(self._keep_color, uid, form, new_color)
                return RedirectResponse(f"/shelf/floor/{floor_id}?done=edit&c={key}" + note, status_code=303)
            except ValueError as e:
                error = f'<p class="msg err">{html.escape(str(e))}</p>'
                name, color = new_name or name, safe_color(str(form.get("hex") or ""), color)
        settings = await run_in_threadpool(self.store.get_shelf_settings, uid)
        if kind == "ms":
            place = '<h2>위치</h2><p class="muted">원고 책은 그 층 자체라 다른 층으로 옮기지 않습니다. 다른 작업물이면 새 층을 만들어 원고를 올려 주세요.</p>'
        else:
            from magus.webshelf import Kind  # noqa: PLC0415

            place = await run_in_threadpool(self.location_form, uid, session, Kind(key, name, [], "", None, floor_id, "doc"))
        body = (
            f'<p class="crumb"><a href="{html.escape(back)}">← {html.escape(name)}</a></p>{error}'
            f'<form method="post" action="/shelf/edit/{html.escape(key)}" class="colors">{self._csrf_input(session)}'
            f'<label class="block">이름 <input name="name" value="{html.escape(name)}" maxlength="120" required></label>'
            + color_fieldset(color, settings.my_colors)
            + f'<p><button class="primary">저장</button> <a href="{html.escape(back)}">그만두기</a></p></form>'
            + place + f'<h2>휴지통</h2><p><a href="/shelf/trash/{html.escape(key)}">이 책을 휴지통으로 옮기기</a></p>'
        )
        from magus.webshelf import COLOR_SCRIPT  # noqa: PLC0415

        return self._book_page(f"{name} — 책 설정", body + COLOR_SCRIPT, session, 400 if error else 200)

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
            what = (f"<p>장 {len(chapters)}개, 확인 요청 {len(issues)}건, 결정 {len(decisions)}건, 수정본 이력이 함께 옮겨집니다. "
                    "층과 층의 다른 책(생각·문헌·모음·문서)은 그대로 남고, 이 층은 원고가 없는 빈 층이 됩니다.</p>")
        else:
            doc = await run_in_threadpool(self.store.get_document, uid, ident)
            if doc is None:
                return self._book_page("휴지통으로", '<p class="msg err">없는 책입니다.</p>', session, 404)
            name, floor_id, back = doc.title, doc.floor, f"/shelf/doc/{ident}"
            what = f"<p>만든 이력 {len(doc.versions)}개가 함께 옮겨집니다.</p>"
        if request.method == "POST":
            try:
                await self._form(request, session)
            except PermissionError:
                return self._book_page("휴지통으로", '<p class="msg err">잘못된 요청입니다.</p>', session, 403)
            if kind == "ms":
                await run_in_threadpool(self.store.trash_manuscript, uid, ident, "웹 책장에서 옮김")
            else:
                await run_in_threadpool(self.store.trash_document, uid, ident, "웹 책장에서 옮김")
            return RedirectResponse(f"/shelf/floor/{floor_id}?done=trash", status_code=303)
        body = (f'<p class="crumb"><a href="{html.escape(back)}">← {html.escape(name)}</a></p>'
                f'<div class="card"><p>「{html.escape(name)}」을(를) 휴지통으로 옮길까요?</p>{what}'
                "<p>지우는 것이 아니라 옮기는 것이라 운영자가 되살릴 수 있습니다.</p>"
                f'<form method="post" action="/shelf/trash/{html.escape(key)}">{self._csrf_input(session)}'
                f'<p><button>휴지통으로 옮기기</button> <a href="{html.escape(back)}">그만두기</a></p></form></div>')
        return self._book_page("휴지통으로", body, session)

    # ---- 문헌 등록(문헌 책에 논문 파일 넣기) ------------------------------------------------------
    def ref_register_form(self, uid: str, session: tuple[str, str], floor: str) -> str:
        visible = [floor] if floor == COMMON else [floor, COMMON]
        refs = sorted((r for r in self.store.list_refs(uid, "unverified", floors=visible) if not r.key.startswith("raw-")),
                      key=lambda r: cite_label(r, r.key))
        options = "".join(f'<option value="{html.escape(r.key)}">{html.escape(cite_label(r, r.key))}</option>' for r in refs[:600])
        return (
            f'<details class="card write"><summary>논문 파일로 문헌 등록</summary>'
            "<p>원문을 읽고 쓸 부분을 고르셨으면, 그 파일을 올리고 쓸 부분과 고른 이유를 적어 주세요. '확인한 문헌'이 됩니다. "
            "Claude에게 말씀하셔도 됩니다(예: \"이 논문을 문헌으로 등록해 줘. 쓸 부분은 「…」, 이유는 …\").</p>"
            f'<form method="post" action="/shelf/refs/register" enctype="multipart/form-data">{self._csrf_input(session)}'
            f'<input type="hidden" name="floor" value="{html.escape(floor)}">'
            '<label class="block">논문 파일(pdf·docx·txt·md, 없어도 됩니다) <input type="file" name="file" accept=".pdf,.docx,.txt,.md"></label>'
            f'<label class="block">어느 문헌인가요? <select name="key"><option value="">목록에 없는 새 문헌(아래에 적기)</option>{options}</select></label>'
            '<details><summary>새 문헌이면: 저자·연도·제목</summary>'
            '<label class="block">저자(예: Kremer, M.) <input name="authors" maxlength="300"></label>'
            '<label class="block">연도(네 자리) <input name="year" maxlength="4" inputmode="numeric"></label>'
            '<label class="block">제목 <input name="title" maxlength="300"></label></details>'
            '<label class="block">쓸 부분(원문 그대로) <textarea name="passage" rows="4" required maxlength="5000"></textarea></label>'
            '<label class="block">고른 이유 <input name="reason" required maxlength="300"></label>'
            '<label class="block">쪽수 등 위치(선택, 예: p.45) <input name="locator" maxlength="60"></label>'
            "<p><button class=\"primary\">확인한 문헌으로 등록</button></p></form></details>"
        )

    async def ref_register(self, request: Request) -> Response:
        session = self.user_of(request)
        if not session:
            return self._need_login(request)
        uid = session[0]
        try:
            form = await self._form(request, session)
        except PermissionError:
            return self._book_page("문헌", '<p class="msg err">잘못된 요청입니다.</p>', session, 403)
        floor = str(form.get("floor") or COMMON)
        back = f"/shelf/refs.{floor}"
        key = str(form.get("key") or "").strip()
        bib: dict[str, Any] = {"key": key} if key else {
            "authors": str(form.get("authors") or "").strip(), "year": str(form.get("year") or "").strip(),
            "title": str(form.get("title") or "").strip()}
        passage = Passage(str(form.get("passage") or "").strip(), str(form.get("reason") or "").strip(),
                          str(form.get("locator") or "").strip() or None)
        item = form.get("file")
        try:
            path, label = None, None
            if isinstance(item, UploadFile) and item.filename:
                saved = await run_in_threadpool(save_upload, self.store, uid, item.filename, await item.read(),
                                                self.settings.max_upload_bytes, self.settings.max_user_bytes)
                path, label = self.store.inbox_path(uid, saved.name), f"inbox/{saved.name}"
            work = floor if floor != COMMON else None
            ref, _, _ = await run_in_threadpool(lambda: add_ref(self.store, uid, bib, [passage], file_path=str(path) if path else None,
                                                                file_label=label, floor=work, default_floor=lambda: COMMON))
            await run_in_threadpool(after_refs_changed, self.store, uid)
        except LimitError:
            return RedirectResponse(f"{back}?registererr=big", status_code=303)
        except (ValueError, FileNotFoundError) as e:  # 주소에는 정해진 코드만 싣는다(저자에게 보일 문장은 화면이 고른다)
            text = str(e)
            code = "passage" if ("passages" in text or "reason" in text) else "bib" if ("저자" in text or "key" in text) else "other"
            return RedirectResponse(f"{back}?registererr={code}", status_code=303)
        return RedirectResponse(f"/shelf/refs.{ref.floor}/{urllib.parse.quote(ref.key)}?done=registered", status_code=303)

