"""P1 4단계: 웹 페이지 4개(로그인, 받은함, 원고, 인용 체크리스트)와 내려받기.

- 로컬(인증 없는 HTTP): 업로드 → 임포트 → 체크리스트 → 내보내기 → 내려받기 한 바퀴, CSRF, 만료·위조 링크.
- 원격: 가짜 인증 서버로 OAuth 인가 코드 + PKCE 로그인. 허용 목록 밖은 403, 링크는 같은 사용자만.
"""

from __future__ import annotations

import base64
import hashlib
import http.server
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.parse
from pathlib import Path

import httpx2
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from test_http import FIXTURES, _free_port, _wait_healthy  # tests/는 패키지가 아니다(rootdir 모드)

from magus.signing import sign, unsign

ISSUER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _csrf(page: str) -> str:
    return re.search(r'name="csrf" value="([0-9a-f]+)"', page).group(1)


@pytest.fixture
def server_proc(tmp_path: Path):
    """(env 추가분) → (base_url, data_dir, log)"""
    procs = []

    def start(extra: dict[str, str], user: str = "alice") -> tuple[str, Path, Path]:
        port = _free_port()
        data_dir = tmp_path / f"data{port}"
        log_path = tmp_path / f"server{port}.log"
        env = {**os.environ, "USER_ID": user, "DATA_DIR": str(data_dir), "EMBEDDINGS": "none", "PYTHONIOENCODING": "utf-8", **extra}
        if "PUBLIC_URL" in extra:
            env["PUBLIC_URL"] = extra["PUBLIC_URL"].replace("{port}", str(port))
        log = log_path.open("w", encoding="utf-8")
        proc = subprocess.Popen([sys.executable, "-m", "magus", "serve", "--transport", "http", "--port", str(port)],
                                env=env, stdout=log, stderr=subprocess.STDOUT)
        procs.append((proc, log))
        base = f"http://127.0.0.1:{port}"
        _wait_healthy(f"{base}/healthz", proc)
        return base, data_dir, log_path

    yield start
    for proc, log in procs:
        proc.terminate()
        proc.wait(timeout=10)
        log.close()


def test_local_round_trip_upload_import_checklist_download(server_proc):
    base, _, log_path = server_proc({})
    with httpx2.Client(base_url=base, follow_redirects=True, timeout=120) as c:
        assert c.get("/inbox", follow_redirects=False).headers["location"].startswith("/login")  # 로그인 전
        page = c.get("/login?next=/inbox").text  # 로컬 개발: USER_ID로 바로 로그인
        assert "받은함" in page and "비어 있습니다" in page
        csrf = _csrf(page)
        assert c.post("/inbox/upload", data={"csrf": "틀림"}, files={"files": ("x.md", b"a")}).status_code == 403
        with (FIXTURES / "닿으려는_종_합성.docx").open("rb") as f:
            page = c.post("/inbox/upload", data={"csrf": csrf},
                          files=[("files", ("원고.docx", f.read())), ("files", ("나쁜.exe", b"x"))]).text
        assert "올림: 원고.docx" in page and "나쁜.exe: 받을 수 있는 형식은" in page
        page = c.get("/book").text
        assert '<option value="원고.docx">' in page
        page = c.post("/book/import", data={"csrf": csrf, "name": "원고.docx", "project_id": "synth", "title": ""}).text
        assert "장 7개(" in page and "<td>synth</td>" in page
        page = c.get("/checklist?project=synth").text
        assert "인용 체크리스트" in page and "🔴 참고문헌에 없음" in page and "🟡 미확인" in page and "<h2>장별</h2>" in page
        assert "🔴 참고문헌에 없음" in c.get("/checklist?project=synth&status=unknown").text
        exported = c.post("/book/export", data={"csrf": csrf, "project_id": "synth"})
        assert exported.status_code == 200 and exported.content[:2] == b"PK"  # docx(zip)
        token = str(exported.url).rsplit("/download/", 1)[1]
        page = c.post("/inbox/delete", data={"csrf": csrf, "name": "원고.docx"}).text
        assert "지움: 원고.docx" in page
    # 링크만으로는 받을 수 없다(로그인 필요), 위조·만료 링크는 거절
    with httpx2.Client(base_url=base, timeout=30) as anon:
        assert anon.get(f"/download/{token}").headers["location"].startswith("/login")
        assert anon.get(f"/download/{token[:-2]}xx").status_code == 410
    log = log_path.read_text(encoding="utf-8")
    assert "물가의 망설임" not in log  # 원고 내용은 로그에 없다


