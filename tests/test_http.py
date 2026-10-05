"""P1 1단계: streamable-http(stateless). 하위 프로세스로 서버를 띄우고 18개 도구를 HTTP로 부른다.
서버 로그에는 도구 이름·user_id·소요 시간·결과만 있고, 본문·발췌·생각은 한 글자도 없어야 한다."""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from mcp import Client

pytestmark = pytest.mark.anyio

FIXTURES = Path(__file__).parent / "fixtures" / "synthetic"
TOOLS = {
    "files_list", "book_outline", "book_issues", "book_read_chapter", "book_write_chapter", "book_decide", "book_issue_add",
    "book_issue_close", "book_import", "book_export", "ref_import_bibliography", "ref_add", "ref_search", "ref_check",
    "idea_add", "idea_add_conversation", "idea_search", "idea_delete", "style_add", "style_search", "style_delete",
}
# 로그에 나오면 안 되는 내용(본문·발췌·생각·문체 구절)
SECRET = ("비밀본문가나다", "비밀발췌라마바", "비밀생각사아자", "비밀구절차카타")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_healthy(url: str, proc: subprocess.Popen, timeout: float = 20) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"서버가 종료됨: {proc.returncode}")
        try:
            with urllib.request.urlopen(url, timeout=1) as r:
                if r.status == 200:
                    return
        except OSError:
            time.sleep(0.2)
    raise TimeoutError(url)


@pytest.fixture
def http_server(data_dir: Path, tmp_path: Path):
    port = _free_port()
    log_path = tmp_path / "server.log"
    with log_path.open("w", encoding="utf-8") as log:
        proc = subprocess.Popen(
            [sys.executable, "-m", "magus", "serve", "--transport", "http", "--port", str(port)],
            env={**os.environ, "USER_ID": "alice", "DATA_DIR": str(data_dir), "EMBEDDINGS": "none", "PYTHONIOENCODING": "utf-8"},
            stdout=log, stderr=subprocess.STDOUT,
        )
        try:
            _wait_healthy(f"http://127.0.0.1:{port}/healthz", proc)
            yield f"http://127.0.0.1:{port}/mcp", log_path
        finally:
            proc.terminate()
            proc.wait(timeout=10)


def _text(result) -> str:
    assert not result.is_error, result.content[0].text if result.content else result
    return "".join(block.text for block in result.content)


async def test_all_tools_over_http_and_log_has_no_content(http_server, data_dir: Path):
    url, log_path = http_server
    inbox = data_dir / "users" / "alice" / "inbox"  # 원격에서는 웹 업로드가 넣는다. 여기서는 파일로 바로 둔다
    inbox.mkdir(parents=True)
    shutil.copy(FIXTURES / "닿으려는_종_합성.docx", inbox / "원고.docx")
    tags = {"호흡": "짧음", "시점": "1인칭", "열기": "장면", "장치": ["반복"], "어미": "-다", "톤": "건조"}
    async with Client(url) as client:
        assert client.server_info.name == "Magus"
        assert {t.name for t in (await client.list_tools()).tools} == TOOLS
        calls = [
            ("files_list", {}),
            ("book_import", {"path": "원고.docx", "project_id": "synth"}),
            ("book_outline", {}),
            ("book_issues", {"limit": 3}),
            ("book_read_chapter", {"number": 1}),
            ("book_write_chapter", {"number": 7, "content": f"{SECRET[0]}. Clack(2012)도 있다.", "note": "고침"}),
            ("book_decide", {"text": "결정"}),
            ("book_issue_add", {"text": "열린 문제"}),
            ("book_issue_close", {"id": "I14"}),
            ("book_export", {}),
            ("ref_import_bibliography", {"text": "Zimmer, C. (1998). At the water's edge. Free Press."}),
            ("ref_check", {"chapter_number": 1}),
            ("ref_add", {"bib": {"key": "clack2012"}, "passages": [{"text": SECRET[1], "reason": "1장"}]}),
            ("ref_search", {"query": "라마바"}),
            ("idea_add", {"text": SECRET[2], "kind": "thought"}),
            ("idea_add_conversation", {"markdown": "**사용자:** 고래는 돌아갔다\n**Claude:** 맞습니다"}),
            ("idea_search", {"query": "사아자"}),
            ("style_add", {"passage": SECRET[3], "reason": "짧은 리듬", "tags": tags}),
            ("style_search", {"query": "짧은 리듬"}),
        ]
        out = {name: _text(await client.call_tool(name, args)) for name, args in calls}
        deletes = [("idea_delete", {"id": out["idea_add"].split()[2], "note": "시험"}),  # 휴지통으로 옮긴 내용도 로그에는 없다
                   ("style_delete", {"id": out["style_add"].split()[2], "note": "시험"})]
        for name, args in deletes:
            _text(await client.call_tool(name, args))
        calls += deletes
        assert {name for name, _ in calls} == TOOLS
        assert "clack2012 (verified)" in _text(await client.call_tool("ref_search", {"query": "라마바"}))
        assert (await client.call_tool("book_read_chapter", {"number": 99})).is_error
        # 원격에서는 서버의 파일 경로를 받지 않는다(받은함 이름만)
        escaped = await client.call_tool("book_import", {"path": str(FIXTURES / "닿으려는_종_합성.docx"), "project_id": "x"})
        assert escaped.is_error and "받은함에" in escaped.content[0].text
    time.sleep(0.3)
    log = log_path.read_text(encoding="utf-8")
    lines = [line for line in log.splitlines() if "magus.audit" in line]
    assert len(lines) == len(calls) + 3 and all(" user=alice " in line for line in lines)
    assert "tool=book_read_chapter user=alice" in lines[-2] and "status=error error=ToolError" in lines[-2]
    for secret in SECRET:
        assert secret not in log  # 본문·발췌·생각·구절은 로그에 없다


def test_refuses_public_bind_without_auth(data_dir: Path):
    proc = subprocess.run(
        [sys.executable, "-m", "magus", "serve", "--transport", "http", "--host", "0.0.0.0"],
        env={**os.environ, "USER_ID": "alice", "DATA_DIR": str(data_dir), "PYTHONIOENCODING": "utf-8"},
        capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    assert proc.returncode == 2 and "인증 없이" in proc.stderr


def test_request_size_limit(http_server):
    # MCP 요청 본문 상한(MAX_REQUEST_MB, 기본 2MB). 넘으면 명확한 오류로 거절한다
    url, _ = http_server
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                       "params": {"name": "idea_add", "arguments": {"text": "가" * 1_100_000, "kind": "thought"}}}).encode()
    request = urllib.request.Request(url, body, {"content-type": "application/json", "accept": "application/json, text/event-stream"})
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(request, timeout=20)
    assert e.value.code == 413
