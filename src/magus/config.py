"""환경변수 설정. P0는 USER_ID 하나로 단일 사용자지만, 코드는 user_id를 항상 인자로 받는다."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
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
    # 웹(원격): 세션·다운로드 링크 서명 비밀, 웹 로그인용 OAuth 클라이언트(인증 서버에 등록한 것)
    session_secret: str | None = None
    web_client_id: str | None = None
    web_client_secret: str | None = None
    # 글의 첨부 한 개(#97). 사용자 전체는 max_user_bytes에 함께 든다
    max_attach_bytes: int = 20_000_000
    # 웹 도움말(#97): 서버에서만 Anthropic API를 부른다(키는 브라우저로 내려가지 않는다). 키가 없으면 도움말만 꺼진다
    anthropic_api_key: str | None = field(default=None, repr=False)  # repr·로그에 남지 않게
    help_model: str = "claude-haiku-4-5-20251001"
    help_max_tokens: int = 600
    help_daily_limit: int = 30  # 사용자별 하루 질문 수
    help_dir: Path | None = None  # 도움말 문서 폴더(없으면 저장소의 docs/help)
    # 개인정보 처리방침 화면 /privacy(2026-10-14): 사용자가 승인하기 전에는 꺼 둔다(꺼지면 404). 글은 저장소의 docs/drafts/privacy.md
    privacy_page: bool = False
    privacy_file: Path | None = None

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
            session_secret=env.get("SESSION_SECRET") or None,
            web_client_id=env.get("WEB_CLIENT_ID") or None,
            web_client_secret=env.get("WEB_CLIENT_SECRET") or None,
            max_attach_bytes=_mb(env, "MAX_ATTACH_MB", 20),
            anthropic_api_key=(env.get("ANTHROPIC_API_KEY") or "").strip() or None,
            help_model=(env.get("HELP_MODEL") or "").strip() or "claude-haiku-4-5-20251001",
            help_max_tokens=_count(env, "HELP_MAX_TOKENS", 600),
            help_daily_limit=_count(env, "HELP_DAILY_LIMIT", 30),
            help_dir=Path(env["HELP_DIR"]).resolve() if env.get("HELP_DIR") else None,
            privacy_page=(env.get("PRIVACY_PAGE") or "").strip().lower() in ("1", "on", "true", "yes"),
            privacy_file=Path(env["PRIVACY_FILE"]).resolve() if env.get("PRIVACY_FILE") else None,
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


def _count(env: Mapping[str, str], name: str, default: int) -> int:
    raw = (env.get(name) or "").strip()
    try:
        value = int(raw) if raw else default
    except ValueError as e:
        raise ValueError(f"{name}={raw!r}: 정수여야 한다") from e
    if value < 0:
        raise ValueError(f"{name}는 0 이상이어야 한다")
    return value
