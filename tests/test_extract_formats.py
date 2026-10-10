"""첨부 글자 뽑기 형식 늘림(2026-10-11): hwp·hwpx·pptx·xlsx·odt·rtf·csv·html. 옛 바이너리(doc·ppt·xls)는 '글자를 뽑지 않는 형식'.

- 시험 파일은 모두 코드로 만든다(밖에서 받지 않는다). hwp는 olefile이 쓰지 못하므로 아주 작은 CFB(OLE) 작성기를 여기 둔다
  (512바이트 섹터, 미니 스트림 없이: 스트림을 모두 4,096바이트 이상으로 채운다. 압축 스트림 뒤 군더더기는 읽는 쪽이 버려야 한다).
- 암호·배포용 hwp → '읽을 수 없는 hwp'(status failed + reason). 압축 폭탄(hwp 구역·xlsx·pptx)은 failed. 30만 자 상한.
- 형식을 늘리기 전에 올라간 hwp는 warm-cache(와 extract)가 뽑는다. 대화에서 hwp 첨부를 찾고 쪽으로 읽는다."""

from __future__ import annotations

import io
import json
import re
import struct
import zipfile
import zlib
from pathlib import Path

import httpx2
import pytest
from mcp import Client
from test_web import _csrf, server_proc  # noqa: F401 - 픽스처

from magus import cli
from magus import extract as ex
from magus.config import Settings
from magus.server import build_server
from magus.store import CategoryItem, LocalStore

POST = "20261011000000000-aaaaaa"

# ---- hwp(CFB) ------------------------------------------------------------------------------------------------

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
    right = {k: e["kids"][n + 1] for e in entries for n, k in enumerate(e["kids"][:-1])}  # 형제는 오른쪽으로 잇는다

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


def _record(tag: int, data: bytes, level: int = 0) -> bytes:
    if len(data) >= 0xFFF:  # 큰 레코드: 크기 칸 0xFFF + 다음 4바이트
        return struct.pack("<II", tag | level << 10 | 0xFFF << 20, len(data)) + data
    return struct.pack("<I", tag | level << 10 | len(data) << 20) + data


def _para_text(text: str) -> bytes:
    """글자 → PARA_TEXT. '\\t'는 탭 컨트롤(8글자), '§'는 표 컨트롤(확장, 8글자), '\\n'은 줄 끝(1글자), 끝에 문단 끝(13)."""
    out = b""
    for ch in text:
        if ch == "\t":
            out += struct.pack("<8H", 9, 0, 0, 0, 0, 0, 0, 9)
        elif ch == "§":
            out += struct.pack("<H", 11) + b" lbt" + b"\0" * 8 + struct.pack("<H", 11)  # 코드 · 컨트롤 id(4바이트) · 8바이트 · 코드
        else:
            out += ch.encode("utf-16-le")
    return out + struct.pack("<H", 13)


def _hwp(sections: list[list[str]], *, compressed: bool = True, flags: int = 0, view_text: bool = False,
         raw_sections: dict[int, bytes] | None = None) -> bytes:
    header = (b"HWP Document File".ljust(32, b"\0") + bytes([0, 1, 0, 5]) + struct.pack("<I", flags | (1 if compressed else 0))).ljust(4096, b"\0")
    streams = {"FileHeader": header}
    for n, paras in enumerate(sections):
        records = b"".join(_record(66, b"\0" * 22) + _record(67, _para_text(p), 1) + _record(69, b"\0" * 36, 1) for p in paras)
        body = raw_sections[n] if raw_sections and n in raw_sections else _deflate(records) if compressed else records
        streams[f"BodyText/Section{n}"] = body.ljust(4096, b"\0")  # 뒤에 0을 채운다(압축 스트림 뒤 군더더기, 0 레코드)
    if view_text:
        streams["ViewText/Section0"] = b"\0" * 4096
    return _cfb(streams)


def _deflate(data: bytes) -> bytes:
    c = zlib.compressobj(9, zlib.DEFLATED, -15)
    return c.compress(data) + c.flush()


# ---- zip 형식 ------------------------------------------------------------------------------------------------

def _zip(files: dict[str, str | bytes]) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)
    return out.getvalue()


HP = 'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph" xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section"'


def _hwpx_section(paras: list[str]) -> str:
    body = "".join(f'<hp:p><hp:run charPrIDRef="0"><hp:t>{p.replace(chr(9), "<hp:tab/>")}</hp:t></hp:run></hp:p>' for p in paras)
    return f'<?xml version="1.0" encoding="UTF-8"?><hs:sec {HP}>{body}</hs:sec>'


