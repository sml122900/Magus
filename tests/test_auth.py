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
import shutil
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
TRIP_AI = "https://trip-ai.lifebookapplication.com/mcp"  # 같은 WorkOS 환경을 쓰는 자매 서비스(결정 #79)


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
    # aud는 이 서버 하나여야 한다(결정 #79). 같은 WorkOS 환경을 쓰는 자매 서비스(trip_ai)의 토큰, 여러 서비스용 토큰은 거부
    assert await v.verify_token(_token(good, aud=TRIP_AI)) is None
    assert await v.verify_token(_token(good, aud=["http://magus.test/mcp", TRIP_AI])) is None
    assert await v.verify_token(_token(good, aud=[TRIP_AI, "http://magus.test/mcp"])) is None
    assert await v.verify_token(_token(good, aud=["http://magus.test/mcp", "http://magus.test/mcp"])) is None
    assert await v.verify_token(_token(good, aud=None)) is None  # aud 없음
    single = await v.verify_token(_token(good, aud=["http://magus.test/mcp"]))  # 원소 하나인 목록은 받는다
    assert single is not None and single.resource == "http://magus.test/mcp"
    # 실패 이유(서버 로그·웹 401용). 토큰 값은 넣지 않고, 설정을 맞추는 데 필요한 공개 값만 적는다
    reasons = {
        "aud": v.check(_token(good, aud="https://other.example/mcp"))[1],
        "iss": v.check(_token(good, iss="https://evil.test"))[1],
        "exp": v.check(_token(good, exp_in=-120))[1],
        "sig": v.check(_token(evil))[1],
        "kid": v.check(_token(good, kid="nope"))[1],
        "fmt": v.check("not-a-jwt")[1],
    }
    assert reasons["aud"] == 'aud 불일치 (토큰 aud=문자열 "https://other.example/mcp", 기대=http://magus.test/mcp)'
    # 거부할 때 받은 aud의 모양(문자열/목록, 값)을 남긴다. 토큰 자체와 sub는 남기지 않는다
    mixed = v.check(_token(good, aud=["http://magus.test/mcp", TRIP_AI], sub="sub-mixed"))[1]
    assert mixed == f'aud 불일치 (토큰 aud=목록 2개 ["http://magus.test/mcp", "{TRIP_AI}"], 기대=http://magus.test/mcp)'
    assert v.check(_token(good, aud=None))[1] == '필수 클레임 없음 (Token is missing the "aud" claim)'
    injected = v.check(_token(good, aud="x\nauth=ok"))[1]  # 검증 전 값이라 줄바꿈이 로그 줄을 가르지 못하게 한다
    assert "\n" not in injected and 'aud=문자열 "x\\nauth=ok"' in injected
    assert reasons["iss"] == f"iss 불일치 (토큰 iss=https://evil.test, 기대={ISSUER})"
    assert reasons["exp"].startswith("만료 (exp=") and reasons["sig"] == "서명 (kid=k1, alg=RS256)"
    assert reasons["kid"].startswith("서명 키(kid) 없음") and reasons["fmt"] == "JWT 형식 아님"
    claims, reason = v.check(_token(good))
    assert reason == "" and claims["sub"] == "sub-alice"


