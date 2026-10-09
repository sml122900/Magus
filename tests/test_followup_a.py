"""코드 점검 후속 A(2026-10-09): '바로 할 수 있는 것' 항목별 시험. 항목 번호는 docs/audit/2026-10-09-code-audit.md."""

from __future__ import annotations

import pytest
from mcp import Client
from test_web import server_proc  # noqa: F401 - 픽스처

from magus.config import Settings
from magus.server import build_server
from magus.store import LocalStore

pytestmark = pytest.mark.anyio
RANGE = "장 번호는 0~9,999입니다(0은 서장)."


# ---- 15-2 읽기 도구의 장 번호 범위 ----

async def test_read_tools_check_chapter_range(store: LocalStore, settings: Settings):
    store.create_project("alice", "책", project_id="b")
    store.write_chapter("alice", "b", 1, "본문", "x", title="하나")
    async with Client(build_server(settings, store)) as c:
        for name, args in [("book_read_chapter", {"number": 2**63}), ("book_read_chapter", {"number": -1}),
                           ("book_issues", {"chapter_number": 2**63}), ("ref_check", {"chapter_number": 10_000}),
                           ("book_issue_add", {"text": "x", "chapter_number": 2**63})]:
            r = await c.call_tool(name, {**args, "project_id": "b"})
            text = r.content[0].text  # 후속 B부터 스키마(0~9999)가 입구에서 먼저 거절한다. 서버 검사는 그대로 둔다
            assert r.is_error and (RANGE in text or "less than or equal to 9999" in text or "greater than or equal to 0" in text), (name, text)
        ok = await c.call_tool("book_read_chapter", {"number": 1, "project_id": "b"})
        assert not ok.is_error
    assert store.read_chapter("alice", "b", 2**63) is None and store.list_issues("alice", "b", None, chapter_number=2**63) == []


# ---- 13-b 연결 노드 되살리기 뒤 인용 수 ----

def _unverified(store: LocalStore) -> int:
    import re

    from magus.book.outline import build_outline

    return int(re.search(r"미확인 문헌 (\d+)편", build_outline(store, "alice", "book")).group(1))


async def test_restoring_link_node_recounts(store: LocalStore, settings: Settings):
    from pathlib import Path

    from magus.book.importer import import_manuscript
    from magus.category.moves import restore_node, trash_node_with_books

    import_manuscript(store, "alice", Path(__file__).parent / "fixtures" / "synthetic" / "닿으려는_종_합성.docx", project_id="book",
                      synthetic=True)
    async with Client(build_server(settings, store)) as c:
        await c.call_tool("category_create", {"name": "읽은 논문", "project": "내 서재"})
        r = await c.call_tool("category_put", {"book": "읽은 논문", "project": "내 서재", "author": "me", "source": {"key": "clack2012"},
                                               "checked": True, "parts": [{"text": "네발동물 대목", "reason": "근거"}]})
        assert not r.is_error, r.content[0].text
    shared = _unverified(store)
    link = next(n for n in store.get_map("alice", "book").nodes if n.link)
    trash_node_with_books(store, "alice", "book", link.id, "시험")
    assert _unverified(store) == shared + 1  # 연결 노드가 없으면 clack2012가 이 원고에서 미확인으로
    restore_node(store, "alice", f"book/{link.id}")
    assert _unverified(store) == shared  # 전에는 다음 문헌 변경·재시작까지 shared + 1이 남았다


# ---- 15-3 대화 기록이 Word·PDF·UTF-8 아님 ----

async def test_conversation_rejects_word_and_bad_encoding(store: LocalStore, settings: Settings):
    from pathlib import Path

    store.create_category("alice", "대화", "blank", "#1f2f5c", (), "common", category_id="talk")
    inbox = store.root / "users" / "alice" / "inbox"
    inbox.mkdir(parents=True)
    synth = Path(__file__).parent / "fixtures" / "synthetic"
    (inbox / "기록.docx").write_bytes((synth / "닿으려는_종_합성.docx").read_bytes())
    (inbox / "기록.pdf").write_bytes((synth / "닿으려는_종_합성.pdf").read_bytes())
    (inbox / "옛기록.txt").write_bytes("**사용자:** 안녕\n**Claude:** 네\n".encode("cp949"))
    (inbox / "기록.md").write_text("**사용자:** 안녕\n\n**Claude:** 네\n", encoding="utf-8")
    async with Client(build_server(settings, store)) as c:
        for name in ("기록.docx", "기록.pdf"):
            r = await c.call_tool("idea_add_conversation", {"book": "대화", "path": name})
            assert r.is_error and "대화 기록은 .md·.txt 파일만 받는다" in r.content[0].text, r.content[0].text
        r = await c.call_tool("idea_add_conversation", {"book": "대화", "path": "옛기록.txt"})
        assert r.is_error and "UTF-8 글자로 읽지 못했다" in r.content[0].text
        ok = await c.call_tool("idea_add_conversation", {"book": "대화", "path": "기록.md"})
        assert not ok.is_error and "발화 2개" in ok.content[0].text


