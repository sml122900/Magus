"""원본 파일 입출력과 저장소 공용 유틸."""

from __future__ import annotations

import functools
import json
import os
import secrets
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar

F = TypeVar("F", bound=Callable[..., Any])


def locked(fn: F) -> F:
    # MCPServer는 동기 도구를 워커 스레드에서 돌린다. 파일+인덱스 갱신을 한 덩어리로 묶는다.
    @functools.wraps(fn)
    def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
        with self._lock:
            return fn(self, *args, **kwargs)

    return wrapper  # type: ignore[return-value]


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def write_text(path: Path, text: str) -> None:
    # 원본 파일이 반쯤 쓰인 채로 남지 않도록 임시 파일에 쓴 뒤 교체한다(줄 끝은 바꾸지 않는다: 전의 newline="\n"과 같다).
    write_bytes(path, text.encode("utf-8"))


def write_bytes(path: Path, data: bytes) -> None:
    """임시 파일에 쓴 뒤 교체(원자적). 임시 이름에 무작위 꼬리(점검 10-a: 서버와 CLI가 같은 파일을 동시에 쓰면 고정 이름 .tmp가 섞였다)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{secrets.token_hex(4)}.tmp")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def mtime(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def to_int(value: str | None, default: int | None = None) -> int | None:
    try:
        return int(value) if value not in (None, "") else default
    except ValueError:
        return default
