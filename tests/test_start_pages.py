"""처음 온 사람의 길(2026-10-14 야간): 로그인 전 첫 화면, Claude 연결 안내, 시작 순서, 올린 뒤 안내와 첨부 글자 상태,
파일마다 글 하나로, 문서 업데이트의 hwp, 올린 문서 없는 프로젝트의 전체 현황."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import httpx2
from test_web import _csrf, claude_call, server_proc  # noqa: F401 - 픽스처

from magus.helpbot import screen_key
from magus.store import LocalStore

sys.path.insert(0, str(Path(__file__).parent))
from test_extract_formats import _hwp  # noqa: E402


def _book(data_dir: Path, user: str = "alice") -> tuple[str, str]:
    store = LocalStore(data_dir)
    project = store.create_project(user, "강마을 이야기", project_id="river")
    node = store.add_node(user, project.id, "자료", x=200, y=0)
    store.create_category(user, "원고", "blank", "#1f2f5c", (), project.id, node.id, category_id="draft")
    store.close()
    return project.id, "draft"


def test_landing_and_connect_without_login(server_proc):  # noqa: F811
    base, _, _ = server_proc({})
    with httpx2.Client(base_url=base, follow_redirects=False, timeout=60) as c:
        first = c.get("/")
        assert first.status_code == 200 and "<h1>Magus</h1>" in first.text
        assert first.text.count("<li>") == 3 and '<a class="btn primary" href="/login">시작하기</a>' in first.text
        assert 'href="/connect"' in first.text and 'action="/logout"' not in first.text
        guide = c.get("/connect")
        assert guide.status_code == 200 and f'<code id="mcp-url">{base}/mcp</code>' in guide.text
        assert "주소 복사" in guide.text and "「항상 허용」을 고르세요." in guide.text and "magus 전체 보여 줘" in guide.text
        c.get("/login")  # 로컬: 바로 로그인
        assert c.get("/").headers["location"] == "/shelf"  # 로그인했으면 프로젝트 목록
        assert 'action="/logout"' in c.get("/connect").text
        assert 'href="/connect"' in c.get("/me").text


def test_steps_until_first_document_and_hints(server_proc):  # noqa: F811
    base, data_dir, _ = server_proc({})
    with httpx2.Client(base_url=base, follow_redirects=True, timeout=120) as c:
        empty = c.get("/login?next=/shelf").text
        assert 'aria-label="시작 순서"' in empty and "<li class=done><b>가입</b>" in empty and "<li class=next><b>프로젝트 만들기</b>" in empty
        _, book = _book(data_dir)
        listed = c.get("/shelf").text
        assert "<li class=done><b>프로젝트 만들기</b>" in listed and "<li class=next><b>문서 올리기</b>" in listed and "프로젝트 열기" in listed
        csrf = _csrf(c.get(f"/shelf/write/{book}").text)
        assert 'name="each"' in c.get(f"/shelf/write/{book}").text
        hwp = _hwp([["제1장 강가의 마을", "나루터에는 아침마다 소금 배가 닿았다."]])
        made = c.post(f"/shelf/write/{book}", data={"csrf": csrf, "title": "", "content": ""},
                      files=[("files", ("강마을_원고.hwp", hwp, "application/octet-stream")),
                             ("files", ("옛 보고서.doc", b"\xd0\xcf\x11\xe0" + b"\0" * 600, "application/msword"))])
        assert "Claude에서 이렇게 물어보세요: 「magus에서 「강마을_원고」 읽어 줘」" in made.text
        assert '<small class="tstate ok">Claude가 읽을 수 있음 · 글자 ' in made.text
        assert '<small class="tstate no">Claude가 읽을 수 없음 · 새 형식(docx·pptx·xlsx)으로' in made.text
        assert 'aria-label="시작 순서"' not in c.get("/shelf").text  # 문서를 올렸으면 시작 순서는 사라진다
        assert ">강마을_원고.hwp<" in c.get("/me/documents").text  # 문서 업데이트에 hwp도(2026-10-14)
        # 파일마다 글 하나로: 논문 셋 → 글 셋(제목은 파일 이름)
        each = c.post(f"/shelf/write/{book}", data={"csrf": csrf, "title": "무시", "content": "", "each": "1"},
                      files=[("files", (f"논문{n}.txt", f"논문 {n}의 초록".encode(), "text/plain")) for n in range(1, 4)])
        assert "글 3개를 만들었습니다." in each.text
        titles = re.findall(r'<li><a class="post" href="[^"]+"><span class="pt">([^<]+)</span>', each.text)
        assert {"논문1", "논문2", "논문3"} <= set(titles) and "무시" not in titles
    outline = claude_call(data_dir, "alice", "book_outline", project_id="river")
    assert "올린 문서 없음" in outline and re.search(r"책에 첨부한 문서 \d개: .*강마을_원고\.hwp\(「원고」, 글자 1쪽, 첨부:", outline)


def test_screen_key_connect():
    assert screen_key("/connect") == "connect" and screen_key("/") == "other"
