"""하이브리드 검색: FTS5(키워드, 한글 bigram)와 벡터(코사인)를 RRF로 합친다.

임베딩 제공자가 없으면(EMBEDDINGS=none) FTS만 쓴다. 한국어 고유명사·학자 이름은 키워드 검색이 잡고,
뜻이 비슷한 문장은 벡터가 잡는다. 두 목록의 순위만 쓰므로 점수 척도를 맞출 필요가 없다.
"""

from __future__ import annotations

from typing import Protocol

from magus.store import Chunk, Store
from magus.store.base import Lane
from magus.textindex import match_query

RRF_K = 60


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
    return [Chunk(c.id, c.owner_type, c.owner_id, c.lane, c.text, scores[c.id]) for c in (chunks[cid] for cid in order)]


def hybrid_search(
    store: Store, user_id: str, query: str, lanes: list[Lane], k: int, embedder: Embedder | None = None
) -> list[Chunk]:
    pool = max(k * 4, 20)
    rankings: list[list[Chunk]] = []
    if match := match_query(query):
        rankings.append(store.search_fts(user_id, lanes, match, pool))
    if embedder is not None and query.strip():
        embed_missing(store, user_id, embedder)
        rankings.append(store.search_vector(user_id, lanes, embedder.embed([query])[0], pool))
    return rrf(rankings)[:k]


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
