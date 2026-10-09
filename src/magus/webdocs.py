"""내 정보 › 문서 업데이트(2026-10-10, docs/decisions/document-update.md). Web에 섞어 쓰는 DocumentPages.

- /me/documents: 지금까지 올라간 문서(게시판 첨부 문서 + 예전 올린 파일)를 새것부터. 찾기 ?q=(파일 이름·프로젝트·노드·책·글 제목).
- 줄마다 [업데이트] → 새 파일 고르기 · 파일 이름(고른 파일 이름으로 미리 채움, 확장자 고정) → '바꾸기'(POST /me/documents/update).
  올린 문서의 원본이면 바꾸기가 곧 수정본 올리기다(결과 한 줄과 리포트 링크).
- 내 정보의 '올리기'는 없앴다: 옛 /inbox/upload·/inbox/delete로 POST가 오면 410과 안내. 옛 /me/files·/inbox는 이 화면으로.
- 글 보기의 ✎ 고치기에서 첨부를 바꿀 때도 같은 동작(magus.docupdate.update_document). 바꾸기 칸·스크립트는 여기 것을 함께 쓴다.
"""

from __future__ import annotations

import hashlib
import html
import logging
import re
import urllib.parse
from collections.abc import Awaitable, Callable
from typing import Any

from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from magus.docupdate import DOC_TYPES, DocRow, UpdateError, find_rows, list_documents, update_document
from magus.ids import local_time
from magus.inbox import MANUSCRIPT_TYPES, mb, size_text
from magus.logsafe import exc_summary
from magus.config import Settings
from magus.store import Store
from magus.store.fileio import data_size

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
log = logging.getLogger("magus.docupdate")
FAILED = "문서를 바꾸는 중에 문제가 생겼습니다. 잠시 뒤 다시 해 보시고, 계속되면 운영자에게 알려 주세요."


def log_failure(where: str, exc: BaseException) -> None:
    """예상 못 한 실패(바꾸기): 예외 종류와 스택(파일:줄 함수)만 남긴다. 메시지에는 파일 이름·글 내용이 들어갈 수 있어 넣지 않는다."""
    log.error("문서 바꾸기 실패(%s) | %s", where, exc_summary(exc))

DOCS_STYLE = """
.usage{color:var(--ink2);margin:8px 0}
.search{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:12px 0 16px}.search input[type=search]{flex:1 1 200px;font-size:17px}
ol.docs{list-style:none;padding:0;margin:12px 0;display:grid;gap:10px}
ol.docs>li{background:var(--canvas);border:1px solid var(--line);border-radius:12px;padding:12px 16px;box-shadow:var(--shadow)}
.dr-name{font-weight:600;overflow-wrap:anywhere}.dr-name small{font-weight:400;margin-left:8px}
.dr-where{color:var(--ink2);margin:4px 0;overflow-wrap:anywhere}.dr-where a{color:var(--primary);display:inline-flex;align-items:center;min-height:32px}
.dr-src{display:inline-block;margin:4px 0;padding:2px 10px;border-radius:9999px;background:var(--tag);color:var(--deep);font-size:14px}
details.upd{margin:8px 0 0}details.upd>summary.btn{min-height:36px}
details.upd form{margin:10px 0 2px;padding:12px;border:1px dashed var(--mute);border-radius:10px;background:var(--soft)}
.swap-name{display:flex;flex-wrap:wrap;align-items:center;gap:6px}.swap-name input{flex:1 1 220px}.swap-name .ext{color:var(--ink2)}
@media (max-width:767px){details.upd>summary.btn,.dr-where a{min-height:44px}}
"""

# 바꾸기 칸: 파일을 고르면 이름 칸을 그 파일 이름(확장자 뺀 것)으로 채우고, 확장자를 옆에 보인다(고칠 수 없다). 스크립트가 없으면 서버가 고른 이름 그대로 쓴다.
SWAP_SCRIPT = """<script>
document.querySelectorAll("[data-swap]").forEach(function (box) {
  var file = box.querySelector("input[type=file]"), name = box.querySelector("input[data-stem]"), ext = box.querySelector("[data-ext]");
  if (!file || !name) return;
  file.addEventListener("change", function () {
    var f = file.files && file.files[0]; if (!f) return;
    var i = f.name.lastIndexOf(".");
    name.value = i > 0 ? f.name.slice(0, i) : f.name;
    if (ext) ext.textContent = i > 0 ? f.name.slice(i) : "";
  });
});
</script>"""


def swap_fields(file_field: str, name_field: str, accept: str, *, dom_id: str | None = None, force: bool = False) -> str:
    """새 파일 고르기 + 파일 이름 칸(확장자는 옆에 고정) + (장 제목이 많이 달라 멈췄을 때만) '같은 책이 맞습니다'.
    name_field는 폼 칸 이름, dom_id는 화면 안에서 겹치지 않을 id(없으면 칸 이름)."""
    box = dom_id or name_field
    return (f'<p><label class="block">새 파일 <input type="file" name="{file_field}" accept="{accept}"></label></p>'
            f'<p class="swap-name"><label for="{box}">파일 이름</label>'
            f'<input id="{box}" name="{name_field}" data-stem maxlength="180"><span class="ext" data-ext></span></p>'
            + ('<p><label><input type="checkbox" name="force" value="1"> 같은 책이 맞습니다(장 제목이 많이 달라도 수정본으로 올리기)</label></p>'
               if force else ""))