def test_signing_rejects_tampering_and_expiry():
    secret = b"k" * 32
    token = sign({"u": "alice"}, secret, "download", 60)
    assert unsign(token, secret, "download")["u"] == "alice"
    assert unsign(token, secret, "session") is None  # 용도가 다르면 무효
    assert unsign(token, b"x" * 32, "download") is None
    assert unsign(sign({"u": "alice"}, secret, "download", -1), secret, "download") is None


@pytest.fixture
def fake_issuer():
    """가짜 인증 서버: 메타데이터, /authorize(검사만), /token(code → sub의 JWT, PKCE 확인)."""
    state: dict[str, dict] = {}
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(ISSUER_KEY.public_key()))

    class Handler(http.server.BaseHTTPRequestHandler):
        def _json(self, body, status=200):
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("content-type", "application/json")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            path = urllib.parse.urlparse(self.path).path
            if path == "/.well-known/oauth-authorization-server":
                self._json({"issuer": issuer, "authorization_endpoint": f"{issuer}/authorize",
                            "token_endpoint": f"{issuer}/token", "jwks_uri": f"{issuer}/jwks"})
            elif path == "/jwks":
                self._json({"keys": [{**jwk, "kid": "k1", "alg": "RS256", "use": "sig"}]})
            else:
                self._json({}, 404)

        def do_POST(self):
            form = dict(urllib.parse.parse_qsl(self.rfile.read(int(self.headers["content-length"])).decode()))
            pending = state.pop(form.get("code", ""), None)
            challenge = base64.urlsafe_b64encode(hashlib.sha256(form.get("code_verifier", "").encode()).digest()).rstrip(b"=").decode()
            if not pending or pending["challenge"] != challenge or form.get("resource") != pending["resource"]:
                return self._json({"error": "invalid_grant"}, 400)
            now = int(time.time())
            bad = pending.get("bad", {})
            aud = [form["resource"], bad["aud_also"]] if "aud_also" in bad else bad.get("aud", form["resource"])
            claims = {"sub": pending["sub"], "iss": bad.get("iss", issuer), "aud": aud,
                      "iat": now, "exp": now + bad.get("exp_in", 600)}
            token = jwt.encode(claims, bad.get("key", ISSUER_KEY), algorithm="RS256", headers={"kid": "k1"})
            issued.append(token)
            self._json({"access_token": token, "token_type": "Bearer"})

        def log_message(self, *args):
            pass

    issued: list[str] = []
    httpd = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    issuer = f"http://127.0.0.1:{httpd.server_port}"
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield issuer, state, issued
    httpd.shutdown()


def _login(c: httpx2.Client, issuer_state: dict, sub: str, bad: dict | None = None) -> httpx2.Response:
    """브라우저 흉내: /login → 인증 서버로 가는 주소 확인 → 인증 서버가 code를 발급했다고 치고 콜백 호출."""
    to_issuer = c.get("/login?next=/inbox", follow_redirects=False)
    query = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(to_issuer.headers["location"]).query))
    assert query["code_challenge_method"] == "S256" and query["response_type"] == "code" and query["client_id"] == "web-client"
    assert query["resource"].endswith("/mcp") and query["redirect_uri"].endswith("/auth/callback")
    code = f"code-{sub}"
    issuer_state[code] = {"sub": sub, "challenge": query["code_challenge"], "resource": query["resource"], "bad": bad or {}}
    return c.get(f"/auth/callback?code={code}&state={query['state']}", follow_redirects=False)


