"""P1 2단계: 원격 모드 인증. Magus는 리소스 서버만 한다.

- 토큰 검증: JWKS 서명, exp, iss, aud(RFC 8707). none·HS* 알고리즘은 받지 않는다.
- sub → user_id는 허용 목록으로만. 목록 밖은 403, 무효한 토큰은 401(+ resource_metadata).
- 격리: 다른 계정의 토큰으로는 그 사용자 데이터만 보인다.
외부 인증 서버 없이, 로컬 RSA 키와 로컬 HTTP JWKS로 시험한다.
"""

from __future__ import annotations

import http.server
import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import httpx2
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from magus.auth import USER_ID_CLAIM, AuthConfig, JwtVerifier, parse_allowed

from test_http import FIXTURES, _free_port, _wait_healthy  # tests/는 패키지가 아니라 rootdir 모드로 불러온다

pytestmark = pytest.mark.anyio
ISSUER = "https://issuer.test"
ALLOWED = "sub-alice=alice,sub-bob=bob"


@pytest.fixture(scope="module")
def keys():
    good = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    evil = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(good.public_key()))
    return good, evil, {"keys": [{**jwk, "kid": "k1", "use": "sig", "alg": "RS256"}]}


def _token(key, sub="sub-alice", aud="http://magus.test/mcp", iss=ISSUER, exp_in=600, alg="RS256", kid="k1") -> str:
    now = int(time.time())
    claims = {"sub": sub, "aud": aud, "iss": iss, "iat": now, "exp": now + exp_in, "scope": "openid", "azp": "claude"}
    return jwt.encode(claims, key, algorithm=alg, headers={"kid": kid})


def _config(public_url="http://magus.test") -> AuthConfig:
    config = AuthConfig.from_env({"AUTH_ISSUER": ISSUER, "PUBLIC_URL": public_url, "ALLOWED_USERS": ALLOWED})
    assert config is not None
    return config


async def test_verifier_accepts_only_valid_allowed_tokens(keys):
    good, evil, jwks = keys
    v = JwtVerifier(_config(), jwks)
    ok = await v.verify_token(_token(good))
    assert ok is not None and ok.subject == "sub-alice" and ok.claims[USER_ID_CLAIM] == "alice"
    assert ok.resource == "http://magus.test/mcp" and ok.client_id == "claude"
    assert await v.verify_token(_token(good, exp_in=-120)) is None  # 만료(leeway 30초 넘음)
    assert await v.verify_token(_token(good, iss="https://evil.test")) is None  # 다른 발급자
    assert await v.verify_token(_token(good, aud="https://other.example/mcp")) is None  # 다른 서버용 토큰
    assert await v.verify_token(_token(evil)) is None  # 서명 키가 다름
    assert await v.verify_token(_token(good, kid="nope")) is None  # 모르는 키
    assert await v.verify_token(_token(good, sub="sub-carol")) is None  # 허용 목록 밖
    assert await v.verify_token(jwt.encode({"sub": "sub-alice", "aud": "http://magus.test/mcp", "iss": ISSUER,
                                            "exp": int(time.time()) + 600}, "s" * 32, algorithm="HS256")) is None  # 대칭키 위조
    assert await v.verify_token("not-a-jwt") is None


def test_config_requires_allow_list_and_public_url():
    assert AuthConfig.from_env({}) is None  # 인증 없음 = 로컬 모드
    with pytest.raises(ValueError, match="PUBLIC_URL"):
        AuthConfig.from_env({"AUTH_ISSUER": ISSUER, "ALLOWED_USERS": ALLOWED})
    with pytest.raises(ValueError, match="ALLOWED_USERS"):
        AuthConfig.from_env({"AUTH_ISSUER": ISSUER, "PUBLIC_URL": "https://m.example"})
    assert parse_allowed(" a=default , user_01H=father ") == {"a": "default", "user_01H": "father"}
    with pytest.raises(ValueError):
        parse_allowed("a=../etc")
    config = AuthConfig.from_env({"AUTH_ISSUER": ISSUER, "PUBLIC_URL": "https://m.example/", "ALLOWED_USERS": "a=b",
                                  "AUTH_AUDIENCE": "https://m.example/mcp, client_123"})
    assert config.resource == "https://m.example/mcp" and config.audiences == ("https://m.example/mcp", "client_123")


