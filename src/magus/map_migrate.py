"""지도 이전(#95): 층 구조(#93) 또는 그 전(사람 소유 카테고리) → 프로젝트·지도. 운영자 CLI `magus maps plan|apply|revert`가 쓴다.

이전 규칙(store.maps의 계산한 지도와 같다): 작업물 → 프로젝트, 공용 층 → 「내 서재」. 원고 책·문서 책 → 가운데 노드.
모음 책(생각·문체·문헌·저자의 카테고리) → 이름이 같은 노드 하나씩(가운데와 이음). 프로젝트가 쓰던 「내 서재」의 문헌(과, 자기 문체가 없으면
문체)은 그 프로젝트 지도에 연결 노드로 붙인다. 그래서 인용 점검이 보는 문헌(자기 + 연결 노드)이 이전 규칙(그 층 + 공용)과 같다.
층 이전 전 데이터는 층 배치부터 적는다(magus floors apply와 같은 일). 그래서 어느 데이터에서 시작해도 같은 지도가 된다.

- plan: 무엇이 어디로 가는지(프로젝트마다 노드·책·연결·선)와 지금의 항목 수·인용 점검 결과. 아무것도 쓰지 않는다.
- apply: 백업(사용자 폴더의 shelf/를 --backup 아래에 복사) 뒤 층 배치와 지도를 파일로 적는다. 인덱스를 다시 만들고,
  이전 전후의 항목 수·인용 점검 결과(확인·미확인·참고문헌에 없음·미연결, 전체 현황 수)가 같은지 비교해 보인다.
  인용 점검은 옛 규칙(그 층 + 공용)으로 낸 값과도 견준다.
- revert: 옛 코드(층 전)로 되돌리기 전에. 항목 파일의 "floor"를 떼고 floors.json과 지도 폴더를 옆으로 비켜 둔다(지우지 않음).

#96(컨텍스트): apply는 지도를 적은 뒤 책 이전(magus.book_migrate.convert)까지 한다: 옛 기본 카테고리 → 이름이 같은 책 + 컨텍스트,
생각·문체 → 그 책의 글, 문헌 → 책을 적음, 원고 책·문서 책 → 컨텍스트. revert는 책 이전부터 거꾸로 한다.
비교는 종류별 글 수(옛 생각·문체·문헌·저자 카테고리), 장별 인용 점검, 전체 현황 수, 확인 요청 수, 수정본 이력이다.
"""

from __future__ import annotations

import shutil
from collections import Counter
from pathlib import Path
from typing import Any

from magus import book_migrate
from magus.category.maptext import Counts, project_block
from magus.floors import COMMON
from magus.ids import utcnow
from magus.maps import LIBRARY_NAME
from magus.melchior.check import Resolver, after_refs_changed, check_text, terms_of
from magus.store import LocalStore
from magus.store.fileio import read_json


def _counts(store: LocalStore, user_id: str) -> dict[str, int]:
    """종류별 글 수. 이전 전(옛 생각·문체 파일)과 뒤(옛 종류를 적은 책의 글)를 같은 이름으로 센다. 휴지통은 세지 않는다."""
    shelf = store.root / "users" / user_id / "shelf"
    legacy: dict[str, str] = {}
    for path in shelf.glob("categories/*/category.json"):
        kind = read_json(path).get(book_migrate.LEGACY)
        if kind:
            legacy[path.parent.name] = str(kind)
    items = store.list_category_items(user_id)
    count = {kind: sum(1 for i in items if legacy.get(i.category_id) == kind) for kind in ("ideas", "styles")}
    return {
        "ideas": len(list((shelf / "casper").glob("*.json"))) + count["ideas"],
        "styles": len(list((shelf / "balthasar").glob("*.json"))) + count["styles"],
        "categories": sum(1 for c in store.list_categories(user_id) if c.id not in legacy),
        "category_items": sum(1 for i in items if i.category_id not in legacy),
    }


def snapshot(store: LocalStore, user_id: str, rule: str = "map") -> dict[str, Any]:
    """비교용: 종류별 글 수, 프로젝트마다 장별 인용 점검(확인·미확인·없음·미연결 고유 수)·전체 현황 머리 수·확인 요청 수·수정본 이력.
    rule="floors"면 인용 점검을 옛 규칙(그 프로젝트 + 「내 서재」)으로 낸다."""
    out: dict[str, Any] = {
        **_counts(store, user_id),
        "refs": len(store.list_refs(user_id)), "refs_verified": len(store.list_refs(user_id, "verified")),
        "documents": len(store.list_documents(user_id)), "projects": {},
    }
    for project in sorted(store.list_projects(user_id), key=lambda p: p.id):
        resolver, terms = Resolver(store, user_id, project.id), terms_of(store, user_id, project.id)
        if rule == "floors":
            resolver.floors = (project.id, COMMON)
        totals: Counter = Counter()
        chapters = {}
        unchecked: set[str] = set()
        unlinked: set[str] = set()
        for meta in store.list_chapters(user_id, project.id):
            chapter = store.read_chapter(user_id, project.id, meta.number)
            if chapter is None:
                continue
            result = check_text(store, user_id, chapter.content, resolver, terms)
            counts = Counter(g.status for g in result.groups)
            totals.update(counts)
            chapters[meta.number] = (counts["verified"], result.unchecked_count, len(result.uncertain_keys))
            unchecked.update(result.unchecked_keys)
            unlinked.update(result.uncertain_keys)
        issues = store.list_issues(user_id, project.id, None)
        out["projects"][project.id] = {
            "verified": totals["verified"], "unverified": totals["unverified"], "unknown": totals["unknown"],
            "uncertain": totals["uncertain"], "chapters": chapters,
            "outline_unique_unverified": len(unchecked), "outline_unlinked": len(unlinked),
            "issues": dict(sorted(Counter(f"{i.status}·{i.kind}" for i in issues).items())),
            "editions": [(e.number, e.file, e.changed, e.added, e.removed, e.unchanged) for e in store.list_editions(user_id, project.id)],
        }
    return out


