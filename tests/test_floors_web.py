"""웹 책장의 층(#93): 책장 전체(3D)·한 층 화면·끌어 옮기기(POST)·위치 설정·되돌리기·층 만들기·검색·격리."""

from __future__ import annotations

import re
import urllib.parse

import httpx2
import pytest
from test_http import FIXTURES  # noqa: F401
from test_web import _csrf, _login, fake_issuer, server_proc  # noqa: F401 - 픽스처

from magus.floors import COMMON
from magus.store import CategoryItem, Idea, LocalStore

pytestmark = pytest.mark.anyio


def _seed(data_dir, user: str = "alice") -> dict[str, str]:
    store = LocalStore(data_dir)
    store.create_project(user, "도시는 어떻게 태어났나", project_id="city")
    store.write_chapter(user, "city", 1, "강가의 장날(Jacobs, 1969).", "x", title="장날")
    store.create_project(user, "강과 사람", project_id="river")
    person = store.create_category(user, "인물", "person", "#7a4e2d", ("시기",), "city")
    store.put_category_item(user, CategoryItem("20261007000000000-aaaaaa", person.id, "제인 제이콥스", "me", "제이콥스", "author"))
    case = store.create_category(user, "사례", "case", "#b8923a", (), COMMON)
    store.add_ideas(user, [Idea("20261007000000001-bbbbbb", "도시는 서로를 찾는 곳", "thought", "me", floor="city")])
    store.close()
    return {"person": person.id, "case": case.id}


