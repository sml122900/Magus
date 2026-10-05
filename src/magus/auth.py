"""원격 모드 인증. Magus는 OAuth 2.1 **리소스 서버**만 한다(자체 OAuth 서버 없음).

- 인증 서버(관리형 서비스)가 발급한 JWT 액세스 토큰을 검증한다: JWKS 서명, exp, iss, aud.
- `sub` → user_id는 허용 목록(`ALLOWED_USERS`)으로만 정한다. 목록에 없는 sub는 거부한다.
  - 토큰이 무효하면 401(SDK가 WWW-Authenticate와 resource_metadata를 붙인다).
  - 토큰은 유효한데 허용 목록에 없으면 403(`ForbiddenGate`). 401이면 클라이언트가 로그인을 되풀이한다.
- 인증 서버 위치는 Protected Resource Metadata(RFC 9728)로 알린다(SDK의 AuthSettings).

환경변수
- PUBLIC_URL: 바깥에서 보이는 서버 주소(예: https://magus.example.com). 리소스 = PUBLIC_URL + /mcp
- AUTH_ISSUER: 인증 서버 issuer(토큰의 iss와 정확히 같아야 한다)
- AUTH_JWKS_URL: 서명 키(JWKS) 주소. 없으면 issuer의 메타데이터(.well-known)에서 jwks_uri를 찾는다
- AUTH_AUDIENCE: 토큰 aud로 받아들일 값(쉼표로 여럿). 없으면 리소스 URL
- ALLOWED_USERS: "sub=user_id" 쉼표 목록(예: "user_01H…=default,user_01J…=father")
"""

from __future__ import annotations

import json
import logging
import time
import urllib.request
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import jwt
from mcp.server.auth.provider import AccessToken
from starlette.types import ASGIApp, Receive, Scope, Send

from magus.ids import safe_id

log = logging.getLogger("magus.auth")
ALGORITHMS = ["RS256", "RS384", "RS512", "ES256", "ES384", "PS256"]  # 비대칭만. none·HS*는 받지 않는다
LEEWAY = 30  # 초. 서버 시계 차이
USER_ID_CLAIM = "magus_user_id"


@dataclass(frozen=True)
class AuthConfig:
    public_url: str
    issuer: str
    audiences: tuple[str, ...]
    allowed: Mapping[str, str]  # sub → user_id
    jwks_url: str | None = None

    @property
    def resource(self) -> str:
        return self.public_url.rstrip("/") + "/mcp"

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> AuthConfig | None:
        issuer = (env.get("AUTH_ISSUER") or "").strip()
        if not issuer:
            return None
        public_url = (env.get("PUBLIC_URL") or "").strip()
        if not public_url:
            raise ValueError("AUTH_ISSUER를 쓰려면 PUBLIC_URL(바깥에서 보이는 서버 주소)이 필요하다")
        allowed = parse_allowed(env.get("ALLOWED_USERS") or "")
        if not allowed:
            # 비어 있으면 모두 거부한다(열리는 쪽이 아니다). 첫 로그인(403)으로 user id를 얻는 단계에 쓴다(docs/deploy.md).
            log.warning("ALLOWED_USERS가 비어 있다: 모든 사용자를 거부한다(403). 첫 로그인으로 id를 얻은 뒤 채운다")
        resource = public_url.rstrip("/") + "/mcp"
        audiences = tuple(a.strip() for a in (env.get("AUTH_AUDIENCE") or resource).split(",") if a.strip())
        return cls(public_url.rstrip("/"), issuer, audiences, allowed, (env.get("AUTH_JWKS_URL") or "").strip() or None)


