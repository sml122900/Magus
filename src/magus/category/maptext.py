"""지도(#95)를 글로: 전체 현황(book_outline)의 짧은 두 줄과 category_list의 프로젝트별 지도. 도구 응답(Claude에게)이다.

노드마다 '노드 이름: 책 이름 글 수[컨텍스트 이름]'을, 연결 노드는 '연결 「원본 노드」(원본 프로젝트)'를, 선은 '이름–이름'으로 적는다.
가운데 노드는 '가운데'라고 부른다(이름 = 프로젝트 제목). 컨텍스트는 이름(없으면 첫 줄 앞부분)만 싣는다(#96: 전문은 그 책을
읽거나 넣는 도구 응답 머리에 실린다).
"""

from __future__ import annotations

from collections import Counter

from magus.maps import BOOK_NAMES, local_key
from magus.store import MapNode, ProjectMap, Store
from magus.store.fileio import read_json


def _clip(text: str, width: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= width else text[: width - 1] + "…"


def _tag(contexts: tuple) -> str:
    """'[논문]' · '[문체 외 1]' · 이름 없는 컨텍스트는 첫 줄 앞부분. 없으면 ""."""
    if not contexts:
        return ""
    first = contexts[0]
    shown = first.name or _clip(first.text.splitlines()[0], 16)
    return f"[{shown}" + (f" 외 {len(contexts) - 1}" if len(contexts) > 1 else "") + "]"


class Counts:
    """책 하나의 글 수(한 번 읽어 둔다). 옛 기본 책(이전 전 데이터, 이전 미리보기)은 옛 파일에서 센다."""

    def __init__(self, store: Store, user: str):
        self.store, self.user = store, user
        self.categories = {c.id: c for c in store.list_categories(user)}
        self.legacy: Counter = Counter()
        self.legacy_verified: Counter = Counter()
        root = getattr(store, "root", None)
        if root is not None:  # 이전 전(#96 전) 데이터: 옛 생각·문체 파일, 책이 없는 문헌
            shelf = root / "users" / user / "shelf"
            for kind, folder in (("ideas", "casper"), ("styles", "balthasar")):
                for path in shelf.glob(f"{folder}/*.json"):
                    self.legacy[(kind, str(read_json(path).get("floor") or "common"))] += 1
            for ref in store.list_refs(user):
                if not ref.book:
                    self.legacy[("refs", ref.floor or "common")] += 1
                    self.legacy_verified[ref.floor or "common"] += ref.status == "verified"

    def book(self, key: str) -> str:
        """'「생각」 12[생각 메모]' · '「문헌」 글 0·문헌 337(확인 0)[논문]' · '「제목」 42장[원고]' · '「제목」 문서[출처 확인 문서]'."""
        floor, local = local_key(key)
        if local in BOOK_NAMES and floor:  # 옛 기본 책(이전 전)
            n = self.legacy[(local, floor)]
            return f"{BOOK_NAMES[local]} {n}" + (f"(확인 {self.legacy_verified[floor]})" if local == "refs" else "")
        if local == "ms" and floor:
            project = self.store.get_project(self.user, floor)
            n = len(self.store.list_chapters(self.user, floor))
            return f"「{_clip(project.title if project else floor, 14)}」 올린 문서 {n}장" + _tag(project.contexts if project else ())
        if local.startswith("doc."):
            doc = self.store.get_document(self.user, local[4:])
            return f"「{_clip(doc.title, 16)}」 문서" + _tag(doc.contexts) if doc else "문서"
        category = self.categories.get(local)
        if category is None:
            return "?"
        sources = f"·문헌 {category.sources}(확인 {category.verified})" if category.sources else ""
        count = f"글 {category.items}{sources}" if sources else f"{category.items}"
        return f"「{_clip(category.name, 12)}」 {count}" + _tag(category.contexts)


def node_text(node: MapNode, counts: Counts) -> str:
    books = " · ".join(counts.book(b) for b in node.books) or "책 없음"
    if node.link:
        where = node.link_title or "?"
        return "연결 원본 없음" if node.missing else f"연결 「{_clip(node.name, 12)}」({_clip(where, 14)}){_tag(node.contexts)}: {books}"
    return f"{'가운데' if node.center else f'「{_clip(node.name, 12)}」'}{_tag(node.contexts)}: {books}"


def edges_text(found: ProjectMap, limit: int = 12) -> str:
    names = {n.id: ("가운데" if n.center else f"연결 {n.name}" if n.link else n.name) for n in found.nodes}
    ordered = [(b, a) if b == "center" else (a, b) for a, b in found.edges]  # 가운데를 앞에
    pairs = [f"{_clip(names[a], 10)}–{_clip(names[b], 10)}" for a, b in ordered if a in names and b in names]
    more = f" 외 {len(pairs) - limit}" if len(pairs) > limit else ""
    return " · ".join(pairs[:limit]) + more if pairs else "없음"


def outline_lines(store: Store, user: str, floor: str, nodes_shown: int = 10) -> list[str]:
    """전체 현황 머리의 두 줄: 이 프로젝트 지도(노드·책·[컨텍스트 이름]·연결)와 선."""
    found = store.get_map(user, floor)
    if found is None:
        return []
    counts = Counts(store, user)
    parts = [node_text(n, counts) for n in found.nodes]
    more = f" 외 노드 {len(parts) - nodes_shown}" if len(parts) > nodes_shown else ""
    return [f"지도(노드 {len(found.nodes)} · 선 {len(found.edges)}): " + " · ".join(parts[:nodes_shown]) + more,
            f"선: {edges_text(found)}"]


def project_block(store: Store, user: str, floor: str, counts: Counts, *, header: str) -> list[str]:
    """category_list의 프로젝트 하나: 머리줄, 노드마다 한 줄(칸이 있는 책은 칸), 선."""
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
