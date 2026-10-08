"""웹 프로젝트·지도(#95): 프로젝트 목록, 프로젝트 화면(지도 + 패널: 노드의 책장 → 책의 게시판), 지도 바꾸기(폼·스크립트),
책 옮기기·되돌리기, 옛 주소, 검색, 내려받기(zip), 격리."""

from __future__ import annotations

import io
import json
import re
import urllib.parse
import zipfile

import httpx2
import pytest
from test_http import FIXTURES  # noqa: F401
from test_web import _csrf, _login, fake_issuer, server_proc  # noqa: F401 - 픽스처

from magus.floors import COMMON
from magus.store import CategoryItem, Context, LocalStore

pytestmark = pytest.mark.anyio


def _seed(data_dir, user: str = "alice") -> dict[str, str]:
    store = LocalStore(data_dir)
    store.create_project(user, "도시는 어떻게 태어났나", project_id="city")
    store.write_chapter(user, "city", 1, "강가의 장날(Jacobs, 1969).", "x", title="장날")
    store.create_project(user, "강과 사람", project_id="river")
    person = store.create_category(user, "인물", "person", "#7a4e2d", ("시기",), "city")
    store.put_category_item(user, CategoryItem("20261007000000000-aaaaaa", person.id, "제인 제이콥스", "me", "제이콥스", "author"))
    case = store.create_category(user, "사례", "case", "#b8923a", (), COMMON)
    styles = store.create_category(user, "문체", "blank", "#6e1f2f", (), COMMON, contexts=(Context("문체", "문학적 부분이 마음에 드는 구절"),))
    ideas = store.create_category(user, "생각", "blank", "#1f2f5c", (), "city", contexts=(Context("생각 메모", "떠오른 생각을 적어 둔 메모다."),))
    store.put_category_item(user, CategoryItem("20261007000000001-bbbbbb", ideas.id, "도시는 서로를 찾는 곳", "me"))
    store.add_link_node(user, "city", COMMON, store.node_of_book(user, styles.id)[1])  # 「내 서재」의 문체로 가는 연결 노드
    person_node = store.node_of_book(user, person.id)[1]
    ideas_node = store.node_of_book(user, ideas.id)[1]
    store.close()
    return {"person": person.id, "case": case.id, "person_node": person_node, "ideas": ideas.id, "ideas_node": ideas_node}


def _query(response) -> dict[str, str]:
    return dict(urllib.parse.parse_qsl(urllib.parse.urlparse(str(response.url)).query))


def test_project_list_and_new_project(server_proc):  # noqa: F811
    base, data_dir, _ = server_proc({})
    _seed(data_dir)
    with httpx2.Client(base_url=base, follow_redirects=True, timeout=120) as c:
        listed = c.get("/login?next=/shelf").text
        csrf = _csrf(listed)
        names = re.findall(r'<span class="pname">([^<]+)</span>', listed)
        assert names[-1] == "내 서재" and set(names[:-1]) == {"도시는 어떻게 태어났나", "강과 사람"}  # 「내 서재」는 끝에
        assert listed.count("최근 수정 ") >= 3 and "노드 4 · 올린 원고 1장" in listed and "노드 1 · 원고 없음" in listed
        assert '<h2>+ 프로젝트</h2>' in listed and 'name="project" value="new"' in listed and 'action="/shelf/projects"' in listed
        assert c.post("/shelf/projects", data={"csrf": "틀림", "title": "x"}).status_code == 403
        assert "projecterr=empty" in str(c.post("/shelf/projects", data={"csrf": csrf, "title": "  "}).url)
        made = c.post("/shelf/projects", data={"csrf": csrf, "title": "다음 책 <b>메모</b>"})
        assert re.search(r"/shelf/p/[0-9a-f]{8}\?node=center&done=project$", str(made.url))
        assert "새 프로젝트를 만들었습니다." in made.text and '<h1 class="pm-title">다음 책 &lt;b&gt;메모&lt;/b&gt;</h1>' in made.text
        # 모든 프로젝트에서 찾기: 프로젝트 → 노드 · 책으로 묶는다. 누르면 그 노드·책이 열린 지도로
        found = c.get("/shelf", params={"q": "제이콥스"}).text
        assert '<h2><a href="/shelf/p/city">도시는 어떻게 태어났나</a>' in found and "찾은 프로젝트 1곳" in found
        assert re.search(r'<a href="/shelf/p/city\?node=[^"]+&amp;book=\d{17}-[0-9a-f]{6}">인물</a>', found)