# ---- 7-b 첨부 docx 글자 뽑기: 낱말(w:t) 단위로 모으고 버림 ----

def _docx(path, body: str):
    import zipfile

    w = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", f'<?xml version="1.0"?><w:document {w}><w:body>{body}</w:body></w:document>')
    return path


def test_docx_text_streams_by_run(tmp_path):
    import random
    import string
    import time

    from magus.extract import TEXT_MAX, extract

    small = _docx(tmp_path / "a.docx", "<w:p><w:pPr/><w:r><w:t>첫 </w:t></w:r><w:r><w:t>문단</w:t><w:tab/><w:t>탭</w:t></w:r></w:p>"
                  "<w:tbl><w:tr><w:tc><w:p><w:r><w:t>칸</w:t><w:br/><w:t>둘째 줄</w:t></w:r></w:p></w:tc></w:tr></w:tbl>"
                  "<w:p><w:hyperlink><w:r><w:t>링크</w:t></w:r></w:hyperlink></w:p>")
    assert extract(small).text == "첫 문단\t탭\n칸\n둘째 줄\n링크\n"
    rnd = random.Random(7)
    runs = "".join(f"<w:r><w:t>{''.join(rnd.choices(string.ascii_letters, k=8))}</w:t></w:r>" for _ in range(200_000))
    one = _docx(tmp_path / "one.docx", f"<w:p>{runs}</w:p>")  # 문단 하나에 run 20만 개(160만 자)
    started = time.monotonic()
    got = extract(one)
    assert got.status == "truncated" and len(got.text) == TEXT_MAX and time.monotonic() - started < 2


# ---- 7-d 깨진 원고 올리기 → 500 대신 안내, CSRF만 403 ----

def _broken_files(tmp_path):
    import zipfile

    no_body = tmp_path / "본문없음.docx"
    with zipfile.ZipFile(no_body, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
    bad_xml = tmp_path / "깨진XML.docx"
    with zipfile.ZipFile(bad_xml, "w") as z:
        z.writestr("word/document.xml", "<w:document><w:body><w:p>")
    return {"zip아님.docx": b"this is not a zip", no_body.name: no_body.read_bytes(), bad_xml.name: bad_xml.read_bytes(),
            "깨진.pdf": b"%PDF-1.7\n%broken\n"}


def test_broken_manuscript_upload_is_400(server_proc, tmp_path):  # noqa: F811
    import httpx2
    from test_web import _csrf

    from magus.book.importer import UNREADABLE

    base, _, log = server_proc({})
    with httpx2.Client(base_url=base, follow_redirects=True, timeout=60) as c:
        csrf = _csrf(c.get("/login?next=/shelf").text)
        for name, data in _broken_files(tmp_path).items():
            r = c.post("/shelf/manuscript", data={"csrf": csrf, "project": "new"}, files={"file": (name, data, "application/octet-stream")})
            assert r.status_code == 400 and UNREADABLE in r.text, (name, r.status_code)
        wrong = c.post("/shelf/manuscript", data={"csrf": "틀림", "project": "new"},
                       files={"file": ("a.docx", b"x", "application/octet-stream")})
        assert wrong.status_code == 403 and "잘못된 요청입니다." in wrong.text
    assert "Traceback" not in log.read_text(encoding="utf-8") and " ERROR " not in log.read_text(encoding="utf-8")


async def test_broken_manuscript_book_import(store: LocalStore, settings: Settings, tmp_path):
    from magus.book.importer import UNREADABLE

    inbox = store.root / "users" / "alice" / "inbox"
    inbox.mkdir(parents=True)
    for name, data in _broken_files(tmp_path).items():
        (inbox / name).write_bytes(data)
    async with Client(build_server(settings, store)) as c:
        for name in _broken_files(tmp_path):
            r = await c.call_tool("book_import", {"path": name, "project_id": "x"})
            assert r.is_error and UNREADABLE in r.content[0].text, (name, r.content[0].text)


# ---- 1-8·1-10 JWKS: 뺀 키는 묶음을 다시 읽으면 무효, 조회가 이벤트 루프를 막지 않음 ----

@pytest.fixture
def jwks_server():
    """바꿀 수 있는 JWKS 흉내: state["keys"]·state["delay"]."""
    import http.server
    import json
    import threading
    import time

    state = {"keys": [], "delay": 0.0, "hits": 0}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            state["hits"] += 1
            time.sleep(state["delay"])
            body = json.dumps({"keys": state["keys"]}).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_port}/jwks", state
    httpd.shutdown()


