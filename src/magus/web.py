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
from magus.book.outline import chapter_count
from magus.book.reupload import reupload_manuscript
from magus.config import Settings
from magus.ids import local_time
from magus.inbox import INBOX_TYPES, LimitError, mb, save_upload, size_text
from magus.melchior.author_report import chapters_text, cite_label
from magus.melchior.report import build_cite_report
from magus.signing import sign, unsign
from magus.store import Store
from magus.store.base import STALE_REASONS

log = logging.getLogger("magus.web")
SESSION_COOKIE, OAUTH_COOKIE = "magus_session", "magus_oauth"
SESSION_TTL, OAUTH_TTL, DOWNLOAD_TTL = 12 * 3600, 600, 24 * 3600
LIGHTS = {"verified": ("🟢", "확인"), "unverified": ("🟡", "미확인"), "unknown": ("🔴", "참고문헌에 없음"),
          "uncertain": ("⚪", "미연결")}
ISSUE_KIND_NAMES = {"citation": "문헌 확인", "fact": "사실·수치 확인", "general": "기타"}
NAV = (("/book", "원고"), ("/inbox", "받은함"), ("/checklist", "인용 체크리스트"), ("/issues", "확인 요청"),
       ("/ideas", "생각"), ("/refs", "문헌"), ("/styles", "문체"))
PAGE_SIZE = 100  # 세 책장 목록의 한 쪽
TAGS_BY = {"ai": "AI가 뽑은 태그", "author": "저자가 정한 태그"}
SAY = "Claude에게 이렇게 말하면 쌓입니다. 예: "  # 빈 책장 안내(받은함 예문과 같은 방식)