def revision_query(result: Any) -> str:
    """바꾸기가 수정본이 됐으면 주소에 붙일 '&rev=…'(수정본 번호·프로젝트·바뀐 장·새 장·빠진 장). 아니면 빈 문자열."""
    rev = getattr(result, "revision", None)
    if rev is None or not getattr(result, "project_id", None):
        return ""
    return "&" + urllib.parse.urlencode([("p", result.project_id), ("e", rev.edition), ("c", len(rev.changed)),
                                         ("a", len(rev.added)), ("r", len(rev.removed))])


def revision_text(store: Store, uid: str, params: Any) -> str:
    """주소의 p·e·c·a·r → ' 「제목」 수정본 E4로 올렸습니다 · 바뀐 장 … · 리포트'(HTML, 이스케이프함). 없으면 빈 문자열."""
    if not _ID.fullmatch(params.get("p") or "") or not (params.get("e") or "").isdigit():
        return ""
    project = store.get_project(uid, params["p"])
    if project is None:
        return ""
    n = {k: int(params.get(k)) if (params.get(k) or "").isdigit() else 0 for k in ("e", "c", "a", "r")}
    report = f"/shelf/book/{urllib.parse.quote(project.id)}?tab=editions&report={n['e']}"
    return (f' 「{html.escape(project.title)}」 수정본 E{n["e"]}로 올렸습니다 · 바뀐 장 {n["c"]} · 새 장 {n["a"]} · 빠진 장 {n["r"]} · '
            f'<a href="{html.escape(report)}">리포트</a>')


