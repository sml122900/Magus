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
- 반영 전에: 백업을 손으로 한 번 돌려 스냅샷을 확인하고(`docker compose --profile backup run --rm backup </dev/null`), 실행 중 이미지를 `magus:rollback-<커밋>`으로 태그해 둔다.
- 반영 전에 되돌릴 커밋(`git rev-parse HEAD`)과 data 해시 목록을 적어 둔다. 되돌릴 때는 그 커밋으로 `reset --hard` 후 다시 빌드한다(`HEAD~1`을 쓰지 않는다).

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
| 2026-10-08 21:47 | `p1-contexts`(#93 층 + #94 책 종류 + #95 프로젝트·지도 + #96 컨텍스트 묶음, 데이터 이전 `magus maps apply --all-users`) | `ec6c40b`(`p1-profile-email`) → `efc19ac` | 반영 전 백업 스냅샷 `b390a042`(1,207개, 오류 없음). 옛 코드 전체 현황: default 미확인 문헌 297·열린 확인 요청 86, father 335편·미연결 5·확인 요청 129. 이전(멈춘 시간 약 1분): 두 사용자 모두 '전후 비교: 같음'·'옛 규칙 인용 점검과 같음'(default 생각 → 글 458·문체 → 글 4·휴지통 글 4·문헌 299, father 문헌 337·수정본 3). 올린 뒤 전체 현황 집계 줄 전후 같음. healthy·재시작 0, 허용 2명, `/healthz` ok, `/mcp` 401, 인덱스 v20. data 1,207개 중 원고 장·확인 요청·결정·원본·올린 파일 등 103개 해시 같음, 바뀜 638(문헌 bib.json 636·project.json 2), 옮겨짐 466(생각·문체 파일 → 책의 글), 새로 478(책·글·지도·floors.json·휴지통 글), `.env` 해시 같음. 컨테이너 안 임시 서버(/tmp, 인증 끔)로 프로젝트 목록·지도·노드 패널·노드 → 책 컨텍스트 순서·자주 쓰는 컨텍스트·올린 문서·옛 주소 넘김 확인 뒤 정리. 메모리 magus 125.8MiB, 디스크 61%. 되돌리기 이미지 `rollback-ec6c40b` 더함, `rollback-ebb98fc` 삭제, `rollback-e08bb79` 유지. 서버 기록 `/root/deploy-20261008-contexts/`(ROLLBACK.txt) |
| 2026-10-06 18:28 | `p1-profile-email`(표시 이름 메일: userinfo 주소를 OIDC 디스커버리에서, 못 받으면 검증한 id_token) | `e08bb79`(`p1-shelf-tweak`) → `ec6c40b` | 원인: WorkOS의 oauth-authorization-server 메타데이터에 userinfo_endpoint가 없어 userinfo를 부르지 않음(로그 email=no 3회, profile.json에 email 없음). 반영 전 백업 `f02024b5`(1,200개, 오류 없음). healthy·재시작 0, 허용 2명, `/healthz` ok, `/mcp` 401, data 1,200개·`.env` 해시 같음, 인덱스 v16. 컨테이너 안에서 userinfo 주소 찾음·가짜 토큰 401 확인. 되돌리기 이미지 `rollback-e08bb79` 더함, `rollback-05a2659` 삭제, `rollback-ebb98fc` 유지. 서버 기록 `/root/deploy-20261006-profile-email/` |
| 2026-10-06 18:15 | `p1-shelf-tweak`(문헌 책등 확인/전체, 상단 바 이름 = 표시 이름·가입 메일, `/me`) | `ebb98fc`(`p1-shelf-fix`) → `e08bb79` | 반영 전 백업 스냅샷 `4593624d`(1,199개, 오류 없음). 인덱스 v16 그대로, healthy·재시작 0, 허용 2명, `/healthz` ok, `/mcp` 401, data 1,199개 해시 같음(index 제외), `.env` 해시 같음. MCP 도구·instructions가 ebb98fc와 같은 해시라 커넥터 재연결 불필요. 컨테이너 안 임시 서버로 책등·`/me` 확인. 메모리 magus 83.5MiB, 디스크 54%. 되돌리기 이미지 `rollback-ebb98fc` 더함, `rollback-74bbbf4` 삭제, `rollback-05a2659` 유지. 서버 기록 `/root/deploy-20261006-shelf-tweak/` |
| 2026-10-06 17:09 | `p1-shelf-fix`(category_put 생각 경로·문체·문헌 안내, 템플릿 항목 내용 완화, instructions 규칙 11, CLI trash put category) | `05a2659`(`p1-shelf`) → `ebb98fc` | 반영 전 백업 스냅샷 `5f39c102`(1,198개, 오류 없음). 인덱스 v16 그대로, healthy·재시작 0, 허용 2명, `/healthz` ok, `/mcp` 401, data 1,198개 해시 같음(index 제외), `.env` 해시 같음. 메모리 magus 83.8MiB, 호스트 available 451MB, 디스크 58%(9.4G 남음). 되돌리기 이미지 `magus:rollback-05a2659` 더함, `rollback-74bbbf4` 유지. 배포 뒤 default 시험 기록(카테고리 「사례」·생각 「시험 메모」) 휴지통. 서버 기록 `/root/deploy-20261006-shelf-fix/` |
| 2026-10-06 14:51 | `p1-shelf`(책장·카테고리·책 색·제목 #92, 웹 항목 고치기·휴지통, 저자 확인 질문지 #84, 인덱스 v16, 도구 30) | `74bbbf4`(`p1-trash`) → `05a2659` | 반영 전 백업 스냅샷 `596da508`(1,194개, 오류 없음). 인덱스 v16 자동 재생성(14:51:41), healthy·재시작 0, 허용 2명, `/healthz` ok, `/mcp` 401, data 1,194개 해시 같음(index 제외), `.env` 해시 같음. 컨테이너 안 임시 서버(/tmp, 인증 끔)로 /shelf·카테고리 목록·/shelf/new·/questions 200. 메모리 magus 131.8MiB, 호스트 available 465MB. 되돌리기 이미지 `magus:rollback-74bbbf4`, 옛 `rollback-2d9777f` 삭제. 되돌리기 전 제목 키 정리(ROLLBACK.txt). 서버 기록 `/root/deploy-20261006-shelf/` |
| 2026-10-06 03:24 | `p1-trash`(휴지통 #88, 도구 설명 가드·내부 이름 빼기 #87, 문체 tags_by #89, 인덱스 스키마 v13) | `2d9777f`(`p1-ui-terms`) → `74bbbf4` | 반영 전 백업 스냅샷 `ec0c2c20`(802개, 오류 없음). 인덱스 v13 자동 재생성(03:25:23), healthy·재시작 0, 허용 2명, `/healthz` ok, `/mcp` 401, data 802개 해시 같음(index 제외), `.env` 해시 같음. 메모리 magus 130MiB, 호스트 available 460MB. 되돌리기 이미지 `magus:rollback-2d9777f`, 옛 `rollback-4df2720` 삭제. 배포 뒤 default 생각 3건을 `magus trash put`으로 휴지통(status.md 0-8절). 서버 기록 `/root/deploy-20261006-trash/` |
| 2026-10-06 03:01 | `p1-ui-terms`(웹 스타일, 세 책장 화면, 용어 통일 #85, 입력칸 #86, 허용 목록 중복 거부) | `4df2720`(`p1-reupload`) → `2d9777f` | 배포 전 서버 `ALLOWED_USERS`로 새 검사 통과(2명). 반영 전 백업 스냅샷 `8ea57cec`(798개, 오류 없음). healthy·재시작 0, 로그 허용 2명, `/healthz` ok, `/mcp` 401 + resource_metadata, data 798개 해시 같음(index 제외), `.env` 해시 같음. 새 문구: 바깥 오류 페이지의 상단 바·입력칸 CSS, 컨테이너 안 임시 로컬 서버로 메뉴 확인 요청·생각. 메모리 magus 123MiB, 호스트 available 469MB. 되돌리기 이미지 `magus:rollback-4df2720`, 옛 `rollback-896633c` 삭제. 서버 기록 `/root/deploy-20261006-ui-terms/`(ROLLBACK.txt) |
| 2026-10-06 01:38 | `p1-reupload`(#69~#77 임포트 보완, #76 다시 올리기, #79 포함) | `896633c`(`p1-auth-audience`) → `4df2720` | 반영 전 백업 스냅샷 `a3322693`(798개, 오류 없음). 인덱스 v12 자동 재생성(01:39:52), healthy, `/healthz` ok, `/mcp` 401 + resource_metadata, data 798개 해시 같음(index 제외), `.env` 해시 같음, default outline 수치 같음. 메모리 magus 123MiB, 호스트 available 440MB. 되돌리기 이미지 `magus:rollback-896633c`, 옛 `rollback-21b4e2a` 삭제. 서버 기록 `/root/deploy-20261006-reupload/`(ROLLBACK.txt) |
| 2026-10-06 00:53 | `p1-auth-audience`(토큰 aud 검사, 결정 #79) + 이력 교체 | `21b4e2a`(옛 이력) → `896633c`. 같은 상태의 새 이력 커밋은 `78c9668` | `/healthz` ok, `/mcp` 401 + resource_metadata, 컨테이너 안에서 trip_ai·섞인 aud 거부, 다른 `AUTH_AUDIENCE`로 시작 실패(종료 2), data 798개 해시 같음, `docs/reports` 객체 없음. 서버 기록은 `/root/deploy-20261006-auth-audience/`(ROLLBACK.txt) |

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
- 하는 일: `restic backup /data`(index.sqlite 제외) → `forget --keep-daily 30 --keep-monthly 12 --prune`(일별 30개 + 월별 12개, 결정 #62) → `check --read-data-subset=1/30`.
- 이미지 버전: compose.yaml에 `restic/restic:0.19.1`로 고정했다(2026-10-05). 올릴 때는 새 버전으로 한 번 손으로 돌려 `backup ok`를 본 뒤 바꾼다.
- 스크립트에서 `docker compose exec`·`run`을 부를 때는 `</dev/null`을 붙인다. 붙이지 않으면 표준입력을 읽어, 뒤에 이어지는 명령을 먹어 버린다.

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
| 2026-10-05 | 서버(Vultr 서울, R2, restic 0.19.1, default PDF 임포트본 797개·8.1MB, trash 제외) | 첫 백업 24초·스냅샷 `28e5e451` 7.7MiB → `restore-test.sh default` 28초 → 복구 797개 → reindex → default/book outline 66줄 **같음** |

## 6. 점검 체크리스트(월 1회)

- [ ] healthchecks.io가 매일 초록인가
- [ ] `restore-test.sh`가 "같음"인가(위 기록에 적는다)
- [ ] `sudo apt list --upgradable`, Docker 이미지 갱신(`docker compose pull && up -d --build`)
- [ ] 디스크(`df -h`)와 사용자별 용량(웹 받은함 페이지의 "사용")