@pytest.fixture
def jwks_url(keys):
    """인증 서버의 JWKS 엔드포인트 흉내(로컬 HTTP). PyJWKClient는 http(s)만 받는다."""
    body = json.dumps(keys[2]).encode()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    httpd = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_port}/oauth2/jwks"
    httpd.shutdown()


@pytest.fixture
def auth_server(jwks_url, data_dir: Path, tmp_path: Path):
    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    log_path = tmp_path / "server.log"
    env = {**os.environ, "DATA_DIR": str(data_dir), "EMBEDDINGS": "none", "PYTHONIOENCODING": "utf-8",
           "PUBLIC_URL": base, "AUTH_ISSUER": ISSUER, "AUTH_JWKS_URL": jwks_url, "ALLOWED_USERS": ALLOWED}
    env.pop("USER_ID", None)
    with log_path.open("w", encoding="utf-8") as log:
        proc = subprocess.Popen([sys.executable, "-m", "magus", "serve", "--transport", "http", "--port", str(port)],
                                env=env, stdout=log, stderr=subprocess.STDOUT)
        try:
            _wait_healthy(f"{base}/healthz", proc)
            yield base, log_path
        finally:
            proc.terminate()
            proc.wait(timeout=10)


def _post(url: str, token: str | None = None) -> tuple[int, dict[str, str], str]:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}).encode()
    headers = {"content-type": "application/json", "accept": "application/json, text/event-stream"}
    if token:
        headers["authorization"] = f"Bearer {token}"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, body, headers), timeout=10) as r:
            return r.status, dict(r.headers), r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read().decode()


def _client(url: str, token: str) -> Client:
    return Client(streamable_http_client(url, http_client=httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}"})))


def _text(result) -> str:
    assert not result.is_error, result.content[0].text if result.content else result
    return "".join(block.text for block in result.content)


async def test_remote_auth_rejects_and_isolates_users(keys, auth_server):
    good, evil, _ = keys
    base, log_path = auth_server
    mcp_url, aud = f"{base}/mcp", f"{base}/mcp"

    # 인증 서버 위치를 알리는 Protected Resource Metadata(RFC 9728). resource는 커넥터 URL과 정확히 같다
    with urllib.request.urlopen(f"{base}/.well-known/oauth-protected-resource/mcp", timeout=10) as r:
        prm = json.load(r)
    assert prm["resource"] == mcp_url and prm["authorization_servers"][0].rstrip("/") == ISSUER

    status, headers, _ = _post(mcp_url)  # 토큰 없음
    assert status == 401 and "resource_metadata=" in headers.get("www-authenticate", "")
    for bad in (_token(good, aud=aud, exp_in=-120), _token(good, aud="https://other/mcp"), _token(evil, aud=aud)):
        assert _post(mcp_url, bad)[0] == 401
    status, _, body = _post(mcp_url, _token(good, aud=aud, sub="sub-carol"))  # 유효하지만 허용 목록 밖
    assert status == 403 and "허용 목록" in json.loads(body)["error_description"]

    alice, bob = _token(good, aud=aud), _token(good, aud=aud, sub="sub-bob")
    async with _client(mcp_url, alice) as c:
        _text(await c.call_tool("book_import", {"path": str(FIXTURES / "닿으려는_종_합성.docx"), "project_id": "synth"}))
        assert _text(await c.call_tool("book_outline", {})).startswith("프로젝트: 닿으려는 종 (합성) (synth)")
        _text(await c.call_tool("idea_add", {"text": "앨리스의 생각", "kind": "thought"}))
    async with _client(mcp_url, bob) as c:  # 다른 계정: 앨리스의 원고·생각이 보이지 않는다
        assert _text(await c.call_tool("book_outline", {})).startswith("프로젝트가 없습니다")
        assert _text(await c.call_tool("idea_search", {"query": "앨리스의 생각"})).endswith("결과 없음")
        assert (await c.call_tool("book_read_chapter", {"number": 1, "project_id": "synth"})).is_error

    time.sleep(0.3)
    log = log_path.read_text(encoding="utf-8")
    assert "tool=book_import user=alice" in log and "tool=book_outline user=bob" in log
    assert "auth=forbidden sub_hash=" in log and "sub-carol" not in log  # sub는 해시로만
    assert "앨리스의 생각" not in log
