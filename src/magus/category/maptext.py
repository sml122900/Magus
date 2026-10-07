"""지도(#95)를 글로: 전체 현황(book_outline)의 짧은 두 줄과 category_list의 프로젝트별 지도. 도구 응답(Claude에게)이다.

노드마다 '노드 이름: 책 이름 항목 수'를, 연결 노드는 '연결 「원본 노드」(원본 프로젝트)'를, 선은 '이름–이름'으로 적는다.
가운데 노드는 '가운데'라고 부른다(이름 = 프로젝트 제목).
"""

from __future__ import annotations

from collections import Counter

from magus.maps import BOOK_NAMES, local_key
from magus.store import MapNode, ProjectMap, Store


def _clip(text: str, width: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= width else text[: width - 1] + "…"


class Counts:
    """책 하나의 항목 수(한 번 읽어 둔다)."""

    def __init__(self, store: Store, user: str):
        self.store, self.user = store, user
        self.builtin: Counter = Counter()
        self.verified: Counter = Counter()
        for kind, items in (("ideas", store.list_ideas(user)), ("styles", store.list_styles(user)), ("refs", store.list_refs(user))):
            for item in items:
                self.builtin[(kind, item.floor or "common")] += 1
                if kind == "refs" and item.status == "verified":
                    self.verified[item.floor or "common"] += 1
        self.categories = {c.id: c for c in store.list_categories(user)}

    def book(self, key: str) -> str:
        """'생각 12' · '문헌 337(확인 0)' · '사례 15' · '원고 책 40장' · '문서 「제목」'."""
        floor, local = local_key(key)
        if local in BOOK_NAMES and floor:
            n = self.builtin[(local, floor)]
            return f"{BOOK_NAMES[local]} {n}" + (f"(확인 {self.verified[floor]})" if local == "refs" else "")
        if local == "ms" and floor:
            return f"원고 책 {len(self.store.list_chapters(self.user, floor))}장"
        if local.startswith("doc."):
            doc = self.store.get_document(self.user, local[4:])
            return f"문서 「{_clip(doc.title, 16)}」" if doc else "문서"
        category = self.categories.get(local)
        return f"{_clip(category.name, 12)} {category.items}" if category else "?"


def node_text(node: MapNode, counts: Counts) -> str:
    books = " · ".join(counts.book(b) for b in node.books) or "책 없음"
    if node.link:
        where = node.link_title or "?"
        return "연결 원본 없음" if node.missing else f"연결 「{_clip(node.name, 12)}」({_clip(where, 14)}) {books}"
    return f"{'가운데' if node.center else f'「{_clip(node.name, 12)}」'} {books}"


def edges_text(found: ProjectMap, limit: int = 12) -> str:
    names = {n.id: ("가운데" if n.center else f"연결 {n.name}" if n.link else n.name) for n in found.nodes}
    ordered = [(b, a) if b == "center" else (a, b) for a, b in found.edges]  # 가운데를 앞에
    pairs = [f"{_clip(names[a], 10)}–{_clip(names[b], 10)}" for a, b in ordered if a in names and b in names]
    more = f" 외 {len(pairs) - limit}" if len(pairs) > limit else ""
    return " · ".join(pairs[:limit]) + more if pairs else "없음"


def outline_lines(store: Store, user: str, floor: str, nodes_shown: int = 10) -> list[str]:
    """전체 현황 머리의 두 줄: 이 프로젝트 지도(노드·책·연결)와 선."""
    found = store.get_map(user, floor)
    if found is None:
        return []
    counts = Counts(store, user)
    parts = [node_text(n, counts) for n in found.nodes]
    more = f" 외 노드 {len(parts) - nodes_shown}" if len(parts) > nodes_shown else ""
    return [f"지도(노드 {len(found.nodes)} · 선 {len(found.edges)}): " + " · ".join(parts[:nodes_shown]) + more,
            f"선: {edges_text(found)}"]


def project_block(store: Store, user: str, floor: str, counts: Counts, *, header: str) -> list[str]:
    """category_list의 프로젝트 하나: 머리줄, 노드마다 한 줄(저자 카테고리는 템플릿·칸), 선."""
    found = store.get_map(user, floor)
    if found is None:
        return []
    lines = [f"{header} · 노드 {len(found.nodes)} · 선 {len(found.edges)}"]
    for node in found.nodes:
        line = f"- {node_text(node, counts)}"
        details = []
        for key in node.books if not node.link else ():
            category = counts.categories.get(key)
            if category is not None and category.fields:
                details.append(f"{category.name} 칸: {', '.join(category.fields)}")
        lines.append(line + (f" ({'; '.join(details)})" if details else ""))
    lines.append(f"- 선: {edges_text(found, 20)}")
    return lines