def test_project_page_map_panel_and_board(server_proc):  # noqa: F811
    base, data_dir, _ = server_proc({})
    ids = _seed(data_dir)
    with httpx2.Client(base_url=base, follow_redirects=True, timeout=120) as c:
        c.get("/login?next=/shelf")
        page = c.get("/shelf/p/city").text
        # 지도: 노드는 링크(키보드·스크립트 없이도), 가운데 노드는 크게, 연결 노드는 원본 프로젝트, 선은 노드 아래 SVG
        assert '<a class="node center" href="/shelf/p/city?node=center" data-node="center"' in page
        assert f'data-node="{ids["person_node"]}"' in page and '<span class="nname">인물</span><span class="nsub">1개</span>' in page
        assert '<a class="node link"' in page and "연결 · 내 서재" in page  # 「내 서재」의 문체로 가는 연결 노드
        assert page.count('<g class="edge"') == 3 and '<svg class="edges" aria-hidden="true"' in page
        assert '<section class="map-list" aria-label="노드 목록">' in page and 'id="map-data"' in page
        assert '<details class="pm-new" id="new-node"><summary class="btn primary-ish">+ 노드</summary>' in page
        assert '<optgroup label="내 서재">' in page and '<optgroup label="강과 사람">' in page  # 연결 노드로 고를 다른 프로젝트의 노드
        assert '<h2 class="pp-title" id="pp-title" tabindex="-1">노드를 골라 주세요</h2>' in page and 'id="book-panel"' in page
        # 노드를 열면 패널에 그 노드의 정면 책장, 책을 열면 그 아래 게시판(iframe)
        node = c.get("/shelf/p/city", params={"node": ids["person_node"]}).text
        assert 'aria-current="true"' in node and 'aria-label="인물, 글 1개"' in node
        assert f'data-key="{ids["person"]}"' in node and f'href="/shelf/add?project=city&amp;node={ids["person_node"]}"' in node
        assert "<summary>노드 설정(이름·색·컨텍스트·선)</summary>" in node and "<h3>선</h3>" in node and "<h3>컨텍스트</h3>" in node
        assert '<span class="none">없음 — 컨텍스트가 없는 책은 AI가 일반 메모로 읽습니다.</span>' in node  # 노드 머리의 컨텍스트(#96)
        thoughts = c.get("/shelf/p/city", params={"node": ids["ideas_node"]}).text
        assert 'aria-label="생각, 컨텍스트 생각 메모, 글 1개"' in thoughts
        assert '<span class="band top" aria-hidden="true">생각 메모</span>' in thoughts  # 책등 위 띠 = 컨텍스트 이름
        book = c.get("/shelf/p/city", params={"node": ids["person_node"], "book": ids["person"]}).text
        assert f'<iframe class="bp-frame" title="인물" src="/shelf/{ids["person"]}"></iframe>' in book
        assert f'data-node="{ids["person_node"]}" data-book="{ids["person"]}"' in book
        by_at = c.get("/shelf/p/city", params={"at": f"/shelf/{ids['person']}/20261007000000000-aaaaaa"}).text  # 게시판 자리 주소만으로
        assert f'src="/shelf/{ids["person"]}/20261007000000000-aaaaaa"' in by_at and 'aria-label="인물, 글 1개"' in by_at
        fragment = c.get("/shelf/p/city/panel", params={"node": "center"}).text  # 스크립트가 노드를 열 때 받는 패널
        assert fragment.startswith('<div class="pp-node" id="pp-node" data-node="center">') and 'data-key="ms.city"' in fragment
        # 연결 노드: 원본의 책이 보이고, 책 추가는 원본 노드로
        link = next(n for n in LocalStore(data_dir).get_map("alice", "city").nodes if n.link)
        linked = c.get("/shelf/p/city", params={"node": link.id}).text
        assert "연결 노드: 「내 서재」의 「문체」 노드를 가리킵니다." in linked and 'href="/shelf/add?project=common&amp;node=' in linked
        # 목록 보기(휴대폰·키보드): 노드 → 책
        listed = c.get("/shelf/p/city", params={"view": "list"}).text
        assert '<div class="pm" data-view="list">' in listed and f'<a href="/shelf/p/city?node={ids["person_node"]}&amp;book={ids["person"]}#book-panel">인물</a>' in listed
        assert c.get("/shelf/p/nothing").status_code == 404
        # 프로젝트 화면 안에서 찾기: 노드 이름·책 이름·게시판 내용
        found = c.get("/shelf/p/city", params={"q": "제이콥스"}).text
        assert '<section class="pm-results" aria-label="찾은 것">' in found and "<mark>제이콥스</mark>" in found