def _rsa(kid: str):
    import json

    import jwt
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key, {**json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key())), "kid": kid, "use": "sig", "alg": "RS256"}


def _signed(key, kid: str) -> str:
    import time

    import jwt

    now = int(time.time())
    return jwt.encode({"sub": "sub-alice", "aud": "http://magus.test/mcp", "iss": "https://issuer.test", "iat": now, "exp": now + 600},
                      key, algorithm="RS256", headers={"kid": kid})


def _verifier(url: str):
    from magus.auth import AuthConfig, JwtVerifier

    config = AuthConfig.from_env({"AUTH_ISSUER": "https://issuer.test", "PUBLIC_URL": "http://magus.test", "ALLOWED_USERS": "sub-alice=alice",
                                  "AUTH_JWKS_URL": url})
    return JwtVerifier(config)


async def test_removed_key_stops_working(jwks_server, monkeypatch: pytest.MonkeyPatch):
    import time

    from magus import auth

    url, state = jwks_server
    k1, jwk1 = _rsa("k1")
    k2, jwk2 = _rsa("k2")
    state["keys"] = [jwk1]
    monkeypatch.setattr(auth, "JWKS_LIFESPAN", 1)
    v = _verifier(url)
    assert await v.verify_token(_signed(k1, "k1")) is not None
    state["keys"] = [jwk2]  # 인증 서버가 k1을 뺐다
    time.sleep(1.2)  # 묶음 수명이 지남
    assert await v.verify_token(_signed(k2, "k2")) is not None
    assert await v.verify_token(_signed(k1, "k1")) is None  # 전에는 키 캐시(lru_cache) 때문에 새로 서명한 k1 토큰도 통과했다


async def test_jwks_fetch_does_not_block_event_loop(jwks_server):
    import time

    import anyio

    url, state = jwks_server
    k1, jwk1 = _rsa("k1")
    state["keys"], state["delay"] = [jwk1], 1.5
    v = _verifier(url)
    lags: list[float] = []

    async def ticker():
        for _ in range(10):
            started = time.monotonic()
            await anyio.sleep(0.05)
            lags.append(time.monotonic() - started)

    async with anyio.create_task_group() as tg:
        tg.start_soon(ticker)
        await anyio.sleep(0.02)  # 티커가 먼저 잠들어 있는 동안 검증한다
        assert await v.verify_token(_signed(k1, "k1")) is not None  # JWKS가 1.5초 늦다
    assert max(lags) < 0.5, lags  # 전에는 검증 동안 이벤트 루프가 멈춰 다른 요청(/healthz)도 기다렸다


# ---- 3-4·4-4 세션 없는 로그아웃, 올린 파일 지우기 이름 검사 ----

def test_logout_without_session_and_inbox_delete_name(server_proc):  # noqa: F811
    import httpx2
    from test_web import _csrf

    base, data_dir, _ = server_proc({})
    with httpx2.Client(base_url=base, follow_redirects=False, timeout=60) as c:
        r = c.post("/logout", data={"csrf": "다른 사이트"})
        assert r.status_code == 303 and r.headers["location"] == "/login" and "set-cookie" not in r.headers  # 쿠키를 지우지 않는다
        c.get("/login?next=/me/files")
        csrf = _csrf(c.get("/me/files").text)
        inbox = data_dir / "users" / "alice" / "inbox"
        inbox.mkdir(parents=True, exist_ok=True)
        (inbox / "secret.txt").write_text("x", encoding="utf-8")
        for bad in ("secret.txt:zone", "../secret.txt", ".secret.txt"):
            assert c.post("/inbox/delete", data={"csrf": csrf, "name": bad}).status_code == 403, bad
        assert (inbox / "secret.txt").exists()
        ok = c.post("/inbox/delete", data={"csrf": csrf, "name": "secret.txt"}, follow_redirects=True)
        assert ok.status_code == 200 and not (inbox / "secret.txt").exists()
        out = c.post("/logout", data={"csrf": csrf})
        assert out.status_code == 200 and "magus_session" in out.headers.get("set-cookie", "")  # 세션이 있으면 지운다


