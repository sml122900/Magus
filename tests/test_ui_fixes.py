"""작은 화면 고침(2026-10-09 구조·버그 점검 6·7·9·12번): 장 상태 한국어, 휴지통 목록, 스크랩 초점, 작은 것."""

from __future__ import annotations

import httpx2
from test_web import server_proc  # noqa: F401 - 픽스처

from magus.store import LocalStore


def test_chapter_status_names(server_proc):  # noqa: F811
    """장 상태는 한국어(초안·고치는 중·완성). 모두 초안이면 상태 칸을 숨긴다."""
    base, data_dir, _ = server_proc({})
    store = LocalStore(data_dir)
    for pid in ("a", "b"):
        store.create_project("alice", f"책 {pid}", project_id=pid)
        store.write_chapter("alice", pid, 1, "첫 장 본문", "x", title="하나")
        store.write_chapter("alice", pid, 2, "둘째 장 본문", "x", title="둘")
    store.write_chapter("alice", "b", 1, "첫 장 본문 고침", "x", status="revising")
    store.write_chapter("alice", "b", 2, "둘째 장 본문 고침", "x", status="done")
    store.close()
    with httpx2.Client(base_url=base, follow_redirects=True, timeout=60) as c:
        c.get("/login?next=/shelf")
        mixed = c.get("/shelf/book/b").text
        assert "<th>상태</th>" in mixed and "<td>고치는 중</td>" in mixed and "<td>완성</td>" in mixed
        assert "revising" not in mixed.split("<main>")[1] and ">done<" not in mixed
        drafts = c.get("/shelf/book/a").text
        assert "<th>상태</th>" not in drafts and "draft" not in drafts.split("<main>")[1]


def test_trash_list_counts_links_and_earlier_posts(server_proc):  # noqa: F811
    """휴지통 목록: 머리에 N개, 연결 노드는 「원본 이름」, 노드 아래 안에 있던 것 한 줄, 먼저 버린 글은 따로(노드를 되살린 뒤 되살린다)."""
    import re  # noqa: PLC0415

    from test_web import _csrf  # noqa: PLC0415

    from magus.category.moves import add_link, trash_node_with_books  # noqa: PLC0415
    from magus.store import CategoryItem  # noqa: PLC0415

    base, data_dir, _ = server_proc({})
    store = LocalStore(data_dir)
    store.create_project("alice", "도시의 책", project_id="city")
    store.create_project("alice", "강의 책", project_id="river")
    node = store.add_node("alice", "city", "현장")
    store.create_category("alice", "답사", "blank", "#1f2f5c", (), "city", node.id, category_id="walk")
    store.put_category_item("alice", CategoryItem("20261009000000001-aaaaaa", "walk", "먼저 버린 글", "me"))
    store.put_category_item("alice", CategoryItem("20261009000000002-aaaaaa", "walk", "남은 글", "me"))
    store.trash_category_item("alice", "walk", "20261009000000001-aaaaaa", "먼저")
    trash_node_with_books(store, "alice", "city", node.id, "노드째")
    link = add_link(store, "alice", "city", "river", "center")
    trash_node_with_books(store, "alice", "city", link.id, "연결 노드")
    store.close()
    with httpx2.Client(base_url=base, follow_redirects=True, timeout=60) as c:
        page = c.get("/login?next=/shelf/p/city/trash").text
        csrf = _csrf(page)
        assert '<p class="trash-count">3개</p>' in page
        assert "<b>노드 「현장」</b>" in page and '<small class="trash-sub">책 1권·글 1개·먼저 버린 글 1개</small>' in page
        assert "<b>연결 노드 「강의 책」</b>" in page
        row = re.search(r"<li>[^<]*<time[^>]*>[^<]*</time> <b>글 「먼저 버린 글」 · 책 「답사」</b>(.*?)</li>", page).group(1)
        assert "<button>" not in row and "노드 「현장」과 함께 휴지통에 있는 책의 글입니다." in row
        node_ref = re.search(r'name="node" value="(city/[^"]+)"', page.split("노드 「현장」")[0].rsplit("<li>", 1)[1] + page.split("노드 「현장」")[1]).group(1)
        c.post("/shelf/p/city/trash", data={"csrf": csrf, "node": node_ref})
        after = c.get("/shelf/p/city/trash").text
        assert '<p class="trash-count">2개</p>' in after and 'name="item" value="walk/20261009000000001-aaaaaa"' in after
        back = c.post("/shelf/p/city/trash", data={"csrf": csrf, "item": "walk/20261009000000001-aaaaaa"})
        assert "먼저 버린 글" in back.text and back.url.path == "/shelf/walk/20261009000000001-aaaaaa"


