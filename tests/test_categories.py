"""책(#92 '저자가 만든 카테고리' → #96 모든 책)·책 색·글 제목·컨텍스트.

- 규칙: 이름(예약어·중복·길이·글자·숫자만·개수), 색(기본 색 이름·#RRGGBB만, 그 밖은 거부), 제목 기본값.
- 저장: 파일이 원본(schema_version), reindex로 다시 만든다. 휴지통은 옮기고 되살린다.
- 도구: category_* 일곱 개(글 넣기·찾기·지우기 포함), 제목(기본값 '매번 묻기'면 먼저 묻게 한다), 컨텍스트 머리.
- 웹: 노드에 꽂힌 책, 만들기(컨텍스트 단추)·고치기(그 자리에서 고치기·자주 쓰는 컨텍스트로 등록)·휴지통·내 색·바로 적기,
  주입 시도, 사용자 격리.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import httpx2
import pytest
from mcp import Client
from test_http import FIXTURES  # noqa: F401
from test_web import _csrf, _login, fake_issuer, server_proc  # noqa: F401 - 픽스처

from magus import cli
from magus.category.rules import (
    MAX_CATEGORIES, NAME_MAX, PALETTE, check_name, name_key, parse_color,
)
from magus.config import Settings
from magus.server import build_server
from magus.store import CategoryItem, Context, LocalStore, SavedContext, ShelfSettings
from magus.webshelf import contrast, text_color
from tests.conftest import make_book

pytestmark = pytest.mark.anyio


def _text(result) -> str:
    return "\n".join(block.text for block in result.content)


# ---- 규칙 ----------------------------------------------------------------------------------

def test_name_rules():
    taken = {name_key("사례"): "사례"}
    assert check_name("  인물  ", taken) == "인물"
    assert check_name("Ancient Rome", taken) == "Ancient Rome" and check_name("강의 준비 2026", taken) == "강의 준비 2026"
    assert check_name("인물 카테고리", taken) == "인물"  # 끝의 '카테고리'는 뗀다
    for ok in ("생각", "문 체", "원고", "문헌"):  # #96: 옛 기본 책 이름도 여느 책 이름
        assert check_name(ok, taken) == ok
    for bad, why in (
        ("전체", "정해진 이름"), ("확인요청", "정해진 이름"), ("책장 카테고리", "정해진 이름"), ("컨텍스트", "정해진 이름"),
        ("카테고리", "정해진 이름"), ("Casper", "정해진 이름"), ("책", "정해진 이름"),
        ("사례 카테고리", "이미 있습니다"), ("사 례", "이미 있습니다"), ("가" * (NAME_MAX + 1), f"{NAME_MAX}자까지"),
        ("<b>굵게</b>", "쓸 수 없는 글자"), ('따옴표"', "쓸 수 없는 글자"), ("2026", "숫자만"), ("   ", "비어 있습니다"),
    ):
        with pytest.raises(ValueError, match=why):
            check_name(bad, taken)


def test_colors_accept_names_and_hex_only():
    assert parse_color("빨강") == parse_color("빨간색") == parse_color("red") == parse_color(" 빨간 ") == "#b3261e"
    assert parse_color("짙은 초록") == parse_color("짙은초록") == "#1f4a3a" and parse_color("남색") == "#1f2f5c"
    assert parse_color("#B22222") == "#b22222"
    for bad in ("#fff", "#12345g", "red;background:url(x)", "#b22222;}", "</style>", "rgb(1,2,3)", "", "보라빛 하늘"):
        with pytest.raises(ValueError, match="기본 색 이름"):
            parse_color(bad)
    assert len(PALETTE) == 18 and len({h for _, h in PALETTE}) == 18


def test_text_color_always_readable():
    """글자색은 어떤 책 색에서도 4.5:1 이상(기본 색 격자와 직접 고른 색 모두)."""
    samples = [h for _, h in PALETTE] + [f"#{v:02x}{v:02x}{v:02x}" for v in range(0, 256, 5)] + ["#767676", "#777777", "#5f8f3f"]
    for color in samples:
        assert contrast(color, text_color(color)) >= 4.5, color


# ---- 저장 ----------------------------------------------------------------------------------

def test_store_files_are_source_with_schema_version(store: LocalStore, data_dir: Path):
    c = store.create_category("alice", "사례", "case", "#b3261e", ("시기", "장소", "출처"))
    item = store.put_category_item("alice", CategoryItem("20261006000000000-aaaaaa", c.id, "강가 장날", "me", "장날", "author",
                                                         {"시기": "1850년대"}, ("예시",), (("book", 3),)))
    folder = data_dir / "users" / "alice" / "shelf" / "categories" / c.id
    record = json.loads((folder / "category.json").read_text(encoding="utf-8"))
    saved = json.loads((folder / "items" / f"{item.id}.json").read_text(encoding="utf-8"))
    assert record["schema_version"] == 1 and record["name"] == "사례" and record["fields"] == ["시기", "장소", "출처"]
    assert saved["schema_version"] == 1 and saved["chapters"] == [{"project": "book", "number": 3}] and saved["title_by"] == "author"
    with pytest.raises(ValueError):
        store.create_category("alice", "x", "blank", "red", ())
    with pytest.raises(ValueError):
        store.update_category("alice", c.id, color="#fff;}")
    store.reindex()  # 인덱스는 파일에서 다시 만든다
    [again] = store.list_categories("alice")
    assert again.items == 1 and store.list_category_items("alice", c.id)[0].fields == {"시기": "1850년대"}
    assert store.search_fts("alice", ["category"], '"장날"', 5)


def test_settings_file_is_filtered(store: LocalStore, data_dir: Path):
    """사람이 settings.json을 고쳐도 색은 #rrggbb만, 내 색은 12개까지, 제목 기본값은 셋 중 하나만 읽는다."""
    path = data_dir / "users" / "alice" / "shelf" / "settings.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"colors": {"ideas": "red;}</style><script>", "styles": "#ABCDEF", "x": "#000000"},
                                "my_colors": ["#111111", "nope", *(f"#0000{n:02x}" for n in range(20))], "title_default": "always"}),
                    encoding="utf-8")
    settings = store.get_shelf_settings("alice")
    assert settings.colors == {"styles": "#abcdef"} and len(settings.my_colors) == 12 and settings.title_default == "ask"
    assert "nope" not in settings.my_colors and settings.my_colors[0] == "#111111"
    saved = store.save_shelf_settings("alice", ShelfSettings({"refs": "#123456", "ideas": "bad"}, ("#222222",), "none"))
    assert saved == ShelfSettings({"refs": "#123456"}, ("#222222",), "none")
    assert json.loads(path.read_text(encoding="utf-8"))["schema_version"] == 1