def test_old_addresses_and_panel_requests(server_proc):  # noqa: F811
    base, data_dir, _ = server_proc({})
    ids = _seed(data_dir)
    with httpx2.Client(base_url=base, timeout=120) as c:
        c.get("/login?next=/shelf", follow_redirects=True)
        nav = {"sec-fetch-dest": "document", "sec-fetch-mode": "navigate"}
        # 주소창으로 책 화면을 바로 열면 그 책이 있는 프로젝트 지도로(그 노드·그 책이 열린 채)
        direct = c.get(f"/shelf/{ids['person']}?q=x", headers=nav)
        assert direct.status_code == 303 and direct.headers["location"] == "/shelf?" + urllib.parse.urlencode({"at": f"/shelf/{ids['person']}?q=x"})
        located = c.get(direct.headers["location"])
        assert located.status_code == 303 and located.headers["location"].startswith(f"/shelf/p/city?book={ids['person']}&at=")
        assert c.get("/shelf/floor/city").headers["location"] == "/shelf/p/city"  # 옛 층 주소
        assert c.get("/shelf", params={"floor": "river", "done": "trash"}).headers["location"] == "/shelf/p/river?done=trash"
        assert c.get("/shelf/doc/x/docx", headers=nav).status_code == 404  # 내려받기는 넘기지 않는다
        assert c.get(f"/shelf/{ids['person']}").status_code == 200  # Sec-Fetch 머리가 없는 브라우저는 예전처럼
        # 게시판 자리(iframe) 안: 머리(메뉴) 없이. 그 안에서 프로젝트 화면이 열리면 바깥 화면을 그 주소로
        panel = c.get(f"/shelf/{ids['person']}", headers={"sec-fetch-dest": "iframe"}).text
        assert '<body class="embed">' in panel and '<header class="site">' not in panel
        out = c.get("/shelf/p/city?done=trash", headers={"sec-fetch-dest": "iframe"}).text
        assert '<a id="go" href="/shelf/p/city?done=trash" target="_top">' in out and "window.top.location.replace" in out
        edited = c.post(f"/shelf/edit/{ids['person']}", data={"csrf": _csrf(c.get("/shelf").text), "name": "사람", "color": "#7a4e2d"})
        assert edited.headers["location"] == f"/shelf/p/city?book={ids['person']}&done=edit&c={ids['person']}"


