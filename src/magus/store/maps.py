"""지도(#95) 저장. LocalStore에 섞어 쓰는 믹스인이다(FloorMixin 뒤에 둔다: 프로젝트 배치 _layout을 쓴다).

원본(사람이 읽는 json): data/users/<user_id>/shelf/maps/<프로젝트 id>.json
  {"schema_version": 1, "updated_at": 시각,
   "nodes": [{"id": "center", "x": 0, "y": 0, "books": ["ms", "doc.<id>"]},
             {"id": "b-ideas", "name": "생각", "x": 0, "y": -240, "books": ["ideas"], "color": "#rrggbb"?},
             {"id": "l-…", "x": …, "y": …, "link": {"project": "common", "node": "b-styles"}}],
   "edges": [["b-ideas", "center"], …]}
책 이름(지도 파일): ms(원고 책) · ideas|styles|refs(기본 책) · <카테고리 id> · doc.<문서 id>.

지도 파일이 없는 프로젝트는 지금 배치에서 계산한 지도로 보인다(_reconcile): 가운데 노드에 원고 책·문서 책,
기본 책·카테고리는 이름이 같은 노드 하나씩(가운데와 이음), 「내 서재」의 문헌(과, 자기 문체가 없으면 문체)으로 가는 연결 노드.
그래서 이전(magus maps apply)은 '보이는 지도를 파일로 적는 일'이고, 층 이전 전·뒤 어느 데이터에서 시작해도 같은 지도가 된다.
지도 파일이 있어도 읽을 때마다 맞춘다: 없어진 책은 빼고, 노드에 없는 책은 이름이 같은 노드(없으면 새 노드)에 꽂아 보인다.
지도를 바꾸는 쓰기 전에는 모든 프로젝트의 지도를 파일로 적는다(ensure_maps).
"""

from __future__ import annotations

import hashlib
import math
import re
import sqlite3
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from magus.ids import new_id, utcnow
from magus.maps import (
    BOOK_NAMES, CENTER, LIBRARY, LIBRARY_NAME, MAP_SCHEMA, MAX_BOOKS_PER_NODE, MAX_NODES, NODE_GAP, RING, clean_node_name,
    global_key, local_key, name_key, valid_node_id,
)
from magus.store.base import MapNode, ProjectMap
from magus.store.fileio import locked, read_json, write_json

_HEX = re.compile(r"#[0-9a-fA-F]{6}")


class MapError(ValueError):
    """지도를 바꿀 수 없는 까닭. code: unknown_floor | unknown_node | center(가운데 노드 휴지통) | center_name | link_name
    | not_empty | node_full | nodes_full | name_taken | bad_name | bad_color | same_node | link_self | link_exists | link_node
    | ms_center | unknown_book. 도구와 웹이 code로 저자에게 보일 문장을 만든다(magus.category.moves.error_message)."""

    def __init__(self, code: str, message: str, **info: Any):
        super().__init__(message)
        self.code, self.info = code, info


