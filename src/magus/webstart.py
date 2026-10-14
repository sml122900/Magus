"""처음 온 사람의 길(2026-10-14 야간): 로그인 전 첫 화면(/), Claude 연결 안내(/connect), 프로젝트 목록의 시작 순서.

- 첫 화면은 이 서비스가 무엇인지 세 줄과 '시작하기'(로그인)만. 로그인했으면 프로젝트 목록으로.
- 연결 안내는 로그인 없이도 열린다(커넥터 주소는 공개 주소다). 주소 복사 단추, claude.ai 설정 순서, '항상 허용', 연결 확인 문장.
- 시작 순서는 문서를 하나 올릴 때까지 프로젝트 목록 위에 보인다(가입 → 프로젝트 → 문서 → 연결 → 묻기). 끝난 단계는 ✓.
화면 글자는 최소로(#97)라는 원칙의 예외다: 처음 온 사람은 도움말 '?'를 누르기 전에 막힌다(야간 보고 docs/nightly/2026-10-14.md)."""

from __future__ import annotations

import html
import urllib.parse
from collections.abc import Callable
from pathlib import Path
from typing import Any

from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response

from magus.extract import EXTRACTABLE, NO_TEXT_SUFFIXES
from magus.mdlite import to_html
from magus.store import Store

PRIVACY_FILE = Path(__file__).resolve().parents[2] / "docs" / "drafts" / "privacy.md"  # 저장소(Docker: /app)
PRIVACY_CUT = "<!-- 여기부터 대조 기록(공개하지 않음) -->"
ASK_ALL = "magus 전체 보여 줘"
ASK_FIND = "magus에서 ○○ 찾아 줘"

START_STYLE = """
.lead{font-size:20px;line-height:1.5;margin:8px 0 16px}
ul.three{padding-left:20px;margin:0 0 24px}ul.three li{margin:6px 0}
.steps h2{margin:0 0 8px;font-size:18px}.steps ol{margin:0;padding-left:24px}.steps li{margin:8px 0}
.steps li.done{color:var(--ink2)}.steps li.done b::after{content:" ✓";color:var(--primary)}
.steps li small{display:block;color:var(--ink2)}
.steps li.next{border-left:4px solid var(--primary);padding:4px 0 4px 12px;margin-left:-16px}.steps li span{display:block;margin-top:6px}
.url-box{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:8px 0 16px}
.url-box code{font-size:17px;padding:8px 12px;border:1px solid var(--mute);border-radius:6px;background:var(--canvas);word-break:break-all;user-select:all}
.must{border-left:4px solid var(--primary);padding:12px 16px;background:var(--canvas);border-radius:6px;margin:16px 0}
ol.howto li{margin:10px 0}
.say{font-weight:600}
"""

COPY_SCRIPT = """<script>(()=>{const b=document.querySelector('[data-copy]');if(!b)return;const t=document.getElementById(b.dataset.copy);
const say=document.querySelector('.copy-note');b.addEventListener('click',async()=>{const v=t.textContent.trim();
try{await navigator.clipboard.writeText(v);say.textContent='복사했습니다.';}catch(e){const r=document.createRange();r.selectNodeContents(t);
const s=getSelection();s.removeAllRanges();s.addRange(r);say.textContent='주소를 골라 두었습니다. Ctrl+C로 복사하세요.';}});})();</script>"""


def mcp_url(base_url: str) -> str:
    return base_url.rstrip("/") + "/mcp"


def has_document(store: Store, uid: str, floors: list[Any]) -> bool:
    """문서를 하나라도 올렸나(올린 문서가 든 프로젝트, 또는 글에 첨부한 문서)."""
    if any(getattr(f, "has_manuscript", False) for f in floors):
        return True
    return bool(store.file_attachments(uid, EXTRACTABLE + NO_TEXT_SUFFIXES))


def steps_card(projects: bool, document: bool, project_link: str = "") -> str:
    """프로젝트 목록 위 시작 순서. 끝난 단계는 흐리게 + ✓, 다음 단계는 테두리와 단추 하나.
    project_link: 가장 최근 프로젝트 화면(문서 올리기 단계의 단추)."""
    steps = [
        (True, "가입", "로그인했습니다.", ""),
        (projects, "프로젝트 만들기", "아래 「+ 프로젝트」에 제목을 적고 만들기.", ""),
        (document, "문서 올리기", "프로젝트에서 「새 책」을 만들고, 글쓰기에서 파일을 첨부합니다(hwp·hwpx·docx·pdf·pptx·xlsx 등).",
         f'<a class="btn quiet" href="{html.escape(project_link)}">프로젝트 열기</a>' if project_link else ""),
        (False, "Claude에 Magus 연결", "연결 안내를 따라 컴퓨터에서 한 번만 하면 됩니다.", '<a class="btn quiet" href="/connect">연결 안내</a>'),
        (False, "Claude에게 묻기", f"새 대화에서 「{ASK_ALL}」 또는 「{ASK_FIND}」.", ""),
    ]
    nxt = next(i for i, (done, *_rest) in enumerate(steps) if not done)
    rows = "".join(
        f'<li{" class=done" if done else " class=next" if i == nxt else ""}><b>{title}</b><small>{how}</small>'
        + (f"<span>{act}</span>" if act and not done else "") + "</li>"
        for i, (done, title, how, act) in enumerate(steps))
    return f'<section class="card steps" aria-label="시작 순서"><h2>시작 순서</h2><ol>{rows}</ol></section>'