def _hwpx() -> bytes:
    return _zip({"mimetype": "application/hwp+zip", "Contents/header.xml": "<x/>",
                 "Contents/section10.xml": _hwpx_section(["셋째 구역"]),  # 이름 순이면 section10이 section2보다 먼저다
                 "Contents/section0.xml": _hwpx_section(["첫 구역의 나루터", "탭\t뒤"]),
                 "Contents/section2.xml": _hwpx_section(["둘째 구역"])})


A = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'
R = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def _slide(paras: list[str]) -> str:
    body = "".join(f"<a:p>{''.join(f'<a:r><a:t>{t}</a:t></a:r>' if t != '<br>' else '<a:br/>' for t in p.split('|'))}</a:p>"
                   for p in paras)
    return f'<p:sld {A}><p:cSld><p:spTree><p:sp><p:txBody>{body}</p:txBody></p:sp></p:spTree></p:cSld></p:sld>'


def _rels(rels: dict[str, tuple[str, str]]) -> str:
    items = "".join(f'<Relationship Id="{i}" Type="{REL}/{t}" Target="{target}"/>' for i, (t, target) in rels.items())
    return f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{items}</Relationships>'


def _pptx(slides: dict[str, list[str]] | None = None) -> bytes:
    slides = slides or {"slide1.xml": ["둘째로 보일 슬라이드"], "slide2.xml": ["첫 슬라이드 제목", "장날|<br>|소금 장수"],
                        "slide3.xml": []}
    order = "".join(f'<p:sldId id="{256 + n}" r:id="rId{n}"/>' for n in (2, 1, 3))  # 차례: slide2 → slide1 → slide3(그림만)
    return _zip({"ppt/presentation.xml": f"<p:presentation {A} {R}><p:sldIdLst>{order}</p:sldIdLst></p:presentation>",
                 "ppt/_rels/presentation.xml.rels": _rels({f"rId{n}": ("slide", f"slides/slide{n}.xml") for n in (1, 2, 3)}),
                 **{f"ppt/slides/{k}": _slide(v) for k, v in slides.items()}})


S = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'


def _sheet(rows: list[str]) -> str:
    return f'<worksheet {S} {R}><sheetData>{"".join(rows)}</sheetData></worksheet>'


def _xlsx(memo_rows: int = 5) -> bytes:
    shared = (f'<sst {S}><si><t>품목</t></si><si><t>나루터 통행료</t></si>'
              '<si><r><t>굵은 </t></r><r><t>글자</t></r></si><si><t>마루</t><rPh sb="0" eb="2"><t>まる</t></rPh></si></sst>')
    sales = _sheet(['<row r="1"><c r="A1" t="s"><v>0</v></c><c r="C1"><v>1785</v></c></row>',  # B1이 비었다
                    '<row r="2"><c r="A2" t="inlineStr"><is><t>소금</t></is></c><c r="B2" t="b"><v>1</v></c><c r="C2" t="s"><v>2</v></c></row>',
                    '<row r="3"><c r="A3" t="str"><f>A1&amp;"x"</f><v>품목x</v></c><c r="B3" t="s"><v>3</v></c></row>',
                    '<row r="4"></row>'])
    memo = _sheet([f'<row r="{n}"><c r="A{n}" t="inlineStr"><is><t>메모 {n}</t></is></c></row>' for n in range(1, memo_rows + 1)])
    return _zip({"xl/workbook.xml": f'<workbook {S} {R}><sheets><sheet name="매출" sheetId="1" r:id="rId2"/>'
                                    f'<sheet name="메모" sheetId="2" r:id="rId1"/></sheets></workbook>',
                 "xl/_rels/workbook.xml.rels": _rels({"rId1": ("worksheet", "worksheets/sheet1.xml"),
                                                      "rId2": ("worksheet", "/xl/worksheets/sheet2.xml"),
                                                      "rId3": ("sharedStrings", "sharedStrings.xml")}),
                 "xl/sharedStrings.xml": shared, "xl/worksheets/sheet1.xml": memo, "xl/worksheets/sheet2.xml": sales})


T = 'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" ' \
    'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" xmlns:dc="http://purl.org/dc/elements/1.1/"'


