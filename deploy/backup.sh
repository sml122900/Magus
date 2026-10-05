#!/bin/sh
# 매일 스냅샷: ./data 전체(→ 컨테이너 /data)를 restic 저장소(R2)에 올린다.
# 보관: 일별 30개 + 월별 12개(각 달의 마지막 스냅샷). 30일 넘게 늦게 발견한 손상도 그 달 말 상태로 되돌릴 수 있다(결정 #62).
# index.sqlite는 빼도 된다(원본 파일에서 `magus reindex`로 다시 만든다). 그래서 실행 중인 DB의 일관성 문제가 없다.
# 환경변수(deploy/.env): RESTIC_REPOSITORY, RESTIC_PASSWORD, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY,
#                        HEALTHCHECK_URL(선택: healthchecks.io 핑. 안 오면 그쪽이 알린다)
set -eu

ping() {
	if [ -n "${HEALTHCHECK_URL:-}" ]; then
		wget -q -T 10 -O /dev/null "${HEALTHCHECK_URL}$1" || true
	fi
}

ping /start
restic snapshots --host magus >/dev/null 2>&1 || restic init

if restic backup /data --host magus --tag daily \
		--exclude '/data/index.sqlite' --exclude '/data/index.sqlite-wal' --exclude '/data/index.sqlite-shm' \
	&& restic forget --host magus --keep-daily 30 --keep-monthly 12 --prune \
	&& restic check --read-data-subset=1/30; then
	ping ""
	echo "backup ok"
else
	ping /fail
	echo "backup FAILED" >&2
	exit 1
fi