def test_edit_conflict_is_refused(server_proc):  # noqa: F811
    """동시 고치기: 고치기 폼을 연 뒤 다른 곳에서 저장했으면 덮어쓰지 않고 거절(적은 것은 보이게). 대화(category_edit)도 같은 검사."""
    import re  # noqa: PLC0415

    from test_web import _csrf  # noqa: PLC0415

    from magus.store import CategoryItem, Ref  # noqa: PLC0415

    base, data_dir, _ = server_proc({})
    store = LocalStore(data_dir)
    store.create_category("alice", "메모", "blank", "#1f2f5c", (), "common", category_id="notes")
    store.put_category_item("alice", CategoryItem("20261009000000001-aaaaaa", "notes", "처음 본문", "me", "제목", "author"))
    store.put_ref("alice", Ref(key="clack2012", status="unverified", bib={"title": "Gaining ground", "authors": "Clack, J."}, book="notes"))
    store.close()
    with httpx2.Client(base_url=base, follow_redirects=True, timeout=60) as c:
        form = c.get("/login?next=/shelf/notes/20261009000000001-aaaaaa/edit").text
        csrf = _csrf(form)
        assert 'class="card write-form" data-guard>' in form and "beforeunload" in form and "pageshow" in form
        stamp = re.search(r'name="base" value="([^"]+)"', form).group(1)
        other = LocalStore(data_dir)  # 다른 창(또는 대화)에서 먼저 저장
        other.patch_category_item("alice", "notes", "20261009000000001-aaaaaa", {"content": "다른 곳에서 고침"})
        other.close()
        late = c.post("/shelf/notes/20261009000000001-aaaaaa/edit", data={"csrf": csrf, "base": stamp, "title": "제목", "content": "내 고침"})
        assert late.status_code == 409 and "다른 곳에서 고쳐진 글입니다. 새로 열어 다시 고쳐 주세요." in late.text and ">내 고침</textarea>" in late.text
        assert LocalStore(data_dir).get_category_item("alice", "notes", "20261009000000001-aaaaaa").content == "다른 곳에서 고침"
        fresh = c.get("/shelf/notes/20261009000000001-aaaaaa/edit").text  # 새로 열면 저장된다
        new_stamp = re.search(r'name="base" value="([^"]+)"', fresh).group(1)
        ok = c.post("/shelf/notes/20261009000000001-aaaaaa/edit", data={"csrf": csrf, "base": new_stamp, "title": "제목", "content": "내 고침"})
        assert ok.status_code == 200 and "<p>내 고침</p>" in ok.text
        # 문헌 글(본문 = 메모)도 같다
        ref_form = c.get("/shelf/notes/clack2012/edit").text
        ref_stamp = re.search(r'name="base" value="([^"]+)"', ref_form).group(1)
        other = LocalStore(data_dir)
        other.set_ref_status("alice", "clack2012", "verified")
        other.close()
        assert c.post("/shelf/notes/clack2012/edit", data={"csrf": csrf, "base": ref_stamp, "content": "메모"}).status_code == 409