def test_config_requires_allow_list_and_public_url():
    assert AuthConfig.from_env({}) is None  # 인증 없음 = 로컬 모드
    with pytest.raises(ValueError, match="PUBLIC_URL"):
        AuthConfig.from_env({"AUTH_ISSUER": ISSUER, "ALLOWED_USERS": ALLOWED})
    # 빈 허용 목록은 "아무도 못 들어옴"이다(첫 로그인으로 id를 얻는 단계). 열리는 쪽이 아니다
    empty = AuthConfig.from_env({"AUTH_ISSUER": ISSUER, "PUBLIC_URL": "https://m.example"})
    assert empty is not None and dict(empty.allowed) == {}
    assert parse_allowed(" a=default , user_01H=father ") == {"a": "default", "user_01H": "father"}
    with pytest.raises(ValueError):
        parse_allowed("a=../etc")
    base = {"AUTH_ISSUER": ISSUER, "PUBLIC_URL": "https://m.example/", "ALLOWED_USERS": "a=b"}
    assert AuthConfig.from_env(base).resource == "https://m.example/mcp"
    assert AuthConfig.from_env({**base, "AUTH_AUDIENCE": " https://m.example/mcp "}).resource == "https://m.example/mcp"
    # 받는 aud를 넓히거나 바꾸는 설정은 없다(결정 #79). PUBLIC_URL/mcp와 다르면 시작하지 않는다
    for wrong in ("https://m.example/mcp, client_123", "client_123", "https://m.example/mcp/", TRIP_AI):
        with pytest.raises(ValueError, match=r"AUTH_AUDIENCE=.*PUBLIC_URL/mcp\(https://m\.example/mcp\)와 달라 시작하지 않습니다"):
            AuthConfig.from_env({**base, "AUTH_AUDIENCE": wrong})


