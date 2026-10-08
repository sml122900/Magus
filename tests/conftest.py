from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from magus.config import Settings
from magus.store import LocalStore


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "data"


@pytest.fixture
def store(data_dir: Path) -> Iterator[LocalStore]:
    s = LocalStore(data_dir)
    yield s
    s.close()


@pytest.fixture
def settings(data_dir: Path) -> Settings:
    return Settings.from_env({"USER_ID": "alice", "DATA_DIR": str(data_dir)})


def make_book(store: LocalStore, user: str, name: str, context: str | None = None, floor: str = "common", node: str | None = None,
              fields: tuple[str, ...] = (), template: str = "blank") -> str:
    """시험용 책(#96: 종류 없음). context: 자주 쓰는 컨텍스트 이름(문체·원고·논문·생각 메모) 또는 None."""
    from magus.contexts import Context

    saved = {c.name: c for c in store.list_saved_contexts(user)}
    contexts = (Context(saved[context].name, saved[context].text),) if context else ()
    return store.create_category(user, name, template, "#1f2f5c", fields, floor, node, contexts=contexts).id
