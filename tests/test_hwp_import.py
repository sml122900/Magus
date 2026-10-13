"""한글 원고 가져오기(2026-10-14, docs/decisions/hwp-import.md): hwpx·hwp를 docx와 같은 블록 열로 읽어 올린 문서로.
대화의 book_import에서 replace(바꾸기)를 뺐다(운영 규칙 #78).

- 시험 파일은 모두 코드로 만든다(밖에서 받지 않는다). hwp는 olefile이 쓰지 못하므로 아주 작은 CFB(OLE) 작성기를 여기 둔다
  (tests/test_extract_formats.py의 것과 같은 꼴. 그 파일은 다른 작업이 고치는 중이라 가져다 쓰지 않고 베꼈다).
- hwpx 메모(fieldBegin type=MEMO)의 꼴은 OWPML 공개 문서를 따른 추정이다. 실제 한글이 만든 파일로 확인하는 일은 대기(결정 문서 '남은 것')."""

from __future__ import annotations

import io
import struct
import zipfile
import zlib
from pathlib import Path

import pytest
from mcp import Client

from magus.book import hwp_reader
from magus.book.importer import UNREADABLE, import_manuscript, read_manuscript
from magus.book.reupload import reupload_manuscript
from magus.config import Settings
from magus.docupdate import list_documents, update_document
from magus.melchior.refs import read_fulltext
from magus.server import build_server
from magus.store import LocalStore

pytestmark = pytest.mark.anyio
U = "alice"

# ---- hwpx(OWPML) ---------------------------------------------------------------------------------------------

NS = ('xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph" xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" '
      'xmlns:hh="http://www.hancom.co.kr/hwpml/2011/head" xmlns:opf="http://www.idpf.org/2007/opf/"')
STYLES = [("바탕글", "Normal", 0), ("본문", "Body", 0), ("개요 1", "Outline 1", 1), ("개요 2", "Outline 2", 2),
          ("개요 3", "Outline 3", 3), ("차례 1", "TOC 1", 0)]
NORMAL, OUT1, OUT2, OUT3, TOC = 0, 2, 3, 4, 5
BULLET_PARA = 4  # 문단 모양 id: 글머리표
HEADER = (
    f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><hh:head {NS} version="1.4" secCnt="2"><hh:refList>'
    '<hh:paraProperties itemCnt="5">'
    + "".join(f'<hh:paraPr id="{i}" tabPrIDRef="0"><hh:align horizontal="JUSTIFY"/><hh:heading type="{t}" idRef="0" level="{lv}"/></hh:paraPr>'
              for i, (t, lv) in enumerate([("NONE", 0), ("OUTLINE", 0), ("OUTLINE", 1), ("OUTLINE", 2), ("BULLET", 0)]))
    + '</hh:paraProperties><hh:styles itemCnt="6">'
    + "".join(f'<hh:style id="{i}" type="PARA" name="{n}" engName="{e}" paraPrIDRef="{p}" charPrIDRef="0" nextStyleIDRef="0" langID="1042"/>'
              for i, (n, e, p) in enumerate(STYLES))
    + "</hh:styles></hh:refList></hh:head>"
)
NUMBERING = ('<hh:numberings itemCnt="1"><hh:numbering id="1" start="0">'
             '<hh:paraHead start="1" level="1" align="LEFT" numFormat="DIGIT">제^1장</hh:paraHead>'
             '<hh:paraHead start="1" level="2" align="LEFT" numFormat="HANGUL_SYLLABLE">^2.</hh:paraHead>'
             '<hh:paraHead start="1" level="3" align="LEFT" numFormat="DIGIT">^2-^3)</hh:paraHead></hh:numbering></hh:numberings>')


def p(inner: str, style: int = NORMAL, para: int | None = None) -> str:
    """문단. inner: 런 안에 들어갈 XML(글자는 t()로)."""
    para = STYLES[style][2] if para is None else para
    return (f'<hp:p id="0" paraPrIDRef="{para}" styleIDRef="{style}" pageBreak="0" columnBreak="0" merged="0">'
            f'<hp:run charPrIDRef="0">{inner}</hp:run><hp:linesegarray><hp:lineseg textpos="0"/></hp:linesegarray></hp:p>')


def t(text: str) -> str:
    return f"<hp:t>{text}</hp:t>"