# ---- 3-5 로컬 모드 Host 허용 목록 ----

def test_local_mode_refuses_foreign_host(server_proc):  # noqa: F811
    import httpx2

    from magus.transports import host_of

    assert [host_of(h) for h in ("127.0.0.1:8000", "[::1]:8000", "localhost", "evil.example:80", "[::1]")] == [
        "127.0.0.1", "::1", "localhost", "evil.example", "::1"]
    base, _, _ = server_proc({})
    with httpx2.Client(base_url=base, follow_redirects=False, timeout=60) as c:
        for path in ("/login", "/shelf", "/healthz", "/mcp"):
            r = c.get(path, headers={"host": "evil.example:8000"})
            assert r.status_code == 400 and "허용하지 않는 Host" in r.text, path
        assert c.get("/login", headers={"host": "localhost"}).status_code == 303  # 루프백 이름은 그대로
        assert c.get("/healthz").status_code == 200


# ---- 15-4·15-5 확인 요청 번호 I²·아주 긴 내보내기 이름 ----

async def test_issue_close_odd_digits_and_long_export_name(store: LocalStore, settings: Settings):
    store.create_project("alice", "책", project_id="b")
    store.write_chapter("alice", "b", 1, "본문", "x", title="하나")
    store.add_issue("alice", "b", "확인", origin="user", chapter_number=1)
    async with Client(build_server(settings, store)) as c:
        for odd in ("I²", "１", "I1a"):
            r = await c.call_tool("book_issue_close", {"id": odd, "project_id": "b"})
            assert r.is_error and "확인 요청 번호 형식이 아닙니다" in r.content[0].text, odd
        r = await c.call_tool("book_export", {"path": "a" * 200_000, "project_id": "b"})
        assert r.is_error and "120바이트까지" in r.content[0].text
        ok = await c.call_tool("book_issue_close", {"id": "I1", "project_id": "b"})
        assert not ok.is_error
    assert not list((store.root / "users" / "alice" / "projects" / "b").glob("exports/*"))


# ---- 13-c·10-a 문헌을 다시 넣어도 status_by·모르는 칸 그대로, 임시 파일 이름 ----

async def test_put_ref_keeps_status_by_and_unknown_keys(store: LocalStore, settings: Settings):
    import json

    from magus.melchior.bibliography import import_bibliography

    store.create_project("alice", "책", project_id="b")
    import_bibliography(store, "alice", "Clack, J. (2012). Gaining ground. Indiana.\n", floor="b")
    async with Client(build_server(settings, store)) as c:
        r = await c.call_tool("category_put", {"book": "참고문헌", "author": "me", "source": {"key": "clack2012"}, "checked": True,
                                               "parts": [{"text": "대목", "reason": "근거"}]})
        assert not r.is_error, r.content[0].text
    store.set_ref_status("alice", "clack2012", "unverified", via="web")
    store.set_ref_status("alice", "clack2012", "verified", via="web")
    path = store.root / "users" / "alice" / "shelf" / "melchior" / "clack2012" / "bib.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps({**data, "future_mark": "앞으로 더할 표시"}, ensure_ascii=False), encoding="utf-8")
    by = data["status_by"]
    async with Client(build_server(settings, store)) as c:  # 같은 문헌을 다시 넣음(표시는 그대로 원문 확인)
        r = await c.call_tool("category_put", {"book": "참고문헌", "author": "me", "source": {"key": "clack2012"}, "checked": True,
                                               "parts": [{"text": "둘째 대목", "reason": "근거"}]})
        assert not r.is_error, r.content[0].text
    after = json.loads(path.read_text(encoding="utf-8"))
    assert after["status"] == "verified" and after["status_by"] == by and after["future_mark"] == "앞으로 더할 표시"


def test_write_is_atomic_with_random_temp_name(tmp_path, monkeypatch: pytest.MonkeyPatch):
    import os

    from magus.store import fileio

    seen: list[str] = []
    real = os.replace

    def spy(src, dst):
        seen.append(os.path.basename(src))
        return real(src, dst)

    monkeypatch.setattr(fileio.os, "replace", spy)
    target = tmp_path / "a.json"
    fileio.write_text(target, "하나\n")
    fileio.write_text(target, "둘\n")
    assert target.read_text(encoding="utf-8") == "둘\n" and len(set(seen)) == 2 and all(n.startswith("a.json.") and n.endswith(".tmp") for n in seen)

    def broken(src, dst):
        raise OSError("디스크")

    monkeypatch.setattr(fileio.os, "replace", broken)
    with pytest.raises(OSError):
        fileio.write_text(target, "셋\n")
    assert target.read_text(encoding="utf-8") == "둘\n" and [p.name for p in tmp_path.iterdir()] == ["a.json"]  # 임시 파일이 남지 않는다


