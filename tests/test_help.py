"""웹 도움말 챗봇(사용자 요청 #97 D). 실제 API는 부르지 않는다: 단위 시험은 가짜 클라이언트, HTTP 시험은 이 시험이 띄운
가짜 Messages API(ANTHROPIC_BASE_URL)로 공식 SDK 경로까지 본다. 키 없음·한도 초과·API 오류·비로그인(401)·허용 목록 밖(403)·CSRF."""

from __future__ import annotations

import json
import logging
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import httpx2
import pytest
from test_web import _csrf, server_proc  # noqa: F401 - 픽스처

from magus.helpbot import DEFAULT_DIR, QUOTA, SCREENS, UNAVAILABLE, HelpBot, load_docs, screen_key, screen_label
from magus.instructions import CORE_NAMES, OLD_NAMES
from magus.signing import sign

SECRET_Q = "비밀질문-앨리스의원고내용"
SECRET_A = "비밀답변-도움말문서기준"


def _reply(text: str = SECRET_A, stop: str = "end_turn") -> SimpleNamespace:
    usage = SimpleNamespace(input_tokens=30, output_tokens=12, cache_creation_input_tokens=0, cache_read_input_tokens=5000)
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)], stop_reason=stop, usage=usage)


class FakeClient:
    def __init__(self, fail: Exception | None = None, reply: SimpleNamespace | None = None):
        self.calls: list[dict] = []
        self.fail, self.reply = fail, reply or _reply()
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise self.fail
        return self.reply


def _bot(client: FakeClient | None = None, key: str | None = "sk-test", limit: int = 30) -> HelpBot:
    client = client or FakeClient()
    return HelpBot(key, "# 문서\n도움말 내용", daily_limit=limit, client_factory=lambda: client)


def test_help_docs_have_no_internal_or_tool_names():
    """시스템 프롬프트(docs/help 전체)에는 내부 이름·도구 이름·옛 이름이 없다. 캐시 최소 길이(4,096토큰)를 넘길 만큼 길다."""
    docs = load_docs(DEFAULT_DIR)
    assert len(docs) > 8000 and docs.startswith("# 용어 사전")
    for word in (*CORE_NAMES, *OLD_NAMES):
        assert word not in docs, word
    assert not re.search(r"(?:book|ref|idea|style|files|category)_[a-z_]+", docs)
    bot = HelpBot("k", docs)
    [block] = bot.system()
    assert block["cache_control"] == {"type": "ephemeral"} and block["text"].endswith(docs.strip()[-50:])
    for word in CORE_NAMES:
        assert word not in block["text"]


def test_screen_names_come_from_a_fixed_list():
    assert screen_key("/shelf") == "projects" and screen_key("/shelf/p/city") == "map"
    assert screen_key("/shelf/book/x", "tab=issues") == "doc_issues" and screen_key("/shelf/book/x") == "doc_chapters"
    assert screen_key("/shelf/book/x", "tab=cites&view=questions") == "doc_questions"
    assert screen_key("/shelf/abc") == "board" and screen_key("/shelf/abc/def") == "board"
    assert screen_key("/shelf/abc/def/edit") == "item_edit" and screen_key("/shelf/edit/abc") == "book_settings"
    assert screen_key("/me/files") == "files" and screen_key("/login") == "other"
    assert screen_label("map", "board") == "프로젝트 지도 · 패널: 게시판"
    assert screen_label("<script>앨리스의 책", "도시는 어떻게") == "기타"  # 브라우저가 보낸 값은 목록에 있을 때만
    assert set(SCREENS.values()) >= {"게시판", "프로젝트 지도"}