def test_trash_and_restore_with_cli(store: LocalStore, data_dir: Path, monkeypatch, capsys):
    c = store.create_category("default", "사례", "case", "#b3261e", ())
    store.put_category_item("default", CategoryItem("20261006000000000-aaaaaa", c.id, "하나", "me"))
    store.put_category_item("default", CategoryItem("20261006000000001-aaaaab", c.id, "둘", "ai"))
    assert store.trash_category_item("default", c.id, "20261006000000001-aaaaab", "시험").content == "둘"
    assert store.trash_category("default", c.id, "통째").items == 1
    assert store.list_categories("default") == [] and not store.search_substring("default", ["category"], "하나", 5)
    store.create_category("default", "사례", "blank", "#000000", ())  # 같은 이름을 새로 만들 수 있다
    other = store.create_category("default", "치울 것", "blank", "#000000", ())
    store.close()
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("USER_ID", "default")
    monkeypatch.setenv("EMBEDDINGS", "none")
    cli.main(["trash", "put", "category", other.id, "--note", "시험 기록 정리"])  # 운영자 CLI로 카테고리 통째
    assert f"휴지통으로 옮김(default): category {other.id}" in capsys.readouterr().out
    cli.main(["trash", "list"])
    out = capsys.readouterr().out
    assert f"- category {c.id}" in out and "책 「사례」" in out and f"- category_item {c.id}/20261006000000001-aaaaab" in out
    with pytest.raises(SystemExit):  # 이름이 겹치면 되살리지 않는다
        cli.main(["trash", "restore", "category", c.id])
    with pytest.raises(SystemExit):  # 새 이름도 이름 규칙을 지킨다
        cli.main(["trash", "restore", "category", c.id, "--name", "전체"])
    cli.main(["trash", "restore", "category", c.id, "--name", "옛 사례"])
    cli.main(["trash", "restore", "category-item", f"{c.id}/20261006000000001-aaaaab"])
    capsys.readouterr()
    store = LocalStore(data_dir)
    names = {x.name: x.items for x in store.list_categories("default")}
    assert names == {"사례": 0, "옛 사례": 2}
    store.close()


# ---- 도구 ----------------------------------------------------------------------------------

