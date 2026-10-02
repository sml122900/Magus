"""환경변수 설정. P0는 USER_ID 하나로 단일 사용자지만, 코드는 user_id를 항상 인자로 받는다."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from magus.ids import safe_id

EMBEDDING_PROVIDERS = ("none", "voyage", "openai")


@dataclass(frozen=True)
class Settings:
    user_id: str
    data_dir: Path
    embeddings: str = "none"
    voyage_api_key: str | None = None
    openai_api_key: str | None = None

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if env is None else env
        embeddings = (env.get("EMBEDDINGS") or "none").strip().lower()
        if embeddings not in EMBEDDING_PROVIDERS:
            raise ValueError(f"EMBEDDINGS={embeddings!r}: {'|'.join(EMBEDDING_PROVIDERS)} 중 하나여야 한다")
        return cls(
            user_id=safe_id((env.get("USER_ID") or "default").strip(), "USER_ID"),
            data_dir=Path(env.get("DATA_DIR") or "./data").resolve(),
            embeddings=embeddings,
            voyage_api_key=env.get("VOYAGE_API_KEY") or None,
            openai_api_key=env.get("OPENAI_API_KEY") or None,
        )
