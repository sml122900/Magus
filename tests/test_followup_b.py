"""코드 점검 후속 B(2026-10-09): 중간 항목별 시험. 항목 번호는 docs/audit/2026-10-09-code-audit.md."""

from __future__ import annotations

import json

import httpx2
import pytest
from mcp import Client
from test_web import _csrf, server_proc  # noqa: F401 - 픽스처

from magus.config import Settings
from magus.server import build_server
from magus.store import CategoryItem, LocalStore

pytestmark = pytest.mark.anyio
BOUND = "----fbtest"


def _chunked(fields: dict[str, str], field: str, name: str, size: int):
    def gen():
        for k, v in fields.items():
            yield f"--{BOUND}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode()
        yield f"--{BOUND}\r\nContent-Disposition: form-data; name=\"{field}\"; filename=\"{name}\"\r\nContent-Type: text/plain\r\n\r\n".encode()
        left = size
        while left > 0:
            n = min(left, 1_000_000)
            yield b"a" * n
            left -= n
        yield f"\r\n--{BOUND}--\r\n".encode()
    return gen()


# ---- 5-a 웹 본문 한도·업로드를 디스크로 바로 ----

def test_body_limit_and_streamed_uploads(server_proc):  # noqa: F811
    base, data_dir, log = server_proc({"MAX_ATTACH_MB": "2", "MAX_UPLOAD_MB": "3"})
    store = LocalStore(data_dir)
    store.create_category("alice", "메모", "blank", "#1f2f5c", (), "common", category_id="bk1")
    store.close()
    headers = {"content-type": f"multipart/form-data; boundary={BOUND}"}
    with httpx2.Client(base_url=base, follow_redirects=False, timeout=120) as c:
        csrf = _csrf(c.get("/login?next=/shelf/write/bk1", follow_redirects=True).text)
        fields = {"csrf": csrf, "title": "시험", "content": "x", "project": "new"}
        # 첨부 주소: 2MB × 10 + 2MB를 넘는 청크 전송 → 받는 도중에 413(웹 오류 화면)
        big = c.post("/shelf/write/bk1", content=_chunked(fields, "files", "big.txt", 30_000_000), headers=headers)
        assert big.status_code == 413 and "보낸 내용이 너무 큽니다(한 번에 22.0 MB까지)." in big.text and "돌아가기" in big.text
        # 작은 폼 주소(지도 바꾸기)는 2MB
        small = c.post("/shelf/p/common/map", content=_chunked(fields, "files", "big.txt", 5_000_000), headers=headers)
        assert small.status_code == 413 and "2.0 MB까지" in small.text
        # 문서 올리기: 한 개 한도 + 1MB
        ms = c.post("/shelf/manuscript", content=_chunked(fields, "file", "원고.docx", 5_000_000), headers=headers)
        assert ms.status_code == 413
        # 정상 첨부는 그대로 저장된다(임시 파일에서 흘려 씀)
        ok = c.post("/shelf/write/bk1", data={"csrf": csrf, "title": "첨부", "content": "본문"},
                    files=[("files", ("a.txt", b"x" * 1_500_000, "text/plain")), ("files", ("b.txt", "가나다".encode(), "text/plain"))])
        assert ok.status_code == 303
        saved = sorted((data_dir / "users" / "alice" / "shelf" / "categories" / "bk1" / "files").glob("*/*/*.txt"))
        assert [p.read_bytes()[:3] for p in saved] == [b"xxx", "가".encode()] and saved[0].stat().st_size == 1_500_000
        # 첨부 한 개 한도(2MB)를 넘으면 저장하지 않는다(읽지 않고 받은 크기로)
        over = c.post("/shelf/write/bk1", data={"csrf": csrf, "title": "큼", "content": "본문"},
                      files=[("files", ("c.txt", b"x" * 2_500_000, "text/plain"))])
        assert over.status_code == 400 and "파일 한 개 2.0 MB까지입니다." in over.text
        # 올린 파일: 한도(3MB) 넘는 파일은 오류, 맞는 파일은 그대로
        up = c.post("/inbox/upload", data={"csrf": csrf},
                    files=[("files", ("큰.txt", b"x" * 3_500_000, "text/plain")), ("files", ("작은.txt", "내용".encode(), "text/plain"))],
                    follow_redirects=True)
        assert "큰.txt: 파일이 너무 크다" in up.text and "올림: 작은.txt" in up.text
        assert (data_dir / "users" / "alice" / "inbox" / "작은.txt").read_text(encoding="utf-8") == "내용"
    assert "Traceback" not in log.read_text(encoding="utf-8")


