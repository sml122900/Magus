"""원격 모드 인증. Magus는 OAuth 2.1 **리소스 서버**만 한다(자체 OAuth 서버 없음).

- 인증 서버(관리형 서비스)가 발급한 JWT 액세스 토큰을 검증한다: JWKS 서명, exp, iss, aud.
  - aud는 이 서버의 리소스(PUBLIC_URL + /mcp) **하나**여야 한다. 문자열이면 그 값, 목록이면 그 값 하나뿐일 때만 받는다.
    같은 인증 환경(WorkOS)을 쓰는 다른 서비스(trip_ai)의 토큰이나, 여러 서비스용 토큰을 막기 위해서다(결정 #79).
- `sub` → user_id는 허용 목록(`ALLOWED_USERS`)으로만 정한다. 목록에 없는 sub는 거부한다.
  - 토큰이 무효하면 401(SDK가 WWW-Authenticate와 resource_metadata를 붙인다).
  - 토큰은 유효한데 허용 목록에 없으면 403(`ForbiddenGate`). 401이면 클라이언트가 로그인을 되풀이한다.
- 인증 서버 위치는 Protected Resource Metadata(RFC 9728)로 알린다(SDK의 AuthSettings).

환경변수
- PUBLIC_URL: 바깥에서 보이는 서버 주소(예: https://magus.example.com). 리소스 = PUBLIC_URL + /mcp
- AUTH_ISSUER: 인증 서버 issuer(토큰의 iss와 정확히 같아야 한다)
- AUTH_JWKS_URL: 서명 키(JWKS) 주소. 없으면 issuer의 메타데이터(.well-known)에서 jwks_uri를 찾는다
- AUTH_AUDIENCE: 비워 둔다(= 리소스 URL). 값이 있는데 리소스 URL과 한 글자라도 다르면 시작하지 않는다
- ALLOWED_USERS: "sub=user_id" 쉼표 목록(예: "user_01H…=default,user_01J…=father")
"""

from __future__ import annotations

import json
import logging
import threading
import time
import urllib.request
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import anyio
import jwt
from mcp.server.auth.provider import AccessToken
from starlette.types import ASGIApp, Receive, Scope, Send

from magus.ids import safe_id

log = logging.getLogger("magus.auth")
ALGORITHMS = ["RS256", "RS384", "RS512", "ES256", "ES384", "PS256"]  # 비대칭만. none·HS*는 받지 않는다
JWKS_LIFESPAN = 300  # 초. JWK 묶음을 이만큼 두고 다시 읽는다
JWKS_TIMEOUT = 5  # 초
LEEWAY = 30  # 초. 서버 시계 차이
USER_ID_CLAIM = "magus_user_id"


@dataclass(frozen=True)
class AuthConfig:
    public_url: str
    issuer: str
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
        config = cls(public_url.rstrip("/"), issuer, allowed, (env.get("AUTH_JWKS_URL") or "").strip() or None)
        audience = (env.get("AUTH_AUDIENCE") or "").strip()
        if audience and audience != config.resource:
            # 받는 aud를 넓히는 설정은 없다(결정 #79, #51 대체). 잘못 넣은 값으로 조용히 열리지 않게 시작을 막는다
            raise ValueError(
                f"AUTH_AUDIENCE={audience!r}가 PUBLIC_URL/mcp({config.resource})와 달라 시작하지 않습니다. "
                "토큰 aud는 이 서버 주소 하나만 받습니다. AUTH_AUDIENCE를 지우거나 PUBLIC_URL/mcp와 똑같이 쓰세요. "
                "로그인이 401이면 WorkOS에 등록한 리소스 주소가 PUBLIC_URL/mcp와 글자까지 같은지 확인하세요"
            )
        return config


