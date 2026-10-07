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
import urllib.error
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
from magus.config import Settings
from magus.ids import local_time, utcnow
from magus.inbox import INBOX_TYPES, LimitError, mb, save_upload, size_text
from magus.signing import sign, unsign
from magus.store import Profile, Store
from magus.webbooks import BookPages
from magus.webfloors import FloorPages
from magus.webshelf import EMBED, ShelfPages, is_panel_request, safe_at, state_url

log = logging.getLogger("magus.web")
SESSION_COOKIE, OAUTH_COOKIE = "magus_session", "magus_oauth"
DISPLAY_NAME_MAX = 40  # 상단 바 표시 이름 길이 한도
SESSION_TTL, OAUTH_TTL, DOWNLOAD_TTL = 12 * 3600, 600, 24 * 3600
# 생각·문헌·문체는 '책장' 하나로 모았다(2026-10-06). 책장 화면은 magus.webshelf.
NAV = (("/shelf", "책장"),)  # #94: 저자 화면은 책장 하나. 원고·확인 요청·인용 상태는 원고 책 안에, 올린 파일은 내 정보 아래

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
.site nav a.me{color:var(--ink2);border-bottom-color:transparent;max-width:16em;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.muted{color:var(--ink2)}
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
.qlist{list-style:none;padding:0;margin:12px 0}.qlist .card{margin:12px 0}.qlist .muted{color:var(--ink2)}
details{margin:12px 0}summary{cursor:pointer;color:var(--ink2);padding:4px 0}
form.inline{display:inline}
form.busy{pointer-events:none}
form.busy button::after{content:"";display:inline-block;width:14px;height:14px;margin-left:8px;vertical-align:-2px;
border:2px solid currentColor;border-right-color:transparent;border-radius:50%;animation:spin .8s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
@media (max-width:767px){main{padding:16px 12px 24px}h1{font-size:22px}table{min-width:640px}
button,input[type=file]::file-selector-button,input:not([type=radio]):not([type=checkbox]):not([type=hidden]),select{min-height:44px}}
"""
# 책장 패널(iframe) 안의 화면: 흰 바탕, 좁은 여백. 제목(h1)은 패널 머리가 보이므로 숨기고, 책장으로 돌아가는 길('← 책장 · N층')도 뺀다.
EMBED_STYLE = """
body.embed{background:var(--canvas)}
body.embed main{max-width:none;padding:12px 16px 24px}
body.embed main>h1{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
body.embed .crumb:has(> a[href="/shelf"]){display:none}
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


class OAuthClient:
    """웹 로그인용 OAuth 클라이언트(인증 서버에 등록한 client_id). 메타데이터는 issuer의 .well-known에서 찾는다."""

    def __init__(self, issuer: str, client_id: str, client_secret: str | None, redirect_uri: str, resource: str):
        self.issuer, self.client_id, self.client_secret = issuer.rstrip("/"), client_id, client_secret
        self.redirect_uri, self.resource = redirect_uri, resource
        self._meta: dict[str, Any] | None = None
        self._oidc: dict[str, Any] | None = None

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

    def oidc_metadata(self) -> dict[str, Any]:
        """OIDC 디스커버리(/.well-known/openid-configuration). userinfo_endpoint는 여기에만 있다
        (WorkOS의 oauth-authorization-server 메타데이터에는 없다 — 2026-10-06 메일을 못 받던 원인). 못 읽으면 빈 dict."""
        if self._oidc is None:
            try:
                with urllib.request.urlopen(self.issuer + "/.well-known/openid-configuration", timeout=10) as r:  # noqa: S310
                    data = json.load(r)
                self._oidc = data if isinstance(data, dict) else {}
            except (OSError, ValueError):
                return {}
        return self._oidc

    def userinfo_endpoint(self) -> str | None:
        """userinfo 주소: OAuth 메타데이터, 없으면 OIDC 디스커버리. issuer와 같은 곳의 주소만 쓴다."""
        endpoint = str(self.metadata().get("userinfo_endpoint") or self.oidc_metadata().get("userinfo_endpoint") or "")
        return endpoint if endpoint.startswith(self.issuer + "/") else None

    def exchange(self, code: str, verifier: str) -> dict[str, Any]:
        form = {"grant_type": "authorization_code", "code": code, "redirect_uri": self.redirect_uri,
                "client_id": self.client_id, "code_verifier": verifier, "resource": self.resource}
        if self.client_secret:
            form["client_secret"] = self.client_secret
        request = urllib.request.Request(
            self.metadata()["token_endpoint"], urllib.parse.urlencode(form).encode(),
            {"content-type": "application/x-www-form-urlencoded", "accept": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=15) as r:  # noqa: S310
            tokens = json.load(r)
        if not isinstance(tokens, dict) or not tokens.get("access_token"):
            raise RuntimeError("토큰 응답에 access_token이 없다")
        return tokens  # access_token, (scope에 openid가 있으면) id_token 등

    def userinfo(self, access_token: str) -> tuple[str, dict[str, Any] | None]:
        """OIDC userinfo(WorkOS: POST /oauth2/userinfo, Bearer 액세스 토큰 → sub·email·email_verified).
        scope에 email이 있어야 메일이 온다(웹 로그인은 openid profile email을 청한다).
        (결과 이유, 응답). 이유는 로그용이고 값을 담지 않는다: ok | no-endpoint | http <상태> | error. 실패해도 로그인은 막지 않는다."""
        endpoint = self.userinfo_endpoint()
        if not endpoint:
            return "no-endpoint", None
        request = urllib.request.Request(endpoint, b"", {"authorization": f"Bearer {access_token}", "accept": "application/json"},
                                         method="POST")
        try:
            with urllib.request.urlopen(request, timeout=10) as r:  # noqa: S310 - issuer와 같은 곳의 주소만(userinfo_endpoint)
                data = json.load(r)
        except urllib.error.HTTPError as e:
            return f"http {e.code}", None
        except (OSError, ValueError):
            return "error", None
        return ("ok", data) if isinstance(data, dict) else ("error", None)


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


@dataclass
class Web(ShelfPages, FloorPages, BookPages):
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
            ("/logout", ["POST"], self.logout), ("/me", ["GET", "POST"], self.me), ("/me/files", ["GET"], self.inbox),
            ("/inbox/upload", ["POST"], self.upload), ("/inbox/delete", ["POST"], self.delete),
            ("/book/export", ["POST"], self.do_export), ("/download/{token}", ["GET"], self.download),
            # 옛 주소는 책장의 새 화면으로(#94)
            ("/inbox", ["GET"], self.files_moved), ("/book", ["GET"], self._old_page("chapters", ())),
            ("/issues", ["GET"], self._old_page("issues", ("status", "kind"))),
            ("/checklist", ["GET"], self._old_page("cites", ("status",))),
            ("/questions", ["GET"], self._old_page("cites", ("status", "type"), {"view": "questions"})),
            *self.shelf_routes(),
        ]
        for path, methods, handler in routes:
            server.custom_route(path, methods=methods, include_in_schema=False)(self._wrap(handler))

    def _wrap(self, handler: Callable[[Request], Awaitable[Response]]) -> Callable[[Request], Awaitable[Response]]:
        """한 화면 책장(2026-10-07 밤): 책 화면 주소를 브라우저 주소창으로 바로 열면 책장의 그 층·그 책 패널로 넘긴다.
        책장 패널(iframe) 안의 요청이면 머리(메뉴) 없는 패널 모양으로 그린다(EMBED)."""

        async def run(request: Request) -> Response:
            path = request.url.path
            if (request.method == "GET" and request.headers.get("sec-fetch-dest") == "document"
                    and request.headers.get("sec-fetch-mode") == "navigate" and path.startswith("/shelf/")
                    and not path.startswith("/shelf/floor/") and not path.endswith("/docx")):
                at = safe_at(path + (f"?{request.url.query}" if request.url.query else ""))
                if at:
                    return RedirectResponse(state_url(at=at), status_code=303)
            token = EMBED.set(is_panel_request(request))
            try:
                return await handler(request)
            finally:
                EMBED.reset(token)

        return run

    # --- 공통 ---
    def _page(self, title: str, body: str, session: tuple[str, str] | None = None, status: int = 200, *,
              current: str | None = None, css: str = "") -> HTMLResponse:
        """current: 지금 보고 있는 메뉴 이름(없으면 제목). css: 그 화면에만 더하는 스타일(책장)."""
        nav = ""
        if session:  # 지금 보고 있는 메뉴(제목이 메뉴 이름과 같은 화면)는 aria-current로 표시한다
            links = "".join(
                f'<a href="{href}"{" aria-current=page" if label == (current or title) else ""}>{label}</a>' for href, label in NAV
            )
            shown = html.escape(self.shown_name(session[0]))
            nav = (f'<nav>{links}<a href="/me" class="me" aria-label="내 정보, {shown}">{shown}</a>'
                   f'<form method="post" action="/logout" class="inline">{self._csrf_input(session)}<button>로그아웃</button></form></nav>')
        body = body.replace("<table>", '<div class="table-wrap"><table>').replace("</table>", "</table></div>")
        if EMBED.get():  # 책장 패널(iframe) 안: 머리(메뉴) 없이, 제목은 패널 머리가 보인다
            return HTMLResponse(
                f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)} · Magus</title><style>{STYLE}{css}{EMBED_STYLE}</style></head><body class="embed">
<main><h1>{html.escape(title)}</h1>{body}</main></body></html>""",
                status_code=status,
            )
        return HTMLResponse(
            f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)} · Magus</title><style>{STYLE}{css}</style></head><body>
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
        here = request.url.path + (f"?{request.url.query}" if request.url.query else "")  # 책장의 층·책 상태도 이어서
        return RedirectResponse(f"/login?next={urllib.parse.quote(here)}", status_code=303)

    # --- 로그인 ---
    async def home(self, request: Request) -> Response:
        return RedirectResponse("/shelf" if self.user_of(request) else "/login", status_code=303)

    async def login(self, request: Request) -> Response:
        nxt = request.query_params.get("next", "/shelf")
        nxt = nxt if nxt.startswith("/") and not nxt.startswith("//") else "/shelf"
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
            tokens = await run_in_threadpool(self.oauth.exchange, code, str(pending["v"]))
            token = str(tokens["access_token"])
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
        await run_in_threadpool(self._remember_email, uid, str(claims.get("sub", "")), tokens)
        response = RedirectResponse(str(pending.get("n") or "/shelf"), status_code=303)
        self._cookie(response, SESSION_COOKIE, sign({"uid": uid, "sid": secrets.token_hex(8)}, self.secret, "session",
                                                    SESSION_TTL), SESSION_TTL)
        response.delete_cookie(OAUTH_COOKIE, path="/")
        log.info("web login user=%s", uid)
        return response

    def _remember_email(self, uid: str, sub: str, tokens: dict[str, Any]) -> None:
        """웹 로그인 때 메일을 프로필에 적는다. ① userinfo(OIDC 디스커버리의 주소) ② 없으면 로그인 응답의 id_token
        (서명·iss·aud=웹 클라이언트 id·exp 검증). 어느 쪽이든 sub가 검증한 액세스 토큰의 sub와 같을 때만 쓴다.
        로그에는 메일을 남기지 않는다(어느 길로 받았는지·못 받은 이유만, #52). 실패해도 로그인은 그대로다."""
        if self.oauth is None or self.verifier is None:
            return

        def usable(claims: dict[str, Any] | None) -> str:
            if not claims:
                return ""
            email = str(claims.get("email") or "").strip()
            if str(claims.get("sub", "")) != sub:
                return "sub-mismatch"
            return email if "@" in email and len(email) <= 254 else "no-email"

        reason, info = self.oauth.userinfo(str(tokens["access_token"]))
        email = usable(info)
        via, why = "userinfo", (reason if reason != "ok" else (email if email in ("sub-mismatch", "no-email") else ""))
        if "@" not in email:
            raw = str(tokens.get("id_token") or "")
            claims = self.verifier.id_token_claims(raw, self.oauth.client_id) if raw else None
            email = usable(claims)
            via = "id_token"
            state = "none" if not raw else "invalid" if claims is None else "ok" if "@" in email else email or "no-email"
            why += f"; id_token={state}"  # 이유 코드만(메일 값은 넣지 않는다)
        ok = "@" in email
        log.info("web login profile: email=%s via=%s%s", "yes" if ok else "no", via if ok else "-", "" if ok else f" ({why})")
        if not ok:
            return
        profile = self.store.get_profile(uid)
        if profile.email != email:
            self.store.save_profile(uid, Profile(email, profile.display_name, utcnow(), profile.name_at))

    def shown_name(self, uid: str) -> str:
        """상단 바 이름: 표시 이름, 없으면 메일, 없으면 내부 이름."""
        profile = self.store.get_profile(uid)
        return profile.display_name or profile.email or uid

    async def me(self, request: Request) -> Response:
        """내 정보: 표시 이름 바꾸기(본인 것만, CSRF). 메일은 보이기만 한다. 비우면 다시 메일로 보인다."""
        session = self.user_of(request)
        if not session:
            return self._need_login(request)
        uid = session[0]
        profile = await run_in_threadpool(self.store.get_profile, uid)
        message = ""
        if request.method == "POST":
            try:
                form = await self._form(request, session)
            except PermissionError:
                return self._page("내 정보", '<p class="msg err">잘못된 요청입니다.</p>', session, 403)
            name = " ".join("".join(ch for ch in str(form.get("display_name") or "") if ch.isprintable()).split())
            if len(name) > DISPLAY_NAME_MAX:
                message = f'<p class="msg err">표시 이름은 {DISPLAY_NAME_MAX}자까지입니다. 지금 {len(name)}자</p>'
            else:
                profile = Profile(profile.email, name or None, profile.email_at, utcnow())
                await run_in_threadpool(self.store.save_profile, uid, profile)
                return RedirectResponse("/me?done=1", status_code=303)
        elif request.query_params.get("done") == "1":
            message = '<p class="msg">저장했습니다.</p>'
        email = (f"<p>메일: {html.escape(profile.email)}</p>" if profile.email
                 else "<p>메일: 아직 모릅니다(웹에서 로그인하면 채워집니다).</p>")
        body = (
            f'{message}<form method="post" action="/me" class="card">{self._csrf_input(session)}'
            f'<p><label>표시 이름 <input name="display_name" value="{html.escape(profile.display_name or "")}" '
            f'maxlength="{DISPLAY_NAME_MAX}"></label></p>'
            "<p>위쪽 막대에 보이는 이름입니다. 비우고 저장하면 메일이 보입니다.</p>"
            f'{email}<p class="muted">메일은 로그인한 계정의 것이라 여기서 바꾸지 않습니다.</p>'
            '<p><button class="primary">저장</button></p></form>'
            '<h2>올린 파일</h2><p><a href="/me/files">올린 파일 보기·올리기·지우기</a> — 원고 책·문헌 책에서 올린 것 말고, '
            "Claude에게 파일 이름으로 건넬 파일을 둡니다.</p>"
        )
        return self._page("내 정보", body, session, 400 if message.startswith('<p class="msg err">') else 200)

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
<p><a href="/me">← 내 정보</a></p>
<p>원고는 책장의 원고 책에서, 논문은 문헌 책에서 올리면 바로 쓰입니다. 여기서 올린 파일은 Claude에게 파일 이름으로 말씀하세요.
예: "올린 파일 kremer1993.pdf를 문헌으로 등록해 줘. 쓸 부분은 「…」, 이유는 …"</p>
{UPLOAD_SCRIPT}"""
        return self._page("올린 파일", body, session, current="")

    async def upload(self, request: Request) -> Response:
        session = self.user_of(request)
        if not session:
            return self._need_login(request)
        limit = self.settings.max_upload_bytes * 20 + 1_000_000
        if int(request.headers.get("content-length") or 0) > limit:  # 다 받기 전에 거른다
            return self._page("올린 파일", f'<p class="msg err">요청이 너무 큽니다(한도 {mb(limit)}).</p>', session, 413)
        try:
            form = await self._form(request, session)
        except PermissionError:
            return self._page("올린 파일", '<p class="msg err">잘못된 요청입니다.</p>', session, 403)
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
            return self._page("올린 파일", '<p class="msg err">잘못된 요청입니다.</p>', session, 403)
        return await self.inbox(request, f"지움: {name}" if ok else f"없음: {name}", not ok)

    # --- 옛 주소(#94): 원고·확인 요청·답해 주실 질문·인용 체크리스트·받은함 → 책장의 새 화면으로 ---
    def _moved_to(self, uid: str, project_id: str | None, tab: str, keep: dict[str, str]) -> str:
        """옛 화면 주소 → 원고 책의 탭. 원고가 있는 작업물이 없으면 책장."""
        try:
            project = self.store.get_project(uid, project_id) if project_id else None
        except ValueError:
            project = None
        if project is None:
            project = next((p for p in self.store.list_projects(uid) if self.store.list_chapters(uid, p.id)), None)
        if project is None:
            return "/shelf"
        query = urllib.parse.urlencode({"tab": tab, **{k: v for k, v in keep.items() if v}})
        return f"/shelf/book/{urllib.parse.quote(project.id)}?{query}"

    def _old_page(self, tab: str, keys: tuple[str, ...], extra: dict[str, str] | None = None) -> Callable[[Request], Awaitable[Response]]:
        async def moved(request: Request) -> Response:
            session = self.user_of(request)
            if not session:
                return self._need_login(request)
            params = request.query_params
            keep = {**{k: params.get(k, "") for k in keys}, **(extra or {})}
            target = await run_in_threadpool(self._moved_to, session[0], params.get("project"), tab, keep)
            return RedirectResponse(target, status_code=302)

        return moved

    async def files_moved(self, request: Request) -> Response:
        if not self.user_of(request):
            return self._need_login(request)
        return RedirectResponse("/me/files", status_code=302)

    async def do_export(self, request: Request) -> Response:
        session = self.user_of(request)
        if not session:
            return self._need_login(request)
        try:
            form = await self._form(request, session)
        except PermissionError:
            return self._page("원고 책", '<p class="msg err">잘못된 요청입니다.</p>', session, 403)
        project = self.store.get_project(session[0], str(form.get("project_id", "")))
        if project is None or not self.store.list_chapters(session[0], project.id):  # 빈 층에는 원고 책이 없다
            return self._page("원고 책", '<p class="msg err">없는 원고 책입니다. <a href="/shelf">책장</a>으로 돌아가세요.</p>', session, 404)
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