def memo(mid: str, anchor: str, *, author: str = "Claude", body: str | None = None, ref: str | None = None) -> str:
    params = (f'<hp:parameters cnt="3" name=""><hp:stringParam name="Author">{author}</hp:stringParam>'
              '<hp:stringParam name="CreateDateTime">2026-10-05 09:00:00</hp:stringParam>'
              + (f'<hp:stringParam name="MemoID">{ref}</hp:stringParam>' if ref else "") + "</hp:parameters>")
    sub = f'<hp:subList id="" textDirection="HORIZONTAL">{p(t(body))}</hp:subList>' if body else ""
    return (f'<hp:ctrl><hp:fieldBegin id="{mid}" type="MEMO" name="" editable="1" dirty="0" fieldid="9{mid}">{params}{sub}'
            f'</hp:fieldBegin></hp:ctrl>{t(anchor)}<hp:ctrl><hp:fieldEnd beginIDRef="{mid}" fieldid="9{mid}"/></hp:ctrl>')


def cell(text: str, col: int, row: int, span: int = 1) -> str:
    return (f'<hp:tc name="" header="0" borderFillIDRef="1"><hp:subList id="" vertAlign="CENTER">{p(t(text))}</hp:subList>'
            f'<hp:cellAddr colAddr="{col}" rowAddr="{row}"/><hp:cellSpan colSpan="{span}" rowSpan="1"/><hp:cellSz width="100" height="100"/></hp:tc>')


def sec(*paras: str, tail: str = "") -> str:
    return f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><hs:sec {NS}>{"".join(paras)}{tail}</hs:sec>'


TABLE = ('<hp:tbl id="1" rowCnt="2" colCnt="3"><hp:sz width="1" height="1"/>'
         f'<hp:tr>{cell("연도", 0, 0)}{cell("인구|수", 1, 0, span=2)}</hp:tr>'
         f'<hp:tr>{cell("1990", 0, 1)}{cell("5백만", 1, 1)}{cell("늘어남", 2, 1)}</hp:tr></hp:tbl>')
SECTION0 = sec(
    p('<hp:secPr id=""><hp:grid lineGrid="0"/></hp:secPr><hp:ctrl><hp:colPr id="" type="NEWSPAPER" colCount="1"/></hp:ctrl>' + t("가상의 한글 책")),
    p(t("A Hangul Book")),
    p(t("차례")),
    p(t('제1부 바다<hp:tab width="100" leader="DOT" type="RIGHT"/>1'), TOC),
    p(t('제1장 물고기의 결심<hp:tab width="100" leader="DOT" type="RIGHT"/>3'), TOC),
    p(t('제2장 뭍으로<hp:tab width="100" leader="DOT" type="RIGHT"/>9'), TOC),
)
SECTION1 = sec(
    p('<hp:ctrl><hp:header id="1" applyPageType="BOTH"><hp:subList id="">' + p(t("머리말 글")) + "</hp:subList></hp:header></hp:ctrl>"
      + t("제1부 바다에서"), OUT1),
    p(t("제1장 물고기의 결심"), OUT2),
    p(t("1. 데본기의 바다"), OUT3),
    p(t("앞 글 ") + memo("7001", "(Daeschler, Shubin &amp; Jenkins, 2006)에 따르면", body="확인 필요: 원문 대조") + t(" 물고기가 올라왔다.")),
    p(TABLE + t("표 1. 인구")),
    p(t("목록 항목"), NORMAL, BULLET_PARA),
    p(t("본문") + '<hp:ctrl><hp:footNote number="1" instId="1"><hp:subList id="">' + p(t("Galor(2022), 13쪽."))
      + "</hp:subList></hp:footNote></hp:ctrl>" + t(" 이어서.")),
    p('<hp:pic id="5"><hp:img binaryItemIDRef="image1"/></hp:pic>' + t("그림 설명 ") + "<hp:equation><hp:script>a+b</hp:script></hp:equation>"),
    p(t('남길 글<hp:deleteBegin Id="1" TcId="1" paraend="0"/>지운 글<hp:deleteEnd Id="1" TcId="1" paraend="0"/> 이어짐')),
    p(t("제2장 뭍으로"), OUT2),
    p(memo("7002", "Clack(2012)는 손가락을 셌다", author="홍길동", ref="m2") + t(".")),
    p('<hp:switch><hp:case hp:required-namespace="http://example.com/x">' + t("둘") + "</hp:case><hp:default>" + t("하나") + "</hp:default></hp:switch>"),
    p(t("제2부 뭍"), OUT1),
    p(t("제3장 사람"), OUT2),
    p(t("사람은 걸었다.")),
    p(t("참고문헌")),
    p(t("Daeschler, E. B., Shubin, N. H., &amp; Jenkins, F. A. (2006). A Devonian tetrapod-like fish. Nature, 440, 757–763.")),
    p(t("Clack, J. A. (2012). Gaining Ground. Indiana University Press.")),
    tail='<hp:memogroup><hp:memo id="m2" author="홍길동"><hp:paraList>' + p(t("서지 확인: Clack(2012)")) + "</hp:paraList></hp:memo></hp:memogroup>",
)
CONTENT = (f'<?xml version="1.0" encoding="UTF-8"?><opf:package {NS}><opf:metadata><opf:title>가상의 한글 책 — 부제 하나</opf:title></opf:metadata>'
           '<opf:manifest><opf:item id="header" href="Contents/header.xml" media-type="application/xml"/>'
           '<opf:item id="section0" href="Contents/section0.xml" media-type="application/xml"/>'
           '<opf:item id="section1" href="Contents/section1.xml" media-type="application/xml"/></opf:manifest>'
           '<opf:spine><opf:itemref idref="header" linear="no"/><opf:itemref idref="section0"/><opf:itemref idref="section1"/></opf:spine></opf:package>')


