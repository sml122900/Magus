#!/bin/sh
# 복구 시험: 최신 스냅샷을 ./restore로 받아 인덱스를 다시 만들고, 사용자마다 outline이 지금 서버와 같은지 본다.
# 사용법: cd /opt/magus/deploy && ./restore-test.sh default father
# 결과(같음/다름)를 docs/deploy.md의 "복구 시험 기록"에 적는다.
set -eu
cd "$(dirname "$0")"
[ "$#" -gt 0 ] || { echo "사용자 id를 하나 이상 주세요(예: default father)" >&2; exit 2; }

rm -rf ./restore && mkdir -p ./restore && chown 10001 ./restore 2>/dev/null || true
# docker compose exec·run은 </dev/null로 부른다: 표준입력을 물려받으면(예: ssh … 'bash -s') 뒤에 오는 명령을 먹는다
docker compose --profile backup run --rm -T restore </dev/null   # → ./restore/data/…
chown -R 10001 ./restore 2>/dev/null || true               # magus 컨테이너(uid 10001)가 인덱스를 쓸 수 있게
docker compose run --rm -T --no-deps -v "$PWD/restore/data:/restored" -e DATA_DIR=/restored magus /app/.venv/bin/magus reindex </dev/null

status=0
for user in "$@"; do
	docker compose exec -T -e USER_ID="$user" magus /app/.venv/bin/magus outline </dev/null > "./restore/live-$user.txt"
	docker compose run --rm -T --no-deps -v "$PWD/restore/data:/restored" -e DATA_DIR=/restored -e USER_ID="$user" \
		magus /app/.venv/bin/magus outline </dev/null > "./restore/restored-$user.txt"
	if diff -q "./restore/live-$user.txt" "./restore/restored-$user.txt" >/dev/null; then
		echo "$user: outline 같음 ($(head -n 2 "./restore/live-$user.txt" | tail -n 1))"
	else
		echo "$user: outline 다름 — diff ./restore/live-$user.txt ./restore/restored-$user.txt" >&2
		status=1
	fi
done
exit $status