def parse_allowed(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in (part.strip() for part in text.split(",")):
        if not item:
            continue
        sub, sep, user_id = item.rpartition("=")
        if not sep or not sub.strip():
            raise ValueError(f"ALLOWED_USERS 항목 {item!r}: 'sub=user_id' 형식이어야 한다")
        out[sub.strip()] = safe_id(user_id.strip(), "ALLOWED_USERS의 user_id")
    return out


class JwtVerifier:
    """SDK의 TokenVerifier. 검증 결과는 토큰별로 짧게 캐시한다(ForbiddenGate와 SDK 백엔드가 같은 토큰을 두 번 본다)."""

    def __init__(self, config: AuthConfig, jwks: Mapping[str, Any] | None = None):
        self.config = config
        self._static = jwt.PyJWKSet.from_dict(dict(jwks)) if jwks else None
        self._client: jwt.PyJWKClient | None = None
        self._cache: OrderedDict[str, tuple[float, dict[str, Any] | None, str]] = OrderedDict()

    def _jwks_client(self) -> jwt.PyJWKClient:
        if self._client is None:
            url = self.config.jwks_url or discover_jwks_url(self.config.issuer)
            self._client = jwt.PyJWKClient(url, cache_keys=True, lifespan=3600)
        return self._client

    def _key(self, token: str) -> Any:
        if self._static is not None:
            kid = jwt.get_unverified_header(token).get("kid")
            keys = [k for k in self._static.keys if kid is None or k.key_id == kid]
            if not keys:
                raise jwt.PyJWKClientError("알 수 없는 kid")
            return keys[0].key
        return self._jwks_client().get_signing_key_from_jwt(token).key

    def decode(self, token: str) -> dict[str, Any] | None:
        """서명·exp·iss·aud를 검증한 클레임. 실패하면 None."""
        return self.check(token)[0]

    def check(self, token: str) -> tuple[dict[str, Any] | None, str]:
        """(클레임, 실패 이유). 성공이면 이유는 "". 실패 이유(iss·aud 불일치, 만료, 서명 …)는 서버 로그에도 남긴다.
        토큰 값은 로그에 남기지 않는다. 설정을 맞추는 데 필요한 iss·aud·kid 같은 공개 값만 함께 적는다."""
        now = time.time()
        if (hit := self._cache.get(token)) and hit[0] > now:
            return hit[1], hit[2]
        reason = ""
        try:
            claims: dict[str, Any] | None = jwt.decode(
                token,
                self._key(token),
                algorithms=ALGORITHMS,
                audience=list(self.config.audiences),
                issuer=self.config.issuer,
                leeway=LEEWAY,
                options={"require": ["exp", "iss", "sub"]},
            )
        except (jwt.PyJWTError, ValueError) as e:
            claims, reason = None, explain(e, token, self.config)
            log.warning("auth=invalid reason=%s", reason)
        expires = min(now + 60, float(claims["exp"])) if claims else now + 10
        self._cache[token] = (expires, claims, reason)
        while len(self._cache) > 256:
            self._cache.popitem(last=False)
        return claims, reason

    def user_of(self, claims: Mapping[str, Any]) -> str | None:
        return self.config.allowed.get(str(claims.get("sub", "")))

    async def verify_token(self, token: str) -> AccessToken | None:
        claims = self.decode(token)
        if claims is None:
            return None
        user_id = self.user_of(claims)
        if user_id is None:
            return None  # ForbiddenGate가 먼저 403을 준다. 여기서는 인증 실패로 둔다
        aud = claims.get("aud")
        audiences = aud if isinstance(aud, list) else [aud]
        resource = self.config.resource if self.config.resource in audiences else None
        scopes = str(claims.get("scope") or claims.get("scp") or "").split()
        return AccessToken(
            token=token,
            client_id=str(claims.get("azp") or claims.get("client_id") or "-"),
            scopes=scopes,
            expires_at=int(claims["exp"]),
            resource=resource,
            subject=str(claims["sub"]),
            claims={"iss": claims.get("iss"), USER_ID_CLAIM: user_id},
        )


# 실패 원인 힌트. 위에서부터 첫 일치(하위 클래스가 먼저: InvalidSignatureError는 DecodeError의 하위다).
_REASONS: tuple[tuple[type[Exception], str], ...] = (
    (jwt.ExpiredSignatureError, "만료"),
    (jwt.ImmatureSignatureError, "아직 유효하지 않음(nbf·iat)"),
    (jwt.InvalidIssuerError, "iss 불일치"),
    (jwt.InvalidAudienceError, "aud 불일치"),
    (jwt.InvalidSignatureError, "서명"),
    (jwt.MissingRequiredClaimError, "필수 클레임 없음"),
    (jwt.InvalidAlgorithmError, "알고리즘"),
    (jwt.PyJWKClientError, "서명 키(kid) 없음 또는 JWKS를 못 읽음"),
    (jwt.DecodeError, "JWT 형식 아님"),
)


def explain(error: Exception, token: str, config: AuthConfig) -> str:
    """'aud 불일치 (토큰 aud=…, 기대=…)'. 토큰 자체나 서명은 넣지 않는다. 검증 전 값이라 설정 맞추기에만 쓴다."""
    hint = next((text for kind, text in _REASONS if isinstance(error, kind)), type(error).__name__)
    try:
        unverified = jwt.decode(token, options={"verify_signature": False})
        header = jwt.get_unverified_header(token)
    except (jwt.PyJWTError, ValueError):
        return hint
    short = lambda value: str(value)[:120]  # noqa: E731
    if hint == "iss 불일치":
        return f"{hint} (토큰 iss={short(unverified.get('iss'))}, 기대={config.issuer})"
    if hint == "aud 불일치":
        return f"{hint} (토큰 aud={short(unverified.get('aud'))}, 기대={', '.join(config.audiences)})"
    if hint == "만료":
        exp = unverified.get("exp")
        when = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(int(exp))) if isinstance(exp, int | float) else "?"
        return f"{hint} (exp={when})"
    if hint in ("서명", "서명 키(kid) 없음 또는 JWKS를 못 읽음", "알고리즘"):
        return f"{hint} (kid={short(header.get('kid'))}, alg={short(header.get('alg'))})"
    if hint == "필수 클레임 없음":
        return f"{hint} ({error})"
    return hint