def test_ask_sends_only_question_docs_and_screen(caplog: pytest.LogCaptureFixture):
    client = FakeClient()
    bot = _bot(client)
    with caplog.at_level(logging.INFO, logger="magus.help"):
        status, body = bot.ask("alice", f"  {SECRET_Q}  ", "게시판")
    assert status == 200 and body == {"ok": True, "answer": SECRET_A, "left": 29}
    [call] = client.calls
    assert call["model"] == "claude-haiku-4-5-20251001" and call["max_tokens"] == 600
    assert call["messages"] == [{"role": "user", "content": f"지금 화면: 게시판\n\n질문: {SECRET_Q}"}]
    assert call["system"][0]["cache_control"] == {"type": "ephemeral"} and "도움말 내용" in call["system"][0]["text"]
    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert "help ok user=alice n=1 in=30 cache_write=0 cache_read=5000 out=12" in logged
    assert SECRET_Q not in logged and SECRET_A not in logged and "sk-test" not in logged


def test_no_key_quota_and_api_errors(caplog: pytest.LogCaptureFixture):
    # 키 없음: 부르지 않고 짧은 안내만
    client = FakeClient()
    assert _bot(client, key=None).ask("alice", "질문", "게시판") == (503, {"ok": False, "error": UNAVAILABLE})
    assert client.calls == []
    # 한도: 하루 2번이면 셋째는 429, 다른 사용자·다음 날은 따로
    day = ["2026-10-08"]
    bot = _bot(limit=2)
    bot.today = lambda: day[0]
    assert [bot.ask("alice", "q", "x")[0] for _ in range(3)] == [200, 200, 429]
    assert bot.ask("alice", "q", "x")[1] == {"ok": False, "error": QUOTA}
    assert bot.ask("bob", "q", "x")[0] == 200
    day[0] = "2026-10-09"
    assert bot.ask("alice", "q", "x")[0] == 200
    # API 오류·연결 오류·거절·빈 답: 짧은 안내만, 한도는 쓰지 않는다
    import anthropic

    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    failures = [anthropic.InternalServerError("x", response=httpx2.Response(500, request=request), body=None),
                anthropic.APIConnectionError(request=request), RuntimeError("뜻밖의 오류")]
    for fail in failures:
        bot = _bot(FakeClient(fail=fail), limit=1)
        with caplog.at_level(logging.INFO, logger="magus.help"):
            assert bot.ask("alice", SECRET_Q, "x") == (503, {"ok": False, "error": UNAVAILABLE})
        assert bot.used("alice") == 0
    for reply in (_reply(""), _reply("거절", stop="refusal")):
        assert _bot(FakeClient(reply=reply)).ask("alice", "q", "x")[0] == 503
    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert "help error user=alice code=500" in logged and "code=APIConnectionError" in logged and SECRET_Q not in logged
    assert _bot().ask("alice", "   ", "x")[0] == 400


# ---- HTTP(서버 프로세스 + 가짜 Messages API) -------------------------------------------------------------------------


@pytest.fixture
def fake_api():
    """가짜 Anthropic Messages API. state["fail"]이 있으면 그 상태 코드로 실패한다. 받은 요청(본문·머리)을 남긴다."""
    state: dict = {"fail": None, "seen": []}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            body = json.loads(self.rfile.read(int(self.headers.get("content-length") or 0)) or b"{}")
            state["seen"].append({"path": self.path, "body": body, "key": self.headers.get("x-api-key")})
            if state["fail"]:
                payload, code = {"type": "error", "error": {"type": "api_error", "message": "boom"}}, state["fail"]
            else:
                payload, code = {
                    "id": "msg_fake", "type": "message", "role": "assistant", "model": body.get("model"),
                    "content": [{"type": "text", "text": f"**{SECRET_A}**"}], "stop_reason": "end_turn", "stop_sequence": None,
                    "usage": {"input_tokens": 40, "output_tokens": 9, "cache_creation_input_tokens": 6000, "cache_read_input_tokens": 0},
                }, 200
            data = json.dumps(payload).encode()
            self.send_response(code)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):  # 시험 출력 조용히
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}", state
    server.shutdown()


def _ask(c: httpx2.Client, csrf: str, q: str = SECRET_Q, **extra) -> httpx2.Response:
    return c.post("/help/ask", json={"csrf": csrf, "q": q, "screen": "map", "sub": "board", **extra})


