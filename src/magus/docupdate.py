"""문서 업데이트(2026-10-10, docs/decisions/document-update.md): 내 정보 › 문서 업데이트의 목록과 바꾸기.

- 목록: 게시판 첨부 문서(docx·hwpx·hwp·pdf·txt·md, 글과 문헌 글) + 예전 올린 파일(inbox). 새것부터.
- 원본 판정: 파일의 sha256이 어느 프로젝트의 판(edition) sha256과 같으면 그 프로젝트의 올린 문서 원본이다(가장 늦게 올린 판).
- 바꾸기(update_document): 그 문서 자리를 새 파일로. 이전 파일은 휴지통(첨부는 첨부 휴지통, 예전 올린 파일은 trash/inbox/).
  올린 문서의 원본이면 바꾸기가 곧 수정본 올리기다(book_import new_edition과 같은 규칙). **수정본을 먼저 만들고, 성공해야 파일을 바꾼다.**
  글 보기의 ✎ 고치기에서 첨부를 바꿀 때도 이것을 쓴다.
"""

from __future__ import annotations

import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import IO

from magus import activity
from magus.attachments import clean_name
from magus.extract import EXTRACTABLE, NO_TEXT_SUFFIXES
from magus.book.reupload import ReuploadReport, reupload_manuscript
from magus.ids import utcnow
from magus.inbox import INBOX_TYPES, MANUSCRIPT_TYPES, file_sha, has_format_chars, safe_filename
from magus.store import Store
from magus.store.fileio import write_data
from magus.store.formats import display_title, one_line

DOC_TYPES = EXTRACTABLE + NO_TEXT_SUFFIXES  # 문서 업데이트 화면에 보이는 첨부(2026-10-14: hwp·pptx 등 글자를 뽑는 형식 모두 + doc·ppt·xls)
_BAD_NAME = re.compile(r'[\\/:*?"<>|\x00-\x1f\x7f]')  # 이름 칸의 금지 문자(폴더 구분자·제어 문자)


class UpdateError(ValueError):
    """바꾸지 않고 멈춘 까닭(저자에게 보일 한 문장)과 종류(same·overlap·unreadable·name·type·big·full·missing·taken·one)."""

    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Source:
    """올린 문서의 원본: 그 프로젝트와 그 파일로 만든 판."""

    project_id: str
    title: str
    edition: int
    uploaded_at: str

    def label(self) -> str:
        return f"「{self.title}」 올린 문서 원본 · " + (f"수정본 E{self.edition}" if self.edition > 1 else "처음 올린 문서 E1")


@dataclass(frozen=True)
class DocRow:
    """문서 업데이트 화면의 한 줄. key: "att:<첨부 id>" 또는 "inbox:<이름>"."""

    key: str
    name: str
    size: int
    at: str
    project: str | None = None
    project_id: str | None = None
    node: str | None = None
    book: str | None = None
    book_id: str | None = None
    post: str | None = None
    link: str | None = None
    source: Source | None = None

    @property
    def is_inbox(self) -> bool:
        return self.key.startswith("inbox:")

    def haystack(self) -> str:
        """찾기 대상: 파일 이름·프로젝트·노드·책·글 제목(원본이면 그 프로젝트 이름도)."""
        return " ".join(x for x in (self.name, self.project, self.node, self.book, self.post,
                                    self.source.title if self.source else None) if x).lower()


def sources(store: Store, user_id: str) -> dict[str, Source]:
    """sha256 → 원본. 같은 파일로 여러 판·프로젝트를 만들었으면 가장 늦게 올린 판."""
    out: dict[str, Source] = {}
    for project in store.list_projects(user_id):
        for e in store.list_editions(user_id, project.id):
            if e.sha256 and (e.sha256 not in out or e.uploaded_at > out[e.sha256].uploaded_at):
                out[e.sha256] = Source(project.id, project.title, e.number, e.uploaded_at)
    return out


def source_of(store: Store, user_id: str, path: Path, name: str, known: dict[str, Source] | None = None) -> Source | None:
    if Path(name).suffix.lower() not in MANUSCRIPT_TYPES:
        return None
    known = sources(store, user_id) if known is None else known
    return known.get(file_sha(path)) if known else None


