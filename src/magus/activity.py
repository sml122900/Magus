"""활동 기록(2026-10-14 사용자 요청). 서버 로그는 컨테이너를 새로 만들면 사라지고 HTTPS 접근 로그는 남기지 않으므로
(Caddyfile `output discard`), 지우고 되살린 일이 언제 있었는지는 이 기록으로 본다(docs/deploy.md 4절).

- 사용자 폴더의 `.activity.log`에 한 줄: `시각(UTC) · 동작 · 대상 종류 · 대상 id · 경로`.
  동작: 휴지통으로 · 되살리기 · 영구 삭제 · 휴지통 비우기 · 프로젝트 만들기 · 문서 업데이트. 경로: 웹 · 대화 · 운영자(CLI).
- 이메일·제목·본문·파일 이름은 넣지 않는다. 대상은 id만(올린 파일은 이름 대신 휴지통 id).
- 90일 지난 줄은 다음 기록 때와 서버를 띄울 때 지운다. 사용자 폴더 안이라 백업(restic)에 들어간다.
- 한 동작 안에서 저장소가 다른 동작을 부르면(노드째 휴지통 → 책 휴지통) 바깥 동작 한 줄만 남긴다(스레드마다 `_local.busy`).
- 기록이 실패해도 동작은 막지 않는다(경고 로그에 예외 종류만).
"""

from __future__ import annotations

import functools
import logging
import os
import re
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from magus.ids import utcnow

LOG_NAME = ".activity.log"
KEEP_DAYS = 90
SEP = " · "
TRASH, RESTORE, PURGE, EMPTY, CREATE, UPDATE = "휴지통으로", "되살리기", "영구 삭제", "휴지통 비우기", "프로젝트 만들기", "문서 업데이트"
KINDS = {"project": "프로젝트", "node": "노드", "category": "책", "category_item": "글", "attachment": "첨부",
         "document": "만든 문서", "manuscript": "올린 문서", "inbox": "올린 파일", "trash": "휴지통"}
WEB, CHAT, OPERATOR = "웹", "대화", "운영자"
VIA: ContextVar[str] = ContextVar("magus_activity_via", default=OPERATOR)  # 웹은 Web._wrap이, 대화는 ToolCallLog가 정한다

log = logging.getLogger("magus.activity")
_local = threading.local()
_write_lock = threading.Lock()
_UNSAFE = re.compile(r"[\s·]+")


@contextmanager
def via(name: str) -> Iterator[None]:
    token = VIA.set(name)
    try:
        yield
    finally:
        VIA.reset(token)


def line(action: str, kind: str, target: str, *, at: str | None = None, path: str | None = None) -> str:
    """기록 한 줄(줄바꿈 없음). 대상 id의 공백·가운뎃점은 _로, 120자까지."""
    return SEP.join((at or utcnow(), action, KINDS.get(kind, kind), _UNSAFE.sub("_", target.strip())[:120] or "-", path or VIA.get()))


def _cutoff(now: datetime | None) -> str:
    return ((now or datetime.now(UTC)) - timedelta(days=KEEP_DAYS)).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def prune(user_dir: Path, now: datetime | None = None) -> int:
    """90일 지난 줄을 지운다(첫 줄이 기준보다 새것이면 읽기만). 지운 줄 수."""
    path = user_dir / LOG_NAME
    with _write_lock:
        if not path.is_file():
            return 0
        cutoff = _cutoff(now)
        with path.open(encoding="utf-8") as f:
            first = f.readline()
        if first[:24] >= cutoff:
            return 0
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        kept = [x for x in lines if x[:24] >= cutoff]
        tmp = path.with_name(LOG_NAME + ".tmp")
        tmp.write_text("".join(kept), encoding="utf-8")
        os.replace(tmp, path)
        return len(lines) - len(kept)


def prune_all(users_dir: Path, now: datetime | None = None) -> int:
    """서버를 띄울 때 모든 사용자 폴더에서 90일 지난 줄을 지운다."""
    total = 0
    for user_dir in sorted(p for p in users_dir.iterdir() if p.is_dir()) if users_dir.is_dir() else []:
        try:
            total += prune(user_dir, now)
        except OSError as e:
            log.warning("활동 기록 정리 실패: %s", type(e).__name__)
    return total


def write(user_dir: Path, action: str, kind: str, target: str, *, now: datetime | None = None) -> None:
    """한 줄을 덧붙인다(먼저 90일 지난 줄을 지운다). 실패해도 예외를 올리지 않는다."""
    try:
        prune(user_dir, now)
        at = (now.isoformat(timespec="milliseconds").replace("+00:00", "Z") if now else None)
        text = line(action, kind, target, at=at) + "\n"
        with _write_lock:
            user_dir.mkdir(parents=True, exist_ok=True)
            with (user_dir / LOG_NAME).open("a", encoding="utf-8") as f:
                f.write(text)
    except OSError as e:
        log.warning("활동 기록 실패: %s", type(e).__name__)


def busy() -> bool:
    return bool(getattr(_local, "busy", False))


@contextmanager
def _outer() -> Iterator[bool]:
    outer = not busy()
    _local.busy = True
    try:
        yield outer
    finally:
        if outer:
            _local.busy = False


Target = Callable[[tuple[Any, ...], dict[str, Any], Any], str | None]


def logged(action: str, kind: str | Callable[[tuple[Any, ...]], str], target: Target) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """저장소 메서드(self, user_id, …)에 붙인다. 바깥 동작이 성공하고 target이 id를 주면 그 사용자 기록에 한 줄."""

    def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(fn)
        def run(self: Any, user_id: str, *args: Any, **kwargs: Any) -> Any:
            with _outer() as outer:
                result = fn(self, user_id, *args, **kwargs)
            if outer and (found := target(args, kwargs, result)):
                self.record_activity(user_id, action, kind(args) if callable(kind) else kind, found)
            return result

        return run

    return deco


class Step:
    target: str | None = None


@contextmanager
def step(store: Any, user_id: str, action: str, kind: str) -> Iterator[Step]:
    """저장소 밖의 한 동작(문서 업데이트 등). 안에서 부른 저장소 동작은 따로 적지 않고, 끝까지 가면 이 한 줄만(target을 채웠을 때)."""
    held = Step()
    with _outer() as outer:
        yield held
    if outer and held.target:
        store.record_activity(user_id, action, kind, held.target)
