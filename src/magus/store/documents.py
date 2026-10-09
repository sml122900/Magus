"""문서 책 저장(사용자 결정 #94, 2026-10-07). LocalStore에 섞어 쓰는 믹스인이다.

문서 책은 원고에서 만든 읽기용 문서다(첫 종류: 출처 확인 문서). 그 시점의 사진이라 다시 만들면 새 판이 생기고 이전 판은 이력으로 남는다.
원본(사람이 읽는 파일):
  data/users/<user_id>/shelf/documents/<id>/document.json   # 제목·종류·층·기준 원고·색·판 목록(판마다 만든 시각·기준 수정본·만든 방법·수치)
  data/users/<user_id>/shelf/documents/<id>/v1.md, v2.md …  # 판마다 내용(markdown)
휴지통: data/users/<user_id>/trash/shelf/documents/<id>/ (통째로 옮긴다)
인덱스: documents 행과 웹 책장 검색 전용 청크(레인 document, 지금 판 내용).
공용 층에는 둘 수 없다(공용 층에는 모음 책만, #94).
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import threading
from collections.abc import Callable, Iterable
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

from magus.category.rules import HEX
from magus.contexts import from_record, to_record
from magus.floors import COMMON
from magus.ids import new_id, safe_id, utcnow
from magus.store.base import DocVersion, Document
from magus.store.fileio import locked, read_json, read_text, write_json, write_text
from magus.textindex import chunk_text

DOCUMENT_SCHEMA = 1


class DocumentMixin:
    root: Path
    _db: sqlite3.Connection
    _lock: threading.RLock
    _user_dir: Callable[[str], Path]
    _replace_chunks: Callable[..., None]
    _guard: Callable[..., object]  # LocalStore: 파일 하나 색인, 실패하면 그것만 건너뜀(2026-10-09)
    _drop_chunks: Callable[[str, str, str], None]
    _layout: Callable[[str], Any]
    _known: Callable[[str, Any], set[str]]
    _check_floor: Callable[[str, Any, str], str]

    def _documents_dir(self, user_id: str) -> Path:
        return self._user_dir(user_id) / "shelf" / "documents"

    def _document_dir(self, user_id: str, doc_id: str) -> Path:
        return self._documents_dir(user_id) / safe_id(doc_id, "document id")

    @locked
    def create_document(self, user_id: str, doc: Document, content: str, node: str | None = None) -> Document:
        """doc.versions에는 첫 판 하나(내용은 content). 원고가 있는 프로젝트여야 한다(「내 서재」면 ValueError).
        node: 꽂을 노드(#95, 없으면 가운데 노드)."""
        floor = self._check_floor(user_id, self._layout(user_id), doc.floor)
        if floor == COMMON:
            raise ValueError("「내 서재」에는 올린 문서에서 만든 문서를 둘 수 없다(올린 문서가 있는 프로젝트에만)")
        self.ensure_maps(user_id)  # type: ignore[attr-defined]
        if not HEX.fullmatch(doc.color):
            raise ValueError(f"색은 #RRGGBB: {doc.color!r}")
        now = utcnow()
        doc = replace(doc, id=doc.id or new_id(), created_at=now, updated_at=now,
                      versions=tuple(replace(v, number=1, at=v.at or now) for v in doc.versions[:1]))
        ddir = self._document_dir(user_id, doc.id)
        write_text(ddir / "v1.md", content)
        write_json(ddir / "document.json", _record(doc))
        with self._db:
            self._index_document(user_id, doc, content)
        self._persist_map(user_id, floor, {f"doc.{doc.id}": node} if node else None)  # type: ignore[attr-defined]
        return doc

    @locked
    def add_document_version(self, user_id: str, doc_id: str, version: DocVersion, content: str) -> Document:
        """다시 만들기: 새 판을 더한다(이전 판 파일은 그대로 이력으로 남는다)."""
        current = self.get_document(user_id, doc_id)
        if current is None:
            raise ValueError(f"문서 {doc_id}가 없다")
        now = utcnow()
        number = current.versions[-1].number + 1
        doc = replace(current, updated_at=now, versions=(*current.versions, replace(version, number=number, at=version.at or now)))
        ddir = self._document_dir(user_id, doc_id)
        write_text(ddir / f"v{number}.md", content)
        write_json(ddir / "document.json", {**read_json(ddir / "document.json"), **_record(doc)})
        with self._db:
            self._index_document(user_id, doc, content)
        return doc

    @locked
    def get_document(self, user_id: str, doc_id: str) -> Document | None:
        try:
            path = self._document_dir(user_id, doc_id) / "document.json"
        except ValueError:
            return None
        row = self._db.execute("SELECT 1 FROM documents WHERE user_id = ? AND id = ?", (user_id, doc_id)).fetchone()
        return _document(read_json(path), path.parent.name) if row and path.exists() else None

    @locked
    def list_documents(self, user_id: str, *, floors: Iterable[str] | None = None, project_id: str | None = None) -> list[Document]:
        sql, args = "SELECT id FROM documents WHERE user_id = ?", [user_id]
        if floors is not None:
            values = list(dict.fromkeys(floors))
            sql += f" AND floor IN ({','.join('?' * len(values))})" if values else " AND 0"
            args += values
        if project_id is not None:
            sql, args = sql + " AND project_id = ?", [*args, project_id]
        out = []
        for (doc_id,) in self._db.execute(sql + " ORDER BY created_at, id", args).fetchall():
            if found := self.get_document(user_id, doc_id):
                out.append(found)
        return out

    @locked
    def read_document(self, user_id: str, doc_id: str, number: int | None = None) -> str | None:
        """판의 내용(markdown). number가 없으면 지금 판."""
        doc = self.get_document(user_id, doc_id)
        if doc is None:
            return None
        number = number or doc.versions[-1].number
        if not any(v.number == number for v in doc.versions):
            return None
        return read_text(self._document_dir(user_id, doc_id) / f"v{number}.md")

    @locked
    def update_document(self, user_id: str, doc_id: str, *, title: str | None = None, color: str | None = None,
                        title_by: str | None = None) -> Document:
        doc = self.get_document(user_id, doc_id)
        if doc is None:
            raise ValueError(f"문서 {doc_id}가 없다")
        if color is not None and not HEX.fullmatch(color):
            raise ValueError(f"색은 #RRGGBB: {color!r}")
        changed = replace(doc, title=title or doc.title, title_by=title_by if title else doc.title_by,  # type: ignore[arg-type]
                          color=(color or doc.color).lower(), updated_at=utcnow())
        path = self._document_dir(user_id, doc_id) / "document.json"
        write_json(path, {**read_json(path), **_record(changed)})
        with self._db:
            self._index_document(user_id, changed, read_text(path.parent / f"v{changed.versions[-1].number}.md"))
        return changed

    def _set_document_floor(self, user_id: str, doc_id: str, floor: str, at: str) -> None:
        path = self._document_dir(user_id, doc_id) / "document.json"
        write_json(path, {**read_json(path), "floor": floor, "updated_at": at})
        with self._db:
            self._db.execute("UPDATE documents SET floor = ?, updated_at = ? WHERE user_id = ? AND id = ?", (floor, at, user_id, doc_id))

    @locked
    def trash_document(self, user_id: str, doc_id: str, note: str) -> Document | None:
        doc = self.get_document(user_id, doc_id)
        if doc is None:
            return None
        target = self._user_dir(user_id) / "trash" / "shelf" / "documents" / doc_id
        if target.exists():
            target.rename(target.with_name(f"{doc_id}-{utcnow().replace(':', '').replace('.', '')}"))
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(self._document_dir(user_id, doc_id)), str(target))
        write_json(target / "document.json", {**read_json(target / "document.json"), "_trash": {"at": utcnow(), "note": note}})
        with self._db:
            self._db.execute("DELETE FROM documents WHERE user_id = ? AND id = ?", (user_id, doc_id))
            self._drop_chunks(user_id, "document", doc_id)
        return doc

    def _index_document(self, user_id: str, doc: Document, content: str) -> None:
        current = doc.versions[-1]
        self._db.execute(
            "INSERT OR REPLACE INTO documents (id, user_id, floor, title, doc_type, project_id, color, edition, versions, created_at, updated_at,"
            " contexts) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (doc.id, user_id, doc.floor, doc.title, doc.doc_type, doc.project_id, doc.color, current.edition, len(doc.versions),
             doc.created_at, doc.updated_at, json.dumps(to_record(doc.contexts), ensure_ascii=False)),
        )
        self._replace_chunks(user_id, "document", doc.id, "document", chunk_text(f"{doc.title}\n{content}"))

    def _reindex_documents(self, user_id: str) -> None:
        known = self._known(user_id, self._layout(user_id))
        for path in sorted(self._documents_dir(user_id).glob("*/document.json")):  # 깨진 문서는 그것만 건너뛴다(2026-10-09 점검 12-b)
            self._guard(path, self._reindex_document, user_id, path, known)

    def _reindex_document(self, user_id: str, path: Path, known: set[str]) -> None:
        doc = _document(read_json(path), path.parent.name)
        if doc.floor not in known or doc.floor == COMMON:  # 사라진 층이면 기준 원고의 층으로(그것도 없으면 색인만 건너뛴다)
            if doc.project_id not in known:
                return
            doc = replace(doc, floor=doc.project_id)
        self._index_document(user_id, doc, read_text(path.parent / f"v{doc.versions[-1].number}.md"))


