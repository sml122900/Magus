"""'+ 프로젝트' 간소화(2026-10-10): 프로젝트 목록의 '+ 프로젝트'는 제목과 '만들기'만. 만들면 올린 문서 없는 프로젝트(가운데 노드만)의
지도로 간다. 올린 문서를 넣는 길은 둘 — 내 정보 › 올린 파일에 올리기, 또는 게시판 글에 첨부 — 그다음 대화에서 book_import
(올린 문서 없는 project_id). 여기서는 웹과 대화를 같은 서버(HTTP, 원격처럼 파일은 이름으로만)로 돈다."""

from __future__ import annotations

import re
import urllib.parse

import httpx2
import pytest
from mcp import Client
from test_web import _csrf, server_proc  # noqa: F401 - 픽스처

from magus.store import LocalStore
from magus.synthetic import build_manuscript_docx

pytestmark = pytest.mark.anyio
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _text(result) -> str:
    return "".join(block.text for block in result.content)


def _new_project(c: httpx2.Client, csrf: str, title: str) -> tuple[str, httpx2.Response]:
    page = c.post("/shelf/projects", data={"csrf": csrf, "title": title})
    return urllib.parse.urlparse(str(page.url)).path.split("/")[-1], page


async def test_plus_project_is_title_only_and_documents_come_through_chat(server_proc, tmp_path):  # noqa: F811
    base, data_dir, _ = server_proc({})
    manuscript = build_manuscript_docx(tmp_path / "닿으려는_종_합성.docx").read_bytes()
    with httpx2.Client(base_url=base, follow_redirects=True, timeout=120) as c:
        shelf = c.get("/login?next=/shelf").text
        csrf = _csrf(shelf)
        # 1. '+ 프로젝트' 칸: 제목(0/120)과 '만들기'만. 파일 칸·'올리기'·진행 막대·문서 올리기 주소는 없다
        card = shelf.split('<li class="pcard new">')[1].split("</li>")[0]
        assert '<form method="post" action="/shelf/projects">' in card and 'data-count-max="120"' in card
        assert '<button class="primary">만들기</button>' in card
        assert 'type="file"' not in card and "올리기" not in card and "/shelf/manuscript" not in shelf and "data-progress" not in shelf
        # 만들면 올린 문서 없는 프로젝트의 지도(가운데 노드)로
        pid_a, page = _new_project(c, csrf, "올린 파일로 채울 책")
        assert "프로젝트를 만들었습니다." in page.text and urllib.parse.parse_qs(urllib.parse.urlparse(str(page.url)).query)["node"] == ["center"]
        store = LocalStore(data_dir)
        try:
            assert store.list_chapters("alice", pid_a) == [] and [n.id for n in store.get_map("alice", pid_a).nodes] == ["center"]
        finally:
            store.close()
        assert c.get(f"/shelf/book/{pid_a}").status_code == 404  # 아직 올린 문서가 없다
        # 2-가. 예전 올린 파일(inbox): 내 정보의 올리기는 2026-10-10에 없앴지만 이미 올린 파일은 그대로 쓴다
        (data_dir / "users" / "alice" / "inbox").mkdir(parents=True)
        (data_dir / "users" / "alice" / "inbox" / "원고.docx").write_bytes(manuscript)
        # 2-나. 첨부 경로: 다른 프로젝트의 가운데 노드에 새 책 → 게시판 글에 문서 첨부
        pid_b, _ = _new_project(c, csrf, "첨부로 채울 책")
        made = c.post(f"/shelf/new?project={pid_b}&node=center", data={"csrf": csrf, "name": "자료", "color": "#2f6db5"})
        book = urllib.parse.urlparse(str(made.url)).path.split("/")[-1]
        post = c.post(f"/shelf/write/{book}", data={"csrf": csrf, "title": "처음 원고", "content": ""},
                      files={"files": ("닿으려는_종_합성.docx", manuscript, DOCX)})
        attachment = re.search(rf'href="/shelf/{book}/[^/"]+/files/([^"]+)"', post.text).group(1)
    # 대화(이 서버의 /mcp): "「프로젝트」의 올린 문서로 가져와 줘"
    async with Client(f"{base}/mcp") as chat:
        listed = _text(await chat.call_tool("files_list", {}))
        assert "원고.docx" in listed and f"첨부:{attachment}" in listed
        a = await chat.call_tool("book_import", {"path": "원고.docx", "project_id": pid_a})
        assert not a.is_error, _text(a)
        b = await chat.call_tool("book_import", {"path": f"첨부:{attachment}", "project_id": pid_b})
        assert not b.is_error, _text(b)
        for pid, title in ((pid_a, "올린 파일로 채울 책"), (pid_b, "첨부로 채울 책")):
            outline = _text(await chat.call_tool("book_outline", {"project_id": pid}))
            assert outline.startswith(f"프로젝트: {title} ({pid})") and "7장" in outline  # 저자가 지은 제목 그대로, 같은 프로젝트
        assert "이미 가져옴" in _text(await chat.call_tool("files_list", {}))
    with httpx2.Client(base_url=base, follow_redirects=True, timeout=120) as c:
        c.get("/login?next=/shelf")
        for pid in (pid_a, pid_b):
            assert '<p class="floor-meta">7장' in c.get(f"/shelf/book/{pid}").text  # 웹에서 올린 문서 화면
            assert f'data-key="ms.{pid}"' in c.get(f"/shelf/p/{pid}?node=center").text  # 가운데 노드에 꽂힘
        # 문서 올리기 주소는 없다(남은 화면이 쓰지 않는다)
        assert c.post("/shelf/manuscript", data={"csrf": "x"}, files={"file": ("a.docx", b"x", DOCX)}, follow_redirects=False).status_code == 405
        store = LocalStore(data_dir)
        try:
            assert len([f for f in store.list_floors("alice") if not f.common]) == 2  # 다른 프로젝트가 생기지 않았다
        finally:
            store.close()


async def test_title_only_project_response_points_to_files_and_attachments(server_proc):  # noqa: F811
    """대화로 제목만 있는 프로젝트를 만들 때 응답이 지금 길(올린 파일·게시판 첨부 → book_import)을 알린다(없어진 웹 경로를 말하지 않는다)."""
    base, _, _ = server_proc({})
    async with Client(f"{base}/mcp") as chat:
        said = _text(await chat.call_tool("book_import", {"title": "새 책"}))
    assert "게시판 글에 첨부한 뒤" in said and "올린 파일" not in said and "책 추가" not in said and "문서 올리기" not in said
