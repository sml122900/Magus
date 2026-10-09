"""하이브리드 검색: FTS5(키워드, 한글 bigram)와 벡터(코사인)를 RRF로 합친다.

임베딩 제공자가 없으면(EMBEDDINGS=none) FTS만 쓴다. 한국어 고유명사·학자 이름은 키워드 검색이 잡고,
뜻이 비슷한 문장은 벡터가 잡는다. 두 목록의 순위만 쓰므로 점수 척도를 맞출 필요가 없다.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from typing import Protocol

from magus.store import Chunk, Store
from magus.store.base import Lane
from magus.textindex import match_query, needle_of, query_parts, search_match, tokens

RRF_K = 60
log = logging.getLogger("magus.search")


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


def rrf(rankings: list[list[Chunk]], k: int = RRF_K) -> list[Chunk]:
    scores: dict[int, float] = {}
    chunks: dict[int, Chunk] = {}
    for ranking in rankings:
        for rank, chunk in enumerate(ranking):
            scores[chunk.id] = scores.get(chunk.id, 0.0) + 1.0 / (k + rank + 1)
            chunks.setdefault(chunk.id, chunk)
    order = sorted(scores, key=lambda cid: -scores[cid])
    return [Chunk(c.id, c.owner_type, c.owner_id, c.lane, c.text, scores[c.id], c.part) for c in (chunks[cid] for cid in order)]


def hybrid_search(
    store: Store, user_id: str, query: str, lanes: list[Lane], k: int, embedder: Embedder | None = None
) -> list[Chunk]:
    pool = max(k * 4, 20)
    rankings: list[list[Chunk]] = []
    if match := match_query(query):
        rankings.append(store.search_fts(user_id, lanes, match, pool))
    if embedder is not None and query.strip():
        try:
            embed_missing(store, user_id, embedder)
            rankings.append(store.search_vector(user_id, lanes, embedder.embed([query])[0], pool))
        except Exception as e:  # 임베딩 API가 실패해도 검색은 FTS 결과로 계속한다
            log.warning("벡터 검색 실패, FTS만 사용: %s", e)
    return rrf(rankings)[:k]


def find_chunks(store: Store, user_id: str, lanes: list[Lane], query: str, limit: int, embedder: Embedder | None = None) -> list[Chunk]:
    """웹 찾기와 category_search가 함께 쓰는 찾기(2026-10-09). 사람이 떠올리는 대로 쳐도 찾게:
    1단계(색인, 순위 먼저): textindex.search_match(앞부분 일치·구절·2글자 조각). 임베딩 제공자가 있으면 벡터와 RRF로 합친다.
    2단계(글자 그대로 포함, 대소문자 무시): 1단계에 없는 글을 최근 것부터 뒤에 붙인다(한 글자·낱말 중간·기호도 찾는다).
    같은 글(owner)은 한 번. 공백만 있으면 []."""
    query = " ".join((query or "").split())
    if not query:
        return []
    pool = max(limit, 20)
    rankings: list[list[Chunk]] = []
    if match := search_match(query):
        try:
            rankings.append(store.search_fts(user_id, lanes, match, pool))
        except sqlite3.OperationalError as e:  # 식은 토큰만으로 만들어 문법 오류가 나지 않아야 한다. 나더라도 2단계로 계속한다
            log.warning("FTS 식 오류, 글자 포함 찾기로 계속: %s", type(e).__name__)
    if embedder is not None:
        try:
            embed_missing(store, user_id, embedder)
            rankings.append(store.search_vector(user_id, lanes, embedder.embed([query])[0], pool))
        except Exception as e:  # 임베딩 API가 실패해도 검색은 키워드 결과로 계속한다
            log.warning("벡터 검색 실패, 키워드만 사용: %s", e)
    first = rrf(rankings) if rankings else []
    if (word := _single_word(query)) is not None:  # 'ra' → raw를 rate·ravallion보다 먼저(가까운 낱말부터, 같으면 원래 순위)
        first.sort(key=lambda c: _closeness(word, c.text))
    owners = {(c.owner_type, c.owner_id, c.part) for c in first}
    second = []
    for c in store.search_substring(user_id, lanes, needle_of(query), pool) if needle_of(query) else []:
        if (c.owner_type, c.owner_id, c.part) not in owners:
            owners.add((c.owner_type, c.owner_id, c.part))
            second.append(c)
    # 첨부 글자(#100)는 제목·본문·파일 이름으로 맞은 것 다음에(각각 1단계 → 2단계 순서 그대로)
    found = [*first, *second]
    return [c for c in found if c.lane != "attach_text"] + [c for c in found if c.lane == "attach_text"]


_PLAIN = re.compile(r"[가-힣぀-ヿ㐀-鿿A-Za-z0-9]+")
TERM_POOL = 10_000  # 낱말 하나에 맞는 조각을 이만큼까지 본다(AND를 글 단위로 맞추려고)


def _term_expr(term: str) -> str | None:
    """낱말(또는 구절) 하나 → FTS 식: 조각이 하나면 앞부분 일치(한글 2글자는 그대로), 여럿이면 이어진 구절."""
    toks = tokens(term)
    if not toks:
        return None
    if len(toks) == 1:
        tok = toks[0]
        return f'"{tok}"*' if tok.isascii() or len(tok) == 1 else f'"{tok}"'
    return '"' + " ".join(toks) + '"'


def _term_owners(store: Store, user_id: str, lanes: list[Lane], term: str, literal: bool) -> dict[tuple[str, str], Chunk]:
    """그 낱말이 맞는 글(owner)과 처음 맞은 조각. literal이면 글자 그대로 포함만(기호가 든 낱말)."""
    found: dict[tuple[str, str], Chunk] = {}
    if not literal and (expr := _term_expr(term)):
        try:
            for c in store.search_fts(user_id, lanes, expr, TERM_POOL):
                found.setdefault((c.owner_type, c.owner_id), c)
        except sqlite3.OperationalError as e:
            log.warning("FTS 식 오류, 글자 포함으로 계속: %s", type(e).__name__)
    for c in store.search_substring(user_id, lanes, term, TERM_POOL):
        found.setdefault((c.owner_type, c.owner_id), c)
    if literal and not found and len(tokens(term)) >= 2 and (expr := _term_expr(term)):
        # 글자 그대로 맞는 글이 하나도 없을 때만: 기호 사이 조각이 이어진 글(raw-3fb7a700() → raw-3fb7a700).
        # 조각 하나(<b> → b, 1009)로는 넓히지 않는다
        try:
            for c in store.search_fts(user_id, lanes, expr, TERM_POOL):
                found.setdefault((c.owner_type, c.owner_id), c)
        except sqlite3.OperationalError as e:
            log.warning("FTS 식 오류: %s", type(e).__name__)
    return found


def find_all_words(store: Store, user_id: str, lanes: list[Lane], query: str, limit: int, embedder: Embedder | None = None) -> list[Chunk]:
    """웹 찾기(2026-10-09 점검): 낱말이 여럿이면 모두 맞는 글만(AND, 글 단위 — 낱말이 다른 조각·첨부 글자에 있어도 된다).
    기호가 든 낱말(<b>, doc_1009)은 글자 그대로 포함만 본다(기호를 뗀 b·1009로 넓히지 않는다). 따옴표 구절은 구절 그대로.
    한글 세 글자 이상 낱말(없는낱말)도 2글자 조각 중 하나만 맞는 글로 넓히지 않는다(조각이 이어진 구절 또는 글자 그대로).
    순서는 find_chunks 그대로(그 밖에 맞은 글은 뒤에). 대화(category_search)도 이것을 쓴다(2026-10-09 결정 b, 전에는 웹만)."""
    query = " ".join((query or "").split())
    phrases, words = query_parts(query)
    terms = [(p, False) for p in phrases] + [(w, _PLAIN.fullmatch(w) is None) for w in words]
    if len(terms) == 1 and not terms[0][1] and not phrases and len(tokens(query)) <= 1:
        return find_chunks(store, user_id, lanes, query, limit, embedder)  # 조각 하나인 낱말(도시·ra·economic): 지금까지와 같다
    if not terms:
        return []
    allowed: dict[tuple[str, str], Chunk] | None = None
    for term, literal in terms:
        hits = _term_owners(store, user_id, lanes, term, literal)
        allowed = hits if allowed is None else {k: v for k, v in allowed.items() if k in hits}
        if not allowed:
            return []
    assert allowed is not None
    ranked = [c for c in find_chunks(store, user_id, lanes, query, max(limit, len(allowed)), embedder)
              if (c.owner_type, c.owner_id) in allowed]
    seen = {(c.owner_type, c.owner_id) for c in ranked}
    rest = [c for key, c in allowed.items() if key not in seen]
    return [*ranked, *rest][:limit] if limit else [*ranked, *rest]


def _single_word(query: str) -> str | None:
    """검색어가 영문·숫자 낱말 하나(따옴표 없이)면 그 낱말(소문자). 아니면 None."""
    phrases, words = query_parts(query)
    found = tokens(query)
    return found[0] if not phrases and len(words) == 1 and len(found) == 1 and found[0].isascii() else None


def _closeness(word: str, text: str) -> int:
    """앞부분이 맞는 낱말 중 가장 가까운 것의 남는 글자 수(raw ← ra: 1). 없으면 크게(벡터로만 걸린 것은 뒤로)."""
    return min((len(t) - len(word) for t in tokens(text) if t.startswith(word)), default=1_000)


def embed_missing(store: Store, user_id: str, embedder: Embedder, batch: int = 64) -> int:
    """임베딩이 비어 있는 청크를 채운다(새로 쓴 글, 인덱스 재생성 뒤). 채운 수를 돌려준다."""
    total = 0
    while chunks := store.chunks_missing_embedding(user_id, batch):
        vectors = embedder.embed([c.text for c in chunks])
        store.set_embeddings(user_id, {c.id: v for c, v in zip(chunks, vectors, strict=True)})
        total += len(chunks)
        if len(chunks) < batch:
            break
    return total
