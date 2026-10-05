#!/bin/sh
# 생존 확인(호스트 cron, 5분마다): 바깥 주소(DNS·Caddy·HTTPS·앱)로 /healthz를 보고 healthchecks.io(magus-alive)에 핑한다.
# 실패하면 /fail을 보낸다. 서버가 통째로 멈춰 핑이 끊겨도 healthchecks.io가 알린다(앱 안의 알림은 그때 못 보낸다).
# 환경변수 파일(deploy/.env): MAGUS_DOMAIN, HEALTHCHECK_ALIVE_URL(비어 있으면 아무것도 하지 않는다)
set -u
cd "$(dirname "$0")"
get() { sed -n "s/^$1=//p" .env | tail -n 1 | tr -d "'\""; }
url=$(get HEALTHCHECK_ALIVE_URL)
domain=$(get MAGUS_DOMAIN)
[ -n "$url" ] && [ -n "$domain" ] || exit 0

if curl -fsS -m 10 -o /dev/null "https://$domain/healthz"; then
	curl -fsS -m 10 --retry 3 -o /dev/null "$url"
else
	curl -fsS -m 10 --retry 3 -o /dev/null "$url/fail"
fi