def test_overview_floor_page_move_and_undo(server_proc):  # noqa: F811
    base, data_dir, _ = server_proc({})
    ids = _seed(data_dir)
    with httpx2.Client(base_url=base, follow_redirects=True, timeout=120) as c:
        shelf = c.get("/login?next=/shelf").text
        csrf = _csrf(shelf)
        # 책장 전체: 공용이 맨 위, 그 아래 작업물 층. 선반 가장자리에 이름·제목·최근 수정, 층마다 작은 책
        names = re.findall(r'<span class="fl-name">([^<]+)</span>', shelf)
        assert names == ["공용", "1층", "2층"]
        assert '<span class="fl-title" title="도시는 어떻게 태어났나">도시는 어떻게 태어났나</span>' in shelf
        assert shelf.count("최근 수정 ") >= 3 and 'href="/shelf?floor=city"' in shelf
        assert f'data-book="{ids["person"]}" data-from="city"' in shelf and 'aria-label="인물, 항목 1개"' in shelf
        assert 'data-drop-floor="river"' in shelf and 'id="move-form"' in shelf and "MagusShelf" in shelf
        assert "prefers-reduced-motion" in shelf  # 움직임 줄이기면 바로 넘어간다
        # 하나의 장: 바깥 틀은 한 번, 층은 그 안의 칸(뒤판 등), 책은 상자(옆면·윗면), 장 안에도 책 추가 자리
        assert shelf.count('class="pl cab-side"') == 1 and shelf.count('class="pl c-back"') == 3
        assert 'class="pl mb-side"' in shelf and '<a class="madd" href="/shelf/add?floor=city"' in shelf
        # 한 화면 책장: 옛 한 층 화면은 그 층으로 다가간 상태로. 층 버튼 줄(끌어 놓을 자리), 층 안내, 책 추가
        floor_resp = c.get("/shelf/floor/city")
        assert str(floor_resp.url) == f"{base}/shelf?floor=city"
        floor = floor_resp.text
        assert '<div class="scene" data-floor="city">' in floor and '<a class="all-shelf" href="/shelf" data-go="">전체 책장</a>' in floor
        assert '<a href="/shelf?floor=city" data-go="city" data-drop-floor="city" aria-current="true">1층</a>' in floor
        assert '<p class="floor-meta" data-meta="city"><b>1층 · 도시는 어떻게 태어났나</b> · 최근 수정' in floor
        assert f'data-book="{ids["person"]}" data-from="city"' in floor and 'href="/shelf/add?floor=city"' in floor
        assert c.get("/shelf/floor/nothing").status_code == 404 and '<div class="scene">' in c.get("/shelf?floor=nothing").text
        # 책의 고유 주소: 그 층으로 다가가 그 책이 열린 상태(장면 아래 패널에 그 책 화면)
        opened = c.get("/shelf", params={"floor": "city", "book": ids["person"]}).text
        assert f'<div class="scene" data-floor="city" data-book="{ids["person"]}">' in opened
        assert f'<iframe class="bp-frame" title="인물" src="/shelf/{ids["person"]}"></iframe>' in opened
        by_at = c.get("/shelf", params={"at": f"/shelf/{ids['person']}/x"}).text  # 패널 안 주소만 주어도 층·책을 찾는다
        assert f'data-floor="city" data-book="{ids["person"]}" data-at="/shelf/{ids["person"]}/x"' in by_at
        assert '<section class="book-panel" id="book-panel" aria-labelledby="bp-title" hidden>' in floor
        # 끌어 놓기 = POST /shelf/move(CSRF). 옮긴 뒤 안내와 되돌리기
        assert c.post("/shelf/move", data={"csrf": "틀림", "book": ids["person"], "to": COMMON}).status_code == 403
        moved = c.post("/shelf/move", data={"csrf": csrf, "book": ids["person"], "to": COMMON, "next": "/shelf?floor=city"})
        assert str(moved.url).startswith(f"{base}/shelf?floor=city&moved=")
        assert "「인물」을 공용으로 옮겼습니다." in moved.text and 'action="/shelf/undo"' in moved.text
        assert f'data-book="{ids["person"]}" data-from="common"' in moved.text  # 1층에서 빠져 공용에 꽂혔다(한 화면이라 모든 층이 보인다)
        move_id = urllib.parse.parse_qs(urllib.parse.urlparse(str(moved.url)).query)["moved"][0]
        undone = c.post("/shelf/undo", data={"csrf": csrf, "move": move_id, "next": "/shelf?floor=city"})
        assert "「인물」을 원래 자리(1층)로 되돌렸습니다." in undone.text and f'data-book="{ids["person"]}"' in undone.text
        again = c.post("/shelf/undo", data={"csrf": csrf, "move": move_id, "next": "/shelf?floor=city"})
        assert "되돌릴 수 있는 것은 마지막으로 옮긴 것뿐입니다." in again.text
        # 같은 이름이 받는 층에 있으면 옮기지 않는다
        store = LocalStore(data_dir)
        store.create_category("alice", "인물", "person", "#7a4e2d", (), COMMON)
        store.close()
        clash = c.post("/shelf/move", data={"csrf": csrf, "book": ids["person"], "to": COMMON, "next": "/shelf"})
        assert "공용에 같은 이름 「인물」이 있어 옮기지 못했습니다. 이름을 바꾼 뒤 옮겨 주세요." in clash.text
        # 기본 카테고리: 위치 설정(키보드 길)으로 옮기면 받는 층 화면으로. 주소 이름이 그 층의 것으로 바뀐다
        edit = c.get("/shelf/edit/ideas.city").text
        assert '<h2>위치</h2>' in edit and '<option value="city" selected>1층 · 도시는 어떻게 태어났나</option>' in edit
        assert "받는 층에 같은 기본 카테고리가 있으면 하나로 합쳐집니다." in edit
        dest = c.post("/shelf/move", data={"csrf": csrf, "book": "ideas.city", "to": "river", "next": "dest"})
        assert str(dest.url).startswith(f"{base}/shelf?floor=river&moved=")
        assert "「생각」을 2층의 생각과 합쳤습니다(항목 1개)." in dest.text
        assert c.get("/shelf/ideas.city").status_code == 404 and "도시는 서로를 찾는 곳" in c.get("/shelf/ideas.river").text
        # 돌아갈 주소는 책장 안만
        evil = c.post("/shelf/move", data={"csrf": csrf, "book": ids["case"], "to": "city", "next": "https://evil.example/x"})
        assert str(evil.url).startswith(f"{base}/shelf?moved=")
        zoom = c.get("/shelf", params={"zoom": "city", "next": "//evil.example"}).text  # 옛 검색 결과 주소
        assert '<div class="scene" data-floor="city">' in zoom
        # 층 만들기(원고 없는 빈 층)
        assert "floorerr=empty" in str(c.post("/shelf/floors", data={"csrf": csrf, "title": "  "}).url)
        made = c.post("/shelf/floors", data={"csrf": csrf, "title": "다음 책 <b>메모</b>"})
        assert "새 층을 만들었습니다." in made.text and "<b>3층 · 다음 책 &lt;b&gt;메모&lt;/b&gt;</b>" in made.text
        assert "원고가 아직 없습니다." in made.text
        # 검색: 층 → 카테고리로 묶고, 결과를 누르면 그 층으로 다가간다(data-result-floor)
        found = c.get("/shelf", params={"q": "제이콥스"}).text
        assert 'data-result-floor="city"' in found and f'<a href="/shelf/{ids["person"]}">인물</a>' in found
        assert "찾는 말이 없는 층:" in found
        # 두 작업물이 같은 문헌을 쓰게 되어 공용으로 옮긴 문헌: 항목에 옮긴 시각과 이유(#93-a 더함)
        from magus.melchior.bibliography import import_bibliography  # noqa: PLC0415

        store = LocalStore(data_dir)
        line = "Jacobs, J. (1969). The economy of cities. Random House."
        import_bibliography(store, "alice", line, "city")
        assert import_bibliography(store, "alice", line, "river").shared == ["jacobs1969"]
        store.close()
        refs = c.get("/shelf/refs.common").text
        assert "공용으로 옮김(" in refs and "1층 「도시는 어떻게 태어났나」·2층 「강과 사람」 원고가 함께 쓰는 문헌이라 공용으로 옮김" in refs


