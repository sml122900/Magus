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
    """올린 파일(설정 아래, #94) → 책장에서 원고 책 만들기 → 인용 상태 → docx 내려받기(로그인 필요한 링크)."""
    base, _, log_path = server_proc({})
    with httpx2.Client(base_url=base, follow_redirects=True, timeout=120) as c:
        assert c.get("/me/files", follow_redirects=False).headers["location"].startswith("/login")  # 로그인 전
        assert c.get("/inbox", follow_redirects=False).headers["location"].startswith("/login")
        page = c.get("/login?next=/me/files").text  # 로컬 개발: USER_ID로 바로 로그인
        assert "<h1>올린 파일</h1>" in page and '<p class="empty">파일이 없습니다.</p>' in page
        csrf = _csrf(page)
        assert c.post("/inbox/upload", data={"csrf": "틀림"}, files={"files": ("x.md", b"a")}).status_code == 403
        with (FIXTURES / "닿으려는_종_합성.docx").open("rb") as f:
            data = f.read()
        page = c.post("/inbox/upload", data={"csrf": csrf}, files=[("files", ("원고.docx", data)), ("files", ("나쁜.exe", b"x"))]).text
        assert "올림: 원고.docx" in page and "나쁜.exe: 받을 수 있는 형식은" in page
        made = c.post("/shelf/manuscript", data={"csrf": csrf, "floor": "new"}, files={"file": ("원고.docx", data, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")})
        assert "올렸습니다: 7장" in made.text
        pid = str(made.url).split("/shelf/book/")[1].split("?")[0]
        page = c.get(f"/shelf/book/{pid}?tab=cites").text
        assert "🔴 참고문헌에 없음" in page and "🟡 미확인" in page and "<h2>장별</h2>" in page
        assert "🔴 참고문헌에 없음" in c.get(f"/shelf/book/{pid}?tab=cites&status=unknown").text
        exported = c.post("/book/export", data={"csrf": csrf, "project_id": pid})
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
            elif path == "/.well-known/openid-configuration":
                self._json({"issuer": issuer, "authorization_endpoint": f"{issuer}/authorize", "token_endpoint": f"{issuer}/token",
                            "jwks_uri": f"{issuer}/jwks", "userinfo_endpoint": f"{issuer}/userinfo"})
            elif path == "/jwks":
                self._json({"keys": [{**jwk, "kid": "k1", "alg": "RS256", "use": "sig"}]})
            else:
                self._json({}, 404)

        def do_POST(self):
            if urllib.parse.urlparse(self.path).path == "/userinfo":  # WorkOS처럼 POST + Bearer 액세스 토큰
                token = (self.headers.get("authorization") or "").removeprefix("Bearer ")
                sub = jwt.decode(token, options={"verify_signature": False})["sub"]
                if sub == "sub-liar":  # 토큰과 다른 sub를 돌려주는 경우: 메일을 받아 적지 않아야 한다
                    return self._json({"sub": "sub-someone", "email": "liar@example.com"})
                if sub == "sub-noinfo":  # userinfo가 실패하면 id_token으로
                    return self._json({"error": "server_error"}, 500)
                return self._json({"sub": sub, "email": f"{sub}@example.com", "email_verified": True})
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
            id_claims = {"sub": pending["sub"], "iss": issuer, "aud": bad.get("id_aud", form.get("client_id")), "iat": now,
                         "exp": now + 600, "email": f"{pending['sub']}@id.example.com", "email_verified": True}
            id_token = jwt.encode(id_claims, ISSUER_KEY, algorithm="RS256", headers={"kid": "k1"})
            self._json({"access_token": token, "token_type": "Bearer", "id_token": id_token})

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
        page = alice.get("/me/files").text
        assert '<a href="/me" class="me" aria-label="내 정보, sub-alice@example.com">sub-alice@example.com</a>' in page
        csrf = _csrf(page)
        alice.post("/inbox/upload", data={"csrf": csrf}, files={"files": ("원고.docx", (FIXTURES / "닿으려는_종_합성.docx").read_bytes())})
        made = alice.post("/shelf/manuscript", data={"csrf": csrf, "floor": "new"},  # 원고 책은 책장에서(#94)
                          files={"file": ("원고.docx", (FIXTURES / "닿으려는_종_합성.docx").read_bytes(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}, follow_redirects=False)
        pid = made.headers["location"].split("/shelf/book/")[1].split("?")[0]
        exported = alice.post("/book/export", data={"csrf": csrf, "project_id": pid}, follow_redirects=False)
        link = exported.headers["location"]
        assert link.startswith("/download/") and alice.get(link).content[:2] == b"PK"
        # 상태(state)가 다르거나 이미 쓴 콜백은 거절
        assert alice.get("/auth/callback?code=x&state=y").status_code == 400
    with httpx2.Client(base_url=base, timeout=60) as bob:
        assert _login(bob, issuer_state, "sub-bob").status_code == 303
        assert '<p class="empty">파일이 없습니다.</p>' in bob.get("/me/files").text  # 앨리스가 올린 파일이 보이지 않는다
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


def test_new_book_replaces_add_book(server_proc):
    """책장에는 책 목록과 '새 책' 하나(2026-10-09). 옛 '책 추가'(새 책·문서 올리기 두 칸) 주소는 같은 자리의 새 책으로 넘기고,
    새 책 화면 위에는 위치 표시(프로젝트 › 「프로젝트」 › 노드). 문서는 게시판 첨부로, 새 프로젝트는 프로젝트 목록의 '+ 프로젝트'로."""
    from magus.store import LocalStore

    base, data_dir, _ = server_proc({})
    store = LocalStore(data_dir)
    store.create_project("alice", "빈 책", project_id="empty")
    store.create_project("alice", "있는 책", project_id="full")
    store.write_chapter("alice", "full", 1, "본문.", "x", title="하나")
    store.close()
    with httpx2.Client(base_url=base, follow_redirects=True, timeout=120) as c:
        c.get("/login?next=/shelf")
        empty = c.get("/shelf/add?project=empty&node=center")
        assert str(empty.url).endswith("/shelf/new?project=empty&node=center")
        empty = empty.text
        assert re.search(r'<nav class="trail" aria-label="위치"><a href="/shelf">프로젝트</a>.*?<a href="/shelf/p/empty">빈 책</a>'
                         r'.*?<a href="/shelf/p/empty\?node=center">가운데</a></nav>', empty)
        assert 'action="/shelf/new?project=empty&amp;node=center"' in empty and 'type="file"' not in empty and "문서 올리기" not in empty
        assert str(c.get("/shelf/add?floor=empty").url).endswith("/shelf/new?floor=empty")  # 옛 주소 이름(floor)도 받는다
        common = c.get("/shelf/new?project=common").text
        assert '<a href="/shelf/p/common">내 서재</a>' in common and 'type="file"' not in common
        assert c.get("/shelf/add?project=nothing").status_code == 404 and c.get("/shelf/new?project=nothing").status_code == 404
        assert c.get("/book", follow_redirects=False).headers["location"] == "/shelf/book/full?tab=chapters"
    assert "aria-current=page>프로젝트</a>" in empty  # 메뉴는 프로젝트 하나(#95)
    assert "border:1px solid var(--mute)" in empty and "--input" not in empty  # 입력칸 테두리 대비 4.75
    for word in ("새 판", "미해결", "받은함", "인용 체크리스트", "층", "공용", "원고 책", "모음 책", "문서 책", "카테고리"):  # #96: 종류 이름도
        assert word not in empty and word not in common


def _seed_shelf(data_dir: Path) -> None:
    """옛 기본 책 셋을 이전한 모양(#96): 「내 서재」에 생각·문체·문헌 책(<종류>-common, 컨텍스트 생각 메모·문체·논문)."""
    from magus.contexts import Context
    from magus.store import CategoryItem, LocalStore, Passage, Ref

    store = LocalStore(data_dir)  # 서버와 같은 데이터 폴더에 직접 넣는다(서버는 매 요청 인덱스를 읽는다)
    saved = {c.name: c for c in store.list_saved_contexts("alice")}
    for book, name, context in (("ideas-common", "생각", "생각 메모"), ("styles-common", "문체", "문체"), ("refs-common", "문헌", "논문")):
        store.create_category("alice", name, "blank", "#1f2f5c", (), "common", category_id=book,
                              contexts=(Context(saved[context].name, saved[context].text),))
    for item in (
        CategoryItem("20261001000000000-aaaaaa", "ideas-common", "물가는 궁지다", "me", origin="산책", created_at="2026-10-01T05:07:00.000Z"),
        CategoryItem("20261001000000001-aaaaab", "ideas-common", "그 관점은 흥미롭습니다", "ai", origin="대화",
                     parent_id="20261001000000000-aaaaaa", created_at="2026-10-01T06:00:00.000Z"),
        CategoryItem("20261002000000000-aaaaac", "ideas-common", "긴 생각 " + "가" * 400, "me", created_at="2026-10-02T00:00:00.000Z"),
        *(CategoryItem(f"2026090{n // 100}00000{n:05d}-bbbbbb", "ideas-common", f"오래된 생각 {n}", "me",
                       created_at=f"2026-09-0{1 + n // 100}T00:{n // 60:02d}:{n % 60:02d}.000Z") for n in range(120)),
    ):
        store.put_category_item("alice", item)
    store.put_ref("alice", Ref("clack2012", "verified", {"first_author": "Clack", "authors": "Clack, J. A.", "year": "2012",
                                                         "title": "Gaining ground", "container": "Indiana University Press"},
                               book="refs-common"),
                  passages=[Passage("tetrapods came ashore", "1장의 근거", "p.45")])
    store.put_ref("alice", Ref("diamond1997", "unverified", {"first_author": "Diamond", "year": "1997", "title": "Guns"}, book="refs-common"))
    store.create_project("alice", "책", project_id="b")
    store.write_chapter("alice", "b", 1, "물고기가 올라왔다(Clack, 2012).", "x", title="물가")
    store.put_category_item("alice", CategoryItem("20261003000000000-cccccc", "styles-common", "짧다. 끊긴다.", "me", reason="짧은 호흡",
                                                  where="유홍준", tags=("호흡: 짧음", "장치: 반복"), tags_by="ai",
                                                  created_at="2026-10-03T00:00:00.000Z"))
    store.put_category_item("alice", CategoryItem("20261003000000001-cccccd", "styles-common", "물결이 길게 이어지는 문장", "me",
                                                  reason="긴 호흡", tags=("호흡: 긺",), created_at="2026-10-03T00:00:01.000Z"))
    store.close()


def test_shelf_books_and_board_lists(server_proc):
    """책장: 책이 노드에 꽂히고(낭독기 이름 "생각, 컨텍스트 생각 메모, 글 N개", 위 띠 = 컨텍스트 이름), 책을 누르면 게시판 페이지
    (2026-10-09). 한 줄 = 제목(없으면 내용 앞부분을 흐리게) · 첨부 표시 · 날짜, 최신 글이 위, 20개씩. 누르면 글 보기 페이지.
    글과 그 책의 문헌 글이 한 게시판에. 이유·위치·태그·원문 확인 표시는 파일에 그대로 있고 보이지 않는다. 예전 주소는 넘긴다."""
    from magus.ids import local_time

    base, data_dir, _ = server_proc({})
    with httpx2.Client(base_url=base, follow_redirects=True, timeout=120) as c:
        c.get("/login?next=/book")
        assert c.get("/shelf/ideas").status_code == 404  # 옛 기본 책 주소: 이전으로 생긴 책이 없으면 없다
        _seed_shelf(data_dir)

        # 노드를 열면 그 노드의 책장(정면 2D)
        for node, label in (("b-ideas-common", "생각, 컨텍스트 생각 메모, 글 123개"), ("b-styles-common", "문체, 컨텍스트 문체, 글 2개"),
                            ("b-refs-common", "문헌, 컨텍스트 논문, 원문 확인 1편, 전체 2개")):
            assert f'aria-label="{label}"' in c.get("/shelf/p/common", params={"node": node}).text
        shelf = c.get("/shelf").text  # 첫 화면은 프로젝트 목록
        assert 'aria-current=page>프로젝트</a>' in shelf and '<span class="pname">내 서재</span>' in shelf
        floor = c.get("/shelf/floor/common")  # 옛 층 주소 → 그 프로젝트 지도
        assert str(floor.url).endswith("/shelf/p/common") and 'data-node="b-ideas-common"' in floor.text
        panel = c.get("/shelf/p/common", params={"node": "b-ideas-common"}).text  # 책등의 색과 글자색, 위 띠 = 컨텍스트 이름
        assert re.search(r'href="/shelf/ideas-common" style="--c:#[0-9a-f]{6};--fg:#[0-9a-f]{6};', panel)
        assert '<span class="band top" aria-hidden="true">생각 메모</span>' in panel
        for old, new in (("/ideas?author=ai", "/shelf/ideas?author=ai"), ("/refs", "/shelf/refs"), ("/styles?tag=x", "/shelf/styles?tag=x")):
            moved = c.get(old, follow_redirects=False)
            assert moved.status_code == 302 and moved.headers["location"] == new

        ideas = c.get("/shelf/ideas").text  # 옛 주소 → 이전으로 생긴 책
        assert '<details class="ctx">' not in ideas  # 컨텍스트는 책 설정 안에서만(2026-10-09)
        assert '<details class="ctx"><summary>생각 메모</summary><p>떠오른 생각을 적어 둔 메모다.' in c.get("/shelf/edit/ideas-common").text
        assert '<nav class="trail" aria-label="위치">' in ideas and '<span aria-current="page">생각</span></nav>' in ideas
        assert ideas.index("긴 생각") < ideas.index("그 관점은") < ideas.index("물가는 궁지다")  # 최신 것부터
        assert '<a class="post" href="/shelf/ideas-common/20261001000000000-aaaaaa"><span class="pt none">물가는 궁지다</span>' in ideas
        when = local_time("2026-10-01T05:07:00.000Z", "%Y-%m-%d %H:%M")
        assert f'<time class="pd" datetime="2026-10-01T05:07:00.000Z">{when}</time>' in ideas
        assert '<span class="pt none">그 관점은 흥미롭습니다<span class="tag" title="AI가 쓴 글">AI</span></span>' in ideas
        first = ideas.split('<ol class="posts">')[1].split("</a>")[0]
        assert "가" * 75 in first and "가" * 76 not in first  # 줄에는 앞부분만
        assert "가" * 400 in c.get("/shelf/ideas-common/20261002000000000-aaaaac").text  # 글 보기에는 전부
        assert ideas.count('<a class="post"') == 20 and '<nav class="pages" aria-label="쪽">' in ideas and "오래된 생각 0<" not in ideas
        assert "오래된 생각 0<" in c.get("/shelf/ideas-common?page=7").text
        only_ai = c.get("/shelf/ideas-common?author=ai").text
        assert "그 관점은" in only_ai and "물가는 궁지다" not in only_ai

        refs = c.get("/shelf/refs").text
        listed = refs.split('<ol class="posts">')[1]
        assert "Clack(2012) 『Gaining ground』" in listed and "Diamond(1997)" in listed
        assert "/check" not in refs and 'type="checkbox"' not in refs and "원문 확인</span>" not in listed  # 웹에서 원문 확인 체크·표시는 뺐다
        assert "status=verified" not in refs and "인용 상태</a>" not in refs and '<p class="sum">글 2</p>' in refs
        clack = c.get("/shelf/refs/clack2012")  # 옛 주소 → 그 문헌 글 보기
        assert str(clack.url).endswith("/shelf/refs-common/clack2012") and "<h1>Clack(2012) 『Gaining ground』</h1>" in clack.text
        assert '<blockquote>「tetrapods came ashore」</blockquote>' in clack.text and "1장의 근거" not in clack.text
        styles = c.get("/shelf/styles").text
        assert "유홍준" not in styles and "짧은 호흡" not in styles and '<span class="pt none">짧다. 끊긴다.</span>' in styles
        post = c.get("/shelf/styles-common/20261003000000000-cccccc").text
        assert "<p>짧다. 끊긴다.</p>" in post and "유홍준" not in post and "짧은 호흡" not in post and "호흡: 짧음" not in post
        short = c.get("/shelf/styles-common?tag=호흡: 짧음").text  # 태그 거르기는 주소로 그대로 된다(태그는 파일에 그대로)
        assert "짧다. 끊긴다." in short and "길게 이어지는" not in short and '<span class="tag">호흡: 짧음</span>' in short

        oldest = "2026090000000" + "00000-bbbbbb"  # 오래된 생각 0
        old = c.get(f"/shelf/ideas/{oldest}")  # 옛 고유 주소 → 그 글 보기 페이지
        assert str(old.url).endswith(f"/shelf/ideas-common/{oldest}") and "<h1>오래된 생각 0</h1>" in old.text
        assert c.get("/shelf/ideas/20260101000000000-ffffff").status_code == 404
        assert c.get("/shelf/nothing").status_code == 404
        for page in (styles, ideas, refs):  # 로그아웃과 줄마다 스크랩(☆)만(찾기는 GET, 글쓰기는 별도 페이지)
            assert page.count('method="post"') - page.count('<form class="star"') == 1
        assert shelf.count('method="post"') == 3  # 로그아웃 · 끌어 옮기기(숨은 폼) · 새 프로젝트 만들기
        assert "<h1>생각</h1>" in ideas and 'aria-current=page>프로젝트</a>' in styles


def test_shelf_search_marks_hits(server_proc):
    """검색(GET ?q=): 두 글자 이상은 FTS(많이 맞은 것부터), 한 글자는 글자 그대로 포함(최근 것부터). 맞은 부분은 <mark>.
    글은 본문·이유·위치로, 문헌 글은 서지·쓸 부분으로도 찾는다. 전체 검색은 프로젝트 → 노드 · 책으로 묶는다."""
    from magus.search import hybrid_search
    from magus.store import CategoryItem, LocalStore

    base, data_dir, _ = server_proc({})
    with httpx2.Client(base_url=base, follow_redirects=True, timeout=120) as c:
        c.get("/login?next=/book")
        _seed_shelf(data_dir)
        store = LocalStore(data_dir)
        store.put_category_item("alice", CategoryItem("20261004000000000-dddddd", "ideas-common", "물고기가 강을 거슬러 오른다", "me"))
        store.put_category_item("alice", CategoryItem("20261004000000001-dddddd", "ideas-common", "<script>alert(1)</script> 꺾쇠 생각", "me"))
        store.close()
        fish = c.get("/shelf/ideas-common", params={"q": "물고기"}).text
        assert "<mark>물고기</mark>가 강을 거슬러 오른다" in fish and "물가는 궁지다" not in fish
        assert "「물고기」 1 · " in fish and 'value="물고기"' in fish
        one = c.get("/shelf/ideas-common", params={"q": "물"}).text  # 한 글자: 2글자 조각 색인으로는 못 찾는다
        assert "<mark>물</mark>고기가" in one and "<mark>물</mark>가는 궁지다" in one
        assert '<p class="msg">없음</p>' in c.get("/shelf/ideas-common", params={"q": "없는말"}).text
        assert "<mark>물결</mark>이 길게" in c.get("/shelf/styles-common", params={"q": "물결"}).text  # 본문(구절)
        assert "<mark>유홍준</mark>" in c.get("/shelf/styles-common", params={"q": "유홍준"}).text  # 위치(출전)
        assert "<mark>Gaining</mark> ground" in c.get("/shelf/refs-common", params={"q": "gaining"}).text  # 서지
        hit = c.get("/shelf/refs-common", params={"q": "ashore"}).text
        assert re.search(r'<small class="hit">[^<]*tetrapods came <mark>ashore</mark></small>', hit)  # 제목 밖에서 맞으면 맞은 곳 한 줄
        both = c.get("/shelf", params={"q": "물"}).text  # 프로젝트 → 노드 · 책으로 묶는다(#95). 책 옆에 컨텍스트 이름(#96)
        assert re.search(r'<a href="/shelf/ideas-common">생각</a> <small>생각 메모 · \d+개</small>', both)  # 누르면 그 책의 게시판
        assert '<a href="/shelf/styles-common">문체</a> <small>문체 · 1개</small>' in both
        assert "<p>「물」 1</p>" in both and ">문헌</a>" not in both and '<h2><a href="/shelf/p/common">내 서재</a>' in both
        evil = c.get("/shelf/ideas-common", params={"q": "<script>"}).text
        assert "<script>alert" not in evil and "&lt;script&gt;alert(1)&lt;/script&gt;" in c.get("/shelf/ideas-common").text
        assert 'value="&lt;script&gt;"' in evil
    store = LocalStore(data_dir)
    assert hybrid_search(store, "alice", "물결", ["category"], 5)  # #96: 도구 찾기(category_search)도 글의 본문을 본다


def test_display_name_from_email_and_editable(server_proc, fake_issuer):
    """상단 바 이름: 처음에는 가입 메일(웹 로그인 때 userinfo), 내 정보에서 표시 이름으로 바꾸고, 비우면 다시 메일.
    메일·표시 이름은 로그에 남지 않고, 사용자마다 따로다."""
    issuer, issuer_state, _ = fake_issuer
    base, data_dir, log_path = server_proc({
        "PUBLIC_URL": "http://127.0.0.1:{port}", "AUTH_ISSUER": issuer,
        "ALLOWED_USERS": "sub-alice=alice,sub-bob=bob,sub-liar=liar,sub-noinfo=noinfo",
        "SESSION_SECRET": "x" * 40, "WEB_CLIENT_ID": "web-client",
    })
    with httpx2.Client(base_url=base, timeout=120) as alice, httpx2.Client(base_url=base, timeout=120) as bob:
        _login(alice, issuer_state, "sub-alice")
        _login(bob, issuer_state, "sub-bob")
        me = alice.get("/me").text
        assert "<h1>내 정보</h1>" in me and "<p>메일 sub-alice@example.com</p>" in me and 'name="display_name" value=""' in me
        csrf = _csrf(me)
        assert alice.post("/me", data={"csrf": "틀림", "display_name": "x"}).status_code == 403
        too_long = alice.post("/me", data={"csrf": csrf, "display_name": "가" * 41})
        assert too_long.status_code == 400 and "표시 이름은 40자까지입니다. 지금 41자" in too_long.text
        saved = alice.post("/me", data={"csrf": csrf, "display_name": "  <b>표시명시험</b>  교수 "}, follow_redirects=True).text
        assert "저장했습니다." in saved and ">&lt;b&gt;표시명시험&lt;/b&gt; 교수</a>" in saved and "<b>표시명시험" not in saved
        assert ">sub-bob@example.com</a>" in bob.get("/shelf").text  # 밥의 상단 바는 밥의 것
        bob_csrf = _csrf(bob.get("/me").text)
        bob.post("/me", data={"csrf": bob_csrf, "display_name": "밥"})
        assert ">&lt;b&gt;표시명시험&lt;/b&gt; 교수</a>" in alice.get("/shelf").text  # 밥이 바꿔도 앨리스 것은 그대로
        cleared = alice.post("/me", data={"csrf": csrf, "display_name": "   "}, follow_redirects=True).text
        assert ">sub-alice@example.com</a>" in cleared  # 비우면 다시 메일
    with httpx2.Client(base_url=base, timeout=120) as liar:
        _login(liar, issuer_state, "sub-liar", {"id_aud": "다른-클라이언트"})
        assert ">liar</a>" in liar.get("/shelf").text  # userinfo의 sub가 다르고 id_token의 aud도 틀리면 메일을 적지 않는다
    with httpx2.Client(base_url=base, timeout=120) as noinfo:
        _login(noinfo, issuer_state, "sub-noinfo")
        assert ">sub-noinfo@id.example.com</a>" in noinfo.get("/shelf").text  # userinfo가 실패하면 검증한 id_token의 메일
    profile = json.loads((data_dir / "users" / "alice" / "profile.json").read_text(encoding="utf-8"))
    assert profile["email"] == "sub-alice@example.com" and "display_name" not in profile and profile["schema_version"] == 1
    assert json.loads((data_dir / "users" / "bob" / "profile.json").read_text(encoding="utf-8"))["display_name"] == "밥"
    assert not (data_dir / "users" / "liar" / "profile.json").exists()
    time.sleep(0.3)
    log = log_path.read_text(encoding="utf-8")
    assert "web login profile: email=yes via=userinfo" in log and "web login profile: email=yes via=id_token" in log
    assert "web login profile: email=no via=- (sub-mismatch; id_token=invalid)" in log  # 이유 코드만
    for secret in ("sub-alice@example.com", "liar@example.com", "sub-noinfo@id.example.com", "sub-liar@id.example.com", "표시명시험", "교수"):
        assert secret not in log  # 메일과 표시 이름은 로그에 없다(#52)


def test_local_mode_shows_internal_name_and_me_page(server_proc):
    base, _, _ = server_proc({})
    with httpx2.Client(base_url=base, follow_redirects=True, timeout=120) as c:
        page = c.get("/login?next=/me").text
        assert ">alice</a>" in page and "<p>메일 —</p>" in page
