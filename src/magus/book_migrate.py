"""책 이전(사용자 결정 #96, 2026-10-08): 종류(기본 카테고리 생각·문체·문헌, 원고 책·문서 책) → 여느 책 + 컨텍스트.

magus maps apply가 지도 이전(#95) 바로 뒤에 부른다(층 배치·지도 파일을 먼저 적은 상태에서). 그래서 층 이전 전 데이터와
층·지도 이전 뒤 데이터 어느 쪽에서 시작해도 같은 결과가 된다(책 id가 종류와 프로젝트로 정해진다).

- 옛 기본 카테고리(프로젝트마다 종류 하나) → 이름이 같은 책(카테고리) 하나. id는 '<종류>-<프로젝트>'(legacy_book_id),
  category.json의 "legacy"에 옛 종류를 남긴다(되돌리기가 본다). 색은 그 종류의 책 색. 컨텍스트: 생각 → 「생각 메모」, 문체 → 「문체」,
  문헌 → 「논문」(처음 제공하는 자주 쓰는 컨텍스트의 사본).
- 생각(shelf/casper/<id>.json) → 그 책의 글(items/<id>.json): 내용 = text, 제목·누가·고친 기록·응답한 글(parent_id)·출처(origin)·
  옛 갈래(kind)는 그대로. 문체(shelf/balthasar) → 글: 내용 = 구절, 이유, 위치 = 출전(work), 태그 = '키: 값' 목록, tags_by.
  id·작성 시각은 그대로다. 휴지통의 생각·문체도 그 책의 글 휴지통으로 옮긴다.
- 문헌(shelf/melchior/<key>/bib.json) → "book"을 적는다(그 프로젝트의 옛 문헌 책). 확인·발췌·전문·옮긴 기록은 그대로다.
- 원고 책(장이 있는 프로젝트) → project.json "contexts" = 「원고」. 문서 책 → document.json "contexts" = 출처 확인 문서 설명.
- 지도 파일의 책 이름 ideas·styles·refs → 새 책 id(노드·선·위치는 그대로).
- floors.json → schema_version 2(기본 카테고리 없음). 마지막 옮기기 기록은 지운다(옛 종류를 가리켜 되돌릴 수 없다).
- 되돌리기(revert_books): 위를 거꾸로. 이전 뒤 그 책에 쌓인 글도 옛 형식으로 돌려 적는다. 옛 문헌 책에 생긴 글(옛 형식에 자리가 없다)이
  있으면 그 책을 「문헌(글)」이라는 저자의 카테고리로 남긴다. 책 폴더는 지우지 않고 shelf/categories.reverted-<시각>/로 비켜 둔다.
"""

from __future__ import annotations

import hashlib
import shutil
from collections import Counter
from pathlib import Path
from typing import Any

from magus.balthasar.style import LIST_KEYS, TAG_KEYS
from magus.category.rules import BUILTINS, DEFAULT_COLORS, ITEM_SCHEMA, SCHEMA_VERSION, name_key
from magus.contexts import DEFAULTS, LEGACY_CONTEXT, SOURCE_CHECK, Context, to_record
from magus.floors import BOOKS_SCHEMA, BUILTIN_ORDER, COMMON, FLOORS_SCHEMA
from magus.ids import utcnow
from magus.store.fileio import read_json, write_json

LEGACY = "legacy"  # category.json: 옛 기본 카테고리 종류(ideas|styles|refs)
REVERTED_REFS_NAME = "문헌(글)"
_KIND_DIRS = {"ideas": "casper", "styles": "balthasar"}


def legacy_book_id(kind: str, floor: str) -> str:
    raw = f"{kind}-{floor}"
    return raw if len(raw) <= 64 else f"{kind}-{hashlib.sha256(floor.encode()).hexdigest()[:12]}"


def _context(kind: str) -> Context:
    saved = next(c for c in DEFAULTS if c.id == LEGACY_CONTEXT[kind])
    return Context(saved.name, saved.text)


def _stamp() -> str:
    return utcnow().replace(":", "").replace(".", "")


def needs(store: Any, user: str) -> bool:
    """옛 형식(#96 전)이 남아 있나: 생각·문체 파일, 책이 없는 문헌, 기본 카테고리를 적은 층 배치(schema 1)."""
    shelf = store.root / "users" / user / "shelf"
    if store.has_legacy_shelf(user):
        return True
    path = shelf / "floors.json"
    return path.exists() and int(read_json(path).get("schema_version") or 1) < BOOKS_SCHEMA


