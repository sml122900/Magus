"""오류 화면(2026-10-09 구조·버그 점검 2번): 404·405·400 공통 화면(Magus 머리·한국어 문장·돌아가기), POST 전용 주소를 GET으로 열면
그 화면으로, 없는 글·책·노드·첨부·프로젝트 문구, 휴지통에 있는 글의 옛 주소, 프로젝트 없이 연 새 책, 노드 컨텍스트가 너무 길면 400."""

from __future__ import annotations

import re

import httpx2
from test_web import _csrf, server_proc  # noqa: F401 - 픽스처

from magus.store import CategoryItem, LocalStore

BOOK = "notes-common"
ITEM = "20261009000000000-aaaaaa"
GONE = "20261009000000001-bbbbbb"


def _seed(data_dir) -> None:
    store = LocalStore(data_dir)
    store.create_category("alice", "메모", "blank", "#1f2f5c", (), "common", category_id=BOOK)
    store.put_category_item("alice", CategoryItem(ITEM, BOOK, "남은 글", "me"))
    store.put_category_item("alice", CategoryItem(GONE, BOOK, "버린 글", "me"))
    store.trash_item_with_replies("alice", BOOK, GONE, "시험")
    store.close()


def _error(page: httpx2.Response, status: int, sentence: str, back: str = "/shelf") -> None:
    assert page.status_code == status, (page.status_code, page.text[:300])
    assert '<a class="brand" href="/shelf" aria-label="처음으로">Magus</a>' in page.text and f'<p class="msg err">{sentence}</p>' in page.text
    assert f'<a class="back" href="{back}">돌아가기</a>' in page.text


def test_error_pages(server_proc):  # noqa: F811
    base, data_dir, _ = server_proc({})
    _seed(data_dir)
    with httpx2.Client(base_url=base, follow_redirects=False, timeout=60) as c:
        page = c.get("/login?next=/shelf", follow_redirects=True).text
        csrf = _csrf(page)
        # 없는 주소: 공통 화면. 직전 화면(같은 사이트)이 있으면 돌아가기가 그리로
        _error(c.get("/없는/주소"), 404, "없는 주소입니다.")
        _error(c.get("/없는/주소", headers={"referer": f"{base}/shelf/p/common"}), 404, "없는 주소입니다.", "/shelf/p/common")
        _error(c.get("/없는/주소", headers={"referer": "https://evil.example/x"}), 404, "없는 주소입니다.")  # 다른 사이트는 무시
        # POST 전용 주소를 주소창에서 열면 그 화면으로
        for path, screen in [("/shelf/projects", "/shelf"), ("/shelf/p/common/map", "/shelf/p/common"), ("/inbox/upload", "/inbox"),
                             (f"/shelf/{BOOK}/{ITEM}/trash", f"/shelf/{BOOK}/{ITEM}"), (f"/shelf/{BOOK}/{ITEM}/scrap", f"/shelf/{BOOK}/{ITEM}"),
                             ("/shelf/move", "/shelf"), ("/logout", "/")]:
            moved = c.get(path)
            assert moved.status_code == 303 and moved.headers["location"] == screen, (path, moved.status_code, moved.headers.get("location"))
        _error(c.request("PUT", "/shelf"), 405, "이 주소는 그렇게 열 수 없습니다.")
        # 화면마다 맞는 문구
        _error(c.get("/shelf/없는책"), 404, "없는 책입니다.")
        _error(c.get(f"/shelf/{BOOK}/20261009000000009-cccccc"), 404, "없는 글입니다.")
        trashed = c.get(f"/shelf/{BOOK}/{GONE}")
        _error(trashed, 404, "이 글은 휴지통에 있습니다.")
        assert '<a href="/shelf/p/common/trash">휴지통 열기</a>' in trashed.text
        _error(c.get(f"/shelf/{BOOK}/{GONE}/edit"), 404, "이 글은 휴지통에 있습니다.")
        _error(c.get(f"/shelf/{BOOK}/{ITEM}/files/0123456789abcdef"), 404, "없는 첨부입니다.")
        _error(c.get("/shelf/p/없는프로젝트"), 404, "없는 프로젝트입니다.")
        _error(c.get("/shelf/p/없는프로젝트/trash"), 404, "없는 프로젝트입니다.")
        _error(c.get("/shelf/doc/없는문서"), 404, "없는 문서입니다.")
        node = c.get("/shelf/p/common?node=없는노드")
        assert node.status_code == 404 and '<p class="msg err">없는 노드입니다.</p>' in node.text and 'class="map-view"' in node.text
        # 프로젝트 없이 연 새 책 → 프로젝트 목록에서 고르게
        new = c.get("/shelf/new")
        assert new.status_code == 303 and new.headers["location"] == "/shelf?pick=book"
        assert "새 책은 프로젝트 안에서 만듭니다." in c.get("/shelf?pick=book").text
        assert c.get("/shelf/new?project=common").status_code == 200
        # 노드 컨텍스트가 500자를 넘으면 책 설정과 같이 400(그 노드를 연 채)
        made = c.post("/shelf/p/common/map", data={"csrf": csrf, "action": "add_node", "name": "현장"}, follow_redirects=True)
        node_id = re.search(r"[?&]node=([^&]+)", str(made.url)).group(1)
        long = c.post("/shelf/p/common/map", data={"csrf": csrf, "action": "contexts", "node": node_id, "ctx_new": "가" * 501})
        assert long.status_code == 400 and "컨텍스트를 저장하지 못했습니다." in long.text
        assert f'class="pp-node" id="pp-node" data-node="{node_id}"' in long.text
        assert '<details class="pp-set" open>' in long.text and ">" + "가" * 501 + "</textarea>" in long.text  # 적은 내용 그대로(결정 d)
        bad_node = c.post("/shelf/p/common/map", data={"csrf": csrf, "action": "add_node", "name": "새 현장", "ctx_new": "나" * 501})
        assert bad_node.status_code == 400 and "노드를 만들지 못했습니다." in bad_node.text
        assert '<details class="pm-new" id="new-node" open>' in bad_node.text and 'name="name" value="새 현장"' in bad_node.text
        assert ">" + "나" * 501 + "</textarea>" in bad_node.text
        assert c.post(f"/shelf/edit/{BOOK}", data={"csrf": csrf, "name": "메모", "ctx_new": "가" * 501}).status_code == 400
        # 폼을 읽지 못함(첨부 21개 > 폼 한도 20) → 400 공통 화면
        files = [("files", (f"{n}.txt", b"x", "text/plain")) for n in range(21)]
        _error(c.post(f"/shelf/write/{BOOK}", data={"csrf": csrf, "content": "x"}, files=files), 400,
               "보낸 내용을 읽지 못했습니다. 화면을 새로 고쳐 다시 해 주세요.")
        # 스크립트(JSON)·MCP는 그대로 짧게
        assert c.get("/없는/주소", headers={"accept": "application/json"}).json() == {"ok": False, "error": "없는 주소입니다."}
        assert "Magus" not in c.get("/mcp/없음").text