def _odt() -> bytes:
    body = ('<text:tracked-changes><text:changed-region><text:deletion><text:p>지운 글자</text:p></text:deletion></text:changed-region>'
            '</text:tracked-changes>'
            '<text:h text:outline-level="1">나루터 이야기</text:h>'
            '<text:p>소금<text:s text:c="3"/>장수<text:tab/>탭<text:line-break/>다음 줄 <text:span>강조</text:span>'
            '<office:annotation><dc:creator>검토자</dc:creator><text:p>메모는 빼기</text:p></office:annotation> 끝</text:p>'
            '<table:table><table:table-row><table:table-cell><text:p>칸 하나</text:p></table:table-cell></table:table-row></table:table>')
    content = f'<office:document-content {T}><office:body><office:text>{body}</office:text></office:body></office:document-content>'
    return _zip({"mimetype": "application/vnd.oasis.opendocument.text", "content.xml": content})


def _rtf() -> bytes:
    hexed = "".join(f"\\'{b:02x}" for b in "나루터 통행료".encode("cp949"))
    big = "\\u" + str(ord("가") - 65536)  # 32767을 넘는 글자는 음수로 적는다
    emoji = "".join(f"\\u{u - 65536 if u > 32767 else u}?" for u in struct.unpack("<2H", "😀".encode("utf-16-le")))
    return ("{\\rtf1\\ansi\\ansicpg949\\deff0{\\fonttbl{\\f0\\fnil\\fcharset129 \\'b8\\'bc\\'c0\\'ba;}}{\\colortbl;\\red0\\green0\\blue0;}"
            "{\\*\\generator Riched20 10.0;}{\\info{\\title 숨은 제목}}\\viewkind4\\uc1\\pard\\f0\\fs20 " + hexed + "\\par\n"
            f"\\u{ord('옥')}?{big}?{emoji} Smith\\rquote s{{\\*\\shppict{{\\pict\\pngblip 89504e470d0a}}}} tea\\tab end\\par\n"
            f"{{\\header 머리말은 빼기\\par}}{{\\uc2\\u{ord('나')}\\'b3\\'aa}}\\par }}").encode("cp949")  # 날 8비트 글자도 코드 페이지로


def _html(meta: bool = True) -> bytes:
    head = '<meta charset="euc-kr">' if meta else ""
    page = (f"<html><head>{head}<title>제목줄</title><style>.x {{ color: red }}</style><script>var a = '숨김';</script></head>"
            "<body><h1>나루터</h1><p>소금&amp;장수   <b>굵게</b>\n이어짐</p><table><tr><td>칸1</td><td>칸2</td></tr></table>"
            "<pre>  들여  쓰기</pre><br>끝</body></html>")
    return page.encode("cp949")


def _varied(seed: int, count: int) -> str:
    """잘 압축되지 않는 한글 음절 count개."""
    return "".join(chr(0xAC00 + (seed * 7919 + i * 104_729) % 11_172) for i in range(count))


def _write(folder: Path, name: str, data: bytes) -> Path:
    path = folder / name
    path.write_bytes(data)
    return path


# ---- 뽑기 ----------------------------------------------------------------------------------------------------

def test_hwp_compressed_and_plain(tmp_path: Path):
    paras = [["첫 문단 나루터", "탭\t뒤 글자", "표§ 다음", "한 줄\n둘째 줄"], ["둘째 구역 소금 장수", "긴 문단 " + "물" * 3000]]
    for compressed in (True, False):
        got = ex.extract(_write(tmp_path, f"원고{compressed}.hwp", _hwp(paras, compressed=compressed)))
        assert got.status == "ok", got
        lines = got.text.split("\n")
        assert lines[:5] == ["첫 문단 나루터", "탭\t뒤 글자", "표 다음", "한 줄", "둘째 줄"]  # 컨트롤은 8글자를 건너뛴다
        assert "둘째 구역 소금 장수" in lines and "긴 문단 " + "물" * 3000 in lines  # 큰 레코드(크기 0xFFF + 4바이트)
    ordered = _hwp([["영"], ["일"], ["이"]] + [[str(n)] for n in range(3, 11)])
    assert ex.extract(_write(tmp_path, "차례.hwp", ordered)).text.split() == ["영", "일", "이", *map(str, range(3, 11))]  # Section10은 끝


