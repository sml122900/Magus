"""공공 문서 호환성 점검(2026-10-14 밤): 실제 공공기관 문서(hwp·hwpx·docx·pptx·xlsx·pdf)로 뽑아 보고 고친 것의 회귀 시험.

시험 파일은 모두 코드로 만든 최소 구조다(받은 문서는 리포에 넣지 않는다). 결과 표는 docs/nightly/2026-10-14-compat.md.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from mcp import Client
from test_extract_formats import POST, _hwp, _write, _zip

from conftest import with_library
from magus import extract as ex
from magus.config import Settings
from magus.server import build_server
from magus.store import CategoryItem, LocalStore

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
MC = ('xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
      'xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape" xmlns:v="urn:schemas-microsoft-com:vml"')


def _part(root: str, body: str) -> str:
    return f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:{root} {W} {MC}>{body}</w:{root}>'


def _p(text: str) -> str:
    return f"<w:p><w:r><w:t xml:space=\"preserve\">{text}</w:t></w:r></w:p>"


def _textbox(text: str) -> str:
    """Word가 글상자를 저장하는 꼴: 새 모양(mc:Choice)과 옛 모양(mc:Fallback, VML)에 같은 글이 두 번 들어 있다."""
    return ("<w:r><mc:AlternateContent>"
            f"<mc:Choice Requires=\"wps\"><w:drawing><wps:txbx><w:txbxContent>{_p(text)}</w:txbxContent></wps:txbx></w:drawing></mc:Choice>"
            f"<mc:Fallback><w:pict><v:textbox><w:txbxContent>{_p(text)}</w:txbxContent></v:textbox></w:pict></mc:Fallback>"
            "</mc:AlternateContent></w:r>")


def _docx_full() -> bytes:
    body = ("<w:body>"
            # 문단 서식의 탭 위치(w:tabs/w:tab)는 글자가 아니다. 글자 묶음 안의 탭만 탭
            '<w:p><w:pPr><w:tabs><w:tab w:val="left" w:pos="720"/><w:tab w:val="right" w:pos="9000"/></w:tabs></w:pPr>'
            "<w:r><w:t>보도 일시</w:t></w:r><w:r><w:tab/><w:t>2026. 10. 14.</w:t></w:r></w:p>"
            '<w:tbl><w:tr><w:tc><w:p><w:r><w:t>표 안 나루터</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>1,785원</w:t></w:r></w:p></w:tc></w:tr></w:tbl>'
            f"<w:p><w:r><w:t>글상자 앞</w:t></w:r>{_textbox('글상자 속 옹기장수')}</w:p>"
            '<w:p><w:r><w:t>각주가 달린 문장</w:t></w:r><w:r><w:footnoteReference w:id="1"/></w:r></w:p>'
            "</w:body>")
    sep = ('<w:footnote w:type="separator" w:id="-1"><w:p><w:r><w:separator/></w:r></w:p></w:footnote>'
           '<w:footnote w:type="continuationSeparator" w:id="0"><w:p><w:r><w:continuationSeparator/></w:r></w:p></w:footnote>')
    return _zip({
        "[Content_Types].xml": "<Types/>",
        "word/document.xml": _part("document", body),
        "word/footnotes.xml": _part("footnotes", sep + '<w:footnote w:id="1"><w:p><w:r><w:footnoteRef/></w:r>'
                                                       "<w:r><w:t xml:space=\"preserve\"> 통계청(2025) 나루 통행 조사</w:t></w:r></w:p></w:footnote>"),
        "word/endnotes.xml": _part("endnotes", '<w:endnote w:id="1">' + _p("미주에 적은 출처") + "</w:endnote>"),
        "word/header1.xml": _part("hdr", _p("소금청 보도자료")),
        "word/header2.xml": _part("hdr", _p("소금청 보도자료")),  # 첫 쪽·짝수 쪽 머리말이 같은 글이면 한 번만
        "word/footer1.xml": _part("ftr", _p("문의: 나루과")),
    })


def test_docx_notes_headers_textbox_once(tmp_path: Path):
    got = ex.extract(_write(tmp_path, "보도자료.docx", _docx_full()))
    assert got.status == "ok", got
    assert got.text == ("보도 일시\t2026. 10. 14.\n"  # 문단 서식의 탭 위치가 탭으로 새지 않는다
                        "표 안 나루터\n1,785원\n"
                        "글상자 앞글상자 속 옹기장수\n\n"  # 글상자는 한 번(옛 모양 mc:Fallback은 건너뛴다)
                        "각주가 달린 문장\n"
                        "\n## 각주\n 통계청(2025) 나루 통행 조사\n"
                        "\n## 미주\n미주에 적은 출처\n"
                        "\n## 머리말·꼬리말\n소금청 보도자료\n문의: 나루과\n"), got.text
    assert got.text.count("옹기장수") == 1


def test_docx_without_extra_parts_unchanged(tmp_path: Path):
    """각주·머리말이 없는 docx는 전과 같다(본문만, 머리 '## …' 없음)."""
    data = _zip({"word/document.xml": _part("document", "<w:body>" + _p("첫 문단") + _p("둘째 문단") + "</w:body>")})
    assert ex.extract(_write(tmp_path, "a.docx", data)).text == "첫 문단\n둘째 문단\n"


@pytest.mark.anyio
async def test_search_item_with_only_attachment_has_no_empty_quote(store: LocalStore, data_dir: Path):
    """본문 없이 첨부만 있는 글(2026-10-14 메인 세션 보고): category_search 결과에 빈 인용 줄 `“”`이 보이지 않는다."""
    with_library(store, "alice")
    book = store.create_category("alice", "논문", "blank", "#1f2f5c", (), "common").id
    store.put_category_item("alice", CategoryItem(POST, book, "", "me", title="논문 1~10", title_by="author"))
    att = store.put_attachment("alice", f"{book}/{POST}", "보도자료.hwp", _hwp([["나루터 통행료 조사 결과"]]))
    store.attachment_text("alice", f"{book}/{POST}", att.id)
    settings = Settings.from_env({"USER_ID": "alice", "DATA_DIR": str(data_dir)})
    async with Client(build_server(settings, store)) as c:
        found = (await c.call_tool("category_search", {"query": "통행료"})).content[0].text
    assert "제목 「논문 1~10」" in found and f"(첨부:{att.id}) 글자에서 맞음" in found
    after_head = found.split("제목 「논문 1~10」", 1)[1].split("\n")
    assert "“”" not in found and after_head[1].startswith("   첨부 1개:"), found


@pytest.mark.anyio
async def test_search_hit_page_is_where_the_word_is(store: LocalStore, data_dir: Path):
    """맞은 쪽은 조각(800자)이 시작한 쪽이 아니라 조각 안에서 낱말이 있는 쪽이다(2026-10-14). 공공 문서는 빈 줄이 없어 조각이 800자씩
    잘리므로, 쪽 경계(3,000자) 바로 뒤의 낱말이 앞 쪽으로 안내될 수 있었다."""
    lines = [f"{n:02d}번 줄 " for n in range(60)]
    lines[30] = "30번 줄 옹기장수 "
    text = "".join(line.ljust(99, "가") + "\n" for line in lines)  # 한 줄 100자: 1쪽은 0~2,999, 30번 줄부터 2쪽
    assert text.index("옹기장수") == 3000 + 6 and ex.page_of(text, "옹기장수") == 2
    with_library(store, "alice")
    book = store.create_category("alice", "자료", "blank", "#1f2f5c", (), "common").id
    store.put_category_item("alice", CategoryItem(POST, book, "긴 자료", "me", title="자료", title_by="author"))
    att = store.put_attachment("alice", f"{book}/{POST}", "긴 자료.txt", text.encode())
    store.attachment_text("alice", f"{book}/{POST}", att.id)
    settings = Settings.from_env({"USER_ID": "alice", "DATA_DIR": str(data_dir)})
    async with Client(build_server(settings, store)) as c:
        found = (await c.call_tool("category_search", {"query": "옹기장수"})).content[0].text
    assert "글자에서 맞음 · 쪽 2/" in found and f'category_search(attachment="{att.id}", page=2)' in found, found
