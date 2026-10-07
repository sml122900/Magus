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
"""

from __future__ import annotations

import sqlite3
import threading
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from magus.floors import BUILTIN_ORDER, COMMON, COMMON_BUILTINS, COMMON_NAME, FLOORS_SCHEMA, NEW_FLOOR_BUILTINS
from magus.ids import new_id, utcnow
from magus.store.base import Floor, FloorMove
from magus.store.fileio import locked, read_json, write_json

KINDS = ("ideas", "styles", "refs")


class MoveError(ValueError):
    """옮기기를 할 수 없는 까닭. code: same | clash | unknown_floor | no_builtin | not_last | undo_clash | full.
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


@dataclass
class FloorPlan:
    """층 이전 미리보기(magus floors plan). 아무것도 쓰지 않는다."""

    user_id: str
    stored: bool  # 이미 이전했나
    floors: list[tuple[str, str, list[str]]]  # (층 이름, 작업물 제목, 꽂힐 기본 카테고리)
    moves: dict[str, Counter]  # 종류(생각·문체·문헌·카테고리) → {층 이름: 항목 수} ("floor"를 새로 적을 것)
    already: Counter  # 이미 "floor"가 있는 항목 수(종류별)
    categories: list[tuple[str, str]]  # (카테고리 이름, 층 이름)

    def lines(self) -> list[str]:
        out = [f"사용자 {self.user_id}: " + ("이미 이전함(floors.json 있음)" if self.stored else "이전 전")]
        for label, title, kinds in self.floors:
            names = "·".join({"ideas": "생각", "styles": "문체", "refs": "문헌"}[k] for k in kinds) or "(기본 카테고리 없음)"
            out.append(f"- {label}{f' 「{title}」' if title else ''}: {names}")
        for kind, counts in self.moves.items():
            if counts:
                out.append(f"- {kind}: " + " · ".join(f"{floor} {n}개" for floor, n in counts.items()) + " (새로 적음)")
        if self.already:
            out.append("- 이미 층이 적힌 항목: " + " · ".join(f"{k} {n}" for k, n in self.already.items()))
        out += [f"- 카테고리 「{name}」 → {floor}" for name, floor in self.categories]
        return out


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

    def _layout(self, user_id: str) -> Layout:
        path = self._floors_path(user_id)
        projects = self._project_ids(user_id)
        if not path.exists():
            return legacy_layout(projects)
        data = read_json(path)
        order = [str(p) for p in data.get("order") or [] if isinstance(p, str)]
        order += [p for p in projects if p not in order]  # 옛 코드가 만든 작업물 등 순서에 없는 것은 끝에(기본 카테고리는 없음)
        builtins = {str(f): [k for k in BUILTIN_ORDER if k in (v or [])] for f, v in (data.get("builtins") or {}).items()}
        for p in projects:
            if p not in (data.get("order") or []) and p not in builtins:
                builtins[p] = list(NEW_FLOOR_BUILTINS)
        last = data.get("last_move") if isinstance(data.get("last_move"), dict) else None
        undone = data.get("last_undone") if isinstance(data.get("last_undone"), dict) else None
        changed = {str(k): str(v) for k, v in (data.get("changed_at") or {}).items()}
        return Layout(order, builtins, changed, last, undone, True)

    def _write_layout(self, user_id: str, layout: Layout) -> None:
        write_json(self._floors_path(user_id), layout.record())
        layout.stored = True

    def _existing(self, user_id: str, layout: Layout) -> list[str]:
        """순서 중 지금 있는 작업물만(휴지통으로 간 작업물의 자리는 남겨 둔다: 같은 id로 다시 가져오면 그 자리)."""
        projects = set(self._project_ids(user_id))
        return [p for p in layout.order if p in projects]

    def _check_floor(self, user_id: str, layout: Layout, floor: str) -> str:
        if floor == COMMON or floor in self._existing(user_id, layout):
            return floor
        raise MoveError("unknown_floor", f"층 {floor!r}가 없다", floor=floor)

    def _known(self, user_id: str, layout: Layout) -> set[str]:
        return {COMMON, *self._existing(user_id, layout)}

    def _floor_or_fallback(self, raw: Any, kind: str, layout: Layout, known: set[str]) -> str:
        return raw if isinstance(raw, str) and raw in known else layout.fallback(kind)

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
    def floor_plan(self, user_id: str) -> FloorPlan:
        layout = self._layout(user_id)
        known = self._known(user_id, layout)
        titles = {r[0]: r[1] for r in self._db.execute("SELECT id, title FROM projects WHERE user_id = ?", (user_id,))}
        labels = {COMMON: COMMON_NAME, **{p: f"{n}층" for n, p in enumerate(self._existing(user_id, layout), 1)}}
        names = {"ideas": "생각", "styles": "문체", "refs": "문헌", "category": "카테고리"}
        moves: dict[str, Counter] = {names[k]: Counter() for k in names}
        already: Counter = Counter()
        cats = []
        for kind, paths in self._shelf_files(user_id).items():
            for path in paths:
                data = read_json(path)
                if isinstance(data.get("floor"), str) and data["floor"] in known:
                    already[names[kind]] += 1
                    floor = data["floor"]
                else:
                    floor = layout.fallback(kind)
                    moves[names[kind]][labels.get(floor, floor)] += 1
                if kind == "category":
                    cats.append((str(data.get("name") or path.parent.name), labels.get(floor, floor)))
        floors = [(labels[f], titles.get(f, ""), layout.kinds(f)) for f in (COMMON, *self._existing(user_id, layout))]
        return FloorPlan(user_id, layout.stored, floors, moves, already, cats)

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
                counts[path.parent.name if path.name != "bib.json" else "melchior"] += 1
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
                UNION ALL SELECT COALESCE(edited_at, created_at) FROM ideas WHERE user_id = ?1 AND floor = ?2
                UNION ALL SELECT created_at FROM style_entries WHERE user_id = ?1 AND floor = ?2
                UNION ALL SELECT COALESCE(updated_at, created_at) FROM refs WHERE user_id = ?1 AND floor = ?2
            )
            """,
            (user_id, floor),
        ).fetchone()
        return max(str(row[0] or ""), layout.changed_at.get(floor, ""))

    @locked
    def list_floors(self, user_id: str) -> list[Floor]:
        layout = self._layout(user_id)
        projects = {r["id"]: r for r in self._db.execute(
            "SELECT p.id, p.title, (SELECT COUNT(*) FROM chapters c WHERE c.user_id = p.user_id AND c.project_id = p.id) AS n "
            "FROM projects p WHERE p.user_id = ?", (user_id,))}
        floors = [Floor(COMMON, 0, COMMON_NAME, tuple(layout.kinds(COMMON)), False, self._floor_updated(user_id, COMMON, layout))]
        for n, pid in enumerate(self._existing(user_id, layout), 1):
            row = projects[pid]
            floors.append(Floor(pid, n, row["title"], tuple(layout.kinds(pid)), bool(row["n"]),
                                self._floor_updated(user_id, pid, layout)))
        return floors

    @locked
    def get_floor(self, user_id: str, floor_id: str) -> Floor | None:
        return next((f for f in self.list_floors(user_id) if f.id == floor_id), None)

    def _register_floor(self, user_id: str, project_id: str, layout: Layout) -> None:
        """create_project가 부른다(ensure_layout 뒤). 새 층에는 생각·문헌. 휴지통에서 같은 id로 다시 만들면 자리·배치 그대로.
        첫 작업물 층이면 공용에 비어 있는 생각·문헌을 그 층으로 옮긴다(작업물이 없을 때 공용에 두었던 자리)."""
        now = utcnow()
        if project_id in layout.order:
            layout.builtins.setdefault(project_id, list(NEW_FLOOR_BUILTINS))  # 휴지통에서 같은 id로: 배치는 그대로
        else:
            first = not self._existing(user_id, layout)
            layout.order.append(project_id)
            layout.builtins[project_id] = list(NEW_FLOOR_BUILTINS)
            if first:
                for kind in NEW_FLOOR_BUILTINS:
                    if kind in layout.builtins.get(COMMON, []) and not self._count_on(user_id, kind, COMMON):
                        layout.builtins[COMMON].remove(kind)
        layout.changed_at[project_id] = now
        self._write_layout(user_id, layout)

    def _count_on(self, user_id: str, kind: str, floor: str) -> int:
        table = {"ideas": "ideas", "styles": "style_entries", "refs": "refs"}[kind]
        return self._db.execute(f"SELECT COUNT(*) FROM {table} WHERE user_id = ? AND floor = ?", (user_id, floor)).fetchone()[0]

    # ---- 새 항목이 들어갈 층 ---------------------------------------------------------------------

    @locked
    def place(self, user_id: str, kind: str, floor: str | None) -> str:
        layout = self._layout(user_id)
        if floor is None:
            return layout.fallback(kind)
        floor = self._check_floor(user_id, layout, floor)
        if kind in layout.builtins.get(floor, []):
            return floor
        if kind in layout.builtins.get(COMMON, []):
            return COMMON
        layout = self.ensure_layout(user_id)  # 그 층에 기본 카테고리를 다시 꽂는다
        layout.builtins.setdefault(floor, []).append(kind)
        layout.changed_at[floor] = utcnow()
        self._write_layout(user_id, layout)
        return floor

    def _ensure_builtin(self, user_id: str, kind: str, floor: str) -> None:
        layout = self.ensure_layout(user_id)
        if kind not in layout.builtins.get(floor, []):
            layout.builtins.setdefault(floor, []).append(kind)
            layout.changed_at[floor] = utcnow()
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

    @locked
    def move_category(self, user_id: str, category_id: str, to_floor: str) -> FloorMove:
        layout = self.ensure_layout(user_id)
        to_floor = self._check_floor(user_id, layout, to_floor)
        row = self._db.execute("SELECT name, floor FROM categories WHERE user_id = ? AND id = ?", (user_id, category_id)).fetchone()
        if row is None:
            raise MoveError("unknown_category", f"카테고리 {category_id}가 없다")
        name, from_floor = row["name"], row["floor"]
        if from_floor == to_floor:
            raise MoveError("same", f"「{name}」은 이미 {self._label(user_id, layout, to_floor)}에 있다", name=name)
        if clash := self._clash(user_id, category_id, to_floor):
            raise MoveError("clash", f"{self._label(user_id, layout, to_floor)}에 같은 이름 「{clash}」이 있다", name=clash,
                            floor=self._label(user_id, layout, to_floor))
        at = utcnow()
        self._set_category_floor(user_id, category_id, to_floor, at)
        move = FloorMove(new_id(), at, category_id, name, from_floor, to_floor)
        layout.last_move = asdict(move)
        layout.changed_at.update({from_floor: at, to_floor: at})
        self._write_layout(user_id, layout)
        return move

    def _builtin_items(self, user_id: str, kind: str, floor: str) -> list[str]:
        if kind == "refs":
            return [r[0] for r in self._db.execute("SELECT key FROM refs WHERE user_id = ? AND floor = ? ORDER BY key", (user_id, floor))]
        table = "ideas" if kind == "ideas" else "style_entries"
        return [r[0] for r in self._db.execute(f"SELECT id FROM {table} WHERE user_id = ? AND floor = ? ORDER BY id", (user_id, floor))]

    def _set_items_floor(self, user_id: str, kind: str, ids: Iterable[str], floor: str) -> None:
        """기본 카테고리 항목들의 층만 바꾼다(파일 먼저, 인덱스 나중)."""
        shelf = self._user_dir(user_id) / "shelf"
        ids = list(ids)
        for item in ids:
            path = (shelf / "melchior" / item / "bib.json" if kind == "refs"
                    else shelf / ("casper" if kind == "ideas" else "balthasar") / f"{item}.json")
            if path.exists():
                write_json(path, {**read_json(path), "floor": floor})
        table, column = {"ideas": ("ideas", "id"), "styles": ("style_entries", "id"), "refs": ("refs", "key")}[kind]
        with self._db:
            self._db.executemany(f"UPDATE {table} SET floor = ? WHERE user_id = ? AND {column} = ?",
                                 [(floor, user_id, i) for i in ids])

    @locked
    def move_builtin(self, user_id: str, kind: str, from_floor: str, to_floor: str) -> FloorMove:
        if kind not in KINDS:
            raise MoveError("no_builtin", f"기본 카테고리 종류가 아니다: {kind!r}")
        layout = self.ensure_layout(user_id)
        from_floor = self._check_floor(user_id, layout, from_floor)
        to_floor = self._check_floor(user_id, layout, to_floor)
        name = {"ideas": "생각", "styles": "문체", "refs": "문헌"}[kind]
        if kind not in layout.builtins.get(from_floor, []):
            raise MoveError("no_builtin", f"{self._label(user_id, layout, from_floor)}에 「{name}」이 없다", name=name)
        if from_floor == to_floor:
            raise MoveError("same", f"「{name}」은 이미 {self._label(user_id, layout, to_floor)}에 있다", name=name)
        merged = kind in layout.builtins.get(to_floor, [])
        items = self._builtin_items(user_id, kind, from_floor)
        self._set_items_floor(user_id, kind, items, to_floor)
        at = utcnow()
        layout.builtins[from_floor].remove(kind)
        if not merged:
            layout.builtins.setdefault(to_floor, []).append(kind)
        move = FloorMove(new_id(), at, kind, name, from_floor, to_floor, merged, tuple(items))
        layout.last_move = asdict(move)
        layout.changed_at.update({from_floor: at, to_floor: at})
        self._write_layout(user_id, layout)
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
        if move.book in KINDS:
            kind = move.book
            here = set(self._builtin_items(user_id, kind, move.to_floor))
            back = [i for i in move.items if i in here]  # 그사이 다른 곳으로 간 항목은 그대로 둔다
            self._set_items_floor(user_id, kind, back, move.from_floor)
            if kind not in layout.builtins.get(move.from_floor, []):
                layout.builtins.setdefault(move.from_floor, []).append(kind)
            if not move.merged and kind in layout.builtins.get(move.to_floor, []) and not self._builtin_items(user_id, kind, move.to_floor):
                layout.builtins[move.to_floor].remove(kind)  # 옮기며 새로 꽂은 자리. 그사이 새 항목이 들어왔으면 남긴다
        else:
            row = self._db.execute("SELECT floor FROM categories WHERE user_id = ? AND id = ?", (user_id, move.book)).fetchone()
            if row is None:
                raise MoveError("unknown_category", f"카테고리 {move.book}가 없다")
            if clash := self._clash(user_id, move.book, move.from_floor):
                raise MoveError("undo_clash", f"{self._label(user_id, layout, move.from_floor)}에 같은 이름 「{clash}」이 생겼다",
                                name=clash, floor=self._label(user_id, layout, move.from_floor))
            self._set_category_floor(user_id, move.book, move.from_floor, at)
        layout.last_move = None
        layout.last_undone = asdict(move)
        layout.changed_at.update({move.from_floor: at, move.to_floor: at})
        self._write_layout(user_id, layout)
        return move

    @locked
    def last_undone(self, user_id: str) -> FloorMove | None:
        last = self._layout(user_id).last_undone
        return FloorMove(**{**last, "items": tuple(last.get("items") or ())}) if last else None

    @locked
    def set_ref_floor(self, user_id: str, key: str, floor: str) -> Any:
        layout = self.ensure_layout(user_id)
        floor = self._check_floor(user_id, layout, floor)
        self._ensure_builtin(user_id, "refs", floor)
        self._set_items_floor(user_id, "refs", [key], floor)
        return self.get_ref(user_id, key)  # type: ignore[attr-defined]

    # ---- 최근 수정 -----------------------------------------------------------------------------

    @locked
    def category_updated(self, user_id: str, category_id: str) -> str:
        row = self._db.execute(
            "SELECT MAX(t) FROM (SELECT updated_at AS t FROM categories WHERE user_id = ?1 AND id = ?2 "
            "UNION ALL SELECT updated_at FROM category_items WHERE user_id = ?1 AND category_id = ?2)", (user_id, category_id),
        ).fetchone()
        return str(row[0] or "")

    @locked
    def builtin_updated(self, user_id: str, kind: str, floor: str) -> str:
        sql = {"ideas": "SELECT MAX(COALESCE(edited_at, created_at)) FROM ideas",
               "styles": "SELECT MAX(created_at) FROM style_entries",
               "refs": "SELECT MAX(COALESCE(updated_at, created_at)) FROM refs"}[kind]
        return str(self._db.execute(sql + " WHERE user_id = ? AND floor = ?", (user_id, floor)).fetchone()[0] or "")