def test_hwp_locked_old_and_broken(tmp_path: Path, store: LocalStore, data_dir: Path):
    for name, data in (("암호.hwp", _hwp([["비밀"]], flags=0x02)), ("배포용.hwp", _hwp([["비밀"]], flags=0x04)),
                       ("뷰텍스트.hwp", _hwp([["비밀"]], view_text=True))):
        got = ex.extract(_write(tmp_path, name, data))
        assert (got.status, got.reason, got.text) == ("failed", "hwp_locked", "")
    old = ex.extract(_write(tmp_path, "옛.hwp", b"HWP Document File V3.00 \x1a\x01\x02\x03\x04\x05" + b"\0" * 200))
    assert (old.status, old.reason) == ("failed", "hwp_old")
    for name, data in (("가짜.hwp", b"not ole"), ("다른.hwp", _cfb({"FileHeader": b"x" * 4096}))):
        got = ex.extract(_write(tmp_path, name, data))
        assert (got.status, got.reason) == ("failed", "")
    # 저장: status.json에 reason, 옛 코드가 읽어도 status만(failed) — 화면·대화에서는 '읽을 수 없는 hwp'
    att = tmp_path / "att"
    att.mkdir()
    status = ex.save(att, "암호.hwp", ex.extract(tmp_path / "암호.hwp"))
    assert json.loads((att / ".text" / "status.json").read_text(encoding="utf-8"))["reason"] == "hwp_locked"
    assert ex.read_status(att) == status and ex.unreadable_hwp(status) == "암호가 걸렸거나 배포용 문서"
    assert ex.unreadable_hwp({"status": "failed"}) is None and ex.unreadable_hwp({"status": "ok", "reason": "hwp_locked"}) is None


def test_hwp_inflate_bomb_and_zip_bombs_refused(tmp_path: Path):
    bomb = _deflate(b"\0" * 5_000_000)  # 약 5KB가 5MB로: 1MB를 넘고 압축률 100:1을 넘는다
    got = ex.extract(_write(tmp_path, "폭탄.hwp", _hwp([["앞"]], raw_sections={0: bomb})))
    assert got.status == "failed" and got.ms < 10_000
    honest = _hwp([["보통 문서 " + "가나다라" * 50] * 1000])  # 압축률이 높아도 1MB 안이면 읽는다
    assert ex.extract(_write(tmp_path, "보통.hwp", honest)).status == "ok"
    spaces = " " * 5_000_000
    for name, data in (("폭탄.xlsx", _zip({"xl/workbook.xml": "<workbook/>", "xl/worksheets/sheet1.xml": spaces})),
                       ("폭탄.pptx", _zip({"ppt/slides/slide1.xml": spaces})),
                       ("폭탄.hwpx", _zip({"Contents/section0.xml": spaces})), ("폭탄.odt", _zip({"content.xml": spaces}))):
        assert ex.extract(_write(tmp_path, name, data)).status == "failed", name
    dtd = _zip({"content.xml": '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><x>&a;</x>'})
    assert ex.extract(_write(tmp_path, "dtd.odt", dtd)).status == "failed"  # DTD가 든 XML은 받지 않는다


def test_zip_formats(tmp_path: Path):
    hwpx = ex.extract(_write(tmp_path, "a.hwpx", _hwpx()))
    assert hwpx.status == "ok" and hwpx.text == "첫 구역의 나루터\n탭\t뒤\n둘째 구역\n셋째 구역\n"
    pptx = ex.extract(_write(tmp_path, "b.pptx", _pptx()))
    assert pptx.text == "## 슬라이드 1\n첫 슬라이드 제목\n장날\n소금 장수\n\n## 슬라이드 2\n둘째로 보일 슬라이드\n"  # 글자 없는 슬라이드 3은 빈다
    xlsx = ex.extract(_write(tmp_path, "c.xlsx", _xlsx()))
    assert xlsx.text.startswith("## 매출\n품목\t\t1785\n소금\tTRUE\t굵은 글자\n품목x\t마루\n\n## 메모\n메모 1\n메모 2\n"), xlsx.text
    assert "まる" not in xlsx.text  # 읽는 법 표기(rPh)는 뺀다
    odt = ex.extract(_write(tmp_path, "d.odt", _odt()))
    assert odt.text == "나루터 이야기\n소금   장수\t탭\n다음 줄 강조 끝\n칸 하나\n", odt.text  # 지운 글자·메모는 뺀다
    for name, data in (("e.hwpx", b"PK broken"), ("f.xlsx", _zip({"xl/workbook.xml": "<workbook"}))):
        assert ex.extract(_write(tmp_path, name, data)).status in ("failed", "empty")
    assert ex.extract(_write(tmp_path, "그림만.pptx", _pptx({"slide1.xml": [], "slide2.xml": [], "slide3.xml": []}))).status == "empty"