class DocumentPages:
    store: Store
    settings: Settings
    _page: Callable[..., Response]
    user_of: Callable[[Request], tuple[str, str] | None]
    _need_login: Callable[[Request], Response]
    _csrf_input: Callable[[tuple[str, str]], str]
    _form: Callable[[Request, tuple[str, str]], Awaitable[Any]]

    def document_routes(self) -> list[tuple[str, list[str], Callable[..., Any]]]:
        return [
            ("/me/documents", ["GET"], self.documents_page),
            ("/me/documents/update", ["POST"], self.documents_update),
            ("/me/files", ["GET"], self.documents_moved), ("/inbox", ["GET"], self.documents_moved),  # 옛 올린 파일 화면
            ("/inbox/upload", ["POST"], self.upload_gone), ("/inbox/delete", ["POST"], self.upload_gone),
        ]

    async def documents_moved(self, request: Request) -> Response:
        if not self.user_of(request):
            return self._need_login(request)
        return RedirectResponse("/me/documents", status_code=302)

    async def upload_gone(self, request: Request) -> Response:
        """내 정보의 '올리기'·'지우기'는 없앴다(2026-10-10). 본문을 읽지 않고 안내와 함께 거절한다(예전 올린 파일은 그대로 둔다)."""
        session = self.user_of(request)
        if not session:
            return self._need_login(request)
        body = ('<p class="msg err">내 정보의 올리기는 없어졌습니다. 새 문서는 게시판 글에 첨부하고, 고친 문서는 '
                '내 정보 › 문서 업데이트에서 그 문서의 [업데이트]로 바꿉니다. 예전에 올린 파일은 그대로 있습니다.</p>'
                '<p><a href="/me/documents">문서 업데이트</a></p>')
        return self._page("문서 업데이트", body, session, 410, current="")

    async def documents_page(self, request: Request) -> Response:
        session = self.user_of(request)
        if not session:
            return self._need_login(request)
        q = " ".join((request.query_params.get("q") or "").split())[:100]
        return await self._documents(request, session, q)

    async def _documents(self, request: Request, session: tuple[str, str], q: str,
                         error: tuple[str, str, str] | None = None, status: int = 200) -> Response:
        uid = session[0]
        rows = await run_in_threadpool(list_documents, self.store, uid)
        shown = find_rows(rows, q)
        message = (f'<p class="msg err">{html.escape(error[1])}</p>' if error
                   else await run_in_threadpool(self._done_line, uid, request.query_params))
        from magus.webboard import search_line  # noqa: PLC0415

        used = await run_in_threadpool(self.store.usage_bytes, uid)
        search = ('<form method="get" action="/me/documents" class="search" role="search">'
                  f'<input type="search" name="q" value="{html.escape(q)}" aria-label="문서 찾기"><button>찾기</button></form>'
                  + (search_line(q, len(shown), "/me/documents") if q else ""))
        items = "".join(self._row_html(session, r, q, error) for r in shown)
        listing = (f'<ol class="docs">{items}</ol>' if items
                   else "" if q else '<p class="empty">올라간 문서가 없습니다.</p>')
        body = (f'<p class="crumb"><a href="/me">← 내 정보</a></p>{message}'
                f'<p class="usage">{mb(used)} / {mb(self.settings.max_user_bytes)}</p>{search}{listing}{SWAP_SCRIPT}')
        return self._page("문서 업데이트", body, session, status, current="", css=DOCS_STYLE)

    def _row_html(self, session: tuple[str, str], r: DocRow, q: str, error: tuple[str, str, str] | None) -> str:
        if r.is_inbox:
            where = "예전에 올린 파일"
        else:
            parts = [html.escape(x) for x in (r.project, r.node, r.book) if x]
            post = f'<a href="{html.escape(r.link)}">{html.escape(r.post or "글")}</a>' if r.link else html.escape(r.post or "")
            where = " › ".join([*parts, post])
        src = f'<p class="dr-src">{html.escape(r.source.label())}</p>' if r.source else ""
        mine = error is not None and error[0] == r.key
        accept = ",".join(MANUSCRIPT_TYPES if r.source else DOC_TYPES)
        form = (f'<details class="upd" data-swap{" open" if mine else ""}><summary class="btn quiet">업데이트</summary>'
                f'<form method="post" action="/me/documents/update" enctype="multipart/form-data">{self._csrf_input(session)}'
                f'<input type="hidden" name="key" value="{html.escape(r.key)}"><input type="hidden" name="q" value="{html.escape(q)}">'
                + swap_fields("file", "name", accept, dom_id=f"name-{hashlib.sha1(r.key.encode()).hexdigest()[:10]}",
                              force=mine and error is not None and error[2] == "overlap")
                + '<p><button class="primary">바꾸기</button></p></form></details>')
        return (f'<li data-key="{html.escape(r.key)}"><p class="dr-name">{html.escape(r.name)}'
                f'<small>{size_text(r.size)} · {local_time(r.at)}</small></p>'
                f'<p class="dr-where">{where}</p>{src}{form}</li>')

    def _done_line(self, uid: str, params: Any) -> str:
        done = params.get("done") or ""
        if done == "revised":
            said = revision_text(self.store, uid, params)
            return f'<p class="msg">{said.strip()}</p>' if said else ""
        if done == "restored":  # 휴지통에서 되살린 예전 올린 파일
            return f'<p class="msg">「{html.escape((params.get("f") or "")[:200])}」 파일을 되살렸습니다.</p>'
        if done == "updated":
            name = (params.get("f") or "")[:200]
            trash = params.get("tr") or ""
            trash_url = "/shelf/trash" if trash == "inbox" else f"/shelf/p/{trash}/trash" if _ID.fullmatch(trash) else ""
            return (f'<p class="msg">「{html.escape(name)}」로 바꿨습니다.' + (" 글 제목도 바꿨습니다." if params.get("t") == "1" else "")
                    + (f' 이전 파일은 <a href="{html.escape(trash_url)}">휴지통</a>에 있습니다.' if trash_url else "") + "</p>")
        return ""

    async def documents_update(self, request: Request) -> Response:
        session = self.user_of(request)
        if not session:
            return self._need_login(request)
        uid = session[0]
        try:
            form = await self._form(request, session)
        except PermissionError:
            return self._page("문서 업데이트", '<p class="msg err">잘못된 요청입니다.</p>', session, 403, current="")
        key = str(form.get("key") or "")
        q = " ".join(str(form.get("q") or "").split())[:100]
        item = form.get("file")
        if not isinstance(item, UploadFile) or not item.filename:
            return await self._documents(request, session, q, (key, "바꿀 새 파일을 골라 주세요.", "pick"), 400)
        size = item.size if item.size is not None else data_size(item.file)  # 읽지 않고 받은 크기로(점검 5-a)
        s = self.settings
        try:
            result = await run_in_threadpool(
                lambda: update_document(self.store, uid, key, item.filename or "", item.file, size, str(form.get("name") or ""),
                                        max_attach=s.max_attach_bytes, max_upload=s.max_upload_bytes, max_user=s.max_user_bytes,
                                        force=form.get("force") == "1"))
        except UpdateError as e:
            return await self._documents(request, session, q, (key, str(e), e.code), 400)
        except Exception as e:  # 예상 못 한 실패: 로그에는 종류·스택만, 화면에는 한국어 한 줄(500)
            log_failure("문서 업데이트", e)
            return await self._documents(request, session, q, (key, FAILED, "failed"), 500)
        back = [("q", q)] if q else []
        if result.revision is not None and result.project_id:
            query = [("done", "revised"), *urllib.parse.parse_qsl(revision_query(result)[1:]), *back]
        else:
            where = "inbox" if result.trash == "/shelf/trash" else result.trash.split("/")[3] if result.trash.count("/") >= 4 else ""
            query = [("done", "updated"), ("f", result.new_name), ("t", "1" if result.title_changed else "0"), ("tr", where), *back]
        return RedirectResponse("/me/documents?" + urllib.parse.urlencode(query), status_code=303)
