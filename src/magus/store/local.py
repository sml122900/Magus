"""P0 저장소. 원본은 data/users/<user_id>/… 아래의 md/json 파일이고, data/index.sqlite는 인덱스다.

쓰기 순서는 항상 '파일 먼저, 인덱스 나중'이다. 인덱스가 어긋나면 reindex()로 파일에서 다시 만든다.
"""

from __future__ import annotations

import functools
import json
import logging
import os
import re
import secrets
import shutil
import sqlite3
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar

from magus.ids import safe_id, utcnow
from magus.store import formats
from magus.store.base import (
    Change,
    ChapterMeta,
    Decision,
    Issue,
    IssueOrigin,
    IssueStatus,
    Part,
    Project,
)
from magus.store.schema import SCHEMA, SCHEMA_VERSION, TABLES

log = logging.getLogger("magus.store")

_CHAPTER_FILE = re.compile(r"ch-(\d+)\.md")
_VERSION_FILE = re.compile(r"ch-(\d+)\.v(\d+)\.md")

F = TypeVar("F", bound=Callable[..., Any])


def _locked(fn: F) -> F:
    # MCPServer는 동기 도구를 워커 스레드에서 돌린다. 파일+인덱스 갱신을 한 덩어리로 묶는다.
    @functools.wraps(fn)
    def wrapper(self: LocalStore, *args: Any, **kwargs: Any) -> Any:
        with self._lock:
            return fn(self, *args, **kwargs)

    return wrapper  # type: ignore[return-value]