def _zip(files: dict[str, str | bytes]) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)
    return out.getvalue()


def hwpx(section1: str = SECTION1, *, extra: dict[str, str] | None = None, header: str = HEADER, section0: str = SECTION0) -> bytes:
    return _zip({"mimetype": "application/hwp+zip", "Contents/section1.xml": section1,  # zip 안 차례와 spine 차례가 다르다
                 "Contents/content.hpf": CONTENT, "Contents/header.xml": header, "Contents/section0.xml": section0, **(extra or {})})


def write(folder: Path, name: str, data: bytes) -> Path:
    path = folder / name
    path.write_bytes(data)
    return path


def test_hwpx_blocks_headings_tables_memos_notes(tmp_path: Path):
    m = read_manuscript(write(tmp_path, "원고.hwpx", hwpx()))
    assert m.source == "hwpx" and m.title == "가상의 한글 책 — 부제 하나"
    texts = [b.text for b in m.blocks]
    assert texts[:3] == ["가상의 한글 책", "A Hangul Book", "차례"]  # 구역 차례는 spine(section0 → section1). 구역 속성·단 정의는 글이 아니다
    assert "제1장 물고기의 결심\t3" in texts  # 목차 줄(차례 스타일, 제목 단계 아님)
    heads = {b.text: b.heading_level for b in m.blocks if b.heading_level}
    assert heads == {"제1부 바다에서": 1, "제1장 물고기의 결심": 2, "1. 데본기의 바다": 3, "제2장 뭍으로": 2, "제2부 뭍": 1, "제3장 사람": 2}
    assert "머리말 글" not in "".join(texts)  # 머리말·꼬리말은 싣지 않는다(docx와 같다)
    assert "앞 글 (Daeschler, Shubin & Jenkins, 2006)에 따르면 물고기가 올라왔다." in texts
    at = texts.index("표 1. 인구")
    table = m.blocks[at + 1]
    assert table.kind == "table" and table.text == "| 연도 | 인구\\|수 |  |\n|---|---|---|\n| 1990 | 5백만 | 늘어남 |"
    assert [b for b in m.blocks if b.text == "목록 항목"][0].is_list
    assert "본문[^1] 이어서." in texts and texts[texts.index("본문[^1] 이어서.") + 1] == "[^1]: Galor(2022), 13쪽."
    assert "[그림 1]그림 설명 [수식]" in texts and (m.figures, m.tables, m.equations) == (1, 1, 1)
    assert "남길 글 이어짐" in texts and "하나" in texts and "둘" not in texts
    first, second = m.comments
    assert (first.author, first.date, first.text) == ("Claude", "2026-10-05 09:00:00", "확인 필요: 원문 대조")
    assert first.anchor == "(Daeschler, Shubin & Jenkins, 2006)에 따르면" and m.blocks[first.block_index].text.startswith("앞 글")
    assert (second.author, second.text, second.anchor) == ("홍길동", "서지 확인: Clack(2012)", "Clack(2012)는 손가락을 셌다")  # 메모 묶음에서 내용