async def test_category_tools_round_trip(settings: Settings, store: LocalStore):
    store.create_project("alice", "책", project_id="book")
    store.write_chapter("alice", "book", 3, "항구 이야기.", "x", title="항구")
    async with Client(build_server(settings, store)) as c:
        listed = _text(await c.call_tool("category_list", {}))
        assert "## 「책」(book) · 올린 문서 있음 · 노드 1 · 선 0\n- 가운데: 「책」 올린 문서 1장" in listed  # #96: 기본 책 없음
        assert "제목 기본값: 매번 묻기" in listed and "자주 쓰는 컨텍스트(context에 이름으로 붙인다): 「문체」" in listed
        made = _text(await c.call_tool("category_create", {"name": "사례 카테고리", "template": "사례", "color": "빨간색", "project": "book",
                                                            "context": ["사례는 출처가 있는 이야기만 모은다."]}))
        assert made.splitlines()[0] == "컨텍스트(책 「사례」): 사례는 출처가 있는 이야기만 모은다."
        assert made.splitlines()[1].startswith("책을 만듦: 「사례」 · 사례(칸: 시기, 장소, 출처) · 색 빨강(#b3261e) · 「책」 · 노드 「사례」")
        for args, why in (({"name": "사례"}, "이미 있습니다"), ({"name": "전체"}, "정해진 이름"),
                          ({"name": "새것", "color": "#fff;}"}, "기본 색 이름"), ({"name": "새것", "context": ["가" * 501]}, "500자까지")):
            result = await c.call_tool("category_create", {"project": "book", **args})
            assert result.is_error and why in _text(result), args
        # 제목: 기본값 '매번 묻기'면 저장하지 않고 먼저 묻게 한다
        asked = await c.call_tool("category_put", {"book": "사례", "author": "me", "content": "1850년대 항구의 장날"})
        assert asked.is_error and "직접 지을지, 지어 드릴지, 비워 둘지" in _text(asked)
        assert store.list_category_items("alice") == []
        put = _text(await c.call_tool("category_put", {
            "book": "사례", "author": "me", "content": "1850년대 항구의 장날", "title": "항구 장날", "title_by": "author",
            "fields": {"시기": "1850년대", "출처": "예시 향토지"}, "tags": ["항구", "장날"], "chapters": [3], "reason": "도입부에 쓸 장면"}))
        assert put.startswith("컨텍스트(책 「사례」): 사례는 출처가 있는 이야기만 모은다.\n넣음: 「사례」 ")
        assert "제목 「항구 장날」" in put and "누가: 저자의 말(me)" in put
        item_id = re.search(r"\d{17}-[0-9a-f]{6}", put).group()
        for args, why in (({"fields": {"값": "3"}}, "'값' 칸이 없다"), ({"chapters": [9]}, "없는 장 번호"),
                          ({"book": "책"}, "올린 문서가 들어 있어 글을 넣지 않는다"), ({"book": "없는것"}, "'없는것' 책이 없다")):
            result = await c.call_tool("category_put", {"book": "사례", "author": "me", "content": "x", "untitled": True, **args})
            assert result.is_error and why in _text(result), args
        edited = _text(await c.call_tool("category_put", {"book": "사례", "author": "me", "item_id": item_id, "fields": {"장소": "예시 강가"}}))
        assert "고침: 「사례」" in edited and "제목 그대로" in edited
        [item] = store.list_category_items("alice")
        assert item.title == "항구 장날" and item.fields == {"시기": "1850년대", "출처": "예시 향토지", "장소": "예시 강가"}
        assert item.chapters == (("book", 3),) and item.content == "1850년대 항구의 장날" and item.reason == "도입부에 쓸 장면"
        found = _text(await c.call_tool("category_search", {"query": "장날", "book": "사례"}))
        assert f"{item_id} · [me]" in found and "제목 「항구 장날」" in found and "연결된 장: 제3장" in found
        assert "## 「사례」 — 컨텍스트(책 「사례」): 사례는 출처가 있는 이야기만 모은다." in found
        # 고치기: 이름·색·컨텍스트(자주 쓰는 컨텍스트 이름은 그 사본, 그 밖은 직접 적은 글)
        assert "이름 「사례」 → 「옛 사례」 · 책 색 #b22222" in _text(await c.call_tool("category_edit", {"book": "사례", "new_name": "옛 사례", "color": "#B22222"}))
        changed = _text(await c.call_tool("category_edit", {"book": "옛 사례", "context": ["논문", "현장 사진은 따로 본다."]}))
        assert changed.startswith("컨텍스트(책 「옛 사례」): 「논문」 원문을 읽고 모은 논문과 책이다.") and "/ 현장 사진은 따로 본다." in changed
        assert [x.name for x in store.list_categories("alice")[0].contexts] == ["논문", ""]
        assert "컨텍스트를 뗌" in _text(await c.call_tool("category_edit", {"book": "옛 사례", "context": []}))
        bad = await c.call_tool("category_edit", {"book": "옛 사례", "color": "red;background:url(//x)"})
        assert bad.is_error and store.list_categories("alice")[0].color == "#b22222"
        # 노드의 컨텍스트(#96-d): 노드 → 책 순서로 이어 읽는다. 책에 없으면 노드의 것만
        await c.call_tool("category_edit", {"node": "사례", "project": "book", "context": ["생각 메모"]})
        follows = _text(await c.call_tool("category_put", {"book": "옛 사례", "author": "ai", "content": "요약", "untitled": True}))
        assert follows.startswith("컨텍스트(노드 「사례」의 것. 책 「옛 사례」에는 없음): 「생각 메모」")
        both = _text(await c.call_tool("category_edit", {"book": "옛 사례", "context": ["현장 사진은 따로 본다."]}))
        assert both.startswith("컨텍스트(노드 「사례」 → 책 「옛 사례」 순서): 「생각 메모」 떠오른 생각을")
        assert both.splitlines()[0].endswith(" → 현장 사진은 따로 본다.")
        asked = await c.call_tool("category_put", {"book": "없는것", "author": "me", "content": "x", "untitled": True})
        assert "「옛 사례」[생각 메모·현장 사진은 따로 본다]" in _text(asked)  # 묻게 할 때도 노드 → 책 순서의 컨텍스트 이름
        # 휴지통: 글 하나, 책 통째
        gone = _text(await c.call_tool("category_trash", {"book": "옛 사례", "note": "시험"}))
        assert "책 「옛 사례」 통째(글 2개)" in gone and store.list_categories("alice") == []


def test_context_header_order_and_limit():
    """#96-d: 응답 머리는 노드 → 책 순서, 합쳐서 HEADER_MAX자까지이고 넘으면 잘렸다고 적는다."""
    from magus.contexts import HEADER_MAX, View

    view = View((Context("책 것", "나" * 600),), "책", "노드", (Context("노드 것", "가" * 600),))
    head = view.header()
    assert head.startswith("컨텍스트(노드 「노드」 → 책 「책」 순서): 「노드 것」 가가")
    assert head.endswith(f"…(잘림: 노드·책 컨텍스트를 합쳐 {HEADER_MAX:,}자까지 싣는다)") and view.too_long
    assert len(head) < HEADER_MAX + 100
    assert View((), "책", "노드").header() == "컨텍스트: 없음(일반 메모로 다룬다) — 책 「책」"
    assert View((Context("", "짧다"),), "책", "노드").header() == "컨텍스트(책 「책」): 짧다"