# ---- 5-d·6-c 파일 이름의 보이지 않는 서식 문자·DEL, 내려받기 이름 인코딩 ----

def test_format_chars_in_names_and_download_quote():
    import urllib.parse

    from magus.attachments import clean_name
    from magus.inbox import safe_filename

    for bad in ("‮gnp.exe.png", "사진​.png", "a\x7f.png"):
        with pytest.raises(ValueError):
            clean_name(bad)
        with pytest.raises(ValueError):
            safe_filename(bad.replace(".png", ".txt"))
    assert clean_name("현장 사진.png") == "현장 사진.png" and safe_filename("원고 E2.docx") == "원고 E2.docx"
    assert urllib.parse.quote("a/b<c>.docx", safe="") == "a%2Fb%3Cc%3E.docx"


# ---- 7-e·7-f '나중에' 다시 뽑기 간격·사용자마다 하나, txt 인코딩 판정 ----

def test_plain_text_encoding(tmp_path):
    import random

    from magus.extract import extract

    mostly = tmp_path / "mostly.txt"
    mostly.write_bytes(("도시의 성장은 느리다. " * 500).encode("utf-8") + b"\xff" + "끝".encode("utf-8"))
    got = extract(mostly)
    assert got.status == "ok" and got.text.startswith("도시의 성장은") and got.text.count("�") == 1  # 전에는 통째로 cp949로 깨졌다
    korean = tmp_path / "옛글.txt"
    korean.write_bytes(("옛 한글 문서 " * 200).encode("cp949"))
    assert extract(korean).text.startswith("옛 한글 문서")
    noise = tmp_path / "noise.txt"
    noise.write_bytes(random.Random(1).randbytes(50_000))
    assert extract(noise).status == "empty"  # 무작위 바이너리를 글자로 색인하지 않는다
    assert extract(tmp_path / "없음.md").status == "failed"


def test_later_retry_waits_and_one_per_user(store: LocalStore, monkeypatch: pytest.MonkeyPatch):
    from magus import extract as ex
    from magus.store import CategoryItem
    from magus.store import attachments as store_attachments

    store.create_category("alice", "메모", "blank", "#1f2f5c", (), "common", category_id="notes")
    store.put_category_item("alice", CategoryItem("20261009000000000-aaaaaa", "notes", "글", "me"))
    owner = "notes/20261009000000000-aaaaaa"
    att = store.put_attachment("alice", owner, "긴 글.txt", "글자 ".encode("utf-8") * 100)
    calls: list[str] = []
    monkeypatch.setattr(ex, "extract", lambda path, deadline=20.0: calls.append(path.name) or ex.Extracted("later", "", 20_000))
    store.attachment_text("alice", owner, att.id)
    store.attachment_text("alice", owner, att.id)  # 방금 '나중에'였다: 60초 안에는 다시 뽑지 않는다
    assert calls == ["긴 글.txt"]
    monkeypatch.setattr(ex, "LATER_RETRY", 0.0)
    store_attachments._extracting.add("alice")  # 같은 사용자의 다른 뽑기가 도는 중
    store.attachment_text("alice", owner, att.id)
    assert calls == ["긴 글.txt"]
    store_attachments._extracting.discard("alice")
    store.attachment_text("alice", owner, att.id)
    assert calls == ["긴 글.txt", "긴 글.txt"]


# ---- 24-d 브라우저 도구가 없을 때: 건너뜀(사유 보임) 또는 MAGUS_REQUIRE_BROWSER=1이면 실패 ----

def test_needs_tools(monkeypatch: pytest.MonkeyPatch):
    import conftest

    mark = conftest.needs_tools("node가 없다", None)
    assert mark.name == "skipif" and mark.kwargs["reason"] == "node가 없다" and mark.args == (True,)
    assert conftest.needs_tools("node가 없다", "node").args == (False,)
    monkeypatch.setattr(conftest, "REQUIRE_BROWSER", True)

    def sample() -> None:
        raise AssertionError("돌지 않아야 한다")

    with pytest.raises(pytest.fail.Exception, match="MAGUS_REQUIRE_BROWSER=1"):
        conftest.needs_tools("node가 없다", None)(sample)()