# 화면 스타일은 여기 한 곳(결정 #56: 템플릿 엔진·외부 글꼴·CDN 없음). 토큰과 참고 문서에서 바꾼 점은 docs/decisions/web-style.md.
# 입력칸 테두리는 --mute(흰 바탕 4.75:1)다. 참고 문서의 입력칸 색(1.82:1)은 칸이 보이지 않아 쓰지 않는다(사용자 결정 #86).
# 주 사용자가 고령이라 가독성을 앞세웠다: 본문 16px·줄간격 1.6, 가는 글씨(300) 없음, 버튼·입력칸 최소 40px(좁은 화면 44px).
# 대비(WCAG AA 4.5:1): ink-mute(#64748d)는 흰 바탕에서만(4.75, 회색 바탕은 4.49) 쓴다. 태그 바탕은 #b9b9f9를 40%로 흰 바탕에
# 얹어(#4434d4 글자 6.2:1) 쓴다. ruby(#ea2261)는 흰 바탕 글자로 4.29라 오류 글자에 쓰지 않고 왼쪽 테두리에만 쓴다.
STYLE = """
:root{--ink:#0d253d;--ink2:#273951;--mute:#64748d;--primary:#533afd;--press:#2e2b8c;--deep:#4434d4;--canvas:#ffffff;
--soft:#f6f9fc;--line:#e3e8ee;--ruby:#ea2261;--tag:rgb(185 185 249/40%);--shadow:rgba(0,55,112,.08) 0 1px 3px}
*{box-sizing:border-box}
body{margin:0;background:var(--soft);color:var(--ink);font:400 16px/1.6 -apple-system,"Apple SD Gothic Neo","Malgun Gothic","Noto Sans KR",system-ui,sans-serif;
word-break:keep-all;overflow-wrap:break-word}
main{max-width:1100px;margin:0 auto;padding:24px 16px 32px}
h1,h2,h3{font-weight:600;letter-spacing:-.2px;line-height:1.3;margin:24px 0 12px}
h1{font-size:26px;margin-top:8px}h2{font-size:20px}h3{font-size:18px}
p{margin:12px 0}a{color:var(--primary)}a:hover{color:var(--press)}small{color:var(--ink2)}
.site{background:var(--canvas);border-bottom:1px solid var(--line)}
.site-in{max-width:1100px;margin:0 auto;padding:8px 16px;display:flex;flex-wrap:wrap;align-items:center;gap:8px 24px}
.brand{font-weight:600;font-size:18px;letter-spacing:-.2px;color:var(--ink);margin-right:auto}
.site nav{display:flex;flex-wrap:wrap;align-items:center;gap:4px 16px}
.site nav a{color:var(--ink2);text-decoration:none;padding:8px 0;border-bottom:2px solid transparent}
.site nav a:hover{color:var(--primary)}
.site nav a[aria-current=page]{color:var(--primary);border-bottom-color:var(--primary)}
.site nav span{color:var(--mute)}
.table-wrap,.card,.msg{background:var(--canvas);border:1px solid var(--line);border-radius:12px;box-shadow:var(--shadow)}
.table-wrap{overflow-x:auto;margin:16px 0}
.card{padding:16px 24px;margin:16px 0}
table{border-collapse:collapse;width:100%}
th,td{padding:8px 12px;text-align:left;vertical-align:top;border-bottom:1px solid var(--line)}
tr:last-child td{border-bottom:0}
th{color:var(--mute);font-size:13px;font-weight:600;white-space:nowrap}
td small{color:var(--mute)}
.pager{color:var(--ink2)}a.tag{text-decoration:none;margin:2px 0}a.tag:hover{color:var(--press)}
.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.msg{padding:12px 16px;margin:16px 0;white-space:pre-wrap}
.err{border-left:4px solid var(--ruby)}
.tag{display:inline-block;background:var(--tag);color:var(--deep);border-radius:9999px;padding:2px 10px;white-space:nowrap}
button,input[type=file]::file-selector-button{font:inherit;font-size:16px;line-height:1.2;min-height:40px;padding:8px 16px;
border-radius:9999px;border:1px solid var(--primary);background:var(--canvas);color:var(--primary);cursor:pointer}
button:hover,input[type=file]::file-selector-button:hover{background:var(--soft)}
button.primary{background:var(--primary);color:#ffffff}
button.primary:hover{background:var(--deep)}button.primary:active{background:var(--press)}
button:disabled{opacity:.5;cursor:default}
input[type=file]{font:inherit;color:var(--ink2);max-width:100%}
input[type=file]::file-selector-button{margin-right:12px}
input:not([type=radio]):not([type=checkbox]):not([type=file]):not([type=hidden]),select{font:inherit;color:var(--ink);background:var(--canvas);
border:1px solid var(--mute);border-radius:6px;padding:8px 12px;min-height:40px;max-width:100%}
input[type=radio],input[type=checkbox]{accent-color:var(--primary);width:18px;height:18px;vertical-align:-3px}
input:focus,select:focus{border-color:var(--primary)}
:focus-visible{outline:3px solid var(--primary);outline-offset:2px}
input[type=file]:focus-visible::file-selector-button{outline:3px solid var(--primary);outline-offset:2px}
label{display:inline-block;margin:4px 16px 4px 0;max-width:100%}select{width:auto}
label.off{color:var(--mute)}
details{margin:12px 0}summary{cursor:pointer;color:var(--ink2);padding:4px 0}
form.inline{display:inline}
form.busy{pointer-events:none}
form.busy button::after{content:"";display:inline-block;width:14px;height:14px;margin-left:8px;vertical-align:-2px;
border:2px solid currentColor;border-right-color:transparent;border-radius:50%;animation:spin .8s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
@media (max-width:767px){main{padding:16px 12px 24px}h1{font-size:22px}table{min-width:640px}
button,input[type=file]::file-selector-button,input:not([type=radio]):not([type=checkbox]):not([type=hidden]),select{min-height:44px}}
"""
# 받은함: 파일을 고르면 바로 올린다(자바스크립트가 꺼져 있으면 '올리기' 버튼으로). 올리는 동안 버튼 옆에 도는 표시가 보인다.
UPLOAD_SCRIPT = """<script>
document.querySelectorAll("form.upload input[type=file]").forEach(function (input) {
  // 파일을 고르면 바로 올린다
  input.addEventListener("change", function () {
    if (!input.files.length) return;
    var form = input.form;
    form.classList.add("busy");
    form.setAttribute("aria-busy", "true");
    form.submit();
  });
});
</script>"""


