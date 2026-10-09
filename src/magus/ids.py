"""id·시각 유틸. user_id·project_id는 디렉터리 이름이 되므로 안전한 문자만 허용한다."""

from __future__ import annotations

import re
import secrets
import threading
from datetime import UTC, datetime, timedelta

_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")


def safe_id(value: str, what: str = "id") -> str:
    if not _SAFE_ID.fullmatch(value):
        raise ValueError(f"{what}={value!r}: 영문·숫자·_·-만, 64자 이하, 영문/숫자로 시작")
    return value


_last = datetime.min.replace(tzinfo=UTC)
_clock = threading.Lock()


def utcnow() -> str:
    """UTC ISO 8601(밀리초 단위, Z 접미사). 문자열 정렬이 곧 시간 정렬이다.
    같은 프로세스 안에서는 항상 증가한다. 연속 쓰기의 순서(최근 변경, 최근 프로젝트)가 같은 시각으로 겹치지 않게 하려는 것이다."""
    global _last
    with _clock:
        now = max(datetime.now(UTC), _last + timedelta(milliseconds=1))
        now = now.replace(microsecond=now.microsecond // 1000 * 1000)
        _last = now
    return now.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def new_id() -> str:
    """책장 항목(아이디어·문체) id. 시간순으로 정렬되고 파일 이름으로 쓸 수 있다. 예: 20261002193152383-a1b2c3"""
    return re.sub(r"\D", "", utcnow()) + "-" + secrets.token_hex(3)


STAMP = "%Y-%m-%d %H:%M:%S"  # 수정본 줄(전체 현황)과 올린 파일 목록이 같은 형식으로 앞뒤를 가리게(점검 16-1)


def local_time(iso: str, fmt: str = "%m-%d %H:%M") -> str:
    """표시용: UTC ISO → 서버 로컬 시각."""
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone().strftime(fmt)
    except ValueError:
        return iso
