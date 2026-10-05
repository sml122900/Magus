# Claude에 Magus 연결하기

> 2026-10-05 구성 기준이다(WorkOS **Staging**, CIMD·DCR 켬). 화면 이름은 Claude 도움말을 따랐다. 사용자의 첫 등록(6단계) 결과로 실제 화면과 다른 곳을 고친다.

- 커넥터 URL: **`https://magus.lifebookapplication.com/mcp`**
- 인증 서버: WorkOS AuthKit Staging `https://dapper-palace-57-staging.authkit.app`(PRM이 알려 주므로 Claude에 따로 넣지 않는다)

## 운영자가 미리 할 일

- [x] 서버 주소가 열려 있다: `https://magus.lifebookapplication.com/healthz` → ok(2026-10-05)
- [x] 운영자 본인이 `ALLOWED_USERS`에 `=default`로 들어 있다. 웹 `/login` → `/book`으로 확인했다(2026-10-05). 아버지는 7단계에서 `=father`로 추가한다([onboarding-father.md](onboarding-father.md)).
- [x] WorkOS(Staging) 설정
  - Magic Auth(메일 코드) 켬, 비밀번호 끔, 가입 끔(사용자는 운영자가 대시보드에서 만든다)
  - CIMD·DCR 켬
  - 리소스 `https://magus.lifebookapplication.com/mcp`(Default). 토큰의 aud가 이 값이어야 한다.

---

## 사용자용(개발자)

1. claude.ai(웹) → 설정 → 커넥터 → **커스텀 커넥터 추가**
2. 이름 `Magus`, URL `https://magus.lifebookapplication.com/mcp`
3. **고급 설정의 OAuth Client ID·Client Secret은 비워 둔다.**
   - WorkOS가 CIMD와 DCR을 모두 지원하므로 Claude가 스스로 클라이언트를 등록한다.
   - 등록 방식을 고르는 칸이 있으면 **"Claude의 공개 신원 사용"(CIMD)**을 고른다. 연결한 뒤에는 바꿀 수 없다(바꾸려면 지우고 다시 추가한다).
   - 웹 로그인용 클라이언트(`client_01M45…`)는 서버의 `/login` 전용이다. 여기에 넣지 않는다.
4. **연결** → WorkOS 로그인 화면 → 이메일 → 메일로 온 코드 → (동의 화면이 나오면 허용) → Claude로 돌아온다.
5. 새 대화에서 확인한다(웹, 그다음 모바일 앱에서 같은 것).
   - "Magus의 book_outline을 호출해 줘"
     - 첫 줄 `프로젝트: 닿으려는 종 (book)`
     - 둘째 줄 `35장 + 서장·맺음·부록 1~3 · 8부 · …`
   - "idea_add로 '연결 시험 메모'를 기록해 줘" → `기록함 [me] <id> · thought`
     - 서버의 default는 실제 원고 사본이다. **시험 메모는 확인한 뒤 운영자가 지운다**(서버에서 `data/users/default/shelf/casper/<id>.json` 삭제 → `magus reindex`).
     - 진짜 떠오른 생각을 기록하면 지우지 않아도 된다.
   - "ref_search로 '인구'를 찾아 줘" → verified 문헌이 아직 없으므로 `결과 없음. verified 문헌의 발췌·전문에서만 찾는다.`가 정상이다.
6. 모바일: 같은 계정의 Claude 앱에서는 웹에서 추가한 커넥터가 그대로 보인다. 5의 세 가지를 다시 해 본다.
7. **토큰 갱신 확인**(알려진 위험): 다음 날 같은 대화에서 다시 불러 본다. 로그인을 다시 하라고 하면 기록한다.

### 연결이 안 될 때(운영자)

서버에서 로그를 본다. 토큰·본문은 로그에 없다.

```sh
cd /opt/magus/deploy && sudo docker compose logs --since 30m magus | grep -E "auth=|tool="
```

| 로그 | 뜻 | 조치 |
|---|---|---|
| `auth=invalid reason=iss 불일치 (토큰 iss=…, 기대=…)` | 토큰의 issuer가 `AUTH_ISSUER`와 다르다 | 같은 WorkOS 환경(Staging)인지, 끝의 `/` |
| `auth=invalid reason=aud 불일치 (토큰 aud=…, 기대=…)` | 토큰의 aud가 `PUBLIC_URL/mcp`가 아니다 | WorkOS 리소스 설정. 필요하면 `AUTH_AUDIENCE`에 실제 aud를 더한다 |
| `auth=invalid reason=만료` / `서명` / `서명 키(kid) 없음…` | 만료, 키 불일치 | 다시 연결. 계속되면 `AUTH_JWKS_URL` |
| `auth=forbidden sub_hash=…` | 토큰은 유효하지만 허용 목록 밖이다 | 웹 `/login`의 403 화면에서 id를 보고 `ALLOWED_USERS`에 넣는다 |
| `tool=… status=ok` | 도구 호출 성공 | — |
| (아무것도 없음) | 토큰이 서버까지 오지 않았다. WorkOS 단계(CIMD·리디렉션·동의)에서 멈췄다 | WorkOS 대시보드의 로그, Claude 화면의 오류 문구 |

## 아버지용

1. 컴퓨터에서 claude.ai에 로그인한다.
2. 왼쪽 아래 이름 → **설정** → **커넥터** → **커스텀 커넥터 추가**를 누른다.
3. 이름에 `Magus`, 주소에 `https://magus.lifebookapplication.com/mcp`를 넣고 **추가**를 누른다. 나머지 칸(고급 설정)은 그대로 둔다.
4. **연결**을 누르면 로그인 화면이 나온다. 운영자가 등록해 둔 이메일 주소를 넣고, 메일로 온 코드를 입력한다.
5. 휴대폰 Claude 앱에서는 따로 할 일이 없다. 컴퓨터에서 연결한 것이 그대로 보인다.
6. 새 대화에서 이렇게 말해 본다.
   - "책 지도를 보여 줘" → 목차와 미확인 문헌 수가 나온다
   - "제12장 인용 중 확인 안 된 것 알려줘" → 문헌 목록이 나온다
   - "오늘 떠오른 생각을 기록해 줘: …" → "기록함"이 나온다

파일(원고 docx, 논문 PDF)은 브라우저에서 `https://magus.lifebookapplication.com/inbox`에 올린다. 같은 이메일로 로그인한다.
