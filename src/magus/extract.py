"""첨부 글자 뽑기(2026-10-09, 사용자 요청 #100-3): 게시판 글에 붙인 문서에서 글자를 뽑아 찾고 읽게 한다.

- 대상: docx·pdf(글자가 있는 것)·txt·md. 그림·스캔 PDF는 이번에 하지 않는다(글자가 안 나오면 '글자 없음'으로 적는다. OCR은 다음 결정).
  2026-10-11(형식 늘림, VERSION 2): hwp·hwpx·pptx·xlsx·odt·rtf·csv·html·htm. 옛 Office 바이너리(doc·ppt·xls)는 뽑지 않고
  '글자를 뽑지 않는 형식'으로 보인다. 암호·배포용 hwp는 failed + reason으로 적어 '읽을 수 없는 hwp'로 보인다.
  2026-10-14(공공 문서 호환성 점검, VERSION 3): reason을 암호(hwp_password)·배포용(hwp_dist)·DRM(hwp_drm)으로 가르고,
  docx에 각주·미주·머리말·꼬리말을 더하고 글상자가 두 번 나오던 것을 고쳤다(docx만 다시 뽑는다, SINCE).
- 어디에: 그 첨부 폴더 안 `.text/<파일 이름>.txt`(뽑은 글자)와 `.text/status.json`({status, chars, ms, at, version, reason?}). 원본은 읽기만.
  썸네일(.thumb/)과 같은 방식이라 옛 코드는 첨부 폴더에서 파일만 세므로 무시한다. 첨부 폴더째 움직이므로 휴지통 왕복에도 함께 간다.
  reason은 옛 코드가 모르는 키일 뿐이다(옛 코드는 status만 보고 '뽑지 못함'으로 보인다).
- 한도: 첨부 하나 30만 자(넘으면 앞부분만 두고 status=truncated). 시간 20초(넘으면 status=later, 처음 열 때 다시 뽑는다).
  시간은 쪽(PDF)·문단(docx)·덩어리(txt)·64KB(XML·hwp)마다 살펴 멈춘다(프로세스를 따로 띄우지 않는다: 서버 메모리 1GB).
  xlsx는 시트마다 2,000행(SHEET_ROWS)까지. zip 형식(hwpx·pptx·xlsx·odt)은 docx처럼 zipguard를 먼저 거친다.
  hwp는 OLE 스트림 하나 50MB(RAW_MAX)까지 읽고, 압축 풀기는 zipguard와 같은 규칙(1MB 넘으면 압축률 100:1, 파일 전체 200MB)에서 멈춘다.
- 메모리: PDF는 pymupdf로 한 쪽씩 읽는다(문서 전체를 올리지 않는다). docx는 zip 안 word/document.xml을 lxml iterparse로 글자(w:t)마다 읽고 버린다(점검 7-b).
  hwpx·pptx·xlsx·odt는 lxml target 파서에 64KB씩 흘려 넣는다(트리를 만들지 않아 문단이 아무리 커도 메모리가 늘지 않는다. DTD가 든 XML은 받지 않는다).
  hwp는 olefile로 BodyText/Section{N}을 열어 레코드를 흘려 읽고 문단 글자(HWPTAG_PARA_TEXT)만 꺼낸다(GPL 계열 pyhwp는 쓰지 않는다).
  txt·md·csv는 1MB씩 읽어 30만 자에서 멈춘다. html은 stdlib html.parser에 1MB씩. rtf는 파일을 한 번에 읽어(50MB까지) 낱말 단위로 걷는다.
  새 라이브러리는 olefile(BSD) 하나다(pymupdf·lxml은 원고 읽기에 이미 쓴다).
- 로그에는 개수·시간·상태만 남긴다(파일 이름·뽑은 글자는 남기지 않는다).
"""

from __future__ import annotations

import codecs
import json
import logging
import posixpath
import re
import time
import zipfile
import zlib
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path

from magus import zipguard
from magus.ids import utcnow
from magus.store.fileio import write_json, write_text

TEXT_DIR = ".text"
STATUS_FILE = "status.json"
TEXT_MAX = 300_000  # 첨부 하나에서 둘 글자 수
DEADLINE = 20.0  # 초. 넘으면 '나중에'
PAGE_CHARS = 3_000  # 대화에서 한 번에 읽는 쪽
EXTRACTABLE = (".docx", ".pdf", ".txt", ".md",  # VERSION 1(#100)
               ".hwp", ".hwpx", ".pptx", ".xlsx", ".odt", ".rtf", ".csv", ".html", ".htm")  # VERSION 2(2026-10-11)
# 그 형식의 뽑은 글자가 마지막으로 바뀐 VERSION. 그보다 옛 상태는 다시 뽑는다(warm-cache·extract·처음 열 때).
# 3(2026-10-14 공공 문서 점검): docx 각주·미주·머리말·꼬리말·글상자 한 번·탭 위치, hwp·hwpx·docx·pptx 다듬기(tidy: PUA 기호·빈 줄),
#   xlsx 숫자 15자리
SINCE = dict.fromkeys(EXTRACTABLE[4:], 2) | dict.fromkeys((".docx", ".hwp", ".hwpx", ".pptx", ".xlsx"), 3)
NO_TEXT_SUFFIXES = (".doc", ".ppt", ".xls")  # 옛 Office 바이너리: 이번에는 뽑지 않는다
NO_TEXT = "글자를 뽑지 않는 형식"  # 저자·Claude에게 보이는 이름
HWP_UNREADABLE = "읽을 수 없는 hwp"
FORMATS = "docx·hwp·hwpx·pdf·pptx·xlsx·odt·rtf·txt·md·csv·html"  # 글자를 뽑는 형식(안내 문장에 쓴다)
VERSION = 3
# status: ok(뽑음) · truncated(30만 자 넘어 앞부분만) · empty(글자 없음: 그림·스캔 PDF·빈 문서) · failed(읽지 못함: 깨진 파일·암호) · later(시간 넘음)
# reason(failed일 때만, 있으면): hwp_password(암호) · hwp_dist(배포용 문서) · hwp_drm(DRM·공인인증서) · hwp_old(한글 97 이전 hwp)
#   hwp_locked(암호·배포용을 가리지 못함): 2026-10-14 전에 뽑은 hwp 상태(앞의 셋을 하나로 적었다), 그리고 암호화된 hwpx
DONE = ("ok", "truncated", "empty", "failed")
READABLE = ("ok", "truncated")
SHEET_ROWS = 2_000  # xlsx 시트 하나에서 뽑는 행(빈 행은 세지 않는다)
RAW_MAX = 50_000_000  # 통째로 읽는 것(hwp의 OLE 스트림 하나, rtf 파일)의 상한
log = logging.getLogger("magus.extract")
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_WHY = {"hwp_password": "암호가 걸린 문서", "hwp_dist": "배포용 문서", "hwp_drm": "보안(DRM)이 걸린 문서", "hwp_old": "한글 97 이전 형식",
        "hwp_locked": "암호가 걸렸거나 배포용 문서"}  # 옛 hwp 상태·암호화된 hwpx


class _Late(Exception):
    pass