def test_server_refuses_to_start_with_other_audience(data_dir: Path):
    """AUTH_AUDIENCE가 PUBLIC_URL/mcp와 다르면 서버가 뜨지 않고, 이유를 한국어로 남긴다(stderr = docker compose logs)."""
    env = {**os.environ, "DATA_DIR": str(data_dir), "EMBEDDINGS": "none", "PYTHONIOENCODING": "utf-8",
           "PUBLIC_URL": "http://127.0.0.1:9", "AUTH_ISSUER": ISSUER, "ALLOWED_USERS": ALLOWED,
           "SESSION_SECRET": "s" * 40, "AUTH_AUDIENCE": f"http://127.0.0.1:9/mcp,{TRIP_AI}"}
    done = subprocess.run([sys.executable, "-m", "magus", "serve", "--transport", "http", "--port", str(_free_port())],
                          env=env, capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert done.returncode == 2
    assert "설정 오류로 시작하지 않습니다: AUTH_AUDIENCE=" in done.stderr and "PUBLIC_URL/mcp(http://127.0.0.1:9/mcp)" in done.stderr
    assert "streamable-http" not in done.stderr  # 듣기 전에 멈췄다


def test_allow_list_refuses_duplicate_sub_or_name(data_dir: Path):
    """같은 sub가 두 번이면 뒤의 것이 조용히 이기고, 같은 이름이 두 번이면 두 계정이 한 공간을 쓴다. 둘 다 시작하지 않는다.
    이유는 한국어로 남기되 sub(사용자 id)는 쓰지 않는다. 지금 서버 모양(서로 다른 sub 둘, default·father)은 통과한다."""
    assert parse_allowed("user_01AAA=default,user_01BBB=father") == {"user_01AAA": "default", "user_01BBB": "father"}
    for text, why in (("user_01AAA=default, user_01BBB=father, user_01AAA=father2", "1번째와 3번째 항목이 같은 sub"),
                      ("user_01AAA=default,user_01BBB=default", "1번째와 2번째 항목이 같은 이름"),
                      (" user_01AAA = default ,user_01AAA=default", "같은 sub")):
        with pytest.raises(ValueError, match=why) as caught:
            parse_allowed(text)
        assert "user_01" not in str(caught.value)
    with pytest.raises(ValueError, match="2번째 항목: 'sub=user_id' 형식") as caught:
        parse_allowed("user_01AAA=default,user_01CCC")
    assert "user_01" not in str(caught.value)
    env = {**os.environ, "DATA_DIR": str(data_dir), "EMBEDDINGS": "none", "PYTHONIOENCODING": "utf-8",
           "PUBLIC_URL": "http://127.0.0.1:9", "AUTH_ISSUER": ISSUER, "ALLOWED_USERS": "user_01AAA=default,user_01BBB=default",
           "SESSION_SECRET": "s" * 40}
    done = subprocess.run([sys.executable, "-m", "magus", "serve", "--transport", "http", "--port", str(_free_port())],
                          env=env, capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert done.returncode == 2 and "설정 오류로 시작하지 않습니다: ALLOWED_USERS의 1번째와 2번째 항목이 같은 이름" in done.stderr
    assert "user_01" not in done.stderr and "streamable-http" not in done.stderr


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
           "PUBLIC_URL": base, "AUTH_ISSUER": ISSUER, "AUTH_JWKS_URL": jwks_url, "ALLOWED_USERS": ALLOWED,
           "SESSION_SECRET": "s" * 40}
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


async def test_remote_auth_rejects_and_isolates_users(keys, auth_server, data_dir: Path):
    good, evil, _ = keys
    base, log_path = auth_server
    mcp_url, aud = f"{base}/mcp", f"{base}/mcp"

    # 인증 서버 위치를 알리는 Protected Resource Metadata(RFC 9728). resource는 커넥터 URL과 정확히 같다
    with urllib.request.urlopen(f"{base}/.well-known/oauth-protected-resource/mcp", timeout=10) as r:
        prm = json.load(r)
    assert prm["resource"] == mcp_url and prm["authorization_servers"][0].rstrip("/") == ISSUER

    status, headers, _ = _post(mcp_url)  # 토큰 없음
    assert status == 401 and "resource_metadata=" in headers.get("www-authenticate", "")
    for bad in (_token(good, aud=aud, exp_in=-120), _token(good, aud="https://other/mcp"), _token(evil, aud=aud),
                _token(good, aud=TRIP_AI), _token(good, aud=[aud, TRIP_AI])):  # 자매 서비스용, 여러 서비스용(결정 #79)
        status, headers, _ = _post(mcp_url, bad)
        assert status == 401 and "resource_metadata=" in headers.get("www-authenticate", "")
    for good_aud in (aud, [aud]):  # 문자열, 원소 하나인 목록
        status, _, body = _post(mcp_url, _token(good, aud=good_aud))
        assert status == 200 and "book_outline" in body
    status, _, body = _post(mcp_url, _token(good, aud=aud, sub="sub-carol"))  # 유효하지만 허용 목록 밖
    assert status == 403 and "허용 목록" in json.loads(body)["error_description"]

    alice, bob = _token(good, aud=aud), _token(good, aud=aud, sub="sub-bob")
    inbox = data_dir / "users" / "alice" / "inbox"
    inbox.mkdir(parents=True)
    shutil.copy(FIXTURES / "닿으려는_종_합성.docx", inbox / "원고.docx")
    async with _client(mcp_url, alice) as c:
        assert "원고.docx" in _text(await c.call_tool("files_list", {}))
        _text(await c.call_tool("book_import", {"path": "원고.docx", "project_id": "synth"}))
        assert _text(await c.call_tool("book_outline", {})).startswith("프로젝트: 닿으려는 종 (합성) (synth)")
        _text(await c.call_tool("idea_add", {"text": "앨리스의 생각", "kind": "thought", "untitled": True}))
    async with _client(mcp_url, bob) as c:  # 다른 계정: 앨리스의 원고·생각이 보이지 않는다
        assert _text(await c.call_tool("book_outline", {})).startswith("프로젝트가 없습니다")
        assert "받은함이 비어 있다" in _text(await c.call_tool("files_list", {}))  # 받은함도 사용자별
        assert (await c.call_tool("book_import", {"path": "원고.docx", "project_id": "x"})).is_error
        assert _text(await c.call_tool("idea_search", {"query": "앨리스의 생각"})).endswith("결과 없음")
        assert (await c.call_tool("book_read_chapter", {"number": 1, "project_id": "synth"})).is_error

    time.sleep(0.3)
    log = log_path.read_text(encoding="utf-8")
    assert "tool=book_import user=alice" in log and "tool=book_outline user=bob" in log
    assert "auth=forbidden sub_hash=" in log and "sub-carol" not in log  # sub는 해시로만
    assert f'aud 불일치 (토큰 aud=문자열 "{TRIP_AI}", 기대={aud})' in log
    assert f'aud 불일치 (토큰 aud=목록 2개 ["{aud}", "{TRIP_AI}"], 기대={aud})' in log
    assert "앨리스의 생각" not in log