def _fold(text: str, limit: int = 300) -> str:
    """긴 글은 앞부분만 보이고 나머지는 '더 보기'로 접는다. 줄바꿈은 살린다."""
    def shown(part: str) -> str:
        return html.escape(part).replace("\n", "<br>")

    if len(text) <= limit:
        return shown(text)
    return f"{shown(text[:limit])}…<details><summary>더 보기</summary>{shown(text)}</details>"


def _paged(items: list, request: Request) -> tuple[list, str]:
    """PAGE_SIZE개씩. 쪽 이동 줄(넘칠 때만)은 목록 위아래에 같은 것을 둔다. 다른 거르기 조건은 그대로 이어 간다."""
    try:
        page = max(1, int(request.query_params.get("page") or 1))
    except ValueError:
        page = 1
    pages = max(1, -(-len(items) // PAGE_SIZE))
    page = min(page, pages)
    start = (page - 1) * PAGE_SIZE
    if pages == 1:
        return items, ""
    keep = [(k, v) for k, v in request.query_params.multi_items() if k != "page"]

    def link(n: int, label: str) -> str:
        return f'<a href="?{html.escape(urllib.parse.urlencode([*keep, ("page", n)]))}">{label}</a>'

    nav = [f"{start + 1}–{min(start + PAGE_SIZE, len(items))} / {len(items)}"]
    nav += [link(page - 1, "이전")] if page > 1 else []
    nav += [link(page + 1, "다음")] if page < pages else []
    return items[start : start + PAGE_SIZE], f'<p class="pager">{" · ".join(nav)}</p>'


def _style_tags(entry) -> list[str]:
    """문체 태그 값들(호흡·시점·열기·어미·톤과 장치 목록)."""
    out: list[str] = []
    for value in entry.tags.values():
        out += [str(v) for v in value] if isinstance(value, list) else [str(value)] if value else []
    return list(dict.fromkeys(v for v in out if v.strip()))


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
            ("/checklist", ["GET"], self.checklist), ("/issues", ["GET"], self.issues),
            ("/ideas", ["GET"], self.ideas), ("/refs", ["GET"], self.refs), ("/styles", ["GET"], self.styles),
        ]
        for path, methods, handler in routes:
            server.custom_route(path, methods=methods, include_in_schema=False)(handler)

    # --- 공통 ---
    def _page(self, title: str, body: str, session: tuple[str, str] | None = None, status: int = 200) -> HTMLResponse:
        nav = ""
        if session:  # 지금 보고 있는 메뉴(제목이 메뉴 이름과 같은 화면)는 aria-current로 표시한다
            links = "".join(
                f'<a href="{href}"{" aria-current=page" if label == title else ""}>{label}</a>' for href, label in NAV
            )
            nav = (f'<nav>{links}<span>{html.escape(session[0])}</span>'
                   f'<form method="post" action="/logout" class="inline">{self._csrf_input(session)}<button>로그아웃</button></form></nav>')
        body = body.replace("<table>", '<div class="table-wrap"><table>').replace("</table>", "</table></div>")
        return HTMLResponse(
            f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)} · Magus</title><style>{STYLE}</style></head><body>