class _Unreadable(Exception):
    """까닭을 status.json에 남기는 '읽지 못함'(암호·배포용 hwp 등)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Extracted:
    status: str
    text: str  # READABLE일 때만 글자가 있다
    ms: int = 0
    reason: str = ""  # failed의 까닭(hwp_password·hwp_dist·hwp_drm·hwp_old). 없으면 status.json에 쓰지 않는다


def extractable(name: str) -> bool:
    return Path(name).suffix.lower() in EXTRACTABLE


def no_text(name: str) -> bool:
    """글자를 뽑지 않는 형식(doc·ppt·xls)인가. 화면·대화에 NO_TEXT로 보인다."""
    return Path(name).suffix.lower() in NO_TEXT_SUFFIXES


def unreadable_hwp(status: dict | None) -> str | None:
    """'읽을 수 없는 hwp'면 그 까닭(한 마디), 아니면 None."""
    if not status or status.get("status") != "failed":
        return None
    return _WHY.get(str(status.get("reason")))


def due(status: dict | None, name: str) -> bool:
    """지금 뽑아야 하나: 상태가 없거나, 그 형식을 뽑기 전 VERSION의 상태거나, '나중에'이고 다시 할 때가 됐으면."""
    if status is None or stale(status, name):
        return True
    return status["status"] == "later" and retry_due(status)


def stale(status: dict, name: str) -> bool:
    try:
        version = int(status.get("version") or 1)
    except (TypeError, ValueError):
        version = 1
    return version < SINCE.get(Path(name).suffix.lower(), 1)


def text_paths(att_dir: Path, name: str) -> tuple[Path, Path]:
    """(뽑은 글자 파일, 상태 파일)."""
    folder = att_dir / TEXT_DIR
    return folder / f"{name}.txt", folder / STATUS_FILE


def read_status(att_dir: Path) -> dict | None:
    path = att_dir / TEXT_DIR / STATUS_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("status") in (*DONE, "later") else None


def read_text(att_dir: Path, name: str) -> str | None:
    status = read_status(att_dir)
    if not status or status["status"] not in READABLE:
        return None
    try:
        return text_paths(att_dir, name)[0].read_text(encoding="utf-8")
    except OSError:
        return None


def extract(path: Path, deadline: float = DEADLINE) -> Extracted:
    """파일 하나 → 뽑은 글자와 상태. 예외를 밖으로 내지 않는다(깨진 파일은 failed)."""
    start = time.monotonic()

    def check() -> None:
        if time.monotonic() - start > deadline:
            raise _Late

    suffix = path.suffix.lower()
    reader = _READERS.get(suffix)
    if reader is None:
        return Extracted("failed", "", 0)
    try:
        text, cut = reader(path, check)
    except _Late:
        return Extracted("later", "", int((time.monotonic() - start) * 1000))
    except _Unreadable as e:  # 암호·배포용 hwp 등: 까닭을 남긴다
        log.info("extract failed kind=%s reason=%s", suffix, e.reason)
        return Extracted("failed", "", int((time.monotonic() - start) * 1000), e.reason)
    except Exception as e:  # 깨진 zip·암호 PDF 등. 이름·내용은 남기지 않는다
        log.info("extract failed kind=%s error=%s", suffix, type(e).__name__)
        return Extracted("failed", "", int((time.monotonic() - start) * 1000))
    if suffix in TIDY:
        text = tidy(text)
    ms = int((time.monotonic() - start) * 1000)
    if not text.strip():
        return Extracted("empty", "", ms)
    return Extracted("truncated" if cut else "ok", text, ms)


# 문서 형식의 뽑은 글자 다듬기(2026-10-14 공공 문서 점검). 글꼴이 그리는 사용자 정의 영역(PUA) 기호를 보통 글자로, 빈 줄 여럿은 하나로.
# PUA: 기호 글꼴(Wingdings) 글자는 문서에 U+F0xx로 들어 있어 뽑으면 깨진 글자다. 점검에서 본 것(·→ᄒᆞᆫ)과 Word 글머리표 기본 기호만 옮긴다.
#   U+F09E 가운뎃점(보도자료 '외화·원화') · U+F09F 글머리 점(연구보고서 표의 '• 창업지원 업종 확대', 132곳)
#   · U+F0E0 오른쪽 화살표(발표 자료 '클릭 → 추가') · U+F53A 한컴 옛한글 'ᄒᆞᆫ'(법령 서식 'ᄒᆞᆫ글 워드프로세서')
#   · U+F06C ● · U+F06E ■ · U+F075 ◆ · U+F076 ❖ · U+F0A7 ▪ · U+F0D8 ➢ · U+F0FC ✓
# PDF의 PUA(글꼴에 글자 대응표가 없는 것)는 무엇인지 알 수 없어 그대로 둔다.
SYMBOL_PUA = str.maketrans({0xF09E: "·", 0xF09F: "•", 0xF0E0: "→", 0xF53A: "ᄒᆞᆫ", 0xF06C: "●", 0xF06E: "■", 0xF075: "◆",
                            0xF076: "❖", 0xF0A7: "▪", 0xF0D8: "➢", 0xF0FC: "✓"})
TIDY = (".hwp", ".hwpx", ".docx", ".pptx")
_BLANKS = re.compile(r"\n[ \t　]*\n(?:[ \t　]*\n)+")


def tidy(text: str) -> str:
    """PUA 기호를 옮기고, 빈 줄이 둘 넘게 이어지면 한 줄로(발표 자료·보도자료의 빈 문단이 쪽을 채우지 않게)."""
    return _BLANKS.sub("\n\n", text.translate(SYMBOL_PUA))


def _limit(parts: list[str], total: int, piece: str) -> tuple[int, bool]:
    """parts에 piece를 더한다. 30만 자를 넘으면 잘라 넣고 True."""
    room = TEXT_MAX - total
    if len(piece) > room:
        parts.append(piece[:room])
        return TEXT_MAX, True
    parts.append(piece)
    return total + len(piece), False


def _pdf(path: Path, check) -> tuple[str, bool]:
    import pymupdf  # noqa: PLC0415  (원고 PDF 읽기에 이미 쓰는 라이브러리)

    parts: list[str] = []
    total = 0
    with pymupdf.open(path) as doc:
        if doc.needs_pass:
            raise PermissionError("암호 PDF")
        for i in range(doc.page_count):  # 한 쪽씩(문서 전체를 메모리에 올리지 않는다)
            check()
            page_text = doc.load_page(i).get_text("text")
            total, cut = _limit(parts, total, page_text.rstrip() + "\n\n")
            if cut:
                return "".join(parts), True
    return "".join(parts), False


_MC_FALLBACK = "{http://schemas.openxmlformats.org/markup-compatibility/2006}Fallback"
# 본문 뒤에 붙이는 docx 부분(2026-10-14 호환성 점검): 각주·미주, 그다음 머리말·꼬리말(같은 글은 한 번)
_DOCX_NOTES = ((r"word/footnotes\.xml", "각주"), (r"word/endnotes\.xml", "미주"))
_DOCX_HEADS = r"word/(header|footer)(\d{0,4})\.xml"


def _docx(path: Path, check) -> tuple[str, bool]:
    """본문(word/document.xml), 그다음 '## 각주'·'## 미주'·'## 머리말·꼬리말'(글자가 있을 때만, 2026-10-14).
    전에는 본문만 읽어 각주·머리말이 빠졌고, 글상자는 새 모양(mc:Choice)과 옛 모양(mc:Fallback)이 둘 다 들어가 두 번 나왔다."""
    sink = _Sink()
    with zipfile.ZipFile(path) as z:
        zipguard.check(z)  # 압축 폭탄은 풀기 전에 막는다(2026-10-09 점검 7-c) → 글자를 뽑지 못함(failed)
        names = z.namelist()
        _docx_xml(z, "word/document.xml", sink, check)
        for pattern, title in _DOCX_NOTES:
            for name in (n for n in names if re.fullmatch(pattern, n)):
                _docx_extra(z, [name], title, sink, check)
        heads = sorted((m.group(1) == "footer", m.group(2).zfill(4), n) for n in names if (m := re.fullmatch(_DOCX_HEADS, n)))  # 머리말 먼저
        _docx_extra(z, [n for *_, n in heads], "머리말·꼬리말", sink, check)
    return sink.result()


def _docx_extra(z: zipfile.ZipFile, names: list[str], title: str, sink: _Sink, check) -> None:
    """각주·머리말 같은 덧붙은 부분: 빈 줄을 빼고, 같은 줄은 한 번만(머리말이 쪽마다 같은 경우) 머리 '## 제목' 아래에."""
    lines: list[str] = []
    for name in names:
        if sink.cut:
            return
        part = _Sink()
        _docx_xml(z, name, part, check)
        lines += [x for x in part.result()[0].split("\n") if x.strip()]
    lines = list(dict.fromkeys(lines))
    if lines:
        sink.add(f"\n## {title}\n" + "\n".join(lines) + "\n")


def _docx_xml(z: zipfile.ZipFile, name: str, sink: _Sink, check) -> None:
    """word/*.xml 하나. 글자(w:t)·탭·줄바꿈이 끝날 때마다 모으고, 읽은 요소와 그 앞 형제를 바로 버린다(2026-10-09 점검 7-b).
    전에는 문단(w:p)이 끝나야 내보내 run 150만 개짜리 문단 하나가 통째로 트리에 올라갔다(84KB → 637MB).
    시간은 요소 1만 개마다, 30만 자는 sink가 본다. 탭·줄바꿈은 글자 묶음(w:r) 안의 것만(문단 서식의 탭 위치 w:tabs/w:tab은 글자가 아니다),
    mc:Fallback(같은 글상자·도형의 옛 모양) 안은 건너뛴다(2026-10-14)."""
    from lxml import etree  # noqa: PLC0415

    tags = {f"{_W}t": "t", f"{_W}tab": "\t", f"{_W}br": "\n", f"{_W}cr": "\n", f"{_W}r": "", f"{_W}p": "\n", _MC_FALLBACK: ""}
    fallback = 0
    with z.open(name) as f:
        for n, (event, el) in enumerate(etree.iterparse(f, events=("start", "end"), tag=tuple(tags), resolve_entities=False,
                                                        no_network=True)):
            if n % 10_000 == 0:
                check()
            if el.tag == _MC_FALLBACK:
                fallback += 1 if event == "start" else -1
            if event == "start":
                continue
            kind = tags[el.tag]
            parent = el.getparent()
            if not fallback and kind:
                if kind == "t":
                    sink.add(el.text or "")
                elif el.tag == f"{_W}p" or (parent is not None and parent.tag == f"{_W}r"):
                    sink.add(kind)
                if sink.cut:
                    return
            el.clear(keep_tail=True)
            if parent is not None:
                while el.getprevious() is not None:
                    del parent[0]


BAD_SHARE = 0.01  # 대체 문자(�)·제어 문자가 이 비율을 넘으면 그 인코딩이 아니다(점검 7-f)
LATER_RETRY = 60.0  # 초. '나중에'(시간 넘음)인 첨부를 다시 뽑기까지 기다림(점검 7-e)


def retry_due(status: dict) -> bool:
    """'나중에' 상태를 다시 뽑아도 되는가: 마지막 시도에서 LATER_RETRY초가 지났으면(시각을 못 읽으면 True)."""
    try:
        at = datetime.fromisoformat(str(status.get("at")).replace("Z", "+00:00"))
    except ValueError:
        return True
    return (datetime.now(UTC) - at).total_seconds() >= LATER_RETRY


def _bad_share(text: str) -> float:
    if not text:
        return 0.0
    bad = sum(1 for ch in text if ch == "�" or (ord(ch) < 32 and ch not in "\t\n\r\f"))
    return bad / len(text)


def _decode(path: Path, encoding: str, check) -> tuple[str, bool]:
    decoder = codecs.getincrementaldecoder(encoding)("replace")
    parts: list[str] = []
    total = 0
    with path.open("rb") as f:
        while block := f.read(1_000_000):
            check()
            total, cut = _limit(parts, total, decoder.decode(block))
            if cut:
                return "".join(parts), True
        total, cut = _limit(parts, total, decoder.decode(b"", final=True))
    return "".join(parts), cut


def _plain(path: Path, check) -> tuple[str, bool]:
    """txt·md: 1MB씩 읽어 30만 자에서 멈춘다. UTF-8(BOM 포함)로 읽되, 깨진 글자(�)·제어 문자가 1%를 넘을 때만 cp949로 읽는다.
    둘 다 넘으면 글자가 아닌 파일로 보고 비운다(empty). 전에는 UTF-8 바이트가 하나만 틀려도 파일 전체를 cp949로 읽어 통째로 깨졌고,
    무작위 바이너리도 'ok'로 색인됐다(점검 7-f)."""
    text, cut = _decode(path, "utf-8-sig", check)
    if _bad_share(text) <= BAD_SHARE:
        return text, cut
    other, other_cut = _decode(path, "cp949", check)
    if _bad_share(other) <= BAD_SHARE:
        return other, other_cut
    return "", False


# ---- 2026-10-11: 형식 늘림(hwp·hwpx·pptx·xlsx·odt·rtf·csv·html) -------------------------------------------

class _Sink:
    """흘려 읽은 글자를 30만 자까지 모은다(넘으면 cut)."""

    def __init__(self) -> None:
        self.parts: list[str] = []
        self.total = 0
        self.cut = False

    def add(self, piece: str) -> None:
        if piece and not self.cut:
            self.total, self.cut = _limit(self.parts, self.total, piece)

    def result(self) -> tuple[str, bool]:
        return "".join(self.parts), self.cut


def _local(tag: str) -> str:
    return tag.rpartition("}")[2]


class _Target:
    """lxml target 파서의 받는 쪽(트리를 만들지 않는다). DTD가 든 XML은 받지 않는다(OOXML·ODF·OWPML은 DTD를 쓰지 않는다)."""

    stop = False  # 참이면 그 XML을 더 읽지 않는다(행 상한 등)

    def doctype(self, *_: object) -> None:
        raise ValueError("DTD가 든 XML")

    def start(self, tag: str, attrib: dict) -> None:
        pass

    def end(self, tag: str) -> None:
        pass

    def data(self, data: str) -> None:
        pass

    def close(self) -> None:
        pass


def _feed(z: zipfile.ZipFile, name: str, target: _Target, sink: _Sink, check: Callable[[], None]) -> None:
    """zip 안 XML 하나를 64KB씩 흘려 읽는다. 30만 자를 채웠거나 target.stop이면 그 자리에서 그만."""
    from lxml import etree  # noqa: PLC0415

    parser = etree.XMLParser(target=target, resolve_entities=False, no_network=True)
    with z.open(name) as f:
        while block := f.read(65_536):
            check()
            parser.feed(block)
            if sink.cut or target.stop:
                return
    parser.close()


def _small_xml(z: zipfile.ZipFile, name: str):  # noqa: ANN202 - lxml 요소 또는 None
    """목록용 작은 XML(관계·workbook·presentation)을 통째로 읽는다. 없거나 크거나 깨졌으면 None(차례는 이름 순으로 대신한다)."""
    from lxml import etree  # noqa: PLC0415

    try:
        if z.getinfo(name).file_size > 5_000_000:
            return None
        data = z.read(name)
        if b"<!DOCTYPE" in data:
            return None
        return etree.fromstring(data, etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False))
    except (KeyError, etree.XMLSyntaxError):
        return None


def _rels(z: zipfile.ZipFile, part: str) -> dict[str, str]:
    """part(예: xl/workbook.xml)의 관계 → {Id: zip 안 경로}. 바깥 링크는 뺀다."""
    folder, _, base = part.rpartition("/")
    root = _small_xml(z, f"{folder}/_rels/{base}.rels")
    out: dict[str, str] = {}
    for rel in root if root is not None else ():
        target = str(rel.get("Target") or "")
        if rel.get("TargetMode") == "External" or not target:
            continue
        out[str(rel.get("Id"))] = target.lstrip("/") if target.startswith("/") else posixpath.normpath(f"{folder}/{target}")
    return out


def _rel_id(el) -> str | None:  # noqa: ANN001
    """r:id 속성(관계 이름공간은 Transitional·Strict 둘 다)."""
    return next((v for k, v in el.attrib.items() if k.endswith("}id") and "relationships" in k), None)


def _numbered(z: zipfile.ZipFile, pattern: str) -> list[str]:
    """이름의 번호 순(section0, section1 … / slide1, slide2 …)."""
    found = [(int(m.group(1)), n) for n in z.namelist() if (m := re.fullmatch(pattern, n))]
    return [n for _, n in sorted(found)]


def _zip_open(path: Path) -> zipfile.ZipFile:
    z = zipfile.ZipFile(path)
    try:
        zipguard.check(z)  # 압축 폭탄은 풀기 전에 막는다(docx와 같다) → failed
    except Exception:
        z.close()
        raise
    return z


class _Hwpx(_Target):
    """hwpx(OWPML) 구역: 문단(hp:p)마다 한 줄, 글자는 hp:t 안의 것만.
    문단 안에 든 것(각주·미주·머리말·꼬리말·표·글상자의 문단)은 그 문단이 끝난 뒤에 잇는다(2026-10-14, hwp와 같은 차례).
    전에는 각주가 문장 한가운데 끼어 '…단위이다(통계청, 2015)' + 각주 + 줄바꿈 + '. 개념의…'처럼 본문 문장이 끊겼다.
    붙잡아 둔 글자가 30만 자를 넘으면 그때까지의 것을 내보내고 그만 읽는다(메모리)."""

    INSIDE = {"tab": "\t", "lineBreak": "\n", "nbSpace": " ", "fwSpace": " ", "hyphen": "-"}

    def __init__(self, sink: _Sink) -> None:
        self.sink, self.in_t = sink, 0
        self.open: list[tuple[list[str], list[str]]] = []  # 열린 문단마다 (그 문단의 글자, 안에 든 문단들의 글자)
        self.held = 0

    def _put(self, piece: str) -> None:
        if not self.open:
            self.sink.add(piece)
            return
        self.open[-1][0].append(piece)
        self.held += len(piece)
        if self.held > TEXT_MAX:
            self._spill()
            self.stop = True

    def _spill(self) -> None:
        for own, inner in self.open:
            self.sink.add("".join(own) + "".join(inner))
        self.open.clear()
        self.held = 0

    def start(self, tag: str, attrib: dict) -> None:
        name = _local(tag)
        if name == "t":
            self.in_t += 1
        elif name == "p":
            self.open.append(([], []))
        elif self.in_t and name in self.INSIDE:
            self._put(self.INSIDE[name])

    def end(self, tag: str) -> None:
        name = _local(tag)
        if name == "t":
            self.in_t -= 1
        elif name == "p" and self.open:
            own, inner = self.open.pop()
            text = "".join(own) + "\n" + "".join(inner)
            if self.open:
                self.open[-1][1].append(text)
                self.held += 1
            else:
                self.sink.add(text)
                self.held = 0

    def data(self, data: str) -> None:
        if self.in_t:
            self._put(data)

    def close(self) -> None:
        self._spill()  # 닫히지 않은 문단(깨진 XML 끝)


def _hwpx_locked(z: zipfile.ZipFile, name: str) -> bool:
    """암호·배포용 hwpx(2026-10-14): 목록(META-INF/manifest.xml)에 암호화 정보가 있고 구역이 XML이 아니면(암호화된 바이트).
    전에는 XML 오류로 까닭 없는 '뽑지 못함'이 되었다."""
    try:
        manifest = z.read("META-INF/manifest.xml") if z.getinfo("META-INF/manifest.xml").file_size < 5_000_000 else b""
        with z.open(name) as f:
            head = f.read(64).lstrip(b"\xef\xbb\xbf \t\r\n")
    except KeyError:
        return False
    return b"encryption-data" in manifest and not head.startswith(b"<")


def _hwpx(path: Path, check) -> tuple[str, bool]:
    sink = _Sink()
    with _zip_open(path) as z:
        for name in _numbered(z, r"Contents/section(\d{1,6})\.xml"):
            if _hwpx_locked(z, name):
                raise _Unreadable("hwp_locked")  # 암호인지 배포용인지는 목록만으로 가리지 못한다
            _feed(z, name, _Hwpx(sink), sink, check)
            if sink.cut:
                break
    return sink.result()


class _Slide(_Target):
    """pptx 슬라이드: a:p마다 한 줄, 글자는 a:t. 머리 '## 슬라이드 N'은 첫 글자가 나올 때 붙인다(글자 없는 슬라이드는 빈다)."""

    def __init__(self, sink: _Sink, head: str) -> None:
        self.sink, self.head, self.in_t, self.said = sink, head, 0, False

    def _say(self, piece: str) -> None:
        if not self.said:
            self.sink.add(self.head)
            self.said = True
        self.sink.add(piece)

    def start(self, tag: str, attrib: dict) -> None:
        name = _local(tag)
        if name == "t":
            self.in_t += 1
        elif name == "br" and self.said:
            self.sink.add("\n")

    def end(self, tag: str) -> None:
        name = _local(tag)
        if name == "t":
            self.in_t -= 1
        elif name == "p" and self.said:
            self.sink.add("\n")

    def data(self, data: str) -> None:
        if self.in_t and data:
            self._say(data)


def _pptx(path: Path, check) -> tuple[str, bool]:
    sink = _Sink()
    with _zip_open(path) as z:
        # 슬라이드 차례는 presentation.xml의 목록(sldIdLst)을 따른다. 읽지 못하면 파일 이름의 번호 순
        rels = _rels(z, "ppt/presentation.xml")
        root = _small_xml(z, "ppt/presentation.xml")
        slides = [rels[r] for el in (root.iter("{*}sldId") if root is not None else ()) if (r := _rel_id(el)) in rels]
        names = set(z.namelist())
        slides = [s for s in slides if s in names] or _numbered(z, r"ppt/slides/slide(\d{1,6})\.xml")
        for n, name in enumerate(slides, 1):
            _feed(z, name, _Slide(sink, ("\n" if sink.total else "") + f"## 슬라이드 {n}\n"), sink, check)
            if sink.cut:
                break
    return sink.result()


class _Shared(_Target):
    """xlsx 공유 문자열(si마다 하나, 읽는 법 표기 rPh는 뺀다). 모두 합쳐 300만 자·100만 개까지만 둔다(넘는 칸은 빈칸)."""

    CHARS, COUNT = 10 * TEXT_MAX, 1_000_000

    def __init__(self) -> None:
        self.items: list[str] = []
        self.buf: list[str] | None = None
        self.in_t = self.rph = self.total = 0

    def start(self, tag: str, attrib: dict) -> None:
        name = _local(tag)
        if name == "si":
            self.buf = []
        elif name == "t":
            self.in_t += 1
        elif name == "rPh":
            self.rph += 1

    def end(self, tag: str) -> None:
        name = _local(tag)
        if name == "t":
            self.in_t -= 1
        elif name == "rPh":
            self.rph -= 1
        elif name == "si" and self.buf is not None:
            text = "".join(self.buf)
            self.buf = None
            if len(self.items) >= self.COUNT:
                self.stop = True
                return
            text = text if self.total + len(text) <= self.CHARS else ""
            self.total += len(text)
            self.items.append(text)

    def data(self, data: str) -> None:
        if self.buf is not None and self.in_t and not self.rph and self.total < self.CHARS:
            self.buf.append(data)


def _column(ref: str) -> int | None:
    """칸 주소(C5) → 0부터 센 열 번호."""
    letters = re.match(r"[A-Z]{1,3}", ref or "")
    if not letters:
        return None
    n = 0
    for ch in letters.group(0):
        n = n * 26 + ord(ch) - 64
    return n - 1


# xlsx 날짜(2026-10-11): 날짜 서식 칸의 일련번호를 YYYY-MM-DD(시각이 있으면 HH:MM까지)로. 기본 서식 번호 중 날짜·시각
_DATE_IDS = {14, 15, 16, 17, 22, 27, 28, 29, 30, 31, 34, 35, 36, 50, 51, 52, 53, 54, 57, 58}  # 날짜(22·27~31·50~58은 날짜+시각 또는 동아시아 날짜)
_TIME_IDS = {18, 19, 20, 21, 32, 33, 45, 46, 47, 55, 56}  # 시각만
_FMT_LITERAL = re.compile(r'"[^"]*"|\\.|\[(?!h|m|s)[^\]]*\]', re.I)  # 따옴표 글자·\글자·[색·조건](경과 시간 [h]는 남긴다)


def date_kind(fmt_id: int, code: str | None) -> str | None:
    """서식 → 'date'(날짜, 시각이 있으면 함께) · 'time'(시각만) · None(날짜 아님)."""
    if code is None:
        return "date" if fmt_id in _DATE_IDS else "time" if fmt_id in _TIME_IDS else None
    bare = _FMT_LITERAL.sub("", code).lower()
    if re.search(r"[yd]", bare):  # 연·일(지수 표기 0.00E+00·General은 날짜가 아니다)
        return "date"
    if re.search(r"[hs]", bare):
        return "time"
    return None


def date_text(raw: str, kind: str, date1904: bool) -> str:
    """일련번호(1900 또는 1904 기준) → YYYY-MM-DD[ HH:MM] 또는 HH:MM. 숫자가 아니거나 범위 밖이면 그대로."""
    from datetime import datetime, timedelta  # noqa: PLC0415

    try:
        serial = float(raw)
    except ValueError:
        return raw
    if not 0 <= serial < 2_958_466:  # 9999-12-31까지
        return raw
    minutes = round((serial - int(serial)) * 1440)
    if kind == "time":
        return f"{minutes // 60 % 24:02d}:{minutes % 60:02d}"
    base = datetime(1904, 1, 1) if date1904 else datetime(1899, 12, 30)  # 1900 기준은 엑셀의 1900-02-29 오류를 따라 30일
    when = base + timedelta(days=int(serial), minutes=minutes)
    return when.strftime("%Y-%m-%d %H:%M") if minutes % 1440 else when.strftime("%Y-%m-%d")


_NUMBER = re.compile(r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")


def _number_text(raw: str) -> str:
    """xlsx 숫자 칸의 저장 값 → 유효 숫자가 15자리를 넘을 때만 15자리로(엑셀이 보이는 정밀도. 부동소수 꼬리 0.94460617502999999 → 0.94460617503).
    그 밖(정수·짧은 소수·숫자가 아닌 것)은 적힌 그대로."""
    text = raw.strip()
    if not _NUMBER.fullmatch(text) or len(text.split("e")[0].split("E")[0].replace("-", "").replace(".", "").lstrip("0")) <= 15:
        return raw
    return f"{float(text):.15g}"


def _xlsx_dates(z: zipfile.ZipFile, rels: dict[str, str]) -> dict[int, str]:
    """styles.xml의 칸 서식 번호(cellXfs 순서) → 'date'·'time'. 날짜 서식이 아닌 것은 넣지 않는다."""
    name = next((t for t in rels.values() if t.endswith("styles.xml")), "xl/styles.xml")
    root = _small_xml(z, name)
    if root is None:
        return {}
    codes = {}
    for el in root.iter("{*}numFmt"):
        try:
            codes[int(el.get("numFmtId") or -1)] = str(el.get("formatCode") or "")
        except ValueError:
            continue
    out: dict[int, str] = {}
    xfs = next(root.iter("{*}cellXfs"), None)
    for n, xf in enumerate(xfs if xfs is not None else ()):
        try:
            fmt_id = int(xf.get("numFmtId") or 0)
        except ValueError:
            continue
        if kind := date_kind(fmt_id, codes.get(fmt_id)):
            out[n] = kind
    return out


class _Sheet(_Target):
    """xlsx 시트: 행마다 한 줄, 칸은 탭으로(빈칸은 열 자리에 맞춰 채우되 한 번에 50칸까지). 숫자는 저장된 값 그대로,
    날짜 서식 칸은 YYYY-MM-DD(시각이 있으면 HH:MM까지, 2026-10-11)."""

    def __init__(self, sink: _Sink, shared: list[str], head: str, dates: dict[int, str] | None = None, date1904: bool = False) -> None:
        self.sink, self.shared, self.head = sink, shared, head
        self.dates, self.date1904, self.style = dates or {}, date1904, -1
        self.rows = self.in_v = self.in_t = self.rph = self.width = 0
        self.cells: list[str] | None = None
        self.cell: list[str] | None = None
        self.kind, self.ref = "n", ""

    def start(self, tag: str, attrib: dict) -> None:
        name = _local(tag)
        if name == "row":
            self.cells, self.width = [], 0
        elif name == "c" and self.cells is not None:
            self.cell, self.kind, self.ref = [], str(attrib.get("t") or "n"), str(attrib.get("r") or "")
            style = str(attrib.get("s") or "")
            self.style = int(style) if style.isdigit() and len(style) < 7 else -1
        elif name == "v":
            self.in_v += 1
        elif name == "t":
            self.in_t += 1
        elif name == "rPh":
            self.rph += 1

    def end(self, tag: str) -> None:
        if self.stop:  # 행 상한 뒤(같은 64KB 안에 남은 행)는 버린다
            return
        name = _local(tag)
        if name == "v":
            self.in_v -= 1
        elif name == "t":
            self.in_t -= 1
        elif name == "rPh":
            self.rph -= 1
        elif name == "c" and self.cell is not None and self.cells is not None:
            raw = "".join(self.cell)
            self.cell = None
            if self.kind == "s":
                index = raw.strip()
                value = self.shared[int(index)] if index.isdigit() and len(index) < 10 and int(index) < len(self.shared) else ""
            elif self.kind == "b":
                value = {"1": "TRUE", "0": "FALSE"}.get(raw.strip(), raw)
            elif self.kind == "n" and self.style in self.dates:  # 날짜 서식 칸: 일련번호 → YYYY-MM-DD[ HH:MM]
                value = date_text(raw.strip(), self.dates[self.style], self.date1904)
            elif self.kind == "d":  # ISO 8601로 적힌 날짜(드묾): 2026-10-11T09:30:00 → 2026-10-11 09:30
                stamp = raw.strip().replace("T", " ")
                value = stamp[:10] if stamp[11:16] in ("", "00:00") else stamp[:16]
            elif self.kind == "n":  # 숫자: 엑셀처럼 유효 숫자 15자리까지(39.509900352700001 → 39.5099003527, 2026-10-14)
                value = _number_text(raw)
            else:  # str·inlineStr·e: 적힌 그대로
                value = raw
            col = _column(self.ref)
            if col is not None and col > len(self.cells):
                self.cells += [""] * min(col - len(self.cells), 50)
            self.cells.append(" ".join(value.split()))
            self.width += len(self.cells[-1]) + 1
        elif name == "row" and self.cells is not None:
            line = "\t".join(self.cells).rstrip("\t")
            self.cells = None
            if not line.strip():
                return
            if self.rows == 0:
                self.sink.add(self.head)
            self.sink.add(line + "\n")
            self.rows += 1
            if self.rows >= SHEET_ROWS:
                self.sink.add(f"(이 시트는 {SHEET_ROWS:,}행까지만 뽑음)\n")
                self.stop = True

    def data(self, data: str) -> None:
        if self.cell is None or self.width > TEXT_MAX:  # 한 행이 30만 자를 넘으면 그 뒤 칸은 버린다
            return
        if (self.kind == "inlineStr" and self.in_t and not self.rph) or (self.kind != "inlineStr" and self.in_v):
            self.cell.append(data)
            self.width += len(data)


def _xlsx(path: Path, check) -> tuple[str, bool]:
    sink = _Sink()
    with _zip_open(path) as z:
        rels = _rels(z, "xl/workbook.xml")
        names = set(z.namelist())
        shared_name = next((t for t in rels.values() if t.endswith("sharedStrings.xml")), "xl/sharedStrings.xml")
        shared = _Shared()
        if shared_name in names:
            _feed(z, shared_name, shared, _Sink(), check)
        root = _small_xml(z, "xl/workbook.xml")
        dates = _xlsx_dates(z, rels)
        pr = next(root.iter("{*}workbookPr"), None) if root is not None else None
        date1904 = pr is not None and str(pr.get("date1904") or "").lower() in ("1", "true")
        sheets = [(str(el.get("name") or ""), rels[r]) for el in (root.iter("{*}sheet") if root is not None else ())
                  if (r := _rel_id(el)) in rels and rels[r] in names]
        if not sheets:  # 목록을 읽지 못하면 파일 이름의 번호 순, 시트 이름은 번호
            sheets = [(f"시트 {n}", s) for n, s in enumerate(_numbered(z, r"xl/worksheets/sheet(\d{1,6})\.xml"), 1)]
        for title, name in sheets:
            if "/worksheets/" not in name:  # 차트 시트 등
                continue
            _feed(z, name, _Sheet(sink, shared.items, ("\n" if sink.total else "") + f"## {title}\n", dates, date1904), sink, check)
            if sink.cut:
                break
    return sink.result()


_ODT = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"
_ODT_SKIP = {f"{_ODT}tracked-changes", "{urn:oasis:names:tc:opendocument:xmlns:office:1.0}annotation"}  # 지운 글자(변경 추적)·메모


class _Odt(_Target):
    """odt content.xml: text:p·text:h마다 한 줄. text:s(빈칸 c개)·text:tab·text:line-break. 각주는 그 자리에 이어진다."""

    def __init__(self, sink: _Sink) -> None:
        self.sink, self.depth, self.skip = sink, 0, 0

    def start(self, tag: str, attrib: dict) -> None:
        if tag in _ODT_SKIP:
            self.skip += 1
        elif self.skip:
            return
        elif tag in (f"{_ODT}p", f"{_ODT}h"):
            self.depth += 1
        elif self.depth and tag == f"{_ODT}s":
            try:
                count = int(attrib.get(f"{_ODT}c") or 1)
            except ValueError:
                count = 1
            self.sink.add(" " * max(1, min(count, 100)))
        elif self.depth and tag == f"{_ODT}tab":
            self.sink.add("\t")
        elif self.depth and tag == f"{_ODT}line-break":
            self.sink.add("\n")

    def end(self, tag: str) -> None:
        if tag in _ODT_SKIP:
            self.skip -= 1
        elif not self.skip and tag in (f"{_ODT}p", f"{_ODT}h"):
            self.depth -= 1
            self.sink.add("\n")

    def data(self, data: str) -> None:
        if self.depth and not self.skip:
            self.sink.add(re.sub(r"[\r\n\t]", " ", data))  # ODF의 글자 속 줄바꿈·탭은 빈칸(줄바꿈은 text:line-break)


def _odt(path: Path, check) -> tuple[str, bool]:
    sink = _Sink()
    with _zip_open(path) as z:
        _feed(z, "content.xml", _Odt(sink), sink, check)
    return sink.result()


# hwp 5.0(OLE 복합 파일). 한글 문서 파일 형식 5.0 공개 문서를 따른다
_HWP_SIGNATURE = b"HWP Document File"
_HWP_PARA_TEXT = 0x10 + 51  # HWPTAG_BEGIN + 51 = 67
_HWP_PASSWORD, _HWP_DIST, _HWP_DRM = 0x02, 0x04, 0x10 | 0x100 | 0x400  # FileHeader 속성: 암호 · 배포용 · DRM·공인인증서 암호화·공인인증서 DRM
_HWP_CHAR = {10: "\n", 24: "-", 30: " ", 31: " "}  # 한 글자짜리 제어 문자(0·13·25~29는 버린다)
_HWP_ONE = frozenset({0, 10, 13, *range(24, 32)})  # 그 밖(1~9·11·12·14~23)은 여덟 글자(16바이트)짜리 컨트롤
_HWP_CTRL = re.compile(rb"[\x00-\x1f]\x00")
_PARA_MAX = 2 * TEXT_MAX + 16  # 문단 하나에서 읽는 바이트(넘는 것은 30만 자 밖이다)


def _hwp(path: Path, check) -> tuple[str, bool]:
    import olefile  # noqa: PLC0415

    with path.open("rb") as f:
        if f.read(len(_HWP_SIGNATURE)) == _HWP_SIGNATURE:  # 한글 97 이전(HWP 3.x)은 OLE 파일이 아니다
            raise _Unreadable("hwp_old")
    if not olefile.isOleFile(str(path)):
        raise ValueError("hwp가 아님")
    sink = _Sink()
    budget = [zipguard.MAX_UNZIPPED]  # 파일 하나에서 풀 수 있는 합(구역들이 나눠 쓴다)
    with olefile.OleFileIO(str(path)) as ole:
        header = ole.openstream("FileHeader").read(256) if ole.exists("FileHeader") else b""
        if not header.startswith(_HWP_SIGNATURE) or len(header) < 40:
            raise ValueError("hwp가 아님")
        flags = int.from_bytes(header[36:40], "little")
        # 까닭을 가른다(2026-10-14): 배포용 문서는 암호를 모르는 저자도 받는 흔한 문서라(공문·보도자료) '암호'와 다르게 알린다.
        # 배포용은 본문이 ViewText에 암호화되어 있다(BodyText는 비었거나 없다)
        if flags & _HWP_PASSWORD:
            raise _Unreadable("hwp_password")
        if flags & _HWP_DIST or ole.exists("ViewText"):
            raise _Unreadable("hwp_dist")
        if flags & _HWP_DRM:
            raise _Unreadable("hwp_drm")
        sections = sorted((int(m.group(1)), e) for e in ole.listdir()
                          if len(e) == 2 and e[0] == "BodyText" and (m := re.fullmatch(r"Section(\d{1,6})", e[1])))
        for _, entry in sections:
            size = ole.get_size(entry)
            if size > RAW_MAX:
                raise zipguard.UnsafeDocument(f"{zipguard.REFUSED} 파일이 너무 큽니다.")
            stream = ole.openstream(entry)  # olefile은 스트림 하나를 메모리에 올린다(위에서 크기를 막았다)
            blocks = _inflate(stream, size, budget, check) if flags & 0x01 else _blocks(stream, check)
            for data in _hwp_records(blocks):
                sink.add(_para_text(data) + "\n")
                if sink.cut:
                    return sink.result()
    return sink.result()


def _blocks(stream, check) -> Iterator[bytes]:  # noqa: ANN001
    while block := stream.read(65_536):
        check()
        yield block


def _inflate(stream, size: int, budget: list[int], check) -> Iterator[bytes]:  # noqa: ANN001
    """압축된 구역(raw deflate)을 1MB씩 푼다. zipguard와 같은 규칙: 1MB를 넘으면 압축률 100:1, 파일 전체 200MB에서 멈춘다(폭탄)."""
    d = zlib.decompressobj(-15)
    limit = max(zipguard.RATIO_FROM, zipguard.MAX_RATIO * size)
    made = 0
    while not d.eof:
        check()
        raw = d.unconsumed_tail or stream.read(65_536)
        out = d.decompress(raw, 1_000_000) if raw else d.flush()
        made += len(out)
        budget[0] -= len(out)
        if made > limit or budget[0] < 0:
            raise zipguard.UnsafeDocument(f"{zipguard.REFUSED} 압축을 풀면 너무 큽니다.")
        if out:
            yield out
        if not raw:  # 스트림이 끝났다(뒤에 붙은 것은 버린다)
            break


def _hwp_records(blocks: Iterator[bytes]) -> Iterator[bytes]:
    """레코드를 흘려 읽고 문단 글자(PARA_TEXT)의 내용만 내보낸다. 머리 32비트: 태그 0~9, 수준 10~19, 크기 20~31(0xFFF면 다음 4바이트)."""
    buf = bytearray()
    skip = 0  # 다음 블록에서 건너뛸 바이트(앞 레코드의 나머지)
    for block in blocks:
        if skip:
            dropped = min(skip, len(block))
            block, skip = block[dropped:], skip - dropped
        buf += block
        pos = 0
        while len(buf) - pos >= 4:
            head = int.from_bytes(buf[pos:pos + 4], "little")
            tag, size, start = head & 0x3FF, head >> 20, pos + 4
            if size == 0xFFF:
                if len(buf) - pos < 8:
                    break
                size, start = int.from_bytes(buf[pos + 4:pos + 8], "little"), pos + 8
            have = len(buf) - start
            if tag == _HWP_PARA_TEXT:
                keep = min(size, _PARA_MAX)
                if have < keep:
                    break  # 내용이 다 오기를 기다린다
                yield bytes(buf[start:start + keep])
            if have >= size:
                pos = start + size
            else:
                skip, pos = size - have, len(buf)
                break
        del buf[:pos]


def _para_text(data: bytes) -> str:
    """PARA_TEXT(UTF-16LE) → 글자. 제어 문자: 한 글자짜리(0·10·13·24~31)는 2바이트, 나머지 컨트롤은 16바이트를 건너뛴다(탭(9)은 탭)."""
    out: list[str] = []
    pos, end = 0, len(data) & ~1
    while pos < end:
        m = _HWP_CTRL.search(data, pos, end)
        while m is not None and m.start() % 2:  # 홀수 자리는 앞 글자의 뒤 바이트다
            m = _HWP_CTRL.search(data, m.start() + 1, end)
        if m is None:
            out.append(data[pos:end].decode("utf-16-le", "replace"))
            break
        out.append(data[pos:m.start()].decode("utf-16-le", "replace"))
        code = data[m.start()]
        if code in _HWP_ONE:
            out.append(_HWP_CHAR.get(code, ""))
            pos = m.start() + 2
        else:
            out.append("\t" if code == 9 else "")
            pos = m.start() + 16
    return "".join(out)


# rtf: 낱말(\word N)·16진(\'hh)·기호(\x)·괄호·글자
_RTF_TOKEN = re.compile(rb"\\([a-zA-Z]{1,32})(-?\d{1,10})? ?|\\'([0-9a-fA-F]{2})|\\(.)|([{}])|[\r\n]+|([^\\{}\r\n]+)", re.S)
_RTF_SKIP = frozenset({  # 글자가 아닌 묶음(목적지)
    b"fonttbl", b"colortbl", b"stylesheet", b"info", b"pict", b"object", b"themedata", b"colorschememapping", b"latentstyles",
    b"datastore", b"listtable", b"listoverridetable", b"rsidtbl", b"generator", b"xmlnstbl", b"fldinst", b"filetbl", b"revtbl",
    b"nonshppict", b"header", b"headerl", b"headerr", b"headerf", b"footer", b"footerl", b"footerr", b"footerf"})
_RTF_TEXT = {b"par": "\n", b"line": "\n", b"sect": "\n", b"page": "\n", b"row": "\n", b"cell": "\t", b"tab": "\t",
             b"emdash": "—", b"endash": "–", b"lquote": "‘", b"rquote": "’", b"ldblquote": "“", b"rdblquote": "”", b"bullet": "•",
             b"emspace": " ", b"enspace": " ", b"qmspace": " "}


def _rtf(path: Path, check) -> tuple[str, bool]:
    """\\ansicpgN(949면 cp949)으로 \\'hh 바이트를 읽고, \\uN은 유니코드(뒤의 대체 글자 \\ucN개는 버린다). {\\*\\…}와 표·그림·정보 묶음은 건너뛴다."""
    with path.open("rb") as f:
        raw = f.read(RAW_MAX)
    sink = _Sink()
    codec = "cp1252"
    pending = bytearray()  # 코드 페이지로 읽을 바이트(두 바이트 글자가 \'hh 둘로 나뉘어 온다)
    stack: list[tuple[bool, int]] = []
    skip, uc, ignore, fresh = False, 1, 0, False

    def flush() -> None:
        if pending:
            sink.add(pending.decode(codec, "replace"))
            pending.clear()

    pos, n = 0, 0
    while pos < len(raw) and not sink.cut:
        m = _RTF_TOKEN.match(raw, pos)
        if m is None:  # 끝에 홀로 남은 '\'
            pos += 1
            continue
        pos = m.end()
        n += 1
        if n % 10_000 == 0:
            check()
        word, num, hexa, sym, brace, text = m.groups()
        first, fresh = fresh, False
        if brace == b"{":
            flush()
            stack.append((skip, uc))
            fresh = True
        elif brace == b"}":
            flush()
            skip, uc = stack.pop() if stack else (False, 1)
            ignore = 0
        elif word is not None and word == b"bin":  # 날 바이트 N개(그림 등)는 건너뛴다
            pos += max(0, int(num or 0))
        elif skip:
            continue
        elif word is not None:
            if first and word in _RTF_SKIP:
                skip = True
            elif word == b"ansicpg" and num:
                try:
                    codec = codecs.lookup(f"cp{int(num)}").name
                except LookupError:
                    pass
            elif word == b"uc" and num:
                uc = max(0, int(num))
            elif word == b"u" and num:
                flush()
                code = int(num) + (65_536 if int(num) < 0 else 0)
                sink.add(chr(code) if 0 <= code < 0x110000 else "")
                ignore = uc
            elif word in _RTF_TEXT:
                flush()
                sink.add(_RTF_TEXT[word])
        elif hexa is not None:
            if ignore:
                ignore -= 1
            else:
                pending.append(int(hexa, 16))
        elif sym is not None:
            if first and sym == b"*":
                skip = True
            elif sym in (b"\\", b"{", b"}"):
                pending += sym
            elif sym == b"~":
                flush()
                sink.add(" ")
            elif sym == b"_":
                pending += b"-"
            elif sym in (b"\n", b"\r"):
                flush()
                sink.add("\n")
        elif text is not None:
            if ignore:
                dropped = min(ignore, len(text))
                text, ignore = text[dropped:], ignore - dropped
            pending += text
    flush()
    text, cut = sink.result()
    # \uN으로 온 짝 대리 문자는 한 글자로, 짝 없는 것은 �로(파일에 쓸 수 있게)
    return text.encode("utf-16-le", "surrogatepass").decode("utf-16-le", "replace"), cut or len(raw) >= RAW_MAX


class _Html(HTMLParser):
    """html: script·style·template은 버리고, 블록 요소는 줄바꿈, 표 칸은 탭. 글자 속 빈칸은 하나로(pre 안은 그대로)."""

    BLOCK = frozenset({"p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "header", "footer", "table",
                       "ul", "ol", "blockquote", "pre", "hr", "dt", "dd", "title", "form", "nav", "aside", "main", "figure", "figcaption",
                       "address", "dl", "caption", "details", "summary", "body", "html"})
    SKIP = frozenset({"script", "style", "template"})

    def __init__(self, sink: _Sink) -> None:
        super().__init__(convert_charrefs=True)
        self.sink, self.skip, self.pre = sink, 0, 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in self.SKIP:
            self.skip += 1
        elif self.skip:
            return
        elif tag == "br":
            self.sink.add("\n")
        elif tag in ("td", "th"):
            self.sink.add("\t")
        elif tag in self.BLOCK:
            self.sink.add("\n")
        self.pre += tag == "pre"

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
        elif self.skip:
            return
        elif tag in self.BLOCK:
            self.sink.add("\n")
        if tag == "pre":
            self.pre = max(0, self.pre - 1)

    def handle_data(self, data: str) -> None:
        if not self.skip:
            self.sink.add(data if self.pre else re.sub(r"\s+", " ", data))


_KOREAN_CHARSETS = {"euc-kr", "euckr", "euc_kr", "ks_c_5601-1987", "ks_c_5601", "ksc5601", "x-windows-949", "windows-949", "uhc", "cp949"}


def _html_charset(head: bytes) -> str | None:
    """BOM, 그다음 <meta charset>. euc-kr 계열은 그 상위 집합인 cp949로 읽는다. 모르는 이름이면 None."""
    if head.startswith(codecs.BOM_UTF8):
        return "utf-8-sig"
    if head.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return "utf-16"
    m = re.search(rb"""<meta[^>]{0,300}?charset\s*=\s*["']?\s*([A-Za-z0-9_.:-]{1,40})""", head[:4096], re.I)
    if not m:
        return None
    name = m.group(1).decode("ascii").lower()
    if name in _KOREAN_CHARSETS:
        return "cp949"
    try:
        return codecs.lookup(name).name
    except LookupError:
        return None


def _html(path: Path, check) -> tuple[str, bool]:
    with path.open("rb") as f:
        head = f.read(1_000_000)
    encoding = _html_charset(head)
    if encoding is None:  # 표시가 없으면 txt처럼: UTF-8, 깨진 글자가 1%를 넘으면 cp949, 둘 다 아니면 글자 아님
        encoding = next((e for e in ("utf-8", "cp949") if _bad_share(head.decode(e, "replace")) <= BAD_SHARE), None)
        if encoding is None:
            return "", False
    sink = _Sink()
    parser = _Html(sink)
    decoder = codecs.getincrementaldecoder(encoding)("replace")
    with path.open("rb") as f:
        while (block := f.read(1_000_000)) and not sink.cut:
            check()
            parser.feed(decoder.decode(block))
        parser.feed(decoder.decode(b"", final=True))
    parser.close()
    text, cut = sink.result()
    text = re.sub(r"\n{3,}", "\n\n", re.sub(r" *\n *", "\n", text))
    return text.strip() + "\n" if text.strip() else "", cut


_READERS: dict[str, Callable[[Path, Callable[[], None]], tuple[str, bool]]] = {
    ".pdf": _pdf, ".docx": _docx, ".txt": _plain, ".md": _plain, ".csv": _plain,
    ".hwp": _hwp, ".hwpx": _hwpx, ".pptx": _pptx, ".xlsx": _xlsx, ".odt": _odt, ".rtf": _rtf, ".html": _html, ".htm": _html,
}


def save(att_dir: Path, name: str, result: Extracted) -> dict:
    """뽑은 결과를 첨부 폴더 안 .text/에 적는다(원본은 건드리지 않는다)."""
    text_file, status_file = text_paths(att_dir, name)
    text_file.parent.mkdir(parents=True, exist_ok=True)
    if result.status in READABLE:
        write_text(text_file, result.text)
    elif text_file.exists():
        text_file.unlink()  # 이 코드가 만든 파생 파일(다시 뽑았더니 글자가 없다)
    status = {"status": result.status, "chars": len(result.text), "ms": result.ms, "at": utcnow(), "version": VERSION}
    if result.reason:
        status["reason"] = result.reason
    write_json(status_file, status)
    return status


def check_report(path: Path) -> str:
    """`magus extract-check`(2026-10-11): 실제 파일로 뽑기를 확인한다. 형식·상태·쪽 수(대화에서 읽는 3,000자 쪽)·글자 수·시간·앞 300자.
    파일 이름과 본문 전체는 내보내지 않는다(로그에도 형식·상태만 남는다)."""
    from magus.attachments import kind_of  # noqa: PLC0415

    suffix = path.suffix.lower()
    head = f"형식: {suffix or '(확장자 없음)'} · {kind_of(path.name) or '알 수 없음'}"
    if not path.is_file():
        return f"{head}\n상태: 파일이 없습니다"
    if no_text(path.name):
        return f"{head}\n상태: {NO_TEXT}"
    if not extractable(path.name):
        return f"{head}\n상태: 글자를 뽑는 형식이 아닙니다({FORMATS})"
    got = extract(path)
    why = _WHY.get(got.reason or "")
    state = {"ok": "뽑음", "truncated": f"앞부분만({TEXT_MAX:,}자에서 자름)", "empty": "글자 없음", "later": f"시간 넘음({DEADLINE:.0f}초)",
             "failed": f"{HWP_UNREADABLE}({why})" if why else "글자를 뽑지 못함"}.get(got.status, got.status)
    lines = [head, f"상태: {state}", f"글자 수: {len(got.text):,}", f"쪽 수: {len(pages(got.text)) if got.text else 0}(대화에서 읽는 {PAGE_CHARS:,}자 쪽)",
             f"시간: {got.ms:,}ms"]
    if got.text:
        lines += ["앞 300자:", got.text[:300]]
    return "\n".join(lines)


def pages(text: str) -> list[str]:
    """대화에서 읽을 쪽(3,000자씩, 문단 경계 가까이에서 자른다)."""
    out, start = [], 0
    while start < len(text):
        end = min(len(text), start + PAGE_CHARS)
        if end < len(text):
            cut = text.rfind("\n", start + PAGE_CHARS // 2, end)
            end = cut + 1 if cut > start else end
        out.append(text[start:end])
        start = end
    return out or [""]


def page_of(text: str, needle: str, offset: int = 0) -> int:
    """needle이 든 쪽 번호(1부터). 못 찾으면 1. offset: needle 시작에서 몇 글자 뒤의 쪽인지(2026-10-14: 조각(800자) 첫머리가 아니라
    조각 안에서 맞은 곳의 쪽을 알린다. 전에는 맞은 곳이 다음 쪽에 있어도 조각이 시작한 쪽을 알렸다)."""
    at = text.find(needle) if needle else -1
    if at < 0:
        return 1
    return page_at(text, at + max(0, offset))


def page_at(text: str, at: int) -> int:
    """글자 자리 at이 든 쪽 번호(1부터)."""
    seen = 0
    for n, page in enumerate(pages(text), 1):
        seen += len(page)
        if at < seen:
            return n
    return max(1, len(pages(text)))


__all__ = ["DEADLINE", "DONE", "EXTRACTABLE", "FORMATS", "HWP_UNREADABLE", "NO_TEXT", "PAGE_CHARS", "READABLE", "SHEET_ROWS", "TEXT_DIR",
           "TEXT_MAX", "Extracted", "due", "extract", "extractable", "no_text", "page_at", "page_of", "pages", "read_status", "read_text", "save", "stale",
           "text_paths", "unreadable_hwp"]