def discover_jwks_url(issuer: str) -> str:
    """issuer의 메타데이터에서 jwks_uri를 찾는다(OAuth 서버 메타데이터, 그다음 OIDC)."""
    base = issuer.rstrip("/")
    for path in ("/.well-known/oauth-authorization-server", "/.well-known/openid-configuration"):
        try:
            with urllib.request.urlopen(base + path, timeout=10) as r:  # noqa: S310 - 설정한 issuer만 연다
                if uri := json.load(r).get("jwks_uri"):
                    return str(uri)
        except (OSError, ValueError):
            continue
    raise ValueError(f"{issuer}의 메타데이터에서 jwks_uri를 찾지 못했다. AUTH_JWKS_URL을 지정하라")


class ForbiddenGate:
    """토큰은 유효한데 허용 목록에 없는 사용자에게 403을 준다(SDK 인증 앞에서). 그 밖에는 그대로 넘긴다."""

    def __init__(self, app: ASGIApp, verifier: JwtVerifier, path: str = "/mcp"):
        self.app, self.verifier, self.path = app, verifier, path

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope.get("path", "").rstrip("/") == self.path:
            header = dict(scope.get("headers") or []).get(b"authorization", b"").decode("latin-1")
            if header.lower().startswith("bearer "):
                claims = self.verifier.decode(header[7:])
                if claims is not None and self.verifier.user_of(claims) is None:
                    log.warning("auth=forbidden sub_hash=%s", _hash(str(claims.get("sub", ""))))
                    body = json.dumps(
                        {"error": "forbidden", "error_description": "허용 목록에 없는 사용자입니다. 운영자에게 문의하세요."},
                        ensure_ascii=False,
                    ).encode()
                    await send({"type": "http.response.start", "status": 403,
                                "headers": [(b"content-type", b"application/json; charset=utf-8"),
                                            (b"content-length", str(len(body)).encode())]})
                    await send({"type": "http.response.body", "body": body})
                    return
        await self.app(scope, receive, send)


def _hash(text: str) -> str:
    """로그에 sub를 그대로 남기지 않는다(허용 목록에 넣을 때는 운영자가 인증 서비스 화면에서 확인한다)."""
    import hashlib

    return hashlib.sha256(text.encode()).hexdigest()[:10]