def parse_allowed(text: str) -> dict[str, str]:
    """`sub=user_id` 쉼표 목록. 같은 sub가 두 번(뒤의 것이 조용히 이긴다)이거나 같은 이름이 두 번(두 계정이 한 공간을 쓴다)이면
    시작하지 않는다. 오류에는 항목 순서만 쓰고 sub(사용자 id)는 쓰지 않는다(로그에 남는다)."""
    out: dict[str, str] = {}
    seen_sub: dict[str, int] = {}
    seen_name: dict[str, int] = {}
    items = [part.strip() for part in text.split(",")]
    for n, item in enumerate((i for i in items if i), 1):
        sub, sep, user_id = item.rpartition("=")
        sub = sub.strip()
        if not sep or not sub:
            raise ValueError(f"ALLOWED_USERS의 {n}번째 항목: 'sub=user_id' 형식이어야 합니다")
        name = safe_id(user_id.strip(), "ALLOWED_USERS의 user_id")
        if sub in seen_sub:
            raise ValueError(f"ALLOWED_USERS의 {seen_sub[sub]}번째와 {n}번째 항목이 같은 sub입니다. "
                             "한 계정은 한 번만 적으세요(두 번이면 어느 공간으로 들어갈지가 순서로 정해집니다)")
        if name in seen_name:
            raise ValueError(f"ALLOWED_USERS의 {seen_name[name]}번째와 {n}번째 항목이 같은 이름(user_id)입니다. "
                             "두 계정이 한 공간을 쓰게 되므로 시작하지 않습니다. 이름을 서로 다르게 적으세요")
        seen_sub[sub], seen_name[name] = n, n
        out[sub] = name
    return out