async def test_title_default_is_kept_on_server(settings: Settings, store: LocalStore):
    """제목 기본값은 서버에 남는다(대화 메모리에 기대지 않는다): ask → 먼저 묻기, ai → Claude가 지어 다시, none → 비워 둔다."""
    book = make_book(store, "alice", "생각", "생각 메모")
    async with Client(build_server(settings, store)) as c:
        def put(**args):
            return c.call_tool("category_put", {"book": "생각", "author": "me", **args})

        ask = await put(content="바다는 돌아가는 곳")
        assert ask.is_error and "매번 묻기" in _text(ask) and store.list_category_items("alice") == []
        mine = _text(await put(content="바다는 돌아가는 곳", title="바다", title_by="author"))
        assert "제목 「바다」 · 누가" in mine
        unsure = await put(content="숲은 기다리는 곳", title="숲의 기다림")
        assert unsure.is_error and "title_by를 함께 준다" in _text(unsure)  # 기본값이 없다(#92-e): 누가 지었는지 꼭 받는다
        ai = _text(await put(content="숲은 기다리는 곳", title="숲의 기다림", title_by="ai"))
        assert "제목 「숲의 기다림」 (AI가 지은 제목)" in ai
        assert "제목 없음" in _text(await put(content="제목 없는 생각", untitled=True))
        assert "(AI가 지은 제목)" in _text(await c.call_tool("category_search", {"query": "숲은 기다리는"}))
        assert "'AI가 짓기'로 저장함" in _text(await c.call_tool("category_title_default", {"mode": "ai"}))
        make = await put(content="강은 이어 주는 곳")
        assert make.is_error and "title_by=ai로 다시 부른다" in _text(make)
        assert "제목 기본값: AI가 짓기" in _text(await c.call_tool("category_list", {}))
        await c.call_tool("category_title_default", {"mode": "none"})
        assert "제목 없음(저자의 제목 기본값: 비워 두기)" in _text(await put(content="강은 이어 주는 곳"))
    titles = {i.content: (i.title, i.title_by) for i in store.list_category_items("alice", book)}
    assert titles == {"바다는 돌아가는 곳": ("바다", "author"), "숲은 기다리는 곳": ("숲의 기다림", "ai"),
                      "제목 없는 생각": (None, None), "강은 이어 주는 곳": (None, None)}
    store.reindex()
    assert {i.content: (i.title, i.title_by) for i in store.list_category_items("alice", book)} == titles  # 파일에서 다시 만들어도 같다


async def test_category_limit(settings: Settings, store: LocalStore):
    for n in range(MAX_CATEGORIES):
        store.create_category("alice", f"책아님{n}", "blank", "#000000", ())
    async with Client(build_server(settings, store)) as c:
        over = await c.call_tool("category_create", {"name": "하나 더"})
    assert over.is_error and f"{MAX_CATEGORIES}권까지" in _text(over)


async def test_saved_contexts_defaults_and_editing(store: LocalStore, data_dir: Path):
    """자주 쓰는 컨텍스트(#96): 파일이 없으면 처음 제공하는 넷(읽기는 아무것도 쓰지 않는다), 고치면 넷과 함께 적는다.
    붙인 컨텍스트는 사본이라 원본을 고치거나 지워도 그대로다."""
    names = [c.name for c in store.list_saved_contexts("alice")]
    assert names == ["문체", "원고", "논문", "생각 메모"] and not (data_dir / "users" / "alice" / "shelf" / "contexts.json").exists()
    assert store.list_saved_contexts("alice")[0].text == "문학적 부분이 마음에 드는 구절을 모아놓은것. 내 문장 표현을 다듬을때 사용"
    book = make_book(store, "alice", "문체", "문체")
    added = store.save_saved_context("alice", SavedContext("", "신문", "신문 기사를 모은 것이다."))
    assert [c.name for c in store.list_saved_contexts("alice")] == ["문체", "원고", "논문", "생각 메모", "신문"]
    with pytest.raises(ValueError, match="이미 있다"):
        store.save_saved_context("alice", SavedContext("", "신문", "x"))
    store.save_saved_context("alice", SavedContext("ctx-style", "문체", "바꾼 원본"))
    assert store.delete_saved_context("alice", added.id) and not store.delete_saved_context("alice", added.id)
    assert store.get_category("alice", book).contexts[0].text.startswith("문학적 부분이")  # 사본은 그대로
    saved = json.loads((data_dir / "users" / "alice" / "shelf" / "contexts.json").read_text(encoding="utf-8"))
    assert saved["schema_version"] == 1 and [c["name"] for c in saved["items"]] == ["문체", "원고", "논문", "생각 메모"]
    with pytest.raises(ValueError, match="500자까지"):
        store.set_book_contexts("alice", book, (Context("", "가" * 501),))
    store.reindex()
    assert store.get_category("alice", book).contexts[0].name == "문체"


# ---- 웹 ------------------------------------------------------------------------------------