def test_help_endpoint_with_fake_api(server_proc, fake_api):  # noqa: F811
    url, state = fake_api
    base, _, log_path = server_proc({"ANTHROPIC_API_KEY": "sk-ant-fake-key-123", "ANTHROPIC_BASE_URL": url, "HELP_DAILY_LIMIT": "2"})
    with httpx2.Client(base_url=base, follow_redirects=True, timeout=120) as c:
        assert c.post("/help/ask", json={"q": "x"}).status_code == 401  # 로그인 전
        page = c.get("/login?next=/shelf").text
        csrf = _csrf(page)
        assert 'class="help-btn" aria-label="도움말" title="도움말"' in page and 'data-screen="projects"' in page
        assert "sk-ant-fake-key-123" not in page  # 키는 브라우저로 내려가지 않는다
        assert "help-btn" not in c.get("/shelf/p/common", headers={"sec-fetch-dest": "iframe"}).text  # 패널 안 화면에는 없다
        assert _ask(c, "틀림").status_code == 403
        ok = _ask(c, csrf)
        assert ok.status_code == 200 and ok.json() == {"ok": True, "answer": SECRET_A, "left": 1}  # 굵은 글씨 표시는 뗀다
        [seen] = state["seen"]
        assert seen["path"] == "/v1/messages" and seen["key"] == "sk-ant-fake-key-123"
        assert seen["body"]["model"] == "claude-haiku-4-5-20251001" and seen["body"]["max_tokens"] == 600
        assert seen["body"]["messages"] == [{"role": "user", "content": f"지금 화면: 프로젝트 지도 · 패널: 게시판\n\n질문: {SECRET_Q}"}]
        assert seen["body"]["system"][0]["cache_control"] == {"type": "ephemeral"} and "# 용어 사전" in seen["body"]["system"][0]["text"]
        assert "alice" not in json.dumps(seen["body"], ensure_ascii=False)  # 사용자 이름·자료는 보내지 않는다
        state["fail"] = 500
        assert _ask(c, csrf).json() == {"ok": False, "error": UNAVAILABLE}
        assert c.get("/shelf").status_code == 200  # 도움말이 실패해도 다른 기능은 그대로
        state["fail"] = None
        assert _ask(c, csrf).status_code == 200
        quota = _ask(c, csrf)
        assert quota.status_code == 429 and quota.json()["error"] == QUOTA
    text = Path(log_path).read_text(encoding="utf-8")
    assert "help ok user=alice n=1 in=40 cache_write=6000 cache_read=0 out=9" in text and "help error user=alice code=500" in text
    assert "help quota user=alice" in text
    assert SECRET_Q not in text and SECRET_A not in text and "sk-ant-fake-key-123" not in text


def test_help_without_key_and_outside_allowed_list(server_proc):  # noqa: F811
    base, _, _ = server_proc({"ANTHROPIC_API_KEY": ""})
    with httpx2.Client(base_url=base, follow_redirects=True, timeout=120) as c:
        csrf = _csrf(c.get("/login?next=/shelf").text)
        got = _ask(c, csrf)
        assert got.status_code == 503 and got.json() == {"ok": False, "error": UNAVAILABLE}
        assert c.get("/shelf").status_code == 200
    # 원격 모드: 서명은 맞지만 허용 목록 밖인 세션은 403(목록에서 빠진 사용자)
    remote, _, _ = server_proc({"PUBLIC_URL": "http://127.0.0.1:{port}", "AUTH_ISSUER": "http://127.0.0.1:9/never",
                                "ALLOWED_USERS": "sub-alice=alice", "SESSION_SECRET": "x" * 40, "WEB_CLIENT_ID": "web-client",
                                "ANTHROPIC_API_KEY": "sk-ant-unused"})
    cookie = sign({"uid": "mallory", "sid": "s1"}, b"x" * 40, "session", 600)
    with httpx2.Client(base_url=remote, timeout=120, cookies={"magus_session": cookie}) as c:
        got = c.post("/help/ask", json={"csrf": "x", "q": "q"})
        assert got.status_code == 403 and got.json()["ok"] is False
    with httpx2.Client(base_url=remote, timeout=120, cookies={"magus_session": "forged.cookie"}) as c:
        assert c.post("/help/ask", json={"csrf": "x", "q": "q"}).status_code == 401
