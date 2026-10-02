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