def test_hwpx_outline_numbers_become_text(store: LocalStore, tmp_path: Path):
    """개요 번호('제^1장', '^2.')는 글자로 저장되지 않는다. 보이는 번호를 붙여 '제N장'을 찾게 한다(이미 적었으면 그대로)."""
    numbered = HEADER.replace("</hh:refList>", NUMBERING + "</hh:refList>")
    first = sec(p('<hp:secPr id="" outlineShapeIDRef="1"/>' + t("가상의 한글 책")))
    body = sec(p(t("물고기의 결심"), OUT1), p(t("데본기의 바다"), OUT2), p(t("세부"), OUT3), p(t("둘째 절"), OUT2), p(t("글.")),
               p(t("뭍으로"), OUT1), p(t("첫 절"), OUT2), p(t("글.")), p(t("제3장 사람"), OUT1), p(t("글.")),
               p('<hp:pic id="1"><hp:caption side="BOTTOM"><hp:subList id="">' + p(t("그림 1. 화석")) + "</hp:subList></hp:caption></hp:pic>"),
               p('<hp:tbl id="2" rowCnt="1" colCnt="1"><hp:caption side="TOP"><hp:subList id="">' + p(t("표 1. 연대"))
                 + f"</hp:subList></hp:caption><hp:tr>{cell('데본기', 0, 0)}</hp:tr></hp:tbl>"))
    m = read_manuscript(write(tmp_path, "번호.hwpx", hwpx(body, header=numbered, section0=first)))
    texts = [b.text for b in m.blocks]
    assert texts[1:9] == ["제1장 물고기의 결심", "가. 데본기의 바다", "가-1) 세부", "나. 둘째 절", "글.", "제2장 뭍으로", "가. 첫 절", "글."]
    assert texts[9] == "제3장 사람" and texts[-4:] == ["[그림 1] 그림 1. 화석", "", "| 데본기 |\n|---|", "표 1. 연대"]
    report = import_manuscript(store, U, tmp_path / "번호.hwpx", project_id="n")
    assert [(c[0], c[2]) for c in report.chapters] == [(1, "물고기의 결심"), (2, "뭍으로"), (3, "사람")]
    assert store.read_chapter(U, "n", 1).content.startswith("## 가. 데본기의 바다\n\n### 가-1) 세부")


def test_hwpx_import_makes_chapters_issues_refs(store: LocalStore, data_dir: Path, tmp_path: Path):
    report = import_manuscript(store, U, write(tmp_path, "원고.hwpx", hwpx()), project_id="h")
    assert [(c[0], c[2], c[3]) for c in report.chapters] == [(1, "물고기의 결심", 1), (2, "뭍으로", 1), (3, "사람", 2)]
    assert [(x.number, x.title) for x in report.parts] == [(1, "바다에서"), (2, "뭍")]
    assert report.source == "원고.hwpx (hwpx)" and len(report.discarded) == 3  # 목차 줄 셋
    project = store.get_project(U, "h")
    assert (project.title, project.subtitle, project.title_en) == ("가상의 한글 책", "부제 하나", "A Hangul Book")
    body = store.read_chapter(U, "h", 1).content
    assert body.startswith("## 1. 데본기의 바다\n\n앞 글") and "| 1990 | 5백만 | 늘어남 |" in body and "- 목록 항목" in body
    assert "본문[^1] 이어서.\n\n[^1]: Galor(2022), 13쪽." in body
    issues = store.list_issues(U, "h", None)
    assert [(i.chapter_number, i.author, i.kind, i.ref_key) for i in issues] == [
        (1, "Claude", "citation", "daeschler2006"), (2, "홍길동", "citation", "clack2012")]
    assert issues[0].by_ai and not issues[1].by_ai and issues[0].paragraph == 2
    assert {r.key for r in store.list_refs(U)} == {"daeschler2006", "clack2012"}
    assert (data_dir / "users" / U / "projects/h/original/원고.hwpx").exists()
    assert store.list_editions(U, "h")[0].file == "원고.hwpx"


def test_hwpx_new_edition_and_document_update(store: LocalStore, tmp_path: Path):
    e1 = write(tmp_path, "원고.hwpx", hwpx())
    inbox = store.root / "users" / U / "inbox"
    inbox.mkdir(parents=True)
    (inbox / "원고.hwpx").write_bytes(e1.read_bytes())
    import_manuscript(store, U, inbox / "원고.hwpx", project_id="h")
    rows = {r.key: r for r in list_documents(store, U)}
    assert rows["inbox:원고.hwpx"].source.label() == "「가상의 한글 책」 올린 문서 원본 · 처음 올린 문서 E1"
    changed = hwpx(SECTION1.replace("사람은 걸었다.", "사람은 뛰었다."))
    result = update_document(store, U, "inbox:원고.hwpx", "원고.hwpx", io.BytesIO(changed), len(changed), None,
                             max_attach=20_000_000, max_upload=50_000_000, max_user=10**9)
    assert result.revision.edition == 2 and [c.number for c in result.revision.changed] == [3]
    assert store.read_chapter(U, "h", 3).content == "사람은 뛰었다."
    assert len(store.list_issues(U, "h", None)) == 2  # 같은 메모는 다시 넣지 않는다(지문)
    third = write(tmp_path, "원고3.hwpx", hwpx(SECTION1.replace("사람은 걸었다.", "사람은 날았다.")))
    assert reupload_manuscript(store, U, third, "h").edition == 3


