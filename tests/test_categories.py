"""저자가 만든 카테고리·책 색·항목 제목(#92).

- 규칙: 이름(예약어·중복·길이·글자·숫자만·개수), 색(기본 색 이름·#RRGGBB만, 그 밖은 거부), 제목 기본값.
- 저장: 파일이 원본(schema_version), reindex로 다시 만든다. 휴지통은 옮기고 되살린다.
- 도구: category_* 일곱 개, idea_add의 제목(기본값 '매번 묻기'면 먼저 묻게 한다).
- 웹: 책장에 꽂힌 카테고리, 만들기·고치기·휴지통·내 색·바로 적기, 주입 시도, 사용자 격리.
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
from magus.store import CategoryItem, LocalStore, ShelfSettings
from magus.webshelf import contrast, text_color

pytestmark = pytest.mark.anyio


def _text(result) -> str:
    return "\n".join(block.text for block in result.content)


# ---- 규칙 ----------------------------------------------------------------------------------

def test_name_rules():
    taken = {name_key("사례"): "사례"}
    assert check_name("  인물  ", taken) == "인물"
    assert check_name("Ancient Rome", taken) == "Ancient Rome" and check_name("강의 준비 2026", taken) == "강의 준비 2026"
    assert check_name("인물 카테고리", taken) == "인물"  # 끝의 '카테고리'는 뗀다
    for bad, why in (
        ("생각", "정해진 이름"), ("문 체", "정해진 이름"), ("확인요청", "정해진 이름"), ("책장 카테고리", "정해진 이름"),
        ("카테고리", "정해진 이름"), ("Casper", "정해진 이름"), ("원고", "정해진 이름"), ("책", "정해진 이름"),
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
    assert f"- category {c.id}" in out and "카테고리 「사례」" in out and f"- category_item {c.id}/20261006000000001-aaaaab" in out
    with pytest.raises(SystemExit):  # 이름이 겹치면 되살리지 않는다
        cli.main(["trash", "restore", "category", c.id])
    with pytest.raises(SystemExit):  # 새 이름도 이름 규칙을 지킨다
        cli.main(["trash", "restore", "category", c.id, "--name", "생각"])
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
        assert "## 1층 「책」(book) · 원고 있음\n- 생각 0개 · 기본(idea_add)" in listed and "제목 기본값: 매번 묻기" in listed
        assert "## 공용\n- 문체 0개 · 기본(style_add)" in listed  # 층(#93): 문체는 공용, 생각·문헌은 작업물 층
        made = _text(await c.call_tool("category_create", {"name": "사례 카테고리", "template": "사례", "color": "빨간색"}))
        assert made.startswith("카테고리를 만듦: 「사례」 · 사례 템플릿(칸: 시기, 장소, 출처) · 색 빨강(#b3261e)")
        for args, why in (({"name": "사례"}, "이미 있습니다"), ({"name": "문헌"}, "정해진 이름"),
                          ({"name": "새것", "color": "#fff;}"}, "기본 색 이름")):
            result = await c.call_tool("category_create", args)
            assert result.is_error and why in _text(result), args
        # 제목: 기본값 '매번 묻기'면 저장하지 않고 먼저 묻게 한다
        asked = await c.call_tool("category_put", {"category": "사례", "author": "me", "content": "1850년대 항구의 장날"})
        assert asked.is_error and "직접 지을지, 지어 드릴지, 비워 둘지" in _text(asked)
        assert store.list_category_items("alice") == []
        put = _text(await c.call_tool("category_put", {
            "category": "사례", "author": "me", "content": "1850년대 항구의 장날", "title": "항구 장날", "title_by": "author",
            "fields": {"시기": "1850년대", "출처": "예시 향토지"}, "tags": ["항구", "장날"], "chapters": [3]}))
        assert put.startswith("넣음: 카테고리 「사례」 ") and "제목 「항구 장날」" in put and "누가: 저자의 말(me)" in put
        item_id = re.search(r"\d{17}-[0-9a-f]{6}", put).group()
        for args, why in (({"fields": {"값": "3"}}, "'값' 칸이 없다"), ({"chapters": [9]}, "없는 장 번호"),
                          ({"category": "문체"}, "style_add 도구를 찾아 쓴다"), ({"category": "문헌"}, "ref_add 도구를 찾아 쓴다"),
                          ({"category": "없는것"}, "카테고리가 없다")):
            result = await c.call_tool("category_put", {"category": "사례", "author": "me", "content": "x", "untitled": True, **args})
            assert result.is_error and why in _text(result), args
        edited = _text(await c.call_tool("category_put", {"category": "사례", "author": "me", "item_id": item_id, "fields": {"장소": "예시 강가"}}))
        assert edited.startswith("고침:") and "제목 그대로" in edited
        [item] = store.list_category_items("alice")
        assert item.title == "항구 장날" and item.fields == {"시기": "1850년대", "출처": "예시 향토지", "장소": "예시 강가"}
        assert item.chapters == (("book", 3),) and item.content == "1850년대 항구의 장날"
        found = _text(await c.call_tool("category_search", {"query": "장날", "category": "사례"}))
        assert f"「사례」 {item_id} · [me]" in found and "제목 「항구 장날」" in found and "연결된 장: 제3장" in found
        # 고치기: 이름·색. 기본 카테고리는 색만
        assert "이름 「사례」 → 「옛 사례」 · 책 색 #b22222" in _text(await c.call_tool("category_edit", {"category": "사례", "new_name": "옛 사례", "color": "#B22222"}))
        assert "「생각」 책 색을 하늘(#8db8de)으로 바꿈." == _text(await c.call_tool("category_edit", {"category": "생각", "color": "하늘"}))
        assert store.get_shelf_settings("alice").colors == {"ideas": "#8db8de"}
        renamed = await c.call_tool("category_edit", {"category": "문헌", "new_name": "논문"})
        assert renamed.is_error and "이름을 바꿀 수 없다" in _text(renamed)
        bad = await c.call_tool("category_edit", {"category": "옛 사례", "color": "red;background:url(//x)"})
        assert bad.is_error and store.list_categories("alice")[0].color == "#b22222"
        # 휴지통: 항목, 통째. 기본 카테고리는 못 옮긴다
        assert (await c.call_tool("category_trash", {"category": "생각", "note": "x"})).is_error
        gone = _text(await c.call_tool("category_trash", {"category": "옛 사례", "note": "시험"}))
        assert "카테고리 「옛 사례」 통째(항목 1개)" in gone and store.list_categories("alice") == []


async def test_title_default_is_kept_on_server(settings: Settings, store: LocalStore):
    """제목 기본값은 서버에 남는다(대화 메모리에 기대지 않는다): ask → 먼저 묻기, ai → Claude가 지어 다시, none → 비워 둔다."""
    async with Client(build_server(settings, store)) as c:
        ask = await c.call_tool("idea_add", {"text": "바다는 돌아가는 곳", "kind": "thought"})
        assert ask.is_error and "매번 묻기" in _text(ask) and store.list_ideas("alice") == []
        mine = _text(await c.call_tool("idea_add", {"text": "바다는 돌아가는 곳", "kind": "thought", "title": "바다", "title_by": "author"}))
        assert mine.endswith("· 제목 「바다」")
        unsure = await c.call_tool("idea_add", {"text": "숲은 기다리는 곳", "kind": "thought", "title": "숲의 기다림"})
        assert unsure.is_error and "title_by를 함께 준다" in _text(unsure)  # 기본값이 없다(#92-e): 누가 지었는지 꼭 받는다
        ai = _text(await c.call_tool("idea_add", {"text": "숲은 기다리는 곳", "kind": "thought", "title": "숲의 기다림", "title_by": "ai"}))
        assert ai.endswith("제목 「숲의 기다림」 (AI가 지은 제목)")
        empty = _text(await c.call_tool("idea_add", {"text": "제목 없는 생각", "kind": "thought", "untitled": True}))
        assert empty.endswith("· 제목 없음")
        assert "(AI가 지은 제목)" in _text(await c.call_tool("idea_search", {"query": "숲은 기다리는"}))
        assert "'AI가 짓기'로 저장함" in _text(await c.call_tool("category_title_default", {"mode": "ai"}))
        make = await c.call_tool("idea_add", {"text": "강은 이어 주는 곳", "kind": "thought"})
        assert make.is_error and "title_by=ai로 다시 부른다" in _text(make)
        assert "제목 기본값: AI가 짓기" in _text(await c.call_tool("category_list", {}))
        await c.call_tool("category_title_default", {"mode": "none"})
        assert "제목 없음(저자의 제목 기본값: 비워 두기)" in _text(await c.call_tool("idea_add", {"text": "강은 이어 주는 곳", "kind": "thought"}))
    titles = {i.text: (i.title, i.title_by) for i in store.list_ideas("alice")}
    assert titles == {"바다는 돌아가는 곳": ("바다", "author"), "숲은 기다리는 곳": ("숲의 기다림", "ai"),
                      "제목 없는 생각": (None, None), "강은 이어 주는 곳": (None, None)}
    store.reindex()
    assert {i.text: (i.title, i.title_by) for i in store.list_ideas("alice")} == titles  # 파일에서 다시 만들어도 같다
    # 제목이 없는 생각 파일에는 title 키가 없다(제목 전 코드로 되돌려도 읽힌다)
    files = [json.loads(p.read_text(encoding="utf-8")) for p in (store.root / "users" / "alice" / "shelf" / "casper").glob("*.json")]
    assert sum("title" in f for f in files) == 2 and all("title_by" in f for f in files if "title" in f)


async def test_category_limit(settings: Settings, store: LocalStore):
    for n in range(MAX_CATEGORIES):
        store.create_category("alice", f"카테고리아님{n}", "blank", "#000000", ())
    async with Client(build_server(settings, store)) as c:
        over = await c.call_tool("category_create", {"name": "하나 더"})
    assert over.is_error and f"{MAX_CATEGORIES}개까지" in _text(over)


# ---- 웹 ------------------------------------------------------------------------------------

def test_web_categories_round_trip(server_proc):  # noqa: F811
    """책장 화면에서 카테고리 만들기(점선 책) → 바로 적기 → 이름·색 바꾸기 → 내 색 → 휴지통. 모든 POST는 CSRF."""
    base, data_dir, _ = server_proc({})
    with httpx2.Client(base_url=base, follow_redirects=True, timeout=120) as c:
        shelf = c.get("/login?next=/shelf").text
        csrf = _csrf(shelf)
        assert '<a class="book add" href="/shelf/new" aria-label="카테고리 추가">' in shelf
        form = c.get("/shelf/new").text
        assert 'name="template" value="case"' in form and form.count('name="color" value="#') == 18 and 'value="custom"' in form
        assert c.post("/shelf/new", data={"csrf": "틀림", "name": "사례", "template": "case", "color": "#b3261e"}).status_code == 403
        for data, why in (({"name": "생각"}, "정해진 이름"), ({"name": "<b>x</b>"}, "쓸 수 없는 글자"),
                          ({"name": "새것", "color": "red;}"}, "책 색을 골라 주세요"),
                          ({"name": "새것", "color": "custom", "hex": '"><script>', "r": "300", "g": "0", "b": "0"}, "직접 고른 색을 읽지 못했습니다")):
            page = c.post("/shelf/new", data={"csrf": csrf, "template": "blank", "color": "#b3261e", **data})
            assert page.status_code == 400 and why in page.text and '"><script>' not in page.text, data
        made = c.post("/shelf/new", data={"csrf": csrf, "name": "사례", "template": "case", "color": "custom", "hex": "",
                                          "r": "74", "g": "103", "b": "65", "keep": "1"})
        assert "「사례」 카테고리를 꽂았습니다." in made.text
        assert 'aria-label="사례, 항목 0개"' in made.text and "--c:#4a6741;" in made.text
        cid = re.search(r'href="/shelf/(\d{17}-[0-9a-f]{6})"', made.text).group(1)
        store = LocalStore(data_dir)
        assert store.get_shelf_settings("alice").my_colors == ("#4a6741",)  # 내 색에 저장
        store.close()
        empty = c.get(f"/shelf/{cid}").text
        assert '<details class="card write" open>' in empty and 'name="f:시기"' in empty and "아직 적은 것이 없습니다." in empty
        # 바로 적기(누가 = 저자, CSRF)
        assert c.post(f"/shelf/write/{cid}", data={"csrf": "틀림", "content": "x"}).status_code == 403
        assert "error=empty" in str(c.post(f"/shelf/write/{cid}", data={"csrf": csrf, "content": "  "}).url)
        written = c.post(f"/shelf/write/{cid}", data={"csrf": csrf, "title": "", "content": "<script>alert(1)</script> 강가 장날",
                                                       "f:시기": "1850년대", "f:없는칸": "무시"})
        assert re.search(rf"/shelf/{cid}/\d{{17}}-[0-9a-f]{{6}}$", str(written.url)) and " open data-here>" in written.text
        assert "&lt;script&gt;alert(1)&lt;/script&gt; 강가 장날" in written.text and "<script>alert" not in written.text
        assert "<dt>시기</dt><dd>1850년대</dd>" in written.text and "누가: 저자의 말" in written.text
        idea = c.post("/shelf/write/ideas", data={"csrf": csrf, "title": "물가의 제목", "content": "물가는 궁지다"})
        assert '<span class="t">물가의 제목</span>' in idea.text and "/shelf/ideas/" in str(idea.url)
        assert c.post("/shelf/write/styles", data={"csrf": csrf, "content": "x"}).status_code == 404  # 문체·문헌은 대화로
        # 고치기: 이름과 색(기본 색 이름은 화면에서 격자로 고른다). 기본 카테고리는 색만
        edit = c.get(f"/shelf/edit/{cid}").text
        assert 'name="name" value="사례"' in edit and '<button aria-label="내 색 #4a6741 빼기">빼기</button>' in edit
        assert "이 카테고리를 휴지통으로 옮기기" in edit
        bad = c.post(f"/shelf/edit/{cid}", data={"csrf": csrf, "name": "사례", "color": "#b3261e;}</style>"})
        assert bad.status_code == 400 and "책 색을 골라 주세요" in bad.text
        done = c.post(f"/shelf/edit/{cid}", data={"csrf": csrf, "name": "옛 사례", "color": "#2f6db5"}).text
        assert "「옛 사례」 카테고리를 고쳤습니다." in done and 'aria-label="옛 사례, 항목 1개"' in done and "--c:#2f6db5;" in done
        builtin = c.get("/shelf/edit/ideas").text
        assert 'name="name"' not in builtin and "기본 카테고리라 이름은 바꿀 수 없습니다." in builtin
        c.post("/shelf/edit/ideas", data={"csrf": csrf, "name": "엉뚱한 이름", "color": "#8db8de"})
        shelf = c.get("/shelf").text
        assert re.search(r'href="/shelf/ideas" style="--c:#8db8de;--fg:#1a1a1a;', shelf) and "엉뚱한 이름" not in shelf
        # 내 색 빼기
        c.post("/shelf/colors", data={"csrf": csrf, "remove": "#4a6741", "next": "https://evil.example/"})
        store = LocalStore(data_dir)
        assert store.get_shelf_settings("alice").my_colors == ()
        store.close()
        # 휴지통: 확인 화면 → 옮김. 기본 카테고리는 못 옮긴다
        confirm = c.get(f"/shelf/trash/{cid}").text
        assert "「옛 사례」 카테고리를 휴지통으로 옮길까요?" in confirm and "항목 1개가 함께 옮겨집니다." in confirm
        assert c.get("/shelf/trash/ideas").status_code == 400
        trashed = c.post(f"/shelf/trash/{cid}", data={"csrf": csrf}).text
        assert "카테고리를 휴지통으로 옮겼습니다." in trashed and "옛 사례" not in trashed
        assert c.get(f"/shelf/{cid}").status_code == 404
    assert (data_dir / "users" / "alice" / "trash" / "shelf" / "categories" / cid / "category.json").exists()


def test_web_category_list_search_and_titles(server_proc):  # noqa: F811
    base, data_dir, _ = server_proc({})
    store = LocalStore(data_dir)
    c1 = store.create_category("alice", "사례", "case", "#b3261e", ("시기", "장소", "출처"))
    store.put_category_item("alice", CategoryItem("20261006000000000-aaaaaa", c1.id, "항구의 장날 이야기", "ai", "장날", "ai"))
    store.put_category_item("alice", CategoryItem("20261006000000001-aaaaab", c1.id, "제목 없는 항목 물결", "me", tags=("물",)))
    store.close()
    with httpx2.Client(base_url=base, follow_redirects=True, timeout=120) as c:
        c.get("/login?next=/shelf")
        listed = c.get(f"/shelf/{c1.id}").text
        assert '<span class="t">장날<span class="tag">AI가 지은 제목</span></span>' in listed
        assert '<span class="t none">제목 없는 항목 물결</span>' in listed and "제목은 AI가 지었습니다." in listed
        assert '<span class="aux"><span class="tag">AI</span></span>' in listed  # 누가: Claude가 쓴 글
        assert "사례 2개(나 1 · AI 1) · 사례 템플릿" in listed
        assert "물결" not in c.get(f"/shelf/{c1.id}?author=ai").text
        found = c.get(f"/shelf/{c1.id}", params={"q": "장날"}).text
        assert "찾은 항목 1개" in found and "<mark>장날</mark>" in found
        everywhere = c.get("/shelf", params={"q": "물결"}).text
        assert "<h2>사례 <small>1개</small></h2>" in everywhere and "<mark>물결</mark>" in everywhere
        assert '<details id="i-20261006000000001-aaaaab" open data-here>' in c.get(f"/shelf/{c1.id}/20261006000000001-aaaaab").text


def test_web_categories_are_per_user(server_proc, fake_issuer):  # noqa: F811
    """같은 카테고리 이름·항목 id를 써도 섞이지 않는다. 남의 카테고리 주소로는 보지도, 적지도, 고치지도, 옮기지도 못한다."""
    issuer, issuer_state, _ = fake_issuer
    base, data_dir, _ = server_proc({
        "PUBLIC_URL": "http://127.0.0.1:{port}", "AUTH_ISSUER": issuer, "ALLOWED_USERS": "sub-alice=alice,sub-bob=bob",
        "SESSION_SECRET": "x" * 40, "WEB_CLIENT_ID": "web-client",
    })
    store = LocalStore(data_dir)
    ids = {}
    for user, word in (("alice", "앨리스"), ("bob", "밥")):
        c = store.create_category(user, "사례", "case", "#b3261e", ())
        store.put_category_item(user, CategoryItem("20261006000000000-aaaaaa", c.id, f"{word}의 바다 사례", "me"))
        store.save_shelf_settings(user, ShelfSettings({"ideas": "#123456" if user == "alice" else "#654321"}, (f"#00000{len(word)}",), "ai"))
        ids[user] = c.id
    store.close()
    with httpx2.Client(base_url=base, timeout=120) as alice:
        assert _login(alice, issuer_state, "sub-alice").status_code == 303
        csrf = _csrf(alice.get("/shelf").text)
        mine = alice.get(f"/shelf/{ids['alice']}").text
        assert "앨리스의 바다" in mine and "밥의" not in mine
        shelf = alice.get("/shelf").text
        assert "--c:#123456;" in shelf and "#654321" not in shelf
        assert "밥의" not in alice.get("/shelf", params={"q": "바다"}).text
        edit = alice.get(f"/shelf/edit/{ids['alice']}").text
        assert "#000003" in edit and "#000001" not in edit  # 밥의 내 색은 안 보인다
        assert alice.get(f"/shelf/{ids['bob']}").status_code == 404
        assert alice.get(f"/shelf/{ids['bob']}/20261006000000000-aaaaaa").status_code == 404
        assert alice.post(f"/shelf/write/{ids['bob']}", data={"csrf": csrf, "content": "침입"}).status_code == 404
        assert alice.post(f"/shelf/edit/{ids['bob']}", data={"csrf": csrf, "name": "뺏음", "color": "#000000"}).status_code == 404
        assert alice.post(f"/shelf/trash/{ids['bob']}", data={"csrf": csrf}).status_code == 404
    store = LocalStore(data_dir)
    [bob] = store.list_categories("bob")
    assert bob.name == "사례" and bob.items == 1 and bob.color == "#b3261e"
    assert store.get_shelf_settings("bob") == ShelfSettings({"ideas": "#654321"}, ("#000001",), "ai")
    store.close()


async def test_put_into_builtin_categories(settings: Settings, store: LocalStore):
    """도구를 그때그때 찾아 불러오는 클라이언트에서 Claude가 idea_add 대신 category_put(category=생각)을 부르기도 한다.
    생각은 idea_add와 같은 규칙(제목 기본값·title_by)으로 저장하고, 문체·문헌은 맞는 도구 이름을 담은 오류를 돌려준다."""
    async with Client(build_server(settings, store)) as c:
        listed = _text(await c.call_tool("category_list", {}))
        assert "생각·문체·문헌은 기본 카테고리다. 생각은 이 도구로도 들어가지만, 문체는 style_add, 문헌은 ref_add로 넣는다." in listed
        desc = {t.name: t.description for t in (await c.list_tools()).tools}["category_put"]
        assert desc.startswith("저자가 그 카테고리에 넣으라고 분명히 말했을 때만 부른다. 생각·문체·문헌은 기본 카테고리다.")
        asked = await c.call_tool("category_put", {"category": "생각", "author": "me", "content": "시험2"})
        assert asked.is_error and "매번 묻기" in _text(asked) and store.list_ideas("alice") == []  # 제목 기본값도 같다
        await c.call_tool("category_title_default", {"mode": "none"})
        saved = _text(await c.call_tool("category_put", {"category": "생각 카테고리", "author": "me", "content": "시험2", "chapters": [3]}))
        assert saved.startswith("생각에 저장함 [me] ") and "제목 없음" in saved and "장 연결·태그가 없어 넣지 않았다" in saved
        titled = await c.call_tool("category_put", {"category": "생각", "author": "me", "content": "시험3", "title": "셋"})
        assert titled.is_error and "title_by를 함께 준다" in _text(titled)
        for name, said in (("문체", "문체는 이 도구로 넣지 않는다. style_add 도구를 찾아 쓴다(구절과 저자가 말한 이유가 필요하다)."),
                           ("문헌", "문헌은 이 도구로 넣지 않는다. ref_add 도구를 찾아 쓴다(서지와, 원문에서 고른 발췌와 그 이유가 필요하다).")):
            result = await c.call_tool("category_put", {"category": name, "author": "me", "content": "x", "untitled": True})
            assert result.is_error and said in _text(result)
        found = await c.call_tool("category_search", {"query": "x", "category": "문헌"})
        assert found.is_error and "ref_search 도구를 찾아 쓴다" in _text(found)
    [idea] = store.list_ideas("alice")
    assert (idea.text, idea.author, idea.kind, idea.title) == ("시험2", "me", "thought", None)
    assert store.list_styles("alice") == [] and store.list_refs("alice") == []


async def test_template_item_needs_only_one_of_content_title_fields(settings: Settings, store: LocalStore):
    """사례 카테고리에 '엘알토, 볼리비아, 제16장'처럼 칸만 채운 항목도 넣는다. 모두 비었을 때만 거부(빈 카테고리는 제목이나 내용)."""
    store.create_project("alice", "책", project_id="book")
    store.write_chapter("alice", "book", 16, "고원 도시.", "x", title="고원")
    async with Client(build_server(settings, store)) as c:
        await c.call_tool("category_title_default", {"mode": "none"})
        await c.call_tool("category_create", {"name": "사례", "template": "사례"})
        await c.call_tool("category_create", {"name": "메모", "template": "빈 카테고리"})
        put = _text(await c.call_tool("category_put", {"category": "사례", "author": "me", "fields": {"장소": "엘알토, 볼리비아"},
                                                       "chapters": [16]}))
        assert put.startswith("넣음: 카테고리 「사례」") and "칸 1" in put
        assert "“장소: 엘알토, 볼리비아”" in _text(await c.call_tool("category_search", {"query": "엘알토"}))
        empty = await c.call_tool("category_put", {"category": "사례", "author": "me"})
        assert empty.is_error and "내용·제목·칸(시기, 장소, 출처) 중 하나는 있어야 한다." in _text(empty)
        blank = await c.call_tool("category_put", {"category": "메모", "author": "me"})
        assert blank.is_error and "제목이나 내용 중 하나는 있어야 한다." in _text(blank)
        only_title = _text(await c.call_tool("category_put", {"category": "메모", "author": "me", "title": "제목만", "title_by": "author"}))
        assert only_title.startswith("넣음: 카테고리 「메모」")
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
        assert 'name="content" rows="6" maxlength="20000"></textarea>' in page  # 카테고리 적기 폼은 내용이 꼭 필요하지 않다
        only_field = w.post(f"/shelf/write/{c.id}", data={"csrf": csrf, "title": "", "content": "", "f:시기": "1950년대"})
        assert "<dt>시기</dt><dd>1950년대</dd>" in only_field.text
        nothing = w.post(f"/shelf/write/{c.id}", data={"csrf": csrf, "title": "", "content": ""})
        assert "error=empty" in str(nothing.url) and "제목·내용·칸 중 하나는 적어 주세요." in nothing.text
        assert "error=empty" in str(w.post("/shelf/write/ideas", data={"csrf": csrf, "title": "제목만", "content": ""}).url)
