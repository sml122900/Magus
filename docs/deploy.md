# 운영: 배포·백업·복구·알림

선택과 이유는 [decisions/hosting.md](decisions/hosting.md), 인증 서비스 연결은 [decisions/auth-provider.md](decisions/auth-provider.md)에 있다.
이 문서는 **운영자(사용자)가 그대로 따라 하는 절차**다. 계정을 만들고 돈을 내는 일은 운영자가 직접 한다.

## 0. 준비물(계정)

- [ ] Vultr 계정(결제 수단). 서버: 서울, `vc2-1c-1gb`, Ubuntu LTS. SSH 키로만 접속한다.
- [ ] 도메인 `magus.lifebookapplication.com`. DNS A 레코드 → 서버 IP `158.247.225.48`. Cloudflare DNS라면 **프록시 끔(DNS 전용)**.
- [ ] WorkOS 계정(AuthKit), **Production 환경**에서 설정한다. issuer·클라이언트 ID·사용자 id를 모두 같은 환경에서 가져온다(섞이면 iss 불일치로 401). 절차는 auth-provider.md "연결 절차"에 있다.
  - 리디렉션 URI 세 개(글자 그대로):
    - `https://magus.lifebookapplication.com/auth/callback` — 웹 로그인(코드: `PUBLIC_URL/auth/callback`)
    - `https://claude.ai/api/mcp/auth_callback` — Claude 커넥터(Claude CIMD 메타데이터의 콜백, 2026-10-03 조사)
    - `https://claude.com/api/mcp/auth_callback` — Claude 커넥터. **사용자가 추가로 등록함, 출처는 WorkOS 측 안내**(우리 조사로는 확인하지 않았다)
  - 리소스(audience): `https://magus.lifebookapplication.com/mcp`
- [ ] Cloudflare R2 버킷 `magus-backup`(위치 힌트 APAC)과 그 버킷 전용 API 토큰(읽기·쓰기). **수명 주기 규칙은 걸지 않는다.**
- [ ] 텔레그램 봇(BotFather)과 운영자 chat id.
- [ ] healthchecks.io 체크 하나: 주기 1일, 유예 2시간, 알림은 텔레그램.

## 1. 서버 준비(한 번)

```sh
# Ubuntu: Docker, 방화벽, 자동 보안 업데이트, 스왑 1GB
sudo apt update && sudo apt install -y docker.io docker-compose-v2 git ufw unattended-upgrades
sudo ufw allow OpenSSH && sudo ufw allow 80 && sudo ufw allow 443 && sudo ufw enable
sudo fallocate -l 1G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
sudo timedatectl set-timezone Asia/Seoul
```

SSH는 비밀번호 로그인을 끄고(`PasswordAuthentication no`) 키로만 들어간다.

## 2. 배포

```sh
sudo git clone <저장소> /opt/magus && cd /opt/magus/deploy
cp .env.example .env && chmod 600 .env     # 값을 채운다(아래 표)
mkdir -p data && sudo chown 10001 data      # 컨테이너 사용자(uid 10001)가 쓴다
sudo docker compose up -d --build
sudo docker compose ps                      # magus: healthy, caddy: running
curl -s https://<도메인>/healthz            # {"status":"ok"}
curl -s https://<도메인>/.well-known/oauth-protected-resource/mcp   # resource = https://<도메인>/mcp
```

| deploy/.env | 값 |
|---|---|
| `MAGUS_DOMAIN` | `magus.example.com`(Caddy가 이 이름으로 인증서를 받는다) |
| `PUBLIC_URL` | `https://magus.example.com` |
| `AUTH_ISSUER` | `https://<이름>.authkit.app` |
| `ALLOWED_USERS` | **처음에는 비워 둔다**(모두 403). 2-1절대로 첫 로그인 뒤 `user_…=default`를 넣는다. 아버지는 나중에 `,user_…=father`를 더한다 |
| `SESSION_SECRET` | `python -c "import secrets;print(secrets.token_hex(32))"` |
| `WEB_CLIENT_ID`(·`WEB_CLIENT_SECRET`) | WorkOS 웹 클라이언트(리다이렉트 `https://<도메인>/auth/callback`) |
| `ALERT_TELEGRAM_BOT_TOKEN`·`ALERT_TELEGRAM_CHAT_ID` | 텔레그램 |
| `RESTIC_REPOSITORY` | `s3:https://<계정id>.r2.cloudflarestorage.com/magus-backup` |
| `RESTIC_PASSWORD` | 무작위. **비밀번호 관리자에 따로 보관한다**(잃으면 백업을 못 읽는다) |
| `AWS_ACCESS_KEY_ID`·`AWS_SECRET_ACCESS_KEY` | R2 API 토큰 |
| `HEALTHCHECK_URL` | `https://hc-ping.com/<uuid>` |

### 2-1. 첫 로그인과 허용 목록(user id 얻기)

허용 목록에는 이메일이 아니라 WorkOS 사용자 id(토큰의 `sub`, `user_…`)를 적는다. 그 id는 한 번 로그인해 봐야 보인다.

1. **배포**: `.env`의 `ALLOWED_USERS`는 비워 둔 채 `sudo docker compose up -d --build`를 실행한다.
   - 비어 있으면 서버는 "모든 사용자를 거부한다"는 경고를 남기고 뜬다. 아무도 들어오지 못한다.
