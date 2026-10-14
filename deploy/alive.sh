#!/bin/sh
# 생존 확인(호스트 cron, 5분마다): 바깥 주소(DNS·Caddy·HTTPS·앱)로 /healthz를 보고 healthchecks.io(magus-alive)에 핑한다.
# 실패하면 /fail을 보낸다. 서버가 통째로 멈춰 핑이 끊겨도 healthchecks.io가 알린다(앱 안의 알림은 그때 못 보낸다).
# 디스크(2026-10-14): 루트(/) 사용률이 DISK_ALERT_PERCENT(기본 85)를 넘으면 앱 알림과 같은 텔레그램(ALERT_TELEGRAM_BOT_TOKEN·
#   ALERT_TELEGRAM_CHAT_ID, 없으면 ALERT_WEBHOOK_URL)으로 알린다. 넘어 있는 동안 6시간에 한 번만. 사용률 숫자만 보내고 자료 내용은 없다.
#   시험: DISK_ALERT_TEST=1 이면 기준과 상관없이 '시험' 알림 한 번(상태 파일을 건드리지 않는다).
# 환경변수 파일(deploy/.env): MAGUS_DOMAIN, HEALTHCHECK_ALIVE_URL(비어 있으면 생존 핑은 하지 않는다), 위 알림 변수
set -u
cd "$(dirname "$0")"
get() { sed -n "s/^$1=//p" .env | tail -n 1 | tr -d "'\""; }

notify() {  # $1: 보낼 글(사용률 같은 숫자만, 비밀·자료 없음)
	token=$(get ALERT_TELEGRAM_BOT_TOKEN)
	chat=$(get ALERT_TELEGRAM_CHAT_ID)
	hook=$(get ALERT_WEBHOOK_URL)
	api=${ALERT_TELEGRAM_API:-https://api.telegram.org}
	if [ -n "$token" ] && [ -n "$chat" ]; then
		curl -fsS -m 10 --retry 2 -o /dev/null --data-urlencode "chat_id=$chat" --data-urlencode "text=$1" "$api/bot$token/sendMessage"
	elif [ -n "$hook" ]; then
		curl -fsS -m 10 --retry 2 -o /dev/null -H 'Content-Type: application/json' --data "{\"text\": \"$1\"}" "$hook"
	fi
}

limit=${DISK_ALERT_PERCENT:-85}
state=${DISK_ALERT_STATE:-/var/tmp/magus-disk-alert}
used=$(df -P / | awk 'NR == 2 { sub("%", "", $5); print $5 }')
if [ "${DISK_ALERT_TEST:-}" = 1 ]; then
	notify "[Magus] 디스크 알림 시험: 지금 사용률 ${used}% (알림 기준 ${limit}%)"
elif [ -n "$used" ] && [ "$used" -gt "$limit" ]; then
	if [ -z "$(find "$state" -mmin -360 2>/dev/null)" ]; then  # 6시간 안에 보낸 적이 없을 때만
		notify "[Magus] 디스크 사용률 ${used}% — 알림 기준 ${limit}%를 넘었습니다. 빌드 캐시·옛 이미지 정리가 필요합니다(docs/deploy.md)." && touch "$state"
	fi
elif [ -f "$state" ]; then
	rm -f "$state"  # 기준 아래로 내려오면 다음에 넘을 때 바로 알린다
fi

url=$(get HEALTHCHECK_ALIVE_URL)
domain=$(get MAGUS_DOMAIN)
[ -n "$url" ] && [ -n "$domain" ] || exit 0

if curl -fsS -m 10 -o /dev/null "https://$domain/healthz"; then
	curl -fsS -m 10 --retry 3 -o /dev/null "$url"
else
	curl -fsS -m 10 --retry 3 -o /dev/null "$url/fail"
fi
