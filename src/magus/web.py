"""웹 페이지(P1 4단계): 로그인, 받은함, 원고, 인용 체크리스트 + 내려받기. MCP와 같은 프로세스의 Starlette 라우트다.

- 로그인
  - 원격: 인증 서버(WorkOS AuthKit)에 OAuth 인가 코드 + PKCE(S256)로 로그인한다. resource=PUBLIC_URL/mcp를 붙인다.
    받은 액세스 토큰은 MCP와 같은 JwtVerifier로 검증하고, 허용 목록의 user_id로 세션을 만든다.
  - 로컬(인증 없는 HTTP, 루프백 전용): USER_ID로 바로 로그인한다(개발용).
- 세션은 서명한 쿠키(HttpOnly, SameSite=Lax, https면 Secure, 12시간)이고, POST 폼은 CSRF 토큰을 확인한다.
- 내려받기 링크는 서명·만료(24시간)가 있다. 링크만으로는 받을 수 없고, 같은 사용자로 로그인해 있어야 한다.
- 디자인은 P1 범위가 아니다. 서버에서 그린 최소 HTML이다.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
import logging
import secrets
import urllib.parse
import urllib.request
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, RedirectResponse, Response

from magus.auth import JwtVerifier
from magus.book.export import export_docx
from magus.book.importer import import_manuscript
from magus.config import Settings
from magus.ids import local_time
from magus.inbox import INBOX_TYPES, LimitError, mb, save_upload, size_text
from magus.melchior.author_report import cite_label
from magus.melchior.report import build_cite_report
from magus.signing import sign, unsign
from magus.store import Store

log = logging.getLogger("magus.web")
SESSION_COOKIE, OAUTH_COOKIE = "magus_session", "magus_oauth"
SESSION_TTL, OAUTH_TTL, DOWNLOAD_TTL = 12 * 3600, 600, 24 * 3600
LIGHTS = {"verified": ("🟢", "확인"), "unverified": ("🟡", "미확인"), "unknown": ("🔴", "참고문헌에 없음"),
          "uncertain": ("⚪", "미연결")}


class OAuthClient:
    """웹 로그인용 OAuth 클라이언트(인증 서버에 등록한 client_id). 메타데이터는 issuer의 .well-known에서 찾는다."""

    def __init__(self, issuer: str, client_id: str, client_secret: str | None, redirect_uri: str, resource: str):
        self.issuer, self.client_id, self.client_secret = issuer.rstrip("/"), client_id, client_secret
        self.redirect_uri, self.resource = redirect_uri, resource
        self._meta: dict[str, Any] | None = None

    def metadata(self) -> dict[str, Any]:
        if self._meta is None:
            for path in ("/.well-known/oauth-authorization-server", "/.well-known/openid-configuration"):
                try:
                    with urllib.request.urlopen(self.issuer + path, timeout=10) as r:  # noqa: S310 - 설정한 issuer만
                        meta = json.load(r)
                    if meta.get("authorization_endpoint") and meta.get("token_endpoint"):
                        self._meta = meta
                        break
                except (OSError, ValueError):
                    continue
            else:
                raise RuntimeError("인증 서버 메타데이터(authorization_endpoint, token_endpoint)를 찾지 못했다")
        return self._meta

    def authorize_url(self, state: str, challenge: str) -> str:
        query = urllib.parse.urlencode({
            "response_type": "code", "client_id": self.client_id, "redirect_uri": self.redirect_uri,
            "scope": "openid profile email", "state": state, "code_challenge": challenge,
            "code_challenge_method": "S256", "resource": self.resource,
        })
        return f"{self.metadata()['authorization_endpoint']}?{query}"

    def exchange(self, code: str, verifier: str) -> str:
        form = {"grant_type": "authorization_code", "code": code, "redirect_uri": self.redirect_uri,
                "client_id": self.client_id, "code_verifier": verifier, "resource": self.resource}
        if self.client_secret:
            form["client_secret"] = self.client_secret
        request = urllib.request.Request(
            self.metadata()["token_endpoint"], urllib.parse.urlencode(form).encode(),
            {"content-type": "application/x-www-form-urlencoded", "accept": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=15) as r:  # noqa: S310
            token = json.load(r).get("access_token")
        if not token:
            raise RuntimeError("토큰 응답에 access_token이 없다")
        return str(token)


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


@dataclass
class Web:
    store: Store
    settings: Settings
    base_url: str  # 바깥에서 보이는 주소(원격: PUBLIC_URL, 로컬: http://127.0.0.1:포트)
    secret: bytes
    verifier: JwtVerifier | None = None
    oauth: OAuthClient | None = None
    local_user: str | None = None  # 로컬(인증 없는 HTTP) 개발용 자동 로그인
    _allowed: set[str] = field(default_factory=set)

    @classmethod
    def create(cls, store: Store, settings: Settings, base_url: str, verifier: JwtVerifier | None) -> Web:
        auth = settings.auth
        if auth is None:
            secret = (settings.session_secret or secrets.token_hex(32)).encode()
            return cls(store, settings, base_url.rstrip("/"), secret, local_user=settings.user_id)
        if not settings.session_secret or len(settings.session_secret) < 32:
            raise ValueError("원격 모드에는 SESSION_SECRET(32자 이상 무작위 문자열)이 필요하다")
        oauth = (
            OAuthClient(auth.issuer, settings.web_client_id, settings.web_client_secret,
                        f"{auth.public_url}/auth/callback", auth.resource)
            if settings.web_client_id else None
        )
        return cls(store, settings, auth.public_url, settings.session_secret.encode(), verifier, oauth,
                   _allowed=set(auth.allowed.values()))

    # --- 세션 ---
    def user_of(self, request: Request) -> tuple[str, str] | None:
        """(user_id, sid). 세션이 없거나, 허용 목록에서 빠진 사용자면 None."""
        data = unsign(request.cookies.get(SESSION_COOKIE, ""), self.secret, "session")
        if not data:
            return None
        uid = str(data.get("uid", ""))
        if self.local_user is not None:
            return (uid, str(data.get("sid"))) if uid == self.local_user else None
        return (uid, str(data.get("sid"))) if uid in self._allowed else None

    def csrf(self, sid: str) -> str:
        return hmac.new(self.secret, f"csrf.{sid}".encode(), hashlib.sha256).hexdigest()[:32]

    def _cookie(self, response: Response, name: str, value: str, ttl: int) -> None:
        response.set_cookie(name, value, max_age=ttl, httponly=True, samesite="lax",
                            secure=self.base_url.startswith("https://"), path="/")

    def export_link(self, user_id: str, location: str) -> str:
        """book_export 결과(로컬 경로) → 서명·만료가 있는 내려받기 URL. 로그인한 같은 사용자만 받는다."""
        path = Path(location)
        token = sign({"u": user_id, "p": path.parent.parent.name, "f": path.name}, self.secret, "download", DOWNLOAD_TTL)
        return f"{self.base_url}/download/{token}"

    # --- 라우트 등록 ---
    def register(self, server: MCPServer) -> None:
        routes: list[tuple[str, list[str], Callable[[Request], Awaitable[Response]]]] = [
            ("/", ["GET"], self.home), ("/login", ["GET"], self.login), ("/auth/callback", ["GET"], self.callback),
            ("/logout", ["POST"], self.logout), ("/inbox", ["GET"], self.inbox), ("/inbox/upload", ["POST"], self.upload),
            ("/inbox/delete", ["POST"], self.delete), ("/book", ["GET"], self.book), ("/book/import", ["POST"], self.do_import),
            ("/book/export", ["POST"], self.do_export), ("/download/{token}", ["GET"], self.download),
            ("/checklist", ["GET"], self.checklist),
        ]
        for path, methods, handler in routes:
            server.custom_route(path, methods=methods, include_in_schema=False)(handler)

    # --- 공통 ---
    def _page(self, title: str, body: str, session: tuple[str, str] | None = None, status: int = 200) -> HTMLResponse:
        nav = ""
        if session:
            nav = (f'<nav><a href="/book">원고</a> · <a href="/inbox">받은함</a> · <a href="/checklist">인용 체크리스트</a>'
                   f' · <span>{html.escape(session[0])}</span>'
                   f' <form method="post" action="/logout" class="inline">{self._csrf_input(session)}<button>로그아웃</button></form></nav>')
        return HTMLResponse(
            f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)} · Magus</title><style>
body{{font-family:system-ui,"Malgun Gothic",sans-serif;max-width:60rem;margin:1rem auto;padding:0 1rem;line-height:1.5}}
table{{border-collapse:collapse;width:100%}}td,th{{border-bottom:1px solid #ddd;padding:.3rem .4rem;text-align:left;vertical-align:top}}
.inline{{display:inline}}.msg{{background:#f4f4f4;padding:.6rem;white-space:pre-wrap}}.err{{background:#fde8e8}}nav{{margin-bottom:1rem}}
</style></head><body>{nav}<h1>{html.escape(title)}</h1>{body}</body></html>""",
            status_code=status,
        )

    def _csrf_input(self, session: tuple[str, str]) -> str:
        return f'<input type="hidden" name="csrf" value="{self.csrf(session[1])}">'

    async def _form(self, request: Request, session: tuple[str, str]) -> Any:
        form = await request.form(max_files=20, max_fields=20)
        if not hmac.compare_digest(str(form.get("csrf", "")).encode(), self.csrf(session[1]).encode()):
            raise PermissionError("CSRF")
        return form

    def _need_login(self, request: Request) -> Response:
        return RedirectResponse(f"/login?next={urllib.parse.quote(request.url.path)}", status_code=303)

    # --- 로그인 ---
    async def home(self, request: Request) -> Response:
        return RedirectResponse("/book" if self.user_of(request) else "/login", status_code=303)

    async def login(self, request: Request) -> Response:
        nxt = request.query_params.get("next", "/book")
        nxt = nxt if nxt.startswith("/") and not nxt.startswith("//") else "/book"
        if self.local_user is not None:  # 로컬 개발: 바로 로그인
            response = RedirectResponse(nxt, status_code=303)
            self._cookie(response, SESSION_COOKIE,
                         sign({"uid": self.local_user, "sid": secrets.token_hex(8)}, self.secret, "session", SESSION_TTL),
                         SESSION_TTL)
            return response
        if self.oauth is None:
            return self._page("로그인", '<p class="msg err">웹 로그인이 설정되지 않았습니다(WEB_CLIENT_ID). 운영자에게 문의하세요.</p>',
                              status=503)
        state, (verifier, challenge) = secrets.token_urlsafe(24), _pkce()
        try:
            target = await run_in_threadpool(self.oauth.authorize_url, state, challenge)
        except RuntimeError as e:
            return self._page("로그인", f'<p class="msg err">{html.escape(str(e))}</p>', status=502)
        response = RedirectResponse(target, status_code=303)
        self._cookie(response, OAUTH_COOKIE, sign({"s": state, "v": verifier, "n": nxt}, self.secret, "oauth", OAUTH_TTL),
                     OAUTH_TTL)
        return response

    async def callback(self, request: Request) -> Response:
        pending = unsign(request.cookies.get(OAUTH_COOKIE, ""), self.secret, "oauth")
        code, state = request.query_params.get("code"), request.query_params.get("state")
        if not pending or not code or not state or not hmac.compare_digest(str(pending.get("s")).encode(), state.encode()):
            return self._page("로그인", '<p class="msg err">로그인 요청이 만료됐거나 맞지 않습니다. <a href="/login">다시 로그인</a></p>',
                              status=400)
        assert self.oauth is not None and self.verifier is not None
        try:
            token = await run_in_threadpool(self.oauth.exchange, code, str(pending["v"]))
        except (OSError, ValueError, RuntimeError) as e:
            log.warning("web login: token exchange failed (%s)", type(e).__name__)
            return self._page("로그인", '<p class="msg err">로그인에 실패했습니다. <a href="/login">다시 로그인</a></p>', status=502)
        claims = await run_in_threadpool(self.verifier.decode, token)
        uid = self.verifier.user_of(claims) if claims else None
        if uid is None:
            status = 403 if claims else 401
            return self._page("로그인", '<p class="msg err">허용 목록에 없는 사용자입니다. 운영자에게 문의하세요.</p>', status=status)
        response = RedirectResponse(str(pending.get("n") or "/book"), status_code=303)
        self._cookie(response, SESSION_COOKIE, sign({"uid": uid, "sid": secrets.token_hex(8)}, self.secret, "session",
                                                    SESSION_TTL), SESSION_TTL)
        response.delete_cookie(OAUTH_COOKIE, path="/")
        log.info("web login user=%s", uid)
        return response

    async def logout(self, request: Request) -> Response:
        session = self.user_of(request)
        if session:
            try:
                await self._form(request, session)
            except PermissionError:
                return self._page("로그아웃", '<p class="msg err">잘못된 요청입니다.</p>', status=403)
        response = self._page("로그아웃", '<p>로그아웃했습니다. <a href="/login">다시 로그인</a></p>')
        response.delete_cookie(SESSION_COOKIE, path="/")
        return response

    # --- 받은함 ---
    async def inbox(self, request: Request, flash: str = "", error: bool = False) -> Response:
        session = self.user_of(request)
        if not session:
            return self._need_login(request)
        uid = session[0]
        files = self.store.list_inbox(uid)
        rows = "".join(
            f"<tr><td>{html.escape(f.name)}</td><td>{size_text(f.size)}</td><td>{local_time(f.modified)}</td>"
            f"<td>{html.escape(INBOX_TYPES.get(Path(f.name).suffix.lower(), ''))}</td>"
            f'<td><form method="post" action="/inbox/delete" class="inline">{self._csrf_input(session)}'
            f'<input type="hidden" name="name" value="{html.escape(f.name)}"><button>지우기</button></form></td></tr>'
            for f in files
        ) or '<tr><td colspan="5">비어 있습니다.</td></tr>'
        message = f'<p class="msg{" err" if error else ""}">{html.escape(flash)}</p>' if flash else ""
        body = f"""{message}
<p>사용 {mb(self.store.usage_bytes(uid))} / 한도 {mb(self.settings.max_user_bytes)} · 파일 한 개 한도 {mb(self.settings.max_upload_bytes)}</p>
<form method="post" action="/inbox/upload" enctype="multipart/form-data">{self._csrf_input(session)}
<input type="file" name="files" multiple accept=".docx,.pdf,.md,.txt"> <button>올리기</button></form>
<table><tr><th>이름</th><th>크기</th><th>올린 시각</th><th>쓰임</th><th></th></tr>{rows}</table>
<p>Claude에서는 파일 이름으로 가리킵니다. 예: "받은함의 kremer1993.pdf를 문헌으로 등록해 줘. 쓸 부분은 「…」, 이유는 …"</p>"""
        return self._page("받은함", body, session)

    async def upload(self, request: Request) -> Response:
        session = self.user_of(request)
        if not session:
            return self._need_login(request)
        limit = self.settings.max_upload_bytes * 20 + 1_000_000
        if int(request.headers.get("content-length") or 0) > limit:  # 다 받기 전에 거른다
            return self._page("받은함", f'<p class="msg err">요청이 너무 큽니다(한도 {mb(limit)}).</p>', session, 413)
        try:
            form = await self._form(request, session)
        except PermissionError:
            return self._page("받은함", '<p class="msg err">잘못된 요청입니다.</p>', session, 403)
        saved, errors = [], []
        for item in form.getlist("files"):
            if not isinstance(item, UploadFile) or not item.filename:
                continue
            data = await item.read()
            try:
                saved.append(save_upload(self.store, session[0], item.filename, data,
                                         self.settings.max_upload_bytes, self.settings.max_user_bytes).name)
            except (LimitError, ValueError) as e:
                errors.append(f"{item.filename}: {e}")
        flash = "\n".join([*(f"올림: {n}" for n in saved), *errors]) or "올릴 파일을 고르세요."
        return await self.inbox(request, flash, bool(errors))

    async def delete(self, request: Request) -> Response:
        session = self.user_of(request)
        if not session:
            return self._need_login(request)
        try:
            form = await self._form(request, session)
            name = str(form.get("name", ""))
            ok = self.store.delete_inbox(session[0], name)
        except (PermissionError, ValueError):
            return self._page("받은함", '<p class="msg err">잘못된 요청입니다.</p>', session, 403)
        return await self.inbox(request, f"지움: {name}" if ok else f"없음: {name}", not ok)

    # --- 원고 ---
    async def book(self, request: Request, flash: str = "", error: bool = False) -> Response:
        session = self.user_of(request)
        if not session:
            return self._need_login(request)
        uid = session[0]
        projects = self.store.list_projects(uid)
        rows = "".join(
            f"<tr><td>{html.escape(p.title)}</td><td>{html.escape(p.id)}</td>"
            f"<td>{len(self.store.list_chapters(uid, p.id))}</td><td>{local_time(p.updated_at)}</td>"
            f'<td><form method="post" action="/book/export" class="inline">{self._csrf_input(session)}'
            f'<input type="hidden" name="project_id" value="{html.escape(p.id)}"><button>docx 내보내기</button></form> '
            f'<a href="/checklist?project={urllib.parse.quote(p.id)}">인용 체크리스트</a></td></tr>'
            for p in projects
        ) or '<tr><td colspan="5">아직 원고가 없습니다. 받은함에 docx(또는 pdf)를 올리고 아래에서 임포트하세요.</td></tr>'
        options = "".join(
            f'<option value="{html.escape(f.name)}">{html.escape(f.name)}</option>'
            for f in self.store.list_inbox(uid) if Path(f.name).suffix.lower() in (".docx", ".pdf")
        )
        message = f'<div class="msg{" err" if error else ""}">{html.escape(flash)}</div>' if flash else ""
        body = f"""{message}
<table><tr><th>제목</th><th>id</th><th>장</th><th>갱신</th><th></th></tr>{rows}</table>
<h2>임포트</h2>
<form method="post" action="/book/import">{self._csrf_input(session)}
<p><label>받은함 원고 <select name="name">{options or '<option value="">(받은함에 docx·pdf 없음)</option>'}</select></label></p>
<p><label>프로젝트 id <input name="project_id" value="book" pattern="[A-Za-z0-9_-]+" required></label>
<label>제목 <input name="title" placeholder="비우면 파일에서"></label>
<label><input type="checkbox" name="replace" value="1"> 같은 id가 있으면 바꾸기(기존 것은 휴지통으로)</label></p>
<p><button>임포트</button> (큰 원고는 몇십 초 걸립니다)</p></form>"""
        return self._page("원고", body, session)

    async def do_import(self, request: Request) -> Response:
        session = self.user_of(request)
        if not session:
            return self._need_login(request)
        try:
            form = await self._form(request, session)
        except PermissionError:
            return self._page("원고", '<p class="msg err">잘못된 요청입니다.</p>', session, 403)
        uid, name = session[0], str(form.get("name", ""))
        try:
            path = self.store.inbox_path(uid, name) if name else None
            if path is None:
                raise FileNotFoundError(f"받은함에 {name!r}이 없다")
            report = await run_in_threadpool(
                import_manuscript, self.store, uid, path,
                project_id=str(form.get("project_id") or "") or None, title=str(form.get("title") or "") or None,
                replace=form.get("replace") == "1",
            )
        except (ValueError, FileNotFoundError) as e:
            return await self.book(request, str(e), True)
        return await self.book(request, report.summary())

    async def do_export(self, request: Request) -> Response:
        session = self.user_of(request)
        if not session:
            return self._need_login(request)
        try:
            form = await self._form(request, session)
        except PermissionError:
            return self._page("원고", '<p class="msg err">잘못된 요청입니다.</p>', session, 403)
        project = self.store.get_project(session[0], str(form.get("project_id", "")))
        if project is None:
            return await self.book(request, "프로젝트가 없습니다.", True)
        location = await run_in_threadpool(export_docx, self.store, session[0], project)
        return RedirectResponse(self.export_link(session[0], location).removeprefix(self.base_url), status_code=303)

    async def download(self, request: Request) -> Response:
        data = unsign(request.path_params["token"], self.secret, "download")
        if not data:
            return self._page("내려받기", '<p class="msg err">링크가 만료됐거나 잘못됐습니다. 다시 내보내세요.</p>', status=410)
        session = self.user_of(request)
        if not session:
            return self._need_login(request)
        if session[0] != data.get("u"):
            return self._page("내려받기", '<p class="msg err">다른 사용자의 파일입니다.</p>', session, 403)
        path = self.store.export_path(session[0], str(data.get("p")), str(data.get("f")))
        if path is None:
            return self._page("내려받기", '<p class="msg err">파일이 없습니다. 다시 내보내세요.</p>', session, 404)
        return FileResponse(path, filename=path.name,
                            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")

    # --- 인용 체크리스트 ---
    async def checklist(self, request: Request) -> Response:
        session = self.user_of(request)
        if not session:
            return self._need_login(request)
        uid = session[0]
        project = self.store.get_project(uid, request.query_params.get("project") or None)
        if project is None:
            return self._page("인용 체크리스트", "<p>원고가 없습니다. <a href=\"/book\">원고</a>에서 임포트하세요.</p>", session)
        report = await run_in_threadpool(build_cite_report, self.store, uid, project.id)
        refs = {r.key: r for r in self.store.list_refs(uid)}
        status = request.query_params.get("status") or ""
        docs = [d for d in report.docs.values() if not status or d.status == status]
        order = {"unknown": 0, "unverified": 1, "uncertain": 2, "verified": 3}
        docs.sort(key=lambda d: (order[d.status], -d.count, d.key))
        counts = {s: len(report.of(s)) for s in LIGHTS}
        filters = " · ".join(
            f'<a href="?project={urllib.parse.quote(project.id)}&status={s}">{LIGHTS[s][0]} {LIGHTS[s][1]} {counts[s]}</a>'
            for s in LIGHTS
        )
        doc_rows = "".join(
            f"<tr><td>{LIGHTS[d.status][0]} {LIGHTS[d.status][1]}</td>"
            f"<td>{html.escape(cite_label(refs.get(d.key), d.key))}"
            + (f"<br><small>후보: {html.escape(' / '.join(d.candidates))}</small>" if d.candidates else "")
            + f"</td><td>{d.count}</td><td>{html.escape(', '.join(d.chapters))}</td></tr>"
            for d in docs
        )
        chapter_rows = "".join(
            f"<tr><td>{html.escape(disp)}</td><td>{html.escape(title)}</td><td>{unique}</td><td>{occ}</td></tr>"
            for disp, title, unique, occ, _ in report.per_chapter
        )
        body = f"""<p>『{html.escape(project.title)}』 · 문헌 {len(report.docs) - counts['uncertain']}편
(확인 {counts['verified']} · 미확인 {counts['unverified']} · 참고문헌에 없음 {counts['unknown']}) · 미연결 {counts['uncertain']}
· <a href="?project={urllib.parse.quote(project.id)}">전체</a></p>
<p>{filters}</p>
<table><tr><th>상태</th><th>문헌</th><th>인용</th><th>장</th></tr>{doc_rows or '<tr><td colspan="4">없음</td></tr>'}</table>
<h2>장별</h2><table><tr><th>장</th><th>제목</th><th>미확인 문헌</th><th>인용 출현</th></tr>{chapter_rows}</table>"""
        return self._page("인용 체크리스트", body, session)