def test_xlsx_row_cap_per_sheet(tmp_path: Path):
    got = ex.extract(_write(tmp_path, "큰.xlsx", _xlsx(memo_rows=2_500)))
    memo = got.text.split("## 메모\n")[1].splitlines()
    assert memo[0] == "메모 1" and memo[ex.SHEET_ROWS - 1] == f"메모 {ex.SHEET_ROWS}" and memo[ex.SHEET_ROWS] == "(이 시트는 2,000행까지만 뽑음)"
    assert f"메모 {ex.SHEET_ROWS + 1}" not in got.text and got.status == "ok"


def test_text_formats(tmp_path: Path):
    rtf = ex.extract(_write(tmp_path, "a.rtf", _rtf()))
    assert rtf.status == "ok" and rtf.text.startswith("나루터 통행료\n옥가😀 Smith’s tea\tend\n나\n"), repr(rtf.text)
    assert "숨은 제목" not in rtf.text and "Riched" not in rtf.text and "89504e" not in rtf.text and "머리말" not in rtf.text
    html = ex.extract(_write(tmp_path, "b.html", _html()))
    assert html.status == "ok" and "나루터" in html.text and "소금&장수 굵게 이어짐" in html.text and "칸1\t칸2" in html.text
    assert "들여  쓰기" in html.text and "숨김" not in html.text and "color" not in html.text and html.text.rstrip().endswith("끝")
    assert ex.extract(_write(tmp_path, "c.htm", _html(meta=False))).text == html.text  # 표시가 없으면 cp949로 짐작
    utf8 = ex.extract(_write(tmp_path, "d.html", "<p>유니코드 문서</p>".encode()))
    assert utf8.text == "유니코드 문서\n"
    csv = ex.extract(_write(tmp_path, "e.csv", "품목,값\n소금,3\n".encode("cp949")))
    assert csv.text == "품목,값\n소금,3\n"
    assert ex.extract(_write(tmp_path, "f.csv", bytes(range(256)) * 100)).status == "empty"  # 글자가 아닌 파일


def test_truncation_and_deadline(tmp_path: Path):
    long = _hwp([["가" * 4000] for _ in range(100)])  # 40만 자
    got = ex.extract(_write(tmp_path, "긴.hwp", long))
    assert got.status == "truncated" and len(got.text) == ex.TEXT_MAX
    page = "<html><body>" + "<p>" + "나" * 1000 + "</p>" * 1 + "".join(f"<p>{'다' * 1000}</p>" for _ in range(400)) + "</body></html>"
    html = ex.extract(_write(tmp_path, "긴.html", page.encode()))
    assert html.status == "truncated" and len(html.text) <= ex.TEXT_MAX
    for name in ("긴.hwp", "긴.html"):
        assert ex.extract(tmp_path / name, deadline=-1).status == "later"
    xlsx = ex.extract(_write(tmp_path, "넓은.xlsx", _zip({
        "xl/workbook.xml": f'<workbook {S} {R}><sheets><sheet name="s" r:id="rId1"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": _rels({"rId1": ("worksheet", "worksheets/sheet1.xml")}),
        "xl/worksheets/sheet1.xml": _sheet([f'<row r="{n}"><c t="inlineStr"><is><t>{_varied(n, 1000)}</t></is></c></row>'
                                            for n in range(1, 400)])})))  # 같은 글자만이면 압축률 100:1을 넘어 zipguard가 막는다
    assert xlsx.status == "truncated" and len(xlsx.text) == ex.TEXT_MAX


def test_old_binary_formats_not_extracted(tmp_path: Path):
    for name in ("옛 문서.doc", "발표.PPT", "표.xls"):
        assert not ex.extractable(name) and ex.no_text(name)
    assert not ex.no_text("사진.png") and not ex.no_text("a.hwp") and ex.extractable("a.HWP")
    assert ex.extract(_write(tmp_path, "옛 문서.doc", b"\xd0\xcf\x11\xe0 old word")).status == "failed"  # 읽는 함수가 없다


