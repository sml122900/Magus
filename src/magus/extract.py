"""첨부 글자 뽑기(2026-10-09, 사용자 요청 #100-3): 게시판 글에 붙인 문서에서 글자를 뽑아 찾고 읽게 한다.

- 대상: docx·pdf(글자가 있는 것)·txt·md. 그림·스캔 PDF는 이번에 하지 않는다(글자가 안 나오면 '글자 없음'으로 적는다. OCR은 다음 결정).
- 어디에: 그 첨부 폴더 안 `.text/<파일 이름>.txt`(뽑은 글자)와 `.text/status.json`({status, chars, ms, at, version}). 원본은 읽기만.
  썸네일(.thumb/)과 같은 방식이라 옛 코드는 첨부 폴더에서 파일만 세므로 무시한다. 첨부 폴더째 움직이므로 휴지통 왕복에도 함께 간다.
- 한도: 첨부 하나 30만 자(넘으면 앞부분만 두고 status=truncated). 시간 20초(넘으면 status=later, 처음 열 때 다시 뽑는다).
  시간은 쪽(PDF)·문단(docx)·덩어리(txt)마다 살펴 멈춘다(프로세스를 따로 띄우지 않는다: 서버 메모리 1GB).
- 메모리: PDF는 pymupdf로 한 쪽씩 읽는다(문서 전체를 올리지 않는다). docx는 zip 안 word/document.xml을 lxml iterparse로 문단마다 읽고 버린다.
  txt·md는 1MB씩 읽어 30만 자에서 멈춘다. 새 라이브러리는 없다(pymupdf·lxml은 원고 읽기에 이미 쓴다).
- 로그에는 개수·시간·상태만 남긴다(파일 이름·뽑은 글자는 남기지 않는다).
"""

from __future__ import annotations

import codecs
import json
import logging
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path

from magus import zipguard
from magus.ids import utcnow
from magus.store.fileio import write_json, write_text

TEXT_DIR = ".text"
STATUS_FILE = "status.json"
TEXT_MAX = 300_000  # 첨부 하나에서 둘 글자 수
DEADLINE = 20.0  # 초. 넘으면 '나중에'
PAGE_CHARS = 3_000  # 대화에서 한 번에 읽는 쪽
EXTRACTABLE = (".docx", ".pdf", ".txt", ".md")
VERSION = 1
# status: ok(뽑음) · truncated(30만 자 넘어 앞부분만) · empty(글자 없음: 그림·스캔 PDF·빈 문서) · failed(읽지 못함: 깨진 파일·암호) · later(시간 넘음)
DONE = ("ok", "truncated", "empty", "failed")
READABLE = ("ok", "truncated")
log = logging.getLogger("magus.extract")
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class _Late(Exception):
    pass


@dataclass(frozen=True)
class Extracted:
    status: str
    text: str  # READABLE일 때만 글자가 있다
    ms: int = 0


def extractable(name: str) -> bool:
    return Path(name).suffix.lower() in EXTRACTABLE


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
    try:
        if suffix == ".pdf":
            text, cut = _pdf(path, check)
        elif suffix == ".docx":
            text, cut = _docx(path, check)
        elif suffix in (".txt", ".md"):
            text, cut = _plain(path, check)
        else:
            return Extracted("failed", "", 0)
    except _Late:
        return Extracted("later", "", int((time.monotonic() - start) * 1000))
    except Exception as e:  # 깨진 zip·암호 PDF 등. 이름·내용은 남기지 않는다
        log.info("extract failed kind=%s error=%s", suffix, type(e).__name__)
        return Extracted("failed", "", int((time.monotonic() - start) * 1000))
    ms = int((time.monotonic() - start) * 1000)
    if not text.strip():
        return Extracted("empty", "", ms)
    return Extracted("truncated" if cut else "ok", text, ms)


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


def _docx(path: Path, check) -> tuple[str, bool]:
    from lxml import etree  # noqa: PLC0415

    parts: list[str] = []
    total = 0
    with zipfile.ZipFile(path) as z:
        zipguard.check(z)  # 압축 폭탄은 풀기 전에 막는다(2026-10-09 점검 7-c) → 글자를 뽑지 못함(failed)
    with zipfile.ZipFile(path) as z, z.open("word/document.xml") as f:
        for n, (_, p) in enumerate(etree.iterparse(f, events=("end",), tag=f"{_W}p")):
            if n % 200 == 0:
                check()
            pieces = []
            for el in p.iter(f"{_W}t", f"{_W}tab", f"{_W}br"):
                pieces.append(el.text or "" if el.tag == f"{_W}t" else ("\t" if el.tag == f"{_W}tab" else "\n"))
            total, cut = _limit(parts, total, "".join(pieces) + "\n")
            p.clear()  # 읽은 문단은 버린다
            if cut:
                return "".join(parts), True
    return "".join(parts), False


def _plain(path: Path, check) -> tuple[str, bool]:
    """txt·md: 1MB씩 읽어 30만 자에서 멈춘다. UTF-8(BOM 포함)이 아니면 cp949로 읽는다."""
    for encoding, errors in (("utf-8-sig", "strict"), ("cp949", "replace")):
        decoder = codecs.getincrementaldecoder(encoding)(errors)
        parts: list[str] = []
        total = 0
        try:
            with path.open("rb") as f:
                while block := f.read(1_000_000):
                    check()
                    total, cut = _limit(parts, total, decoder.decode(block))
                    if cut:
                        return "".join(parts), True
                total, cut = _limit(parts, total, decoder.decode(b"", final=True))
            return "".join(parts), cut
        except UnicodeDecodeError:
            continue
    return "", False


def save(att_dir: Path, name: str, result: Extracted) -> dict:
    """뽑은 결과를 첨부 폴더 안 .text/에 적는다(원본은 건드리지 않는다)."""
    text_file, status_file = text_paths(att_dir, name)
    text_file.parent.mkdir(parents=True, exist_ok=True)
    if result.status in READABLE:
        write_text(text_file, result.text)
    elif text_file.exists():
        text_file.unlink()  # 이 코드가 만든 파생 파일(다시 뽑았더니 글자가 없다)
    status = {"status": result.status, "chars": len(result.text), "ms": result.ms, "at": utcnow(), "version": VERSION}
    write_json(status_file, status)
    return status


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


def page_of(text: str, needle: str) -> int:
    """needle이 든 쪽 번호(1부터). 못 찾으면 1."""
    at = text.find(needle) if needle else -1
    if at < 0:
        return 1
    seen = 0
    for n, page in enumerate(pages(text), 1):
        seen += len(page)
        if at < seen:
            return n
    return 1


__all__ = ["DEADLINE", "DONE", "EXTRACTABLE", "PAGE_CHARS", "READABLE", "TEXT_DIR", "TEXT_MAX", "Extracted", "extract", "extractable",
           "page_of", "pages", "read_status", "read_text", "save", "text_paths"]
