"""P0 저장소. 원본은 data/users/<user_id>/… 아래의 md/json 파일이고, data/index.sqlite는 인덱스다.

쓰기 순서는 항상 '파일 먼저, 인덱스 나중'이다. 인덱스가 어긋나면 reindex()로 파일에서 다시 만든다.
"""

from __future__ import annotations

import json
import logging
import re
import secrets
import shutil
import sqlite3
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any

from magus import activity
from magus.activity import CREATE, RESTORE, TRASH, logged
from magus.ids import new_id, safe_id, utcnow
from magus.store import formats
from magus.store.fileio import locked as _locked
from magus.store.attachments import AttachmentMixin
from magus.store.fileio import mtime as _mtime
from magus.store.fileio import read_json as _read_json
from magus.store.fileio import write_bytes as _write_bytes
from magus.store.fileio import write_data as _write_data
from magus.store.fileio import read_text as _read_text
from magus.store.fileio import to_int as _int
from magus.store.fileio import write_json as _write_json
from magus.store.fileio import write_text as _write_text
from magus.floors import COMMON, MAX_FLOORS
from magus.category.rules import HEX
from magus.contexts import from_record, to_record
from magus.store.categories import CategoryMixin, _item_from_record
from magus.store.contexts import ContextMixin
from magus.store.documents import DocumentMixin
from magus.store.floors import FloorMixin
from magus.store.maps import MapMixin
from magus.store.project_trash import ProjectTrashMixin, last_edition
from magus.store.trash_purge import TrashPurgeMixin
from magus.store.node_copy import NodeCopyMixin
from magus.store.shelf import ShelfMixin, safe_ref_key
from magus.store.base import (
    ANCHOR_MAX,
    BookTitles,
    Edition,
    CHAPTER_NUMBER_MAX,
    CHAPTER_RANGE,
    CHAPTER_STATUSES,
    AuthorKind,
    Change,
    Chapter,
    ChapterMeta,
    ChapterStatus,
    CiteKeys,
    Decision,
    InboxFile,
    Issue,
    IssueKind,
    IssueOrigin,
    IssueStatus,
    Part,
    Profile,
    Project,
    chapter_number_ok,
    reading_order,
    same_name,
)
from magus.store.schema import SCHEMA, SCHEMA_VERSION, TABLES

log = logging.getLogger("magus.store")
INDEX_PENDING = "index-pending.json"  # 파일은 저장됐는데 색인이 늦은 글(파생, 다 하면 지운다, 점검 12-a)
RETRY_WAITS = (0.0, 0.5, 1.0)  # 색인이 실패하면 기다렸다 다시(초). sqlite 자체도 잠김을 5초까지 기다린다
REPAIR_EVERY, REPAIR_TRIES = 2.0, 90  # 그래도 안 되면 뒤에서 2초마다, 3분까지

NON_CITATION_TERMS = "non_citation_terms.txt"
AI_AUTHORS = "ai_authors.txt"  # 이 프로젝트에서 AI로 볼 코멘트 작성자 이름(기본 목록에 더한다, #71)
ANSWERS = "answers.md"  # 저자 확인 질문지의 답(#84). 질문은 매번 계산하고 답만 쌓인다
CACHE_DIR = ".cache"  # 계산 캐시(파생값, 지워도 된다). 옛 코드는 읽지 않는다
ANSWERS_HEADER = ("# 저자 답\n\n질문은 매번 올린 문서와 문헌에서 계산하고, 답만 여기에 쌓인다(book_answer). "
                  "같은 질문에 다시 답하면 아래 것이 이긴다. 사람이 고쳐도 된다.\n")
_CHAPTER_FILE = re.compile(r"ch-(\d+)\.md")
_VERSION_FILE = re.compile(r"ch-(\d+)\.v(\d+)\.md")