def test_category_edit_checks_conflict(store: LocalStore, settings):
    """대화의 category_edit(checked·parts)도 읽은 뒤 쓰기 전에 다른 저장이 있었으면 바꾸지 않는다(인자 추가 없이)."""
    import anyio  # noqa: PLC0415
    import pytest  # noqa: PLC0415
    from mcp import Client  # noqa: PLC0415

    from magus.server import build_server  # noqa: PLC0415
    from magus.store import Passage, Ref  # noqa: PLC0415
    from magus.store.base import EditConflict  # noqa: PLC0415

    store.create_category("alice", "문헌", "blank", "#1f2f5c", (), "common", category_id="refs-x")
    store.put_ref("alice", Ref(key="clack2012", status="unverified", bib={"title": "Gaining ground", "authors": "Clack, J."}, book="refs-x"),
                  passages=[Passage("쓸 부분", "근거", "p.1")])
    with pytest.raises(EditConflict):
        store.set_ref_status("alice", "clack2012", "verified", if_updated_at="2000-01-01T00:00:00.000Z")
    with pytest.raises(EditConflict):
        store.add_passages("alice", "clack2012", [Passage("새 부분", "", None)], if_updated_at="2000-01-01T00:00:00.000Z")
    real = store.get_ref

    def stale(user_id, key, floors=None):  # 도구가 읽은 뒤 다른 곳에서 저장된 것처럼(읽은 시각이 옛것)
        found = real(user_id, key, floors=floors)
        return Ref(**{**found.__dict__, "updated_at": "2000-01-01T00:00:00.000Z", "created_at": "2000-01-01T00:00:00.000Z"}) if found else None

    store.get_ref = stale  # type: ignore[method-assign]

    async def call() -> tuple[str, str]:
        async with Client(build_server(settings, store)) as c:
            checked = await c.call_tool("category_edit", {"item_id": "clack2012", "checked": True})
            parts = await c.call_tool("category_edit", {"item_id": "clack2012", "parts": [{"text": "또 다른 부분", "reason": "x"}]})
            return checked.content[0].text, parts.content[0].text

    checked, parts = anyio.run(call)
    assert "그사이 다른 곳(웹 등)에서 저장된 글이라 바꾸지 않았다." in checked and "그사이 다른 곳" in parts
    store.get_ref = real  # type: ignore[method-assign]
    assert store.get_ref("alice", "clack2012").status == "unverified" and len(store.get_passages("alice", "clack2012")) == 1


def test_help_texts_and_screen_names():
    """도움말(10번): 답할 수 없는 요청의 문장, 빈 창 첫 줄, '고치기' 화면 이름, 프로젝트 휴지통 화면, 넓은 화면에서 창을 오른쪽에 붙인다."""
    from magus.helpbot import HELP_STYLE, PREAMBLE, SCREENS, screen_key, widget  # noqa: PLC0415

    assert '"그건 답할 수 없습니다. Magus 사용법을 물어봐 주세요."' in PREAMBLE and "도움말에 없는 내용입니다." in PREAMBLE
    assert SCREENS[screen_key("/shelf/notes/20261009000000000-aaaaaa/edit")] == "고치기"
    assert screen_key("/shelf/trash") == "project_trash" and screen_key("/shelf/trash/notes") == "trash"
    assert SCREENS["trash"] == "책을 휴지통으로 옮기기"
    assert '<p class="help-hint">Magus 사용법을 물어보세요. 예: 글은 어떻게 고쳐요?</p>' in widget("c", "u")
    assert "body.help-open{padding-right:380px}" in HELP_STYLE and ".help-box{right:0;bottom:0" in HELP_STYLE


def test_small_things(server_proc):  # noqa: F811
    """작은 것(12번): 이름 없는 짧은 컨텍스트는 한 번만, 노드 설정의 '컨텍스트' 제목은 하나, 올린 파일 사용량의 뜻 한 줄,
    책 설정의 '🗑 휴지통으로'와 확인 화면 제목 '책을 휴지통으로 옮기기'. 주소는 그대로."""
    from magus.contexts import Context  # noqa: PLC0415

    base, data_dir, _ = server_proc({})
    store = LocalStore(data_dir)
    node = store.add_node("alice", "common", "현장")
    store.set_node_contexts("alice", "common", node.id, (Context("", "현장 메모다."),))
    store.create_category("alice", "메모", "blank", "#1f2f5c", (), "common", node.id, category_id="notes")
    store.close()
    with httpx2.Client(base_url=base, follow_redirects=True, timeout=60) as c:
        panel = c.get(f"/login?next=/shelf/p/common?node={node.id}").text.split('id="pp-node"')[1]
        assert panel.count("현장 메모다.") == 2  # 머리의 칩 하나 + 노드 설정 폼의 칸 하나(펼치는 칸에 또 나오지 않는다)
        assert '<span class="ctx ctx-chip">현장 메모다.</span>' in panel and "<h3>컨텍스트</h3>" not in panel
        files = c.get("/me/files").text
        assert "사용량에는 올린 파일, 글의 첨부, 올린 문서와 수정본, 휴지통에 있는 것이 모두 들어갑니다." in files
        settings = c.get("/shelf/edit/notes").text
        assert '<a class="trash-link" href="/shelf/trash/notes"><span aria-hidden="true">🗑</span> 휴지통으로</a>' in settings
        confirm = c.get("/shelf/trash/notes").text
        assert "<h1>책을 휴지통으로 옮기기</h1>" in confirm and "「메모」 책을 휴지통으로 옮길까요?" in confirm