def test_map_edits_with_forms_and_script(server_proc):  # noqa: F811
    base, data_dir, _ = server_proc({})
    ids = _seed(data_dir)
    with httpx2.Client(base_url=base, follow_redirects=True, timeout=120) as c:
        csrf = _csrf(c.get("/login?next=/shelf").text)
        post = "/shelf/p/city/map"
        assert c.post(post, data={"csrf": "틀림", "action": "add_node", "name": "x"}).status_code == 403
        # 폼(스크립트 없이): 만들고 나면 그 노드가 열린 지도로, 한 줄 안내
        made = c.post(post, data={"csrf": csrf, "action": "add_node", "name": "골목", "x": "300", "y": "-200"})
        node = _query(made)["node"]
        assert "노드 「골목」을 만들었습니다." in made.text and 'style="left:300.0px;top:-200.0px"' in made.text
        taken = c.post(post, data={"csrf": csrf, "action": "add_node", "name": "골목"})
        assert "같은 이름의 노드 「골목」이 이미 있습니다." in taken.text
        renamed = c.post(post, data={"csrf": csrf, "action": "rename", "node": node, "name": "골목길"})
        assert "노드 이름을 「골목길」로 바꿨습니다." in renamed.text and '<span class="nname">골목길</span>' in renamed.text
        colored = c.post(post, data={"csrf": csrf, "action": "color", "node": node, "color": "#2f6db5"})
        assert "노드 색을 바꿨습니다." in colored.text and "--nc:#2f6db5;--nfg:#ffffff" in colored.text
        joined = c.post(post, data={"csrf": csrf, "action": "connect", "node": node, "other": ids["person_node"]})
        assert "선을 이었습니다." in joined.text and joined.text.count('<g class="edge"') == 5
        cut = c.post(post, data={"csrf": csrf, "action": "disconnect", "node": node, "other": "center"})
        assert "선을 끊었습니다." in cut.text and cut.text.count('<g class="edge"') == 4
        # 노드 만들 때 컨텍스트 단추·직접 적기, 노드 설정의 컨텍스트(#96)
        with_ctx = c.post(post, data={"csrf": csrf, "action": "add_node", "name": "현장", "ctx_pick": "ctx-note", "ctx_new": "현장 메모다."})
        assert "노드 「현장」을 만들었습니다." in with_ctx.text and '<details class="ctx"><summary>생각 메모</summary>' in with_ctx.text
        field = _query(with_ctx)["node"]
        changed = c.post(post, data={"csrf": csrf, "action": "contexts", "node": field, "ctx_name": "", "ctx_text": "고친 현장 메모",
                                     "ctx_from": ""})
        assert "노드의 컨텍스트를 바꿨습니다." in changed.text and "<p>고친 현장 메모</p>" in changed.text
        too_long = c.post(post, data={"csrf": csrf, "action": "contexts", "node": field, "ctx_new": "가" * 501})
        assert "컨텍스트를 저장하지 못했습니다." in too_long.text
        c.post(post, data={"csrf": csrf, "action": "trash", "node": field})
        busy = c.post(post, data={"csrf": csrf, "action": "trash", "node": ids["person_node"]})
        assert "책이 꽂힌 노드는 휴지통으로 옮길 수 없습니다." in busy.text
        linked = c.post(post, data={"csrf": csrf, "action": "add_link", "target": "river:center"})
        assert "연결 노드 「강과 사람」을 만들었습니다. 여기서 보거나 넣으면 원본에 들어갑니다." in linked.text
        gone = c.post(post, data={"csrf": csrf, "action": "trash", "node": node})
        assert "노드를 휴지통으로 옮겼습니다." in gone.text and 'data-node="' + node not in gone.text
        # 스크립트(fetch, JSON): 노드 옮기기는 위치만 저장, 잘못되면 저자에게 보일 문장
        headers = {"accept": "application/json"}
        moved = c.post(post, data={"csrf": csrf, "action": "move_node", "node": "center", "x": "12.5", "y": "-8"}, headers=headers)
        assert moved.json() == {"ok": True}
        wrong = c.post(post, data={"csrf": csrf, "action": "trash", "node": "center"}, headers=headers)
        assert wrong.status_code == 400 and wrong.json() == {"ok": False, "error": "가운데 노드는 휴지통으로 옮길 수 없습니다."}
        assert c.post(post, data={"csrf": "x", "action": "move_node"}, headers=headers).json()["ok"] is False
    store = LocalStore(data_dir)
    center = store.get_map("alice", "city").nodes[0]
    assert (center.x, center.y) == (12.5, -8.0)
    assert sorted(t.id for t in store.list_trash("alice") if t.kind == "node") == sorted([f"city/{node}", f"city/{field}"])
    store.close()


