from __future__ import annotations

import functools
import os
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from magus.config import Settings
from magus.store import LocalStore


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(autouse=True)
def _no_background_warm(monkeypatch: pytest.MonkeyPatch) -> None:
    """인용 계산 캐시를 뒤에서 데우는 일꾼(결정 f)은 시험에서 끈다(계산 수를 세는 시험·임시 폴더 정리와 겹치지 않게).
    켜고 보는 시험은 tests/test_cite_warm.py."""
    from magus.melchior import warmer

    monkeypatch.setattr(warmer, "ENABLED", False)


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


def wait_log(path: Path, *needles: str, until: Callable[[str], bool] | None = None, timeout: float = 10.0) -> str:
    """하위 프로세스(서버) 로그에 needles가 모두 나올 때까지(또는 until이 참일 때까지) 최대 timeout초 기다리고 글을 돌려준다.
    점검 24-b: 0.3초 쉬고 읽으면 느린 PC·CI에서 로그가 아직 쓰이지 않아 실패할 수 있었다. 제때 안 나오면 마지막 글을 돌려준다(단정이 실패를 알린다)."""
    deadline = time.monotonic() + timeout
    while True:
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        if all(n in text for n in needles) and (until is None or until(text)):
            return text
        if time.monotonic() > deadline:
            return text
        time.sleep(0.05)


REQUIRE_BROWSER = os.environ.get("MAGUS_REQUIRE_BROWSER") == "1"


def needs_tools(reason: str, *tools: Any) -> Callable[[Any], Any]:
    """브라우저 시험의 도구(node·Chrome)가 없으면 건너뛴다(pytest -rs로 사유가 보인다). MAGUS_REQUIRE_BROWSER=1이면 건너뛰지 않고 실패한다
    (점검 24-d: Docker·CI에서 조용히 빠져도 알아차리기 어려웠다)."""
    missing = any(t is None for t in tools)
    if missing and REQUIRE_BROWSER:
        def fail(fn: Any) -> Any:
            @functools.wraps(fn)
            def wrapper(*args: Any, **kwargs: Any) -> None:
                pytest.fail(f"{reason} — MAGUS_REQUIRE_BROWSER=1이라 건너뛰지 않는다")

            return wrapper

        return fail
    return pytest.mark.skipif(missing, reason=reason)