2. **로그인 시도(403 예상)**: 브라우저에서 `https://magus.lifebookapplication.com/login` → WorkOS 로그인으로 간다.
   - 403 화면이 나오고, 거기에 **사용자 id가 보인다**("운영자에게 아래 사용자 id를 알려 주세요").
   - 401 화면("로그인 토큰을 받아들이지 못했습니다")이면 허용 목록 문제가 아니라 설정 문제다. `sudo docker compose logs magus | grep "token rejected"`로 원인을 본다. 원인은 iss 불일치·aud 불일치·만료·서명 중 하나로 나온다.
3. **id 복사**: 403 화면의 id를 복사한다. 같은 값이 WorkOS 대시보드 Users의 그 사용자 id다(둘 중 아무 데서나).
4. **목록에 넣기**: `.env`에 `ALLOWED_USERS=user_…=default`를 쓴다.
5. **재시작**: `sudo docker compose up -d`.
   - `restart`는 `.env`를 다시 읽지 않는다. 바뀐 설정으로 컨테이너를 다시 만드는 `up -d`를 쓴다.
6. **재로그인**: `/login` → `/book`이 보이면 끝이다.

**순서(2026-10-05 결정)**
- 지금은 **운영자(사용자) 본인 계정을 `default`에 연결**한다. 개발용 PDF 임포트본으로 6단계(Claude 커넥터)를 시험한다.
  - 기존 원고 옮기기: 로컬의 `data/users/default`를 서버의 `/opt/magus/deploy/data/users/default`로 복사한다(`scp -r`).
  - 그다음 `sudo chown -R 10001 data && sudo docker compose exec magus /app/.venv/bin/magus reindex`를 실행한다.
- **아버지는 나중에 `father`로 따로 추가**한다. 같은 1~6단계로 id를 얻어 `ALLOWED_USERS=user_…=default,user_…=father`로 넣는다.
  - 아버지 원고는 docx 원본을 아버지 받은함에 새로 올려 임포트한다(PDF 임포트본을 옮기지 않는다).
  - 절차는 [onboarding-father.md](onboarding-father.md)에 있다.

업데이트: `cd /opt/magus && sudo git pull && cd deploy && sudo docker compose up -d --build`.

## 3. 알림 확인

```sh
sudo docker compose exec magus /app/.venv/bin/magus alert-test   # 텔레그램에 "알림 시험"이 와야 한다
```

- 서버 오류(ERROR 로그)는 같은 내용으로는 10분에 한 번만 온다. 원고 내용은 들어 있지 않다(종류·위치만).
- 백업이 실패하거나 하루 동안 돌지 않으면 healthchecks.io가 알린다.

## 4. 백업(매일 04:00)

```sh
sudo crontab -e
0 4 * * * cd /opt/magus/deploy && docker compose --profile backup run --rm backup >> /var/log/magus-backup.log 2>&1
```

- 처음 한 번은 손으로 돌려 본다: `sudo docker compose --profile backup run --rm backup` → `backup ok`.
- 하는 일: `restic backup /data`(index.sqlite 제외) → `forget --keep-daily 30 --prune` → `check --read-data-subset=1/30`.
- 이미지 버전 고정: 처음 돌린 뒤 `docker image inspect restic/restic:latest`로 버전을 보고, compose.yaml의 `restic/restic:latest`를 그 버전으로 바꾼다.

## 5. 복구

### 서버를 새로 만들어야 할 때(전체 복구)

1. 1~2절대로 새 서버에 배포한다. `.env`는 비밀번호 관리자에 보관한 값을 쓴다. 이때 `docker compose up`은 아직 하지 않는다.
2. `cd /opt/magus/deploy && mkdir -p restore && sudo docker compose --profile backup run --rm restore` → `restore/data/…`
3. `sudo rm -rf data && sudo mv restore/data data && sudo chown -R 10001 data`
4. `sudo docker compose up -d --build && sudo docker compose exec magus /app/.venv/bin/magus reindex`
5. 확인: `sudo docker compose exec -e USER_ID=default magus /app/.venv/bin/magus outline`을 복구 전 기록과 비교한다. Claude에서 book_outline도 부른다.

특정 날짜로 되돌리려면 `restic snapshots`로 id를 찾아 `restore <id>`를 쓴다.

### 복구 시험(정기, 서버 위에서)

```sh
cd /opt/magus/deploy && sudo ./restore-test.sh default father
# default: outline 같음 (35장 + 서장·맺음·부록 1~3 · 8부 · …)
```

최신 스냅샷을 `./restore`로 받아 별도 컨테이너에서 reindex하고, 사용자마다 지금 서버의 outline과 비교한다.
결과를 아래 기록에 적는다. 끝나면 `sudo rm -rf restore`.

### 복구 시험 기록

| 날짜 | 어디서 | 결과 |
|---|---|---|
| 2026-10-03 | 로컬(Docker, restic 공식 이미지, 로컬 저장소, 실데이터 사본 53.4MB) | 백업 34초·스냅샷 50.3MiB → 복구 2,396개 → reindex → default/book outline 66줄 **같음** |
| (배포 후) | 서버(R2) | `restore-test.sh default father` |

## 6. 점검 체크리스트(월 1회)

- [ ] healthchecks.io가 매일 초록인가
- [ ] `restore-test.sh`가 "같음"인가(위 기록에 적는다)
- [ ] `sudo apt list --upgradable`, Docker 이미지 갱신(`docker compose pull && up -d --build`)
- [ ] 디스크(`df -h`)와 사용자별 용량(웹 받은함 페이지의 "사용")