def _record(doc: Document) -> dict[str, Any]:
    return {"schema_version": DOCUMENT_SCHEMA, "id": doc.id, "title": doc.title, "title_by": doc.title_by, "doc_type": doc.doc_type,
            "floor": doc.floor, "project_id": doc.project_id, "color": doc.color, "created_at": doc.created_at,
            "updated_at": doc.updated_at, "versions": [asdict(v) | {"stats": dict(v.stats)} for v in doc.versions],
            "contexts": to_record(doc.contexts)}


def _document(r: dict[str, Any], folder: str) -> Document:
    versions = tuple(
        DocVersion(int(v.get("number") or n), str(v.get("at") or ""), v.get("edition"), str(v.get("method") or "server"),
                   v.get("preface_by") if v.get("preface_by") in ("ai", "author") else None,
                   {str(k): int(x) for k, x in (v.get("stats") or {}).items() if isinstance(x, int)})
        for n, v in enumerate(r.get("versions") or [], 1)
    ) or (DocVersion(1, str(r.get("created_at") or ""), None, "server"),)
    color = str(r.get("color") or "")
    return Document(
        id=folder, title=str(r.get("title") or "문서"), title_by=r.get("title_by") if r.get("title_by") in ("ai", "author") else None,
        doc_type=str(r.get("doc_type") or "source_check"), floor=str(r.get("floor") or ""), project_id=str(r.get("project_id") or ""),
        color=color.lower() if HEX.fullmatch(color) else "#5b5f66", created_at=str(r.get("created_at") or ""),
        updated_at=str(r.get("updated_at") or r.get("created_at") or ""), versions=versions,
        contexts=from_record(r.get("contexts")),
    )