def test_move_books_between_nodes_and_undo(server_proc):  # noqa: F811
    base, data_dir, _ = server_proc({})
    ids = _seed(data_dir)
    with httpx2.Client(base_url=base, follow_redirects=True, timeout=120) as c:
        csrf = _csrf(c.get("/login?next=/shelf").text)
        here = f"/shelf/p/city?node={ids['person_node']}"
        assert c.post("/shelf/move", data={"csrf": "틀림", "book": ids["person"], "to": "city:center"}).status_code == 403
        # 패널의 책을 지도의 다른 노드로 끌어 놓기 = POST /shelf/move(to=프로젝트:노드)
        moved = c.post("/shelf/move", data={"csrf": csrf, "book": ids["person"], "to": f"city:{ids['ideas_node']}", "next": here})
        assert "moved=" in str(moved.url) and "「인물」을 노드 「생각」으로 옮겼습니다." in moved.text and 'action="/shelf/undo"' in moved.text
        move_id = _query(moved)["moved"]
        undone = c.post("/shelf/undo", data={"csrf": csrf, "move": move_id, "next": here})
        assert "「인물」을 원래 자리(「도시는 어떻게 태어났나」 · 노드 「인물」)로 되돌렸습니다." in undone.text
        assert "되돌릴 수 있는 것은 마지막으로 옮긴 것뿐입니다." in c.post("/shelf/undo", data={"csrf": csrf, "move": move_id, "next": here}).text
        # 다른 프로젝트로(책 설정의 '위치' = 키보드 길): 받는 프로젝트 지도로, 그 책이 열린 채
        edit = c.get(f"/shelf/edit/{ids['person']}").text
        assert '<h2>위치</h2>' in edit and f'<option value="city:{ids["person_node"]}" selected>도시는 어떻게 태어났나 · 인물</option>' in edit
        dest = c.post("/shelf/move", data={"csrf": csrf, "book": ids["person"], "to": "river", "next": "dest"})
        assert str(dest.url).startswith(f"{base}/shelf/p/river?") and f"book={ids['person']}" in str(dest.url)
        assert "「인물」을 「강과 사람」 · 노드 「인물」로 옮겼습니다." in dest.text
        # 같은 이름이 받는 프로젝트에 있으면 옮기지 않는다
        store = LocalStore(data_dir)
        store.create_category("alice", "인물", "person", "#7a4e2d", (), COMMON)
        store.close()
        clash = c.post("/shelf/move", data={"csrf": csrf, "book": ids["person"], "to": COMMON, "next": "/shelf/p/river"})
        assert "「내 서재」에 같은 이름 「인물」이 있어 옮기지 못했습니다. 이름을 바꾼 뒤 옮겨 주세요." in clash.text
        evil = c.post("/shelf/move", data={"csrf": csrf, "book": ids["case"], "to": "city", "next": "https://evil.example/x"})
        assert str(evil.url).startswith(f"{base}/shelf?moved=")  # 돌아갈 주소는 책장 안만
    # 두 프로젝트가 같은 문헌을 쓰게 되어 「내 서재」로 옮긴 문헌: 항목에 옮긴 시각과 이유
    from magus.melchior.bibliography import import_bibliography  # noqa: PLC0415

    store = LocalStore(data_dir)
    line = "Jacobs, J. (1969). The economy of cities. Random House."
    import_bibliography(store, "alice", line, "city")
    assert import_bibliography(store, "alice", line, "river").shared == ["jacobs1969"]
    store.close()
    with httpx2.Client(base_url=base, follow_redirects=True, timeout=120) as c:
        c.get("/login?next=/shelf")
        library = LocalStore(data_dir).source_book("alice", COMMON)
        refs = c.get(f"/shelf/{library}").text  # 「내 서재」의 문헌 책(없어서 만든 「참고문헌」)
        assert "「도시는 어떻게 태어났나」·「강과 사람」 원고가 함께 쓰는 문헌이라 「내 서재」로 옮김" in refs


