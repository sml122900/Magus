"""층 이전(#93): 사람 소유 카테고리(옛 구조) → 층 구조. 운영자 CLI `magus floors plan|apply|revert`가 쓴다.

이전 규칙: 기존 작업물 → 1층(여럿이면 만든 순서대로 1층, 2층…), 생각 → 1층, 문헌 → 1층(작업물이 둘 이상이면 공용:
지금은 문헌이 모든 원고에 함께 쓰이므로 어느 원고의 인용 점검도 바뀌지 않게), 문체 → 공용, 저자가 만든 카테고리 → 공용.
작업물이 없으면 모두 공용.

- plan: 무엇이 어디로 가는지 목록(아무것도 쓰지 않는다)과 지금의 항목 수·인용 점검 결과.
- apply: 백업(사용자 폴더의 shelf/를 --backup 아래에 복사) 뒤 항목 파일에 "floor"를 적고 floors.json을 만든다.
  인덱스를 다시 만들고, 이전 전후의 항목 수·인용 점검 결과가 같은지 비교해 보인다.
- revert: 옛 코드로 되돌리기 전에. 항목 파일(휴지통 포함)의 "floor"를 떼고 floors.json을 옆으로 비켜 둔다(지우지 않음).
화면·도구는 이전 전후로 같아 보인다(이전 전에도 같은 규칙으로 보이기 때문). 그래서 이 이전은 '보이는 배치를 파일로 적는 일'이다.
"""

from __future__ import annotations

import shutil
from collections import Counter
from pathlib import Path
from typing import Any

from magus.ids import utcnow
from magus.melchior.check import Resolver, after_refs_changed, check_text, terms_of
from magus.store import LocalStore


def snapshot(store: LocalStore, user_id: str) -> dict[str, Any]:
    """비교용: 종류별 항목 수, 작업물마다 장별 인용 점검(확인·미확인·없음·미연결 고유 수)과 outline 머리 수."""
    out: dict[str, Any] = {
        "ideas": len(store.list_ideas(user_id)), "styles": len(store.list_styles(user_id)),
        "refs": len(store.list_refs(user_id)), "refs_verified": len(store.list_refs(user_id, "verified")),
        "categories": len(store.list_categories(user_id)), "category_items": len(store.list_category_items(user_id)),
        "projects": {},
    }
    for project in sorted(store.list_projects(user_id), key=lambda p: p.id):
        resolver, terms = Resolver(store, user_id, project.id), terms_of(store, user_id, project.id)
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
        out["projects"][project.id] = {
            "verified": totals["verified"], "unverified": totals["unverified"], "unknown": totals["unknown"],
            "uncertain": totals["uncertain"], "chapters": chapters,
            # 전체 현황 머리줄의 수(장 사이 합집합). 인덱스의 캐시가 아니라 지금 계산한다
            "outline_unique_unverified": len(unchecked), "outline_unlinked": len(unlinked),
        }
    return out


def summary_lines(snap: dict[str, Any]) -> list[str]:
    lines = [f"- 항목: 생각 {snap['ideas']} · 문체 {snap['styles']} · 문헌 {snap['refs']}(확인 {snap['refs_verified']}) · "
             f"카테고리 {snap['categories']}(항목 {snap['category_items']})"]
    for pid, p in snap["projects"].items():
        lines.append(f"- 작업물 {pid}: 인용 점검(장별 고유 합) 확인 {p['verified']} · 미확인 {p['unverified']} · "
                     f"참고문헌에 없음 {p['unknown']} · 미연결 {p['uncertain']} · 전체 현황 '미확인 문헌' {p['outline_unique_unverified']}편 · "
                     f"미연결 {p['outline_unlinked']}")
    return lines


def plan(store: LocalStore, user_id: str) -> list[str]:
    return [*store.floor_plan(user_id).lines(), "지금의 항목 수·인용 점검:", *summary_lines(snapshot(store, user_id))]


def apply(store: LocalStore, user_id: str, backup: Path) -> tuple[list[str], bool]:
    """(보고 줄, 전후가 같은가)."""
    before = snapshot(store, user_id)
    shelf = store.root / "users" / user_id / "shelf"
    target = backup / f"{user_id}-shelf-{utcnow().replace(':', '').replace('.', '')}"
    if shelf.exists():
        shutil.copytree(shelf, target)
    lines = [f"백업: {target}" if shelf.exists() else "백업: 책장 폴더가 없어 복사할 것이 없음"]
    lines += store.floor_plan(user_id).lines()
    store.ensure_layout(user_id)
    store.reindex()
    after_refs_changed(store, user_id)
    after = snapshot(store, user_id)
    same = before == after
    lines += ["이전 전:", *summary_lines(before), "이전 뒤:", *summary_lines(after),
              "전후 비교: " + ("같음(항목 수·장별 인용 점검·전체 현황 수)" if same else "다름 — 위 두 묶음을 비교한다")]
    return lines, same


def revert(store: LocalStore, user_id: str) -> list[str]:
    counts = store.revert_floors(user_id)
    store.reindex()
    after_refs_changed(store, user_id)
    return [f"층 되돌리기 {user_id}: " + (" · ".join(f"{k} {v}" for k, v in counts.items()) or "바꿀 것 없음"),
            "이제 옛 코드(층 전)로 되돌려도 항목 파일을 읽는다. 층 뒤에 만든 작업물은 그대로 남는다."]