class LocalStore:
    def __init__(self, data_dir: Path):
        self.root = Path(data_dir)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(self.root / "index.sqlite", check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        if self._db.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
            log.info("인덱스 스키마 v%s 생성 → 파일에서 재생성", SCHEMA_VERSION)
            self.reindex()

    def close(self) -> None:
        self._db.close()

    # ---- 경로 ------------------------------------------------------------------------

    def _user_dir(self, user_id: str) -> Path:
        return self.root / "users" / safe_id(user_id, "user_id")

    def _project_dir(self, user_id: str, project_id: str) -> Path:
        return self._user_dir(user_id) / "projects" / safe_id(project_id, "project_id")

    def _require_project(self, user_id: str, project_id: str) -> Path:
        pdir = self._project_dir(user_id, project_id)
        if not (pdir / "project.json").exists():
            raise ValueError(f"프로젝트 {project_id!r}가 없다")
        return pdir

    def _rel(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    # ---- 프로젝트 --------------------------------------------------------------------

    @_locked
    def create_project(self, user_id: str, title: str, project_id: str | None = None) -> Project:
        project_id = safe_id(project_id or secrets.token_hex(4), "project_id")
        pdir = self._project_dir(user_id, project_id)
        if (pdir / "project.json").exists():
            raise ValueError(f"프로젝트 {project_id!r}가 이미 있다")
        now = utcnow()
        for sub in ("book", "versions", "original"):
            (pdir / sub).mkdir(parents=True, exist_ok=True)
        _write_json(pdir / "project.json", {"title": title, "created_at": now, "parts": []})
        with self._db:
            self._index_project(user_id, project_id, title, now)
        return Project(project_id, user_id, title, now, now)

    @_locked
    def get_project(self, user_id: str, project_id: str | None = None) -> Project | None:
        sql, args = "SELECT * FROM projects WHERE user_id = ?", [user_id]
        if project_id:
            sql, args = sql + " AND id = ?", [*args, project_id]
        row = self._db.execute(sql + " ORDER BY updated_at DESC, created_at DESC LIMIT 1", args).fetchone()
        if not row:
            return None
        return Project(row["id"], row["user_id"], row["title"], row["created_at"], row["updated_at"])

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
        return [_chapter_meta(r) for r in rows]

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
        status: str | None = None,
        part: int | None = None,
    ) -> ChapterMeta:
        if number < 0:
            raise ValueError("장 번호는 0 이상")
        # 메타는 서버가 관리한다. 호출자가 front matter를 붙여 보내도 버리고 본문만 쓴다.
        _, content = formats.parse_chapter(content)
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
            "title": title or prev.get("title") or f"제{number}장",
            "status": status or prev.get("status") or "draft",
            "part": part if part is not None else _int(prev.get("part")),
            "version": _int(prev.get("version"), 1) + 1 if old is not None else 1,
            "updated_at": now,
            "note": note,
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
    def recent_changes(self, user_id: str, project_id: str, limit: int = 5) -> list[Change]:
        rows = self._db.execute(
            """
            SELECT number, version, note, updated_at AS at
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
        decision = Decision(max((d.id for d in decisions), default=0) + 1, text.strip(), utcnow())
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
    ) -> Issue:
        if not text.strip():
            raise ValueError("미해결 내용이 비어 있다")
        path = self._require_project(user_id, project_id) / "issues.md"
        issues = formats.parse_issues(_read_text(path))
        issue = Issue(
            id=max((i.id for i in issues), default=0) + 1,
            text=text.strip(),
            status="open",
            origin=origin,
            chapter_number=chapter_number,
            created_at=utcnow(),
        )
        _write_text(path, formats.dump_issues([*issues, issue]))
        with self._db:
            self._index_issues(user_id, project_id, [issue])
            self._touch(user_id, project_id, issue.created_at)
        return issue

    @_locked
    def list_issues(
        self, user_id: str, project_id: str, status: IssueStatus | None = "open"
    ) -> list[Issue]:
        sql, args = "SELECT * FROM issues WHERE user_id = ? AND project_id = ?", [user_id, project_id]
        if status:
            sql, args = sql + " AND status = ?", [*args, status]
        rows = self._db.execute(sql + " ORDER BY id", args)
        return [
            Issue(r["id"], r["text"], r["status"], r["origin"], r["chapter_number"], r["created_at"], r["closed_note"])
            for r in rows
        ]

    # ---- 인덱스 ----------------------------------------------------------------------

    @_locked
    def reindex(self) -> None:
        db = self._db
        for table in reversed(TABLES):
            db.execute(f"DROP TABLE IF EXISTS {table}")
        db.executescript(SCHEMA)
        users_dir = self.root / "users"
        with db:
            for udir in sorted(users_dir.iterdir()) if users_dir.is_dir() else []:
                if not udir.is_dir():
                    continue
                db.execute("INSERT OR IGNORE INTO users (id) VALUES (?)", (udir.name,))
                for project_json in sorted((udir / "projects").glob("*/project.json")):
                    self._reindex_project(udir.name, project_json.parent)
        db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def _reindex_project(self, user_id: str, pdir: Path) -> None:
        project_id = pdir.name
        data = _read_json(pdir / "project.json")
        created = data.get("created_at") or utcnow()
        self._index_project(user_id, project_id, data.get("title") or project_id, created)
        self._index_parts(user_id, project_id, [Part(int(p["number"]), p["title"]) for p in data.get("parts", [])])
        chapter_ids = {}
        for f in sorted((pdir / "book").glob("ch-*.md")):
            if m := _CHAPTER_FILE.fullmatch(f.name):
                chapter_ids[int(m.group(1))] = self._index_chapter(user_id, project_id, int(m.group(1)), f)
        for f in sorted((pdir / "versions").glob("ch-*.v*.md")):
            m = _VERSION_FILE.fullmatch(f.name)
            if m and int(m.group(1)) in chapter_ids:
                self._index_version(user_id, chapter_ids[int(m.group(1))], f)
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

    def _index_project(self, user_id: str, project_id: str, title: str, created_at: str) -> None:
        self._db.execute("INSERT OR IGNORE INTO users (id) VALUES (?)", (user_id,))
        self._db.execute(
            "INSERT INTO projects (id, user_id, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (project_id, user_id, title, created_at, created_at),
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
                (user_id, project_id, number, title, status, part, path, char_count, version, note, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (user_id, project_id, number) DO UPDATE SET
                title = excluded.title, status = excluded.status, part = excluded.part,
                path = excluded.path, char_count = excluded.char_count, version = excluded.version,
                note = excluded.note, updated_at = excluded.updated_at
            RETURNING id
            """,
            (
                user_id,
                project_id,
                number,
                meta.get("title") or f"제{number}장",
                meta.get("status") or "draft",
                _int(meta.get("part")),
                self._rel(path),
                len(body),
                _int(meta.get("version"), 1),
                meta.get("note", ""),
                meta.get("updated_at") or _mtime(path),
            ),
        ).fetchone()[0]

    def _index_version(self, user_id: str, chapter_id: int, path: Path) -> None:
        meta, _ = formats.parse_chapter(path.read_text(encoding="utf-8"))
        m = _VERSION_FILE.fullmatch(path.name)
        assert m, path
        self._db.execute(
            "INSERT OR REPLACE INTO chapter_versions (user_id, chapter_id, version, path, note, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, chapter_id, int(m.group(2)), self._rel(path), meta.get("note", ""),
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
            "(user_id, project_id, id, text, status, origin, chapter_number, created_at, closed_note) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (user_id, project_id, i.id, i.text, i.status, i.origin, i.chapter_number, i.created_at, i.closed_note)
                for i in issues
            ],
        )


# ---- 파일 유틸 -------------------------------------------------------------------------


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _write_text(path: Path, text: str) -> None:
    # 원본 파일이 반쯤 쓰인 채로 남지 않도록 임시 파일에 쓴 뒤 교체한다.
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: dict[str, Any]) -> None:
    _write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def _mtime(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _int(value: str | None, default: int | None = None) -> int | None:
    try:
        return int(value) if value not in (None, "") else default
    except ValueError:
        return default


def _chapter_meta(r: sqlite3.Row) -> ChapterMeta:
    return ChapterMeta(
        number=r["number"],
        title=r["title"],
        status=r["status"],
        part=r["part"],
        char_count=r["char_count"],
        unverified_cite_count=r["unverified_cite_count"],
        version=r["version"],
        note=r["note"],
        updated_at=r["updated_at"],
    )