def test_remote_web_login_with_oauth(server_proc, fake_issuer):
    issuer, issuer_state, _ = fake_issuer
    base, data_dir, _ = server_proc({
        "PUBLIC_URL": "http://127.0.0.1:{port}", "AUTH_ISSUER": issuer, "ALLOWED_USERS": "sub-alice=alice,sub-bob=bob",
        "SESSION_SECRET": "x" * 40, "WEB_CLIENT_ID": "web-client",
    })
    with httpx2.Client(base_url=base, timeout=60) as alice:
        done = _login(alice, issuer_state, "sub-alice")
        assert done.status_code == 303 and done.headers["location"] == "/inbox"
        page = alice.get("/inbox").text
        assert "<span>alice</span>" in page
        csrf = _csrf(page)
        alice.post("/inbox/upload", data={"csrf": csrf}, files={"files": ("원고.docx", (FIXTURES / "닿으려는_종_합성.docx").read_bytes())})
        alice.post("/book/import", data={"csrf": csrf, "name": "원고.docx", "project_id": "synth"})
        exported = alice.post("/book/export", data={"csrf": csrf, "project_id": "synth"}, follow_redirects=False)
        link = exported.headers["location"]
        assert link.startswith("/download/") and alice.get(link).content[:2] == b"PK"
        # 상태(state)가 다르거나 이미 쓴 콜백은 거절
        assert alice.get("/auth/callback?code=x&state=y").status_code == 400
    with httpx2.Client(base_url=base, timeout=60) as bob:
        assert _login(bob, issuer_state, "sub-bob").status_code == 303
        assert "비어 있습니다" in bob.get("/inbox").text  # 앨리스의 받은함이 보이지 않는다
        assert bob.get(link).status_code == 403  # 앨리스의 내려받기 링크
    with httpx2.Client(base_url=base, timeout=60) as carol:
        denied = _login(carol, issuer_state, "sub-carol")
        # 403: 허용 목록 밖. 본인의 사용자 id를 보여 준다(운영자가 ALLOWED_USERS에 넣을 값)
        assert denied.status_code == 403 and "허용 목록에 없습니다(403)" in denied.text
        assert "<code>sub-carol</code>" in denied.text and "받아들이지 못했습니다" not in denied.text
        assert carol.get("/inbox", follow_redirects=False).status_code == 303  # 세션 없음


def test_web_login_rejected_token_is_401_with_reason_in_log(server_proc, fake_issuer):
    """토큰 무효(401)와 허용 목록 밖(403)을 다른 문구로 보인다. 401의 원인은 서버 로그에만, 토큰 값은 남기지 않는다."""
    issuer, issuer_state, issued = fake_issuer
    base, _, log_path = server_proc({
        "PUBLIC_URL": "http://127.0.0.1:{port}", "AUTH_ISSUER": issuer, "ALLOWED_USERS": "sub-alice=alice",
        "SESSION_SECRET": "x" * 40, "WEB_CLIENT_ID": "web-client",
    })
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    cases = {
        'aud 불일치 (토큰 aud=문자열 "web-client"': {"aud": "web-client"},
        # 웹 로그인도 MCP와 같은 검증기다: 자매 서비스(trip_ai) 주소가 섞인 aud는 거부(결정 #79)
        'aud 불일치 (토큰 aud=목록 2개 ["http://127.0.0.1:': {"aud_also": "https://trip-ai.lifebookapplication.com/mcp"},
        'aud 불일치 (토큰 aud=문자열 "https://trip-ai.lifebookapplication.com/mcp"':
            {"aud": "https://trip-ai.lifebookapplication.com/mcp"},
        "iss 불일치 (토큰 iss=https://evil.test": {"iss": "https://evil.test"},
        "만료 (exp=": {"exp_in": -300},
        "서명 (kid=k1, alg=RS256)": {"key": other_key},
    }
    for bad in cases.values():
        with httpx2.Client(base_url=base, timeout=60) as c:
            page = _login(c, issuer_state, "sub-alice", bad)
            assert page.status_code == 401, bad
            assert "로그인 토큰을 받아들이지 못했습니다(401)" in page.text and "허용 목록" not in page.text
            assert c.get("/inbox", follow_redirects=False).status_code == 303  # 세션이 생기지 않았다
    time.sleep(0.3)
    log = log_path.read_text(encoding="utf-8")
    for hint in cases:
        assert f"web login: token rejected ({hint}" in log, hint
    assert len(issued) == len(cases) and not any(token in log for token in issued)  # 토큰 값은 로그에 없다
    assert not any(token.split(".")[2] in log for token in issued)  # 서명 조각도 없다


