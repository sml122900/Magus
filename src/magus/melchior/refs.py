"""문헌 글 넣기(#96: 글 넣기 category_put의 '서지·원문 확인' 칸, 옛 ref_add): 저자가 실제로 읽고 고른 대목이 있는 문헌을 verified로 넣는다.

쓸 부분(발췌, passages)이 하나 이상 있어야 verified(원문 확인)가 된다. 기억이나 목록만으로는 verified가 되지 않는다.
같은 key(또는 alias)가 unverified로 있으면 그 항목을 verified로 올리고, bib·aliases·발췌를 합친다.
발췌는 ref_picked 레인, 전문은 ref_full 레인으로 청킹된다(저장소가 한다).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import replace
from pathlib import Path
from typing import Any

from magus.project_args import needs_share, share_ref
from magus.melchior.bibliography import first_author
from magus.melchior.citations import make_ref_key
from magus.store import Passage, Ref, Store

_YEAR = re.compile(r"(?:1[5-9]|20)\d{2}[a-z]?")


def read_fulltext(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in (".txt", ".md"):
        return path.read_text(encoding="utf-8")
    if suffix == ".pdf":
        import pymupdf

        with pymupdf.open(path) as doc:
            return "\n\n".join(page.get_text() for page in doc)
    if suffix == ".docx":
        from magus.book.docx_reader import read_docx

        return "\n\n".join(b.text for b in read_docx(path).blocks if b.text.strip())
    raise ValueError(f"전문 파일 형식을 읽을 수 없다: {path.name} (txt, md, pdf, docx)")


def derive_key(bib: dict[str, Any]) -> str:
    if key := str(bib.get("key") or "").strip():
        return key
    authors = bib.get("authors") or bib.get("author") or ""
    if isinstance(authors, list):
        authors = ", ".join(map(str, authors))
    author = str(bib.get("first_author") or first_author(str(authors)))
    year = str(bib.get("year") or "").strip()
    if not author or not _YEAR.fullmatch(year):
        raise ValueError("bib에 key가 없으면 저자(authors 또는 author)와 네 자리 연도(year)가 필요하다")
    return make_ref_key(author, year)


def add_alias(store: Store, user_id: str, key: str, surface: str) -> tuple[Ref, str]:
    """사용자가 확정한 본문 표기를 문헌의 aliases에 넣는다(`magus alias`). 음역 추정은 저장하지 않으므로 이 길로만 들어간다.
    '케인스(1930)'·'케인스 1930'·'케인스' → '케인스1930'. 연도가 없으면 문헌의 연도를 쓴다(1930a의 a는 뗀다:
    본문 인용에는 보통 a/b가 없다)."""
    ref = store.get_ref(user_id, key)
    if ref is None:
        raise ValueError(f"문헌 {key!r}가 없다")
    year = m.group() if (m := _YEAR.search(surface)) else str(ref.bib.get("year", ""))[:4]
    name = re.sub(r"[\s(),]+", "", _YEAR.sub("", surface))
    if not name or not _YEAR.fullmatch(year):
        raise ValueError(f"표기 {surface!r}에서 이름과 연도를 알 수 없다. 예: 케인스(1930)")
    alias = make_ref_key(name, year)
    if (other := store.resolve_ref(user_id, alias)) and other.key != ref.key:
        raise ValueError(f"{alias}는 이미 {other.key}에 이어져 있다")
    if alias == ref.key or alias in ref.aliases:
        return ref, alias
    return store.put_ref(user_id, replace(ref, aliases=(*ref.aliases, alias))), alias


def _norm(text: str) -> str:
    return re.sub(r"[^0-9a-z가-힣]+", " ", unicodedata.normalize("NFKC", text).lower()).strip()


def key_by_title(store: Store, user_id: str, bib: dict[str, Any], full_text: str | None) -> str:
    """bib에 key도 저자·연도도 없을 때: bib의 제목이나 전문 첫머리(5,000자)에 제목이 그대로 들어 있는 참고문헌 하나.
    "fixtures/papers/논문.pdf를 문헌으로 등록해 줘"처럼 파일만 받았을 때 쓴다. 둘 이상이면 고르지 않는다."""
    haystack = _norm(f"{bib.get('title') or ''} {(full_text or '')[:5000]}")
    hits = [
        r.key for r in store.list_refs(user_id) if len(title := _norm(str(r.bib.get("title", "")))) >= 12 and title in haystack
    ]
    if len(hits) == 1:
        return hits[0]
    if hits:
        raise ValueError(f"제목이 맞는 참고문헌이 여럿이다({', '.join(hits)}). bib에 key를 넣어 달라")
    raise ValueError("bib에 key가 없으면 저자(authors 또는 author)와 네 자리 연도(year)가 필요하다. 전문 첫머리에서 참고문헌 제목도 찾지 못했다")


def add_ref(
    store: Store,
    user_id: str,
    bib: dict[str, Any],
    passages: list[Passage],
    *,
    book: str,
    file_path: str | None = None,
    full_text: str | None = None,
    aliases: list[str] | None = None,
    file_label: str | None = None,
    verified: bool = True,
    memo: str | None = None,
) -> tuple[Ref, str | None, int, str | None, str | None]:
    """(저장된 ref, 이전 상태 또는 None, 새로 추가된 발췌 수, 옮긴 책 또는 None, 연결 노드를 붙인 원래 프로젝트 또는 None).
    book(#96): 그 글을 넣을 책(카테고리 id). 새 문헌은 그 책에 든다. 이미 있는 문헌은 같은 프로젝트면 그 책으로 옮기고,
    그 프로젝트 원고의 인용 점검이 보지 못하는 다른 프로젝트에 있으면 제자리에 두고 이 프로젝트 지도에 그 노드로 가는
    연결 노드를 붙인다(2026-10-11, 전에는 「내 서재」로 옮겼다).
    verified=False면 '원문 확인' 없이 서지만 넣는다(발췌 없어도 된다, 이미 확인한 문헌이면 확인은 그대로). memo: 글의 내용(bib "memo")."""
    passages = [p for p in passages if p.text.strip()]
    if verified and not passages:
        raise ValueError("원문 확인에는 쓸 부분(parts)이 하나 이상 있어야 한다. 직접 읽고 고른 대목(text)과 이유(reason)를 준다.")
    if verified and any(not p.reason.strip() for p in passages):
        raise ValueError("원문 확인에는 쓸 부분마다 이유(reason: 왜 골랐는지)가 필요하다")
    if file_path and full_text:
        raise ValueError("file_path와 full_text 중 하나만 준다")
    if file_path:
        full_text = read_fulltext(Path(file_path).expanduser())

    clean_bib = {k: v for k, v in bib.items() if v not in (None, "", []) and k != "key"}
    if memo and memo.strip():
        clean_bib["memo"] = memo.strip()
    try:
        key = derive_key(bib)
    except ValueError:
        key = key_by_title(store, user_id, bib, full_text)
    target_floor = store.get_category(user_id, book).floor if store.get_category(user_id, book) else None
    if target_floor is None:
        raise ValueError(f"책 {book!r}가 없다")
    existing = store.resolve_ref(user_id, key)
    if existing:
        old = store.get_passages(user_id, existing.key)
        seen = {p.text.strip() for p in old}
        new = [p for p in passages if p.text.strip() not in seen]
        ref = Ref(
            key=existing.key,
            status="verified" if verified or existing.status == "verified" else "unverified",
            bib={**existing.bib, **clean_bib},
            aliases=tuple(dict.fromkeys([*existing.aliases, *(aliases or [])])),
            file_path=file_label or file_path or existing.file_path,
            created_at=existing.created_at,
        )
        stored = store.put_ref(user_id, ref, passages=[*old, *new], full_text=full_text)
        moved = linked = None
        if needs_share(store, user_id, stored.floor, target_floor):  # 다른 프로젝트에 있는 문헌: 제자리에 두고 연결 노드를 붙인다
            linked = stored.floor
            stored = share_ref(store, user_id, stored.key, stored.floor, target_floor)
        elif stored.floor == target_floor and stored.book != book:  # 같은 프로젝트: 저자가 고른 책으로
            stored = store.set_ref_book(user_id, stored.key, book)
            moved = book
        return stored, existing.status, len(new), moved, linked
    ref = Ref(key=key, status="verified" if verified else "unverified", bib=clean_bib, aliases=tuple(aliases or ()),
              file_path=file_label or file_path, book=book)
    return store.put_ref(user_id, ref, passages=passages, full_text=full_text), None, len(passages), None, None