def test_stale_status_is_extracted_again(tmp_path: Path):
    assert ex.due(None, "a.hwp") and ex.due({"status": "failed", "version": 1}, "a.hwp")  # 형식을 뽑기 전 VERSION의 상태
    assert not ex.due({"status": "failed", "version": 1}, "a.docx") and not ex.due({"status": "ok", "version": 2}, "a.hwp")
    assert ex.due({"status": "later", "version": 2, "at": "2026-01-01T00:00:00.000Z"}, "a.hwp")


# ---- 저장소·대화·명령·웹 ----------------------------------------------------------------------------------------

def _post(store: LocalStore, user: str = "alice") -> str:
    book = store.create_category(user, "장날 메모", "blank", "#1f2f5c", (), "common").id
    store.put_category_item(user, CategoryItem(POST, book, "답사 자료", "me", title="답사"))
    return book


@pytest.mark.anyio
async def test_chat_finds_and_reads_hwp_and_labels(store: LocalStore, data_dir: Path):
    book = _post(store)
    owner = f"{book}/{POST}"
    paras = [[f"{n}번째 문단 " + "물" * 200 for n in range(40)] + ["끝에 숨은 옹기장수 이야기"]]
    ids = {}
    for name, data in (("한글 원고.hwp", _hwp(paras)), ("암호.hwp", _hwp([["비밀"]], flags=0x02)), ("옛 문서.doc", b"\xd0\xcf\x11\xe0 doc"),
                       ("표.xlsx", _xlsx())):
        att = store.put_attachment("alice", owner, name, data)
        store.attachment_text("alice", owner, att.id)
        ids[name] = att.id
    assert store.attachment_text("alice", owner, ids["옛 문서.doc"]) == (None, None)
    assert not (data_dir / "users" / "alice" / "shelf" / "categories" / book / "files" / POST / ids["옛 문서.doc"] / ".text").exists()
    settings = Settings.from_env({"USER_ID": "alice", "DATA_DIR": str(data_dir)})
    async with Client(build_server(settings, store)) as c:
        def text(r) -> str:
            return r.content[0].text

        found = text(await c.call_tool("category_search", {"query": "옹기장수"}))
        assert f"📎 첨부 「한글 원고.hwp」(첨부:{ids['한글 원고.hwp']}) 글자에서 맞음 · 쪽 " in found
        page = int(re.search(r"글자에서 맞음 · 쪽 (\d+)/", found).group(1))
        assert "한글 원고.hwp(한글 문서" in found and f"첨부:{ids['암호.hwp']}, 읽을 수 없는 hwp)" in found
        assert f"첨부:{ids['옛 문서.doc']}, 글자를 뽑지 않는 형식)" in found
        read = text(await c.call_tool("category_search", {"attachment": ids["한글 원고.hwp"], "page": page}))
        assert "옹기장수" in read and "마지막 쪽이다." in read and page > 1
        assert "0번째 문단" in text(await c.call_tool("category_search", {"attachment": ids["한글 원고.hwp"]}))
        locked = text(await c.call_tool("category_search", {"attachment": ids["암호.hwp"]}))
        assert "읽을 수 없는 hwp다(암호가 걸렸거나 배포용 문서)" in locked
        old = text(await c.call_tool("category_search", {"attachment": ids["옛 문서.doc"]}))
        assert "글자를 뽑지 않는 형식이다(doc·ppt·xls 같은 옛 형식)" in old
        sheet = text(await c.call_tool("category_search", {"query": "소금"}))
        assert f"📎 첨부 「표.xlsx」(첨부:{ids['표.xlsx']}) 글자에서 맞음" in sheet


