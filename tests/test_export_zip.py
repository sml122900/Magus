"""프로젝트 zip 내려받기(#95, export_zip.build_zip) — 점검 24-a: 글·문헌 글·올린 문서·만든 문서·연결 노드가 든 프로젝트를 풀어
파일 이름과 앞머리를 본다(전에는 이 경로가 시험에서 한 번도 돌지 않았다)."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest
from mcp import Client

from magus.book.importer import import_manuscript
from magus.config import Settings
from magus.export_zip import build_zip
from magus.server import build_server
from magus.store import CategoryItem, LocalStore, Passage
from conftest import with_library

pytestmark = pytest.mark.anyio
SYNTH = Path(__file__).parent / "fixtures" / "synthetic" / "닿으려는_종_합성.docx"


async def test_project_zip_has_every_kind(store: LocalStore, settings: Settings):
    import_manuscript(store, "alice", SYNTH, project_id="book", synthetic=True)
    store.add_decision("alice", "book", "1장은 고치지 않는다")
    walk = store.add_node("alice", "book", "답사", x=300, y=0)
    notes = store.create_category("alice", "장날 메모", "blank", "#1f2f5c", (), "book", walk.id).id
    store.put_category_item("alice", CategoryItem("20261009000000001-aaaaaa", notes, "엘알토 장날 본문", "me", "엘알토 장날", "author",
                                                  reason="답사", where="2쪽", passages=(Passage("시장 대목", "근거", "p.2"),), tags=("시장",)))
    store.put_category_item("alice", CategoryItem("20261009000000002-aaaaaa", notes, "Claude가 정리한 답", "ai",
                                                  parent_id="20261009000000001-aaaaaa"))
    async with Client(build_server(settings, store)) as c:
        made = await c.call_tool("book_document", {"kind": "출처 확인 문서", "project_id": "book", "untitled": True})
        assert not made.is_error, made.content[0].text
        r = await c.call_tool("category_put", {"book": refs_book(store), "author": "me", "source": {"key": "clack2012"}, "checked": True,
                                               "parts": [{"text": "네발동물 대목", "reason": "근거", "where": "p.3"}]})
        assert not r.is_error, r.content[0].text
    with_library(store, "alice")
    store.add_link_node("alice", "common", "book", walk.id)

    data = build_zip(store, "alice", ["book", "common"])
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = z.namelist()
        text = {n: z.read(n).decode("utf-8") for n in names if n.endswith((".md", ".json"))}
    title = store.get_project("alice", "book").title
    root = next(n.split("/")[0] for n in names if n.endswith("/지도.json") and "내 서재" not in n)
    assert "README.md" in names and f"{root}/지도.json" in names
    # 올린 문서: 원본 사본·장·확인 요청·결정
    ms = f"{root}/가운데 노드/올린 문서"
    assert any(n.startswith(f"{ms}/") and n.endswith(".docx") for n in names)
    chapters = sorted(n for n in names if n.startswith(f"{ms}/장/"))
    assert chapters and text[chapters[0]].startswith("---\n장: ") and "\n상태: " in text[chapters[0]]
    assert text[f"{ms}/확인 요청.md"].startswith("# 확인 요청\n\n- I1 · 열림")
    assert "1장은 고치지 않는다" in text[f"{ms}/결정.md"]
    # 만든 문서(출처 확인 문서)는 가운데 노드에 파일 하나
    assert any(n.startswith(f"{root}/가운데 노드/") and "출처 확인 문서" in n and n.endswith(".md") for n in names)
    # 글: 날짜·제목 파일 이름, 앞머리(작성자·이유·위치·태그·id), 쓸 부분
    post = next(n for n in names if n.startswith(f"{root}/답사/장날 메모/") and "엘알토 장날" in n)
    body = text[post]
    assert body.startswith("---\n날짜: ") and "\n제목: 엘알토 장날\n" in body and "\n작성자: 저자\n" in body
    assert "\n이유: 답사\n" in body and "\n위치: 2쪽\n" in body and "\nid: 20261009000000001-aaaaaa\n" in body
    assert "엘알토 장날 본문" in body and "> 시장 대목" in body
    reply = next(n for n in names if n.startswith(f"{root}/답사/장날 메모/") and "Claude가 정리한 답" in n)
    assert "\n작성자: Claude(AI)\n" in text[reply] and "\n응답한 글: 20261009000000001-aaaaaa\n" in text[reply]
    # 문헌 글: key·상태·쓸 부분
    ref = next(n for n in names if "/문헌 글/clack2012" in n)
    assert "\nkey: clack2012\n" in text[ref] and "원문 확인(저자가 원문을 읽고 확인)" in text[ref] and "> 네발동물 대목" in text[ref]
    # 지도.json: 노드·책·선
    project_map = json.loads(text[f"{root}/지도.json"])
    assert project_map["프로젝트"] == title and {n["이름"] for n in project_map["노드"]} >= {"가운데", "답사"}
    # 「내 서재」의 연결 노드는 원본을 가리키는 메모만(내용은 원본 폴더에 한 번)
    link = next(n for n in names if n.endswith("/연결.md") and n.startswith("내 서재/"))
    assert "「답사」 노드를 가리킵니다" in text[link] and "(이 zip에 함께 들었습니다)" in text[link]


def refs_book(store: LocalStore) -> str:
    ref = store.get_ref("alice", "clack2012")
    assert ref is not None and ref.book
    return store.get_category("alice", ref.book).name