class LocalStore(ShelfMixin, CategoryMixin, ContextMixin, FloorMixin, MapMixin, DocumentMixin, AttachmentMixin, ProjectTrashMixin,
                 TrashPurgeMixin, NodeCopyMixin):
    def __init__(self, data_dir: Path):
        self.root = Path(data_dir)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._skipped: list[str] = []  # 마지막 색인 다시 만들기에서 건너뛴 파일(데이터 루트 기준 경로)
        self._db = sqlite3.connect(self.root / "index.sqlite", check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        if self._db.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
            log.info("인덱스 스키마 v%s 생성 → 파일에서 재생성", SCHEMA_VERSION)
            self.reindex()
        self._repairer: threading.Thread | None = None
        if self._pending_path().exists() and self._repair_pending():  # 지난번에 늦은 색인(점검 12-a)
            self._start_repair()  # 남은 것은 뒤에서 계속

    def close(self) -> None:
        self._db.close()

    # ---- 파일을 쓴 뒤의 색인(2026-10-09 점검 12-a) -----------------------------------------------
    # 쓰기 순서는 파일 → 색인이다. 색인이 실패하면(다른 프로세스가 DB를 잠금 등) 전에는 도구 오류가 나 같은 글을 다시 넣어 둘이 됐고,
    # 휴지통은 색인에 유령 글이 남았다. 이제 파일은 저장된 것이므로 오류를 올리지 않는다: 두 번 더 해 보고, 그래도 안 되면
    # 그 글 하나를 기록해 두고(index-pending.json, 파생) 뒤에서 파일 기준으로 다시 색인한다. 서버를 다시 띄우면 남은 것을 먼저 한다.

    def _sync_index(self, user_id: str, owner: str) -> None:
        """owner: 'item:<책 id>/<글 id>' 또는 'ref:<key>'. 파일 그대로 그 하나를 색인한다(파일이 없으면 색인에서 뺀다)."""
        last: Exception | None = None
        for wait in RETRY_WAITS:
            if wait:
                time.sleep(wait)
            try:
                with self._db:
                    self._index_one(user_id, owner)
                return
            except sqlite3.OperationalError as e:
                last = e
        log.warning("색인 늦음(파일은 저장됨, 그 글만 뒤에서 다시): %s", type(last).__name__)
        self._pending_add(user_id, owner)

    def _index_one(self, user_id: str, owner: str) -> None:
        kind, _, rest = owner.partition(":")
        if kind == "item":
            book, _, item_id = rest.partition("/")
            path = self._category_dir(user_id, book) / "items" / f"{safe_id(item_id, 'item id')}.json"
            if path.exists():
                self._index_item(user_id, _item_from_record(book, _read_json(path)))
            else:
                self._db.execute("DELETE FROM category_items WHERE user_id = ? AND category_id = ? AND id = ?", (user_id, book, item_id))
                self._drop_chunks(user_id, "category", f"{book}/{item_id}")
        elif kind == "ref":
            rdir = self._melchior_dir(user_id) / safe_ref_key(rest)
            if (rdir / "bib.json").exists():
                self._index_ref(user_id, rdir)

    def _pending_path(self) -> Path:
        return self.root / INDEX_PENDING

    def _pending_read(self) -> dict[str, list[str]]:
        try:
            data = json.loads(self._pending_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return {u: [o for o in owners if isinstance(o, str)] for u, owners in data.items() if isinstance(owners, list)} if isinstance(data, dict) else {}

    def _pending_write(self, pending: dict[str, list[str]]) -> None:
        pending = {u: owners for u, owners in pending.items() if owners}
        if pending:
            _write_text(self._pending_path(), json.dumps(pending, ensure_ascii=False, indent=1) + "\n")
        else:
            self._pending_path().unlink(missing_ok=True)

    def _pending_add(self, user_id: str, owner: str) -> None:
        pending = self._pending_read()
        pending[user_id] = list(dict.fromkeys([*pending.get(user_id, []), owner]))
        self._pending_write(pending)
        self._start_repair()

    def _start_repair(self) -> None:
        if self._repairer is None or not self._repairer.is_alive():
            self._repairer = threading.Thread(target=self._repair_loop, name="magus-index-repair", daemon=True)
            self._repairer.start()

    def _repair_pending(self) -> int:
        """기록된 늦은 색인을 지금 한 번 해 본다. 남은 수를 돌려준다."""
        with self._lock:
            pending = self._pending_read()
            for user_id, owners in pending.items():
                left = []
                for owner in owners:
                    try:
                        with self._db:
                            self._index_one(user_id, owner)
                    except sqlite3.OperationalError:
                        left.append(owner)
                pending[user_id] = left
            self._pending_write(pending)
            return sum(len(o) for o in pending.values())

    def _repair_loop(self) -> None:
        for _ in range(REPAIR_TRIES):
            time.sleep(REPAIR_EVERY)
            try:
                if self._repair_pending() == 0:
                    log.info("늦은 색인을 다시 했다")
                    return
            except sqlite3.ProgrammingError:  # 저장소가 닫혔다(서버 종료). 다음 시작 때 한다
                return
        log.error("늦은 색인을 다시 하지 못했다(파일은 그대로) — 서버를 다시 시작하면 다시 한다")

    # ---- 경로 ------------------------------------------------------------------------

    def _user_dir(self, user_id: str) -> Path:
        return self.root / "users" / safe_id(user_id, "user_id")

    def _project_dir(self, user_id: str, project_id: str) -> Path:
        return self._user_dir(user_id) / "projects" / safe_id(project_id, "project_id")

    def record_activity(self, user_id: str, action: str, kind: str, target: str) -> None:
        activity.write(self._user_dir(user_id), action, kind, target)

    def _require_project(self, user_id: str, project_id: str) -> Path:
        pdir = self._project_dir(user_id, project_id)
        if not (pdir / "project.json").exists():
            raise ValueError(f"프로젝트 {project_id!r}가 없다")
        return pdir

    def _rel(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    @_locked
    def list_users(self) -> list[str]:
        return [r[0] for r in self._db.execute("SELECT id FROM users ORDER BY id")]

    # ---- 프로젝트 --------------------------------------------------------------------

    @logged(CREATE, "project", lambda args, kw, result: result.id)
    @_locked
    def create_project(
        self, user_id: str, title: str, project_id: str | None = None, *, titles: BookTitles | None = None
    ) -> Project:
        project_id = safe_id(project_id or secrets.token_hex(4), "project_id")
        if project_id == COMMON:
            raise ValueError(f"{COMMON!r}은 「내 서재」(옛 공용 층)의 id라 다른 프로젝트 id로 쓸 수 없다")
        pdir = self._project_dir(user_id, project_id)
        if (pdir / "project.json").exists():
            raise ValueError(f"프로젝트 {project_id!r}가 이미 있다")
        layout = self.ensure_layout(user_id)  # 층 배치를 먼저 파일로 적는다(이전 전 사용자, #93)
        if project_id not in layout.order and len(self._known(user_id, layout)) >= MAX_FLOORS:  # 「내 서재」도 하나로 센다(2026-10-11)
            raise ValueError(f"프로젝트는 {MAX_FLOORS}개까지다")
        now = utcnow()
        for sub in ("book", "versions", "original"):
            (pdir / sub).mkdir(parents=True, exist_ok=True)
        extra = _title_fields(titles) if titles else {}
        _write_json(pdir / "project.json", {"title": title, **extra, "created_at": now, "parts": []})
        with self._db:
            self._index_project(user_id, project_id, title, now, extra)
        self._register_floor(user_id, project_id, layout)  # 프로젝트 순서에 더한다(#96부터 기본 책은 없다)
        self.ensure_maps(user_id)  # 새 프로젝트의 지도: 가운데 노드(#95)
        return Project(project_id, user_id, title, now, now, **extra)

    @_locked
    def set_titles(self, user_id: str, project_id: str, titles: BookTitles) -> Project:
        path = self._require_project(user_id, project_id) / "project.json"
        data = _read_json(path)
        if titles.title:
            data["title"] = titles.title
        for key in ("subtitle", "title_en", "subtitle_en"):
            data.pop(key, None)
        data.update(_title_fields(titles))
        _write_json(path, data)
        with self._db:
            self._db.execute(
                "UPDATE projects SET title = ?, subtitle = ?, title_en = ?, subtitle_en = ? WHERE user_id = ? AND id = ?",
                (data["title"], data.get("subtitle"), data.get("title_en"), data.get("subtitle_en"), user_id, project_id),
            )
        project = self.get_project(user_id, project_id)
        assert project is not None
        return project

    @_locked
    def get_project(self, user_id: str, project_id: str | None = None) -> Project | None:
        sql, args = "SELECT * FROM projects WHERE user_id = ?", [user_id]
        if project_id:
            sql, args = sql + " AND id = ?", [*args, project_id]
        row = self._db.execute(sql + " ORDER BY updated_at DESC, created_at DESC LIMIT 1", args).fetchone()
        return _project(row) if row else None

    @_locked
    def list_projects(self, user_id: str) -> list[Project]:
        rows = self._db.execute(
            "SELECT * FROM projects WHERE user_id = ? ORDER BY updated_at DESC, created_at DESC", (user_id,)
        )
        return [_project(r) for r in rows]

    @logged(TRASH, "manuscript", lambda args, kw, result: result.rsplit("/", 1)[-1])  # book_import replace=True
    @_locked
    def archive_project(self, user_id: str, project_id: str) -> str:
        pdir = self._require_project(user_id, project_id)
        target = self._user_dir(user_id) / "trash" / f"{project_id}-{utcnow().replace(':', '').replace('.', '')}"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(pdir), str(target))
        with self._db:
            for table in ("parts", "decisions", "issues"):
                self._db.execute(f"DELETE FROM {table} WHERE user_id = ? AND project_id = ?", (user_id, project_id))
            self._db.execute("DELETE FROM chapters WHERE user_id = ? AND project_id = ?", (user_id, project_id))
            self._db.execute("DELETE FROM projects WHERE user_id = ? AND id = ?", (user_id, project_id))
        return self._rel(target)

    @logged(TRASH, "manuscript", lambda args, kw, result: result.rsplit("/", 1)[-1])
    @_locked
    def trash_manuscript(self, user_id: str, project_id: str, note: str, *, confirm_name: str | None = None) -> str:
        """원고 책을 휴지통으로(#94): 작업물 폴더(장·확인 요청·결정·수정본 이력·원본)를 통째로 trash/<id>-<시각>/으로 옮기고,
        같은 id·제목의 빈 층을 남긴다. 층에 꽂힌 다른 책(생각·문헌·카테고리·문서)은 그대로다. 지우지 않는다.
        장이나 수정본 기록이 있으면 confirm_name이 그 이름이어야 한다(아니면 ValueError("name", 이름), 2026-10-14)."""
        project = self.get_project(user_id, project_id)
        if project is None:
            raise ValueError(f"프로젝트 {project_id!r}가 없다")
        guarded = self.list_chapters(user_id, project_id) or last_edition(self._project_dir(user_id, project_id) / "project.json")
        if guarded and not same_name(confirm_name, project.title):
            raise ValueError("name", project.title)
        moved = self.archive_project(user_id, project_id)
        _write_json(self.root / moved / "trash-note.json", {"at": utcnow(), "note": note})
        self.create_project(user_id, project.title, project_id, titles=BookTitles(project.title, project.subtitle,
                                                                                    project.title_en, project.subtitle_en))
        if project.contexts:  # 컨텍스트는 그 자리(가운데 노드의 책)에 남긴다(#96): 다시 올리면 그대로 읽힌다
            self.set_book_contexts(user_id, f"ms.{project_id}", project.contexts)
        return moved

    @_locked
    def set_project_color(self, user_id: str, project_id: str, color: str | None) -> None:
        path = self._require_project(user_id, project_id) / "project.json"
        if color is not None and not HEX.fullmatch(color):
            raise ValueError(f"색은 #RRGGBB: {color!r}")
        data = _read_json(path)
        data.pop("color", None)
        _write_json(path, {**data, **({"color": color.lower()} if color else {})})
        with self._db:
            self._db.execute("UPDATE projects SET color = ? WHERE user_id = ? AND id = ?",
                             (color.lower() if color else None, user_id, project_id))

    @_locked
    def save_original(self, user_id: str, project_id: str, filename: str, data: bytes) -> str:
        path = self._require_project(user_id, project_id) / "original" / Path(filename).name
        _write_bytes(path, data)  # 원자적으로(점검 10-a)
        return self._rel(path)

    @_locked
    def read_original(self, user_id: str, project_id: str, filename: str) -> str | None:
        """original/의 글 파일(임포트·수정본 리포트 md). 없거나 밖을 가리키면 None."""
        folder = self._project_dir(user_id, project_id) / "original"
        path = folder / Path(filename).name
        return path.read_text(encoding="utf-8") if path.suffix == ".md" and path.is_file() else None

    @_locked
    def original_bytes(self, user_id: str, project_id: str, filename: str | None = None) -> tuple[str, bytes] | None:
        """original/의 원고 파일(내려받기용, #95). filename이 없으면 마지막 수정본의 원고(docx·pdf). 없으면 None."""
        folder = self._project_dir(user_id, project_id) / "original"
        names = [filename] if filename else []
        if not names:
            editions = self.list_editions(user_id, project_id)
            if editions:
                last = editions[-1]
                names = [f"E{last.number}-{last.file}", last.file]
            names += sorted((p.name for p in folder.glob("*") if p.suffix.lower() in (".docx", ".hwpx", ".hwp", ".pdf")),
                            key=lambda n: (folder / n).stat().st_mtime, reverse=True) if folder.exists() else []
        for name in names:
            path = folder / Path(name).name
            if path.is_file():
                return path.name, path.read_bytes()
        return None

    @_locked
    def get_non_citation_terms(self, user_id: str, project_id: str) -> list[str]:
        path = self._project_dir(user_id, project_id) / "book" / NON_CITATION_TERMS
        lines = (line.strip() for line in _read_text(path).splitlines())
        return [line for line in lines if line and not line.startswith("#")]

    @_locked
    def set_non_citation_terms(self, user_id: str, project_id: str, terms: list[str]) -> None:
        path = self._require_project(user_id, project_id) / "book" / NON_CITATION_TERMS
        clean = list(dict.fromkeys(t.strip() for t in terms if t.strip()))
        header = "# 인용 추출에서 뺄 낱말(지명·사건·기관 등). 한 줄에 하나. 예: 마닐라(1571)의 '마닐라'\n"
        _write_text(path, header + "".join(f"{t}\n" for t in clean))

    @_locked
    def get_ai_authors(self, user_id: str, project_id: str) -> list[str]:
        path = self._project_dir(user_id, project_id) / "book" / AI_AUTHORS
        lines = (line.strip() for line in _read_text(path).splitlines())
        return [line for line in lines if line and not line.startswith("#")]

    @_locked
    def set_ai_authors(self, user_id: str, project_id: str, names: list[str]) -> None:
        path = self._require_project(user_id, project_id) / "book" / AI_AUTHORS
        clean = list(dict.fromkeys(n.strip() for n in names if n.strip()))
        header = "# AI로 볼 문서 코멘트 작성자 이름(기본 목록에 더한다). 한 줄에 하나. 예: 우리 편집 AI\n"
        _write_text(path, header + "".join(f"{n}\n" for n in clean))

    @_locked
    def get_answers(self, user_id: str, project_id: str) -> str:
        return _read_text(self._project_dir(user_id, project_id) / "book" / ANSWERS)

    @_locked
    def add_answer(self, user_id: str, project_id: str, block: str) -> None:
        path = self._require_project(user_id, project_id) / "book" / ANSWERS
        current = _read_text(path) or ANSWERS_HEADER
        _write_text(path, current.rstrip("\n") + "\n\n" + block.strip("\n") + "\n")

    def _cache_file(self, user_id: str, project_id: str, name: str) -> Path:
        return self._project_dir(user_id, project_id) / CACHE_DIR / f"{safe_id(name, 'cache')}.json"

    def get_cache(self, user_id: str, project_id: str, name: str) -> str:
        try:
            return _read_text(self._cache_file(user_id, project_id, name))
        except (OSError, UnicodeDecodeError):
            return ""

    def put_cache(self, user_id: str, project_id: str, name: str, text: str) -> None:
        path = self._cache_file(user_id, project_id, name)
        if not (path.parent.parent / "project.json").exists():
            return  # 그사이 프로젝트가 휴지통으로 갔다
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.{secrets.token_hex(4)}.tmp")  # 두 요청이 함께 써도 서로의 임시 파일을 밟지 않게
        tmp.write_text(text, encoding="utf-8", newline="\n")
        tmp.replace(path)

    @_locked
    def set_parts(self, user_id: str, project_id: str, parts: list[Part]) -> None:
        path = self._require_project(user_id, project_id) / "project.json"
        data = _read_json(path)
        data["parts"] = [{"number": p.number, "title": p.title} for p in parts]
        _write_json(path, data)
        with self._db:
            self._db.execute("DELETE FROM parts WHERE user_id = ? AND project_id = ?", (user_id, project_id))
            self._index_parts(user_id, project_id, parts)

    @_locked
    def list_parts(self, user_id: str, project_id: str) -> list[Part]:
        rows = self._db.execute(
            "SELECT number, title FROM parts WHERE user_id = ? AND project_id = ? ORDER BY number",
            (user_id, project_id),
        )
        return [Part(r["number"], r["title"]) for r in rows]

    # ---- 장 --------------------------------------------------------------------------

    @_locked
    def list_chapters(self, user_id: str, project_id: str) -> list[ChapterMeta]:
        rows = self._db.execute(
            "SELECT * FROM chapters WHERE user_id = ? AND project_id = ? ORDER BY number",
            (user_id, project_id),
        )
        return reading_order(_chapter_meta(r) for r in rows)

    @_locked
    def read_chapter(self, user_id: str, project_id: str, number: int) -> Chapter | None:
        if not chapter_number_ok(number):  # 범위 밖(2^63 등)은 없는 장. SQLite 정수 범위를 넘으면 OverflowError였다(2026-10-09 점검 15-2)
            return None
        row = self._db.execute(
            "SELECT * FROM chapters WHERE user_id = ? AND project_id = ? AND number = ?",
            (user_id, project_id, number),
        ).fetchone()
        if not row:
            return None
        _, body = formats.parse_chapter((self.root / row["path"]).read_text(encoding="utf-8"))
        return Chapter(_chapter_meta(row), body)

    @_locked
    def write_chapter(
        self,
        user_id: str,
        project_id: str,
        number: int,
        content: str,
        note: str,
        *,
        title: str | None = None,
        status: ChapterStatus | None = None,
        part_number: int | None = None,
        label: str | None = None,
        edition: int | None = None,
    ) -> ChapterMeta:
        if not chapter_number_ok(number):  # 쓰기 전에(2026-10-09 점검 15-1)
            raise ValueError(CHAPTER_RANGE)
        if status is not None and status not in CHAPTER_STATUSES:
            raise ValueError(f"status={status!r}: {'|'.join(CHAPTER_STATUSES)} 중 하나")
        # 메타는 서버가 관리한다. 호출자가 front matter를 붙여 보내도 버리고 본문만 쓴다.
        content, _ = formats.strip_front_matter(content)
        if not content:
            raise ValueError("본문이 비어 있다")
        pdir = self._require_project(user_id, project_id)
        path = pdir / "book" / f"ch-{number:02d}.md"
        old: dict[str, str] | None = None
        archive: Path | None = None
        if path.exists():
            # 사람이 파일을 직접 고쳤을 수도 있으니 인덱스가 아니라 파일을 그대로 보관한다.
            old, _ = formats.parse_chapter(path.read_text(encoding="utf-8"))
            archive = pdir / "versions" / f"ch-{number:02d}.v{_int(old.get('version'), 1)}.md"
            archive.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, archive)
        prev = old or {}
        now = utcnow()
        meta = {
            "label": label or prev.get("label"),
            "title": title or prev.get("title") or f"제{number}장",
            "status": status or prev.get("status") or "draft",
            "part_number": part_number if part_number is not None else _int(prev.get("part_number")),
            "version": _int(prev.get("version"), 1) + 1 if old is not None else 1,
            "edition": edition,  # 업로드로 쓴 본문만 판 번호를 단다. Magus에서 고치면 비워진다(#76)
            "updated_at": now,
            "last_note": note,
        }
        _write_text(path, formats.dump_chapter(meta, content))
        with self._db:
            chapter_id = self._index_chapter(user_id, project_id, number, path)
            if archive:
                self._index_version(user_id, chapter_id, archive)
            self._touch(user_id, project_id, now)
        row = self._db.execute("SELECT * FROM chapters WHERE id = ?", (chapter_id,)).fetchone()
        return _chapter_meta(row)

    @_locked
    def set_chapter_edition(self, user_id: str, project_id: str, number: int, edition: int) -> None:
        path = self._require_project(user_id, project_id) / "book" / f"ch-{number:02d}.md"
        meta, body = formats.parse_chapter(path.read_text(encoding="utf-8"))
        if meta.get("edition") == str(edition):
            return
        keys = list(meta)
        meta["edition"] = str(edition)
        if "edition" not in keys and "version" in keys:  # 앞머리 순서를 write_chapter와 같게(version 다음)
            meta = {k: meta[k] for k in [*keys[: keys.index("version") + 1], "edition", *keys[keys.index("version") + 1 :]]}
        _write_text(path, formats.dump_chapter(meta, body))
        with self._db:
            self._index_chapter(user_id, project_id, number, path)

    @_locked
    def remove_chapter(self, user_id: str, project_id: str, number: int, edition: int) -> str:
        pdir = self._require_project(user_id, project_id)
        target = pdir / "removed" / f"ch-{number:02d}-E{edition}"
        target.mkdir(parents=True, exist_ok=True)
        current = pdir / "book" / f"ch-{number:02d}.md"
        if current.exists():
            shutil.move(str(current), str(target / current.name))
        for f in (pdir / "versions").glob(f"ch-{number:02d}.v*.md"):  # 같은 번호의 새 장이 이전본을 덮지 않게
            if _VERSION_FILE.fullmatch(f.name):
                shutil.move(str(f), str(target / f.name))
        with self._db:
            self._db.execute(
                "DELETE FROM chapters WHERE user_id = ? AND project_id = ? AND number = ?", (user_id, project_id, number)
            )
            self._touch(user_id, project_id, utcnow())
        return self._rel(target)

    @_locked
    def list_editions(self, user_id: str, project_id: str) -> list[Edition]:
        data = _read_json(self._require_project(user_id, project_id) / "project.json")
        return [Edition(**e) for e in data.get("editions", [])]

    @_locked
    def add_edition(self, user_id: str, project_id: str, edition: Edition) -> None:
        path = self._require_project(user_id, project_id) / "project.json"
        data = _read_json(path)
        data["editions"] = [*data.get("editions", []), {k: v for k, v in asdict(edition).items() if v not in (None, False)}]
        _write_json(path, data)

    @_locked
    def recent_changes(self, user_id: str, project_id: str, limit: int = 5) -> list[Change]:
        rows = self._db.execute(
            """
            SELECT number, version, last_note AS note, updated_at AS at
              FROM chapters WHERE user_id = ? AND project_id = ?
            UNION ALL
            SELECT c.number, v.version, v.note, v.created_at
              FROM chapter_versions v JOIN chapters c ON c.id = v.chapter_id
             WHERE v.user_id = ? AND c.user_id = ? AND c.project_id = ?
            ORDER BY at DESC, version DESC
            LIMIT ?
            """,
            (user_id, project_id, user_id, user_id, project_id, limit),
        )
        return [Change(r["number"], r["version"], r["note"], r["at"]) for r in rows]

    # ---- 결정·미해결 -----------------------------------------------------------------

    @_locked
    def add_decision(self, user_id: str, project_id: str, text: str) -> Decision:
        if not text.strip():
            raise ValueError("결정 내용이 비어 있다")
        path = self._require_project(user_id, project_id) / "decisions.md"
        decisions = formats.parse_decisions(_read_text(path))
        decision = Decision(self._next_id(path.parent, "decision", (d.id for d in decisions)), text.strip(), utcnow())
        _write_text(path, formats.dump_decisions([*decisions, decision]))
        with self._db:
            self._index_decisions(user_id, project_id, [decision])
            self._touch(user_id, project_id, decision.created_at)
        return decision

    @_locked
    def list_decisions(self, user_id: str, project_id: str, limit: int | None = None) -> list[Decision]:
        rows = self._db.execute(
            "SELECT id, text, created_at FROM decisions WHERE user_id = ? AND project_id = ? "
            "ORDER BY id DESC LIMIT ?",
            (user_id, project_id, -1 if limit is None else limit),
        )
        return [Decision(r["id"], r["text"], r["created_at"]) for r in rows]

    @_locked
    def add_issue(
        self,
        user_id: str,
        project_id: str,
        text: str,
        origin: IssueOrigin = "user",
        chapter_number: int | None = None,
        *,
        kind: IssueKind = "general",
        ref_key: str | None = None,
        author: str | None = None,
        author_kind: AuthorKind | None = None,
        comment_date: str | None = None,
        anchor: str | None = None,
        paragraph: int | None = None,
        comment_fp: str | None = None,
    ) -> Issue:
        if not text.strip():
            raise ValueError("확인 요청 내용이 비어 있다")
        path = self._require_project(user_id, project_id) / "issues.md"
        issues = formats.parse_issues(_read_text(path))
        issue = Issue(
            id=self._next_id(path.parent, "issue", (i.id for i in issues)),
            text=text.strip(),
            status="open",
            origin=origin,
            chapter_number=chapter_number,
            created_at=utcnow(),
            kind=kind,
            ref_key=ref_key,
            author=author or None,
            author_kind=author_kind,
            comment_date=comment_date or None,
            anchor=formats.one_line(anchor)[:ANCHOR_MAX] or None if anchor else None,
            paragraph=paragraph,
            comment_fp=comment_fp,
        )
        _write_text(path, formats.dump_issues([*issues, issue]))
        with self._db:
            self._index_issues(user_id, project_id, [issue])
            self._touch(user_id, project_id, issue.created_at)
        return issue

    @_locked
    def close_issue(self, user_id: str, project_id: str, issue_id: int, note: str | None = None) -> Issue | None:
        path = self._require_project(user_id, project_id) / "issues.md"
        issues = formats.parse_issues(_read_text(path))
        target = next((i for i in issues if i.id == issue_id), None)
        if target is None:
            return None
        closed = replace(target, status="closed", closed_note=(note or "").strip() or target.closed_note)
        _write_text(path, formats.dump_issues([closed if i.id == issue_id else i for i in issues]))
        with self._db:
            self._index_issues(user_id, project_id, [closed])
            self._touch(user_id, project_id, utcnow())
        return closed

    @_locked
    def update_issues(self, user_id: str, project_id: str, issues: list[Issue]) -> None:
        if not issues:
            return
        path = self._require_project(user_id, project_id) / "issues.md"
        new = {i.id: replace(i, anchor=formats.one_line(i.anchor)[:ANCHOR_MAX] if i.anchor else None) for i in issues}
        current = formats.parse_issues(_read_text(path))
        if missing := set(new) - {i.id for i in current}:
            raise ValueError(f"없는 확인 요청: {sorted(missing)}")  # 용어집 이름(점검 25-b)
        _write_text(path, formats.dump_issues([new.get(i.id, i) for i in current]))
        with self._db:
            self._index_issues(user_id, project_id, list(new.values()))
            self._touch(user_id, project_id, utcnow())

    @_locked
    def set_issue_refs(self, user_id: str, project_id: str, ref_ids: dict[int, str | None]) -> None:
        if not ref_ids:
            return
        path = self._require_project(user_id, project_id) / "issues.md"
        issues = [
            replace(i, ref_id=ref_ids[i.id]) if i.id in ref_ids else i
            for i in formats.parse_issues(_read_text(path))
        ]
        _write_text(path, formats.dump_issues(issues))
        with self._db:
            self._index_issues(user_id, project_id, [i for i in issues if i.id in ref_ids])

    @_locked
    def set_cite_keys(self, user_id: str, project_id: str, cites: dict[int, CiteKeys]) -> None:
        with self._db:
            self._db.executemany(
                "UPDATE chapters SET unverified_cite_count = ?, unverified_cite_keys = ?, uncertain_cite_keys = ?"
                " WHERE user_id = ? AND project_id = ? AND number = ?",
                [
                    (len(k.unverified), json.dumps(sorted(k.unverified)), json.dumps(sorted(k.uncertain)),
                     user_id, project_id, number)
                    for number, k in cites.items()
                ],
            )

    def _inbox_dir(self, user_id: str) -> Path:
        return self._user_dir(user_id) / "inbox"

    def _inbox_file(self, user_id: str, name: str) -> Path:
        path = self._inbox_dir(user_id) / name
        if path.parent != self._inbox_dir(user_id) or name in ("", ".", ".."):
            raise ValueError(f"올린 파일 이름이 아니다: {name!r}")
        return path

    def list_inbox(self, user_id: str) -> list[InboxFile]:
        folder = self._inbox_dir(user_id)
        if not folder.is_dir():
            return []
        return [_inbox_entry(p) for p in sorted(folder.iterdir(), key=lambda p: p.name) if p.is_file()]

    def put_inbox(self, user_id: str, name: str, data: bytes | IO[bytes]) -> InboxFile:
        path = self._inbox_file(user_id, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.{secrets.token_hex(4)}.part")
        _write_data(tmp, data)  # 업로드는 임시 파일에서 흘려 쓴다(점검 5-a)
        tmp.replace(path)  # 받는 도중에 끊겨도 반쪽 파일이 받은함에 보이지 않는다
        return _inbox_entry(path)

    def delete_inbox(self, user_id: str, name: str) -> bool:
        path = self._inbox_file(user_id, name)
        if not path.is_file():
            return False
        path.unlink()
        return True

    def inbox_path(self, user_id: str, name: str) -> Path | None:
        path = self._inbox_file(user_id, name)
        return path if path.is_file() else None

    # 예전 올린 파일의 휴지통(2026-10-10 문서 업데이트): trash/inbox/<휴지통 id>/<이름> + <휴지통 id>.trash.json = {at, note, name}
    def _inbox_trash(self, user_id: str) -> Path:
        return self._user_dir(user_id) / "trash" / "inbox"

    @logged(TRASH, "inbox", lambda args, kw, result: result)  # 파일 이름 대신 휴지통 id
    @_locked
    def trash_inbox(self, user_id: str, name: str, note: str) -> str:
        path = self._inbox_file(user_id, name)
        if not path.is_file():
            raise ValueError(f"올린 파일에 {name!r}이 없다")
        trash_id = new_id()
        folder = self._inbox_trash(user_id) / trash_id
        folder.mkdir(parents=True)
        shutil.move(str(path), str(folder / path.name))
        _write_json(folder.with_name(f"{trash_id}.trash.json"), {"at": utcnow(), "note": note, "name": path.name})
        return trash_id

    @_locked
    def list_trashed_inbox(self, user_id: str) -> list[tuple[str, InboxFile, dict]]:
        out = []
        for mark in sorted(self._inbox_trash(user_id).glob("*.trash.json"), reverse=True):
            folder = mark.with_name(mark.name.removesuffix(".trash.json"))
            files = [p for p in folder.iterdir() if p.is_file()] if folder.is_dir() else []
            if len(files) == 1:
                out.append((folder.name, _inbox_entry(files[0]), _read_json(mark)))
        return out

    @logged(RESTORE, "inbox", lambda args, kw, result: args[0])
    @_locked
    def restore_inbox(self, user_id: str, trash_id: str) -> str:
        folder = self._inbox_trash(user_id) / safe_id(trash_id, "trash id")
        files = [p for p in folder.iterdir() if p.is_file()] if folder.is_dir() else []
        if len(files) != 1:
            raise ValueError("missing", "")
        target = self._inbox_file(user_id, files[0].name)
        if target.exists():
            raise ValueError("taken", files[0].name)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(files[0]), str(target))
        folder.rmdir()
        folder.with_name(f"{trash_id}.trash.json").unlink(missing_ok=True)
        return target.name

    @_locked
    def get_profile(self, user_id: str) -> Profile:
        path = self._user_dir(user_id) / "profile.json"
        data = _read_json(path) if path.exists() else {}
        return Profile(**{k: (str(data[k]) if data.get(k) else None) for k in ("email", "display_name", "email_at", "name_at")})

    @_locked
    def save_profile(self, user_id: str, profile: Profile) -> Profile:
        record = {"schema_version": 1, **{k: v for k, v in asdict(profile).items() if v}}
        _write_json(self._user_dir(user_id) / "profile.json", record)
        return profile

    def usage_bytes(self, user_id: str) -> int:
        folder = self._user_dir(user_id)
        return sum(p.stat().st_size for p in folder.rglob("*") if p.is_file()) if folder.is_dir() else 0

    def export_path(self, user_id: str, project_id: str, filename: str) -> Path | None:
        folder = self._project_dir(user_id, project_id) / "exports"
        path = folder / Path(filename).name
        return path if path.name == filename and path.is_file() else None

    @_locked
    def save_export(self, user_id: str, project_id: str, filename: str, data: bytes) -> str:
        path = self._require_project(user_id, project_id) / "exports" / Path(filename).name
        _write_bytes(path, data)  # 원자적으로(점검 10-a)
        return str(path.resolve())

    @_locked
    def list_issues(
        self,
        user_id: str,
        project_id: str,
        status: IssueStatus | None = "open",
        *,
        chapter_number: int | None = None,
        origin: IssueOrigin | None = None,
        kind: IssueKind | None = None,
    ) -> list[Issue]:
        if chapter_number is not None and not chapter_number_ok(chapter_number):  # 범위 밖 장(2026-10-09 점검 15-2)
            return []
        sql, args = "SELECT * FROM issues WHERE user_id = ? AND project_id = ?", [user_id, project_id]
        for column, value in (("status", status), ("chapter_number", chapter_number), ("origin", origin), ("kind", kind)):
            if value is not None:
                sql, args = sql + f" AND {column} = ?", [*args, value]
        rows = self._db.execute(sql + " ORDER BY id", args)
        return [
            Issue(
                r["id"], r["text"], r["status"], r["origin"], r["chapter_number"], r["created_at"], r["closed_note"],
                r["kind"], r["ref_key"], r["ref_id"], r["author"], r["author_kind"], r["comment_date"], r["anchor"],
                r["paragraph"], r["comment_fp"], r["stale"], r["stale_edition"],
            )
            for r in rows
        ]

    def _next_id(self, pdir: Path, kind: str, existing: Iterable[int]) -> int:
        """한 번 준 번호는 다시 쓰지 않는다. 사람이 md에서 항목을 지워도 project.json에 마지막 번호가 남는다."""
        path = pdir / "project.json"
        data = _read_json(path)
        key = f"last_{kind}_id"
        new_id = max(int(data.get(key, 0)), max(existing, default=0)) + 1
        data[key] = new_id
        _write_json(path, data)
        return new_id

    # ---- 인덱스 ----------------------------------------------------------------------

    @_locked
    def reindex(self) -> list[str]:
        """파일 → 색인(2026-10-09 점검 12-b). 새 색인을 옆 파일(index.sqlite.new)에 따로 만든 뒤 지금 색인에 통째로 옮긴다(SQLite backup).
        깨진 파일(JSON·앞머리를 읽지 못함, 범위 밖 장 번호 등)은 그것만 건너뛰고 경로를 로그에 남긴다(내용은 남기지 않는다).
        만드는 일 자체가 실패하면 지금 색인을 그대로 둔다 — 스키마가 다른 옛 색인이면 빈 새 스키마로(user_version은 올리지 않아 다음 시작 때 다시 만든다).
        어느 쪽이든 예외를 올리지 않아 서버는 뜬다. 건너뛴 파일의 경로를 돌려준다."""
        tmp = self.root / "index.sqlite.new"
        tmp.unlink(missing_ok=True)
        new = sqlite3.connect(tmp, check_same_thread=False)
        new.row_factory = sqlite3.Row
        new.execute("PRAGMA foreign_keys = ON")
        old, self._db, self._skipped = self._db, new, []
        try:
            new.executescript(SCHEMA)
            users_dir = self.root / "users"
            with new:
                for udir in sorted(users_dir.iterdir()) if users_dir.is_dir() else []:
                    if udir.is_dir():
                        self._index_user(udir.name, udir)
            new.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            new.commit()
            new.backup(old)  # 지금 색인 자리로 통째로(다 만든 뒤에만 바뀐다)
            (self.root / INDEX_PENDING).unlink(missing_ok=True)  # 다 다시 만들었으니 늦은 색인 기록은 끝(점검 12-a)
        except Exception as e:  # noqa: BLE001 — 색인은 파생값이다. 무엇이 실패해도 서버는 떠야 한다
            log.error("색인 다시 만들기 실패, 지금 색인을 그대로 둔다(%s)", type(e).__name__)
            self._db = old
            if old.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:  # 옛 스키마로는 화면이 깨진다 → 빈 새 스키마
                for table in reversed(TABLES):
                    old.execute(f"DROP TABLE IF EXISTS {table}")
                old.executescript(SCHEMA)
                log.error("색인을 빈 새 스키마로 두었다. 다음 시작 때 다시 만든다")
        finally:
            self._db = old
            new.close()
            tmp.unlink(missing_ok=True)
        if self._skipped:
            log.warning("색인 다시 만들기: 파일 %d개를 건너뛰었다(위 경로들)", len(self._skipped))
        return list(self._skipped)

    def _guard(self, path: Path, fn: Callable[..., Any], *args: Any) -> Any:
        """파일 하나(또는 한 덩어리)를 색인한다. 실패하면 그것만 되돌리고 건너뛴다 — 경로와 오류 종류만 남긴다(내용은 남기지 않는다)."""
        self._db.execute("SAVEPOINT one_file")
        try:
            return fn(*args)
        except Exception as e:  # noqa: BLE001 — 깨진 파일 하나 때문에 나머지 색인이 멈추지 않게
            self._db.execute("ROLLBACK TO one_file")
            rel = path.relative_to(self.root).as_posix() if path.is_relative_to(self.root) else path.name
            self._skipped.append(rel)
            log.warning("색인 건너뜀: %s (%s)", rel, type(e).__name__)
            return None
        finally:
            self._db.execute("RELEASE one_file")

    def _index_user(self, user_id: str, udir: Path) -> None:
        self._db.execute("INSERT OR IGNORE INTO users (id) VALUES (?)", (user_id,))
        for project_json in sorted((udir / "projects").glob("*/project.json")):
            self._guard(project_json, self._reindex_project, user_id, project_json.parent)
        self._guard(udir / "shelf" / "melchior", self._reindex_shelf, user_id)
        self._guard(udir / "shelf" / "categories", self._reindex_categories, user_id)
        self._guard(udir / "shelf" / "documents", self._reindex_documents, user_id)

    @_locked
    def _reindex_user(self, user_id: str) -> None:
        """한 사용자의 색인만 파일에서 다시(프로젝트 휴지통·되살리기, 2026-10-09). 다른 사용자의 색인은 그대로."""
        db = self._db
        existing = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        with db:
            ids = [r[0] for r in db.execute("SELECT id FROM chunks WHERE user_id = ?", (user_id,))]
            for n in range(0, len(ids), 500):
                part = ids[n : n + 500]
                db.execute(f"DELETE FROM chunks_fts WHERE rowid IN ({','.join('?' * len(part))})", part)
            for table in reversed(TABLES):
                if table not in ("users", "chunks_fts") and table in existing:
                    db.execute(f"DELETE FROM {table} WHERE user_id = ?", (user_id,))
            self._index_user(user_id, self._user_dir(user_id))

    def _reindex_project(self, user_id: str, pdir: Path) -> None:
        project_id = pdir.name
        data = _read_json(pdir / "project.json")
        created = data.get("created_at") or utcnow()
        self._index_project(user_id, project_id, data.get("title") or project_id, created, data)
        self._index_parts(user_id, project_id, [Part(int(p["number"]), p["title"]) for p in data.get("parts", [])])
        chapter_ids = {}
        for f in sorted((pdir / "book").glob("ch-*.md")):
            if m := _CHAPTER_FILE.fullmatch(f.name):
                if int(m.group(1)) > CHAPTER_NUMBER_MAX:  # 범위 밖 번호(2026-10-09 점검 15-1): 색인에 넣지 않는다(파일은 그대로)
                    self._guard(f, _out_of_range, f.name)
                    continue
                if (cid := self._guard(f, self._index_chapter, user_id, project_id, int(m.group(1)), f)) is not None:
                    chapter_ids[int(m.group(1))] = cid
        for f in sorted((pdir / "versions").glob("ch-*.v*.md")):
            m = _VERSION_FILE.fullmatch(f.name)
            if m and int(m.group(1)) in chapter_ids:
                self._guard(f, self._index_version, user_id, chapter_ids[int(m.group(1))], f)
        self._index_decisions(user_id, project_id, formats.parse_decisions(_read_text(pdir / "decisions.md")))
        self._index_issues(user_id, project_id, formats.parse_issues(_read_text(pdir / "issues.md")))
        latest = self._db.execute(
            """
            SELECT MAX(t) FROM (
                SELECT updated_at AS t FROM chapters WHERE user_id = ?1 AND project_id = ?2
                UNION ALL SELECT created_at FROM decisions WHERE user_id = ?1 AND project_id = ?2
                UNION ALL SELECT created_at FROM issues WHERE user_id = ?1 AND project_id = ?2
            )
            """,
            (user_id, project_id),
        ).fetchone()[0]
        if latest:
            self._touch(user_id, project_id, latest)

    def _touch(self, user_id: str, project_id: str, at: str) -> None:
        self._db.execute(
            "UPDATE projects SET updated_at = MAX(updated_at, ?) WHERE user_id = ? AND id = ?",
            (at, user_id, project_id),
        )

    def _index_project(
        self, user_id: str, project_id: str, title: str, created_at: str, extra: dict | None = None
    ) -> None:
        extra = extra or {}
        color = extra.get("color") if isinstance(extra.get("color"), str) and HEX.fullmatch(extra["color"]) else None
        self._db.execute("INSERT OR IGNORE INTO users (id) VALUES (?)", (user_id,))
        self._db.execute(
            "INSERT INTO projects (id, user_id, title, subtitle, title_en, subtitle_en, created_at, updated_at, color, contexts)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (project_id, user_id, title, extra.get("subtitle"), extra.get("title_en"), extra.get("subtitle_en"),
             created_at, created_at, color, json.dumps(to_record(from_record(extra.get("contexts"))), ensure_ascii=False)),
        )

    def _index_parts(self, user_id: str, project_id: str, parts: list[Part]) -> None:
        self._db.executemany(
            "INSERT INTO parts (user_id, project_id, number, title) VALUES (?, ?, ?, ?)",
            [(user_id, project_id, p.number, p.title) for p in parts],
        )

    def _index_chapter(self, user_id: str, project_id: str, number: int, path: Path) -> int:
        meta, body = formats.parse_chapter(path.read_text(encoding="utf-8"))
        return self._db.execute(
            """
            INSERT INTO chapters
                (user_id, project_id, number, label, title, status, part_number, path, char_count, version, last_note,
                 updated_at, edition)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (user_id, project_id, number) DO UPDATE SET
                label = excluded.label, title = excluded.title, status = excluded.status,
                part_number = excluded.part_number, path = excluded.path, char_count = excluded.char_count,
                version = excluded.version, last_note = excluded.last_note, updated_at = excluded.updated_at,
                edition = excluded.edition
            RETURNING id
            """,
            (
                user_id,
                project_id,
                number,
                meta.get("label") or None,
                meta.get("title") or f"제{number}장",
                meta.get("status") or "draft",
                _int(meta.get("part_number")),
                self._rel(path),
                len(body),
                _int(meta.get("version"), 1),
                meta.get("last_note", ""),
                meta.get("updated_at") or _mtime(path),
                _int(meta.get("edition")),
            ),
        ).fetchone()[0]

    def _index_version(self, user_id: str, chapter_id: int, path: Path) -> None:
        meta, _ = formats.parse_chapter(path.read_text(encoding="utf-8"))
        m = _VERSION_FILE.fullmatch(path.name)
        assert m, path
        self._db.execute(
            "INSERT OR REPLACE INTO chapter_versions (user_id, chapter_id, version, path, note, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, chapter_id, int(m.group(2)), self._rel(path), meta.get("last_note", ""),
             meta.get("updated_at") or _mtime(path)),
        )

    def _index_decisions(self, user_id: str, project_id: str, decisions: list[Decision]) -> None:
        self._db.executemany(
            "INSERT OR REPLACE INTO decisions (user_id, project_id, id, text, created_at) VALUES (?, ?, ?, ?, ?)",
            [(user_id, project_id, d.id, d.text, d.created_at) for d in decisions],
        )

    def _index_issues(self, user_id: str, project_id: str, issues: list[Issue]) -> None:
        self._db.executemany(
            "INSERT OR REPLACE INTO issues "
            "(user_id, project_id, id, text, status, origin, chapter_number, created_at, closed_note, kind, ref_key, "
            "ref_id, author, author_kind, comment_date, anchor, paragraph, comment_fp, stale, stale_edition) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (user_id, project_id, i.id, i.text, i.status, i.origin, i.chapter_number, i.created_at, i.closed_note,
                 i.kind, i.ref_key, i.ref_id, i.author, i.author_kind, i.comment_date, i.anchor, i.paragraph,
                 i.comment_fp, i.stale, i.stale_edition)
                for i in issues
            ],
        )