def test_warm_cache_and_extract_pick_up_hwp_uploaded_before(data_dir: Path, monkeypatch: pytest.MonkeyPatch,
                                                           capsys: pytest.CaptureFixture[str]):
    store = LocalStore(data_dir)
    book = _post(store)
    owner = f"{book}/{POST}"
    old = store.put_attachment("alice", owner, "예전.hwp", _hwp([["형식을 늘리기 전에 올라간 한글 문서"]]))  # 그때는 뽑지 않았다(.text 없음)
    pptx = store.put_attachment("alice", owner, "발표.pptx", _pptx())
    doc = store.put_attachment("alice", owner, "옛.doc", b"\xd0\xcf\x11\xe0")
    folder = data_dir / "users" / "alice" / "shelf" / "categories" / book / "files" / POST
    # 옛 코드가 남긴 것처럼: 이 형식을 뽑기 전 VERSION의 상태(있을 수 없지만 있으면 다시 뽑는다)
    (folder / pptx.id / ".text").mkdir()
    (folder / pptx.id / ".text" / "status.json").write_text(json.dumps({"status": "failed", "chars": 0, "ms": 0, "at": "x", "version": 1}),
                                                            encoding="utf-8")
    assert not (folder / old.id / ".text").exists()
    store.close()
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("USER_ID", "alice")
    cli.main(["warm-cache", "--all-users"])
    out = capsys.readouterr().out
    assert "alice: 첨부 글자 대상 2 · 뽑음 2 · 앞부분만 0 · 글자 없음 0 · 실패 0 · 나중에 0 · 이미 0 · 형식 아님 1 · " in out
    assert "예전" not in out and "한글 문서" not in out  # 이름·글자는 보이지 않는다
    store = LocalStore(data_dir)
    status, text = store.attachment_text("alice", owner, old.id, make=False)
    assert status["status"] == "ok" and "형식을 늘리기 전에" in text
    assert store.search_fts("alice", ["attach_text"], '"한글"', 10)  # 색인도
    assert store.attachment_text("alice", owner, doc.id, make=False) == (None, None)
    store.close()
    cli.main(["extract", "--all-users"])
    assert "alice: 대상 2 · 뽑음 0 · 앞부분만 0 · 글자 없음 0 · 실패 0 · 나중에 0 · 이미 2 · 형식 아님 1" in capsys.readouterr().out


def test_web_labels_hwp_html_and_old_formats(server_proc):  # noqa: F811
    base, data_dir, log_path = server_proc({})
    store = LocalStore(data_dir)
    book = store.create_category("alice", "장날 메모", "blank", "#1f2f5c", (), "common").id
    store.close()
    with httpx2.Client(base_url=base, follow_redirects=True, timeout=120) as c:
        csrf = _csrf(c.get(f"/login?next=/shelf/write/{book}").text)
        made = c.post(f"/shelf/write/{book}", data={"csrf": csrf, "title": "답사", "content": "본문"},
                      files=[("files", ("나루 기록.hwp", _hwp([["옹기장수가 나루를 건넜다"]]), "application/octet-stream")),
                             ("files", ("암호.hwp", _hwp([["비밀"]], flags=0x04), "application/octet-stream")),
                             ("files", ("옛 표.xls", b"\xd0\xcf\x11\xe0 xls", "application/vnd.ms-excel")),
                             ("files", ("자료.html", _html(), "text/html"))])
        assert made.status_code == 200
        post = str(made.url).rsplit("/", 1)[1]
        assert "한글 문서 · " in made.text and "· 글자를 뽑지 않는 형식</small>" in made.text
        assert not re.search(r"옛 표\.xls</a> <small>[^<]*</small> <a class=\"as-text\"", made.text)  # xls에는 '글자 보기'가 없다
        links = dict(re.findall(rf'download>([^<]+)</a> <small>[^<]*</small> <a class="as-text" href="(/shelf/{book}/{post}/text/[^"]+)"',
                                made.text))
        assert set(links) == {"나루 기록.hwp", "암호.hwp", "자료.html"}
        assert "옹기장수가 나루를 건넜다" in c.get(links["나루 기록.hwp"]).text
        assert "읽을 수 없는 hwp입니다(암호가 걸렸거나 배포용 문서)." in c.get(links["암호.hwp"]).text
        assert "칸1\t칸2" in c.get(links["자료.html"]).text
        board = c.get(f"/shelf/{book}", params={"q": "옹기장수"}).text
        assert "나루 기록.hwp" in board and "<mark>옹기" in board
        html_file = re.search(rf'href="(/shelf/{book}/{post}/files/[^"]+)" download>자료.html', made.text).group(1)
        got = c.get(html_file)
        assert got.headers["content-type"] == "application/octet-stream" and got.headers["content-disposition"].startswith("attachment")
        xls_file = re.search(rf'href="(/shelf/{book}/{post}/files/([^"]+))" download>옛 표.xls', made.text)
        missing = c.get(f"/shelf/{book}/{post}/text/{xls_file.group(2)}")
        assert missing.status_code == 404 and "글자를 뽑지 않는 형식입니다(doc·ppt·xls)." in missing.text
    log = Path(log_path).read_text(encoding="utf-8")
    assert "extract failed kind=.hwp reason=hwp_locked" in log and "암호" not in log and "옹기" not in log
