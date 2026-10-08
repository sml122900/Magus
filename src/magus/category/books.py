"""책 이름 → 책(#96). 도구(category_*·idea_add_conversation·ref_import_bibliography)가 함께 쓴다.

책은 셋 중 하나로 보인다: 글이 쌓이는 책(카테고리), 올린 문서가 든 책(가운데 노드, 이름 = 프로젝트 제목), 원고에서 만든 문서.
종류 이름은 저자에게 쓰지 않는다. 같은 이름이 여러 프로젝트에 있으면 project(그 프로젝트, 그다음 그 지도의 연결 노드가 가리키는 책)로
가린다. 못 찾으면 책 이름과 컨텍스트 이름을 보여 주며 묻게 하는 오류를 낸다(instructions의 넣을 곳 묻기 규칙).
"""

from __future__ import annotations

from dataclasses import dataclass

from mcp.server.mcpserver.exceptions import ToolError

from magus.category.rules import clean_name, name_key
from magus.contexts import view_for_book
from magus.project_args import find_project, floor_name, short
from magus.store import Category, ProjectMap, Store
from magus.store.formats import one_line


@dataclass(frozen=True)
class BookRef:
    """이름으로 찾은 책. key: 책 주소 이름(카테고리 id · ms.<프로젝트> · doc.<id>). category: 글이 쌓이는 책이면 그 카테고리."""

    key: str
    name: str
    floor: str
    category: Category | None = None

    @property
    def upload(self) -> bool:
        """올린 문서가 든 책이나 원고에서 만든 문서인가(글을 넣지 않는다)."""
        return self.category is None


def all_books(store: Store, user: str) -> list[BookRef]:
    out = [BookRef(c.id, c.name, c.floor, c) for c in store.list_categories(user)]
    for f in store.list_floors(user):
        if f.has_manuscript:
            out.append(BookRef(f"ms.{f.id}", f.title, f.id))
    out += [BookRef(f"doc.{d.id}", d.title, d.floor) for d in store.list_documents(user)]
    return out


def books_text(store: Store, user: str, books: list[BookRef], limit: int = 15) -> str:
    """'「생각」[생각 메모](「프로젝트」) · …' — 묻게 할 때 보이는 책 이름과 컨텍스트 이름."""
    multi = len({b.floor for b in books}) > 1
    parts = []
    for b in books[:limit]:
        view = view_for_book(store, user, b.key)
        tag = f"[{view.contexts[0].name or one_line(view.contexts[0].text)[:12]}]" if view.contexts else ""
        parts.append(f"「{short(b.name, 14)}」{tag}" + (f"({floor_name(store, user, b.floor)})" if multi else ""))
    return " · ".join(parts) + (f" 외 {len(books) - limit}권" if len(books) > limit else "")


def find_book(store: Store, user: str, text: str, project: str | None = None) -> BookRef:
    raw = " ".join(str(text or "").split()).strip("「」")
    key = name_key(clean_name(raw))
    books = all_books(store, user)
    found = [b for b in books if b.key == raw or name_key(b.name) == key]
    if project and project.strip() and len(found) > 1:
        here = find_project(store, user, project).id
        own = [b for b in found if b.floor == here]
        if len(own) == 1:
            return own[0]
        linked = {k for n in (store.get_map(user, here) or ProjectMap("", "", (), ())).nodes if n.link for k in n.books}
        via = [b for b in found if b.key in linked]
        if len(via) == 1:
            return via[0]
    if len(found) == 1:
        return found[0]
    if not found:
        raise ToolError(f"'{raw}' 책이 없다. 저자에게 어느 책인지 묻는다. 책: {books_text(store, user, books) or '없음'}")
    raise ToolError(f"「{found[0].name}」 책이 여러 프로젝트에 있다({', '.join(dict.fromkeys(floor_name(store, user, b.floor) for b in found))}). "
                    "project로 어느 것인지 준다.")


def writable_book(store: Store, user: str, text: str, project: str | None = None) -> BookRef:
    """글을 넣을 책(카테고리). 올린 문서가 든 책이면 오류."""
    book = find_book(store, user, text, project)
    if book.upload:
        raise ToolError(f"「{book.name}」에는 올린 문서가 들어 있어 글을 넣지 않는다(고칠 곳은 대화로 제안하고, 저자가 원본 파일에서 고친다). "
                        "글을 넣을 책을 저자에게 묻는다.")
    return book
