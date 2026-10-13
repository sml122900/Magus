"""공공 문서 호환성 점검(2026-10-14 밤): 실제 공공기관 문서(hwp·hwpx·docx·pptx·xlsx·pdf)로 뽑아 보고 고친 것의 회귀 시험.

시험 파일은 모두 코드로 만든 최소 구조다(받은 문서는 리포에 넣지 않는다). 결과 표는 docs/nightly/2026-10-14-compat.md.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from mcp import Client
from test_extract_formats import POST, _hwp, _varied, _write, _zip

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


def test_hwp_pua_symbols_mapped(tmp_path: Path):
    """한글 문서의 PUA 글자 둘(실제 공공 문서에서 봄): 기호 글꼴 가운뎃점 U+F09E → '·', 옛한글 U+F53A → 'ᄒᆞᆫ'."""
    hwp = ex.extract(_write(tmp_path, "서식.hwp", _hwp([["용지는 백색 A4에 글 워드프로세서를 사용", "외화원화 차입"]])))
    assert hwp.text == "용지는 백색 A4에 ᄒᆞᆫ글 워드프로세서를 사용\n외화·원화 차입\n"
    section = ('<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph">'
               "<hp:p><hp:run><hp:t>거주자비거주자</hp:t></hp:run></hp:p></hs:sec>")
    hwpx = ex.extract(_write(tmp_path, "보도.hwpx", _zip({"Contents/section0.xml": section})))
    assert hwpx.text == "거주자·비거주자\n"


def test_pptx_symbols_and_blank_lines_tidied(tmp_path: Path):
    """발표 자료(2026-10-14 점검): Wingdings 화살표 U+F0E0 → '→', 빈 문단이 수십 줄 이어지던 것은 빈 줄 하나로. PDF는 다듬지 않는다."""
    A = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'
    paras = "<a:p><a:r><a:t>폴더를 클릭  추가</a:t></a:r></a:p>" + "<a:p></a:p>" * 18 + "<a:p><a:r><a:t>다음 줄</a:t></a:r></a:p>"
    slide = f"<p:sld {A}><p:cSld><p:spTree><p:sp><p:txBody>{paras}</p:txBody></p:sp></p:spTree></p:cSld></p:sld>"
    got = ex.extract(_write(tmp_path, "발표.pptx", _zip({"ppt/slides/slide1.xml": slide})))
    assert got.text == "## 슬라이드 1\n폴더를 클릭 → 추가\n\n다음 줄\n", got.text
    assert ex.tidy("가\n \n　\n\n나\n\n다") == "가\n\n나\n\n다" and ".pdf" not in ex.TIDY


def test_xlsx_numbers_15_digits():
    """xlsx 숫자는 엑셀이 보이는 유효 숫자 15자리까지(부동소수 꼬리를 뗀다). 정수·짧은 소수·숫자 아닌 것은 그대로."""
    assert ex._number_text("39.509900352700001") == "39.5099003527"
    assert ex._number_text("0.94460617502999999") == "0.94460617503"
    assert ex._number_text("14.3932937499") == "14.3932937499"  # 15자리 안
    assert [ex._number_text(x) for x in ("103737", "1785", "-0.5", "1.5E-3", "#N/A", "")] == ["103737", "1785", "-0.5", "1.5E-3", "#N/A", ""]
    assert ex._number_text("1.2345678901234568E+18") == "1.23456789012346e+18"


HPX = 'xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph"'


def _hp(text: str, inner: str = "", after: str = "") -> str:
    return f"<hp:p><hp:run><hp:t>{text}</hp:t>{inner}<hp:t>{after}</hp:t></hp:run></hp:p>"


def test_hwpx_notes_and_tables_after_their_paragraph(tmp_path: Path):
    """hwpx: 문단 안에 든 각주·머리말·표의 글자는 그 문단이 끝난 뒤에(2026-10-14, 실제 연구보고서에서 각주가 본문 문장 한가운데 끼었다)."""
    note = f'<hp:ctrl><hp:footNote number="1"><hp:subList>{_hp(" 반면 사업체는 일정한 장소를 의미한다")}</hp:subList></hp:footNote></hp:ctrl>'
    head = f"<hp:ctrl><hp:header><hp:subList>{_hp('소금청 보고서')}</hp:subList></hp:header></hp:ctrl>"
    table = (f"<hp:tbl><hp:tr><hp:tc><hp:subList>{_hp('칸 하나')}</hp:subList></hp:tc>"
             f"<hp:tc><hp:subList>{_hp('칸 둘')}</hp:subList></hp:tc></hp:tr></hp:tbl>")
    section = (f"<hs:sec {HPX}>" + _hp("", head, "보도자료") + _hp("기업체란 관리하는 단위이다(통계청, 2015)", note, ". 개념을 그대로 적용하였다.")
               + _hp("다음 표와 같다", table, " 끝.") + _hp("마지막 문단") + "</hs:sec>")
    got = ex.extract(_write(tmp_path, "보고서.hwpx", _zip({"Contents/section0.xml": section})))
    assert got.text == ("보도자료\n소금청 보고서\n"
                        "기업체란 관리하는 단위이다(통계청, 2015). 개념을 그대로 적용하였다.\n 반면 사업체는 일정한 장소를 의미한다\n"
                        "다음 표와 같다 끝.\n칸 하나\n칸 둘\n"
                        "마지막 문단\n"), got.text
    # 문단 하나에 든 큰 표: 붙잡아 둔 글자가 30만 자를 넘으면 그때까지를 내보내고 앞부분만(메모리를 무한히 쓰지 않는다)
    cells = "".join(f"<hp:tc><hp:subList>{_hp(f'{n:05d}' + _varied(n, 995))}</hp:subList></hp:tc>" for n in range(400))  # 잘 압축되지 않게(zipguard)
    big = f"<hs:sec {HPX}>" + _hp("머리", f"<hp:tbl><hp:tr>{cells}</hp:tr></hp:tbl>") + _hp("뒤 문단") + "</hs:sec>"
    cut = ex.extract(_write(tmp_path, "큰 표.hwpx", _zip({"Contents/section0.xml": big})))
    assert cut.status == "truncated" and len(cut.text) == ex.TEXT_MAX and cut.text.startswith("머리00000") and "뒤 문단" not in cut.text


def test_encrypted_hwpx_says_locked(tmp_path: Path):
    """암호·배포용 hwpx: 목록에 암호화 정보가 있고 구역이 XML이 아니면 '읽을 수 없는 hwp'(까닭 있음). 전에는 까닭 없는 실패였다."""
    manifest = ('<?xml version="1.0"?><odf:manifest xmlns:odf="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0">'
                '<odf:file-entry odf:full-path="Contents/section0.xml" odf:media-type="application/xml">'
                '<odf:encryption-data odf:checksum-type="SHA1" odf:checksum="x"><odf:algorithm odf:algorithm-name="AES"/>'
                "</odf:encryption-data></odf:file-entry></odf:manifest>")
    locked = _zip({"mimetype": "application/hwp+zip", "META-INF/manifest.xml": manifest, "Contents/section0.xml": b"\x8f\x01\xfe" * 300})
    got = ex.extract(_write(tmp_path, "배포.hwpx", locked))
    assert (got.status, got.reason, ex.unreadable_hwp({"status": got.status, "reason": got.reason})) == (
        "failed", "hwp_locked", "암호가 걸렸거나 배포용 문서")
    plain = _zip({"mimetype": "application/hwp+zip", "META-INF/manifest.xml": "<odf:manifest/>",
                  "Contents/section0.xml": '<hs:sec xmlns:hs="s" xmlns:hp="p"><hp:p><hp:run><hp:t>보통 문서</hp:t></hp:run></hp:p></hs:sec>'})
    assert ex.extract(_write(tmp_path, "보통.hwpx", plain)).text == "보통 문서\n"
    broken = _zip({"Contents/section0.xml": b"\x8f\x01\xfe" * 300})  # 목록에 암호화 정보가 없으면 그냥 깨진 파일
    assert (ex.extract(_write(tmp_path, "깨짐.hwpx", broken)).reason) == ""


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
async def test_search_snippet_shows_the_whole_query(store: LocalStore, data_dir: Path):
    """맞은 곳 앞뒤 글자는 검색어 전체가 이어 나오는 곳(낱말 사이 줄바꿈 허용) → 긴 낱말부터(2026-10-14 공공 문서 점검).
    전에는 첫 낱말이 처음 나온 곳(머리말의 담당 부서 이름 등)이 보였다."""
    text = ("담당 부서 해외건설정책과\n" + "가나다라마바사 " * 40 + "\n정부 공공 금융기관 해외건설\n위기극복 지혜모아\n" + "아자차카 " * 40
            + "\n용지는 한글 문서로 " + "타파하 " * 40 + "\nᄒᆞᆫ글 워드프로세서를 사용\n")
    with_library(store, "alice")
    book = store.create_category("alice", "자료", "blank", "#1f2f5c", (), "common").id
    store.put_category_item("alice", CategoryItem(POST, book, "보도", "me", title="보도", title_by="author"))
    att = store.put_attachment("alice", f"{book}/{POST}", "보도.txt", text.encode())
    store.attachment_text("alice", f"{book}/{POST}", att.id)
    settings = Settings.from_env({"USER_ID": "alice", "DATA_DIR": str(data_dir)})
    async with Client(build_server(settings, store)) as c:
        first = (await c.call_tool("category_search", {"query": "해외건설 위기극복"})).content[0].text
        second = (await c.call_tool("category_search", {"query": "글 워드프로세서"})).content[0].text
    assert "해외건설 위기극복 지혜모아" in first and "담당 부서" not in first, first
    assert "ᄒᆞᆫ글 워드프로세서를 사용" in second, second


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
    # 앞뒤 100자는 뽑은 글자 전체에서(조각 첫머리에 잘리지 않는다): 앞 줄(29번 줄)의 끝이 보인다
    shown = found.split("글자에서 맞음 · 쪽 2/", 1)[1].split("“", 1)[1].split("”", 1)[0]
    assert shown.startswith("…") and "옹기장수" in shown and "29번 줄" not in shown and shown.index("옹기장수") > 90, shown