def test_empty_allow_list_starts_and_denies_everyone(server_proc, fake_issuer):
    # 첫 배포: ALLOWED_USERS를 비워 두고 띄운다 → 로그인하면 403과 함께 자기 id가 보인다 → 그 id를 목록에 넣는다
    issuer, issuer_state, _ = fake_issuer
    base, _, log_path = server_proc({
        "PUBLIC_URL": "http://127.0.0.1:{port}", "AUTH_ISSUER": issuer, "ALLOWED_USERS": "",
        "SESSION_SECRET": "x" * 40, "WEB_CLIENT_ID": "web-client",
    })
    with httpx2.Client(base_url=base, timeout=60) as c:
        page = _login(c, issuer_state, "user_01FIRST")
        assert page.status_code == 403 and "<code>user_01FIRST</code>" in page.text
    assert "ALLOWED_USERS가 비어 있다" in log_path.read_text(encoding="utf-8")


def test_remote_requires_session_secret(tmp_path: Path):
    env = {**os.environ, "DATA_DIR": str(tmp_path / "d"), "PYTHONIOENCODING": "utf-8", "PUBLIC_URL": "https://m.example",
           "AUTH_ISSUER": "https://issuer.test", "ALLOWED_USERS": "a=alice"}
    env.pop("SESSION_SECRET", None)
    proc = subprocess.run([sys.executable, "-m", "magus", "serve", "--transport", "http", "--port", str(_free_port())],
                          env=env, capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert proc.returncode == 2 and "SESSION_SECRET" in proc.stderr


def test_book_import_defaults_follow_whether_a_book_exists(server_proc):
    """책이 없으면 '새 책으로 가져오기'가 기본이고 '수정본'은 비활성. 책이 있으면 '수정본'이 기본. '바꾸기'는 접힌 영역 안."""
    base, _, _ = server_proc({})
    with httpx2.Client(base_url=base, follow_redirects=True, timeout=120) as c:
        empty = c.get("/login?next=/book").text
        assert '<label class="off"><input type="radio" name="mode" value="edition" disabled> <b>수정본으로 올리기</b></label>' in empty
        assert '<input type="radio" name="mode" value="new" checked>' in empty
        assert re.search(r'<details><summary>드물게 쓰는 선택</summary>.*?name="replace".*?</details>', empty, re.S)
        csrf = _csrf(empty)
        c.post("/inbox/upload", data={"csrf": csrf}, files={"files": ("원고.docx", (FIXTURES / "닿으려는_종_합성.docx").read_bytes())})
        c.post("/book/import", data={"csrf": csrf, "name": "원고.docx", "project_id": "synth", "mode": "new"})
        has_book = c.get("/book").text
    assert '<label><input type="radio" name="mode" value="edition" checked>' in has_book
    assert '<input type="radio" name="mode" value="new">' in has_book and 'value="edition" disabled' not in has_book
    assert 'aria-current=page>원고</a>' in has_book  # 지금 보고 있는 메뉴
    # 용어 통일(#85): 저자에게는 확인 요청·수정본·생각으로 보인다
    assert '<th class="num">열린 확인 요청</th><th class="num">수정본·올린 시각</th>' in has_book
    assert "(수정본) 장 제목이 많이 달라도" in has_book and "새 판" not in has_book and "미해결" not in has_book
    assert '<a href="/issues">확인 요청</a>' in has_book and '<a href="/shelf">책장</a>' in has_book  # 생각·문헌·문체는 책장 하나로
    assert "border:1px solid var(--mute)" in has_book and "--input" not in has_book  # 입력칸 테두리 대비 4.75


def _seed_shelf(data_dir: Path) -> None:
    from magus.store import Idea, LocalStore, Passage, Ref, StyleEntry

    store = LocalStore(data_dir)  # 서버와 같은 데이터 폴더에 직접 넣는다(서버는 매 요청 인덱스를 읽는다)
    store.add_ideas("alice", [
        Idea("20261001000000000-aaaaaa", "물가는 궁지다", "thought", "me", "산책", created_at="2026-10-01T05:07:00.000Z"),
        Idea("20261001000000001-aaaaab", "그 관점은 흥미롭습니다", "conversation", "ai", "대화", "20261001000000000-aaaaaa"),
        Idea("20261002000000000-aaaaac", "긴 생각 " + "가" * 400, "thought", "me"),
        *(Idea(f"2026090{n // 100}00000{n:05d}-bbbbbb", f"오래된 생각 {n}", "thought", "me") for n in range(120)),
    ])
    store.put_ref("alice", Ref("clack2012", "verified", {"first_author": "Clack", "authors": "Clack, J. A.", "year": "2012",
                                                         "title": "Gaining ground", "container": "Indiana University Press"}),
                  passages=[Passage("tetrapods came ashore", "1장의 근거", "p.45")])
    store.put_ref("alice", Ref("diamond1997", "unverified", {"first_author": "Diamond", "year": "1997", "title": "Guns"}))
    store.create_project("alice", "책", project_id="b")
    store.write_chapter("alice", "b", 1, "물고기가 올라왔다(Clack, 2012).", "x", title="물가")
    tags = {"호흡": "짧음", "시점": "1인칭", "열기": "장면", "장치": ["반복"], "어미": "-다", "톤": "건조"}
    store.add_style("alice", StyleEntry("20261003000000000-cccccc", "짧다. 끊긴다.", "짧은 호흡", tags, "유홍준"))
    store.add_style("alice", StyleEntry("20261003000000001-cccccd", "물결이 길게 이어지는 문장", "긴 호흡", {**tags, "호흡": "긺", "장치": []}))
    store.close()


def test_shelf_books_and_board_lists(server_proc):
    """책장: 생각·문체·문헌이 책 세 권으로 꽂히고(낭독기 이름 "생각, 항목 N개"), 책을 누르면 게시판형 목록이 열린다.
    한 줄 = 제목(없으면 내용 앞부분을 흐리게) · 작성 시각 · 보조 정보, 누르면 그 자리에서 펼친다(details). 예전 주소는 넘긴다."""
    from magus.ids import local_time

    base, data_dir, _ = server_proc({})
    with httpx2.Client(base_url=base, follow_redirects=True, timeout=120) as c:
        c.get("/login?next=/book")
        empty = {path: c.get(path).text for path in ("/shelf/ideas", "/shelf/refs", "/shelf/styles")}
        assert 'Claude에게 이렇게 말하면 쌓입니다. 예: "생각에 기록해 줘: …"' in empty["/shelf/ideas"]  # 기존 안내 문구 그대로
        assert "아직 등록한 문헌이 없습니다." in empty["/shelf/refs"] and "아직 모은 문장이 없습니다." in empty["/shelf/styles"]
        assert 'aria-label="생각, 항목 0개"' in c.get("/shelf").text
        _seed_shelf(data_dir)

        shelf = c.get("/shelf").text
        for label in ("생각, 항목 123개", "문체, 항목 2개", "문헌, 항목 2개"):
            assert f'aria-label="{label}"' in shelf
        assert 'aria-current=page>책장</a>' in shelf and '<span class="spine-title" aria-hidden="true">생각</span>' in shelf
        assert re.search(r'class="book" href="/shelf/ideas" style="--c:#[0-9a-f]{6};--fg:#[0-9a-f]{6};', shelf)
        for old, new in (("/ideas?author=ai", "/shelf/ideas?author=ai"), ("/refs", "/shelf/refs"), ("/styles?tag=x", "/shelf/styles?tag=x")):
            moved = c.get(old, follow_redirects=False)
            assert moved.status_code == 302 and moved.headers["location"] == new

        ideas = c.get("/shelf/ideas").text
        assert ideas.index("긴 생각") < ideas.index("그 관점은") < ideas.index("물가는 궁지다")  # 최신 것부터
        assert '<span class="t none">물가는 궁지다</span>' in ideas  # 제목이 없으면 내용 앞부분을 흐리게
        when = local_time("2026-10-01T05:07:00.000Z", "%Y-%m-%d %H:%M")
        assert f'<time class="when" datetime="2026-10-01T05:07:00.000Z">{when}</time><span class="aux">나</span>' in ideas
        assert '<span class="aux"><span class="tag">AI</span></span>' in ideas
        assert 'AI의 답입니다. <a href="/shelf/ideas/20261001000000000-aaaaaa">응답한 생각</a>' in ideas
        assert '<a href="/shelf/ideas/20261001000000000-aaaaaa">이 항목의 주소</a>' in ideas
        first = ideas.split('<ol class="board">')[1].split("</summary>")[0]
        assert "가" * 70 in first and "가" * 80 not in first and "가" * 400 in ideas  # 줄에는 앞부분만, 펼치면 전부
        assert "1–100 / 123" in ideas and "다음</a>" in ideas and "오래된 생각 0<" not in ideas
        assert "오래된 생각 0<" in c.get("/shelf/ideas?page=2").text
        only_ai = c.get("/shelf/ideas?author=ai").text
        assert "그 관점은" in only_ai and "물가는 궁지다" not in only_ai

        refs = c.get("/shelf/refs").text
        assert refs.index("Clack(2012) 『Gaining ground』") < refs.index("Diamond(1997)")  # 확인한 문헌부터
        assert "🟢 확인 · 인용된 장 1" in refs and "<p>인용된 장: 제1장</p>" in refs
        assert '<p>「tetrapods came ashore」<br><span class="muted">1장의 근거 · p.45</span></p>' in refs
        assert '인용 현황은 <a href="/checklist?project=b&">인용 체크리스트</a>' in refs
        assert "Gaining ground" not in c.get("/shelf/refs?status=unverified").text
        styles = c.get("/shelf/styles").text
        assert '<a class="tag" href="/shelf/styles?tag=%EC%A7%A7%EC%9D%8C">짧음</a>' in styles and "출처: 유홍준" in styles
        assert '<span class="t">「짧다. 끊긴다.」</span>' in styles
        short = c.get("/shelf/styles?tag=짧음").text
        assert "짧다. 끊긴다." in short and "길게 이어지는" not in short and "태그 「짧음」만" in short

        # 고유 주소: 그 항목이 있는 쪽을 열고, 그 항목을 펼친 채 보인다
        oldest = "2026090000000" + "00000-bbbbbb"  # 오래된 생각 0(둘째 쪽)
        old = c.get(f"/shelf/ideas/{oldest}").text
        assert f'<details id="i-{oldest}" open data-here>' in old and "101–123 / 123" in old
        assert old.count(" open data-here") == 1 and "scrollIntoView" in old
        assert '<details id="i-clack2012" open data-here>' in c.get("/shelf/refs/clack2012").text
        assert c.get("/shelf/ideas/20260101000000000-ffffff").status_code == 404
        assert c.get("/shelf/nothing").status_code == 404
        for page in (refs, styles, shelf):
            assert page.count('method="post"') == 1  # 로그아웃뿐(문체·문헌은 대화로 넣는다)
        assert ideas.count('method="post"') == 2  # 생각에는 바로 적기 폼이 있다(#92)
        assert "<h1>생각</h1>" in ideas and 'aria-current=page>책장</a>' in styles


def test_shelf_search_marks_hits(server_proc):
    """검색(GET ?q=): 두 글자 이상은 FTS(많이 맞은 것부터), 한 글자는 글자 그대로 포함(최근 것부터). 맞은 부분은 <mark>.
    문체는 구절·출처로도, 문헌은 서지로도 찾는다(웹 전용 레인). 책장 전체 검색은 카테고리별로 묶는다."""
    from magus.search import hybrid_search
    from magus.store import Idea, LocalStore

    base, data_dir, _ = server_proc({})
    with httpx2.Client(base_url=base, follow_redirects=True, timeout=120) as c:
        c.get("/login?next=/book")
        _seed_shelf(data_dir)
        store = LocalStore(data_dir)
        store.add_ideas("alice", [Idea("20261004000000000-dddddd", "물고기가 강을 거슬러 오른다", "thought", "me"),
                                  Idea("20261004000000001-dddddd", "<script>alert(1)</script> 꺾쇠 생각", "thought", "me")])
        store.close()
        fish = c.get("/shelf/ideas", params={"q": "물고기"}).text
        assert "<mark>물고기</mark>가 강을 거슬러 오른다" in fish and "물가는 궁지다" not in fish
        assert "「물고기」 찾은 항목 1개 · 많이 맞은 것부터" in fish and 'value="물고기"' in fish
        one = c.get("/shelf/ideas", params={"q": "물"}).text  # 한 글자: 2글자 조각 색인으로는 못 찾는다
        assert "<mark>물</mark>고기가" in one and "<mark>물</mark>가는 궁지다" in one and "한 글자는 그 글자가 들어간" in one
        assert "찾는 말이 들어간 항목이 없습니다." in c.get("/shelf/ideas", params={"q": "없는말"}).text
        assert "<mark>물결</mark>이 길게" in c.get("/shelf/styles", params={"q": "물결"}).text  # 구절
        assert "<mark>유홍준</mark>" in c.get("/shelf/styles", params={"q": "유홍준"}).text  # 출처
        assert "<mark>Gaining</mark> ground" in c.get("/shelf/refs", params={"q": "gaining"}).text  # 서지
        hit = c.get("/shelf/refs", params={"q": "ashore"}).text
        assert re.search(r'<small class="hit">[^<]*tetrapods came <mark>ashore</mark></small>', hit)  # 제목 밖에서 맞으면 맞은 곳 한 줄
        both = c.get("/shelf", params={"q": "물"}).text
        assert re.search(r"<h2>생각 <small>\d+개</small>", both) and "<h2>문체 <small>1개</small></h2>" in both
        assert "찾은 카테고리 2곳" in both and "<h2>문헌" not in both and "찾는 말이 없는 카테고리: 문헌" in both
        evil = c.get("/shelf/ideas", params={"q": "<script>"}).text
        assert "<script>alert" not in evil and "&lt;script&gt;alert(1)&lt;/script&gt;" in c.get("/shelf/ideas").text
        assert 'value="&lt;script&gt;"' in evil
    store = LocalStore(data_dir)
    assert not hybrid_search(store, "alice", "물결", ["style"], 5)  # 문체 자문(style_search)은 여전히 구절을 보지 않는다
    store.close()
