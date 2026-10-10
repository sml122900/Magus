"""층(#93) 저장. LocalStore에 섞어 쓰는 믹스인이다.

원본(사람이 읽는 json):
  data/users/<user_id>/shelf/floors.json
    {"schema_version": 1, "order": [프로젝트 id…(위에서 아래로)], "builtins": {층 id: ["ideas"|"styles"|"refs"…]},
     "changed_at": {층 id: 시각(옮기기·층 만들기)}, "last_move": {…마지막 옮기기, 되돌리기용} | null}
항목의 층은 각 파일의 "floor"다(생각·문체 json, 문헌 bib.json, 카테고리 category.json).

floors.json이 없는 사용자(층 이전 전)는 이전 규칙과 같은 배치로 보인다(legacy_layout):
  작업물이 없으면 공용에 생각·문체·문헌, 하나면 공용에 문체·그 층에 생각·문헌,
  둘 이상이면 공용에 문체·문헌(어느 원고의 인용 점검 결과도 바뀌지 않게)·작업물 층마다 생각·문헌.
"floor"가 없는 항목은 위에서부터(공용 먼저) 그 종류가 꽂힌 첫 층에, 저자의 카테고리는 공용에 있는 것으로 본다(fallback).
층 배치를 바꾸는 쓰기(층 만들기·옮기기·기본 카테고리 다시 꽂기) 전에는 그 배치를 파일로 적는다(ensure_layout).
이것은 이전 스크립트(magus floors apply)가 하는 일과 같다. 그래서 이전 전후로 화면·도구·인용 점검이 달라지지 않는다.

#96(컨텍스트): 기본 카테고리가 없어졌다. 이전(magus maps apply)이 옛 기본 카테고리를 여느 책(카테고리)으로 바꾸고 floors.json을
schema_version 2(BOOKS_SCHEMA)로 적는다. 2부터는 "builtins"를 읽지 않는다(모두 비어 있다). 옛 형식을 읽는 코드(legacy_layout·
ensure_layout·floor_plan·revert_floors)는 이전과 되돌리기 때문에 남겨 둔다. 옛 파일이 없는 새 사용자는 처음부터 2다.
"""

from __future__ import annotations

import sqlite3
import threading
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from magus.floors import BOOKS_SCHEMA, BUILTIN_ORDER, COMMON, COMMON_BUILTINS, COMMON_NAME, FLOORS_SCHEMA, NEW_FLOOR_BUILTINS
from magus.ids import new_id, utcnow
from magus.store.base import Floor, FloorMove
from magus.store.fileio import locked, read_json, write_json

KINDS = ("ideas", "styles", "refs")


class MoveError(ValueError):
    """옮기기를 할 수 없는 까닭. code: same | clash | unknown_floor | no_builtin | not_last | undo_clash | unknown_category
    | common_only(공용에는 모음 책만) | fixed(원고 책).
    도구와 웹이 code로 저자에게 보일 문장을 만든다(메시지는 운영자용)."""

    def __init__(self, code: str, message: str, **info: Any):
        super().__init__(message)
        self.code, self.info = code, info


@dataclass
class Layout:
    order: list[str]
    builtins: dict[str, list[str]]
    changed_at: dict[str, str] = field(default_factory=dict)
    last_move: dict[str, Any] | None = None
    last_undone: dict[str, Any] | None = None  # 마지막으로 되돌린 옮기기(웹 안내 한 줄용)
    stored: bool = False  # floors.json이 있나(이전을 마쳤나)
    books: bool = False  # 기본 카테고리가 없는 형식인가(#96, floors.json schema_version 2)

    def kinds(self, floor: str) -> list[str]:
        return [k for k in BUILTIN_ORDER if k in self.builtins.get(floor, [])]

    def fallback(self, kind: str) -> str:
        """"floor"가 없는 항목의 층: 위에서부터(공용 먼저) 그 종류가 꽂힌 첫 층. 저자의 카테고리는 공용."""
        if kind in KINDS:
            for floor in (COMMON, *self.order):
                if kind in self.builtins.get(floor, []):
                    return floor
            return self.order[0] if self.order else COMMON
        return COMMON

    def record(self) -> dict[str, Any]:
        if self.books:  # #96: 기본 카테고리 없음
            return {"schema_version": BOOKS_SCHEMA, "order": self.order, "changed_at": self.changed_at,
                    "last_move": self.last_move, "last_undone": self.last_undone}
        return {"schema_version": FLOORS_SCHEMA, "order": self.order,
                "builtins": {f: self.kinds(f) for f in (COMMON, *self.order)},  # 빈 목록도 적는다(옮겨 비운 층)
                "changed_at": self.changed_at, "last_move": self.last_move, "last_undone": self.last_undone}