def test_web_categories_round_trip(server_proc):  # noqa: F811
    """노드의 '책 추가' → 새 책(컨텍스트 단추) → 바로 적기 → 이름·색·컨텍스트 고치기(그 자리에서·등록) → 내 색 → 휴지통. POST는 CSRF."""
    base, data_dir, _ = server_proc({})
    with httpx2.Client(base_url=base, follow_redirects=True, timeout=120) as c:
        shelf = c.get("/login?next=/shelf").text
        csrf = _csrf(shelf)
        # 책 추가 자리는 노드의 책장에 있다(#95). 프로젝트가 없으면 「내 서재」 하나
        assert '<a class="book add" href="/shelf/add?project=common&amp;node=center" aria-label="책 추가">' in c.get(
            "/shelf/p/common?node=center").text
        form = c.get("/shelf/new").text
        assert 'name="template"' not in form and form.count('name="color" value="#') == 18 and 'value="custom"' in form  # 칸 모양은 대화로(#97)
        assert 'name="ctx_pick" value="ctx-style"' in form and 'data-name="문체"' in form and 'name="ctx_new"' in form
        assert c.post("/shelf/new", data={"csrf": "틀림", "name": "사례", "template": "case", "color": "#b3261e"}).status_code == 403
        for data, why in (({"name": "전체"}, "정해진 이름"), ({"name": "<b>x</b>"}, "쓸 수 없는 글자"),
                          ({"name": "새것", "color": "red;}"}, "책 색을 골라 주세요"),
                          ({"name": "새것", "color": "custom", "hex": '"><script>', "r": "300", "g": "0", "b": "0"}, "직접 고른 색을 읽지 못했습니다"),
                          ({"name": "새것", "ctx_new": "가" * 501}, "500자까지")):
            page = c.post("/shelf/new", data={"csrf": csrf, "template": "blank", "color": "#b3261e", **data})
            assert page.status_code == 400 and why in page.text and '"><script>' not in page.text, data
        made = c.post("/shelf/new", data={"csrf": csrf, "name": "사례", "template": "case", "color": "custom", "hex": "",
                                          "r": "74", "g": "103", "b": "65", "keep": "1", "ctx_pick": "ctx-paper"})
        assert "「사례」 만들었습니다." in made.text
        assert 'aria-label="사례, 컨텍스트 논문, 글 0개"' in made.text and "--c:#4a6741;" in made.text  # 위 띠 = 컨텍스트 이름
        assert '<span class="band top" aria-hidden="true">논문</span>' in made.text
        cid = re.search(r'data-key="(\d{17}-[0-9a-f]{6})"', made.text).group(1)
        store = LocalStore(data_dir)
        assert store.get_shelf_settings("alice").my_colors == ("#4a6741",)  # 내 색에 저장
        [attached] = store.get_category("alice", cid).contexts
        assert attached.name == "논문" and attached.text.startswith("원문을 읽고 모은 논문과 책이다.")
        store.close()
        empty = c.get(f"/shelf/{cid}").text  # 빈 책: 한 줄 + '새 글' 하나(#97)
        assert '<p class="empty">글이 없습니다.</p>' in empty and '<summary class="btn">새 글</summary>' in empty
        assert 'name="f:시기"' not in empty and 'name="reason"' not in empty and 'name="files" multiple' in empty
        assert '<details class="ctx"><summary>논문</summary><p>원문을 읽고 모은 논문과 책이다.' in empty  # 머리에 컨텍스트(누르면 전문)
        store = LocalStore(data_dir)  # 노드에도 컨텍스트가 있으면 노드 → 책 순서로 보인다(#96-d)
        floor, node = store.node_of_book("alice", cid)
        store.set_node_contexts("alice", floor, node, (Context("현장", "현장에서 본 것만 적는다."),))
        store.close()
        both = c.get(f"/shelf/{cid}").text
        assert both.index("<summary>현장</summary>") < both.index('<span class="ctx-sep"') < both.index("<summary>논문</summary>")
        assert '<span class="ctx-label">노드 「사례」</span>' in both and '<span class="ctx-label">이 책</span>' in both
        # 바로 적기(누가 = 저자, CSRF)
        assert c.post(f"/shelf/write/{cid}", data={"csrf": "틀림", "content": "x"}).status_code == 403
        assert "error=empty" in str(c.post(f"/shelf/write/{cid}", data={"csrf": csrf, "content": "  "}).url)
        written = c.post(f"/shelf/write/{cid}", data={"csrf": csrf, "title": "", "content": "<script>alert(1)</script> 강가 장날",
                                                       "f:시기": "1850년대", "f:없는칸": "무시", "reason": "도입부", "where": "향토지 12쪽"})
        assert re.search(rf"/shelf/{cid}/\d{{17}}-[0-9a-f]{{6}}$", str(written.url)) and " open data-here>" in written.text
        assert "&lt;script&gt;alert(1)&lt;/script&gt; 강가 장날" in written.text and "<script>alert" not in written.text
        assert "<p>시기:" not in written.text and "도입부" not in written.text  # 웹의 새 글은 제목·본문·첨부만(#97)
        assert c.post("/shelf/write/ideas", data={"csrf": csrf, "content": "x"}).status_code == 404  # 옛 기본 책 주소: 이전 전에는 없다
        # 고치기: 이름·색·컨텍스트. 붙인 컨텍스트는 그 자리에서 고친다(원본은 그대로)
        edit = c.get(f"/shelf/edit/{cid}").text
        assert 'name="name" value="사례"' in edit and '<button aria-label="내 색 #4a6741 빼기">빼기</button>' in edit
        assert f'<a href="/shelf/trash/{cid}">휴지통</a>' in edit and 'value="ctx-paper" data-name="논문"' in edit
        assert re.search(r'name="ctx_pick" value="ctx-paper"[^>]*checked', edit) and 'name="ctx_from" value="ctx-paper"' in edit
        bad = c.post(f"/shelf/edit/{cid}", data={"csrf": csrf, "name": "사례", "color": "#b3261e;}</style>"})
        assert bad.status_code == 400 and "책 색을 골라 주세요" in bad.text
        # '자주 쓰는 컨텍스트로 등록': 그 줄을 목록에 더하고 이 화면을 다시 보인다(책은 저장하지 않는다)
        registered = c.post(f"/shelf/edit/{cid}", data={"csrf": csrf, "name": "사례", "color": "#2f6db5", "ctx_pick": "ctx-paper",
                                                        "ctx_name": "현장 사례", "ctx_text": "현장에서 들은 이야기다.", "ctx_from": "ctx-paper",
                                                        "register": "0"})
        assert registered.status_code == 200 and "「현장 사례」 등록했습니다." in registered.text
        done = c.post(f"/shelf/edit/{cid}", data={"csrf": csrf, "name": "옛 사례", "color": "#2f6db5", "ctx_pick": "ctx-paper",
                                                  "ctx_name": "논문", "ctx_text": "고친 컨텍스트", "ctx_from": "ctx-paper",
                                                  "ctx_new": "직접 적은 둘째"}).text
        assert "「옛 사례」 저장했습니다." in done and 'aria-label="옛 사례, 컨텍스트 논문 외 1, 글 1개"' in done and "--c:#2f6db5;" in done
        store = LocalStore(data_dir)
        assert [(x.name, x.text) for x in store.get_category("alice", cid).contexts] == [("논문", "고친 컨텍스트"), ("", "직접 적은 둘째")]
        assert next(x for x in store.list_saved_contexts("alice") if x.id == "ctx-paper").text.startswith("원문을 읽고")  # 원본 그대로
        assert any(x.name == "현장 사례" for x in store.list_saved_contexts("alice"))
        store.close()
        # 떼기(체크 상자): 저장하면 그 줄이 떨어진다
        c.post(f"/shelf/edit/{cid}", data={"csrf": csrf, "name": "옛 사례", "color": "#2f6db5", "ctx_name": ["논문", ""],
                                           "ctx_text": ["고친 컨텍스트", "직접 적은 둘째"], "ctx_from": ["", ""], "ctx_drop": "1"})
        store = LocalStore(data_dir)
        assert [x.text for x in store.get_category("alice", cid).contexts] == ["고친 컨텍스트"]
        store.close()
        # 내 색 빼기
        c.post("/shelf/colors", data={"csrf": csrf, "remove": "#4a6741", "next": "https://evil.example/"})
        store = LocalStore(data_dir)
        assert store.get_shelf_settings("alice").my_colors == ()
        store.close()
        # 휴지통: 확인 화면 → 옮김
        confirm = c.get(f"/shelf/trash/{cid}").text
        assert "「옛 사례」 · 글 1" in confirm and "휴지통으로 옮기기</button>" in confirm
        assert c.get("/shelf/trash/ideas").status_code == 404
        trashed = c.post(f"/shelf/trash/{cid}", data={"csrf": csrf}).text
        assert "휴지통으로 옮겼습니다." in trashed and "옛 사례" not in trashed
        assert c.get(f"/shelf/{cid}").status_code == 404
    assert (data_dir / "users" / "alice" / "trash" / "shelf" / "categories" / cid / "category.json").exists()


