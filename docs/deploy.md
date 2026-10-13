# 운영: 배포·백업·복구·알림

선택과 이유는 [decisions/hosting.md](decisions/hosting.md), 인증 서비스 연결은 [decisions/auth-provider.md](decisions/auth-provider.md)에 있다.
이 문서는 **운영자(사용자)가 그대로 따라 하는 절차**다. 계정을 만들고 돈을 내는 일은 운영자가 직접 한다.

## 0. 준비물(계정)

- [ ] Vultr 계정(결제 수단). 서버: 서울, `vc2-1c-1gb`, Ubuntu LTS. SSH 키로만 접속한다.
- [ ] 도메인 `magus.lifebookapplication.com`. DNS A 레코드 → 서버 IP `158.247.225.48`. Cloudflare DNS라면 **프록시 끔(DNS 전용)**.
- [ ] WorkOS 계정(AuthKit). 지금은 **Staging 환경**(`dapper-palace-57-staging.authkit.app`)을 쓴다. 10-05 오전에 Production으로 정했다가, 같은 날 사용자 지시로 바꿨다. issuer·클라이언트 ID·사용자 id를 모두 같은 환경에서 가져온다(섞이면 iss 불일치로 401). 절차는 auth-provider.md "연결 절차"에 있다.
  - 리디렉션 URI 세 개(글자 그대로):
    - `https://magus.lifebookapplication.com/auth/callback` — 웹 로그인(코드: `PUBLIC_URL/auth/callback`)
    - `https://claude.ai/api/mcp/auth_callback` — Claude 커넥터(Claude CIMD 메타데이터의 콜백, 2026-10-03 조사)
    - `https://claude.com/api/mcp/auth_callback` — Claude 커넥터. **사용자가 추가로 등록함, 출처는 WorkOS 측 안내**(우리 조사로는 확인하지 않았다)
  - 리소스(audience): `https://magus.lifebookapplication.com/mcp`
- [ ] Cloudflare R2 버킷 `magus-backup`(위치 힌트 APAC)과 그 버킷 전용 API 토큰(읽기·쓰기). **수명 주기 규칙은 걸지 않는다.**
- [ ] 텔레그램 봇(BotFather)과 운영자 chat id.
- [ ] healthchecks.io 체크 둘, 알림은 텔레그램.
  - `magus-alive`: 주기 5분, 유예 5분. `deploy/alive.sh`(호스트 root cron, 유일한 발신처)가 바깥 주소 `https://<도메인>/healthz`(DNS·HTTPS·Caddy·앱)를 본 뒤 핑한다. 실패하면 `/fail`로 핑한다(`docs/decisions/hosting.md` 알림).
  - `magus-backup`: 주기 1일, 유예 2시간. `deploy/backup.sh`가 핑한다.

## 1. 서버 준비(한 번)

```sh
# Ubuntu: Docker, 방화벽, 자동 보안 업데이트, 스왑 1GB
sudo apt update && sudo apt install -y docker.io docker-compose-v2 git ufw unattended-upgrades
sudo ufw allow OpenSSH && sudo ufw allow 80 && sudo ufw allow 443 && sudo ufw enable
# 스왑: `swapon --show`에 이미 있으면 건너뛴다(Vultr Ubuntu 24.04 이미지에는 /swapfile 2.3G가 있다)
sudo fallocate -l 1G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
sudo timedatectl set-timezone Asia/Seoul
```

SSH는 비밀번호 로그인을 끄고 키로만 들어간다.
- Vultr 이미지는 `/etc/ssh/sshd_config.d/50-cloud-init.conf`에 `PasswordAuthentication yes`를 둔다. sshd는 먼저 읽은 값을 쓰므로 그보다 앞서 읽히는 `00-magus.conf`에 적는다.
- **기존 세션 하나를 열어 둔 채로** 바꾸고, 새 세션으로 키 접속이 되는 것을 확인한 뒤에 기존 세션을 닫는다.

```sh
printf 'PasswordAuthentication no\nKbdInteractiveAuthentication no\nPermitRootLogin prohibit-password\n' | sudo tee /etc/ssh/sshd_config.d/00-magus.conf
sudo sshd -t && sudo systemctl reload ssh
sudo sshd -T | grep -E '^(passwordauthentication|permitrootlogin) '   # no / without-password
# 다른 창에서: ssh root@<서버> echo ok → 성공, ssh -o PubkeyAuthentication=no root@<서버> → "Permission denied (publickey)"
```

## 2. 배포

원격 저장소가 없으므로 코드는 git bundle로 옮긴다(로컬 PC에서, 커밋한 것만 들어간다).

```sh
git bundle create magus.bundle master --tags
scp magus.bundle root@<서버>:/root/ && scp deploy/.env root@<서버>:/root/magus.env   # .env는 로컬에서 채운 것
```

```sh
sudo git clone -b master /root/magus.bundle /opt/magus && cd /opt/magus/deploy
sudo install -m 600 /root/magus.env .env && sudo rm /root/magus.env   # 또는 cp .env.example .env로 만들어 채운다(아래 표)
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
| `R2_ENDPOINT` | `https://<계정id>.r2.cloudflarestorage.com`(버킷 이름 없이). `R2_BUCKET=magus-backup` |
| `R2_ACCESS_KEY_ID`·`R2_SECRET_ACCESS_KEY` | R2 API 토큰. `RESTIC_REPOSITORY`·`AWS_*`는 이 값들로 compose가 만든다(고치지 않는다) |
| `RESTIC_PASSWORD` | 무작위. **비밀번호 관리자에 따로 보관한다**(잃으면 백업을 못 읽는다). `$`가 있으면 작은따옴표로 감싼다 |
| `HEALTHCHECK_ALIVE_URL` | magus-alive 체크의 `https://hc-ping.com/<uuid>` |
| `HEALTHCHECK_URL` | magus-backup 체크의 `https://hc-ping.com/<uuid>` |

### 2-1. 첫 로그인과 허용 목록(user id 얻기)

허용 목록에는 이메일이 아니라 WorkOS 사용자 id(토큰의 `sub`, `user_…`)를 적는다. 그 id는 한 번 로그인해 봐야 보인다.

1. **배포**: `.env`의 `ALLOWED_USERS`는 비워 둔 채 `sudo docker compose up -d --build`를 실행한다.
   - 비어 있으면 서버는 "모든 사용자를 거부한다"는 경고를 남기고 뜬다. 아무도 들어오지 못한다.
