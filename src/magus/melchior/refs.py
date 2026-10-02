"""ref_add: 사용자가 실제로 읽고 발췌한 문헌을 verified로 넣는다.

발췌(passages)가 하나 이상 있어야 verified가 된다. 기억이나 목록만으로는 verified가 되지 않는다.
같은 key(또는 alias)가 unverified로 있으면 그 항목을 verified로 올리고, bib·aliases·발췌를 합친다.
발췌는 ref_picked 레인, 전문은 ref_full 레인으로 청킹된다(저장소가 한다).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

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


def add_ref(
    store: Store,
    user_id: str,
    bib: dict[str, Any],
    passages: list[Passage],
    *,
    file_path: str | None = None,
    full_text: str | None = None,
    aliases: list[str] | None = None,
) -> tuple[Ref, str | None, int]:
    """(저장된 ref, 이전 상태 또는 None, 새로 추가된 발췌 수)."""
    passages = [p for p in passages if p.text.strip()]
    if not passages:
        raise ValueError("passages가 비어 있다. 직접 읽고 고른 발췌(text, reason)가 있어야 verified가 된다.")
    if any(not p.reason.strip() for p in passages):
        raise ValueError("모든 발췌에 reason(왜 골랐는지)이 필요하다")
    if file_path and full_text:
        raise ValueError("file_path와 full_text 중 하나만 준다")
    if file_path:
        full_text = read_fulltext(Path(file_path).expanduser())

    clean_bib = {k: v for k, v in bib.items() if v not in (None, "", []) and k != "key"}
    key = derive_key(bib)
    existing = store.resolve_ref(user_id, key)
    if existing:
        old = store.get_passages(user_id, existing.key)
        seen = {p.text.strip() for p in old}
        new = [p for p in passages if p.text.strip() not in seen]
        ref = Ref(
            key=existing.key,
            status="verified",
            bib={**existing.bib, **clean_bib},
            aliases=tuple(dict.fromkeys([*existing.aliases, *(aliases or [])])),
            file_path=file_path or existing.file_path,
            created_at=existing.created_at,
        )
        stored = store.put_ref(user_id, ref, passages=[*old, *new], full_text=full_text)
        return stored, existing.status, len(new)
    ref = Ref(key=key, status="verified", bib=clean_bib, aliases=tuple(aliases or ()), file_path=file_path)
    return store.put_ref(user_id, ref, passages=passages, full_text=full_text), None, len(passages)