def _style_tags(tags: Any) -> list[str]:
    out: list[str] = []
    for key in TAG_KEYS:
        value = (tags or {}).get(key) if isinstance(tags, dict) else None
        values = value if isinstance(value, list) else [value] if value else []
        out += [f"{key}: {v}" for v in values if str(v).strip()]
    return out


def _tags_back(tags: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {k: [] if k in LIST_KEYS else "" for k in TAG_KEYS}
    for tag in tags:
        key, sep, value = str(tag).partition(":")
        key, value = key.strip(), value.strip()
        if not sep or key not in TAG_KEYS or not value:
            continue
        if key in LIST_KEYS:
            out[key].append(value)
        elif not out[key]:
            out[key] = value
    return out


def _idea_item(data: dict[str, Any]) -> dict[str, Any]:
    item: dict[str, Any] = {
        "schema_version": ITEM_SCHEMA, "id": data["id"], "title": data.get("title") or None, "title_by": data.get("title_by"),
        "content": str(data.get("text") or ""), "fields": {}, "author": "ai" if data.get("author") == "ai" else "me",
        "tags": [], "chapters": [], "created_at": data.get("created_at") or "",
        "updated_at": data.get("edited_at") or data.get("created_at") or "",
    }
    if data.get("edited_by"):
        item.update(edited_at=data.get("edited_at"), edited_by=data["edited_by"])
    for key in ("parent_id", "origin", "kind"):
        if data.get(key):
            item[key] = data[key]
    return item


def _style_item(data: dict[str, Any]) -> dict[str, Any]:
    item: dict[str, Any] = {
        "schema_version": ITEM_SCHEMA, "id": data["id"], "title": None, "title_by": None,
        "content": str(data.get("passage") or ""), "fields": {}, "author": "me", "tags": _style_tags(data.get("tags")),
        "chapters": [], "created_at": data.get("created_at") or "", "updated_at": data.get("created_at") or "",
    }
    if str(data.get("reason") or "").strip():
        item["reason"] = data["reason"]
    if data.get("work"):
        item["where"] = data["work"]
    if data.get("tags_by"):
        item["tags_by"] = data["tags_by"]
    return item


def _idea_back(item: dict[str, Any], floor: str) -> dict[str, Any]:
    """글 → 옛 생각. 칸(fields)·이유·위치처럼 옛 생각에 없는 칸은 내용 끝에 줄로 붙인다(잃지 않게)."""
    extra = [f"{k}: {v}" for k, v in (item.get("fields") or {}).items() if v]
    extra += [f"이유: {item['reason']}"] if item.get("reason") else []
    extra += [f"위치: {item['where']}"] if item.get("where") else []
    text = "\n".join([str(item.get("content") or ""), *extra]).strip() or str(item.get("title") or "")
    author = "ai" if item.get("author") == "ai" else "me"
    out: dict[str, Any] = {"id": item["id"], "text": text, "kind": item.get("kind") or ("thought" if author == "me" else "ai"),
                           "author": author, "origin": item.get("origin"), "parent_id": item.get("parent_id"),
                           "created_at": item.get("created_at") or "", "floor": floor}
    for key in ("title", "title_by", "edited_at", "edited_by"):
        if item.get(key):
            out[key] = item[key]
    return out


def _style_back(item: dict[str, Any], floor: str) -> dict[str, Any]:
    return {"id": item["id"], "passage": str(item.get("content") or item.get("title") or ""),
            "reason": str(item.get("reason") or "(저자가 이유를 밝히지 않음)"), "tags": _tags_back(item.get("tags") or []),
            "work": item.get("where"), "created_at": item.get("created_at") or "", "tags_by": item.get("tags_by"), "floor": floor}


def convert(store: Any, user: str) -> Counter:
    """층 배치·지도가 파일로 적힌 상태(schema 1)에서 부른다. 이미 바꿨으면(schema 2) 아무것도 하지 않는다. 바꾼 것을 센다."""
    counts: Counter = Counter()
    udir = store.root / "users" / user
    shelf = udir / "shelf"
    layout = store._layout(user)
    if layout.books:
        return counts
    known = [COMMON, *store._existing(user, layout)]
    settings = store.get_shelf_settings(user)

    def floor_of(data: dict[str, Any], kind: str) -> str:
        return data["floor"] if data.get("floor") in known else layout.fallback(kind)

    # 1) 어느 책을 만들지: 층 배치에 꽂힌 기본 카테고리 + 항목이 있는 (종류, 프로젝트)
    sources: dict[tuple[str, str], list[tuple[Path, dict[str, Any]]]] = {}
    for kind, folder in _KIND_DIRS.items():
        for path in sorted((shelf / folder).glob("*.json")):
            data = read_json(path)
            sources.setdefault((kind, floor_of(data, kind)), []).append((path, data))
    refs = [(p, read_json(p)) for p in sorted((shelf / "melchior").glob("*/bib.json"))]
    for path, data in refs:
        sources.setdefault(("refs", floor_of(data, "refs")), []).append((path, data))
    need = {(k, f) for f in known for k in layout.kinds(f)} | set(sources)
    order = {f: n for n, f in enumerate(known)}
    taken = {(str(r.get("floor") or COMMON), name_key(str(r.get("name") or "")))
             for r in (read_json(p) for p in (shelf / "categories").glob("*/category.json"))}
    made_at = {pdir.name: str(read_json(pdir / "project.json").get("created_at") or "")
               for pdir in (udir / "projects").glob("*") if (pdir / "project.json").exists()}
    stamps = sorted([t for t in made_at.values() if t] + [str(d.get("created_at")) for items in sources.values()
                                                           for _, d in items if d.get("created_at")])
    earliest = stamps[0] if stamps else ""
    made: dict[tuple[str, str], str] = {}
    for kind, floor in sorted(need, key=lambda kf: (order.get(kf[1], 99), BUILTIN_ORDER.index(kf[0]))):
        book = legacy_book_id(kind, floor)
        items = sources.get((kind, floor), [])
        times = sorted(str(d.get("created_at") or "") for _, d in items if d.get("created_at"))
        # 빈 책의 만든 시각은 그 프로젝트의 것(「내 서재」면 가장 이른 프로젝트·글): 어느 경로로 이전해도 같은 결과가 되게
        created = times[0] if times else made_at.get(floor) or earliest or utcnow()
        name, n = BUILTINS[kind], 2
        while (floor, name_key(name)) in taken:  # 같은 이름의 책이 이미 있으면(정해진 이름이라 보통 없다) 뒤에 번호
            name, n = f"{BUILTINS[kind]} {n}", n + 1
            counts["이름 바꿈"] += 1
        taken.add((floor, name_key(name)))
        write_json(shelf / "categories" / book / "category.json", {
            "schema_version": SCHEMA_VERSION, "id": book, "name": name, "template": "blank",
            "color": settings.colors.get(kind, DEFAULT_COLORS[kind]), "fields": [], "created_at": created,
            "updated_at": times[-1] if times else created, "floor": floor, "contexts": to_record((_context(kind),)), LEGACY: kind,
        })
        made[(kind, floor)] = book
        counts[f"책 「{BUILTINS[kind]}」"] += 1

    # 2) 항목 옮기기(먼저 쓰고 지운다)
    for (kind, floor), items in sources.items():
        book = made[(kind, floor)]
        for path, data in items:
            if kind == "refs":
                write_json(path, {**data, "floor": floor, "book": book})
                counts["문헌에 책 적음"] += 1
                continue
            item = _idea_item(data) if kind == "ideas" else _style_item(data)
            write_json(shelf / "categories" / book / "items" / f"{data['id']}.json", item)
            path.unlink()
            counts["생각 → 글" if kind == "ideas" else "문체 → 글"] += 1

    # 3) 휴지통의 생각·문체 → 그 책의 글 휴지통
    trash = udir / "trash" / "shelf"
    for kind, folder in _KIND_DIRS.items():
        for path in sorted((trash / folder).glob("*.json")):
            data = read_json(path)
            book = made.get((kind, floor_of(data, kind))) or next((b for (k, _), b in made.items() if k == kind), None)
            if book is None:
                counts["휴지통 그대로(책 없음)"] += 1
                continue
            item = _idea_item(data) if kind == "ideas" else _style_item(data)
            write_json(trash / "category-items" / book / f"{data['id']}.json", {**item, "_trash": data.get("_trash") or {}})
            path.unlink()
            counts["휴지통 글"] += 1

    # 4) 지도: 책 이름 ideas·styles·refs → 새 책 id
    for floor in known:
        path = shelf / "maps" / f"{floor}.json"
        if not path.exists():
            continue
        data = read_json(path)
        for node in data.get("nodes") or []:
            if isinstance(node, dict) and isinstance(node.get("books"), list):
                node["books"] = [made.get((b, floor), b) if b in BUILTINS else b for b in node["books"]]
        write_json(path, data)
        counts["지도"] += 1

    # 5) 원고 책·문서 책의 컨텍스트
    for pdir in sorted((udir / "projects").glob("*")):
        pj = pdir / "project.json"
        if pj.exists() and any((pdir / "book").glob("ch-*.md")) and not read_json(pj).get("contexts"):
            write_json(pj, {**read_json(pj), "contexts": to_record((_context("ms"),))})
            counts["원고 컨텍스트"] += 1
    for path in sorted((shelf / "documents").glob("*/document.json")):
        if not read_json(path).get("contexts"):
            write_json(path, {**read_json(path), "contexts": to_record((SOURCE_CHECK,))})
            counts["문서 컨텍스트"] += 1

    # 6) 층 배치: 기본 카테고리 없음(schema 2)
    write_json(shelf / "floors.json", {"schema_version": BOOKS_SCHEMA, "order": layout.order, "changed_at": layout.changed_at,
                                       "last_move": None, "last_undone": None})
    return counts


def revert_books(store: Any, user: str) -> Counter:
    """#96 이전을 거꾸로(옛 코드 #95로 되돌리기 전에). 층 배치는 schema 1(기본 카테고리)로 적는다."""
    counts: Counter = Counter()
    udir = store.root / "users" / user
    shelf = udir / "shelf"
    floors_path = shelf / "floors.json"
    if not floors_path.exists() or int(read_json(floors_path).get("schema_version") or 1) < BOOKS_SCHEMA:
        return counts
    layout = store._layout(user)
    stamp = _stamp()
    aside = shelf / f"categories.reverted-{stamp}"
    builtins: dict[str, list[str]] = {}
    back: dict[str, tuple[str, str]] = {}  # 새 책 id → (옛 종류, 프로젝트)
    for cpath in sorted((shelf / "categories").glob("*/category.json")):
        record = read_json(cpath)
        kind = record.get(LEGACY)
        if kind not in BUILTINS:
            continue
        book, floor = cpath.parent.name, str(record.get("floor") or COMMON)
        back[book] = (kind, floor)
        builtins.setdefault(floor, [])
        if kind not in builtins[floor]:
            builtins[floor].append(kind)
        items = sorted((cpath.parent / "items").glob("*.json"))
        if kind == "refs" and items:  # 옛 문헌 책에 생긴 글: 옛 형식에 자리가 없어 저자의 카테고리로 남긴다
            write_json(cpath, {k: v for k, v in {**record, "name": REVERTED_REFS_NAME}.items() if k not in (LEGACY, "contexts")})
            counts["문헌 책의 글을 카테고리로 남김"] += len(items)
            continue
        for path in items:
            item = read_json(path)
            folder = shelf / _KIND_DIRS[kind]
            write_json(folder / f"{item['id']}.json", (_idea_back if kind == "ideas" else _style_back)(item, floor))
            path.unlink()
            counts["글 → 생각" if kind == "ideas" else "글 → 문체"] += 1
        tdir = udir / "trash" / "shelf" / "category-items" / book
        for path in sorted(tdir.glob("*.json")):
            item = read_json(path)
            mark = item.get("_trash") or {}
            write_json(udir / "trash" / "shelf" / _KIND_DIRS[kind] / f"{item['id']}.json",
                       {**(_idea_back if kind == "ideas" else _style_back)(item, floor), "_trash": mark})
            path.unlink()
            counts["휴지통 글 되돌림"] += 1
        aside.mkdir(parents=True, exist_ok=True)
        shutil.move(str(cpath.parent), str(aside / book))
        counts[f"책 「{record.get('name')}」 비켜 둠"] += 1

    # 문헌: "book"을 뗀다. 옛 형식은 프로젝트마다 문헌 책 하나라, 문헌이 있는 프로젝트에는 문헌 기본 카테고리를 꽂는다
    for path in sorted((shelf / "melchior").glob("*/bib.json")):
        data = read_json(path)
        if "book" in data:
            write_json(path, {k: v for k, v in data.items() if k != "book"})
            counts["문헌 책 뗌"] += 1
        floor = str(data.get("floor") or COMMON)
        if "refs" not in builtins.setdefault(floor, []):
            builtins[floor].append("refs")

    # 지도: 새 책 id → 옛 이름. 문헌이 든 저자의 책은 그대로 둔다(문헌은 옛 문헌 책으로 보인다)
    for mpath in sorted((shelf / "maps").glob("*.json")):
        data = read_json(mpath)
        floor = mpath.stem
        for node in data.get("nodes") or []:
            if isinstance(node, dict) and isinstance(node.get("books"), list):
                node["books"] = [back[b][0] if b in back and back[b][1] == floor else b for b in node["books"]
                                 if not (b in back and back[b][1] != floor)]
        write_json(mpath, data)
        counts["지도"] += 1

    known = [COMMON, *store._existing(user, layout)]
    write_json(floors_path, {
        "schema_version": FLOORS_SCHEMA, "order": layout.order,
        "builtins": {f: [k for k in BUILTIN_ORDER if k in builtins.get(f, [])] for f in known},
        "changed_at": layout.changed_at, "last_move": None, "last_undone": None,
    })
    return counts