def _num(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return round(number, 1) if math.isfinite(number) and abs(number) < 1e6 else 0.0


def _edge(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a <= b else (b, a)


def _clear(x: float, y: float, nodes: list[dict[str, Any]]) -> bool:
    """(x, y)에 노드를 놓아도 다른 노드와 겹치지 않나(가로로 긴 노드라 타원으로 본다. 가운데 노드는 더 크다)."""
    for n in nodes:
        w, h = (230, 120) if n["id"] == CENTER else (NODE_GAP, 90)
        if ((x - n["x"]) / w) ** 2 + ((y - n["y"]) / h) ** 2 < 1:
            return False
    return True


def free_slot(nodes: list[dict[str, Any]]) -> tuple[float, float]:
    """새 노드를 놓을 빈자리: 가운데 노드를 둘러싼 고리(240, 360, 480…)를 위에서부터 시계 방향으로 훑어 처음 빈 곳."""
    center = next((n for n in nodes if n["id"] == CENTER), {"x": 0.0, "y": 0.0})
    for ring in range(1, 12):
        radius = RING * (1 + 0.5 * (ring - 1))
        steps = 8 * ring
        for i in range(steps):
            angle = -math.pi / 2 + 2 * math.pi * i / steps
            x, y = round(center["x"] + radius * 1.3 * math.cos(angle)), round(center["y"] + radius * 0.85 * math.sin(angle))
            if _clear(x, y, nodes):
                return float(x), float(y)
    return float(center["x"]), float(center["y"] + RING * 7)


def ring_layout(count: int) -> list[tuple[float, float]]:
    """계산한 지도: 가운데를 둘러싼 가로로 긴 타원에 고르게(위에서부터 시계 방향). 노드가 많으면 고리가 커진다."""
    radius = max(RING, 29 * count)
    return [(float(round(radius * 1.3 * math.cos(-math.pi / 2 + 2 * math.pi * i / count))),
             float(round(radius * 0.85 * math.sin(-math.pi / 2 + 2 * math.pi * i / count)))) for i in range(count)]


def link_id(project: str, node: str) -> str:
    return "l-" + hashlib.sha256(f"{project}/{node}".encode()).hexdigest()[:10]


class MapMixin:
    root: Path
    _db: sqlite3.Connection
    _lock: threading.RLock
    _user_dir: Callable[[str], Path]
    _layout: Callable[[str], Any]
    _existing: Callable[[str, Any], list[str]]
    ensure_layout: Callable[[str], Any]
    _write_layout: Callable[[str, Any], None]

    # ---- 파일 ------------------------------------------------------------------------------

    def _map_path(self, user_id: str, floor: str) -> Path:
        return self._user_dir(user_id) / "shelf" / "maps" / f"{floor}.json"

    def _load_map(self, user_id: str, floor: str) -> dict[str, Any] | None:
        path = self._map_path(user_id, floor)
        if not path.exists():
            return None
        data = read_json(path)
        return data if isinstance(data, dict) else None

    def _known_floors(self, user_id: str, layout: Any) -> list[str]:
        return [LIBRARY, *self._existing(user_id, layout)]

    # ---- 지금 책 ------------------------------------------------------------------------------

    def _floor_books(self, user_id: str, floor: str, layout: Any) -> list[str]:
        """그 프로젝트에 지금 있는 책(지도 파일의 책 이름): 원고 책, 기본 책, 카테고리(만든 순서), 문서 책(만든 순서)."""
        books = []
        if floor != LIBRARY and self._db.execute(
                "SELECT 1 FROM chapters WHERE user_id = ? AND project_id = ? LIMIT 1", (user_id, floor)).fetchone():
            books.append("ms")
        books += layout.kinds(floor)
        books += [r[0] for r in self._db.execute(
            "SELECT id FROM categories WHERE user_id = ? AND floor = ? ORDER BY created_at, id", (user_id, floor))]
        books += [f"doc.{r[0]}" for r in self._db.execute(
            "SELECT id FROM documents WHERE user_id = ? AND floor = ? ORDER BY created_at, id", (user_id, floor))]
        return books

    def _book_title(self, user_id: str, local: str) -> str:
        if local in BOOK_NAMES:
            return BOOK_NAMES[local]
        row = self._db.execute("SELECT name FROM categories WHERE user_id = ? AND id = ?", (user_id, local)).fetchone()
        return str(row[0]) if row else local

    # ---- 맞추기(읽을 때마다) ----------------------------------------------------------------------

    def _reconcile(self, user_id: str, floor: str, layout: Any, hint: dict[str, str] | None = None) -> tuple[dict[str, Any], bool]:
        """(지도, 파일이 있나). 지도는 지도 파일 형식(책 이름은 지도 파일의 것)이다. 아무것도 쓰지 않는다.
        hint: {지도 파일의 책 이름: 노드 id} — 아직 노드에 없는 그 책을 그 노드에 놓는다(새로 만들거나 옮겨 온 책, 되돌리기)."""
        raw = self._load_map(user_id, floor)
        stored = raw is not None
        nodes: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in (raw or {}).get("nodes") or []:
            if not isinstance(item, dict) or not valid_node_id(str(item.get("id") or "")) or item["id"] in seen:
                continue
            seen.add(item["id"])
            node: dict[str, Any] = {"id": item["id"], "x": _num(item.get("x")), "y": _num(item.get("y"))}
            link = item.get("link")
            if item["id"] != CENTER and isinstance(link, dict) and isinstance(link.get("project"), str) and isinstance(link.get("node"), str):
                node["link"] = {"project": link["project"], "node": link["node"]}
            else:
                if item["id"] != CENTER:
                    node["name"] = " ".join(str(item.get("name") or "").split())[:40] or "노드"
                node["books"] = [str(b) for b in item.get("books") or [] if isinstance(b, str)]
            if isinstance(item.get("color"), str) and _HEX.fullmatch(item["color"]):
                node["color"] = item["color"].lower()
            nodes.append(node)
        center = next((n for n in nodes if n["id"] == CENTER), None)
        if center is None:
            center = {"id": CENTER, "x": 0.0, "y": 0.0, "books": []}
        nodes = [center, *(n for n in nodes if n is not center)]
        edges = {_edge(str(a), str(b)) for a, b in ((e[0], e[1]) for e in (raw or {}).get("edges") or []
                                                      if isinstance(e, list | tuple) and len(e) == 2)}

        present = self._floor_books(user_id, floor, layout)
        here = set(present)
        placed: set[str] = set()
        for n in nodes:
            if "link" in n:
                continue
            keep = []
            for b in n["books"]:
                if b in here and b not in placed and (b != "ms" or n["id"] == CENTER):
                    keep.append(b)
                    placed.add(b)
            n["books"] = keep
        added: list[dict[str, Any]] = []
        for b in present:
            if b in placed:
                continue
            wanted = next((n for n in nodes if n["id"] == (hint or {}).get(b) and "link" not in n and (b != "ms" or n["id"] == CENTER)), None)
            if wanted is not None and len(wanted["books"]) < MAX_BOOKS_PER_NODE:
                wanted["books"].append(b)
                continue
            if b == "ms" or b.startswith("doc."):
                center["books"].insert(0, b) if b == "ms" else center["books"].append(b)
                continue
            title = self._book_title(user_id, b)
            target = next((n for n in nodes if "link" not in n and n["id"] != CENTER and name_key(n["name"]) == name_key(title)), None)
            if target is None:
                nid, k = f"b-{b}", 2
                while any(n["id"] == nid for n in nodes):
                    nid, k = f"b-{b}-{k}", k + 1
                target = {"id": nid, "name": title, "x": 0.0, "y": 0.0, "books": []}
                nodes.append(target)
                added.append(target)
                edges.add(_edge(CENTER, nid))
            target["books"].append(b)
        if not stored and floor != LIBRARY:  # 이전 규칙: 「내 서재」의 문헌, (자기 문체가 없으면) 문체로 가는 연결 노드
            library, _ = self._reconcile(user_id, LIBRARY, layout)
            for kind in ("styles", "refs"):
                if kind == "styles" and kind in layout.kinds(floor):
                    continue
                source = next((n for n in library["nodes"] if kind in n.get("books", [])), None)
                if source is not None and not any(n.get("link") == {"project": LIBRARY, "node": source["id"]} for n in nodes):
                    linked = {"id": link_id(LIBRARY, source["id"]), "x": 0.0, "y": 0.0,
                              "link": {"project": LIBRARY, "node": source["id"]}}
                    nodes.append(linked)
                    added.append(linked)
                    edges.add(_edge(CENTER, linked["id"]))
        if not stored:
            for n, (x, y) in zip([n for n in nodes if n is not center], ring_layout(len(nodes) - 1), strict=True):
                n["x"], n["y"] = x, y
        else:  # 파일이 있는 지도에 새로 보이는 노드는 빈자리에(앞의 것부터 차례로)
            fresh = {id(n) for n in added}
            settled = [m for m in nodes if id(m) not in fresh]
            for n in added:
                n["x"], n["y"] = free_slot(settled)
                settled.append(n)
        ids = {n["id"] for n in nodes}
        data = {"nodes": nodes, "edges": sorted(e for e in edges if e[0] in ids and e[1] in ids and e[0] != e[1]),
                "updated_at": str((raw or {}).get("updated_at") or "")}
        return data, stored

    def _write_map(self, user_id: str, floor: str, data: dict[str, Any]) -> None:
        data["updated_at"] = utcnow()
        write_json(self._map_path(user_id, floor), {"schema_version": MAP_SCHEMA, "updated_at": data["updated_at"],
                                                     "nodes": data["nodes"], "edges": [list(e) for e in data["edges"]]})

    @locked
    def ensure_maps(self, user_id: str) -> list[str]:
        """모든 프로젝트의 지도를 파일로 적는다(층 배치도 먼저 적는다). 이미 적힌 지도는 그대로. 적은 프로젝트 id를 돌려준다."""
        layout = self.ensure_layout(user_id)
        made = []
        derived = {f: self._reconcile(user_id, f, layout) for f in self._known_floors(user_id, layout)}
        for floor, (data, stored) in derived.items():
            if not stored:
                self._write_map(user_id, floor, data)
                made.append(floor)
        return made

    def _persist_map(self, user_id: str, floor: str, hint: dict[str, str] | None = None) -> None:
        """책이 생기거나 옮겨 온 뒤: 그 프로젝트의 지도를 맞춰 파일로 적는다(새 책은 hint의 노드, 없으면 이름이 같은 노드나 새 노드).
        부르기 전에 ensure_maps로 다른 지도를 먼저 적어 둔다(책이 생기기 전 모습으로)."""
        layout = self._layout(user_id)
        if floor in self._known_floors(user_id, layout):
            local = {local_key(b)[1]: n for b, n in (hint or {}).items() if n}
            self._write_map(user_id, floor, self._reconcile(user_id, floor, layout, local)[0])

    def _editable(self, user_id: str, floor: str) -> tuple[Any, dict[str, Any]]:
        """바꾸기 전에: 모든 지도를 파일로 적고, 이 프로젝트의 지도를 맞춰 읽는다."""
        self.ensure_maps(user_id)
        layout = self._layout(user_id)
        if floor not in self._known_floors(user_id, layout):
            raise MapError("unknown_floor", f"프로젝트 {floor!r}가 없다", floor=floor)
        return layout, self._reconcile(user_id, floor, layout)[0]

    # ---- 읽기 ------------------------------------------------------------------------------

    def _floor_title(self, user_id: str, floor: str) -> str | None:
        if floor == LIBRARY:
            return LIBRARY_NAME
        row = self._db.execute("SELECT title FROM projects WHERE user_id = ? AND id = ?", (user_id, floor)).fetchone()
        return str(row[0]) if row else None

    @locked
    def get_map(self, user_id: str, floor: str) -> ProjectMap | None:
        layout = self._layout(user_id)
        if floor not in self._known_floors(user_id, layout):
            return None
        data, stored = self._reconcile(user_id, floor, layout)
        title = self._floor_title(user_id, floor) or floor
        others: dict[str, dict[str, Any] | None] = {}
        nodes = []
        for n in data["nodes"]:
            if "link" in n:
                target, node_id = n["link"]["project"], n["link"]["node"]
                if target not in others:
                    others[target] = (self._reconcile(user_id, target, layout)[0]
                                      if target in self._known_floors(user_id, layout) else None)
                source = next((m for m in (others[target] or {}).get("nodes", []) if m["id"] == node_id), None)
                source_title = self._floor_title(user_id, target) or ""
                if source is None or "link" in source:
                    nodes.append(MapNode(n["id"], "원본 없음", n["x"], n["y"], n.get("color"), (), False, (target, node_id),
                                         source_title, True))
                    continue
                name = source_title if source["id"] == CENTER else source["name"]
                nodes.append(MapNode(n["id"], name, n["x"], n["y"], n.get("color") or source.get("color"),
                                     tuple(global_key(target, b) for b in source["books"]), False, (target, node_id), source_title))
                continue
            nodes.append(MapNode(n["id"], title if n["id"] == CENTER else n["name"], n["x"], n["y"], n.get("color"),
                                 tuple(global_key(floor, b) for b in n["books"]), n["id"] == CENTER))
        return ProjectMap(floor, title, tuple(nodes), tuple(data["edges"]), stored, data["updated_at"])

    @locked
    def map_updated(self, user_id: str, floor: str) -> str:
        raw = self._load_map(user_id, floor)
        return str((raw or {}).get("updated_at") or "")

    @locked
    def node_of_book(self, user_id: str, key: str) -> tuple[str, str] | None:
        """책 주소 이름 → (프로젝트, 노드)."""
        floor = self.book_floor(user_id, key)
        if floor is None:
            return None
        found = self.get_map(user_id, floor)
        node = found.node_of(key) if found else None
        return (floor, node.id) if node else None

    @locked
    def book_floor(self, user_id: str, key: str) -> str | None:
        """책 주소 이름 → 그 책이 있는 프로젝트."""
        floor, local = local_key(key)
        if floor is not None:
            return floor
        if local.startswith("doc."):
            row = self._db.execute("SELECT floor FROM documents WHERE user_id = ? AND id = ?", (user_id, local[4:])).fetchone()
        else:
            row = self._db.execute("SELECT floor FROM categories WHERE user_id = ? AND id = ?", (user_id, local)).fetchone()
        return str(row[0]) if row else None

    @locked
    def cite_scope(self, user_id: str, floor: str) -> tuple[str, ...]:
        """그 프로젝트 원고의 인용 점검이 보는 문헌의 프로젝트: 자기 문헌 + 연결 노드가 가리키는 노드에 꽂힌 문헌(#95)."""
        layout = self._layout(user_id)
        known = self._known_floors(user_id, layout)
        out = [floor]
        if floor not in known:
            return tuple(out)
        data, _ = self._reconcile(user_id, floor, layout)
        for n in data["nodes"]:
            link = n.get("link")
            if not link or link["project"] not in known or link["project"] in out:
                continue
            target, _ = self._reconcile(user_id, link["project"], layout)
            source = next((m for m in target["nodes"] if m["id"] == link["node"]), None)
            if source is not None and "refs" in source.get("books", []):
                out.append(link["project"])
        return tuple(out)

    # ---- 노드·선 바꾸기 ---------------------------------------------------------------------------

    def _check_name(self, data: dict[str, Any], name: str, skip: str | None = None) -> str:
        try:
            clean = clean_node_name(name)
        except ValueError as e:
            raise MapError("bad_name", str(e)) from e
        if any("link" not in n and n["id"] not in (CENTER, skip) and name_key(n["name"]) == name_key(clean) for n in data["nodes"]):
            raise MapError("name_taken", f"같은 이름의 노드 「{clean}」가 있다", name=clean)
        return clean

    def _room(self, data: dict[str, Any]) -> None:
        if len(data["nodes"]) >= MAX_NODES:
            raise MapError("nodes_full", f"노드는 프로젝트마다 {MAX_NODES}개까지다")

    def _node(self, data: dict[str, Any], node_id: str) -> dict[str, Any]:
        found = next((n for n in data["nodes"] if n["id"] == node_id), None)
        if found is None:
            raise MapError("unknown_node", f"노드 {node_id!r}가 없다", node=node_id)
        return found

    def _place(self, data: dict[str, Any], x: float | None, y: float | None) -> tuple[float, float]:
        return (_num(x), _num(y)) if x is not None and y is not None else free_slot(data["nodes"])

    @locked
    def add_node(self, user_id: str, floor: str, name: str, *, x: float | None = None, y: float | None = None,
                 color: str | None = None) -> MapNode:
        """새 노드(가운데 노드와 잇는다)."""
        _, data = self._editable(user_id, floor)
        self._room(data)
        clean = self._check_name(data, name)
        nx, ny = self._place(data, x, y)
        node: dict[str, Any] = {"id": "n-" + new_id(), "name": clean, "x": nx, "y": ny, "books": []}
        if color and _HEX.fullmatch(color):
            node["color"] = color.lower()
        data["nodes"].append(node)
        data["edges"] = sorted({*map(tuple, data["edges"]), _edge(CENTER, node["id"])})
        self._write_map(user_id, floor, data)
        result = self.get_map(user_id, floor)
        assert result is not None
        return result.node(node["id"])  # type: ignore[return-value]

    @locked
    def add_link_node(self, user_id: str, floor: str, target_floor: str, target_node: str, *, x: float | None = None,
                      y: float | None = None) -> MapNode:
        """다른 프로젝트의 노드를 가리키는 연결 노드(가운데 노드와 잇는다). 연결 노드를 고르면 그 원본으로 잇는다."""
        layout, data = self._editable(user_id, floor)
        if target_floor not in self._known_floors(user_id, layout):
            raise MapError("unknown_floor", f"프로젝트 {target_floor!r}가 없다", floor=target_floor)
        target, _ = self._reconcile(user_id, target_floor, layout)
        source = next((n for n in target["nodes"] if n["id"] == target_node), None)
        if source is None:
            raise MapError("unknown_node", f"노드 {target_node!r}가 없다", node=target_node)
        if "link" in source:  # 연결의 연결은 만들지 않는다: 원본으로
            target_floor, target_node = source["link"]["project"], source["link"]["node"]
            target, _ = self._reconcile(user_id, target_floor, layout)
        if target_floor == floor:
            raise MapError("link_self", "같은 프로젝트의 노드는 연결 노드로 만들지 않는다(선으로 잇는다)")
        if any(n.get("link") == {"project": target_floor, "node": target_node} for n in data["nodes"]):
            raise MapError("link_exists", "이미 이 지도에 연결돼 있다")
        self._room(data)
        nx, ny = self._place(data, x, y)
        nid, k = link_id(target_floor, target_node), 2
        while any(n["id"] == nid for n in data["nodes"]):
            nid, k = f"{link_id(target_floor, target_node)}-{k}", k + 1
        data["nodes"].append({"id": nid, "x": nx, "y": ny, "link": {"project": target_floor, "node": target_node}})
        data["edges"] = sorted({*map(tuple, data["edges"]), _edge(CENTER, nid)})
        self._write_map(user_id, floor, data)
        result = self.get_map(user_id, floor)
        assert result is not None
        return result.node(nid)  # type: ignore[return-value]

    @locked
    def ensure_link(self, user_id: str, floor: str, target_floor: str, kind: str) -> MapNode | None:
        """floor의 지도에 target_floor의 그 기본 책(kind)이 꽂힌 노드로 가는 연결 노드가 없으면 붙인다(문헌을 「내 서재」로 옮길 때).
        이미 있으면 None. 같은 프로젝트거나 그 책이 없으면 None."""
        layout = self._layout(user_id)
        if floor == target_floor or floor not in self._known_floors(user_id, layout):
            return None
        target, _ = self._reconcile(user_id, target_floor, layout)
        source = next((n for n in target["nodes"] if kind in n.get("books", [])), None)
        data, _ = self._reconcile(user_id, floor, layout)
        if source is None or any(n.get("link") == {"project": target_floor, "node": source["id"]} for n in data["nodes"]):
            return None
        try:
            return self.add_link_node(user_id, floor, target_floor, source["id"])
        except MapError:
            return None

    @locked
    def update_node(self, user_id: str, floor: str, node_id: str, *, name: str | None = None, color: str | None = None,
                    x: float | None = None, y: float | None = None) -> MapNode:
        """이름(가운데·연결 노드는 못 바꿈)·색(""이면 지움)·위치."""
        _, data = self._editable(user_id, floor)
        node = self._node(data, node_id)
        if name is not None:
            if node_id == CENTER or "link" in node:
                raise MapError("center_name" if node_id == CENTER else "link_name",
                               "가운데 노드 이름은 프로젝트 제목이다" if node_id == CENTER else "연결 노드 이름은 원본 노드 이름이다")
            node["name"] = self._check_name(data, name, skip=node_id)
        if color is not None:
            if color and not _HEX.fullmatch(color):
                raise MapError("bad_color", f"색은 #RRGGBB: {color!r}")
            node.pop("color", None)
            if color:
                node["color"] = color.lower()
        if x is not None and y is not None:
            node["x"], node["y"] = _num(x), _num(y)
        self._write_map(user_id, floor, data)
        result = self.get_map(user_id, floor)
        assert result is not None
        return result.node(node_id)  # type: ignore[return-value]

    @locked
    def connect_nodes(self, user_id: str, floor: str, a: str, b: str) -> bool:
        """선 잇기. 이미 이어져 있으면 False."""
        _, data = self._editable(user_id, floor)
        self._node(data, a)
        self._node(data, b)
        if a == b:
            raise MapError("same_node", "같은 노드끼리는 잇지 않는다")
        edges = set(map(tuple, data["edges"]))
        if _edge(a, b) in edges:
            return False
        data["edges"] = sorted({*edges, _edge(a, b)})
        self._write_map(user_id, floor, data)
        return True

    @locked
    def disconnect_nodes(self, user_id: str, floor: str, a: str, b: str) -> bool:
        """선 끊기. 선이 없으면 False."""
        _, data = self._editable(user_id, floor)
        edges = set(map(tuple, data["edges"]))
        if _edge(a, b) not in edges:
            return False
        data["edges"] = sorted(edges - {_edge(a, b)})
        self._write_map(user_id, floor, data)
        return True

    @locked
    def trash_node(self, user_id: str, floor: str, node_id: str, note: str) -> MapNode:
        """노드를 휴지통으로(trash/shelf/nodes/<프로젝트>/<노드>.json, 이어진 선과 함께). 가운데 노드와 책이 꽂힌 노드는 옮기지 않는다
        (책을 먼저 옮긴다). 연결 노드는 옮겨도 원본은 그대로다."""
        _, data = self._editable(user_id, floor)
        node = self._node(data, node_id)
        if node_id == CENTER:
            raise MapError("center", "가운데 노드는 휴지통으로 옮기지 않는다")
        if node.get("books"):
            raise MapError("not_empty", "책이 꽂힌 노드는 휴지통으로 옮기지 않는다", books=len(node["books"]))
        shown = self.get_map(user_id, floor)
        before = shown.node(node_id) if shown else None
        edges = [e for e in data["edges"] if node_id in e]
        write_json(self._user_dir(user_id) / "trash" / "shelf" / "nodes" / floor / f"{node_id}.json",
                   {**node, "edges": [list(e) for e in edges], "_trash": {"at": utcnow(), "note": note}})
        data["nodes"] = [n for n in data["nodes"] if n["id"] != node_id]
        data["edges"] = [e for e in data["edges"] if node_id not in e]
        self._write_map(user_id, floor, data)
        assert before is not None
        return before

    def _drop_empty_node(self, user_id: str, floor: str, node_id: str) -> None:
        """옮기기로 생겼던 노드를 되돌리기 뒤에 치운다(비어 있고 연결 노드가 가리키지 않을 때만). 휴지통에 남기지 않는다."""
        layout = self._layout(user_id)
        data, _ = self._reconcile(user_id, floor, layout)
        node = next((n for n in data["nodes"] if n["id"] == node_id), None)
        if node is None or node_id == CENTER or "link" in node or node.get("books"):
            return
        for other in self._known_floors(user_id, layout):
            if other != floor and any(n.get("link") == {"project": floor, "node": node_id}
                                      for n in self._reconcile(user_id, other, layout)[0]["nodes"]):
                return
        data["nodes"] = [n for n in data["nodes"] if n["id"] != node_id]
        data["edges"] = [e for e in data["edges"] if node_id not in e]
        self._write_map(user_id, floor, data)

    def _trashed_nodes(self, user_id: str) -> list[tuple[str, dict[str, Any]]]:
        base = self._user_dir(user_id) / "trash" / "shelf" / "nodes"
        return [(f"{p.parent.name}/{p.stem}", read_json(p)) for p in sorted(base.glob("*/*.json"))]

    def _restore_node(self, user_id: str, ref: str) -> list[str]:
        floor, _, node_id = ref.partition("/")
        path = self._user_dir(user_id) / "trash" / "shelf" / "nodes" / floor / f"{node_id}.json"
        if not valid_node_id(node_id) or not valid_node_id(floor) or not path.exists():
            raise ValueError(f"휴지통에 노드 {ref}가 없다")
        record = read_json(path)
        _, data = self._editable(user_id, floor)
        self._room(data)
        node = {k: v for k, v in record.items() if k not in ("_trash", "edges")}
        if any(n["id"] == node["id"] for n in data["nodes"]):
            node["id"] = "n-" + new_id()
        if "link" not in node:
            node["books"] = []
            if any("link" not in n and n["id"] != CENTER and name_key(n["name"]) == name_key(node.get("name", "")) for n in data["nodes"]):
                node["name"] = f"{node.get('name', '노드')}(되살림)"[:20]
        ids = {n["id"] for n in data["nodes"]}
        data["nodes"].append(node)
        restored = {_edge(node["id"], b if a == node_id else a) for a, b in record.get("edges") or [] if (b if a == node_id else a) in ids}
        data["edges"] = sorted({*map(tuple, data["edges"]), *restored})
        self._write_map(user_id, floor, data)
        path.unlink()
        return [f"{floor}/{node['id']}"]

    # ---- 책 놓기 ------------------------------------------------------------------------------

    @locked
    def place_book(self, user_id: str, floor: str, key: str, node_id: str) -> tuple[str | None, str]:
        """그 프로젝트 안에서 책을 노드에 놓는다. (전에 있던 노드, 놓은 노드). 원고 책은 가운데에만."""
        _, data = self._editable(user_id, floor)
        node = self._node(data, node_id)
        if "link" in node:
            raise MapError("link_node", "연결 노드에는 책을 놓지 않는다(원본 노드에 놓는다)")
        _, local = local_key(key)
        if local == "ms" and node_id != CENTER:
            raise MapError("ms_center", "원고 책은 가운데 노드에만 둔다")
        before = next((n for n in data["nodes"] if local in n.get("books", [])), None)
        if before is None:
            raise MapError("unknown_book", f"이 프로젝트에 책 {key!r}가 없다")
        if before is node:
            return node_id, node_id
        if len(node["books"]) >= MAX_BOOKS_PER_NODE:
            raise MapError("node_full", f"노드 하나에 책은 {MAX_BOOKS_PER_NODE}권까지다", node=node_id)
        before["books"].remove(local)
        node["books"].append(local)
        self._write_map(user_id, floor, data)
        return before["id"], node_id