async def test_put_attachment_and_inbox_take_files(store: LocalStore, tmp_path):
    import io

    store.create_category("alice", "메모", "blank", "#1f2f5c", (), "common", category_id="bk1")
    store.put_category_item("alice", CategoryItem("20261009000000000-aaaaaa", "bk1", "글", "me"))
    stream = io.BytesIO(b"0123456789" * 1000)
    stream.seek(500)  # 처음부터 쓴다
    att = store.put_attachment("alice", "bk1/20261009000000000-aaaaaa", "a.txt", stream)
    path = store.attachment_path("alice", "bk1/20261009000000000-aaaaaa", att.id)[0]
    assert path.read_bytes() == b"0123456789" * 1000 and att.size == 10_000
    entry = store.put_inbox("alice", "b.txt", io.BytesIO("안녕".encode()))
    assert entry.size == len("안녕".encode())


# ---- 12-a 파일은 썼는데 색인이 실패하면 그 글만 다시 색인 ----

async def test_index_lag_is_repaired_in_background(data_dir, settings: Settings, monkeypatch: pytest.MonkeyPatch):
    import sqlite3
    import time

    import magus.store.local as local

    monkeypatch.setattr(local, "RETRY_WAITS", (0.0, 0.05))
    monkeypatch.setattr(local, "REPAIR_EVERY", 0.1)
    store = LocalStore(data_dir)
    store.create_category("alice", "메모", "blank", "#1f2f5c", (), "common", category_id="notes")
    store.put_category_item("alice", CategoryItem("20261009000000001-aaaaaa", "notes", "버릴 글", "me", "버릴 글", "author"))
    store._db.execute("PRAGMA busy_timeout = 50")
    lock = sqlite3.connect(data_dir / "index.sqlite")
    lock.execute("BEGIN IMMEDIATE")  # 다른 프로세스가 쓰는 중
    async with Client(build_server(settings, store)) as c:
        r = await c.call_tool("category_put", {"book": "메모", "author": "me", "content": "새 글", "untitled": True})
    assert not r.is_error, r.content[0].text  # 파일은 저장됐다: 오류를 내지 않는다(전에는 오류 → 다시 넣어 둘이 됐다)
    store.trash_item_with_replies("alice", "notes", "20261009000000001-aaaaaa", "웹")  # 전에는 OperationalError, 색인에 유령 글
    pending = json.loads((data_dir / "index-pending.json").read_text(encoding="utf-8"))
    assert len(pending["alice"]) == 2
    lock.rollback()
    lock.close()
    for _ in range(50):
        if not (data_dir / "index-pending.json").exists():
            break
        time.sleep(0.1)
    rows = [(i.content, i.id) for i in store.list_category_items("alice", "notes")]
    assert [c for c, _ in rows] == ["새 글"] and not (data_dir / "index-pending.json").exists()
    store.close()


def test_pending_index_is_repaired_at_start(data_dir):
    store = LocalStore(data_dir)
    store.create_category("alice", "메모", "blank", "#1f2f5c", (), "common", category_id="notes")
    store.put_category_item("alice", CategoryItem("20261009000000001-aaaaaa", "notes", "글", "me", "글", "author"))
    store._db.execute("DELETE FROM category_items")  # 지난번에 색인이 늦은 채 서버가 꺼졌다
    store._db.commit()
    store.close()
    (data_dir / "index-pending.json").write_text(json.dumps({"alice": ["item:notes/20261009000000001-aaaaaa"]}), encoding="utf-8")
    again = LocalStore(data_dir)
    assert [i.content for i in again.list_category_items("alice", "notes")] == ["글"]
    assert not (data_dir / "index-pending.json").exists()
    again.close()