def legacy_layout(project_ids: list[str]) -> Layout:
    """이전 전 배치(= 이전 규칙). project_ids는 만든 순서."""
    if not project_ids:
        return Layout([], {COMMON: list(BUILTIN_ORDER)})
    if len(project_ids) == 1:
        return Layout(list(project_ids), {COMMON: list(COMMON_BUILTINS), project_ids[0]: list(NEW_FLOOR_BUILTINS)})
    # 작업물이 둘 이상: 문헌은 공용에 둔다(지금은 문헌이 모든 원고에 함께 쓰이므로, 어느 원고의 인용 점검도 그대로).
    return Layout(list(project_ids), {COMMON: ["styles", "refs"], **{p: list(NEW_FLOOR_BUILTINS) for p in project_ids}})


class FloorMixin:
    root: Path
    _db: sqlite3.Connection
    _lock: threading.RLock
    _user_dir: Callable[[str], Path]

    # ---- 배치 읽기·쓰기 ------------------------------------------------------------------------

    def _floors_path(self, user_id: str) -> Path:
        return self._user_dir(user_id) / "shelf" / "floors.json"

    def _project_ids(self, user_id: str) -> list[str]:
        """만든 순서(인덱스). 층 순서가 없을 때 쓴다."""
        return [r[0] for r in self._db.execute(
            "SELECT id FROM projects WHERE user_id = ? ORDER BY created_at, id", (user_id,))]

    def has_legacy_shelf(self, user_id: str) -> bool:
        """#96 전 형식의 책장 파일이 있나: 생각(shelf/casper)·문체(shelf/balthasar) 파일, 또는 책("book")이 적히지 않은 문헌."""
        shelf = self._user_dir(user_id) / "shelf"
        if next((shelf / "casper").glob("*.json"), None) or next((shelf / "balthasar").glob("*.json"), None):
            return True
        return any("book" not in read_json(p) for p in (shelf / "melchior").glob("*/bib.json"))

    def _layout(self, user_id: str) -> Layout:
        path = self._floors_path(user_id)
        projects = self._project_ids(user_id)
        if not path.exists():
            if self.has_legacy_shelf(user_id):  # 층 이전 전(#93 전) 데이터: 이전 규칙의 배치로 보인다(이전만 쓴다)
                return legacy_layout(projects)
            return Layout(projects, {}, books=True)  # 새 사용자(#96): 기본 카테고리 없음
        data = read_json(path)
        books = int(data.get("schema_version") or 1) >= BOOKS_SCHEMA
        order = [str(p) for p in data.get("order") or [] if isinstance(p, str)]
        order += [p for p in projects if p not in order]  # 옛 코드가 만든 작업물 등 순서에 없는 것은 끝에(기본 카테고리는 없음)
        builtins = {} if books else {str(f): [k for k in BUILTIN_ORDER if k in (v or [])] for f, v in (data.get("builtins") or {}).items()}
        for p in projects:
            if not books and p not in (data.get("order") or []) and p not in builtins:
                builtins[p] = list(NEW_FLOOR_BUILTINS)
        last = data.get("last_move") if isinstance(data.get("last_move"), dict) else None
        undone = data.get("last_undone") if isinstance(data.get("last_undone"), dict) else None
        changed = {str(k): str(v) for k, v in (data.get("changed_at") or {}).items()}
        return Layout(order, builtins, changed, last, undone, True, books)

    def _write_layout(self, user_id: str, layout: Layout) -> None:
        write_json(self._floors_path(user_id), layout.record())
        layout.stored = True

    def _existing(self, user_id: str, layout: Layout) -> list[str]:
        """순서 중 지금 있는 작업물만(휴지통으로 간 작업물의 자리는 남겨 둔다: 같은 id로 다시 가져오면 그 자리)."""
        projects = set(self._project_ids(user_id))
        return [p for p in layout.order if p in projects]

    def _check_floor(self, user_id: str, layout: Layout, floor: str) -> str:
        if floor in self._known(user_id, layout):
            return floor
        raise MoveError("unknown_floor", f"층 {floor!r}가 없다", floor=floor)

    def _has_library(self, user_id: str, layout: Layout) -> bool:
        """「내 서재」(id common, 옛 공용 층)가 있나. 2026-10-11부터 보통 프로젝트라 자동으로 만들지 않는다(새 사용자는 프로젝트 0개).
        지도 파일이 있거나 그 프로젝트에 책·문헌·문서가 있으면(옛 사용자) 있다. #96 전 형식(이전만 쓴다)은 언제나 있다."""
        if not layout.books:
            return True
        if (self._user_dir(user_id) / "shelf" / "maps" / f"{COMMON}.json").exists():
            return True
        return any(self._db.execute(f"SELECT 1 FROM {table} WHERE user_id = ? AND floor = ? LIMIT 1", (user_id, COMMON)).fetchone()
                   for table in ("categories", "refs", "documents"))

    def _known(self, user_id: str, layout: Layout) -> set[str]:
        return {*([COMMON] if self._has_library(user_id, layout) else []), *self._existing(user_id, layout)}

    # ---- 이전(= 배치를 파일로 적기) -------------------------------------------------------------

    def _shelf_files(self, user_id: str) -> dict[str, list[Path]]:
        shelf = self._user_dir(user_id) / "shelf"
        return {
            "ideas": sorted((shelf / "casper").glob("*.json")),
            "styles": sorted((shelf / "balthasar").glob("*.json")),
            "refs": sorted((shelf / "melchior").glob("*/bib.json")),
            "category": sorted((shelf / "categories").glob("*/category.json")),
        }

    @locked
    def ensure_layout(self, user_id: str) -> Layout:
        """배치를 파일로 적는다(이미 적혀 있으면 읽기만). "floor"가 없는 항목 파일에 지금 보이는 층을 적는다.
        보이는 모습은 바뀌지 않으므로 인덱스는 그대로다."""
        layout = self._layout(user_id)
        if layout.stored:
            return layout
        known = self._known(user_id, layout)
        for kind, paths in self._shelf_files(user_id).items():
            for path in paths:
                data = read_json(path)
                if not (isinstance(data.get("floor"), str) and data["floor"] in known):
                    write_json(path, {**data, "floor": layout.fallback(kind)})
        self._write_layout(user_id, layout)
        return layout

    @locked
    def revert_floors(self, user_id: str) -> dict[str, int]:
        """층 이전 되돌리기(옛 코드로 되돌리기 전에): 항목 파일(휴지통 포함)에서 "floor"를 떼고 floors.json을 옆으로 비켜 둔다.
        지우지 않는다(floors.json.reverted-<시각>). 층 뒤에 만든 작업물은 그대로 남는다(옛 코드에서는 원고가 없는 책으로 보인다)."""
        udir = self._user_dir(user_id)
        counts: Counter = Counter()
        paths = [p for ps in self._shelf_files(user_id).values() for p in ps]
        paths += sorted((udir / "trash" / "shelf").glob("*/*.json")) + sorted((udir / "trash" / "shelf").glob("*/*/*.json"))
        for path in paths:
            data = read_json(path)
            if isinstance(data, dict) and "floor" in data:
                write_json(path, {k: v for k, v in data.items() if k != "floor"})
                counts["melchior" if path.name == "bib.json" else "categories" if path.name == "category.json" else path.parent.name] += 1
        floors = self._floors_path(user_id)
        if floors.exists():
            floors.rename(floors.with_name(f"floors.json.reverted-{utcnow().replace(':', '').replace('.', '')}"))
            counts["floors.json"] = 1
        return dict(counts)

    # ---- 층 목록 -----------------------------------------------------------------------------

    def _floor_updated(self, user_id: str, floor: str, layout: Layout) -> str:
        row = self._db.execute(
            """
            SELECT MAX(t) FROM (
                SELECT updated_at AS t FROM projects WHERE user_id = ?1 AND id = ?2
                UNION ALL SELECT updated_at FROM categories WHERE user_id = ?1 AND floor = ?2
                UNION ALL SELECT i.updated_at FROM category_items i JOIN categories c ON c.user_id = i.user_id AND c.id = i.category_id
                          WHERE i.user_id = ?1 AND c.floor = ?2
                UNION ALL SELECT COALESCE(updated_at, created_at) FROM refs WHERE user_id = ?1 AND floor = ?2
                UNION ALL SELECT updated_at FROM documents WHERE user_id = ?1 AND floor = ?2
            )
            """,
            (user_id, floor),
        ).fetchone()
        return max(str(row[0] or ""), layout.changed_at.get(floor, ""), self.map_updated(user_id, floor))  # type: ignore[attr-defined]

    @locked
    def list_floors(self, user_id: str) -> list[Floor]:
        layout = self._layout(user_id)
        projects = {r["id"]: r for r in self._db.execute(
            "SELECT p.id, p.title, (SELECT COUNT(*) FROM chapters c WHERE c.user_id = p.user_id AND c.project_id = p.id) AS n "
            "FROM projects p WHERE p.user_id = ?", (user_id,))}
        floors = ([Floor(COMMON, 0, COMMON_NAME, tuple(layout.kinds(COMMON)), False, self._floor_updated(user_id, COMMON, layout))]
                  if self._has_library(user_id, layout) else [])
        for n, pid in enumerate(self._existing(user_id, layout), 1):
            row = projects[pid]
            floors.append(Floor(pid, n, row["title"], tuple(layout.kinds(pid)), bool(row["n"]),
                                self._floor_updated(user_id, pid, layout)))
        return floors

    @locked
    def get_floor(self, user_id: str, floor_id: str) -> Floor | None:
        return next((f for f in self.list_floors(user_id) if f.id == floor_id), None)

    def _register_floor(self, user_id: str, project_id: str, layout: Layout) -> None:
        """create_project가 부른다(ensure_layout 뒤). 프로젝트 순서 끝에 더한다(휴지통에서 같은 id로 다시 만들면 그 자리).
        #96부터 새 프로젝트에 기본 책은 없다(옛 형식 사용자는 이전을 마친 뒤에만 서버가 뜬다)."""
        if project_id not in layout.order:
            layout.order.append(project_id)
        layout.changed_at[project_id] = utcnow()
        self._write_layout(user_id, layout)

    # ---- 옮기기 ------------------------------------------------------------------------------

    def _label(self, user_id: str, layout: Layout, floor: str) -> str:
        if floor == COMMON:
            return COMMON_NAME
        existing = self._existing(user_id, layout)
        return f"{existing.index(floor) + 1}층" if floor in existing else floor

    def _set_category_floor(self, user_id: str, category_id: str, floor: str, at: str) -> None:
        path = self._user_dir(user_id) / "shelf" / "categories" / category_id / "category.json"
        write_json(path, {**read_json(path), "floor": floor, "updated_at": at})
        with self._db:
            self._db.execute("UPDATE categories SET floor = ?, updated_at = ? WHERE user_id = ? AND id = ?",
                             (floor, at, user_id, category_id))

    def _clash(self, user_id: str, category_id: str, floor: str) -> str | None:
        row = self._db.execute(
            "SELECT b.name FROM categories a JOIN categories b ON b.user_id = a.user_id AND b.name_key = a.name_key AND b.id != a.id "
            "WHERE a.user_id = ? AND a.id = ? AND b.floor = ?", (user_id, category_id, floor)).fetchone()
        return row[0] if row else None

    def _set_book_refs_floor(self, user_id: str, book: str, floor: str) -> None:
        """책을 다른 프로젝트로 옮기면 그 책의 문헌도 그 프로젝트의 것이 된다(#96: 문헌은 책의 글)."""
        shelf = self._user_dir(user_id) / "shelf" / "melchior"
        keys = [r[0] for r in self._db.execute("SELECT key FROM refs WHERE user_id = ? AND book = ?", (user_id, book))]
        for key in keys:
            path = shelf / key / "bib.json"
            if path.exists():
                write_json(path, {**read_json(path), "floor": floor})
        with self._db:
            self._db.executemany("UPDATE refs SET floor = ? WHERE user_id = ? AND key = ?", [(floor, user_id, k) for k in keys])

    @locked
    def move_category(self, user_id: str, category_id: str, to_floor: str, to_node: str | None = None) -> FloorMove:
        layout = self.ensure_layout(user_id)
        self.ensure_maps(user_id)  # type: ignore[attr-defined]
        to_floor = self._check_floor(user_id, layout, to_floor)
        row = self._db.execute("SELECT name, floor FROM categories WHERE user_id = ? AND id = ?", (user_id, category_id)).fetchone()
        if row is None:
            raise MoveError("unknown_category", f"책 {category_id}가 없다")
        name, from_floor = row["name"], row["floor"]
        if from_floor == to_floor:
            raise MoveError("same", f"「{name}」은 이미 {self._label(user_id, layout, to_floor)}에 있다", name=name)
        if clash := self._clash(user_id, category_id, to_floor):
            raise MoveError("clash", f"{self._label(user_id, layout, to_floor)}에 같은 이름 「{clash}」이 있다", name=clash,
                            floor=self._label(user_id, layout, to_floor))
        at = utcnow()
        self._set_category_floor(user_id, category_id, to_floor, at)
        self._set_book_refs_floor(user_id, category_id, to_floor)
        move = FloorMove(new_id(), at, category_id, name, from_floor, to_floor)
        layout.last_move = asdict(move)
        layout.changed_at.update({from_floor: at, to_floor: at})
        self._write_layout(user_id, layout)
        self._moved_maps(user_id, from_floor, to_floor, {category_id: to_node} if to_node else None)
        return move

    def _moved_maps(self, user_id: str, from_floor: str, to_floor: str, hint: dict[str, str] | None) -> None:
        """책이 다른 프로젝트로 간 뒤 두 지도를 맞춰 적는다(받는 쪽은 hint의 노드에)."""
        self._persist_map(user_id, from_floor)  # type: ignore[attr-defined]
        self._persist_map(user_id, to_floor, hint)  # type: ignore[attr-defined]

    @locked
    def move_document(self, user_id: str, doc_id: str, to_floor: str, to_node: str | None = None) -> FloorMove:
        """문서 책을 원고가 있는 다른 프로젝트로(#94·#95)."""
        layout = self.ensure_layout(user_id)
        self.ensure_maps(user_id)  # type: ignore[attr-defined]
        to_floor = self._check_floor(user_id, layout, to_floor)
        row = self._db.execute("SELECT title, floor FROM documents WHERE user_id = ? AND id = ?", (user_id, doc_id)).fetchone()
        if row is None:
            raise MoveError("unknown_category", f"문서 {doc_id}가 없다")
        has_ms = self._db.execute("SELECT 1 FROM chapters WHERE user_id = ? AND project_id = ? LIMIT 1", (user_id, to_floor)).fetchone()
        if to_floor == COMMON or not has_ms:
            raise MoveError("common_only", "올린 문서에서 만든 문서는 올린 문서가 있는 프로젝트에만 둔다", name=row["title"])
        if row["floor"] == to_floor:
            raise MoveError("same", "이미 그 층에 있다", name=row["title"])
        at = utcnow()
        self._set_document_floor(user_id, doc_id, to_floor, at)  # type: ignore[attr-defined]
        move = FloorMove(new_id(), at, f"doc.{doc_id}", row["title"], row["floor"], to_floor)
        layout.last_move = asdict(move)
        layout.changed_at.update({row["floor"]: at, to_floor: at})
        self._write_layout(user_id, layout)
        self._moved_maps(user_id, row["floor"], to_floor, {f"doc.{doc_id}": to_node} if to_node else None)
        return move

    @locked
    def last_move(self, user_id: str) -> FloorMove | None:
        last = self._layout(user_id).last_move
        if not last:
            return None
        return FloorMove(**{**last, "items": tuple(last.get("items") or ())})

    @locked
    def undo_move(self, user_id: str, move_id: str) -> FloorMove:
        layout = self.ensure_layout(user_id)
        move = self.last_move(user_id)
        if move is None or move.id != move_id:
            raise MoveError("not_last", "되돌릴 수 있는 것은 마지막 옮기기뿐이다")
        if move.from_floor not in self._known(user_id, layout):
            raise MoveError("unknown_floor", f"층 {move.from_floor!r}가 없다", floor=move.from_floor)
        at = utcnow()
        self.ensure_maps(user_id)  # type: ignore[attr-defined]
        key = move.book
        if move.from_floor == move.to_floor:  # 같은 프로젝트 안에서 노드만 옮긴 것(#95)
            if move.from_node:
                try:
                    self.place_book(user_id, move.from_floor, key, move.from_node)  # type: ignore[attr-defined]
                except ValueError:
                    pass  # 그 노드가 사라졌거나 가득 찼으면 지금 자리에
        elif move.book.startswith("doc."):  # 문서 책(#94)
            doc_id = move.book[4:]
            if self._db.execute("SELECT 1 FROM documents WHERE user_id = ? AND id = ?", (user_id, doc_id)).fetchone() is None:
                raise MoveError("unknown_category", f"문서 {doc_id}가 없다")
            self._set_document_floor(user_id, doc_id, move.from_floor, at)  # type: ignore[attr-defined]
        else:
            row = self._db.execute("SELECT floor FROM categories WHERE user_id = ? AND id = ?", (user_id, move.book)).fetchone()
            if row is None:
                raise MoveError("unknown_category", f"책 {move.book}가 없다")
            if clash := self._clash(user_id, move.book, move.from_floor):
                raise MoveError("undo_clash", f"{self._label(user_id, layout, move.from_floor)}에 같은 이름 「{clash}」이 생겼다",
                                name=clash, floor=self._label(user_id, layout, move.from_floor))
            self._set_category_floor(user_id, move.book, move.from_floor, at)
            self._set_book_refs_floor(user_id, move.book, move.from_floor)
        layout.last_move = None
        layout.last_undone = asdict(move)
        layout.changed_at.update({move.from_floor: at, move.to_floor: at})
        self._write_layout(user_id, layout)
        if move.from_floor != move.to_floor:
            self._moved_maps(user_id, move.to_floor, move.from_floor, {key: move.from_node} if move.from_node else None)
            if move.made_node and move.to_node:
                self._drop_empty_node(user_id, move.to_floor, move.to_node)  # type: ignore[attr-defined]
        return move

    @locked
    def record_move(self, user_id: str, move: FloorMove) -> FloorMove:
        """마지막 옮기기로 적는다(노드를 옮긴 것까지 담아 한 번 되돌릴 수 있게, #95)."""
        layout = self.ensure_layout(user_id)
        layout.last_move = asdict(move)
        layout.changed_at.update({move.from_floor: move.at, move.to_floor: move.at})
        self._write_layout(user_id, layout)
        return move

    @locked
    def last_undone(self, user_id: str) -> FloorMove | None:
        last = self._layout(user_id).last_undone
        return FloorMove(**{**last, "items": tuple(last.get("items") or ())}) if last else None