def test_web_saved_contexts_page(server_proc):  # noqa: F811
    """내 정보 → 자주 쓰는 컨텍스트(/me/contexts): 고치기·더하기·지우기. 붙여 둔 사본은 그대로."""
    base, data_dir, _ = server_proc({})
    with httpx2.Client(base_url=base, follow_redirects=True, timeout=120) as c:
        me = c.get("/login?next=/me").text
        csrf = _csrf(me)
        assert '<a href="/me/contexts">자주 쓰는 컨텍스트</a>' in me
        page = c.get("/me/contexts").text
        assert page.count('class="saved-ctx"') == 4 and ">문학적 부분이 마음에 드는 구절을 모아놓은것. 내 문장 표현을 다듬을때 사용</textarea>" in page
        assert c.post("/me/contexts", data={"csrf": "틀림", "action": "add", "name": "x", "text": "y"}).status_code == 403
        added = c.post("/me/contexts", data={"csrf": csrf, "action": "add", "name": "<b>신문</b>", "text": "신문 기사 <script>"}).text
        assert "더했습니다." in added and "&lt;b&gt;신문&lt;/b&gt;" in added and "<script>" not in added.split("<main>")[1].split("</main>")[0]
        dup = c.post("/me/contexts", data={"csrf": csrf, "action": "add", "name": "문체", "text": "x"})
        assert dup.status_code == 400 and "이미 있다" in dup.text
        saved = c.post("/me/contexts", data={"csrf": csrf, "action": "save", "id": "ctx-note", "name": "생각 메모", "text": "고친 생각 메모"}).text
        assert "저장했습니다." in saved and ">고친 생각 메모</textarea>" in saved
        c.post("/me/contexts", data={"csrf": csrf, "action": "delete", "id": "ctx-manuscript"})
    store = LocalStore(data_dir)
    assert [x.name for x in store.list_saved_contexts("alice")] == ["문체", "논문", "생각 메모", "<b>신문</b>"]
    store.close()