def test_export_zip(server_proc):  # noqa: F811
    base, data_dir, _ = server_proc({})
    _seed(data_dir)
    with httpx2.Client(base_url=base, follow_redirects=True, timeout=120) as c:
        c.get("/login?next=/shelf")
        got = c.get("/shelf/p/city/export.zip")
        assert got.status_code == 200 and got.headers["content-type"] == "application/zip"
        assert "attachment" in got.headers["content-disposition"] and "UTF-8''" in got.headers["content-disposition"]
        names = zipfile.ZipFile(io.BytesIO(got.content)).namelist()
        assert "README.md" in names and "도시는 어떻게 태어났나/지도.json" in names
        assert "도시는 어떻게 태어났나/가운데 노드/원고/장/001 장날.md" in names
        assert any(n.startswith("도시는 어떻게 태어났나/인물/인물/") and n.endswith(" 제이콥스.md") for n in names)
        assert "도시는 어떻게 태어났나/생각/생각/컨텍스트.md" in names  # 책의 컨텍스트(#96)
        assert "도시는 어떻게 태어났나/연결 · 문체/연결.md" in names
        z = zipfile.ZipFile(io.BytesIO(got.content))
        item = z.read(next(n for n in names if n.endswith(" 제이콥스.md"))).decode("utf-8")
        assert item.startswith("---\n날짜: ") and "\n제목: 제이콥스\n작성자: 저자\n" in item and item.rstrip().endswith("제인 제이콥스")
        mapped = json.loads(z.read("도시는 어떻게 태어났나/지도.json"))
        assert mapped["프로젝트"] == "도시는 어떻게 태어났나" and any(set(e["이음"]) == {"가운데", "인물"} for e in mapped["선"])
        assert [n["이름"] for n in mapped["노드"]][0] == "가운데" and any(n["연결"] for n in mapped["노드"])
        everything = zipfile.ZipFile(io.BytesIO(c.get("/shelf/export.zip").content)).namelist()
        assert {n.split("/")[0] for n in everything} >= {"README.md", "도시는 어떻게 태어났나", "강과 사람", "내 서재"}


def test_map_pages_are_per_user(server_proc, fake_issuer):  # noqa: F811
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
        assert bob.get("/shelf/p/city").status_code == 404  # 앨리스의 프로젝트
        assert bob.get("/shelf/p/city/panel", params={"node": "center"}).status_code == 404
        tried = bob.post("/shelf/p/city/map", data={"csrf": csrf, "action": "add_node", "name": "침입"}, headers={"accept": "application/json"})
        assert tried.status_code == 400 and tried.json()["ok"] is False
        tried = bob.post("/shelf/move", data={"csrf": csrf, "book": alice_ids["person"], "to": COMMON, "next": "/shelf"})
        assert tried.status_code == 303 and "moveerr=unknown_category" in tried.headers["location"]
        assert "moveerr=" in bob.post("/shelf/undo", data={"csrf": csrf, "move": "x", "next": "/shelf"}).headers["location"]
        zipped = zipfile.ZipFile(io.BytesIO(bob.get("/shelf/export.zip").content)).namelist()
        assert not any("도시는" in n for n in zipped) and bob.get("/shelf/p/city/export.zip").status_code == 404
    after = {p: p.read_bytes() for p in (data_dir / "users" / "alice").rglob("*.json")}
    assert before == after
