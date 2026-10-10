"""프로젝트 휴지통(2026-10-09 구조·버그 점검 3번). 지금까지는 프로젝트를 없앨 길이 없었다.

- 옮기는 것(지우지 않는다): 프로젝트 폴더(올린 문서·수정본·확인 요청·결정), 지도, 그 프로젝트의 책(글·첨부)·문헌 글·문서,
  그 프로젝트의 휴지통 기록(노드·글·첨부·책). 모두 사용자 폴더 안 `trash/projects/<프로젝트>-<시각>/files/`로, 옮긴 목록은 같은 폴더의
  manifest.json에. 파일 내용은 그대로라 되살리면 바이트까지 같다. floors.json(프로젝트 순서)은 건드리지 않는다(되살리면 그 자리).
- 휴지통에 있는 동안 색인에서 빠지므로 검색·전체 현황·MCP·숫자에 보이지 않는다(옮긴 뒤 그 사용자 색인만 다시 만든다).
- 막는 경우: 다른 프로젝트의 연결 노드가 이 프로젝트의 노드를 가리킬 때(그 프로젝트 이름을 보인다).
  「내 서재」(옛 공용 층)도 2026-10-11부터 보통 프로젝트라 같은 규칙이다(올린 문서가 없으므로 지도·책·문헌·문서만 옮긴다).
- 되살리기를 막는 경우: 같은 id의 프로젝트가 그사이 생겼을 때, 프로젝트가 가득 찼을 때, 같은 책·문헌·문서 폴더가 그사이 생겼을 때.
- 옛 코드는 trash/projects/를 읽지 않는다. 옛 코드가 보면 그 프로젝트는 그냥 없다(순서에만 자리가 남는다).
"""

from __future__ import annotations

import re
import shutil
import sqlite3
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from magus.floors import MAX_FLOORS
from magus.ids import safe_id, utcnow
from magus.store.base import ProjectTrashInfo, TrashedProject
from magus.store.fileio import locked, read_json, write_json

MANIFEST = "manifest.json"