def list_documents(store: Store, user_id: str) -> list[DocRow]:
    known = sources(store, user_id)
    floors = {f.id: f for f in store.list_floors(user_id)}
    books = {c.id: c for c in store.list_categories(user_id)}
    nodes: dict[str, str] = {}  # 책 id → 노드 이름(가운데는 '가운데')
    for floor in floors.values():
        found = store.get_map(user_id, floor.id)
        for n in found.nodes if found else ():
            for key in n.books:
                nodes.setdefault(key, "가운데" if n.center else n.name)
    rows: list[DocRow] = []
    for owner, att in store.file_attachments(user_id, DOC_TYPES):
        hit = store.attachment_path(user_id, owner, att.id)
        if hit is None:
            continue
        if owner.startswith("ref:"):
            key = owner[4:]
            ref = store.get_ref(user_id, key)
            book_id = ref.book if ref else None
            from magus.melchior.author_report import cite_label  # noqa: PLC0415

            post = cite_label(ref, key) if ref else key
            link = f"/shelf/{book_id}/{key}" if book_id else None
        else:
            book_id, _, item_id = owner.partition("/")
            item = store.get_category_item(user_id, book_id, item_id)
            names = [a.name for a in store.list_attachments(user_id, owner)]
            post = display_title(item.title, item.content, item.fields, names, 60) if item else item_id
            link = f"/shelf/{book_id}/{item_id}"
        book = books.get(book_id or "")
        floor = floors.get(book.floor) if book else None
        rows.append(DocRow(
            f"att:{att.id}", att.name, att.size, att.at,
            project=floor.title if floor else None, project_id=floor.id if floor else None,
            node=nodes.get(book_id or ""), book=book.name if book else None, book_id=book_id, post=post, link=link,
            source=source_of(store, user_id, hit[0], att.name, known)))
    for f in store.list_inbox(user_id):
        path = store.inbox_path(user_id, f.name)
        rows.append(DocRow(f"inbox:{f.name}", f.name, f.size, f.modified,
                           source=source_of(store, user_id, path, f.name, known) if path else None))
    return sorted(rows, key=lambda r: r.at, reverse=True)


def find_rows(rows: list[DocRow], q: str) -> list[DocRow]:
    """글자 그대로 포함(대소문자 무시): 앞 글자·가운데 글자 모두. 낱말이 여럿이면 모두 들어 있는 줄."""
    words = q.lower().split()
    return [r for r in rows if all(w in r.haystack() for w in words)] if words else rows


@dataclass
class UpdateResult:
    old_name: str
    new_name: str
    trash: str  # 이전 파일이 간 휴지통 화면 주소
    title_changed: bool = False
    revision: ReuploadReport | None = None
    project_id: str | None = None


def new_name(chosen: str, stem: str | None, *, inbox: bool) -> str:
    """고른 파일 이름 + 저자가 고친 이름 칸 → 저장할 이름. 확장자는 고른 파일의 것(고칠 수 없다). 금지 문자는 거절(UpdateError)."""
    picked = Path(str(chosen or "").replace("\\", "/").rsplit("/", 1)[-1])
    suffix = picked.suffix
    wanted = one_line(stem or "") or picked.stem
    if wanted.lower().endswith(suffix.lower()) and suffix:  # 이름 칸에 확장자까지 적었으면 한 번만
        wanted = wanted[: -len(suffix)]
    name = f"{wanted}{suffix}"
    if _BAD_NAME.search(wanted) or has_format_chars(wanted):  # 폴더 구분자 등은 떼지 않고 거절(clean_name은 경로를 떼어 버린다)
        raise UpdateError("파일 이름에 쓸 수 없는 글자가 있습니다(/ \\ : * ? \" < > | 와 보이지 않는 글자, 200바이트 넘는 이름).", "name")
    try:
        return safe_filename(name) if inbox else clean_name(name)
    except ValueError as e:
        if "형식" in str(e):
            raise UpdateError(f"받지 않는 형식입니다: {picked.name}", "type") from e
        raise UpdateError("파일 이름에 쓸 수 없는 글자가 있습니다(/ \\ : * ? \" < > | 와 보이지 않는 글자, 200바이트 넘는 이름).",
                          "name") from e


def _title_rule(store: Store, user_id: str, owner: str, old: str, new: str) -> bool:
    """글 제목이 이전 파일 이름(확장자 포함 또는 뺀 것)과 같으면 같은 꼴로 새 이름으로 바꾼다. 문헌 글은 제목이 서지라 그대로."""
    if owner.startswith("ref:"):
        return False
    book, _, item_id = owner.partition("/")
    item = store.get_category_item(user_id, book, item_id)
    if item is None or not item.title:
        return False
    norm = lambda s: " ".join(s.split())  # noqa: E731  (제목 자동 채움은 공백을 하나로 줄인다)
    title = norm(item.title)
    if title == norm(old):
        changed = new
    elif title == norm(Path(old).stem):
        changed = norm(Path(new).stem)
    else:
        return False
    if changed == item.title:
        return False
    store.patch_category_item(user_id, book, item_id, {"title": changed, "edited_at": utcnow(), "edited_by": "author"})
    return True