def test_one_view_direct_addresses_and_panel(server_proc):  # noqa: F811
    base, data_dir, _ = server_proc({})
    ids = _seed(data_dir)
    with httpx2.Client(base_url=base, timeout=120) as c:
        c.get("/login?next=/shelf", follow_redirects=True)
        # 주소창으로 책 화면을 바로 열면(브라우저가 Sec-Fetch-Dest: document를 붙인다) 한 화면 책장의 그 책으로
        nav = {"sec-fetch-dest": "document", "sec-fetch-mode": "navigate"}
        direct = c.get(f"/shelf/{ids['person']}?q=x", headers=nav)
        assert direct.status_code == 303 and direct.headers["location"] == "/shelf?" + urllib.parse.urlencode({"at": f"/shelf/{ids['person']}?q=x"})
        assert c.get("/shelf/floor/city", headers=nav).headers["location"] == "/shelf?floor=city"  # 옛 한 층 화면은 그 층으로
        assert c.get("/shelf/doc/x/docx", headers=nav).status_code == 404  # 내려받기는 넘기지 않는다
        assert c.get(f"/shelf/{ids['person']}").status_code == 200  # Sec-Fetch 머리가 없는 브라우저는 예전처럼
        # 패널(iframe) 안: 머리(메뉴) 없이
        panel = c.get(f"/shelf/{ids['person']}", headers={"sec-fetch-dest": "iframe"}).text
        assert '<body class="embed">' in panel and '<header class="site">' not in panel and "<h1>인물</h1>" in panel
        # 패널 안에서 책장 주소가 열리면(저장·휴지통 뒤) 바깥 화면을 그 주소로
        out = c.get("/shelf?floor=city&done=trash", headers={"sec-fetch-dest": "iframe"}).text
        assert '<a id="go" href="/shelf?floor=city&amp;done=trash" target="_top">' in out and "window.top.location.replace" in out
        # 고치기 뒤 돌아오는 주소에는 그 책이 열려 있다
        edited = c.post(f"/shelf/edit/{ids['person']}", data={"csrf": _csrf(c.get("/shelf").text), "name": "사람", "color": "#7a4e2d"})
        assert edited.headers["location"] == f"/shelf?floor=city&book={ids['person']}&done=edit&c={ids['person']}"


def test_cabinet_rows_break_where_books_no_longer_fit():
    from magus.webfloors import row_breaks, with_shelves  # noqa: PLC0415

    assert row_breaks([38] * 5, 258) == set()  # 5권 + 사이 4칸 = 206px
    widths = [54] * 6  # 4권이면 228px, 5권째는 286px라 모바일 칸(258px)에서 줄을 바꾼다. 데스크톱 칸(548px)에는 다 들어간다
    assert row_breaks(widths, 258) == {4} and row_breaks(widths, 548) == set()
    rows = with_shelves([f"<li>{i}</li>" for i in range(6)], widths)
    assert rows.count('<li class="brk m" aria-hidden="true">') == 1 and rows.index('class="brk m"') < rows.index("<li>4</li>")


def test_floor_pages_are_per_user(server_proc, fake_issuer):  # noqa: F811
    issuer, issuer_state, _ = fake_issuer
    base, data_dir, _ = server_proc({
        "PUBLIC_URL": "http://127.0.0.1:{port}", "AUTH_ISSUER": issuer, "ALLOWED_USERS": "sub-alice=alice,sub-bob=bob",
        "SESSION_SECRET": "x" * 40, "WEB_CLIENT_ID": "web-client",
    })
    alice_ids = _seed(data_dir, "alice")
    store = LocalStore(data_dir)
    store.create_project("bob", "밥의 책", project_id="bobs")
    store.close()
    before = {p: p.read_bytes() for p in (data_dir / "users" / "alice").rglob("*.json")}
    with httpx2.Client(base_url=base, timeout=120) as bob:
        assert _login(bob, issuer_state, "sub-bob").status_code == 303
        csrf = _csrf(bob.get("/shelf").text)
        page = bob.get("/shelf").text
        assert "도시는 어떻게" not in page and "인물" not in page
        assert bob.get("/shelf/floor/city").status_code == 404  # 앨리스의 층
        tried = bob.post("/shelf/move", data={"csrf": csrf, "book": alice_ids["person"], "to": COMMON, "next": "/shelf"})
        assert tried.status_code == 303 and "moveerr=unknown_category" in tried.headers["location"]
        tried = bob.post("/shelf/move", data={"csrf": csrf, "book": "ideas.city", "to": COMMON, "next": "/shelf"})
        assert "moveerr=unknown_floor" in tried.headers["location"]
        assert "moveerr=" in bob.post("/shelf/undo", data={"csrf": csrf, "move": "x", "next": "/shelf"}).headers["location"]
    after = {p: p.read_bytes() for p in (data_dir / "users" / "alice").rglob("*.json")}
    assert before == after
