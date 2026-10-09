"""임베딩 제공자. 서버가 쓰는 외부 API는 이것뿐이다.

EMBEDDINGS=none(기본)이면 제공자가 없고 모든 검색이 FTS만으로 동작한다.
voyage / openai는 표준 라이브러리 HTTP로 부른다(SDK 의존성 없음). 모델은 EMBEDDINGS_MODEL로 바꾼다.
키가 없으면 경고를 남기고 FTS로 동작한다. 호출이 실패해도 검색은 키워드 결과로 계속된다(search.find_chunks가 처리).
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request
from collections.abc import Callable
from typing import Any

from magus.config import Settings

log = logging.getLogger("magus.embeddings")

Post = Callable[[str, dict[str, str], dict[str, Any]], dict[str, Any]]


def _http_post(url: str, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 (고정된 https 엔드포인트)
        return json.loads(response.read())


class VoyageEmbedder:
    url = "https://api.voyageai.com/v1/embeddings"

    def __init__(self, api_key: str, model: str = "voyage-3.5", post: Post = _http_post):
        self.api_key, self.model, self.post = api_key, model, post

    def embed(self, texts: list[str]) -> list[list[float]]:
        data = self.post(
            self.url,
            {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            {"input": texts, "model": self.model},
        )
        return [row["embedding"] for row in sorted(data["data"], key=lambda r: r["index"])]


class OpenAIEmbedder:
    url = "https://api.openai.com/v1/embeddings"

    def __init__(self, api_key: str, model: str = "text-embedding-3-small", post: Post = _http_post):
        self.api_key, self.model, self.post = api_key, model, post

    def embed(self, texts: list[str]) -> list[list[float]]:
        data = self.post(
            self.url,
            {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            {"input": texts, "model": self.model},
        )
        return [row["embedding"] for row in sorted(data["data"], key=lambda r: r["index"])]


def get_embedder(settings: Settings, model: str | None = None) -> VoyageEmbedder | OpenAIEmbedder | None:
    model = model or os.environ.get("EMBEDDINGS_MODEL") or None
    if settings.embeddings == "voyage":
        if not settings.voyage_api_key:
            log.warning("EMBEDDINGS=voyage인데 VOYAGE_API_KEY가 없다. FTS만으로 동작한다.")
            return None
        return VoyageEmbedder(settings.voyage_api_key, **({"model": model} if model else {}))
    if settings.embeddings == "openai":
        if not settings.openai_api_key:
            log.warning("EMBEDDINGS=openai인데 OPENAI_API_KEY가 없다. FTS만으로 동작한다.")
            return None
        return OpenAIEmbedder(settings.openai_api_key, **({"model": model} if model else {}))
    return None