class ProjectTrashMixin:
    root: Path
    _db: sqlite3.Connection
    _lock: threading.RLock
    _user_dir: Callable[[str], Path]
    _reindex_user: Callable[[str], None]
    list_floors: Callable[..., Any]
    get_map: Callable[..., Any]
    _layout: Callable[[str], Any]
    _known_floors: Callable[..., list[str]]
    _reconcile: Callable[..., Any]
    _floor_title: Callable[[str, str], str | None]

    def _project_trash_root(self, user_id: str) -> Path:
        return self._user_dir(user_id) / "trash" / "projects"

    def _project_parts(self, user_id: str, project_id: str) -> tuple[list[str], list[str], list[str], list[str]]:
        """(옮길 상대 경로들, 책 id, 문헌 key, 문서 id). 상대 경로는 사용자 폴더 기준이고, 지금 있는 것만."""
        udir = self._user_dir(user_id)
        cats = [r[0] for r in self._db.execute("SELECT id FROM categories WHERE user_id = ? AND floor = ? ORDER BY id",
                                               (user_id, project_id))]
        refs = [r[0] for r in self._db.execute("SELECT key FROM refs WHERE user_id = ? AND floor = ? ORDER BY key", (user_id, project_id))]
        docs = [r[0] for r in self._db.execute("SELECT id FROM documents WHERE user_id = ? AND floor = ? ORDER BY id",
                                               (user_id, project_id))]
        paths = [f"projects/{project_id}", f"shelf/maps/{project_id}.json"]
        paths += [f"shelf/categories/{c}" for c in cats] + [f"shelf/melchior/{k}" for k in refs] + [f"shelf/documents/{d}" for d in docs]
        paths += [f"trash/shelf/nodes/{project_id}"]
        paths += [f"trash/shelf/category-items/{c}" for c in cats] + [f"trash/shelf/attachments/{c}" for c in cats]
        paths += [f"trash/shelf/attachments/ref/{k}" for k in refs]
        for meta in sorted((udir / "trash" / "shelf" / "categories").glob("*/category.json")):  # 이 프로젝트에서 책째 버린 책
            if read_json(meta).get("floor") == project_id:
                paths.append(f"trash/shelf/categories/{meta.parent.name}")
        found = [p for p in paths if (udir / p).exists()]
        found = [p for p in found if not any(p.startswith(q + "/") for q in found)]  # 이미 담긴 폴더 안의 것은 한 번만
        return found, cats, refs, docs

    def _linked_into(self, user_id: str, project_id: str) -> list[str]:
        """이 프로젝트의 노드를 가리키는 연결 노드가 있는 다른 프로젝트의 이름."""
        layout = self._layout(user_id)
        out = []
        for other in self._known_floors(user_id, layout):
            if other != project_id and any((n.get("link") or {}).get("project") == project_id
                                           for n in self._reconcile(user_id, other, layout)[0]["nodes"]):
                out.append(self._floor_title(user_id, other) or other)
        return out

    def _counts(self, user_id: str, project_id: str, cats: list[str]) -> tuple[int, int, int]:
        """(글 수, 장 수, 수정본 수)."""
        items = sum(int(self._db.execute("SELECT COUNT(*) FROM category_items WHERE user_id = ? AND category_id = ?",
                                         (user_id, c)).fetchone()[0]) for c in cats)
        chapters = int(self._db.execute("SELECT COUNT(*) FROM chapters WHERE user_id = ? AND project_id = ?",
                                        (user_id, project_id)).fetchone()[0])
        pj = self._user_dir(user_id) / "projects" / project_id / "project.json"
        editions = read_json(pj).get("editions") or [] if pj.exists() else []
        revisions = sum(1 for e in editions if isinstance(e, dict) and int(e.get("number") or 0) >= 2)
        return items, chapters, revisions

    @locked
    def project_trash_info(self, user_id: str, project_id: str) -> ProjectTrashInfo | None:
        floor = next((f for f in self.list_floors(user_id) if f.id == project_id), None)
        if floor is None:
            return None
        _, cats, refs, _ = self._project_parts(user_id, project_id)
        items, chapters, revisions = self._counts(user_id, project_id, cats)
        shown = self.get_map(user_id, project_id)
        linked = tuple(self._linked_into(user_id, project_id))
        return ProjectTrashInfo(project_id, floor.title, len(shown.nodes) if shown else 0, len(cats), items, len(refs), chapters,
                                revisions, "linked" if linked else None, linked)

    @locked
    def trash_project(self, user_id: str, project_id: str, note: str) -> str:
        """프로젝트를 통째로 휴지통으로. 휴지통 id(폴더 이름)를 돌려준다. 막히면 ValueError(code, 보일 이름)."""
        info = self.project_trash_info(user_id, project_id)
        if info is None:
            raise ValueError("missing", "")
        if info.blocked:
            raise ValueError(info.blocked, "·".join(f"「{x}」" for x in info.linked_from))
        udir = self._user_dir(user_id)
        paths, cats, refs, docs = self._project_parts(user_id, project_id)
        stamp = re.sub(r"[^0-9]", "", utcnow())
        trash_id = f"{safe_id(project_id, 'project_id')}-{stamp}"
        bundle = self._project_trash_root(user_id) / trash_id
        files = bundle / "files"
        manifest = {"project_id": project_id, "title": info.title, "at": utcnow(), "note": note, "paths": paths,
                    "categories": cats, "refs": refs, "documents": docs, "chapters": info.chapters, "revisions": info.revisions,
                    "items": info.items}
        write_json(bundle / MANIFEST, {**manifest, "state": "moving"})  # 먼저 적고 옮긴다(중간에 멈춰도 무엇을 옮겼는지 남게)
        for rel in paths:
            target = files / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(udir / rel), str(target))
        write_json(bundle / MANIFEST, manifest)
        self._reindex_user(user_id)
        return trash_id

    @locked
    def list_trashed_projects(self, user_id: str) -> list[TrashedProject]:
        out = []
        for path in sorted(self._project_trash_root(user_id).glob(f"*/{MANIFEST}")):
            data = read_json(path)
            out.append(TrashedProject(path.parent.name, str(data.get("project_id") or ""), str(data.get("title") or ""),
                                      str(data.get("at") or ""), int(data.get("chapters") or 0), int(data.get("revisions") or 0),
                                      len(data.get("categories") or []), int(data.get("items") or 0)))
        return sorted(out, key=lambda t: t.trashed_at, reverse=True)

    @locked
    def restore_project(self, user_id: str, trash_id: str) -> str:
        """휴지통의 프로젝트를 제자리로. 프로젝트 id를 돌려준다. 막히면 아무것도 옮기지 않고 ValueError(code, 보일 이름).
        code: missing | taken(같은 id의 프로젝트) | full(프로젝트 가득) | clash(같은 책·문헌·문서가 그사이 생김)."""
        safe_id(trash_id, "trash id")
        bundle = self._project_trash_root(user_id) / trash_id
        if not (bundle / MANIFEST).exists():
            raise ValueError("missing", "")
        data = read_json(bundle / MANIFEST)
        project_id = str(data.get("project_id") or "")
        udir = self._user_dir(user_id)
        floors = self.list_floors(user_id)
        if any(f.id == project_id for f in floors) or (udir / "projects" / project_id).exists():
            raise ValueError("taken", str(data.get("title") or project_id))
        if len(floors) >= MAX_FLOORS:
            raise ValueError("full", "")
        paths = [str(p) for p in data.get("paths") or []]
        for rel in paths:  # 먼저 모두 살핀 뒤 옮긴다(반쯤 되살린 채 남지 않게)
            if ".." in Path(rel).parts or (udir / rel).exists() or not (bundle / "files" / rel).exists():
                raise ValueError("clash", rel.rsplit("/", 1)[-1])
        for rel in paths:
            (udir / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(bundle / "files" / rel), str(udir / rel))
        (bundle / MANIFEST).unlink()
        for folder in sorted((d for d in bundle.rglob("*") if d.is_dir()), key=lambda d: len(d.parts), reverse=True):
            if not any(folder.iterdir()):  # 옮긴 뒤 남은 빈 폴더만 치운다(무엇이 남았으면 그대로 둔다)
                folder.rmdir()
        if bundle.exists() and not any(bundle.iterdir()):
            bundle.rmdir()
        self._reindex_user(user_id)
        return project_id