class JwtVerifier:
    """SDK의 TokenVerifier. 검증 결과는 토큰별로 짧게 캐시한다(ForbiddenGate와 SDK 백엔드가 같은 토큰을 두 번 본다)."""

    def __init__(self, config: AuthConfig, jwks: Mapping[str, Any] | None = None):
        self.config = config
        self._static = jwt.PyJWKSet.from_dict(dict(jwks)) if jwks else None
        self._client: jwt.PyJWKClient | None = None
        self._cache: OrderedDict[str, tuple[float, dict[str, Any] | None, str]] = OrderedDict()
        self._lock = threading.Lock()  # 검증은 워커 스레드에서도 돈다(점검 1-10)

    def _jwks_client(self) -> jwt.PyJWKClient:
        if self._client is None:
            url = self.config.jwks_url or discover_jwks_url(self.config.issuer)
            # 키 하나하나는 캐시하지 않고 JWK 묶음만 5분(점검 1-8): 인증 서버가 키를 빼면 늦어도 5분 뒤 그 키 토큰을 받지 않는다
            # (cache_keys=True는 만료 없는 lru_cache라 뺀 키를 계속 믿었다). JWKS가 늦어도 5초에서 끊는다(기본 30초)
            self._client = jwt.PyJWKClient(url, cache_keys=False, lifespan=JWKS_LIFESPAN, timeout=JWKS_TIMEOUT)
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
        with self._lock:
            hit = self._cache.get(token)
        if hit and hit[0] > now:
            return hit[1], hit[2]
        reason = ""
        try:
            claims: dict[str, Any] | None = jwt.decode(
                token,
                self._key(token),
                algorithms=ALGORITHMS,
                audience=self.config.resource,
                issuer=self.config.issuer,
                leeway=LEEWAY,
                options={"require": ["exp", "iss", "sub", "aud"]},
            )
            # PyJWT는 aud 목록에 우리 주소가 하나라도 있으면 통과시킨다. 다른 서비스 주소가 섞인 토큰도 막는다
            if not only_audience(claims["aud"], self.config.resource):
                raise jwt.InvalidAudienceError("aud에 이 서버 말고 다른 값이 있다")
        except (jwt.PyJWTError, ValueError) as e:
            claims, reason = None, explain(e, token, self.config)
            log.warning("auth=invalid reason=%s", reason)
        expires = min(now + 60, float(claims["exp"])) if claims else now + 10
        with self._lock:
            self._cache[token] = (expires, claims, reason)
            while len(self._cache) > 256:
                self._cache.popitem(last=False)
        return claims, reason

    def id_token_claims(self, token: str, client_id: str) -> dict[str, Any] | None:
        """웹 로그인 응답의 OIDC id_token: 서명(같은 JWKS)·iss·aud(웹 클라이언트 id)·exp를 검증한 claim. 아니면 None.
        액세스 토큰이 아니므로 사용자 확인에는 쓰지 않고, 메일을 읽는 데만 쓴다(WorkOS 문서: id_token에 email, aud = client id)."""
        try:
            return jwt.decode(token, self._key(token), algorithms=ALGORITHMS, audience=client_id, issuer=self.config.issuer,
                              options={"require": ["exp", "iss", "aud", "sub"]})
        except (jwt.PyJWTError, ValueError):
            return None

    def user_of(self, claims: Mapping[str, Any]) -> str | None:
        return self.config.allowed.get(str(claims.get("sub", "")))

    async def verify_token(self, token: str) -> AccessToken | None:
        # JWKS를 읽는 동기 호출(urllib)이 이벤트 루프를 막지 않게 워커 스레드에서(점검 1-10: JWKS가 5초 늦으면 /healthz도 4.5초)
        claims = await anyio.to_thread.run_sync(self.decode, token)
        if claims is None:
            return None
        user_id = self.user_of(claims)
        if user_id is None:
            return None  # ForbiddenGate가 먼저 403을 준다. 여기서는 인증 실패로 둔다
        scopes = str(claims.get("scope") or claims.get("scp") or "").split()
        return AccessToken(
            token=token,
            client_id=str(claims.get("azp") or claims.get("client_id") or "-"),
            scopes=scopes,
            expires_at=int(claims["exp"]),
            resource=self.config.resource,  # check가 aud = 이 리소스 하나임을 확인했다
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
        return f"{hint} (토큰 aud={describe_audience(unverified.get('aud'))}, 기대={config.resource})"
    if hint == "만료":
        exp = unverified.get("exp")
        when = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(int(exp))) if isinstance(exp, int | float) else "?"
        return f"{hint} (exp={when})"
    if hint in ("서명", "서명 키(kid) 없음 또는 JWKS를 못 읽음", "알고리즘"):
        return f"{hint} (kid={short(header.get('kid'))}, alg={short(header.get('alg'))})"
    if hint == "필수 클레임 없음":
        return f"{hint} ({error})"
    return hint


def only_audience(aud: Any, resource: str) -> bool:
    """aud가 resource 하나뿐인가: 문자열이면 같은 값, 목록이면 원소가 그 값 하나."""
    return aud == resource or aud == [resource]


def describe_audience(aud: Any) -> str:
    """로그용 aud 모양: '문자열 "…"', '목록 2개 ["…", "…"]'. aud는 비밀이 아니다(토큰 자체·sub는 남기지 않는다).
    값은 검증 전 입력이라 JSON 문자열로 적어 줄바꿈 같은 제어 문자가 로그 줄을 가르지 못하게 한다."""
    quote = lambda value: json.dumps(str(value)[:120], ensure_ascii=False)  # noqa: E731
    if aud is None:
        return "없음"
    if isinstance(aud, str):
        return f"문자열 {quote(aud)}"
    if isinstance(aud, list):
        shown = ", ".join(quote(item) for item in aud[:5])
        more = f" 외 {len(aud) - 5}개" if len(aud) > 5 else ""
        return f"목록 {len(aud)}개 [{shown}]{more}"
    return f"{type(aud).__name__} {quote(aud)}"


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
                claims = await anyio.to_thread.run_sync(self.verifier.decode, header[7:])  # 이벤트 루프를 막지 않게(점검 1-10)
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
