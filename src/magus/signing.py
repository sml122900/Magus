"""서명한 짧은 토큰(세션 쿠키, 다운로드 링크, OAuth state). 비밀은 SESSION_SECRET(환경변수)이다.

형식: base64url(JSON) "." base64url(HMAC-SHA256). 모든 토큰에 만료(exp, 초)가 있다. 용도(purpose)를 서명에 넣어
세션 토큰을 다운로드 토큰으로 바꿔 쓰지 못하게 한다.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def sign(payload: dict[str, Any], secret: bytes, purpose: str, ttl: int) -> str:
    body = _b64(json.dumps({**payload, "exp": int(time.time()) + ttl, "pur": purpose}, separators=(",", ":")).encode())
    mac = hmac.new(secret, f"{purpose}.{body}".encode(), hashlib.sha256).digest()
    return f"{body}.{_b64(mac)}"


def unsign(token: str, secret: bytes, purpose: str) -> dict[str, Any] | None:
    """서명이 맞고, 용도가 같고, 만료 전이면 payload. 아니면 None."""
    try:
        body, mac = token.split(".", 1)
        expected = hmac.new(secret, f"{purpose}.{body}".encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _unb64(mac)):
            return None
        payload = json.loads(_unb64(body))
    except (ValueError, TypeError):
        return None
    if payload.get("pur") != purpose or int(payload.get("exp", 0)) < time.time():
        return None
    return payload
