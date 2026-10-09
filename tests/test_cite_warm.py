"""인용 계산 캐시를 뒤에서 데우기(2026-10-09 결정 f, melchior/warmer.py): 문헌이 바뀌거나 올린 문서를 가져온 직후 예약되어,
첫 인용 상태 탭·질문이 다시 계산하지 않는다. 같은 프로젝트는 줄에 한 번. CLI warm-cache."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest
from mcp import Client
from test_cite_cache import SECOND, _cache_file
from test_questions import BIB, TEXT

from magus import cli
from magus.config import Settings
from magus.melchior import warmer
from magus.melchior.bibliography import import_bibliography
from magus.melchior.cache import CiteCache
from magus.melchior.check import after_refs_changed
from magus.server import build_server
from magus.store import LocalStore

pytestmark = pytest.mark.anyio
SYNTH = Path(__file__).parent / "fixtures" / "synthetic" / "닿으려는_종_합성.docx"


@pytest.fixture
def warming(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(warmer, "ENABLED", True)


def _book(store: LocalStore) -> None:
    store.create_project("alice", "책", project_id="book")
    store.write_chapter("alice", "book", 1, TEXT, "x", title="첫 장")
    store.write_chapter("alice", "book", 2, SECOND, "x", title="둘째 장")
    import_bibliography(store, "alice", BIB)


def test_refs_changed_warms_in_background(store: LocalStore, warming: None):
    _book(store)
    store.create_project("alice", "원고 없는 프로젝트", project_id="empty")
    after_refs_changed(store, "alice")
    assert warmer.wait_idle(60)
    assert _cache_file(store).is_file()
    cache = CiteCache(store, "alice", "book")
    cache.chapters()
    assert cache.computed == 0  # 첫 화면이 다시 계산하지 않는다
    assert not (store.root / "users" / "alice" / "projects" / "empty" / ".cache").exists()  # 올린 문서 없는 프로젝트는 건너뜀


def test_same_project_is_queued_once(store: LocalStore, warming: None, monkeypatch: pytest.MonkeyPatch):
    _book(store)
    calls: list[str] = []
    started, gate = threading.Event(), threading.Event()

    def slow(_store, _user, project_id):
        started.set()
        gate.wait(10)
        calls.append(project_id)

    monkeypatch.setattr("magus.melchior.cache.warm", slow)
    warmer.schedule(store, "alice", ["book"])
    assert started.wait(10)  # 일꾼이 첫 것을 들고 계산 중
    for _ in range(4):
        warmer.schedule(store, "alice", ["book"])  # 그동안 넷 → 줄에는 한 번
    gate.set()
    assert warmer.wait_idle(30)
    assert calls == ["book", "book"]


def test_disabled_does_nothing(store: LocalStore):
    _book(store)
    after_refs_changed(store, "alice")  # conftest가 끔
    assert warmer.wait_idle(1) and not _cache_file(store).exists()


async def test_book_import_and_ref_put_schedule(store: LocalStore, settings: Settings, warming: None):
    inbox = store.root / "users" / "alice" / "inbox"
    inbox.mkdir(parents=True)
    (inbox / SYNTH.name).write_bytes(SYNTH.read_bytes())
    async with Client(build_server(settings, store)) as c:
        r = await c.call_tool("book_import", {"path": SYNTH.name, "project_id": "synth"})
        assert not r.is_error
        assert warmer.wait_idle(120)
        made = store.root / "users" / "alice" / "projects" / "synth" / ".cache" / "cites.json"
        assert made.is_file()
        before = made.stat().st_mtime_ns
        refs = store.list_refs("alice")
        r = await c.call_tool("category_put", {"book": "참고문헌", "author": "me", "source": {"key": refs[0].key}, "checked": True,
                                               "parts": [{"text": "고른 대목", "reason": "근거", "where": "p.1"}]})
        assert not r.is_error, r.content[0].text
        assert warmer.wait_idle(120)
        assert made.stat().st_mtime_ns > before  # 문헌 상태가 바뀌어 다시 데웠다
    cache = CiteCache(store, "alice", "synth")
    cache.chapters()
    assert cache.computed == 0


def test_cli_warm_cache(data_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    store = LocalStore(data_dir)
    _book(store)
    store.close()
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("USER_ID", "alice")
    cli.main(["warm-cache", "--all-users"])
    assert "alice/book:" in capsys.readouterr().out
    again = LocalStore(data_dir)
    assert _cache_file(again).is_file()
    again.close()
