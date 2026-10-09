"""인용 계산 캐시를 뒤에서 데운다(2026-10-09 사용자 결정 f). 첫 인용 상태 탭·답해 주실 질문·출처 확인 문서도 빠르게.

- 언제: 문헌이 바뀐 직후(after_refs_changed — 문헌 글 넣기·고치기·참고문헌 들이기·표기 잇기·비인용 용어·노드 연결)와
  올린 문서·수정본을 가져온 직후(가져오기도 끝에 after_refs_changed를 부른다). 그 사용자의 올린 문서가 있는 프로젝트를 모두 예약한다.
- 어떻게: 일꾼 스레드 하나가 줄을 차례로 비운다. 같은 (사용자, 프로젝트)는 줄에 한 번만. 계산 도중 문헌이 또 바뀌면
  CiteCache.save가 쓰지 않고, 다시 예약된 것이 새로 계산한다. 실패해도 다음 화면이 다시 계산하므로 남기기만 한다.
- 서버(magus serve)에서만 켠다(기본은 꺼짐). 다른 CLI 명령·스크립트는 프로세스가 곧 끝나거나 저장소를 닫아 계산이 잘린다. 시험도 끈다(conftest).
"""

from __future__ import annotations

import logging
import threading
import time

from magus.store import Store

log = logging.getLogger("magus.cache")

ENABLED = False  # magus serve만 켠다(cli.main). 라이브러리로 쓰는 스크립트는 저장소를 닫은 뒤에도 일꾼이 돌 수 있어 끈 채로 둔다
_lock = threading.Lock()
_idle = threading.Event()
_idle.set()
_queue: dict[tuple[int, str, str], Store] = {}  # (id(store), 사용자, 프로젝트) → store. 넣은 순서대로
_worker: threading.Thread | None = None


def projects_with_manuscript(store: Store, user_id: str) -> list[str]:
    return [p.id for p in store.list_projects(user_id) if store.list_chapters(user_id, p.id)]


def schedule(store: Store, user_id: str, project_ids: list[str] | None = None) -> None:
    """뒤에서 데울 프로젝트를 줄에 넣는다(project_ids가 없으면 그 사용자의 올린 문서가 있는 프로젝트 모두). 바로 돌아온다."""
    global _worker
    if not ENABLED:
        return
    try:
        ids = project_ids if project_ids is not None else projects_with_manuscript(store, user_id)
    except Exception as e:  # noqa: BLE001 — 예약은 덤이다
        log.warning("인용 계산 캐시 예약 실패: %s", type(e).__name__)
        return
    with _lock:
        for project_id in ids:
            _queue.setdefault((id(store), user_id, project_id), store)
        if _queue and (_worker is None or not _worker.is_alive()):
            _idle.clear()
            _worker = threading.Thread(target=_run, name="magus-cite-warm", daemon=True)
            _worker.start()


def _run() -> None:
    from magus.melchior.cache import warm  # cache → questions → check가 이 모듈을 부른다(순환 import 피함)

    while True:
        with _lock:
            if not _queue:
                _idle.set()
                return
            key = next(iter(_queue))
            store = _queue.pop(key)
        started = time.monotonic()
        warm(store, key[1], key[2])
        log.info("인용 계산 캐시 데움: user=%s project=%s %.1f초", key[1], key[2], time.monotonic() - started)


def wait_idle(timeout: float = 60.0) -> bool:
    """줄이 빌 때까지 기다린다(시험·CLI용). 제때 비면 True."""
    return _idle.wait(timeout)