def test_web_category_list_search_and_titles(server_proc):  # noqa: F811
    base, data_dir, _ = server_proc({})
    store = LocalStore(data_dir)
    c1 = store.create_category("alice", "사례", "case", "#b3261e", ("시기", "장소", "출처"))
    store.put_category_item("alice", CategoryItem("20261006000000000-aaaaaa", c1.id, "항구의 장날 이야기", "ai", "장날", "ai"))
    store.put_category_item("alice", CategoryItem("20261006000000001-aaaaab", c1.id, "제목 없는 글 물결", "me", tags=("물",)))
    store.close()
    with httpx2.Client(base_url=base, follow_redirects=True, timeout=120) as c:
        c.get("/login?next=/shelf")
        listed = c.get(f"/shelf/{c1.id}").text
        assert '<span class="t">장날<span class="tag" title="AI가 지은 제목">AI 제목</span></span>' in listed
        assert '<span class="t none">제목 없는 글 물결</span>' in listed
        assert '<span class="aux"><span class="tag" title="AI가 쓴 글">AI</span></span>' in listed  # 누가: Claude가 쓴 글
        assert '<p class="sum">글 2 · <a href=' in listed and 'aria-label="책 설정"' in listed
        assert 'class="ctxs"' not in listed  # 컨텍스트가 없으면 아무것도 보이지 않는다(#97)
        assert "물결" not in c.get(f"/shelf/{c1.id}?author=ai").text
        found = c.get(f"/shelf/{c1.id}", params={"q": "장날"}).text
        assert "「장날」 1 · " in found and "<mark>장날</mark>" in found
        everywhere = c.get("/shelf", params={"q": "물결"}).text
        assert re.search(rf'<a href="/shelf/p/common\?node=[^"]+&amp;book={c1.id}">사례</a> <small>1개</small>', everywhere)
        assert "<mark>물결</mark>" in everywhere
        assert '<details id="i-20261006000000001-aaaaab" open data-here>' in c.get(f"/shelf/{c1.id}/20261006000000001-aaaaab").text


def test_web_categories_are_per_user(server_proc, fake_issuer):  # noqa: F811
    """같은 책 이름·글 id를 써도 섞이지 않는다. 남의 책 주소로는 보지도, 적지도, 고치지도, 옮기지도 못한다."""
    issuer, issuer_state, _ = fake_issuer
    base, data_dir, _ = server_proc({
        "PUBLIC_URL": "http://127.0.0.1:{port}", "AUTH_ISSUER": issuer, "ALLOWED_USERS": "sub-alice=alice,sub-bob=bob",
        "SESSION_SECRET": "x" * 40, "WEB_CLIENT_ID": "web-client",
    })
    store = LocalStore(data_dir)
    ids = {}
    for user, word in (("alice", "앨리스"), ("bob", "밥")):
        c = store.create_category(user, "사례", "case", "#123456" if user == "alice" else "#654321", (),
                                  contexts=(Context("", f"{word}의 컨텍스트"),))
        store.put_category_item(user, CategoryItem("20261006000000000-aaaaaa", c.id, f"{word}의 바다 사례", "me"))
        store.save_shelf_settings(user, ShelfSettings({}, (f"#00000{len(word)}",), "ai"))
        store.save_saved_context(user, SavedContext("", f"{word} 것", f"{word}의 자주 쓰는 컨텍스트"))
        ids[user] = c.id
    store.close()
    with httpx2.Client(base_url=base, timeout=120) as alice:
        assert _login(alice, issuer_state, "sub-alice").status_code == 303
        csrf = _csrf(alice.get("/shelf").text)
        mine = alice.get(f"/shelf/{ids['alice']}").text
        assert "앨리스의 바다" in mine and "밥의" not in mine and "앨리스의 컨텍스트" in mine
        shelf = alice.get("/shelf/p/common", params={"node": f"b-{ids['alice']}"}).text
        assert "--c:#123456;" in shelf and "#654321" not in shelf
        assert "밥의" not in alice.get("/shelf", params={"q": "바다"}).text
        edit = alice.get(f"/shelf/edit/{ids['alice']}").text
        assert "#000003" in edit and "#000001" not in edit  # 밥의 내 색은 안 보인다
        assert "앨리스 것" in edit and "밥 것" not in edit  # 자주 쓰는 컨텍스트도 사람마다
        assert "밥의" not in alice.get("/me/contexts").text
        assert alice.get(f"/shelf/{ids['bob']}").status_code == 404
        assert alice.get(f"/shelf/{ids['bob']}/20261006000000000-aaaaaa").status_code == 404
        assert alice.post(f"/shelf/write/{ids['bob']}", data={"csrf": csrf, "content": "침입"}).status_code == 404
        assert alice.post(f"/shelf/edit/{ids['bob']}", data={"csrf": csrf, "name": "뺏음", "color": "#000000"}).status_code == 404
        assert alice.post(f"/shelf/trash/{ids['bob']}", data={"csrf": csrf}).status_code == 404
        bob_ctx = next(x.id for x in LocalStore(data_dir).list_saved_contexts("bob") if x.name == "밥 것")
        alice.post("/me/contexts", data={"csrf": csrf, "action": "delete", "id": bob_ctx})  # 남의 것은 지우지 못한다
    store = LocalStore(data_dir)
    [bob] = store.list_categories("bob")
    assert bob.name == "사례" and bob.items == 1 and bob.color == "#654321" and bob.contexts[0].text == "밥의 컨텍스트"
    assert store.get_shelf_settings("bob") == ShelfSettings({}, ("#000001",), "ai")
    assert any(x.name == "밥 것" for x in store.list_saved_contexts("bob"))
    store.close()