def summary_lines(snap: dict[str, Any]) -> list[str]:
    lines = [f"- 글: 생각 {snap['ideas']} · 문체 {snap['styles']} · 문헌 {snap['refs']}(확인 {snap['refs_verified']}) · "
             f"저자의 책(옛 카테고리) {snap['categories']}(글 {snap['category_items']}) · 문서 {snap['documents']}"]
    for pid, p in snap["projects"].items():
        issues = p.get("issues") or {}
        opened = sum(n for k, n in issues.items() if k.startswith("open"))
        lines.append(f"- 프로젝트 {pid}: 인용 점검(장별 고유 합) 확인 {p['verified']} · 미확인 {p['unverified']} · "
                     f"참고문헌에 없음 {p['unknown']} · 미연결 {p['uncertain']} · 전체 현황 '미확인 문헌' {p['outline_unique_unverified']}편 · "
                     f"미연결 {p['outline_unlinked']} · 확인 요청 {sum(issues.values())}(열림 {opened}) · "
                     f"수정본 {len(p.get('editions') or [])}개")
    return lines


def state(store: LocalStore, user_id: str) -> str:
    shelf = store.root / "users" / user_id / "shelf"
    if not book_migrate.needs(store, user_id) and (shelf / "floors.json").exists():
        return "책·컨텍스트까지 바꿈(#96)"
    if (shelf / "maps").exists() and any((shelf / "maps").glob("*.json")):
        return "지도까지 적힘(#95)"
    return "층 배치만 적힘(#93)" if (shelf / "floors.json").exists() else "이전 전(층 배치 파일 없음)"


def map_lines(store: LocalStore, user_id: str) -> list[str]:
    counts = Counts(store, user_id)
    lines = []
    for floor in store.list_floors(user_id):
        head = f"- 프로젝트 {LIBRARY_NAME}" if floor.common else f"- 프로젝트 「{floor.title}」({floor.id})"
        block = project_block(store, user_id, floor.id, counts, header=head)
        lines += [block[0], *(f"  {line}" for line in block[1:])]
    return lines


def plan(store: LocalStore, user_id: str) -> list[str]:
    before, old = snapshot(store, user_id), snapshot(store, user_id, "floors")
    return [f"사용자 {user_id}: {state(store, user_id)}", *map_lines(store, user_id), "지금의 항목 수·인용 점검:", *summary_lines(before),
            "옛 규칙(그 층 + 공용)으로 낸 인용 점검과: " + ("같음" if old == before else "다름 — 이 지도로는 인용 점검 결과가 바뀐다")]


def apply(store: LocalStore, user_id: str, backup: Path) -> tuple[list[str], bool]:
    """(보고 줄, 전후가 같은가)."""
    before, old = snapshot(store, user_id), snapshot(store, user_id, "floors")
    shelf = store.root / "users" / user_id / "shelf"
    target = backup / f"{user_id}-shelf-{utcnow().replace(':', '').replace('.', '')}"
    if shelf.exists():
        shutil.copytree(shelf, target)
    lines = [f"백업: {target}" if shelf.exists() else "백업: 책장 폴더가 없어 복사할 것이 없음", f"이전 전 상태: {state(store, user_id)}"]
    made = store.ensure_maps(user_id)
    converted = book_migrate.convert(store, user_id)  # #96: 옛 종류 → 책 + 컨텍스트
    store.reindex()
    after_refs_changed(store, user_id)
    after = snapshot(store, user_id)
    same = before == after == old
    lines += [f"지도를 적은 프로젝트 {len(made)}개",
              "책 이전(#96): " + (" · ".join(f"{k} {v}" for k, v in converted.items()) or "바꿀 것 없음(이미 바꿈)"),
              *map_lines(store, user_id),
              "이전 전:", *summary_lines(before), "이전 뒤:", *summary_lines(after),
              "옛 규칙(그 층 + 공용)으로 낸 인용 점검과 이전 뒤: " + ("같음" if old == after else "다름"),
              "전후 비교: " + ("같음(항목 수·장별 인용 점검·전체 현황 수)" if same else "다름 — 위 묶음을 비교한다")]
    return lines, same


def revert(store: LocalStore, user_id: str) -> list[str]:
    """옛 코드(층 전)로 되돌리기 전에: 책 이전(#96)을 거꾸로 하고, 항목 파일의 "floor"를 떼고, floors.json과 지도 폴더를 비켜 둔다."""
    books = book_migrate.revert_books(store, user_id)
    counts = {**books, **store.revert_floors(user_id)}
    maps = store.root / "users" / user_id / "shelf" / "maps"
    if maps.exists():
        maps.rename(maps.with_name(f"maps.reverted-{utcnow().replace(':', '').replace('.', '')}"))
        counts["maps"] = 1
    store.reindex()
    after_refs_changed(store, user_id)
    return [f"지도 되돌리기 {user_id}: " + (" · ".join(f"{k} {v}" for k, v in counts.items()) or "바꿀 것 없음"),
            "이제 옛 코드(층 전)로 되돌려도 항목 파일을 읽는다. 이전 뒤에 만든 프로젝트는 원고 없는 책으로 남는다."]
