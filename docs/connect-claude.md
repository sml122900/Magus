# Claude에 Magus 연결하기

> 2026-10-05 구성 기준이다(WorkOS **Staging**, CIMD·DCR 켬). 화면 순서와 이름은 그날 사용자가 claude.ai(웹)에서 본 화면이다. 모바일은 아직 확인하지 않았다.

- 커넥터 URL: **`https://magus.lifebookapplication.com/mcp`**
- 인증 서버: WorkOS AuthKit Staging `https://dapper-palace-57-staging.authkit.app`(PRM이 알려 주므로 Claude에 따로 넣지 않는다)

## 운영자가 미리 할 일

- [x] 서버 주소가 열려 있다: `https://magus.lifebookapplication.com/healthz` → ok(2026-10-05)
- [x] 운영자 본인이 `ALLOWED_USERS`에 `=default`로 들어 있다. 웹 `/login` → `/book`으로 확인했다(2026-10-05). 아버지는 7단계에서 `=father`로 추가한다([onboarding-father.md](onboarding-father.md)).
- [x] WorkOS(Staging) 설정
  - Magic Auth(메일 코드) 켬, 비밀번호 끔, 가입 끔(사용자는 운영자가 대시보드에서 만든다)
  - CIMD·DCR 켬
  - 리소스 `https://magus.lifebookapplication.com/mcp`(Default). 토큰의 aud가 이 값이어야 한다.

> **주의: 로컬 magus와 원격 Magus를 동시에 켜지 않는다.**
> - Claude Desktop의 로컬 커넥터(stdio)와 원격 커넥터는 도구 이름(`book_outline`, `idea_add` …)이 같다. Claude가 어느 쪽을 부를지 정할 수 없다.
> - 둘은 데이터도 다르다(로컬 `data/` ↔ 서버). 섞어 쓰면 원고와 책장이 두 곳으로 갈라진다.
> - 원격을 쓸 때는 로컬 커넥터를 끈다(Desktop 설정 → 커넥터, 또는 대화의 도구 메뉴).

---

## 사용자용(개발자)

1. claude.ai(웹) → **설정** → **커넥터** → **커스텀 커넥터 추가**
2. 이름 `Magus`, URL `https://magus.lifebookapplication.com/mcp`
3. 화면이 서버를 읽고 스스로 채운다. **감지된 값을 그대로 둔다.**
   - 인증: **"지금 로그인"**(감지됨)
   - OAuth 클라이언트: **"Claude의 게시된 ID 사용"**(감지됨). CIMD 방식이다. Client ID·Secret은 넣지 않는다.
     - 웹 로그인용 클라이언트(`client_01M45…`)는 서버의 `/login` 전용이다. 여기에 넣지 않는다.
     - 연결한 뒤에는 방식을 바꿀 수 없다(바꾸려면 지우고 다시 추가한다).
   - 요청 헤더: 비워 둔다.