async def test_put_routes_sources_and_shows_context(settings: Settings, store: LocalStore):
    """#96: 서지·원문 확인이 있으면 문헌 글(인용 점검이 본다), 없으면 여느 글. 어느 쪽이든 응답 머리에 그 책의 컨텍스트."""
    make_book(store, "alice", "읽은 논문", "논문")
    async with Client(build_server(settings, store)) as c:
        desc = {t.name: t.description for t in (await c.list_tools()).tools}["category_put"]
        assert desc.startswith("글 넣기. 저자가 그 책에 넣으라고 분명히 말했을 때만 부른다.")
        note = _text(await c.call_tool("category_put", {"book": "읽은 논문", "author": "me", "content": "다음에 읽을 것", "untitled": True}))
        assert note.startswith("컨텍스트(책 「읽은 논문」): 「논문」") and "넣음: 「읽은 논문」" in note
        unchecked = await c.call_tool("category_put", {"book": "읽은 논문", "author": "me", "checked": True,
                                                       "source": {"authors": "Galor, O.", "year": "2022", "title": "The journey"}})
        assert unchecked.is_error and "쓸 부분(parts)이 하나 이상" in _text(unchecked)
        source = _text(await c.call_tool("category_put", {"book": "읽은 논문", "author": "me", "checked": True, "reason": "서론",
                                                           "source": {"authors": "Galor, O.", "year": "2022", "title": "The journey"},
                                                           "parts": [{"text": "성장의 수수께끼", "where": "p.3"}]}))
        assert "galor2022: 새 문헌 글 → 원문 확인 · 쓸 부분 1개 더함(모두 1개)" in source and "책 「읽은 논문」" in source
        trash = await c.call_tool("category_trash", {"book": "읽은 논문", "item_id": "galor2022", "note": "x"})
        assert trash.is_error and "문헌 글(서지·원문 확인)은 휴지통으로 옮기지 않는다" in _text(trash)
        whole = await c.call_tool("category_trash", {"book": "읽은 논문", "note": "x"})
        assert whole.is_error and "문헌·참고문헌 항목이 1편 있어" in _text(whole)
    [book] = store.list_categories("alice")
    ref = store.get_ref("alice", "galor2022")
    assert (book.items, book.sources, book.verified) == (1, 1, 1) and ref.book == book.id and ref.status == "verified"
    assert store.get_passages("alice", "galor2022")[0].reason == "서론"  # 글의 이유가 쓸 부분의 이유가 된다


async def test_template_item_needs_only_one_of_content_title_fields(settings: Settings, store: LocalStore):
    """사례 책에 '엘알토, 볼리비아, 제16장'처럼 칸만 채운 글도 넣는다. 모두 비었을 때만 거부."""
    store.create_project("alice", "책", project_id="book")
    store.write_chapter("alice", "book", 16, "고원 도시.", "x", title="고원")
    async with Client(build_server(settings, store)) as c:
        await c.call_tool("category_title_default", {"mode": "none"})
        await c.call_tool("category_create", {"name": "사례", "template": "사례"})
        await c.call_tool("category_create", {"name": "메모", "template": "빈 책"})
        put = _text(await c.call_tool("category_put", {"book": "사례", "author": "me", "fields": {"장소": "엘알토, 볼리비아"},
                                                       "chapters": [16]}))
        assert "넣음: 「사례」" in put and "칸 1" in put
        assert "“장소: 엘알토, 볼리비아”" in _text(await c.call_tool("category_search", {"query": "엘알토"}))
        empty = await c.call_tool("category_put", {"book": "사례", "author": "me"})
        assert empty.is_error and "내용·제목·칸·쓸 부분 중 하나는 있어야 한다." in _text(empty)
        only_title = _text(await c.call_tool("category_put", {"book": "메모", "author": "me", "title": "제목만", "title_by": "author"}))
        assert "넣음: 「메모」" in only_title
    [item] = [i for i in store.list_category_items("alice") if i.fields]
    assert (item.content, item.title, item.fields, item.chapters) == ("", None, {"장소": "엘알토, 볼리비아"}, (("book", 16),))


def test_web_list_shows_fields_when_no_title_or_content(server_proc):  # noqa: F811
    base, data_dir, _ = server_proc({})
    store = LocalStore(data_dir)
    c = store.create_category("alice", "사례", "case", "#b3261e", ("시기", "장소", "출처"))
    store.put_category_item("alice", CategoryItem("20261006000000000-aaaaaa", c.id, "", "me", fields={"장소": "엘알토, 볼리비아"}))
    store.close()
    with httpx2.Client(base_url=base, follow_redirects=True, timeout=120) as w:
        page = w.get(f"/login?next=/shelf/{c.id}").text
        assert '<span class="t none">장소: 엘알토, 볼리비아</span>' in page
        csrf = _csrf(page)
        assert 'name="content" rows="6" maxlength="20000"></textarea>' in page  # 내용이 꼭 필요하지 않다
        assert "<p>장소: 엘알토, 볼리비아</p>" in page  # 칸은 본문의 일부로 보인다(#97)
        only_field = w.post(f"/shelf/write/{c.id}", data={"csrf": csrf, "title": "", "content": "", "f:시기": "1950년대"})
        assert "error=empty" in str(only_field.url)  # 웹의 새 글은 제목·본문·첨부만(칸은 대화로, #97)
        nothing = w.post(f"/shelf/write/{c.id}", data={"csrf": csrf, "title": "", "content": ""})
        assert "error=empty" in str(nothing.url) and "제목이나 본문을 적어 주세요." in nothing.text
