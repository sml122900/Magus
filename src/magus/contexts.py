"""컨텍스트(사용자 결정 #96, 2026-10-08): 노드·책에 붙이는 'AI가 그 글을 읽는 방법'.

- 책의 종류(원고 책·모음 책·문서 책, 생각·문체·문헌)를 없앴다. 책에는 글이 쌓이거나 올린 문서가 들어 있고,
  그 책을 어떻게 읽을지는 저자가 적은 컨텍스트가 정한다(예: "이 문서는 논문으로서 학술적인 문서야.").
  컨텍스트가 없으면 일반 메모다.
- 붙이는 곳은 노드와 책이다. 책을 읽을 때는 그 책이 꽂힌 노드의 것 → 책의 것 순서로 이어 읽는다(사용자 결정 #96-d 변경, 2026-10-08).
  둘 다 없으면 일반 메모다. 한 곳 안에서는 붙인 순서대로 잇는다. 연결 노드로 보는 책도 원본 노드 → 책이다(책은 원본 노드에 꽂혀 있다).
  응답 머리에 싣는 길이는 노드·책을 합쳐 HEADER_MAX자까지이고, 넘으면 잘렸다고 적는다.
- 붙인 컨텍스트는 사본이다: 그 자리에서 고쳐도 자주 쓰는 컨텍스트(등록해 둔 원본)는 그대로다.
- 자주 쓰는 컨텍스트는 사람마다 목록(이름 + 내용, shelf/contexts.json)이다. 파일이 없으면 처음 제공하는 넷(DEFAULTS)이다.
  「문체」는 사용자가 준 문장 그대로다.
- 서버의 일(올린 문서의 장 나누기·확인 요청·참고문헌·수정본·출처 확인 문서, 인용 점검)은 컨텍스트와 상관없다.
  인용 점검은 글의 '원문 확인' 표시와 참고문헌 항목으로 본다. 컨텍스트 글을 읽어 판단하지 않는다.
- AI는 컨텍스트를 도구 응답에서 본다: 노드·책을 읽거나 넣는 도구의 응답 머리에 그 컨텍스트 전문을 싣는다(header).
  전체 현황(book_outline)과 지도 보기(category_list)에는 이름(없으면 첫 줄 앞부분)만 싣는다(label).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any
from dataclasses import dataclass


@dataclass(frozen=True)
class Context:
    """컨텍스트 하나(#96): AI가 그 노드·책의 글을 읽는 방법. name은 자주 쓰는 컨텍스트에서 붙였으면 그 이름(직접 적었으면 "").
    붙인 것은 사본이다(그 자리에서 고쳐도 자주 쓰는 컨텍스트의 원본은 그대로)."""

    name: str
    text: str


@dataclass(frozen=True)
class SavedContext:
    """자주 쓰는 컨텍스트(#96): 사람마다 목록(shelf/contexts.json). 파일이 없으면 처음 제공하는 넷."""

    id: str
    name: str
    text: str
    created_at: str = ""
    updated_at: str = ""


CONTEXT_NAME_MAX = 20  # 이름(한 줄)
CONTEXT_MAX = 500  # 내용 하나. 도구 응답마다 실리므로 짧게
HEADER_MAX = 1000  # 응답 머리에 싣는 노드·책 컨텍스트 합계(넘으면 잘렸다고 적는다)
MAX_ATTACHED = 4  # 노드·책 하나에 붙이는 수
MAX_SAVED = 20  # 자주 쓰는 컨텍스트 수
CONTEXTS_SCHEMA = 1

# 처음 제공하는 자주 쓰는 컨텍스트(저자가 고치거나 지울 수 있다). 「문체」는 사용자가 준 문장 그대로다(2026-10-08).
DEFAULTS: tuple[SavedContext, ...] = (
    SavedContext("ctx-style", "문체", "문학적 부분이 마음에 드는 구절을 모아놓은것. 내 문장 표현을 다듬을때 사용"),
    SavedContext("ctx-manuscript", "원고",
                 "내가 쓰고 있는 책의 원고다. 원본은 내 Word 파일이고, 여기 있는 것은 마지막으로 올린 사본이다. "
                 "고칠 곳은 대화에서 제안해 주면 내가 Word에서 고친다."),
    SavedContext("ctx-paper", "논문",
                 "원문을 읽고 모은 논문과 책이다. '원문 확인' 표시가 있는 글만 인용 근거로 쓴다. "
                 "표시가 없는 글은 아직 원문을 확인하지 않은 목록(원고의 참고문헌에서 읽어 온 것 등)이다."),
    SavedContext("ctx-note", "생각 메모",
                 "떠오른 생각을 적어 둔 메모다. 내가 쓴 글과 AI가 쓴 글을 구분해서 읽는다. "
                 "다듬어지지 않은 생각이라 사실이나 출처로 쓰지 않는다."),
)
# 이전(#96)에서 옛 종류에 붙이는 컨텍스트: 원고 책 → 「원고」, 생각 → 「생각 메모」, 문체 → 「문체」, 문헌 → 「논문」
LEGACY_CONTEXT = {"ms": "ctx-manuscript", "ideas": "ctx-note", "styles": "ctx-style", "refs": "ctx-paper"}
# 출처 확인 문서(서버가 만드는 읽기용 문서)에 붙이는 설명. 자주 쓰는 컨텍스트에는 넣지 않는다(문서를 만들 때·이전 때 붙인다)
SOURCE_CHECK = Context(
    "출처 확인 문서",
    "올린 문서의 인용과 사실 확인 상태를 서버가 정리한 읽기용 문서다. 만든 때의 사진이라 새 수정본이 오면 옛 판 기준이 된다. "
    "문서의 질문·수치·문헌 목록은 서버가 만든 것이라 다시 세거나 고쳐 쓰지 않는다.",
)
NONE = "컨텍스트: 없음(일반 메모로 다룬다)"


def clean_context(name: str | None, text: str | None) -> Context:
    """이름(한 줄, 20자)과 내용(500자). 내용이 비면 ValueError."""
    clean_name = " ".join(str(name or "").split())
    body = "\n".join(line.rstrip() for line in str(text or "").strip().splitlines()).strip()
    if not body:
        raise ValueError("컨텍스트 내용이 비어 있습니다.")
    if len(clean_name) > CONTEXT_NAME_MAX:
        raise ValueError(f"컨텍스트 이름은 {CONTEXT_NAME_MAX}자까지입니다. 지금 {len(clean_name)}자입니다.")
    if len(body) > CONTEXT_MAX:
        raise ValueError(f"컨텍스트 내용은 하나에 {CONTEXT_MAX}자까지입니다. 지금 {len(body)}자입니다.")
    return Context(clean_name, body)


def clean_contexts(items: Iterable[Context]) -> tuple[Context, ...]:
    """붙일 컨텍스트들: 하나씩 검사하고, 내용이 같은 것은 한 번만, MAX_ATTACHED개까지."""
    out: list[Context] = []
    for c in items:
        clean = clean_context(c.name, c.text)
        if all(o.text != clean.text for o in out):
            out.append(clean)
    if len(out) > MAX_ATTACHED:
        raise ValueError(f"컨텍스트는 노드·책마다 {MAX_ATTACHED}개까지 붙일 수 있습니다.")
    return tuple(out)


def name_key(name: str) -> str:
    return "".join((name or "").split()).lower()


def find_saved(saved: Iterable[SavedContext], name: str) -> SavedContext | None:
    key = name_key(name.strip("「」 "))
    return next((s for s in saved if name_key(s.name) == key), None) if key else None


def from_values(saved: list[SavedContext], values: Iterable[str]) -> tuple[Context, ...]:
    """도구 인자(context: 문자열 목록) → 붙일 컨텍스트. 자주 쓰는 컨텍스트 이름이면 그 사본, 아니면 직접 적은 글(이름 없음)."""
    out = []
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        hit = find_saved(saved, text)
        out.append(Context(hit.name, hit.text) if hit else Context("", text))
    return clean_contexts(out)


def label(contexts: tuple[Context, ...], width: int = 12) -> str:
    """이름만: '「원고」', '「문체」 외 1'. 이름 없는 것은 첫 줄 앞부분."""
    if not contexts:
        return ""
    first = contexts[0]
    shown = first.name or _clip(first.text.splitlines()[0], width)
    return f"「{shown}」" + (f" 외 {len(contexts) - 1}" if len(contexts) > 1 else "")


def band(contexts: tuple[Context, ...]) -> str:
    """책등 위 띠: 첫 컨텍스트 이름(없으면 첫 줄 앞부분) + ' 외 N'. 없으면 빈 문자열."""
    if not contexts:
        return ""
    first = contexts[0]
    shown = first.name or _clip(first.text.splitlines()[0], 6)
    return shown + (f" 외 {len(contexts) - 1}" if len(contexts) > 1 else "")


def joined(contexts: tuple[Context, ...]) -> str:
    """붙인 순서대로 이은 전문: '「이름」 내용 / 「이름」 내용'."""
    return " / ".join((f"「{c.name}」 " if c.name else "") + " ".join(c.text.split()) for c in contexts)


@dataclass(frozen=True)
class View:
    """책 하나(또는 노드 하나)에 지금 걸린 컨텍스트. 책을 볼 때는 node_contexts(꽂힌 노드의 것)를 먼저, contexts(책의 것)를 다음에
    읽는다(#96-d). 노드만 볼 때는 contexts가 그 노드의 것이고 node_contexts는 비어 있다."""

    contexts: tuple[Context, ...]
    book: str = ""  # 책 이름(노드만 볼 때는 "")
    node: str = ""  # 노드 이름(가운데 노드면 "가운데")
    node_contexts: tuple[Context, ...] = ()

    @property
    def all(self) -> tuple[Context, ...]:
        """읽는 순서: 노드 → 책."""
        return self.node_contexts + self.contexts

    @property
    def too_long(self) -> bool:
        return len(_body(self)) > HEADER_MAX

    def header(self) -> str:
        """도구 응답 머리 한 줄: 'AI가 이 글을 읽는 방법'. 없으면 '없음(일반 메모로 다룬다)'."""
        if not self.all:
            return NONE + (f" — 책 「{self.book}」" if self.book else f" — 노드 「{self.node}」" if self.node else "")
        if not self.book:
            where = f"노드 「{self.node}」"
        elif self.node_contexts and self.contexts:
            where = f"노드 「{self.node}」 → 책 「{self.book}」 순서"
        elif self.node_contexts:
            where = f"노드 「{self.node}」의 것. 책 「{self.book}」에는 없음"
        else:
            where = f"책 「{self.book}」"
        body = _body(self)
        if len(body) > HEADER_MAX:
            body = body[:HEADER_MAX].rstrip() + f"…(잘림: 노드·책 컨텍스트를 합쳐 {HEADER_MAX:,}자까지 싣는다)"
        return f"컨텍스트({where}): {body}"


def _body(view: View) -> str:
    """노드의 것 → 책의 것. 두 쪽이 다 있으면 ' → '로 가른다(한 쪽 안은 ' / ')."""
    return " → ".join(joined(part) for part in (view.node_contexts, view.contexts) if part)


def _clip(text: str, width: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= width else text[: width - 1] + "…"


# ---- 파일 ↔ 객체(category.json·project.json·document.json·지도 노드의 "contexts") ----------------------------------

def to_record(contexts: tuple[Context, ...]) -> list[dict[str, str]]:
    return [{"name": c.name, "text": c.text} for c in contexts]


def from_record(raw: object) -> tuple[Context, ...]:
    """파일에서 읽은 값을 거른다(사람이 고친 파일도 읽히게): 내용이 있는 것만, 길이는 자르지 않는다."""
    out = []
    for item in raw if isinstance(raw, list) else []:
        if isinstance(item, dict) and str(item.get("text") or "").strip():
            out.append(Context(" ".join(str(item.get("name") or "").split()), str(item["text"]).strip()))
    return tuple(out)


# ---- 지금 걸린 컨텍스트(도구 응답 머리·웹 패널) ------------------------------------------------------------------

def book_contexts(store: Any, user: str, key: str) -> tuple[tuple[Context, ...], str]:
    """책 주소 이름(카테고리 id · ms.<프로젝트> · doc.<id>) → (그 책의 컨텍스트, 책 이름). 없는 책이면 ((), "")."""
    base, _, rest = key.partition(".")
    if base == "ms" and rest:
        project = store.get_project(user, rest)
        return (project.contexts, project.title) if project else ((), "")
    if base == "doc" and rest:
        doc = store.get_document(user, rest)
        return (doc.contexts, doc.title) if doc else ((), "")
    try:
        category = store.get_category(user, key)
    except ValueError:
        category = None
    return (category.contexts, category.name) if category else ((), "")


def view_for_book(store: Any, user: str, key: str) -> View:
    """책에 걸린 컨텍스트: 그 책이 꽂힌 노드의 것 → 책의 것(#96-d)."""
    own, name = book_contexts(store, user, key)
    where = store.node_of_book(user, key)
    found = store.get_map(user, where[0]) if where else None
    node = found.node(where[1]) if found and where else None
    node_name = ("가운데" if node.center else node.name) if node else ""
    return View(own, name, node_name, node.contexts if node else ())


def view_for_node(store: Any, user: str, floor: str, node_id: str) -> View:
    found = store.get_map(user, floor)
    node = found.node(node_id) if found else None
    if node is None:
        return View(())
    return View(node.contexts, node=("가운데" if node.center else node.name))


def attach_manuscript_context(store: Any, user: str, project_id: str) -> bool:
    """처음 올린 문서(가운데 노드의 책)에 자주 쓰는 컨텍스트 「원고」를 붙인다(#96). 이미 컨텍스트가 있거나 저자가 「원고」를
    지웠으면 붙이지 않는다. 저자는 책 설정에서 떼거나 고칠 수 있다."""
    project = store.get_project(user, project_id)
    if project is None or project.contexts:
        return False
    saved = find_saved(store.list_saved_contexts(user), "원고")
    if saved is None:
        return False
    store.set_book_contexts(user, f"ms.{project_id}", (Context(saved.name, saved.text),))
    return True