# ---- 15-6 칸별 입력 길이 상한, 15-2 장 번호 범위(스키마) ----

async def test_input_limits_in_schema_and_enforced(store: LocalStore, settings: Settings):
    store.create_project("alice", "책", project_id="b")
    store.write_chapter("alice", "b", 1, "본문(Clack, 2012).", "x", title="하나")
    store.create_category("alice", "메모", "blank", "#1f2f5c", (), "common", category_id="notes")
    async with Client(build_server(settings, store)) as c:
        tools = {t.name: t.input_schema for t in (await c.list_tools()).tools}

        def prop(tool: str, name: str) -> dict:
            p = tools[tool]["properties"][name]
            return next((x for x in p.get("anyOf", [p]) if x.get("type") != "null"), p)

        assert prop("book_import", "title")["maxLength"] == 120 and prop("book_import", "subtitle")["maxLength"] == 120
        assert prop("book_write_chapter", "title")["maxLength"] == 120 and prop("book_write_chapter", "note")["maxLength"] == 500
        assert prop("book_decide", "text")["maxLength"] == 4000 and prop("book_issue_add", "text")["maxLength"] == 4000
        assert prop("book_issue_close", "note")["maxLength"] == 500 and prop("book_answer", "note")["maxLength"] == 500
        assert prop("category_put", "aliases")["items"]["maxLength"] == 40
        assert prop("idea_add_conversation", "origin")["maxLength"] == 100
        part = tools["category_put"]["$defs"]["PartIn"]["properties"]
        assert part["text"]["maxLength"] == 2000 and part["reason"]["anyOf"][0]["maxLength"] == 500
        for tool, name in (("book_read_chapter", "number"), ("book_issues", "chapter_number"), ("book_issue_add", "chapter_number"),
                           ("ref_check", "chapter_number"), ("book_write_chapter", "number")):
            assert (prop(tool, name)["minimum"], prop(tool, name)["maximum"]) == (0, 9999), tool
        long = "가" * 200_000
        for tool, args in (("book_decide", {"text": long}), ("book_issue_add", {"text": long}),
                           ("book_import", {"title": "책", "subtitle": long}), ("book_issue_close", {"id": "I1", "note": long}),
                           ("book_write_chapter", {"number": 1, "content": "본문", "note": "x", "title": long}),
                           ("category_put", {"book": "메모", "author": "me", "source": {"key": "clack2012"}, "aliases": [long]}),
                           ("category_edit", {"book": "메모", "item_id": "clack2012", "parts": [{"text": long, "reason": "근거"}]})):
            r = await c.call_tool(tool, {**args, "project_id": "b"} if tool.startswith("book_") else args)
            assert r.is_error and "at most" in r.content[0].text, (tool, r.content[0].text[:200])
        ok = await c.call_tool("book_decide", {"text": "가" * 4000, "project_id": "b"})
        assert not ok.is_error
    assert store.read_chapter("alice", "b", 1).meta.title == "하나"  # 긴 제목은 저장되지 않았다


# ---- 16-1 시각 형식 통일·이미 가져온 파일·같은 파일 수정본 막기·올린 문서 없음 ----

async def test_same_file_edition_and_timestamps(store: LocalStore, settings: Settings):
    import re
    from pathlib import Path

    synth = Path(__file__).parent / "fixtures" / "synthetic" / "닿으려는_종_합성.docx"
    inbox = store.root / "users" / "alice" / "inbox"
    inbox.mkdir(parents=True)
    (inbox / "원고.docx").write_bytes(synth.read_bytes())
    (inbox / "다른.docx").write_bytes(synth.read_bytes() + b"\0")  # 내용이 다른 파일(가져오지 않음)
    async with Client(build_server(settings, store)) as c:
        made = await c.call_tool("book_import", {"path": "원고.docx", "project_id": "book"})
        assert not made.is_error, made.content[0].text[:300]
        again = await c.call_tool("book_import", {"path": "원고.docx", "project_id": "book", "new_edition": True})
        assert again.is_error and "이미 올린 파일입니다. 마지막 수정본 E1(원고.docx)" in again.content[0].text
        listed = (await c.call_tool("files_list", {})).content[0].text
        line = next(x for x in listed.splitlines() if x.startswith("- 원고.docx"))
        assert re.search(r"· \d{4}-\d\d-\d\d \d\d:\d\d:\d\d ·", line) and "이미 가져옴: 처음 올린 문서 E1(「" in line
        assert "이미 가져옴" not in next(x for x in listed.splitlines() if x.startswith("- 다른.docx"))
        outline = (await c.call_tool("book_outline", {"project_id": "book"})).content[0].text
        assert re.search(r"처음 올린 문서 E1 · 마지막 업로드 \d{4}-\d\d-\d\d \d\d:\d\d:\d\d\(원고\.docx\)", outline)
        empty = await c.call_tool("book_import", {"title": "아직 문서 없는 책", "project_id": "empty"})
        assert not empty.is_error
        assert "올린 문서 없음" in (await c.call_tool("book_outline", {"project_id": "empty"})).content[0].text


