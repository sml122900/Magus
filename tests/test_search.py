"""7단계: 하이브리드 검색(FTS5 + 벡터 RRF), 임베딩 제공자 스텁(실제 호출 없음), 완료 기준 일부."""

from __future__ import annotations

import dataclasses
import logging

import pytest
from mcp import Client

from magus.book.demo import seed_demo
from magus.config import Settings
from magus.embeddings import OpenAIEmbedder, VoyageEmbedder, get_embedder
from magus.ids import new_id
from magus.search import embed_missing, hybrid_search, rrf
from magus.server import build_server
from magus.store import Chunk, Idea, LocalStore
from magus.textindex import chunk_text, match_query, tokens

pytestmark = pytest.mark.anyio


class FakeEmbedder:
    """개념 사전으로 벡터를 만든다. '바다'와 '해양'은 같은 방향 → 키워드가 달라도 벡터 검색이 잡는다."""

    concepts = [("바다", "해양", "물"), ("숲", "나무", "삼림"), ("도시", "거리", "골목")]

    def __init__(self):
        self.calls = 0

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        return [[float(any(w in t for w in words)) for words in self.concepts] + [0.01] for t in texts]


class BrokenEmbedder:
    def embed(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("API down")


def _idea(store: LocalStore, text: str, author: str = "me") -> str:
    [idea] = store.add_ideas("alice", [Idea(new_id(), text, "thought", author)])
    return idea.id


def test_tokens_bigram_and_latin():
    assert tokens("갤러는 Clack의 2012") == ["갤러", "러는", "clack", "의", "2012"]
    assert match_query("갤러") == '"갤러"'
    assert match_query("!!") is None


def test_chunk_text_respects_size():
    pieces = chunk_text("\n\n".join(["가" * 300] * 5), size=800, overlap=100)
    assert len(pieces) >= 2 and all(len(p) <= 800 + 100 for p in pieces)


def test_rrf_merges_rankings():
    a, b, c = (Chunk(i, "idea", str(i), "idea_me", t) for i, t in [(1, "a"), (2, "b"), (3, "c")])
    merged = rrf([[a, b], [b, c]])
    assert [m.id for m in merged] == [2, 1, 3]  # 두 목록에 다 있는 b가 1등


def test_fts_only_vs_hybrid(store: LocalStore):
    sea = _idea(store, "바다는 모든 생명이 돌아가는 곳이다")
    _idea(store, "숲은 천천히 자란다")
    assert hybrid_search(store, "alice", "해양", ["idea_me"], 5) == []  # 키워드 불일치: FTS만으로는 못 찾는다
    fake = FakeEmbedder()
    hits = hybrid_search(store, "alice", "해양", ["idea_me"], 5, fake)
    assert hits[0].owner_id == sea  # 벡터가 잡는다
    # 키워드 일치(FTS) + 벡터 일치가 겹치면 위로 온다
    both = hybrid_search(store, "alice", "바다 생명", ["idea_me"], 5, fake)
    assert both[0].owner_id == sea


def test_embeddings_are_derived_and_refilled(store: LocalStore):
    _idea(store, "도시의 골목")
    fake = FakeEmbedder()
    assert embed_missing(store, "alice", fake) == 1
    assert store.chunks_missing_embedding("alice") == []
    store.reindex()  # 임베딩은 파생값: 재생성하면 비고, 다음 검색 때 다시 채운다
    assert len(store.chunks_missing_embedding("alice")) == 1
    hybrid_search(store, "alice", "거리", ["idea_me"], 5, fake)
    assert store.chunks_missing_embedding("alice") == []


def test_embedder_failure_falls_back_to_fts(store: LocalStore, caplog):
    sea = _idea(store, "바다는 넓다")
    with caplog.at_level(logging.WARNING, logger="magus.search"):
        hits = hybrid_search(store, "alice", "바다", ["idea_me"], 5, BrokenEmbedder())
    assert [h.owner_id for h in hits] == [sea] and "FTS만 사용" in caplog.text


def test_provider_selection_and_request_shape(caplog):
    base = Settings.from_env({"USER_ID": "u"})
    assert get_embedder(base) is None
    with caplog.at_level(logging.WARNING, logger="magus.embeddings"):
        assert get_embedder(dataclasses.replace(base, embeddings="voyage")) is None
    assert "VOYAGE_API_KEY" in caplog.text
    assert isinstance(get_embedder(dataclasses.replace(base, embeddings="voyage", voyage_api_key="k")), VoyageEmbedder)
    openai = get_embedder(dataclasses.replace(base, embeddings="openai", openai_api_key="k"), model="m-1")
    assert isinstance(openai, OpenAIEmbedder) and openai.model == "m-1"

    sent = {}

    def fake_post(url, headers, payload):  # 네트워크 없이 요청 모양만 확인한다
        sent.update(url=url, headers=headers, payload=payload)
        return {"data": [{"index": 1, "embedding": [0.2]}, {"index": 0, "embedding": [0.1]}]}

    vectors = VoyageEmbedder("secret", post=fake_post).embed(["가", "나"])
    assert vectors == [[0.1], [0.2]]
    assert sent["url"].startswith("https://api.voyageai.com/") and sent["headers"]["Authorization"] == "Bearer secret"
    assert sent["payload"] == {"input": ["가", "나"], "model": "voyage-3.5"}
    OpenAIEmbedder("k", post=fake_post).embed(["가"])
    assert sent["url"] == "https://api.openai.com/v1/embeddings" and sent["payload"]["model"] == "text-embedding-3-small"


async def test_server_uses_embedder_for_idea_search(settings: Settings, store: LocalStore):
    sea = _idea(store, "바다는 모든 생명이 돌아가는 곳이다")
    async with Client(build_server(settings, store, FakeEmbedder())) as client:
        result = await client.call_tool("idea_search", {"query": "해양"})
        assert sea in result.content[0].text


async def test_every_tool_is_user_scoped(settings: Settings, store: LocalStore, tmp_path):
    """완료 기준: 모든 쿼리가 user_id로 필터된다(다른 user_id로 호출하면 빈 결과)."""
    seed_demo(store, settings.user_id)
    alice_idea = _idea(store, "앨리스의 생각: 바다")
    async with Client(build_server(settings, store)) as client:
        alice_style = (await client.call_tool("style_add", {"passage": "짧다.", "reason": "짧은 호흡", "tags": {"호흡": "짧음", "시점": "1인칭", "열기": "장면", "장치": [], "어미": "-다", "톤": "건조"}})).content[0].text.split()[2]
        await client.call_tool("ref_add", {"bib": {"authors": "Clack, J.", "year": "2012", "title": "Gaining ground"}, "passages": [{"text": "네발동물", "reason": "근거"}]})
        await client.call_tool("category_create", {"name": "앨리스의 사례", "template": "사례"})
        await client.call_tool("category_put", {"category": "앨리스의 사례", "author": "me", "content": "앨리스의 바다 사례", "untitled": True})
    bob = dataclasses.replace(settings, user_id="bob")
    empty_markers = ("없습니다", "결과 없음", "0건", "비어 있다", "아직 없다")
    store.put_inbox(settings.user_id, "앨리스원고.docx", b"x")  # 받은함도 사용자별이다
    calls = {
        "book_outline": {},
        "book_read_chapter": {"number": 1, "project_id": "demo"},
        "book_write_chapter": {"number": 1, "content": "x", "note": "y", "project_id": "demo"},
        "book_issues": {"project_id": "demo"},
        "book_decide": {"text": "x", "project_id": "demo"},
        "book_issue_add": {"text": "x", "project_id": "demo"},
        "book_issue_close": {"id": "I1", "project_id": "demo"},
        "book_export": {"project_id": "demo"},
        "book_import": {"path": "없는파일.docx"},
        "files_list": {},
        "ref_check": {"chapter_number": 1, "project_id": "demo"},
        "ref_search": {"query": "네발동물"},
        "idea_search": {"query": "바다", "author": "all"},
        "style_search": {"query": "짧은 호흡"},
        "idea_delete": {"id": alice_idea, "note": "x"},  # 같은 id라도 bob의 휴지통 일이다(앨리스 것은 못 옮긴다)
        "style_delete": {"id": alice_style, "note": "x"},
        "book_questions": {"project_id": "demo"},
        "book_answer": {"question_id": "bibonly:clack2012", "choice": "keep", "project_id": "demo"},
        "category_list": {},
        "category_search": {"query": "바다"},
        "category_put": {"category": "앨리스의 사례", "author": "me", "content": "x", "untitled": True},
        "category_edit": {"category": "앨리스의 사례", "color": "빨강"},
        "category_trash": {"category": "앨리스의 사례", "note": "x"},
    }
    async with Client(build_server(bob, store)) as client:
        names = {t.name for t in (await client.list_tools()).tools}
        assert len(names) == 30
        for name, args in calls.items():
            result = await client.call_tool(name, args)
            text = result.content[0].text
            assert result.is_error or any(m in text for m in empty_markers), (name, text)
            assert "앨리스의 바다" not in text and "네발동물”" not in text, (name, text)
        # 만들기·제목 기본값은 밥 자신의 책장에만 쓴다(앨리스와 같은 이름이어도)
        assert not (await client.call_tool("category_create", {"name": "앨리스의 사례"})).is_error
        await client.call_tool("category_title_default", {"mode": "ai"})
    # 쓰기 도구(ref_import_bibliography, ref_add, idea_*, style_add)는 bob 자신의 책장에만 쓴다
    assert store.list_refs("bob") == [] and store.list_ideas("bob") == [] and store.list_styles("bob") == []
    assert [c.items for c in store.list_categories("bob")] == [0] and [c.items for c in store.list_categories(settings.user_id)] == [1]
    assert store.get_shelf_settings("bob").title_default == "ai" and store.get_shelf_settings(settings.user_id).title_default == "ask"
    assert alice_idea in {i.id for i in store.list_ideas(settings.user_id)} and alice_style in {s.id for s in store.list_styles(settings.user_id)}