def _inbox_entry(path: Path) -> InboxFile:
    stat = path.stat()
    modified = datetime.fromtimestamp(stat.st_mtime, tz=UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    return InboxFile(path.name, stat.st_size, modified)


def _project(r: sqlite3.Row) -> Project:
    return Project(
        r["id"], r["user_id"], r["title"], r["created_at"], r["updated_at"], r["subtitle"], r["title_en"], r["subtitle_en"],
        r["color"], from_record(json.loads(r["contexts"] or "[]")),
    )


def _title_fields(titles: BookTitles) -> dict[str, str]:
    """project.json에 둘 부제·영문 제목·영문 부제(있는 것만)."""
    return {k: v for k, v in (("subtitle", titles.subtitle), ("title_en", titles.title_en), ("subtitle_en", titles.subtitle_en)) if v}


def _chapter_meta(r: sqlite3.Row) -> ChapterMeta:
    return ChapterMeta(
        number=r["number"],
        title=r["title"],
        status=r["status"],
        part_number=r["part_number"],
        char_count=r["char_count"],
        unverified_cite_count=r["unverified_cite_count"],
        version=r["version"],
        last_note=r["last_note"],
        updated_at=r["updated_at"],
        label=r["label"],
        unverified_cite_keys=tuple(json.loads(r["unverified_cite_keys"])),
        uncertain_cite_keys=tuple(json.loads(r["uncertain_cite_keys"])),
        edition=r["edition"],
    )


def _out_of_range(name: str) -> None:
    raise ValueError(f"장 번호가 범위(0~{CHAPTER_NUMBER_MAX:,}) 밖이다: {name}")