# ---- 16-2 project를 주면 그 프로젝트(와 연결 노드가 가리키는 책)의 책만 ----

async def test_project_scopes_book(store: LocalStore, settings: Settings):
    from magus.category.moves import add_link

    store.create_project("alice", "첫째", project_id="one")
    store.create_project("alice", "둘째", project_id="two")
    book = store.create_category("alice", "책B", "blank", "#1f2f5c", (), "one").id
    store.put_category_item("alice", CategoryItem("20261009000000001-aaaaaa", book, "남길 글", "me", "남길 글", "author"))
    async with Client(build_server(settings, store)) as c:
        wrong = await c.call_tool("category_put", {"book": "책B", "project": "둘째", "author": "me", "content": "x", "untitled": True})
        assert wrong.is_error and "「둘째」에는 「책B」 책이 없다(「첫째」에 있다)" in wrong.content[0].text
        nowhere = await c.call_tool("category_put", {"book": "책B", "project": "셋째", "author": "me", "content": "x", "untitled": True})
        assert nowhere.is_error and "셋째" in nowhere.content[0].text
        trash = await c.call_tool("category_trash", {"book": "책B", "project": "둘째", "note": "시험"})
        assert trash.is_error and len(store.list_category_items("alice", book)) == 1  # 전에는 「첫째」의 책B를 통째 옮겼다
        ok = await c.call_tool("category_put", {"book": "책B", "project": "첫째", "author": "me", "content": "넣음", "untitled": True})
        assert not ok.is_error
        add_link(store, "alice", "two", "one", store.node_of_book("alice", book)[1])  # 둘째 지도에 책B의 노드로 가는 연결 노드
        via = await c.call_tool("category_put", {"book": "책B", "project": "둘째", "author": "me", "content": "연결로", "untitled": True})
        assert not via.is_error, via.content[0].text
    assert len(store.list_category_items("alice", book)) == 3


# ---- 16-3 category_edit: 한 번에 하나, 쓸 부분에도 이유 ----

async def test_category_edit_one_job_and_reason(store: LocalStore, settings: Settings):
    from magus.melchior.bibliography import import_bibliography

    store.create_project("alice", "책", project_id="b")
    import_bibliography(store, "alice", "Ahlberg, P. (2019). Follow the footprints. Nature.\n", floor="b")
    async with Client(build_server(settings, store)) as c:
        both = await c.call_tool("category_edit", {"item_id": "ahlberg2019", "parts": [{"text": "대목", "reason": "근거"}], "checked": True})
        assert both.is_error and "한 번에 하나만 한다" in both.content[0].text and "parts · checked" in both.content[0].text
        colors = await c.call_tool("category_edit", {"book": "참고문헌", "item_id": "ahlberg2019", "scrap": True, "color": "빨강"})
        assert colors.is_error and "scrap · 책·노드 고치기" in colors.content[0].text
        bare = await c.call_tool("category_edit", {"item_id": "ahlberg2019", "parts": [{"text": "이유 없는 대목"}]})
        assert bare.is_error and "쓸 부분마다 이유" in bare.content[0].text  # 전에는 이유 없이 더한 뒤 checked=true로 원문 확인이 됐다
        assert store.get_passages("alice", "ahlberg2019") == [] and store.get_ref("alice", "ahlberg2019").status == "unverified"
        ok = await c.call_tool("category_edit", {"item_id": "ahlberg2019", "parts": [{"text": "발자국 대목", "reason": "근거"}]})
        assert not ok.is_error
        checked = await c.call_tool("category_edit", {"item_id": "ahlberg2019", "checked": True})
        assert not checked.is_error and store.get_ref("alice", "ahlberg2019").status == "verified"