<header class="site"><div class="site-in"><span class="brand">Magus</span>{nav}</div></header>
<main><h1>{html.escape(title)}</h1>{body}</main></body></html>""",
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
        claims, reason = await run_in_threadpool(self.verifier.check, token)
        if claims is None:  # 토큰을 받아들이지 못함(서버 설정 문제일 가능성이 크다). 원인은 서버 로그에만
            log.warning("web login: token rejected (%s)", reason)
            return self._page(
                "로그인",
                '<p class="msg err">로그인은 됐지만 Magus가 로그인 토큰을 받아들이지 못했습니다(401). '
                "서버 설정 문제일 수 있습니다. 운영자에게 알려 주세요. 원인은 서버 로그에 있습니다.</p>"
                '<p><a href="/login">다시 로그인</a></p>',
                status=401,
            )
        uid = self.verifier.user_of(claims)
        if uid is None:  # 토큰은 유효하지만 허용 목록 밖. 본인의 사용자 id를 보여 준다(운영자가 목록에 넣을 값)
            sub = str(claims.get("sub", ""))
            log.warning("web login: not allowed sub_hash=%s", hashlib.sha256(sub.encode()).hexdigest()[:10])
            return self._page(
                "로그인",
                '<p class="msg err">로그인은 됐지만 이 계정은 Magus 허용 목록에 없습니다(403).</p>'
                f"<p>운영자에게 아래 사용자 id를 알려 주세요.</p><p><code>{html.escape(sub)}</code></p>",
                status=403,
            )
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
            f'<tr><td>{html.escape(f.name)}</td><td class="num">{size_text(f.size)}</td><td class="num">{local_time(f.modified)}</td>'
            f"<td>{html.escape(INBOX_TYPES.get(Path(f.name).suffix.lower(), ''))}</td>"
            f'<td><form method="post" action="/inbox/delete" class="inline">{self._csrf_input(session)}'
            f'<input type="hidden" name="name" value="{html.escape(f.name)}"><button>지우기</button></form></td></tr>'
            for f in files
        ) or '<tr><td colspan="5">비어 있습니다.</td></tr>'
        message = f'<p class="msg{" err" if error else ""}">{html.escape(flash)}</p>' if flash else ""
        body = f"""{message}
<p>사용 {mb(self.store.usage_bytes(uid))} / 한도 {mb(self.settings.max_user_bytes)} · 파일 한 개 한도 {mb(self.settings.max_upload_bytes)}</p>
<form method="post" action="/inbox/upload" enctype="multipart/form-data" class="card upload">{self._csrf_input(session)}
<input type="file" name="files" multiple accept=".docx,.pdf,.md,.txt"> <button class="primary">올리기</button></form>
<table><tr><th>이름</th><th class="num">크기</th><th class="num">올린 시각</th><th>쓰임</th><th></th></tr>{rows}</table>
<p>Claude에서는 파일 이름으로 가리킵니다. 예: "받은함의 kremer1993.pdf를 문헌으로 등록해 줘. 쓸 부분은 「…」, 이유는 …"</p>
{UPLOAD_SCRIPT}"""
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

        def edition_of(project_id: str) -> str:
            editions = self.store.list_editions(uid, project_id)
            return f"E{editions[-1].number} · {local_time(editions[-1].uploaded_at)}" if editions else "-"

        def issue_counts(project_id: str) -> str:
            issues = self.store.list_issues(uid, project_id, "open")
            ai = sum(1 for i in issues if i.by_ai)
            return f"{len(issues)}" + (f" (🤖 AI 확인 요청 {ai})" if ai else "")

        rows = "".join(
            f"<tr><td>{html.escape(p.title)}" + (f"<br><small>{html.escape(p.subtitle)}</small>" if p.subtitle else "")
            + f"</td><td>{html.escape(p.id)}</td>"
            f"<td>{html.escape(chapter_count(self.store.list_chapters(uid, p.id)))}</td>"
            f'<td class="num"><a href="/issues?project={urllib.parse.quote(p.id)}">{issue_counts(p.id)}</a></td>'
            f'<td class="num">{edition_of(p.id)}</td><td class="num">{local_time(p.updated_at)}</td>'
            f'<td><form method="post" action="/book/export" class="inline">{self._csrf_input(session)}'
            f'<input type="hidden" name="project_id" value="{html.escape(p.id)}"><button>docx 내보내기</button></form> '
            f'<a href="/checklist?project={urllib.parse.quote(p.id)}">인용 체크리스트</a></td></tr>'
            for p in projects
        ) or '<tr><td colspan="7">아직 원고가 없습니다. 받은함에 docx(또는 pdf)를 올리고 아래에서 임포트하세요.</td></tr>'
        options = "".join(
            f'<option value="{html.escape(f.name)}">{html.escape(f.name)}</option>'
            for f in self.store.list_inbox(uid) if Path(f.name).suffix.lower() in (".docx", ".pdf")
        )
        message = f'<div class="msg{" err" if error else ""}">{html.escape(flash)}</div>' if flash else ""
        body = f"""{message}