class StartPages:
    store: Store
    settings: Any
    base_url: str
    user_of: Callable[[Request], tuple[str, str] | None]
    _page: Callable[..., HTMLResponse]

    def start_routes(self) -> list[tuple[str, list[str], Callable[..., Any]]]:
        return [("/", ["GET"], self.landing), ("/connect", ["GET"], self.connect_page), ("/privacy", ["GET"], self.privacy_page)]

    async def privacy_page(self, request: Request) -> Response:
        """개인정보 처리방침(2026-10-14 초안). PRIVACY_PAGE가 켜졌을 때만 보이고, 꺼져 있으면 없는 주소와 같은 404.
        글은 docs/drafts/privacy.md의 대조 기록 앞까지(대조 표는 공개하지 않는다). 로그인 없이 열린다."""
        if not self.settings.privacy_page:
            raise HTTPException(status_code=404)
        path = self.settings.privacy_file or PRIVACY_FILE
        try:
            text = (await run_in_threadpool(path.read_text, encoding="utf-8")).split(PRIVACY_CUT, 1)[0]
        except OSError:
            raise HTTPException(status_code=404) from None
        lines = text.strip().splitlines()
        title = lines[0].lstrip("# ").strip() if lines and lines[0].startswith("# ") else "개인정보 처리방침"
        body = to_html("\n".join(lines[1:] if lines and lines[0].startswith("# ") else lines))
        return self._page(title, body, self.user_of(request), css=START_STYLE)

    async def landing(self, request: Request) -> Response:
        if self.user_of(request):
            return RedirectResponse("/shelf", status_code=303)
        body = (
            '<p class="lead">원고·논문·자료를 올려 두면, Claude가 대화에서 바로 찾아 읽습니다.</p>'
            '<ul class="three">'
            "<li>한글(hwp)·Word·PDF·파워포인트·엑셀 파일을 그대로 올립니다.</li>"
            "<li>Claude에 Magus를 한 번 연결하면 「magus에서 ○○ 찾아 줘」로 내 자료를 찾습니다.</li>"
            "<li>올린 자료는 다른 사용자에게 보이지 않습니다. 원본 파일은 내 컴퓨터에 그대로 둡니다.</li>"
            "</ul>"
            '<p><a class="btn primary" href="/login">시작하기</a></p>'
            '<p class="muted">지금은 초대받은 분만 쓸 수 있습니다.</p>'
            '<p><a href="/connect">Claude 연결 안내</a></p>'
        )
        return self._page("Magus", body, css=START_STYLE)

    async def connect_page(self, request: Request) -> Response:
        session = self.user_of(request)
        url = html.escape(mcp_url(self.base_url))
        body = (
            "<h2>1. 커넥터 주소</h2>"
            f'<div class="url-box"><code id="mcp-url">{url}</code>'
            '<button type="button" class="primary" data-copy="mcp-url">주소 복사</button></div>'
            '<p class="copy-note muted" role="status" aria-live="polite"></p>'
            "<h2>2. claude.ai에 넣기(컴퓨터에서 한 번)</h2>"
            '<ol class="howto">'
            "<li>claude.ai에 로그인 → 왼쪽 아래 이름 → <b>설정</b> → <b>커넥터</b></li>"
            "<li><b>커스텀 커넥터 추가</b> → 이름 <code>Magus</code>, 주소 칸에 위 주소를 붙여 넣고 <b>추가</b></li>"
            "<li><b>연결</b> → Magus 로그인 화면에서 이 사이트와 같은 메일로 로그인(메일로 온 코드)</li>"
            "<li>대화창 아래 도구 메뉴에서 <b>Magus</b>가 켜져 있는지 봅니다.</li>"
            "</ol>"
            '<p class="muted">claude.ai가 영어로 보이면 설정 = Settings, 커넥터 = Connectors, 커스텀 커넥터 추가 = Add custom connector, '
            "연결 = Connect, 항상 허용 = Always allow입니다.</p>"
            '<div class="must"><b>「항상 허용」을 고르세요.</b> Claude가 Magus를 처음 쓸 때 허락을 물으면 「항상 허용」을 누릅니다. '
            "고르지 않으면 찾을 때마다 다시 묻습니다(설정 › 커넥터 › Magus에서도 바꿀 수 있습니다).</div>"
            "<h2>3. 연결 확인</h2>"
            f'<p>새 대화에서 <span class="say">「{ASK_ALL}」</span>라고 써 보세요. 「프로젝트: …」로 시작하는 답이 오면 연결된 것입니다.</p>'
            f'<p>올린 문서를 찾을 때는 <span class="say">「{ASK_FIND}」</span>.</p>'
            '<p class="muted">휴대폰 Claude 앱에는 따로 할 일이 없습니다. 컴퓨터에서 연결한 것이 그대로 보입니다. '
            "안 되면 커넥터를 지우고 다시 추가한 뒤 연결합니다.</p>"
            + (f'<p><a href="{"/shelf" if session else "/login"}">{"프로젝트로" if session else "시작하기"}</a></p>')
            + COPY_SCRIPT
        )
        return self._page("Claude 연결", body, session, css=START_STYLE)


async def project_steps(store: Store, uid: str, floors: list[Any]) -> str:
    """문서를 올리기 전까지만 시작 순서를 보인다. 그 뒤에는 빈 문자열."""
    document = await run_in_threadpool(has_document, store, uid, floors)
    if document:
        return ""
    latest = max(floors, key=lambda f: f.updated_at, default=None)
    return steps_card(bool(floors), document, f"/shelf/p/{urllib.parse.quote(latest.id)}" if latest else "")
