"""환경변수 설정. P0는 USER_ID 하나로 단일 사용자지만, 코드는 user_id를 항상 인자로 받는다."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from magus.auth import AuthConfig
from magus.ids import safe_id

EMBEDDING_PROVIDERS = ("none", "voyage", "openai")


@dataclass(frozen=True)
class Settings:
    user_id: str
    data_dir: Path
    embeddings: str = "none"
    voyage_api_key: str | None = None
    openai_api_key: str | None = None
    # 도구가 받은 상대 경로(fixtures/papers/논문.pdf)를 푸는 기준. Desktop이 띄우는 작업 폴더는 정해져 있지 않다.
    files_root: Path | None = None
    # 원격(HTTP) 모드의 인증 설정. AUTH_ISSUER가 없으면 None(로컬 모드: USER_ID 하나)
    auth: AuthConfig | None = None
    # 한도(넘으면 명확한 오류): 업로드 한 개, 사용자별 저장 용량, MCP 요청 본문
    max_upload_bytes: int = 50_000_000
    max_user_bytes: int = 1_000_000_000
    max_request_bytes: int = 2_000_000

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if env is None else env
        embeddings = (env.get("EMBEDDINGS") or "none").strip().lower()
        if embeddings not in EMBEDDING_PROVIDERS:
            raise ValueError(f"EMBEDDINGS={embeddings!r}: {'|'.join(EMBEDDING_PROVIDERS)} 중 하나여야 한다")
        data_dir = Path(env.get("DATA_DIR") or "./data").resolve()
        return cls(
            user_id=safe_id((env.get("USER_ID") or "default").strip(), "USER_ID"),
            data_dir=data_dir,
            embeddings=embeddings,
            voyage_api_key=env.get("VOYAGE_API_KEY") or None,
            openai_api_key=env.get("OPENAI_API_KEY") or None,
            files_root=Path(env.get("FILES_DIR") or data_dir.parent).resolve(),
            auth=AuthConfig.from_env(env),
            max_upload_bytes=_mb(env, "MAX_UPLOAD_MB", 50),
            max_user_bytes=_mb(env, "MAX_USER_MB", 1000),
            max_request_bytes=_mb(env, "MAX_REQUEST_MB", 2),
        )


def _mb(env: Mapping[str, str], name: str, default: float) -> int:
    raw = (env.get(name) or "").strip()
    try:
        value = float(raw) if raw else default
    except ValueError as e:
        raise ValueError(f"{name}={raw!r}: MB 단위 숫자여야 한다") from e
    if value <= 0:
        raise ValueError(f"{name}는 0보다 커야 한다")
    return int(value * 1_000_000)