def update_document(store: Store, user_id: str, key: str, chosen: str, data: IO[bytes], size: int, stem: str | None, *,
                    max_attach: int, max_upload: int, max_user: int, force: bool = False,
                    allowed: tuple[str, ...] | None = DOC_TYPES) -> UpdateResult:
    """key("att:<id>" | "inbox:<이름>")의 문서를 새 파일로 바꾼다. 멈추면 UpdateError(아무것도 바뀌지 않는다).
    allowed: 받을 확장자(문서 업데이트 화면은 DOC_TYPES, 글 고치기의 바꾸기는 None = 글의 첨부로 받는 형식 모두)."""
    inbox = key.startswith("inbox:")
    if inbox:
        old_name = key[len("inbox:"):]
        try:
            old_path = store.inbox_path(user_id, old_name)
        except ValueError:
            old_path = None
        owner = att_id = ""
    else:
        att_id = key[len("att:"):]
        try:
            hit = store.find_attachment(user_id, att_id)
        except ValueError:
            hit = None
        owner = hit[0] if hit else ""
        found = store.attachment_path(user_id, owner, att_id) if hit else None
        old_path, old_name = (found[0], found[1].name) if found else (None, "")
    if old_path is None:
        raise UpdateError("바꿀 문서가 없습니다. 화면을 새로 고쳐 주세요.", "missing")
    name = new_name(chosen, stem, inbox=inbox)
    source = source_of(store, user_id, old_path, old_name)
    suffix = Path(name).suffix.lower()
    if source is not None and suffix not in MANUSCRIPT_TYPES:
        raise UpdateError("올린 문서의 원본은 docx·hwpx·hwp·pdf 파일로만 바꿀 수 있습니다.", "type")
    if allowed is not None and suffix not in allowed:
        raise UpdateError(f"받지 않는 형식입니다: {name}", "type")
    if inbox and suffix not in INBOX_TYPES:
        raise UpdateError(f"받지 않는 형식입니다: {name}", "type")
    limit = max_upload if inbox else max_attach
    if size > limit:
        raise UpdateError(f"파일이 너무 큽니다: {size / 1_000_000:,.1f} MB(한 개 한도 {limit / 1_000_000:,.1f} MB).", "big")
    if store.usage_bytes(user_id) + size > max_user:
        raise UpdateError(f"저장 용량 한도({max_user / 1_000_000:,.0f} MB)를 넘습니다. 휴지통의 것도 용량에 들어갑니다.", "full")
    if inbox and name != old_name and store.inbox_path(user_id, name):
        raise UpdateError(f"같은 이름의 올린 파일 「{name}」이 이미 있습니다. 이름을 바꿔 주세요.", "taken")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        path = Path(tmp) / name
        write_data(path, data)  # 받은 임시 파일에서 흘려 쓴다(점검 5-a)
        result = UpdateResult(old_name, name, "/shelf/trash" if inbox else "")
        if source is not None:  # 올린 문서의 원본: 수정본을 먼저 만든다. 멈추면 파일도 그대로
            try:
                result.revision = reupload_manuscript(store, user_id, path, source.project_id, force=force)
            except (ValueError, FileNotFoundError) as e:
                said = str(e)
                code = "same" if said.startswith("이미 올린 파일") else "overlap" if "겹친다" in said else "unreadable"
                if code == "overlap":
                    said = (f"장 제목이 지금 올린 문서(「{source.title}」)와 많이 달라 멈췄습니다. 같은 책이 맞으면 "
                            "'같은 책이 맞습니다'에 표시하고 파일을 다시 골라 주세요.")
                elif code == "same":
                    said = "이미 올린 파일입니다. Word에서 고쳐 저장한 파일인지 확인해 주세요."
                raise UpdateError(said, code) from e
            result.project_id = source.project_id
        with path.open("rb") as f, activity.step(store, user_id, activity.UPDATE, "inbox" if inbox else "attachment") as act:
            note = f"문서 업데이트: 「{name}」로 바꿈"
            if inbox:  # 활동 기록에는 파일 이름 대신 이전 파일의 휴지통 id
                act.target = store.trash_inbox(user_id, old_name, note)
                store.put_inbox(user_id, name, f)
            else:
                new_att, _ = store.replace_attachment(user_id, owner, att_id, name, f, note)
                act.target = f"{owner}/{att_id}"
                result.title_changed = _title_rule(store, user_id, owner, old_name, name)
                book = store.get_category(user_id, owner.partition("/")[0]) if not owner.startswith("ref:") else None
                ref = store.get_ref(user_id, owner[4:]) if owner.startswith("ref:") else None
                floor = book.floor if book else (ref.floor if ref else None)
                result.trash = f"/shelf/p/{floor}/trash" if floor else "/shelf/trash"
    if not inbox:  # 첨부 글자(.text)를 새 파일로(20초까지, 넘으면 '나중에'), 썸네일은 볼 때 다시 만든다
        from magus.extract import extractable  # noqa: PLC0415

        if extractable(name):
            store.attachment_text(user_id, owner, new_att.id)
        store.attachment_thumb(user_id, owner, new_att.id)
    return result