# ---- 22-a 제목 없는 글의 보일 이름 규칙 하나 ----

def test_display_title_rule():
    from magus.store.formats import UNTITLED, display_title

    assert display_title("제목", "본문", {"장소": "엘알토"}, ["사진.jpg"]) == "제목"
    assert display_title(None, "본문", {}, ["현장 사진.jpg", "b.txt"]) == "현장 사진"
    assert display_title("", "  본문\n둘째 줄 ", {}, []) == "본문 둘째 줄"
    assert display_title(None, "", {"장소": "엘알토", "빈칸": ""}, []) == "장소: 엘알토"
    assert display_title(None, "", {}, []) == UNTITLED == "제목 없는 글"
    assert display_title(None, "가" * 50, {}, [], 30) == "가" * 30 + "…"  # 본문에서 만든 이름만 자른다
    assert display_title("나" * 70, "본문", {}, [], 30) == "나" * 70  # 제목은 자르지 않는다(제목 한도 80)


async def test_same_name_everywhere(store: LocalStore, settings: Settings):
    import io
    import zipfile

    from magus.export_zip import build_zip

    store.create_category("alice", "메모", "blank", "#1f2f5c", (), "common", category_id="notes")
    item = "20261009000000001-aaaaaa"
    store.put_category_item("alice", CategoryItem(item, "notes", "본문은 따로 있다", "me"))
    store.put_attachment("alice", f"notes/{item}", "장터 답사 기록.docx", b"PK")
    async with Client(build_server(settings, store)) as c:
        scrap = (await c.call_tool("category_edit", {"item_id": item, "scrap": True})).content[0].text
        listed = (await c.call_tool("files_list", {})).content[0].text
    names = zipfile.ZipFile(io.BytesIO(build_zip(store, "alice", ["common"]))).namelist()
    assert "“장터 답사 기록”" in scrap  # 전: 제목 → 첫 첨부 → 본문(같음)
    assert "책의 글 「장터 답사 기록」" in listed  # 전: 제목 → 첫 첨부 → 본문 30자(같음, 줄바꿈이 섞일 수 있었다)
    assert any(n.endswith(" 장터 답사 기록.md") for n in names)  # 전: zip은 첨부 이름을 보지 않고 본문 30자
    async with Client(build_server(settings, store)) as c:
        trashed = (await c.call_tool("category_trash", {"book": "메모", "item_id": item, "note": "시험"})).content[0].text
    assert "“장터 답사 기록”" in trashed  # 전: 휴지통 응답은 첨부 이름 없이 본문
    entry = next(t for t in store.list_trash("alice") if t.kind == "category_item")
    assert entry.preview == "장터 답사 기록"  # 휴지통 기록(웹 휴지통 줄)도 같은 규칙


# ---- 26 도구 설명 줄이기: 스키마의 title 주석·default null만 빼고, 이름이 title인 인자·값 있는 기본값은 그대로 ----

async def test_plain_schema(store: LocalStore, settings: Settings):
    import json

    from magus.server import plain_schema

    assert plain_schema({"title": "X", "properties": {"title": {"title": "Title", "type": "string"}, "k": {"default": None},
                                                         "s": {"default": "open"}}}) == {
        "properties": {"title": {"type": "string"}, "k": {}, "s": {"default": "open"}}}
    async with Client(build_server(settings, store)) as c:
        tools = {t.name: t.input_schema for t in (await c.list_tools()).tools}
    text = json.dumps(tools, ensure_ascii=False)
    assert '"title": "' not in text and '"default": null' not in text
    assert "title" in tools["category_put"]["properties"] and tools["book_issues"]["properties"]["status"]["default"] == "open"
    assert "items" in tools["category_put"]["properties"]["parts"]["anyOf"][0]