4. **연결** → WorkOS 로그인 화면 → 이메일 → 메일로 온 코드 → Claude로 돌아온다.
5. 대화창의 **도구 메뉴에서 Magus를 켠다.** 로컬 magus는 끈다(위 주의).
6. 새 대화에서 확인한다. 2026-10-05 웹에서 넷 다 성공했다.
   - "Magus의 book_outline을 호출해 줘"
     - 첫 줄 `프로젝트: 닿으려는 종 (book)`
     - 둘째 줄 `35장 + 서장·맺음·부록 1~3 · 8부 · 249,065자 · 미확인 문헌 297편 · 미연결 0 · 열린 확인 요청 86`(용어 통일 #85를 배포하기 전 서버는 `열린 미해결 86`)
   - "제12장 인용 점검해 줘"(ref_check) → 미확인 28편, 문단 번호 포함
   - "제31장 요약해 줘"(book_read_chapter 1회) → 요약과 함께 그 장의 열린 확인 요청(I78)과 미확인 인용 8편을 말한다
   - "idea_add로 … 기록해 줘" → `기록함 [me] <id> · thought`
     - 서버의 default는 실제 원고 사본이다. 시험 메모를 남기지 않으려면 진짜 떠오른 생각으로 시험한다.
     - 생각을 지우려면 Claude에게 지우라고 분명히 말한다(idea_delete, 휴지통으로 옮김). 되살리기는 운영자가 한다(아래).
   - "ref_search로 '인구'를 찾아 줘" → verified 문헌이 아직 없으므로 `결과 없음. verified 문헌의 발췌·전문에서만 찾는다.`가 정상이다.
   - (#96 배포 뒤) idea_add·style_add·ref_add·idea_search·style_search·ref_search는 없다(도구 23개). 위 둘 대신
     "「생각」 책에 기록해 줘: …" → category_put(응답 첫 줄에 그 책의 컨텍스트 「생각 메모」), "'인구'를 찾아 줘" → category_search로 본다.
     넣을 곳을 말하지 않은 "저장해 줘"에는 책 이름과 컨텍스트 이름을 보여 주며 묻는 것이 정상이다.
7. 모바일: 같은 계정의 Claude 앱에서는 웹에서 추가한 커넥터가 그대로 보인다. 6을 다시 해 본다(**미확인**).
8. **토큰 갱신 확인**(알려진 위험): 다음 날 같은 대화에서 다시 불러 본다. 로그인을 다시 하라고 하면 기록한다(**미확인**).

### 정상일 때의 서버 쪽 흐름

2026-10-05 등록 때 관찰한 것이다(임시로 Caddy 접근 로그를 켰다가 껐다).

1. `POST /mcp` → **401**(토큰 없음, `resource_metadata` 안내)
2. `GET /.well-known/oauth-protected-resource/mcp` → 200(인증 서버 = WorkOS)
3. 로그인·클라이언트 확인은 Claude ↔ WorkOS 사이에서 일어나 서버에는 보이지 않는다. CIMD냐 DCR이냐도 서버 로그로는 알 수 없다.
4. `POST /mcp` 200(Bearer, UA `Claude-User`) 여러 번 → 도구 목록
5. 도구 호출 한 번마다 `POST /mcp`가 두 번 오고, magus 로그에 `tool=<이름> user=default status=ok`가 한 줄 남는다.

### 연결이 안 될 때(운영자)

서버에서 로그를 본다. 토큰·본문은 로그에 없다. 도구 인자(장 번호 등)도 남기지 않는다(로그 원칙).
어떤 장을 읽었는지는 Claude 대화창의 도구 호출을 펼쳐 보면 보인다.

```sh
cd /opt/magus/deploy && sudo docker compose logs --since 30m magus | grep -E "auth=|tool="
```

| 로그 | 뜻 | 조치 |
|---|---|---|
| `auth=invalid reason=iss 불일치 (토큰 iss=…, 기대=…)` | 토큰의 issuer가 `AUTH_ISSUER`와 다르다 | 같은 WorkOS 환경(Staging)인지, 끝의 `/` |
| `auth=invalid reason=aud 불일치 (토큰 aud=…, 기대=…)` | 토큰의 aud가 `PUBLIC_URL/mcp` 하나가 아니다(다른 주소, 또는 다른 주소가 섞인 목록) | WorkOS에 등록한 리소스 주소가 `PUBLIC_URL/mcp`와 글자까지 같은지 확인한다. `AUTH_AUDIENCE`로 받는 aud를 늘리지 않는다(같은 WorkOS 환경의 다른 서비스 토큰이 통과한다. 결정 #79) |
| `auth=invalid reason=만료` / `서명` / `서명 키(kid) 없음…` | 만료, 키 불일치 | 다시 연결. 계속되면 `AUTH_JWKS_URL` |
| `auth=forbidden sub_hash=…` | 토큰은 유효하지만 허용 목록 밖이다 | 웹 `/login`의 403 화면에서 id를 보고 `ALLOWED_USERS`에 넣는다 |
| `tool=… status=ok` | 도구 호출 성공 | — |
| (아무것도 없음) | 토큰이 서버까지 오지 않았다. WorkOS 단계(CIMD·리디렉션·동의)에서 멈췄다 | WorkOS 대시보드의 로그, Claude 화면의 오류 문구 |

### 생각·문체 휴지통(운영자)

지우지 않고 `data/users/<user_id>/trash/shelf/`로 옮긴다(#88). 검색·목록·웹 화면에서 빠지고 되살릴 수 있다. 저자는 Claude에게 지우라고 말하면 된다(idea_delete·style_delete).

```sh
cd /opt/magus/deploy
sudo docker compose exec -T -e USER_ID=<user_id> magus /app/.venv/bin/magus trash list </dev/null
sudo docker compose exec -T -e USER_ID=<user_id> magus /app/.venv/bin/magus trash put idea <id> --note "이유" </dev/null
sudo docker compose exec -T -e USER_ID=<user_id> magus /app/.venv/bin/magus trash restore idea <id> </dev/null
```

생각을 옮기면 그 생각에 응답한 AI 발화(`parent_id`가 그 id)도 함께 옮기고, 되살리면 함께 돌아온다.

## 아버지용

1. 컴퓨터에서 claude.ai에 로그인한다.
2. 왼쪽 아래 이름 → **설정** → **커넥터** → **커스텀 커넥터 추가**를 누른다.
3. 이름에 `Magus`, 주소에 `https://magus.lifebookapplication.com/mcp`를 넣는다. 아래 칸들은 저절로 채워진다("지금 로그인", "Claude의 게시된 ID 사용"). 그대로 둔다.
4. **연결**을 누르면 로그인 화면이 나온다. 운영자가 등록해 둔 이메일 주소를 넣고, 메일로 온 코드를 입력한다.
5. 대화창 아래 **도구 메뉴에서 Magus를 켠다.**
6. 휴대폰 Claude 앱에서는 따로 할 일이 없다. 컴퓨터에서 연결한 것이 그대로 보인다.
7. 새 대화에서 이렇게 말해 본다.
   - "전체 보여 줘" → 목차와 미확인 문헌 수가 나온다
   - "제12장 인용 중 확인 안 된 것 알려줘" → 문헌 목록이 나온다
   - "생각에 기록해 줘: …" → "기록함"이 나온다(어디에 넣을지 말하지 않고 "기록해 줘"라고만 하면 Claude가 생각·문체·문헌 중 어디인지 묻는다)

파일(원고 docx, 논문 PDF)은 브라우저에서 `https://magus.lifebookapplication.com/inbox`에 올린다. 같은 이메일로 로그인한다.