def test_hwpx_locked_broken_and_bomb(tmp_path: Path):
    locked = hwpx(extra={"META-INF/manifest.xml": '<odf:manifest><odf:file-entry><odf:encryption-data/></odf:file-entry></odf:manifest>'})
    with pytest.raises(ValueError, match="암호가 걸렸거나 배포용인 한글 문서"):
        read_manuscript(write(tmp_path, "암호.hwpx", locked))
    for name, data in (("깨짐.hwpx", b"PK broken"), ("구역없음.hwpx", _zip({"mimetype": "application/hwp+zip"})),
                       ("나쁜xml.hwpx", _zip({"Contents/section0.xml": "<hs:sec"}))):
        with pytest.raises(ValueError) as e:
            read_manuscript(write(tmp_path, name, data))
        assert str(e.value) == UNREADABLE and "한글(.hwpx·.hwp)" in UNREADABLE
    spaces = " " * 30_000_000  # 압축률이 큰 항목(폭탄)
    with pytest.raises(ValueError, match="열 수 없는 문서"):
        read_manuscript(write(tmp_path, "폭탄.hwpx", _zip({"Contents/section0.xml": spaces})))


# ---- hwp 5.0(CFB) ---------------------------------------------------------------------------------------------

END, FREE, FATSECT, NOSTREAM = 0xFFFFFFFE, 0xFFFFFFFF, 0xFFFFFFFD, 0xFFFFFFFF


def _cfb(streams: dict[str, bytes]) -> bytes:
    """streams: {"FileHeader": …, "BodyText/Section0": …} → CFB v3 파일. 스트림은 4,096바이트 이상(미니 스트림을 쓰지 않는다)."""
    entries: list[dict] = [{"name": "Root Entry", "type": 5, "kids": [], "data": None}]
    index = {"": 0}
    for path, data in streams.items():
        assert len(data) >= 4096, path
        parts = path.split("/")
        for i in range(len(parts)):
            key, parent = "/".join(parts[: i + 1]), "/".join(parts[:i])
            if key not in index:
                last = i == len(parts) - 1
                index[key] = len(entries)
                entries.append({"name": parts[i], "type": 2 if last else 1, "kids": [], "data": data if last else None})
                entries[index[parent]]["kids"].append(index[key])
    sectors: list[bytes] = []
    fat: list[int] = []

    def chain(data: bytes) -> int:
        start, count = len(sectors), (len(data) + 511) // 512
        for n in range(count):
            sectors.append(data[n * 512:(n + 1) * 512].ljust(512, b"\0"))
            fat.append(start + n + 1 if n < count - 1 else END)
        return start

    for e in entries:
        e["start"], e["size"] = (chain(e["data"]), len(e["data"])) if e["data"] is not None else (END if e["type"] == 5 else 0, 0)
    right = {k: e["kids"][n + 1] for e in entries for n, k in enumerate(e["kids"][:-1])}

    def entry(i: int) -> bytes:
        if i >= len(entries):
            return struct.pack("<64sHBBIII16sIQQIQ", b"", 0, 0, 0, NOSTREAM, NOSTREAM, NOSTREAM, b"", 0, 0, 0, 0, 0)
        e = entries[i]
        name = e["name"].encode("utf-16-le") + b"\0\0"
        return struct.pack("<64sHBBIII16sIQQIQ", name, len(name), e["type"], 1, NOSTREAM, right.get(i, NOSTREAM),
                           e["kids"][0] if e["kids"] else NOSTREAM, b"", 0, 0, 0, e["start"], e["size"])

    dir_count = (len(entries) * 128 + 511) // 512
    dir_start = chain(b"".join(entry(i) for i in range(dir_count * 4)))
    fat_count = 1
    while (len(sectors) + fat_count) > fat_count * 128:
        fat_count += 1
    fat_start = len(sectors)
    fat += [FATSECT] * fat_count
    fat += [FREE] * (fat_count * 128 - len(fat))
    table = struct.pack(f"<{len(fat)}I", *fat)
    sectors += [table[n * 512:(n + 1) * 512] for n in range(fat_count)]
    header = struct.pack("<8s16sHHHHH6sIIIIIIIII", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", b"", 0x3E, 3, 0xFFFE, 9, 6, b"", 0, fat_count,
                         dir_start, 0, 4096, END, 0, END, 0)
    header += struct.pack("<109I", *([fat_start + n for n in range(fat_count)] + [FREE] * (109 - fat_count)))
    return header + b"".join(sectors)


def rec(tag: int, data: bytes, level: int = 0) -> bytes:
    if len(data) >= 0xFFF:
        return struct.pack("<II", tag | level << 10 | 0xFFF << 20, len(data)) + data
    return struct.pack("<I", tag | level << 10 | len(data) << 20) + data


def ctrl_char(code: int, ctrl_id: str) -> bytes:
    """여덟 글자짜리 컨트롤: 코드 · 컨트롤 id(4바이트, 거꾸로) · 8바이트 · 코드."""
    return struct.pack("<H", code) + ctrl_id[::-1].encode("latin-1") + b"\0" * 8 + struct.pack("<H", code)


