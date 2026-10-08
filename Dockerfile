# Magus 원격 서버 이미지(P1). 데이터는 /data(볼륨)에 두고, 컨테이너는 비root로 돈다.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8 PYTHONDONTWRITEBYTECODE=1 \
    DATA_DIR=/data PORT=8000 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

RUN pip install --no-cache-dir "uv>=0.12.22,<0.13" \
 && useradd --system --uid 10001 --home-dir /app magus \
 && mkdir -p /data && chown magus /data

WORKDIR /app
# 의존성 먼저(코드가 바뀌어도 이 층은 캐시된다)
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
# 웹 도움말(#97)의 시스템 프롬프트. magus.helpbot이 /app/docs/help를 읽는다
COPY docs/help ./docs/help
RUN uv sync --frozen --no-dev

USER magus
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s \
  CMD ["/app/.venv/bin/python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3)"]
# 원격 모드: AUTH_ISSUER·PUBLIC_URL·ALLOWED_USERS·SESSION_SECRET이 있어야 0.0.0.0에 열린다(없으면 시작을 거부한다)
CMD ["/app/.venv/bin/magus", "serve", "--transport", "http", "--host", "0.0.0.0", "--port", "8000"]
