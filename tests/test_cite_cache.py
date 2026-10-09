"""인용 계산 캐시(2026-10-09, melchior/cache.py): 결과가 캐시 없이 계산한 것과 글자까지 같고, 원고·문헌·용어가 바뀌면 다시 계산한다."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from test_questions import BIB, TEXT  # tests/는 패키지가 아니다(rootdir 모드)

from magus.book.documents import build_source_check
from magus.melchior.author_report import build_author_report
from magus.melchior.bibliography import import_bibliography
from magus.melchior.cache import NAME, CiteCache
from magus.melchior.check import after_refs_changed
from magus.melchior.questions import build_questions
from magus.melchior.refs import add_alias
from magus.melchior.report import build_cite_report
from magus.store import LocalStore

SECOND = "그랜트의 관찰은 유명하다. 존 그랜트는 런던의 사망표를 모았다. (Maddison, 2001)과 매디슨(2001)."


def _book(store: LocalStore, user: str = "alice") -> None:
    store.create_project(user, "책", project_id="book")
    store.write_chapter(user, "book", 1, TEXT, "x", title="첫 장")
    store.write_chapter(user, "book", 2, SECOND, "x", title="둘째 장")
    import_bibliography(store, user, BIB)
    after_refs_changed(store, user)


def _cache_file(store: LocalStore, user: str = "alice") -> Path:
    return store.root / "users" / user / "projects" / "book" / ".cache" / f"{NAME}.json"


def _everything(store: LocalStore) -> str:
    """캐시를 쓰는 모든 결과를 한 문자열로(비교용)."""
    report = build_cite_report(store, "alice", "book")
    questions = [asdict(q) for q in build_questions(store, "alice", "book")]
    markdown, _ = build_source_check(store, "alice", "book", "문서")
    markdown = "\n".join(line for line in markdown.splitlines() if "만든 시각" not in line and "의 사진입니다" not in line)
    return json.dumps([report.render(top=500), report.per_chapter, sorted(report.uncited), questions, markdown,
                       build_author_report(store, "alice", "book", "오늘")], ensure_ascii=False, default=sorted)


def _fresh(store: LocalStore) -> str:
    """캐시 파일을 지우고(파생값) 처음부터 계산한 결과."""
    _cache_file(store).unlink(missing_ok=True)
    out = _everything(store)
    _cache_file(store).unlink(missing_ok=True)
    return out


def test_cached_results_equal_fresh_ones(store: LocalStore):
    _book(store)
    fresh = _fresh(store)
    first = _everything(store)  # 캐시를 만든다
    assert _cache_file(store).exists()
    cache = CiteCache(store, "alice", "book")
    cache.chapters()
    assert cache.computed == 0  # 두 번째부터는 다시 계산하지 않는다
    assert first == fresh and _everything(store) == fresh


def test_changes_recompute_only_what_changed(store: LocalStore):
    _book(store)
    _everything(store)
    # 문헌이 바뀌면(표기를 이음) 인용 대조를 다시 하고 결과가 바뀐다 — 캐시 없이 계산한 것과 같다
    before = _everything(store)
    add_alias(store, "alice", "maddison2001", "매디슨(2001)")
    after_refs_changed(store, "alice")
    cache = CiteCache(store, "alice", "book")
    cache.chapters()
    assert cache.computed == 2
    changed = _everything(store)
    assert changed != before and changed == _fresh(store)
    # 장 하나를 고치면 그 장만
    _everything(store)
    store.write_chapter("alice", "book", 2, SECOND + " Graunt(1662)도.", "고침")
    cache = CiteCache(store, "alice", "book")
    cache.chapters()
    assert cache.computed == 1
    assert _everything(store) == _fresh(store)
    # 비인용 용어가 바뀌어도 다시
    _everything(store)
    store.set_non_citation_terms("alice", "book", ["가나다"])
    after_refs_changed(store, "alice")
    assert CiteCache(store, "alice", "book").chapters() and _everything(store) == _fresh(store)


def test_name_mentions_kept_per_author(store: LocalStore):
    """이름 찾기는 그 문헌의 저자 칸과 장 본문이 같으면 다시 하지 않는다(문헌 상태만 바뀌어도 그대로)."""
    _book(store)
    _everything(store)
    data = json.loads(_cache_file(store).read_text(encoding="utf-8"))
    assert "graunt1662" in data["mentions"]
    assert any(data["mentions"]["graunt1662"]["found"].values())  # 둘째 장의 '존 그랜트'
    questions = {q.id: q for q in build_questions(store, "alice", "book")}
    assert "존 그랜트" in questions["bibonly:graunt1662"].text and "제2장" in questions["bibonly:graunt1662"].text


def test_broken_or_foreign_cache_is_ignored(store: LocalStore):
    _book(store)
    fresh = _fresh(store)
    _cache_file(store).parent.mkdir(parents=True, exist_ok=True)
    for broken in ("{깨진", "[]", json.dumps({"version": 99, "checks": {"x": 1}}),
                   json.dumps({"version": 1, "code": "다른 코드", "scope": "x", "checks": {}, "mentions": {}})):
        _cache_file(store).write_text(broken, encoding="utf-8")
        assert _everything(store) == fresh


def test_cache_is_derived_and_invisible(store: LocalStore, tmp_path: Path):
    """캐시는 프로젝트 폴더의 .cache/ 한 파일. 색인을 다시 만들어도 수치가 같고, 다른 사용자에게 섞이지 않는다."""
    _book(store)
    _everything(store)
    assert sorted(p.name for p in _cache_file(store).parent.iterdir()) == [f"{NAME}.json"]
    before = build_cite_report(store, "alice", "book").per_chapter
    store.reindex()
    assert build_cite_report(store, "alice", "book").per_chapter == before
    _book(store, "bob")
    assert not _cache_file(store, "bob").exists()
    build_questions(store, "bob", "book")
    assert _cache_file(store, "bob").exists() and _cache_file(store, "alice").exists()