2. **로그인 시도(403 예상)**: 브라우저에서 `https://magus.lifebookapplication.com/login` → WorkOS 로그인으로 간다.
   - 403 화면이 나오고, 거기에 **사용자 id가 보인다**("운영자에게 아래 사용자 id를 알려 주세요").
   - 401 화면("로그인 토큰을 받아들이지 못했습니다")이면 허용 목록 문제가 아니라 설정 문제다. `sudo docker compose logs magus | grep "token rejected"`로 원인을 본다. 원인은 iss 불일치·aud 불일치·만료·서명 중 하나로 나온다.
     - **aud 불일치**면 WorkOS에 등록한 리소스 주소가 `PUBLIC_URL/mcp`(`https://magus.lifebookapplication.com/mcp`)와 글자까지 같은지 확인한다(끝 `/`, http/https, 대소문자). 로그에 받은 aud의 모양(문자열/목록, 값)이 나온다.
     - `AUTH_AUDIENCE`로 받는 aud를 늘리지 않는다. 같은 WorkOS 환경을 쓰는 다른 서비스(trip_ai)의 토큰이 통과하게 된다. 서버는 `AUTH_AUDIENCE`가 `PUBLIC_URL/mcp`와 다르면 시작하지 않는다(`docs/decisions/shared-auth-audience.md`, 결정 #79).
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

업데이트: 로컬에서 새 번들을 만들어 `/root/magus.bundle`에 올린 뒤 아래를 실행한다.

- 지금(2026-10-06 18:28부터) 서버는 master(태그 `p1-profile-email`)에 있다. 옛 이력은 지웠다.
- `p1-shelf`부터 되돌릴 때는 먼저 생각 파일의 제목 키를 정리한다(서버 `/root/deploy-20261006-shelf/ROLLBACK.txt`, status.md 0-10절).
- 로컬이 Windows면 서버 접속은 Windows OpenSSH(`C:\Windows\System32\OpenSSH\ssh.exe`)로 한다. Git Bash의 ssh는 다른 known_hosts를 읽어 "Host key verification failed"가 난다(호스트 키를 새로 받아들이지 않는다).
- `ssh … 'bash -s' <<EOF` 안에서 `docker compose exec -T`를 부를 때는 `</dev/null`을 붙인다. 안 붙이면 exec가 스크립트의 남은 줄을 stdin으로 먹는다.
- 배포는 pull 대신 `cd /opt/magus && sudo git fetch /root/magus.bundle master && sudo git checkout -B master FETCH_HEAD && cd deploy && sudo docker compose up -d --build`. 태그도 가져오려면 `git fetch /root/magus.bundle "refs/heads/master:refs/remotes/bundle/master" "refs/tags/*:refs/tags/*"` 뒤 `git checkout -B master <태그>`.
  - 그 master에 `p1-auth-audience`가 들어 있어야 한다(`git merge-base --is-ancestor p1-auth-audience FETCH_HEAD`). 아니면 aud 검사가 옛 판으로 되돌아간다.
- 반영 전에: 백업을 손으로 한 번 돌려 스냅샷을 확인하고(`docker compose --profile backup run --rm -e BACKUP_TAG=<배포 태그> backup </dev/null`, 2026-10-09부터 스냅샷에 `predeploy`·배포 태그),
  실행 중 이미지를 `magus:rollback-<커밋>`으로 태그해 둔다. 되돌리기 이미지는 지금 것 + 최근 2개만 남긴다(그보다 옛 판은 태그에서 다시 빌드, 2-9절).
- 반영 전에 되돌릴 커밋(`git rev-parse HEAD`)과 data 해시 목록을 적어 둔다. 되돌릴 때는 그 커밋으로 `reset --hard` 후 다시 빌드한다(`HEAD~1`을 쓰지 않는다).
  - data 해시는 `index.sqlite*`와 파생 폴더(`.cache`·`.text`·`.thumb`)를 빼고 비교한다(2026-10-09 결정 f). 원본 파일은 전후가 같아야 하고, 파생 파일은 개수만 따로 적는다.
  - `.env`는 변수 이름 개수만 본다(`grep -c '^이름=' …/.env`). 값·길이·해시는 보지 않는다(2026-10-09 사용자 지시, CLAUDE.md).
- 올린 뒤에: 인용 계산 캐시를 미리 만든다(`docker compose exec -T magus /app/.venv/bin/magus warm-cache --all-users`). 올리고 healthy면 `docker builder prune -f --filter until=72h`(72시간 넘은 빌드 캐시)와 되돌리기 이미지 정리(지금 것 + 최근 2개).

### 2-2. 층(#93) + 책 종류(#94) + 프로젝트·지도(#95) + 컨텍스트(#96) 묶음 배포 — 사용자 승인 뒤 한 번에

네 작업을 한 번에 낸다: **데이터 이전 한 번, 커넥터 재연결 한 번.** 반영 전 서버는 `p1-profile-email`(`ec6c40b`, 층 이전 전), 반영할 것은 master 끝.
바뀌는 것: 인덱스 v16 → v20(시작할 때 자동 재생성), 항목 파일에 `"floor"`(= 그 항목의 프로젝트 id)·`shelf/floors.json`·`shelf/maps/<프로젝트>.json`(이전 스크립트가 쓴다),
생각·문체 파일 → 책의 글(`shelf/categories/<책>/items/`), 문헌 bib.json에 `"book"`, 책·원고·문서에 `"contexts"`(#96, 같은 이전 명령이 한다),
도구 30 → 23(#94: idea_delete·style_delete를 category_trash에, book_document 더함 / #96: idea_add·style_add·ref_add → category_put, idea_search·style_search·ref_search → category_search),
도구 인자 floor → project(+ node), category → book, instructions 머리말·규칙 바뀜(#96 규칙 2·3·5~9·11·12),
웹 첫 화면은 프로젝트 목록, 프로젝트 화면은 지도 + 패널(옛 주소 `/book`·`/issues`·`/checklist`·`/questions`·`/inbox`·`/shelf?floor=`·`/shelf/floor/…`·`/shelf/ideas…`는 새 화면으로 넘긴다).
**새 코드의 `magus serve`는 옛 형식 책장(생각·문체 파일, 층 배치 없음)이 남은 사용자가 있으면 시작하지 않는다** — 3단계 이전을 빠뜨리고 올리는 일을 막는다.

1. **기록·백업**(서버, 위 "반영 전에" 그대로): `git rev-parse HEAD`(= `ec6c40b`) 기록, data 해시 목록, 손 백업 스냅샷(`docker compose --profile backup run --rm backup </dev/null`), 실행 중 이미지를 `magus:rollback-ec6c40b`로 태그.
2. **코드 반영·빌드만**(아직 올리지 않음): `cd /opt/magus && sudo git fetch /root/magus.bundle master && sudo git checkout -B master FETCH_HEAD`
   (`git merge-base --is-ancestor p1-auth-audience FETCH_HEAD` 확인) → `cd deploy && sudo docker compose build magus`.
3. **서버를 멈추고 이전**(멈춘 사이에 쓰기가 끼지 않게. 몇 초~몇십 초):
   ```sh
   sudo docker compose stop magus
   sudo docker compose run --rm --no-deps magus /app/.venv/bin/magus maps plan --all-users                     # 미리보기: 프로젝트마다 노드·책·연결·선, 지금 수치
   sudo docker compose run --rm --no-deps magus /app/.venv/bin/magus maps apply --all-users --backup /data/maps-backup
   ```
   - 층 이전 전 데이터라 apply가 층 배치(floors.json·"floor")부터 적고 지도를 적고, 책·컨텍스트(#96)까지 바꾼다(층 이전을 따로 돌리지 않는다. 옛 이름 `floors`도 같은 명령이다).
     출력에 `책 이전(#96): 책 「문체」 1 · 책 「생각」 1 · 책 「문헌」 1 · … · 원고 컨텍스트 1` 줄이 있다.
   - apply 출력 끝이 사용자마다 **"옛 규칙(그 층 + 공용)으로 낸 인용 점검과 이전 뒤: 같음"·"전후 비교: 같음"**이어야 한다. "다름"이면 올리지 않고 아래 "되돌리기"로 간다.
   - 로컬 시험(사본)에서의 기대값: father-trial 사본은 프로젝트 「인류가 선택한 진화…」(가운데 올린 문서[원고] · 「생각」[생각 메모] · 「문헌」 문헌 글 337[논문] · 연결 「문체」(내 서재)), 「내 서재」(「문체」[문체]),
     문헌 337·원문 확인 0·전체 현황 미확인 문헌 335편·확인 요청 129·수정본 1 그대로(`data/realdata/2026-10-08-maps-trial.md`, `data/realdata/2026-10-08-books-trial.md`).
4. **올리기**: `sudo docker compose up -d` → `docker compose ps`(healthy) → 로그에 허용 2명 → `/healthz` ok, `/mcp` 401 + resource_metadata.
5. **확인**(운영자 계정, 웹): `/shelf`에 프로젝트 카드(원고 프로젝트 + 「내 서재」). 프로젝트를 누르면 지도: 가운데 노드(올린 문서, 컨텍스트 「원고」), 생각·문헌 노드, 연결 「문체」.
   가운데 노드 → 올린 문서 → 탭 넷. `/book` → 올린 문서. 책 게시판 머리에 노드 → 책 순서의 컨텍스트, 노드 목록 보기에 종류 이름(원고 책 등)이 없는지. `/inbox` → '올린 파일'. 노드 하나를 끌어 놓은 뒤 새로 고쳐도 그 자리인지.
   data 해시: 바뀐 파일은 항목 파일(`"floor"`)과 새 `shelf/floors.json`·`shelf/maps/`, 백업 폴더뿐이어야 한다(원고·issues.md·decisions.md·project.json은 같음).
6. **커넥터 재연결 한 번**(claude.ai 설정 → 커넥터 → Magus 연결 해제 → 다시 연결). 도구 23개인지, 비밀 대화에서 "전체 보여 줘"가 book_outline으로 가고 머리에 지도 두 줄이 보이는지,
   "지도 보여 줘"가 category_list로 가는지, "저장해 줘"(넣을 곳을 말하지 않음)에 책 이름과 컨텍스트 이름을 보여 주며 묻는지, 글을 넣은 응답 첫 줄에 컨텍스트가 보이는지.
7. **사용자 할 일(배포 뒤)**: 휴대폰에서 지도 보기의 핀치·끌기, 책 끌어 옮기기(길게 눌러 들어 올리기) 한 번. 헤드리스로는 마우스만 확인했다.

**되돌리기**(이 순서를 지킨다. 옛 코드는 `"floor"`가 든 생각·문체 파일을 읽지 못한다):
```sh
sudo docker compose stop magus
sudo docker compose run --rm --no-deps magus /app/.venv/bin/magus maps revert --all-users   # 새 코드로: 글을 생각·문체 파일로, 문헌의 "book"·"floor"를 떼고, 이전으로 생긴 책·floors.json·maps/를 옆으로 비켜 둔다(지우지 않음)
sudo docker tag magus:rollback-ec6c40b magus:latest && sudo docker compose up -d --no-build      # 옛 이미지. 또는 ec6c40b로 reset --hard 뒤 build
```
- 옛 코드는 인덱스 버전이 다르면(v20 ≠ v16) 파일에서 다시 만든다. 새 파일 중 옛 코드가 모르는 것은 그대로 남고 무시된다: 문서 책(`shelf/documents/`), 원고 책 색(project.json `color`),
  컨텍스트(project.json·document.json `contexts`, `shelf/contexts.json`), 문헌의 옮긴 기록(bib.json `moved`), 휴지통의 노드(`trash/shelf/nodes/`),
  비켜 둔 `maps.reverted-<시각>/`·`categories.reverted-<시각>/`(이전으로 생긴 책). 배포 뒤 문헌 책에 직접 쓴 글(서지 없는 글)은 저자의 카테고리 「문헌(글)」로 남는다.
- 배포 뒤에 웹에서 휴지통으로 보낸 원고 책은 `trash/`에 있고, 그 프로젝트는 같은 id의 원고 없는 프로젝트로 남는다(옛 코드에서는 장 없는 책). 배포 뒤 만든 프로젝트도 같다.
- 그래도 이상하면 3단계의 `/data/maps-backup/<사용자>-shelf-<시각>/`을 사용자 `shelf/`에 되돌려 놓는다(또는 1단계 스냅샷에서 복구, 5절).

반영 기록

| 날짜(KST) | 반영 | 반영 전 → 후 | 확인 |
|---|---|---|---|
| 2026-10-09 03:13 | `p1-board`(#98 게시판 페이지·도움말 대화 보관·웹 글 고치기/원문 확인 체크 없앰 + 배포 전 수정: 사진 썸네일·크게 보기, 원문 확인 떼기(category_edit), 규칙 7 문장, 휴대폰 화면. 데이터 이전 없음) | `ed15ffb`(`p1-razor`) → `0e0c89e` | 서버 키 줄 개수 1(값 출력 없음). 반영 전 백업 스냅샷 `cf6daea4`(2,321개, 오류 없음). healthy·재시작 0, 허용 2명, `/healthz` ok, `/mcp` 401 + resource_metadata, 인덱스 v20, Pillow 12.3.0. data 2,321개 해시 같음(index 제외), `.env` 해시 같음. 수치 전후 같음: default 문헌 299·원문 확인 0·미확인 297·미연결 0·확인 요청 86·수정본 0, father 337·0·335·5·129·수정본 3(E3). 전체 현황 글자까지 같음. `magus thumbs --all-users`: 서버에 사진 첨부가 없어 만듦 0, 그 뒤 원본 해시 같음(.thumb 제외 2,321개). 컨테이너 안 /tmp 임시 점검 13/13(게시판 사진 썸네일·📎·글 휴지통·되살리기·노드 휴지통·원문 확인 붙이기/떼기·files_list 첨부·도구 23개, 실사용자 공간에 시험 글 없음). 메모리 111.6MiB, 디스크 76%. 되돌리기 이미지 `rollback-ed15ffb` 더함(`efc19ac`·`ec6c40b`·`e08bb79` 유지). 서버 기록 `/root/deploy-20261009-board/`(ROLLBACK.txt) |
| 2026-10-09 00:33 | `p1-razor`(#97 오캄의 면도날 + 도움말 + 이어지는 질문 + 노드 삭제, 데이터 이전 없음) | `efc19ac`(`p1-contexts`) → `ed15ffb` | 서버 키 줄 개수 1(값 출력 없음). 반영 전 백업 스냅샷 `65e81c66`(2,320개, 오류 없음). healthy·재시작 0, 허용 2명, `/healthz` ok, `/mcp` 401 + resource_metadata, `/help/ask` 로그인 없이 401, 인덱스 v20. data 2,320개 해시 같음(index 제외), `.env` 해시 같음. 수치 전후 같음: default 문헌 299·미확인 297·미연결 0·확인 요청 86·수정본 0, father 337·335·5·129·수정본 3(E3). 전체 현황 글자까지 같음. 컨테이너 안 /tmp 임시 점검 9/9(실사용자 공간에서 노드 삭제 시험 안 함). 도움말 실제 호출 1회: 입력 50·캐시 쓰기 15,749·출력 173토큰, 5.0초. 메모리 127.5MiB, 디스크 69%. 되돌리기 이미지 `rollback-efc19ac` 더함(`ec6c40b`·`e08bb79` 유지). 서버 기록 `/root/deploy-20261009-razor/` |
| 2026-10-08 21:47 | `p1-contexts`(#93 층 + #94 책 종류 + #95 프로젝트·지도 + #96 컨텍스트 묶음, 데이터 이전 `magus maps apply --all-users`) | `ec6c40b`(`p1-profile-email`) → `efc19ac` | 반영 전 백업 스냅샷 `b390a042`(1,207개, 오류 없음). 옛 코드 전체 현황: default 미확인 문헌 297·열린 확인 요청 86, father 335편·미연결 5·확인 요청 129. 이전(멈춘 시간 약 1분): 두 사용자 모두 '전후 비교: 같음'·'옛 규칙 인용 점검과 같음'(default 생각 → 글 458·문체 → 글 4·휴지통 글 4·문헌 299, father 문헌 337·수정본 3). 올린 뒤 전체 현황 집계 줄 전후 같음. healthy·재시작 0, 허용 2명, `/healthz` ok, `/mcp` 401, 인덱스 v20. data 1,207개 중 원고 장·확인 요청·결정·원본·올린 파일 등 103개 해시 같음, 바뀜 638(문헌 bib.json 636·project.json 2), 옮겨짐 466(생각·문체 파일 → 책의 글), 새로 478(책·글·지도·floors.json·휴지통 글), `.env` 해시 같음. 컨테이너 안 임시 서버(/tmp, 인증 끔)로 프로젝트 목록·지도·노드 패널·노드 → 책 컨텍스트 순서·자주 쓰는 컨텍스트·올린 문서·옛 주소 넘김 확인 뒤 정리. 메모리 magus 125.8MiB, 디스크 61%. 되돌리기 이미지 `rollback-ec6c40b` 더함, `rollback-ebb98fc` 삭제, `rollback-e08bb79` 유지. 서버 기록 `/root/deploy-20261008-contexts/`(ROLLBACK.txt) |
| 2026-10-06 18:28 | `p1-profile-email`(표시 이름 메일: userinfo 주소를 OIDC 디스커버리에서, 못 받으면 검증한 id_token) | `e08bb79`(`p1-shelf-tweak`) → `ec6c40b` | 원인: WorkOS의 oauth-authorization-server 메타데이터에 userinfo_endpoint가 없어 userinfo를 부르지 않음(로그 email=no 3회, profile.json에 email 없음). 반영 전 백업 `f02024b5`(1,200개, 오류 없음). healthy·재시작 0, 허용 2명, `/healthz` ok, `/mcp` 401, data 1,200개·`.env` 해시 같음, 인덱스 v16. 컨테이너 안에서 userinfo 주소 찾음·가짜 토큰 401 확인. 되돌리기 이미지 `rollback-e08bb79` 더함, `rollback-05a2659` 삭제, `rollback-ebb98fc` 유지. 서버 기록 `/root/deploy-20261006-profile-email/` |
| 2026-10-06 18:15 | `p1-shelf-tweak`(문헌 책등 확인/전체, 상단 바 이름 = 표시 이름·가입 메일, `/me`) | `ebb98fc`(`p1-shelf-fix`) → `e08bb79` | 반영 전 백업 스냅샷 `4593624d`(1,199개, 오류 없음). 인덱스 v16 그대로, healthy·재시작 0, 허용 2명, `/healthz` ok, `/mcp` 401, data 1,199개 해시 같음(index 제외), `.env` 해시 같음. MCP 도구·instructions가 ebb98fc와 같은 해시라 커넥터 재연결 불필요. 컨테이너 안 임시 서버로 책등·`/me` 확인. 메모리 magus 83.5MiB, 디스크 54%. 되돌리기 이미지 `rollback-ebb98fc` 더함, `rollback-74bbbf4` 삭제, `rollback-05a2659` 유지. 서버 기록 `/root/deploy-20261006-shelf-tweak/` |
| 2026-10-06 17:09 | `p1-shelf-fix`(category_put 생각 경로·문체·문헌 안내, 템플릿 항목 내용 완화, instructions 규칙 11, CLI trash put category) | `05a2659`(`p1-shelf`) → `ebb98fc` | 반영 전 백업 스냅샷 `5f39c102`(1,198개, 오류 없음). 인덱스 v16 그대로, healthy·재시작 0, 허용 2명, `/healthz` ok, `/mcp` 401, data 1,198개 해시 같음(index 제외), `.env` 해시 같음. 메모리 magus 83.8MiB, 호스트 available 451MB, 디스크 58%(9.4G 남음). 되돌리기 이미지 `magus:rollback-05a2659` 더함, `rollback-74bbbf4` 유지. 배포 뒤 default 시험 기록(카테고리 「사례」·생각 「시험 메모」) 휴지통. 서버 기록 `/root/deploy-20261006-shelf-fix/` |
| 2026-10-06 14:51 | `p1-shelf`(책장·카테고리·책 색·제목 #92, 웹 항목 고치기·휴지통, 저자 확인 질문지 #84, 인덱스 v16, 도구 30) | `74bbbf4`(`p1-trash`) → `05a2659` | 반영 전 백업 스냅샷 `596da508`(1,194개, 오류 없음). 인덱스 v16 자동 재생성(14:51:41), healthy·재시작 0, 허용 2명, `/healthz` ok, `/mcp` 401, data 1,194개 해시 같음(index 제외), `.env` 해시 같음. 컨테이너 안 임시 서버(/tmp, 인증 끔)로 /shelf·카테고리 목록·/shelf/new·/questions 200. 메모리 magus 131.8MiB, 호스트 available 465MB. 되돌리기 이미지 `magus:rollback-74bbbf4`, 옛 `rollback-2d9777f` 삭제. 되돌리기 전 제목 키 정리(ROLLBACK.txt). 서버 기록 `/root/deploy-20261006-shelf/` |
| 2026-10-06 03:24 | `p1-trash`(휴지통 #88, 도구 설명 가드·내부 이름 빼기 #87, 문체 tags_by #89, 인덱스 스키마 v13) | `2d9777f`(`p1-ui-terms`) → `74bbbf4` | 반영 전 백업 스냅샷 `ec0c2c20`(802개, 오류 없음). 인덱스 v13 자동 재생성(03:25:23), healthy·재시작 0, 허용 2명, `/healthz` ok, `/mcp` 401, data 802개 해시 같음(index 제외), `.env` 해시 같음. 메모리 magus 130MiB, 호스트 available 460MB. 되돌리기 이미지 `magus:rollback-2d9777f`, 옛 `rollback-4df2720` 삭제. 배포 뒤 default 생각 3건을 `magus trash put`으로 휴지통(status.md 0-8절). 서버 기록 `/root/deploy-20261006-trash/` |
| 2026-10-06 03:01 | `p1-ui-terms`(웹 스타일, 세 책장 화면, 용어 통일 #85, 입력칸 #86, 허용 목록 중복 거부) | `4df2720`(`p1-reupload`) → `2d9777f` | 배포 전 서버 `ALLOWED_USERS`로 새 검사 통과(2명). 반영 전 백업 스냅샷 `8ea57cec`(798개, 오류 없음). healthy·재시작 0, 로그 허용 2명, `/healthz` ok, `/mcp` 401 + resource_metadata, data 798개 해시 같음(index 제외), `.env` 해시 같음. 새 문구: 바깥 오류 페이지의 상단 바·입력칸 CSS, 컨테이너 안 임시 로컬 서버로 메뉴 확인 요청·생각. 메모리 magus 123MiB, 호스트 available 469MB. 되돌리기 이미지 `magus:rollback-4df2720`, 옛 `rollback-896633c` 삭제. 서버 기록 `/root/deploy-20261006-ui-terms/`(ROLLBACK.txt) |
| 2026-10-06 01:38 | `p1-reupload`(#69~#77 임포트 보완, #76 다시 올리기, #79 포함) | `896633c`(`p1-auth-audience`) → `4df2720` | 반영 전 백업 스냅샷 `a3322693`(798개, 오류 없음). 인덱스 v12 자동 재생성(01:39:52), healthy, `/healthz` ok, `/mcp` 401 + resource_metadata, data 798개 해시 같음(index 제외), `.env` 해시 같음, default outline 수치 같음. 메모리 magus 123MiB, 호스트 available 440MB. 되돌리기 이미지 `magus:rollback-896633c`, 옛 `rollback-21b4e2a` 삭제. 서버 기록 `/root/deploy-20261006-reupload/`(ROLLBACK.txt) |
| 2026-10-06 00:53 | `p1-auth-audience`(토큰 aud 검사, 결정 #79) + 이력 교체 | `21b4e2a`(옛 이력) → `896633c`. 같은 상태의 새 이력 커밋은 `78c9668` | `/healthz` ok, `/mcp` 401 + resource_metadata, 컨테이너 안에서 trip_ai·섞인 aud 거부, 다른 `AUTH_AUDIENCE`로 시작 실패(종료 2), data 798개 해시 같음, `docs/reports` 객체 없음. 서버 기록은 `/root/deploy-20261006-auth-audience/`(ROLLBACK.txt) |

### 2-3. 오캄의 면도날 + 도움말 + 노드 삭제(#97) — 2026-10-09 사용자 승인

반영 전 서버는 `p1-contexts`(`efc19ac`), 반영할 것은 태그 `p1-razor`(`razor-c`·`razor-ab`·`razor-d`·이어지는 질문·`node-trash` 뒤). **데이터 이전 없음**:
기존 파일 형식은 그대로이고 새 폴더(`files/`·`trash/shelf/attachments/`·노드째 휴지통 `trash/shelf/nodes/<프로젝트>/<노드>/`)와
bib.json의 선택 키 `status_by`, 노드 휴지통 기록의 선택 키(`_trash.categories`·`documents`·`map_before`·`map_after_sha`)만 새로 생긴다(쓰기가 있을 때만). 인덱스 버전 그대로(v20).
바뀌는 것: 웹 화면 문구(설명 → 도움말), 게시판 새 글·고치기 = 제목·본문·첨부, 문헌 글의 '원문 확인' 체크, 원문 확인 넣기 폼(`/shelf/refs/register`) 없음,
첨부 보기 `/shelf/<책>/<글>/files/<id>`, 도움말 `POST /help/ask`(이어지는 질문: 최근 3번·3,000자), 노드 삭제(🗑·확인 창·`/shelf/p/<프로젝트>/trash` 되살리기),
instructions 규칙 12(커넥터 재연결), 의존성 `anthropic`(이미지 다시 빌드). MCP 도구 수·설명은 그대로(23개).
**실제 사용자 공간에서는 노드 삭제를 시험하지 않는다**(시험은 로컬 시험본과 컨테이너 안 /tmp 임시 서버에서만).

0. **사용자 할 일(배포 전)**: 서버 `/opt/magus/deploy/.env`에 `ANTHROPIC_API_KEY=<키>`를 직접 넣는다(대화창에 붙이지 않는다. `=` 앞뒤 공백 없이).
   없으면 도움말만 "지금은 도움말을 쓸 수 없어요."이고 다른 기능은 그대로다. 선택: `MAX_ATTACH_MB`(기본 20)·`HELP_DAILY_LIMIT`(기본 30).
   넣은 뒤 확인은 값 없이 개수만: `grep -c '^ANTHROPIC_API_KEY=sk-ant-' /opt/magus/deploy/.env` → 1.
1. **기록·백업**: `git rev-parse HEAD`(= `efc19ac`), data 해시 목록(index 제외), `.env` 해시, 손 백업 스냅샷, 실행 중 이미지를 `magus:rollback-efc19ac`로 태그.
   옛 코드 전체 현황 머리 4줄(사용자·프로젝트마다 `magus outline`): default 미확인 문헌 297·열린 확인 요청 86, father 335편·미연결 5·확인 요청 129·수정본 E3.
2. **코드 반영·빌드**: `git fetch /root/magus.bundle master && git checkout -B master FETCH_HEAD`(`git merge-base --is-ancestor p1-contexts FETCH_HEAD`) → `docker compose build magus`.
3. **올리기**: `docker compose up -d` → healthy·재시작 0, 허용 2명, `/healthz` ok, `/mcp` 401 + resource_metadata. 이전 명령은 없다.
4. **확인**: data 해시가 반영 전과 같음(index 제외. 아직 아무도 쓰지 않았으므로), 전체 현황 머리 4줄이 1단계와 같음, 문헌 수(father 337·default 299)·확인 요청 수·수정본 수 같음.
   컨테이너 안 임시 서버(/tmp, 인증 끔, 실데이터 안 씀)로 게시판 새 글(첨부 하나)·원문 확인 체크·첨부 보기·'?' 창 확인 뒤 정리.
   키를 넣었으면 운영자 계정으로 '?'에서 질문 하나 → 로그 `help ok … cache_write=…` 한 줄(질문·답이 로그에 없는지).
5. **커넥터 재연결 한 번**(instructions 규칙 12가 바뀜). 도구 23개 그대로.

**되돌리기**: 데이터 이전이 없으므로 이미지만 되돌린다. `docker tag magus:rollback-efc19ac magus:latest && docker compose up -d --no-build`(또는 `efc19ac`로 reset --hard 뒤 build).
옛 코드는 첨부 폴더(`files/`)·`status_by`를 읽지 않고 무시한다(로컬 사본에서 확인: reindex·전체 현황 정상, 체크한 원문 확인은 그대로 확인으로 보인다).
배포 뒤 웹에서 붙인 첨부는 옛 화면에 보이지 않을 뿐 폴더에 그대로 있다.

### 2-4. 게시판 페이지 + 배포 전 수정(#98) — 2026-10-09 사용자 승인

반영 전 서버는 `p1-razor`(`ed15ffb`), 반영할 것은 태그 `p1-board`(`0e0c89e`). **데이터 이전 없음**: 저장 형식 그대로이고, 사진 첨부의 썸네일
(`…/files/<글>/<첨부 id>/.thumb/thumb.jpg`, 파생값)과 bib.json `status_by.via=chat`만 새로 생긴다. 인덱스 v20 그대로. 의존성 `pillow`(이미지 다시 빌드).
바뀌는 것: 책 = 별도 페이지의 게시판(위치 표시·20개씩·글쓰기·글 보기), 지도 옆 iframe 없앰, 웹의 수정본 올리기·글 고치기·원문 확인 체크 없앰,
글 🗑 → 프로젝트 휴지통에서 되살리기, 게시판 첨부 → files_list `첨부:<id>` → book_import, instructions 규칙 7, category_edit `checked`·`item_id`,
사진 썸네일·크게 보기, 도움말 대화 브라우저 보관. MCP 도구 수 23개 그대로(설명 바뀜) → **커넥터 재연결**.
**실제 사용자 공간에서는 시험 글을 쓰지 않는다**(점검은 컨테이너 안 /tmp 임시 서버에서만).

1. **기록·백업**(`private/tmp/deploy-board/pre.sh`): head, `.env` 해시·키 줄 개수, data 해시(index 제외), 사진 첨부 수, 옛 코드 수치·전체 현황, 손 백업 스냅샷.
2. **되돌리기 이미지·빌드**(`build.sh`): `magus:rollback-ed15ffb` 태그 → 번들 fetch → `git checkout -B master p1-board`(`p1-razor` 포함 확인) → `docker compose build magus`.
3. **올리기·확인**(`up.sh`): `up -d` → healthy·허용 2명·`/healthz`·`/mcp` 401 → 수치·전체 현황 전후 → data 해시(아직 아무도 쓰지 않음) →
   `docker compose exec magus /app/.venv/bin/magus thumbs --all-users` → `.thumb/`을 뺀 data 해시가 반영 전과 같은지(원본 그대로) → 컨테이너 안 /tmp 임시 점검(`smoke.py`).
4. **커넥터 재연결 한 번**(도구 설명·instructions 규칙 7이 바뀜).

**되돌리기**: 데이터 이전이 없으므로 이미지만 되돌린다. `docker tag magus:rollback-ed15ffb magus:latest && docker compose up -d --no-build`.
옛 코드는 첨부 폴더에서 파일만 세므로 `.thumb/` 하위 폴더를 무시한다(첨부 목록 그대로). 배포 뒤 대화로 뗀 원문 확인 표시는 파일(bib.json status)에 그대로 남는다.

### 2-5. 웹 수정 묶음(#99: 고치기·제목 자동 채움·스크랩·찾기·첨부 고르기·책 색·책등·정해진 이름) — 2026-10-09 사용자 승인

반영 전 서버는 `p1-board`(`0e0c89e`), 반영할 것은 태그 `p1-edit-scrap`(`webfix-1-edit`~`webfix-9-help`·`webfix-4b-rank` 뒤). **데이터 이전 없음**:
저장 형식은 표시 하나만 늘어난다 — 글 파일·bib.json의 선택 키 `"scrap": true`(스크랩했을 때만), 뺀 첨부의 휴지통 기록
`trash/shelf/attachments/…/<첨부 id>.trash.json`(#97부터 있던 형식). **인덱스 v20 → v22**(스크랩 칸, 첨부 이름 색인):
새 서버가 처음 뜰 때 모든 사용자 색인을 파일에서 다시 만든다(내용 파일은 그대로, index.sqlite만 바뀜). 의존성 그대로.
바뀌는 것: 웹 글 고치기(되돌림)·뺀 첨부 되살리기, 제목 자동 채움, 스크랩(☆·'★ 스크랩만'), 찾기(앞부분 일치·글자 포함·첨부 이름),
첨부 고르기 목록, 책 색 화면, 책등 글자, 정해진 이름 안내, 도움말 문서. MCP 도구 23개 그대로(category_search `scrap_only`·category_edit `scrap`,
설명 바뀜), instructions 규칙 6·7 → **커넥터 재연결**. **실제 사용자 공간에는 시험 글을 쓰지 않는다**(점검은 컨테이너 안 /tmp, 찾기는 읽기만).

1. **기록·백업**(`private/tmp/deploy-webfix/pre.sh`): head, `.env` 해시·키 줄 개수, data 해시(index 제외), 옛 코드 수치·전체 현황·찾기(읽기만), 손 백업.
2. **되돌리기 이미지·빌드**(`build.sh`): `magus:rollback-0e0c89e` 태그 → 번들 fetch → `git checkout -B master p1-edit-scrap`(`p1-board` 포함 확인) → build.
3. **올리기·확인**(`up.sh`): `up -d` → healthy(색인을 다시 만드느라 조금 늦을 수 있다)·허용 2명·`/healthz`·`/mcp` 401 → 인덱스 v22 →
   수치·전체 현황 전후 → 찾기(raw·ra, 읽기만) → data 해시(index 제외, 아직 아무도 쓰지 않았으므로 같아야 한다) → 컨테이너 안 /tmp 점검(`smoke.py`).
4. **커넥터 재연결 한 번**(도구 설명·instructions 규칙 6·7이 바뀜).

반영 기록(2026-10-09 13:50 서버 시각): `0e0c89e` → `d692855`. 백업 `3313cc70`, healthy·재시작 0, 인덱스 v22 재생성, data 2,328개 해시 같음,
수치·전체 현황 전후 같음(default 299·297·0·86, father 337·335·5·129·E3), 찾기 `ra` 0 → 150·156(raw 1번째), /tmp 점검 21/21. 기록 `/root/deploy-20261009-webfix/`.

**되돌리기**: 데이터 이전이 없으므로 이미지만 되돌린다. `docker tag magus:rollback-0e0c89e magus:latest && docker compose up -d --no-build`
(옛 코드가 인덱스 v20을 다시 만든다). 옛 코드는 `"scrap"` 키와 첨부 휴지통 기록을 읽지 않고 무시한다. 다만 옛 코드로 대화에서 그 글을 고치면
(category_put item_id) 옛 put_category_item이 모르는 칸을 쓰지 않아 그 글의 스크랩 표시가 빠진다(글 내용은 그대로).

### 2-6. 첨부 글자·대화 검색 범위·예약어 '스크랩'(#100) — 2026-10-09 사용자 승인

반영 전 서버는 `p1-edit-scrap`(`d692855`), 반영할 것은 태그 `p1-attach-text`(`att-1-search-scope`·`att-2-reserved`·`att-3-extract` 뒤). **데이터 이전 없음**:
새로 생기는 것은 첨부 폴더 안 `.text/`(뽑은 글자·상태, 파생값)뿐이다. **인덱스 v22 → v23**(레인 attach_text, chunks.part): 첫 시작 때 다시 만든다. 의존성 그대로.
MCP 도구 23개 그대로(category_search `attachment`·`page`, category_edit `parts`, 설명 바뀜), instructions 규칙 2 → **커넥터 재연결**.

1. **기록·백업**(`private/tmp/deploy-attach/pre.sh`): head, `.env`, data 해시, 「스크랩」 책 수(읽기만), 글자 뽑을 첨부 수, 옛 코드 수치·전체 현황·찾기, 손 백업.
2. **되돌리기 이미지·빌드**(`build.sh`): `magus:rollback-d692855` → 번들 fetch → `git checkout -B master p1-attach-text` → build.
3. **올리기·확인**(`up.sh`): healthy·인덱스 v23 → 수치·전체 현황 전후 → data 해시(같아야 한다) → `magus extract --all-users`(개수만) →
   `.text/`를 뺀 data 해시가 반영 전과 같은지, 새 파일이 `.text/`뿐인지 → 컨테이너 안 /tmp 점검(`smoke.py`).
4. **커넥터 재연결 한 번**.

반영 기록(2026-10-09 14:57 서버 시각): `d692855` → `458ffb9`. 백업 `4a98c511`, healthy·재시작 0, 인덱스 v23 재생성, data 2,328개 해시 같음,
수치·전체 현황 전후 같음(default 299·297·0·86, father 337·335·5·129·E3), `magus extract --all-users` default 2개 뽑음(실패 0),
뽑은 뒤 기존 파일 해시 같음·새 파일은 .text 4개뿐, /tmp 점검 12/12. 기록 `/root/deploy-20261009-attach/`.

**되돌리기**: `docker tag magus:rollback-d692855 magus:latest && docker compose up -d --no-build`(옛 코드가 인덱스 v22를 다시 만든다).
옛 코드는 첨부 폴더에서 파일만 세므로 `.text/`를 무시한다(시험본에서 첨부 목록·수치 같음 확인). 지울 필요 없다(파생값).

### 2-7. 대화 검색 순위 보정 + 쓸 부분 저장 뒤 원문 확인 묻기(#101) — 2026-10-09 사용자 승인

반영 전 서버는 `p1-attach-text`(`458ffb9`), 반영할 것은 태그 `p1-search-rank`(`rank-1-search`·`rank-2-ask-check` 뒤). **데이터 이전 없음, 인덱스 v23 그대로**(다시 만들지 않는다).
바뀌는 것은 대화 찾기(category_search)의 결과 순서·책별 제한·개수 줄과 instructions 규칙 2 → **커넥터 재연결**. 도구 설명·웹 그대로.
절차는 2-6절과 같다(`private/tmp/deploy-rank/` pre.sh → build.sh → up.sh, 첨부 글자 단계는 '이미'만 나와야 한다).
반영 기록: `458ffb9` → `58ce884`. 백업 `c8a063b8`, healthy, data 2,332개 해시(.text 포함) 같음, 수치 전후 같음(father 337·335·5·129·E3), /tmp 점검 6/6.

**되돌리기**: `docker tag magus:rollback-458ffb9 magus:latest && docker compose up -d --no-build`.

### 2-8. 구조·버그 점검 결과 고치기(웹만) — 2026-10-09 사용자 승인

반영 전 서버는 `p1-search-rank`(`58ce884`), 반영할 것은 태그 `p1-fix-ui`(`fix-1-cite-cache`~`fix-12-small` 뒤). **데이터 이전 없음, 인덱스 v23 그대로.**
새로 생길 수 있는 것은 파생값·옮긴 것뿐이다: 프로젝트 폴더의 `.cache/cites.json`(인용 계산 캐시, 화면을 열 때 생긴다)과 `trash/projects/`(프로젝트 휴지통).
도구 설명·instructions는 그대로 → **커넥터 재연결 필요 없음**. 의존성·Dockerfile·deploy 그대로.

1. **기록·백업**(`private/tmp/deploy-fixui/pre.sh`): head, `.env` 해시, data 해시(index 제외), 옛 코드 수치·전체 현황, 옛 코드 인용 상태 계산 시간(읽기만), 손 백업.
2. **되돌리기 이미지·빌드**(`build.sh`): `magus:rollback-58ce884` → 번들 fetch → `git checkout -B master p1-fix-ui` → build.
3. **올리기·확인**(`up.sh`): healthy → `/healthz`·`/mcp` 401·없는 주소 404 오류 화면·POST 전용 주소 GET 303 → 인덱스 v23 → 수치·전체 현황 전후 →
   인용 상태 계산 시간(새 코드, 캐시는 메모리에만 두어 사용자 공간에 쓰지 않는다) → data 해시(`.cache`·`trash/projects` 빼고 같아야) → 컨테이너 안 /tmp 점검.
   - 컨테이너 안 /tmp에 넣은 파일은 root 것이라 `docker exec -u 0 … rm`으로 지운다(앱 사용자 10001은 지우지 못한다 — 지난 배포들의 마지막 rm도 실패했었다).

반영 기록(2026-10-09 18:35 서버 시각): `58ce884` → `409242d`. 백업 `8eb92b70`(2,363개, 오류 없음), healthy·재시작 0, 오류 로그 0, `.env` 같음,
data 2,363개 해시 같음(.cache·trash/projects 0개), 수치·전체 현황 전후 같음(default 299·297·0·86 3개 프로젝트, father 337·335·5·129·E3),
없는 주소 404(찾을 수 없습니다·돌아가기), `/shelf/projects` GET → 303 /shelf, /tmp 점검 9/9, 메모리 111MiB, 디스크 76%. 기록 `/root/deploy-20261009-fixui/`.
인용 상태 계산(인용 집계 + 답해 주실 질문): default 8.0~8.7초 → 처음 7.9초·다음 0.12초, father 12.8~13.4초 → 처음 11.8초·다음 0.15초.

**되돌리기**: `docker tag magus:rollback-58ce884 magus:latest && docker compose up -d --no-build`(인덱스 v23 그대로). 옛 코드는 `.cache/`와 `trash/projects/`를 읽지 않는다
(시험본에서 확인). 되돌린 동안 휴지통에 있는 프로젝트는 옛 코드에서 그냥 없는 프로젝트로 보이고 되살릴 수 없다 — 새 코드로 다시 올리거나 manifest.json의
paths를 `files/`에서 사용자 폴더로 옮긴 뒤 `magus reindex`.

### 2-9. 코드 점검 높음 5건 + 운영(로그 회전·배포 전 백업 태그·이미지 정리) — 2026-10-09 사용자 승인

반영 전 서버는 `p1-fix-ui`(`409242d`), 반영할 것은 태그 `p1-high-fix`(`deba2af`: `fix-high-5`까지의 5건 + 운영 커밋). **데이터 이전 없음, 인덱스 v23 그대로.**
바뀐 것: 그림 폭탄(썸네일 픽셀 상한 3,000만·실패 표시 `.thumb/failed`), docx 압축 폭탄(`magus/zipguard.py`, 풀기 전에 항목 2,000·풀린 합 200MB·압축률 100:1),
색인 다시 만들기(새 파일에 만들어 바꿔 끼움, 깨진 파일은 건너뛰고 경로만 로그, 실패하면 지금 색인 유지), 장 번호 0~9,999(book_write_chapter 입력 스키마에 최소·최대),
대화로 글 고치기(category_put item_id)는 웹과 같은 patch. 운영: `deploy/compose.yaml`의 magus·caddy `logging`, `deploy/backup.sh`의 `BACKUP_TAG`.
도구 설명·instructions 그대로, **book_write_chapter 입력 스키마만 바뀜**(도구 목록 9,207 → 9,218토큰). 서버가 범위 밖 번호를 거절하므로 재연결은 필수가 아니다(재연결하면 Claude가 범위를 미리 안다).

1. **기록**(`private/tmp/deploy-high/pre.sh`, 읽기만): head, `.env` 해시, SESSION_SECRET(줄 수·길이 32자 이상·감사 때 찍힌 값과 같은지·실행 중 컨테이너와 같은지, 값은 출력하지 않음),
   data 해시, 옛 코드 수치·전체 현황, 로그 설정·크기, 이미지 목록·`docker system df`, 메모리·디스크.
2. **되돌리기 이미지·코드·백업·빌드**(`build.sh`): `magus:rollback-409242d` → 번들 fetch → `git checkout -B master p1-high-fix` →
   손 백업(**새 backup.sh라 코드를 바꾼 뒤** `-e BACKUP_TAG=p1-high-fix`, 올리기 전) → build.
3. **올리기·확인**(`up.sh`): `docker compose up -d`(logging이 바뀌어 magus·caddy를 다시 만든다, caddy 인증서는 볼륨에 그대로) → healthy·`/healthz`·`/mcp` 401·`/login` 303 →
   인덱스 v23 → 수치·전체 현황 전후 → data 해시 → `.env` 같음 → SESSION_SECRET이 새 컨테이너에 있고 `.env`와 같음 → `LogConfig` → /tmp 점검(`smoke.py`) → 메모리·디스크.
4. **이미지 정리**(`cleanup.sh`, 올리기가 healthy일 때만): `magus:latest` + `rollback-409242d`·`rollback-58ce884`만 남기고 나머지 rollback 태그를 `docker rmi`(목록 먼저 출력),
   그다음 `docker image prune -f`(dangling만). 컨테이너·볼륨·빌드 캐시는 건드리지 않는다.

반영 기록(2026-10-09 19:32 서버 시각): `409242d` → `deba2af`. 백업 `68013e32`(태그 predeploy·p1-high-fix, 2,363개, 오류 없음), healthy·재시작 0, 오류 로그 0, `.env` 같음,
data 2,363개 해시 같음, 수치·전체 현황 전후 같음(default 299·297·0·86 3개 프로젝트, father 337·335·5·129·수정본 3(E3)), /tmp 점검 8/8
(압축 폭탄 25KB 0.01초 거절, 첨부 글자 뽑기 failed, 3,600만 픽셀 PNG 썸네일 없음·원본 그대로, 4,200만 화소 JPEG 썸네일 만듦, 색인 건너뜀 2·나머지 색인, 장 번호 2^63·-1·10000·문자열 거절,
대화 고치기 ★·누가 그대로). 로그 설정 `json-file map[]` → `map[max-file:5 max-size:10m]`(magus·caddy). 메모리 magus 119 → 103MiB, caddy 12 → 10MiB.
SESSION_SECRET: 줄 1개·32자 이상·새 컨테이너에 있고 `.env`와 같음 — **감사 때 도구 출력에 찍힌 값과 아직 같다(교체 안 함, 승인 대기).**
이미지 정리: rollback-458ffb9·d692855·0e0c89e·ed15ffb·efc19ac·ec6c40b·e08bb79(7개) 지움, dangling 0. 이미지 10.06GB → 7.34GB, 디스크 76%(여유 5.3G) → 67%(7.3G).
빌드 캐시 7.78GB(그중 6.54GB 회수 가능)는 그대로. 기록 `/root/deploy-20261009-high/`.

**되돌리기**: `docker tag magus:rollback-409242d magus:latest && docker compose up -d --no-build`(인덱스 v23 그대로, 데이터 형식 같음).
썸네일 실패 표시(`.thumb/failed`)는 옛 코드가 읽지 않는다(그 그림은 다시 만들려 한다). compose·backup.sh까지 되돌리려면 `git checkout -B master p1-fix-ui` 뒤 `up -d`.
`p1-contexts` 이전(`ec6c40b`)으로 가는 이미지는 지웠다 — 그때는 태그에서 다시 빌드하고 먼저 새 코드로 `magus maps revert --all-users`(2-2절).

### 2-10. 점검 후속 A: .env 보호 장치·결정 반영(b·d·e·f·h·i)·바로 할 수 있는 것 — 2026-10-09 사용자 승인

반영 전 서버는 `p1-high-fix`(`deba2af`), 반영할 것은 태그 `p1-followup-a`(`7662192`). **데이터 이전 없음, 인덱스 v23 그대로, 도구 설명·스키마·instructions 글자까지 그대로 → 커넥터 재연결 필요 없음**(도구 목록 9,218토큰).
바뀐 것(동작·응답 문장): 대화 찾기 AND(결정 b), 거절 뒤 적은 내용 유지(d·e), 인용 캐시 뒤에서 데우기·`magus warm-cache`(f), backup.sh 태그별 보관(h),
15-2·13-b·15-3·7-b·7-d·1-8·1-10·3-4·4-4·3-5·15-4·15-5·13-c·10-a·5-d·6-c·7-e·7-f·22-b·25-b·20-3·21-a~d(status.md 0-30절). 의존성: lxml 직접 선언(판 그대로), ruff는 개발만.

1. **기록**(`private/tmp/deploy-fa/pre.sh`, 읽기만): head, SESSION_SECRET 줄 개수만, data 해시(index·파생 제외), 옛 코드 수치·전체 현황, 로그 설정,
   `restic/restic:latest`를 쓰는 곳(compose·스크립트·cron·컨테이너), 이미지·빌드 캐시.
2. **되돌리기 이미지·코드·백업·빌드**(`build.sh`): `magus:rollback-deba2af` → `git checkout -B master p1-followup-a` → 손 백업(새 backup.sh, `BACKUP_TAG=p1-followup-a`) → build.
3. **올리기·확인**(`up.sh`): healthy·`/healthz`·`/mcp` 401·`/login` 303 → 인덱스 v23 → 수치·전체 현황 전후 → `magus warm-cache --all-users` → 첫 열기 시간 →
   data 해시(파생 제외) → SESSION_SECRET 줄 개수 → 로그 설정 → /tmp 점검(`smoke.py`) → 메모리·디스크.
4. **정리**(`cleanup.sh`, healthy일 때만): `docker builder prune -f --filter until=72h`, 쓰는 곳이 없으면 `restic/restic:latest` 지움, 되돌리기 이미지는 지금 것 + 최근 2개.

반영 기록(2026-10-09 21:27 서버 시각): `deba2af` → `7662192`. 백업 `a231513b`(predeploy·p1-followup-a, 2,363개, 오류 없음) — 새 보관 규칙으로 앞 배포 전 스냅샷 `68013e32`도 남음.
healthy·재시작 0·오류 로그 0, 원본 2,351개 해시 같음(파생 .cache 0 → 2, .text 10, .thumb 2), 수치·전체 현황 전후 같음(default 299·297·0·86 3개 프로젝트, father 337·335·5·129·수정본 3(E3)),
SESSION_SECRET 줄 1개, 로그 설정 `max-file:5 max-size:10m`(magus·caddy), /tmp 점검 10/10.
인용 캐시 미리 만들기: default 8.4초·father 12.1초 → 그 뒤 인용 상태 첫 열기 default 0.15초·father 0.17초(새로 계산한 장 0; 전에는 첫 열기 7.9초·11.8초).
정리: 빌드 캐시 8.77GB → 4.07GB(4.70GB 회수), `restic/restic:latest`·`magus:rollback-58ce884` 지움, 이미지 9.11GB → 5.44GB, 디스크 75% → 55%(여유 11G).
메모리 magus 105 → 133MiB(캐시를 데운 직후). 기록 `/root/deploy-20261009-fa/`.

**되돌리기**: `docker tag magus:rollback-deba2af magus:latest && docker compose up -d --no-build`(인덱스 v23 그대로, 데이터 형식 같음). 옛 코드는 `.cache/`를 그대로 읽는다(같은 형식).
backup.sh까지 되돌리려면 `git checkout -B master p1-high-fix` — 그러면 다음 매일 백업의 forget이 배포 전 스냅샷을 다시 일별 규칙으로 다룬다.

### 2-11. 점검 후속 B: 중간 항목 8개 + 도구 설명 줄이기 — 2026-10-09 사용자 승인

반영 전 서버는 `p1-followup-a`(`7662192`), 반영할 것은 태그 `p1-followup-b`(`86b6155`). **데이터 이전 없음, 인덱스 v23 그대로.**
**도구 설명·입력 스키마가 바뀜 → 커넥터 재연결 필요**(도구 목록 9,218 → 6,359토큰, instructions 2,437 그대로).
바뀐 것: 5-a 웹 본문 한도·업로드를 디스크로, 12-a 늦은 색인 다시 하기(index-pending.json, 파생), 15-6·15-2 입력 상한·장 번호 범위(스키마),
16-1 시각 형식(YYYY-MM-DD HH:MM:SS)·같은 파일 수정본 멈춤·'이미 가져옴'·'올린 문서 없음', 16-2 project 범위, 16-3 category_edit 한 번에 하나·쓸 부분 이유,
22-a 보일 이름 규칙 하나, 26 설명 줄이기·스키마 title·default null 뺌(status.md 0-31절, `docs/decisions/tool-descriptions-diet.md`). 의존성·Dockerfile·deploy 그대로.

절차는 2-10절과 같다(`private/tmp/deploy-fb/pre.sh`·`build.sh`·`up.sh`·`cleanup.sh`, 되돌리기 이미지 `magus:rollback-7662192`, 백업 태그 p1-followup-b).

반영 기록(2026-10-09 22:23 서버 시각): `7662192` → `86b6155`. 백업 `b10f8adf`(predeploy·p1-followup-b, 2,365개, 오류 없음).
healthy·재시작 0·오류 로그 0, 원본 2,351개 해시 같음(파생 .cache 2·.text 10·.thumb 2 그대로), 수치 전후 같음(default 299·297·0·86, father 337·335·5·129·수정본 3(E3)).
전체 현황 차이는 의도한 것뿐: 수정본 줄 시각 `10-08 00:16` → `2026-10-08 00:16:37`, 올린 문서 없는 프로젝트 둘은 '수정본 기록 없음(…)' → '올린 문서 없음'.
인용 상태 첫 열기 default 0.14초·father 0.16초(캐시 그대로 유효). /tmp 점검 10/10. 메모리 magus 121 → 96MiB. 디스크 55%.
정리: `rollback-409242d` 지움(남김: latest·rollback-7662192·rollback-deba2af), 72시간 넘은 빌드 캐시 0B. 배포 전 스냅샷 68013e32·a231513b·b10f8adf.

**되돌리기**: `docker tag magus:rollback-7662192 magus:latest && docker compose up -d --no-build`(인덱스 v23, 데이터 형식 같음).
늦은 색인 기록(`index-pending.json`)이 남아 있으면 옛 코드는 읽지 않는다 — 되돌린 뒤 `magus reindex`로 맞춘다. 되돌리면 커넥터도 다시 연결한다(설명이 옛것으로).

### 2-12. 후속 C: 찾기 일부 낱말만 맞음 + 활용형 앞부분, .env 훅 오탐 — 2026-10-09 사용자 승인

반영 전 서버는 `p1-followup-b`(`86b6155`), 반영할 것은 태그 `p1-followup-c`(`8806621`). **데이터 이전 없음, 인덱스 v23 그대로.**
바뀐 것: 찾기(웹·category_search)에서 보이는 범위에 모든 낱말이 맞는 글이 없으면 일부 낱말만 맞는 글을 '일부 낱말만 맞음'으로, 이 단계에서만 한글 낱말 앞부분(짧은 → 짧).
category_search 설명 한 문장(도구 목록 6,359 → 6,376토큰) → **커넥터 재연결 필요(B와 묶어 한 번)**. .env 훅(`.claude/`, 서버와 상관없음). 의존성·Dockerfile·deploy 그대로(status.md 0-32절).

절차는 2-11절과 같다(`private/tmp/deploy-fc/pre.sh`·`build.sh`·`up.sh`·`cleanup.sh`, 도구 `/root/fc-tools/`, 되돌리기 이미지 `magus:rollback-86b6155`, 백업 태그 p1-followup-c).

반영 기록(2026-10-09 23:01 서버 시각): `86b6155` → `8806621`. 백업 `92d55834`(predeploy·p1-followup-c, 2,365개, 오류 없음).
healthy·재시작 0·오류 로그 0, 원본 2,351개 해시 같음(파생 .cache 2·.text 10·.thumb 2 그대로), 수치 전후 같음(default 299·297·0·86, father 337·335·5·129·수정본 3(E3)),
전체 현황 네 개 모두 같음. 인용 상태 첫 열기 default 0.14초·father 0.17초. /tmp 점검 9/9(활용형 셋·모두 맞음 그대로·기호 글자 그대로·결과 줄·설명·대화 첫 줄).
메모리 magus 102 → 114MiB. 정리: `rollback-deba2af` 지움(남김: latest·rollback-86b6155·rollback-7662192), 72시간 넘은 빌드 캐시 0B, 디스크 55 → 51%.
배포 전 스냅샷 68013e32·a231513b·b10f8adf·92d55834.

**되돌리기**: `docker tag magus:rollback-86b6155 magus:latest && docker compose up -d --no-build`(인덱스 v23, 데이터 형식 같음). 되돌리면 커넥터도 다시 연결한다.

### 2-13. '+ 프로젝트' 간소화(제목만으로 만들기) — 2026-10-10 사용자 승인

반영 전 서버는 `p1-followup-c`(`8806621`), 반영할 것은 태그 `p1-plus-project`(`c0e8c55`). **데이터 이전 없음, 인덱스 v23 그대로. 웹만, 커넥터 재연결 필요 없음**
(도구 설명·스키마·instructions 그대로, book_import의 제목만 만들기 응답 한 문장만). 바뀐 것: '+ 프로젝트' = 제목·'만들기'만, 웹 문서 올리기 주소(`/shelf/manuscript`)·진행 막대 없앰,
도움말 02~05(status.md 0-33절). 의존성·Dockerfile·deploy 그대로.

절차는 2-11절과 같다(`private/tmp/deploy-pp/pre.sh`·`build.sh`·`up.sh`·`cleanup.sh`, 도구 `/root/pp-tools/`, 되돌리기 이미지 `magus:rollback-8806621`, 백업 태그 p1-plus-project).

반영 기록(2026-10-10 00:36 서버 시각): `8806621` → `c0e8c55`. 백업 `baf921f2`(predeploy·p1-plus-project, 2,367개, 오류 없음).
healthy·재시작 0·오류 로그 0, 원본 2,353개 해시 같음(파생 .cache 2·.text 10·.thumb 2 그대로), 수치 전후 같음(default 299·297·0·86, father 337·335·5·129·수정본 3(E3)),
전체 현황 다섯 개 모두 같음. 인용 상태 첫 열기 default 0.14초·father 0.17초. /tmp 점검 7/7('+ 프로젝트' 칸·문서 올리기 주소 없음·올린 파일과 첨부 두 길·제목 그대로·응답 문장).
메모리 magus 119 → 92MiB. 정리: `rollback-7662192` 지움(남김: latest·rollback-8806621·rollback-86b6155), 72시간 넘은 빌드 캐시 0B, 디스크 51%.

**되돌리기**: `docker tag magus:rollback-8806621 magus:latest && docker compose up -d --no-build`(데이터 형식 같음, 재연결 필요 없음).

### 2-14. 버튼 높이 맞추기 + '사진 찍기' 삭제 — 2026-10-10 사용자 승인

반영 전 서버는 `p1-plus-project`(`c0e8c55`), 반영할 것은 태그 `p1-btn-photo`(`fb76fb0`). **데이터 이전 없음, 인덱스 v23 그대로. 웹만, 커넥터 재연결 필요 없음.**
바뀐 것: 전역 버튼 규격(button·a.btn·summary.btn)과 `.acts` 줄, 글 보기·게시판·지도 머리·문서 화면의 짝 맞춤, 글쓰기·고치기의 카메라 단추 없앰(status.md 0-34절).

절차는 2-11절과 같다(`private/tmp/deploy-bp/pre.sh`·`build.sh`·`up.sh`·`cleanup.sh`, 도구 `/root/bp-tools/`, 되돌리기 이미지 `magus:rollback-c0e8c55`, 백업 태그 p1-btn-photo).

반영 기록(2026-10-10 02:14 서버 시각): `c0e8c55` → `fb76fb0`. 백업 `72236369`(predeploy·p1-btn-photo, 2,383개, 오류 없음).
healthy·재시작 0·오류 로그 0, 원본 2,367개 해시 같음(파생 .cache 3·.text 10·.thumb 3 그대로), 수치 전후 같음(default book 299·297·0·86, default 3b0d82fd 수정본 E2,
father 337·335·5·129·수정본 3(E3)), 전체 현황 다섯 개 모두 같음. /tmp 점검 4/4. 정리: `rollback-86b6155` 지움(남김: latest·rollback-c0e8c55·rollback-8806621), 디스크 51%.

**되돌리기**: `docker tag magus:rollback-c0e8c55 magus:latest && docker compose up -d --no-build`(데이터 형식 같음, 재연결 필요 없음).

### 2-15. 내 정보 '문서 업데이트' + 내 정보 올리기 없애기 — 2026-10-10 사용자 승인

반영 전 서버는 `p1-btn-photo`(`fb76fb0`), 반영할 것은 태그 `p1-doc-update`(`9316d37`). **데이터 이전 없음, 인덱스 v23 그대로. 도구 설명·instructions가 바뀌어 커넥터 재연결 필요.**
바뀐 것: 내 정보 › 문서 업데이트(`/me/documents`), 내 정보의 올리기·지우기 없앰(옛 `/inbox/upload`·`/inbox/delete` POST 410), 바꾸기 실패 로그(종류·스택만)(status.md 0-35·0-36절).

절차는 2-11절과 같다(`private/tmp/deploy-du/pre.sh`·`build.sh`·`up.sh`·`cleanup.sh`, 도구 `/root/du-tools/`, 되돌리기 이미지 `magus:rollback-fb76fb0`, 백업 태그 p1-doc-update).
이번부터 데이터 해시는 index.sqlite만 빼고 파생(.cache·.text·.thumb)까지 본다. 실데이터 확인은 읽기만·GET만(`docs_check.py`: 화면을 컨테이너 안에서 그려 줄 수 대조),
쓰는 점검(410·바꾸기·실패)은 컨테이너 /tmp 임시 공간(`smoke.py`)에서.

반영 기록(2026-10-10 03:35 서버 시각): `fb76fb0` → `9316d37`. 백업 `a1573b3f`(predeploy·p1-doc-update, 2,383개, 오류 없음). healthy·재시작 0·오류 로그 0, 데이터 2,383개 해시 같음(index.sqlite만 빼고 파생 .cache 3·.text 10·.thumb 3 포함, 올린 뒤·화면 점검 뒤·캐시 뒤·첫 열기 뒤 네 번), 수치 전후 같음(default book 299·297·0·86, default 3b0d82fd 수정본 E2,
father 337·335·5·129·수정본 3(E3)), 전체 현황은 장 상태 말만 다름(셋)·같음(둘). 문서 업데이트 화면 default 4줄·father 1줄 맞음(father 원고 1개 = E1~E3 원본, 같은 파일이라 '수정본 E3'으로 표시). /tmp 점검 7/7.
up.sh 출력이 SSH 끊김으로 잘려 남은 단계는 `up2.sh`로 다시 했다(결과 같음). 정리: `rollback-8806621` 지움(남김: latest·rollback-fb76fb0·rollback-c0e8c55), 디스크 52%.

**되돌리기**: `docker tag magus:rollback-fb76fb0 magus:latest && docker compose up -d --no-build`(데이터 형식 같음. 도구 설명이 옛것으로 돌아가므로 커넥터 재연결).
문서 업데이트로 바꾼 첨부·올린 파일은 옛 코드에서도 그대로 읽힌다(같은 자리의 파일, 이전 파일은 휴지통 폴더).

### 2-16. 머리의 Magus 로고 = 처음 페이지 링크 — 2026-10-10 사용자 승인

반영 전 서버는 `p1-doc-update`(`9316d37`), 반영할 것은 태그 `p1-logo-home`(`681020d`). **데이터 이전 없음, 인덱스 v23 그대로. 웹만, 커넥터 재연결 필요 없음.**
바뀐 것: 모든 화면 머리의 'Magus'가 처음 페이지(`/shelf`) 링크, 로그인 전 화면은 `/login`(status.md 0-37절). 의존성·Dockerfile·deploy 그대로.

절차는 2-11절과 같다(`private/tmp/deploy-logo/pre.sh`·`build.sh`·`up.sh`·`cleanup.sh`, 도구 `/root/logo-tools/`, 되돌리기 이미지 `magus:rollback-9316d37`, 백업 태그 p1-logo-home).
실데이터 화면 점검은 없고(읽기만 수치·전체 현황·해시), 바깥 GET으로 로그인 전 404 화면의 로고(/login), 컨테이너 /tmp에서 로그인한 9화면의 로고(/shelf)를 본다(`smoke.py`).

반영 기록(2026-10-10 23:56 서버 시각): `9316d37` → `681020d`. 백업 `4998f295`(predeploy·p1-logo-home, 2,383개, 오류 없음). healthy·재시작 0·오류 로그 0,
데이터 2,383개 해시 같음(index.sqlite만 빼고 파생 포함, 두 번), 수치 전후 같음(default book 299·297·0·86, default 3b0d82fd 수정본 E2, father 337·335·5·129·수정본 3(E3)),
전체 현황 다섯 개 모두 같음, 인용 상태 첫 열기 0.0~0.19초. 로그인 전 404 로고 /login 1개, /tmp 점검 2/2.
정리: `rollback-c0e8c55` 지움(남김: latest·rollback-9316d37·rollback-fb76fb0), 디스크 52%.

**되돌리기**: `docker tag magus:rollback-9316d37 magus:latest && docker compose up -d --no-build`(데이터 형식 같음, 재연결 필요 없음).

### 2-17. 2026-10-11 묶음(대화 넣기 제한·여러 문서 형식·휴지통 비우기·「내 서재」 보통 프로젝트·노드 복사·컨텍스트 칸) — 2026-10-11 사용자 승인

반영 전 서버는 `p1-logo-home`(`681020d`), 반영할 것은 태그 `p1-batch-1011`(`5962dce`). **데이터 이전 없음, 인덱스 v23 그대로. 의존성 olefile 0.47 추가(이미지 다시 빌드).
도구 설명·instructions가 바뀌어 커넥터 재연결 필요.** 바뀐 것: status.md 0-38·0-39절, `docs/decisions/2026-10-11-batch.md`.

절차는 2-11절과 같고 warm 단계를 더했다(`private/tmp/deploy-batch/pre.sh`·`build.sh`·`up.sh`·`warm.sh`·`cleanup.sh`, 도구 `/root/batch-tools/`,
되돌리기 이미지 `magus:rollback-681020d`, 백업 태그 p1-batch-1011). 실데이터는 읽기만·GET만(`batch_check.py`: 「내 서재」·연결 노드·프로젝트 목록을
프로세스 안에서 그림), 쓰는 점검은 컨테이너 /tmp(`smoke.py` 11가지). 배포 뒤 `magus warm-cache --all-users` 한 번(새로 뽑게 된 형식의 이미 올라간 첨부).

반영 기록(2026-10-11 04:26 서버 시각): `681020d` → `5962dce`. 백업 `c971a18e`(predeploy·p1-batch-1011, 2,431개, 오류 없음). healthy·재시작 0·오류 로그 0,
데이터 2,431개 해시 같음(index.sqlite만 빼고 파생 포함, 올린 뒤·읽기만 점검 뒤 두 번), 수치 전후 같음(default book 299·297·0·86), 전체 현황 셋 모두 같음,
인용 상태 첫 열기 0.27초·새로 계산 0장. 「내 서재」: default·father 모두 보통 프로젝트로 목록에 보임(특별 모양 없음, 휴지통 단추 있음),
default 「내 서재」 노드 2·책 1·글 5, father 「내 서재」 노드 1·책 0. 연결 노드는 두 사용자 모두 지금 지도에 없음. /tmp 점검 11/11.
warm-cache: default 첨부 글자 새로 0(이미 1·형식 아님 1), father 새로 1(실패 0), 원본 2,415개 해시 같음(파생 빼고), .text 10 → 12.
정리: `rollback-fb76fb0` 지움(남김: latest·rollback-681020d·rollback-9316d37), 디스크 59%.

배포 전 기록에서 본 것(배포와 무관, 사용자 확인 필요): father의 원고 프로젝트 `book`(장 42·수정본 2·책 3)이 2026-10-11 00:13 KST 웹에서 프로젝트 휴지통으로 옮겨져 있고
(`trash/projects/book-…`), 지금 father의 프로젝트는 원고 없는 `834536a5` 하나다. default의 `3b0d82fd`(장 3·수정본 1)·`a47cf6fb`도 같은 날 휴지통으로 옮겨졌다.
이번 배포로 휴지통 '영구 삭제'·'휴지통 비우기'가 생겼으므로, father 원고를 되살릴지 먼저 정한다(되살리기: 프로젝트 목록 › 휴지통 › 되살리기).

**되돌리기**: `docker tag magus:rollback-681020d magus:latest && docker compose up -d --no-build`(데이터 형식 같음. 도구 설명이 옛것으로 돌아가므로 커넥터 재연결).
새 코드로 생긴 것은 옛 코드에서도 그대로 읽힌다: 복사한 노드·책(보통 노드·책), 새 형식의 .text(옛 코드는 hwp 등 첨부를 '뽑지 않음'으로 보고 .text를 읽지 않는다).
영구 삭제한 것은 되돌리기로 돌아오지 않는다(백업에서 복구).

## 3. 알림 확인

```sh
sudo docker compose exec magus /app/.venv/bin/magus alert-test   # 텔레그램에 "알림 시험"이 와야 한다
```

- 서버 오류(ERROR 로그)는 같은 내용으로는 10분에 한 번만 온다. 원고 내용은 들어 있지 않다(종류·위치만).
- 백업이 실패하거나 하루 동안 돌지 않으면 healthchecks.io(magus-backup)가 알린다.
- 서버나 HTTPS가 멈추면 healthchecks.io(magus-alive)가 알린다. 호스트 cron에 생존 확인을 건다.

```sh
sudo crontab -e
*/5 * * * * /opt/magus/deploy/alive.sh >/dev/null 2>&1
```

손으로 한 번 돌려 healthchecks.io의 magus-alive가 초록이 되는지 본다: `sudo /opt/magus/deploy/alive.sh; echo $?`(0이면 `/healthz` 200과 핑 2xx).

- 2026-10-06 점검: 서버 `alive.sh`가 저장소 판과 같다(해시 `ea4684b`). `HEALTHCHECK_ALIVE_URL`은 `https://hc-ping.com/<uuid>` 형식이고, 손으로 돌려 종료 0을 확인했다. 값은 출력하지 않는다.
- 시험할 때 `.env` 값을 셸에서 읽으려면 `alive.sh`의 `get` 함수를 그대로 쓴다. `tr -d "\x27…"`처럼 쓰면 GNU tr이 `\`·`x`·`2`·`7`을 지워 주소가 망가진다(2026-10-06 실제로 겪음, 400 invalid url format).

## 4. 백업(매일 04:00)

```sh
sudo crontab -e
0 4 * * * cd /opt/magus/deploy && docker compose --profile backup run --rm backup </dev/null >> /var/log/magus-backup.log 2>&1
```

- 시간대를 바꾼 뒤라면 `sudo systemctl restart cron`(cron은 시작할 때의 시간대로 돈다).
- 처음 한 번은 손으로 돌려 본다: `sudo docker compose --profile backup run --rm backup` → `backup ok`.
  - 첫 실행이 R2에 저장소를 만든다(init). 2026-10-05: 24초, 스냅샷 7.7MiB.
- 하는 일: `restic backup /data`(index.sqlite 제외) → `forget --tag daily --keep-daily 30 --keep-monthly 12 --prune`(일별 30개 + 월별 12개, 결정 #62)
  → `forget --tag predeploy --keep-within 30d --prune`(배포 전 백업은 30일, 2026-10-09 결정 h) → `check --read-data-subset=1/30`.
- 스냅샷 태그(2026-10-09): 매일 백업은 `daily`, 배포 전 손 백업은 `-e BACKUP_TAG=<배포 태그>`로 `predeploy`와 그 태그(영문·숫자·`.`·`_`·`-`만).
  두 태그는 따로 정리한다(결정 h): 배포 전 스냅샷은 일별·월별 규칙에 들지 않아 같은 날 뒤 백업에 밀려 지워지지 않고, 30일 지나면 지워진다.
  한 forget에 `--keep-tag predeploy`를 더하지 않는 까닭: 그달 마지막 스냅샷이 predeploy이면 월별 보관을 차지했다가 30일 뒤 지워져 그달 월별 백업이 사라진다.
- 이미지 버전: compose.yaml에 `restic/restic:0.19.1`로 고정했다(2026-10-05). 올릴 때는 새 버전으로 한 번 손으로 돌려 `backup ok`를 본 뒤 바꾼다.
- 스크립트에서 `docker compose exec`·`run`을 부를 때는 `</dev/null`을 붙인다. 붙이지 않으면 표준입력을 읽어, 뒤에 이어지는 명령을 먹어 버린다.

## 5. 복구

- **언제 무엇을 옮기거나 지웠는지(사고 시각)는 활동 기록으로 본다(2026-10-14)**: `sudo tail -n 50 /opt/magus/deploy/data/users/<user id>/.activity.log` → 한 줄 = 시각(UTC, 한국은 +9시간) · 동작(휴지통으로·되살리기·영구 삭제·휴지통 비우기·프로젝트 만들기·문서 업데이트) · 대상 종류 · 대상 id · 경로(웹·대화·운영자). 서버 로그(컨테이너를 새로 만들면 사라짐)와 HTTPS 접근 로그(남기지 않음) 대신 이것을 본다. 이름·내용·메일은 없고, 90일 지난 줄은 지워지며, 백업에 들어간다(`magus/activity.py`).

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
| 2026-10-05 | 서버(Vultr 서울, R2, restic 0.19.1, default PDF 임포트본 797개·8.1MB, trash 제외) | 첫 백업 24초·스냅샷 `28e5e451` 7.7MiB → `restore-test.sh default` 28초 → 복구 797개 → reindex → default/book outline 66줄 **같음** |

## 6. 점검 체크리스트(월 1회)

- [ ] healthchecks.io가 매일 초록인가
- [ ] `restore-test.sh`가 "같음"인가(위 기록에 적는다)
- [ ] `sudo apt list --upgradable`, Docker 이미지 갱신(`docker compose pull && up -d --build`)
- [ ] 디스크(`df -h`)와 사용자별 용량(웹 받은함 페이지의 "사용")
- [ ] 되돌리기 이미지(`docker images magus`): 지금 것 + 최근 rollback 2개만. 빌드 캐시는 배포마다 72시간 넘은 것을 정리한다(2026-10-09 결정 i, 8.8GB → 4.1GB)
- [ ] 컨테이너 로그는 compose의 `logging`(json-file 10MB × 5)으로 회전한다(2026-10-09부터). `docker inspect -f '{{.HostConfig.LogConfig.Config}}' magus-magus-1`