<table><tr><th>제목</th><th>id</th><th>장</th><th class="num">열린 확인 요청</th><th class="num">수정본·올린 시각</th><th class="num">갱신</th><th></th></tr>{rows}</table>
<h2>원고 올리기</h2>
<form method="post" action="/book/import" class="card">{self._csrf_input(session)}
<p><label>받은함 원고 <select name="name">{options or '<option value="">(받은함에 docx·pdf 없음)</option>'}</select></label></p>
<p><label{'' if projects else ' class="off"'}><input type="radio" name="mode" value="edition"{' checked' if projects else ' disabled'}> <b>수정본으로 올리기</b></label>
 — Word에서 고친 원고를 다시 올릴 때. 바뀐 장만 바뀌고, 결정·확인 요청·생각·문체·문헌은 그대로입니다.<br>
<label><input type="radio" name="mode" value="new"{'' if projects else ' checked'}> 새 책으로 가져오기</label> — 처음 올리는 원고</p>
<p><label>프로젝트 id <input name="project_id" value="{html.escape(projects[0].id if projects else 'book')}" pattern="[A-Za-z0-9_-]+" required></label>
<label>제목 <input name="title" placeholder="비우면 파일에서"></label>
<label>부제 <input name="subtitle" placeholder="비우면 파일에서"></label></p>
<p><label><input type="checkbox" name="force" value="1"> (수정본) 장 제목이 많이 달라도 같은 책으로 올리기</label></p>
<details><summary>드물게 쓰는 선택</summary>
<p><label><input type="checkbox" name="replace" value="1"> (새 책) 같은 id가 있으면 바꾸기 — 결정·확인 요청까지 휴지통으로 갑니다. 수정본을 올릴 때는 쓰지 마세요</label></p></details>
<p><button class="primary">올리기</button> (큰 원고는 몇십 초 걸립니다)</p></form>"""
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
            project_id = str(form.get("project_id") or "") or None
            title, subtitle = str(form.get("title") or "") or None, str(form.get("subtitle") or "") or None
            if form.get("mode") == "edition":  # 같은 책의 수정본(#76)
                if not project_id:
                    raise ValueError("수정본으로 올릴 책의 프로젝트 id를 적어 주세요.")
                again = await run_in_threadpool(
                    reupload_manuscript, self.store, uid, path, project_id,
                    title=title, subtitle=subtitle, force=form.get("force") == "1",
                )
                return await self.book(request, again.summary())
            report = await run_in_threadpool(
                import_manuscript, self.store, uid, path,
                project_id=project_id, title=title, subtitle=subtitle, replace=form.get("replace") == "1",
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

    # --- 확인 요청(issues) ---
    async def issues(self, request: Request) -> Response:
        """열린 확인 요청 목록(조회 전용). AI가 원고에 단 코멘트에서 온 것은 'AI 확인 요청'으로 드러낸다(#71)."""
        session = self.user_of(request)
        if not session:
            return self._need_login(request)
        uid = session[0]
        project = self.store.get_project(uid, request.query_params.get("project") or None)
        if project is None:
            return self._page("확인 요청", "<p>원고가 없습니다. <a href=\"/book\">원고</a>에서 임포트하세요.</p>", session)
        status = request.query_params.get("status") if request.query_params.get("status") in ("open", "closed", "all") else "open"
        kind = request.query_params.get("kind") if request.query_params.get("kind") in ISSUE_KIND_NAMES else None
        issues = self.store.list_issues(uid, project.id, None if status == "all" else status, kind=kind)  # type: ignore[arg-type]
        names = {c.number: c.display for c in self.store.list_chapters(uid, project.id)}
        q = urllib.parse.quote(project.id)

        def who(i) -> str:
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
        filters = " · ".join(
            f'<a href="?project={q}&status={status}&kind={k}">{name}</a>' for k, name in ISSUE_KIND_NAMES.items()
        )
        body = f"""<p>『{html.escape(project.title)}』 · 확인 요청 {len(issues)}건""" + (
            f" · 그중 🤖 AI 확인 요청 {ai}건(AI가 원고에 단 코멘트입니다)" if ai else "") + f"""</p>
<p><a href="?project={q}&status=open">열린 것</a> · <a href="?project={q}&status=closed">닫힌 것</a> · <a href="?project={q}&status=all">전체</a> | {filters}</p>
<table><tr><th>번호</th><th>장</th><th>누가</th><th>종류</th><th>내용</th></tr>{rows or '<tr><td colspan="5">없음</td></tr>'}</table>"""
        return self._page("확인 요청", body, session)

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
            + f'</td><td class="num">{d.count}</td><td>{html.escape(", ".join(d.chapters))}</td></tr>'
            for d in docs
        )
        chapter_rows = "".join(
            f'<tr><td>{html.escape(disp)}</td><td>{html.escape(title)}</td><td class="num">{unique}</td><td class="num">{occ}</td></tr>'
            for disp, title, unique, occ, _ in report.per_chapter
        )
        body = f"""<p>『{html.escape(project.title)}』 · 문헌 {len(report.docs) - counts['uncertain']}편
(확인 {counts['verified']} · 미확인 {counts['unverified']} · 참고문헌에 없음 {counts['unknown']}) · 미연결 {counts['uncertain']}
· <a href="?project={urllib.parse.quote(project.id)}">전체</a></p>
<p>{filters}</p>
<table><tr><th>상태</th><th>문헌</th><th class="num">인용</th><th>장</th></tr>{doc_rows or '<tr><td colspan="4">없음</td></tr>'}</table>
<h2>장별</h2><table><tr><th>장</th><th>제목</th><th class="num">미확인 문헌</th><th class="num">인용 출현</th></tr>{chapter_rows}</table>"""
        return self._page("인용 체크리스트", body, session)

    # --- 세 책장(읽기 전용): 넣는 것은 Claude 대화로 한다 ---
    async def ideas(self, request: Request) -> Response:
        """생각(Casper). 최근 것부터. 누가 말했는지(나·AI)를 구분하고, AI 답은 응답한 내 생각으로 잇는다."""
        session = self.user_of(request)
        if not session:
            return self._need_login(request)
        uid = session[0]
        author = request.query_params.get("author") if request.query_params.get("author") in ("me", "ai") else None
        everything = self.store.list_ideas(uid)
        if not everything:
            return self._page("생각", f'<p class="msg">아직 쌓인 생각이 없습니다. {SAY}"생각에 기록해 줘: …"</p>', session)
        chosen = [i for i in reversed(everything) if author is None or i.author == author]
        shown, pager = _paged(chosen, request)
        mine = sum(1 for i in everything if i.author == "me")

        def who(i) -> str:
            if i.author == "me":
                return "나"
            back = f'<br><small><a href="#idea-{html.escape(i.parent_id)}">응답한 생각</a></small>' if i.parent_id else ""
            return f'<span class="tag">AI</span>{back}'

        rows = "".join(
            f'<tr id="idea-{html.escape(i.id)}"><td class="num">{local_time(i.created_at, "%Y-%m-%d")}</td>'
            f"<td>{_fold(i.text)}</td><td>{who(i)}</td><td>{html.escape(i.origin or '')}</td></tr>"
            for i in shown
        )
        body = (f"<p>생각 {len(everything)}개(나 {mine} · AI {len(everything) - mine}) · "
                '<a href="?">전체</a> · <a href="?author=me">나</a> · <a href="?author=ai">AI</a></p>'
                f"{pager}<table><tr><th class=\"num\">날짜</th><th>내용</th><th>누가</th><th>출처</th></tr>"
                f"{rows or '<tr><td colspan=\"4\">없음</td></tr>'}</table>{pager}")
        return self._page("생각", body, session)

    async def refs(self, request: Request) -> Response:
        """문헌(Melchior). 확인한 것부터. 쓸 부분·이유(발췌)와 지금 책에서 인용된 장. 인용 현황 전체는 인용 체크리스트로 잇는다."""
        session = self.user_of(request)
        if not session:
            return self._need_login(request)
        uid = session[0]
        everything = self.store.list_refs(uid)
        if not everything:
            return self._page("문헌", f'<p class="msg">아직 등록한 문헌이 없습니다. {SAY}'
                                    '"받은함의 kremer1993.pdf를 문헌으로 등록해 줘. 쓸 부분은 「…」, 이유는 …"</p>', session)
        status = request.query_params.get("status") if request.query_params.get("status") in ("verified", "unverified") else None
        project = self.store.get_project(uid, request.query_params.get("project") or None)
        cited: dict[str, list[str]] = {}
        if project is not None:
            report = await run_in_threadpool(build_cite_report, self.store, uid, project.id)
            cited = {key: list(dict.fromkeys(d.chapters)) for key, d in report.docs.items()}
        chosen = sorted((r for r in everything if status is None or r.status == status), key=lambda r: (r.status != "verified", r.key))
        shown, pager = _paged(chosen, request)
        verified = sum(1 for r in everything if r.status == "verified")

        def passages(ref) -> str:
            found = self.store.get_passages(uid, ref.key)
            return "<br>".join(
                f"「{_fold(p.text, 200)}」<br><small>{html.escape(p.reason)}"
                + (f" · {html.escape(p.locator)}" if p.locator else "") + "</small>"
                for p in found
            ) or "-"

        rows = "".join(
            f"<tr><td>{LIGHTS[r.status][0]} {LIGHTS[r.status][1]}</td>"
            f"<td>{html.escape(cite_label(r, r.key))}"
            + (f"<br><small>{html.escape(str(r.bib.get('container')))}</small>" if r.bib.get("container") else "")
            + f"</td><td>{passages(r)}</td><td>{html.escape(chapters_text(cited.get(r.key, [])) or '-')}</td></tr>"
            for r in shown
        )
        q = f"project={urllib.parse.quote(project.id)}&" if project else ""
        checklist = f' · 인용 현황은 <a href="/checklist?{q}">인용 체크리스트</a>' if project else ""
        body = (f"<p>문헌 {len(everything)}편(확인 {verified} · 미확인 {len(everything) - verified}){checklist}</p>"
                f'<p><a href="?{q}">전체</a> · <a href="?{q}status=verified">{LIGHTS["verified"][0]} {LIGHTS["verified"][1]}</a>'
                f' · <a href="?{q}status=unverified">{LIGHTS["unverified"][0]} {LIGHTS["unverified"][1]}</a></p>'
                f"{pager}<table><tr><th>상태</th><th>문헌</th><th>쓸 부분·이유</th><th>인용된 장</th></tr>"
                f"{rows or '<tr><td colspan=\"4\">없음</td></tr>'}</table>{pager}")
        return self._page("문헌", body, session)

    async def styles(self, request: Request) -> Response:
        """문체(Balthasar). 구절·출처·이유·태그. 태그를 누르면 그 태그만 본다."""
        session = self.user_of(request)
        if not session:
            return self._need_login(request)
        uid = session[0]
        everything = self.store.list_styles(uid)
        if not everything:
            return self._page("문체", f'<p class="msg">아직 모은 문장이 없습니다. {SAY}'
                                    '"이 문장을 문체에 넣어 줘: 「…」 — 짧게 끊어 읽히는 호흡이 좋다"</p>', session)
        tag = (request.query_params.get("tag") or "").strip()
        chosen = [s for s in reversed(everything) if not tag or tag in _style_tags(s)]
        shown, pager = _paged(chosen, request)

        def tags(s) -> str:
            pills = " ".join(f'<a class="tag" href="?tag={urllib.parse.quote(t)}">{html.escape(t)}</a>' for t in _style_tags(s))
            by = TAGS_BY.get(s.tags_by or "")  # 태그를 누가 정했나(#89). 기록 전 항목은 표시하지 않는다
            return pills + (f"<br><small>{by}</small>" if by else "")

        rows = "".join(
            f"<tr><td>「{_fold(s.passage, 300)}」</td><td>{html.escape(s.work or '')}</td>"
            f"<td>{_fold(s.reason, 300)}</td><td>{tags(s)}</td></tr>"
            for s in shown
        )
        only = f" · 태그 「{html.escape(tag)}」만 · <a href=\"?\">전체</a>" if tag else ""
        body = (f"<p>문장 {len(everything)}개{only}</p>"
                f"{pager}<table><tr><th>구절</th><th>출처</th><th>이유</th><th>태그</th></tr>"
                f"{rows or '<tr><td colspan=\"4\">없음</td></tr>'}</table>{pager}")
        return self._page("문체", body, session)