def para(text: str | bytes, *, style: int = 0, shape: int = 0, level: int = 0, ctrls: tuple[bytes, ...] = ()) -> bytes:
    """문단: PARA_HEADER(스타일 id는 10번째 바이트) + PARA_TEXT + 컨트롤 레코드들(한 단계 아래)."""
    body = (text.encode("utf-16-le") if isinstance(text, str) else text) + struct.pack("<H", 13)
    header = struct.pack("<IIHBBHHHIH", len(body) // 2, 0, shape, style, 0, 1, 0, 1, 0, 0)
    return rec(66, header, level) + rec(67, body, level + 1) + b"".join(ctrls)


def hwp_table(level: int, cells: list[tuple[int, int, str]], rows: int, cols: int, header_size: int = 8) -> bytes:
    """표 컨트롤(CTRL_HEADER 'tbl ' + TABLE + 칸마다 LIST_HEADER와 문단). header_size: 셀 주소 앞 문단 리스트 머리 길이."""
    out = rec(71, b" lbt" + b"\0" * 40, level) + rec(77, struct.pack("<IHH", 0, rows, cols) + b"\0" * 20, level + 1)
    for col, row, text in cells:
        head = (struct.pack("<HHI", 1, 0, 0) if header_size == 8 else struct.pack("<HI", 1, 0)) + struct.pack("<HHHH", col, row, 1, 1) + b"\0" * 18
        out += rec(72, head, level + 1) + para(text, level=level + 1)
    return out


def hwp_note(level: int, text: str) -> bytes:
    return rec(71, b"  nf" + b"\0" * 20, level) + rec(72, struct.pack("<HHI", 1, 0, 0) + b"\0" * 8, level + 1) + para(text, level=level + 1)


def style(name: str, eng: str, shape: int) -> bytes:
    return (struct.pack("<H", len(name)) + name.encode("utf-16-le") + struct.pack("<H", len(eng)) + eng.encode("utf-16-le")
            + struct.pack("<BBhHHH", 0, 0, 1042, shape, 0, 0))


def shape_prop(kind: int = 0, level: int = 0) -> bytes:
    return struct.pack("<I", kind << 23 | level << 25) + b"\0" * 50


HWP_STYLES = [("바탕글", "Normal", 0), ("개요 1", "Outline 1", 1), ("개요 2", "Outline 2", 2), ("사용자 제목", "", 3)]


def hwp_body(*, header_size: int = 8) -> bytes:
    tbl, gso, eq, fn = ctrl_char(11, "tbl "), ctrl_char(11, "gso "), ctrl_char(11, "eqed"), ctrl_char(17, "fn  ")
    return b"".join([
        para("가상의 한글 책"),
        para("제1부 바다에서", style=1),
        para("제1장 물고기의 결심", style=2),
        para("셋째 단계 제목", style=3, shape=3),  # 스타일 이름으로는 모르고 문단 모양이 개요 3수준
        para("탭".encode("utf-16-le") + ctrl_char(9, "\0\0\0\t") + "뒤 글(Clack, 2012).".encode("utf-16-le")),
        para("표 1. 인구".encode("utf-16-le") + tbl,
             ctrls=(hwp_table(1, [(0, 0, "연도"), (1, 0, "인구"), (0, 1, "1990"), (1, 1, "5백만")], 2, 2, header_size),)),
        para("그림 ".encode("utf-16-le") + gso + " 수식 ".encode("utf-16-le") + eq,
             ctrls=(rec(71, b" osg" + b"\0" * 20, 1), rec(71, b"deqe" + b"\0" * 20, 1))),
        para("본문".encode("utf-16-le") + fn + " 이어서.".encode("utf-16-le"), ctrls=(hwp_note(1, "Galor(2022), 13쪽."),)),
        para("목록 항목", shape=4),
        para("제2장 뭍으로", style=2),
        para("사람은 걸었다."),
        para("참고문헌"),
        para("Clack, J. A. (2012). Gaining Ground. Indiana University Press."),
        rec(93, b"\0" * 4),  # 메모 목록(가져오지 않고 수만 리포트에)
    ])


def numbering(formats: list[tuple[int, str]]) -> bytes:
    """NUMBERING 레코드: 수준마다 (번호 모양, 형식 글). 7수준을 채우고 시작 번호 1, 수준별 시작 번호 1."""
    formats = (formats + [(0, "^7")] * 7)[:7]
    levels = b"".join(struct.pack("<IhhIH", shape << 5, 0, 0, 0, len(text)) + text.encode("utf-16-le") for shape, text in formats)
    return levels + struct.pack("<H", 1) + struct.pack("<7I", *[1] * 7)


def hwp(*, compressed: bool = True, flags: int = 0, view_text: bool = False, header_size: int = 8, body: bytes | None = None,
        numbered: bool = False) -> bytes:
    header = (b"HWP Document File".ljust(32, b"\0") + bytes([0, 1, 0, 5]) + struct.pack("<I", flags | (1 if compressed else 0))).ljust(4096, b"\0")
    docinfo = b"".join(rec(42, style(n, e, s), 1) for n, e, s in HWP_STYLES)
    docinfo += rec(23, numbering([(0, "제^1장"), (8, "^2.")]), 1) if numbered else b""
    docinfo += b"".join(rec(25, shape_prop(k, lv), 1) for k, lv in [(0, 0), (1, 0), (1, 1), (1, 2), (3, 0)])
    section = hwp_body(header_size=header_size) if body is None else body

    def pack(data: bytes) -> bytes:
        if compressed:
            c = zlib.compressobj(9, zlib.DEFLATED, -15)
            data = c.compress(data) + c.flush()
        return data.ljust(4096, b"\0")

    streams = {"FileHeader": header, "DocInfo": pack(docinfo), "BodyText/Section0": pack(section)}
    if view_text:
        streams["ViewText/Section0"] = b"\0" * 4096
    return _cfb(streams)


@pytest.mark.parametrize("compressed", [True, False])
@pytest.mark.parametrize("header_size", [8, 6])
def test_hwp_blocks_headings_tables_notes(tmp_path: Path, compressed: bool, header_size: int):
    m = read_manuscript(write(tmp_path, "원고.hwp", hwp(compressed=compressed, header_size=header_size)))
    assert m.source == "hwp" and m.comments == [] and m.notes == ["hwp 메모 1개는 확인 요청으로 가져오지 않음(hwpx로 저장해 올리면 가져온다)"]
    texts = [b.text for b in m.blocks]
    heads = {b.text: b.heading_level for b in m.blocks if b.heading_level}
    assert heads == {"제1부 바다에서": 1, "제1장 물고기의 결심": 2, "셋째 단계 제목": 3, "제2장 뭍으로": 2}
    assert "탭\t뒤 글(Clack, 2012)." in texts
    at = texts.index("표 1. 인구")
    assert m.blocks[at + 1].kind == "table" and m.blocks[at + 1].text == "| 연도 | 인구 |\n|---|---|\n| 1990 | 5백만 |"
    assert "그림 [그림 1] 수식 [수식]" in texts and (m.figures, m.tables, m.equations) == (1, 1, 1)
    assert texts[texts.index("본문[^1] 이어서.") + 1] == "[^1]: Galor(2022), 13쪽."
    assert [b for b in m.blocks if b.text == "목록 항목"][0].is_list


def test_hwp_outline_numbers_become_text(store: LocalStore, tmp_path: Path):
    secd = rec(71, b"dces" + b"\0" * 14 + struct.pack("<H", 1) + b"\0" * 20, 1)  # 구역 정의: 개요 번호 id 1(18번째 바이트)
    body = b"".join([
        para(ctrl_char(2, "secd") + "가상의 한글 책".encode("utf-16-le"), ctrls=(secd,)),
        para("물고기의 결심", shape=1), para("데본기", shape=2), para("둘째 절", shape=2), para("글."),
        para("뭍으로", shape=1), para("첫 절", shape=2), para("글."), para("제3장 사람", shape=1), para("글."),
    ])
    m = read_manuscript(write(tmp_path, "번호.hwp", hwp(body=body, numbered=True)))
    assert [b.text for b in m.blocks] == ["가상의 한글 책", "제1장 물고기의 결심", "가. 데본기", "나. 둘째 절", "글.", "제2장 뭍으로",
                                          "가. 첫 절", "글.", "제3장 사람", "글."]
    report = import_manuscript(store, U, tmp_path / "번호.hwp", project_id="n")
    assert [(c[0], c[2]) for c in report.chapters] == [(1, "물고기의 결심"), (2, "뭍으로"), (3, "사람")]


def test_number_text_shapes():
    assert [hwp_reader.number_text(n, f) for n, f in [(3, "DIGIT"), (3, "CIRCLED_DIGIT"), (4, "ROMAN_CAPITAL"), (9, "ROMAN_SMALL"),
                                                      (2, "LATIN_CAPITAL"), (15, "HANGUL_SYLLABLE"), (3, "HANGUL_JAMO"),
                                                      (2, "HANGUL_PHONETIC"), (3, "IDEOGRAPH"), (5, "모름")]] == [
        "3", "③", "IV", "ix", "B", "가", "ㄷ", "이", "三", "5"]
    assert hwp_reader.with_prefix("제1장", "제 1 장 물고기") == "제 1 장 물고기" and hwp_reader.with_prefix("1.", "") == "1."
    assert hwp_reader.with_prefix("1.", "제1장 물고기") == "제1장 물고기"  # 기본 개요 번호가 손으로 적은 장 제목을 가리지 않게
    assert hwp_reader.with_prefix("1.", "서론") == "1. 서론"


def test_hwp_import_and_refs(store: LocalStore, tmp_path: Path):
    report = import_manuscript(store, U, write(tmp_path, "원고.hwp", hwp()), project_id="w")
    assert [(c[0], c[2], c[3]) for c in report.chapters] == [(1, "물고기의 결심", 1), (2, "뭍으로", 1)]
    assert "원고.hwp (hwp) · hwp 메모 1개는 확인 요청으로 가져오지 않음" in report.summary()
    assert store.get_project(U, "w").title == "원고"  # 문서 정보 제목이 없으면 파일 이름
    body = store.read_chapter(U, "w", 1).content
    assert body.startswith("## 셋째 단계 제목\n\n탭\t뒤 글(Clack, 2012).") and "| 1990 | 5백만 |" in body
    assert [r.key for r in store.list_refs(U)] == ["clack2012"]
    # 논문 전문(category_put file)으로도 읽는다
    assert "사람은 걸었다." in read_fulltext(tmp_path / "원고.hwp")


def test_hwp_locked_old_and_broken(tmp_path: Path):
    for name, data in (("암호.hwp", hwp(flags=0x02)), ("배포용.hwp", hwp(flags=0x04)), ("뷰텍스트.hwp", hwp(view_text=True))):
        with pytest.raises(ValueError) as e:
            read_manuscript(write(tmp_path, name, data))
        assert str(e.value) == hwp_reader.LOCKED
    with pytest.raises(ValueError, match="한글 97 이전 형식"):
        read_manuscript(write(tmp_path, "옛.hwp", b"HWP Document File V3.00 \x1a\x01\x02\x03\x04\x05" + b"\0" * 200))
    for name, data in (("가짜.hwp", b"not ole"), ("다른.hwp", _cfb({"FileHeader": b"x" * 4096})),
                       ("깨진압축.hwp", _raw_hwp(b"\xff" * 64))):
        with pytest.raises(ValueError) as e:
            read_manuscript(write(tmp_path, name, data))
        assert str(e.value) == UNREADABLE, name


def test_hwp_inflate_bomb_refused(tmp_path: Path):
    c = zlib.compressobj(9, zlib.DEFLATED, -15)
    bomb = c.compress(b"\0" * 30_000_000) + c.flush()  # 압축률 1,000:1 넘음
    with pytest.raises(ValueError, match="열 수 없는 문서"):
        read_manuscript(write(tmp_path, "폭탄.hwp", _raw_hwp(bomb)))


def _raw_hwp(section: bytes) -> bytes:
    """압축 표시를 한 hwp에 구역 스트림을 그대로(압축된 것으로 보고) 넣는다."""
    header = (b"HWP Document File".ljust(32, b"\0") + bytes([0, 1, 0, 5]) + struct.pack("<I", 1)).ljust(4096, b"\0")
    return _cfb({"FileHeader": header, "BodyText/Section0": section.ljust(4096, b"\0")})


# ---- 대화: book_import(hwpx), replace 없음 -------------------------------------------------------------------

async def test_chat_imports_hwpx_and_refuses_replace(settings: Settings, store: LocalStore, tmp_path: Path):
    store.put_inbox(settings.user_id, "한글 원고.hwpx", hwpx())
    async with Client(build_server(settings, store)) as client:
        tools = {x.name: x for x in (await client.list_tools()).tools}
        schema = tools["book_import"].input_schema["properties"]
        assert "replace" not in schema and "new_edition" in schema
        assert "replace" not in tools["book_import"].description and "docx·hwpx·hwp" in tools["book_import"].description
        listed = "".join(b.text for b in (await client.call_tool("files_list", {})).content)
        assert "- 한글 원고.hwpx · " in listed and "올린 문서(book_import)" in listed
        done = await client.call_tool("book_import", {"path": "한글 원고.hwpx", "project_id": "h"})
        assert not done.is_error and "장 3개" in done.content[0].text
        # 같은 project_id로 다시: 바꾸지 않고 수정본·사이트 휴지통을 안내한다. 옛 도구 목록의 replace=true도 버려진다
        for args in ({}, {"replace": True}):
            again = await client.call_tool("book_import", {"path": "한글 원고.hwpx", "project_id": "h", **args})
            said = again.content[0].text
            assert again.is_error and "new_edition=true" in said and "휴지통" in said and "replace" not in said
        assert len(store.list_editions(settings.user_id, "h")) == 1 and not (store.root / "users" / settings.user_id / "trash").exists()
        none = await client.call_tool("book_import", {"title": "", "new_edition": True})
        assert none.is_error and none.content[0].text.endswith("수정본에는 문서 파일(path)이 필요하다.")
