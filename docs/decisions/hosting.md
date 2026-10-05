# 호스팅·백업·알림: Vultr 서울 VPS + Docker Compose + Caddy, restic → Cloudflare R2, 텔레그램 + healthchecks.io

- 날짜: 2026-10-03 (P1 5단계 준비)
- 코드·설정: `Dockerfile`, `deploy/compose.yaml`, `deploy/Caddyfile`, `deploy/backup.sh`, `deploy/restore-test.sh`, `deploy/.env.example`, `src/magus/alerts.py`
- 운영 절차: [docs/deploy.md](../deploy.md)
- 조사 기준일: 2026-10-03. 웹 조사 결과이고, 가격은 각 서비스 문서 기준이다. 확인하지 못한 것은 "미확인"으로 적었다.

## Problem

- 두 사람(한국)이 쓰는 원격 MCP 서버를 둘 곳을 정해야 한다.
  - 상태는 파일과 SQLite 인덱스이고, 수백 MB 이하다(실데이터 53MB).
  - 영구 디스크가 있는 단일 인스턴스여야 한다. 서버리스·Vercel은 금지다.
  - HTTPS가 필요하고, 한국에서 가까워야 하고, 싸야 한다.
- data/ 전체를 매일 객체 스토리지에 스냅샷하고 30일 보관한다. 복구 절차를 문서로 두고, 실제로 한 번 복구해 본다.
- 오류가 나면 운영자에게 이메일이나 메신저로 알린다.

## Action

### 호스팅 비교

| | 한국에서 가장 가까운 곳 | 최소 구성 + 1~3GB 디스크 | 무료·체험 | 디스크 주의점 | 도메인·TLS / 배포 | 프록시 제한 |
|---|---|---|---|---|---|---|
| Fly.io | 도쿄(nrt), 서울 없음 | 512MB 머신 $3.69 × 도쿄 1.308 ≈ $4.83 + 볼륨 $0.15/GB → 약 $5(볼륨에도 지역 가산이 붙는지는 미확인) | 무료 없음, 체험 2시간 또는 7일 | 볼륨이 서버 한 대·머신 하나에 묶이고 복제가 없다. 스냅샷 5일 | `fly certs`, Dockerfile, `fly secrets` | 무데이터 60초 끊김(설정으로 바꿀 수 있다) |
| Railway | 싱가포르 | Hobby 월 $5(사용료 $5 포함) | 일회 $5 | 서비스당 볼륨 하나, 재배포 때 잠깐 끊김. Hobby 볼륨 최대 5GB, 백업 6일 | 자동 TLS, Dockerfile | **요청 최대 15분, 무데이터 5분** |
| **Vultr** | **서울(icn)** | **1 vCPU·1GB·25GB SSD $5.00**(공식 plans API) | 없음 | 디스크는 VM 자체(직접 관리). 자동 백업 +20% | Caddy 자동 HTTPS, Docker Compose | 제한 없음 |
| AWS Lightsail | 서울 | $5(0.5GB) / $7(1GB) | $5·$7·$12 번들 3개월 무료 | 일일 스냅샷 7개, $0.05/GB | Caddy | 제한 없음 |
| Hetzner | 싱가포르 | 싱가포르 CPX12 €15.49 + IPv4 €0.50(2026-06 인상 후) | 없음 | 백업 +20% | Caddy | 제한 없음 |
| Oracle Always Free | 서울·춘천 | $0(Arm 할당 2026-06에 절반) | 상시 무료 | **7일 동안 놀면 회수될 수 있다**(MCP 서버는 한가해 보인다), 용량 보장 없음 | Caddy | 제한 없음 |

### 객체 스토리지 비교

| | 무료 | GB·월 | 내려받기 비용 | S3 호환·보관 규칙 |
|---|---|---|---|---|
| **Cloudflare R2** | 10GB·월, A 100만·B 1,000만 회 | $0.015 | 무료 | S3 API, 수명 주기 규칙, 버킷 잠금 |
| Backblaze B2 | 처음 10GB | 약 $0.007 | 저장량 3배까지 무료 | S3 API·Object Lock, **아시아 리전 없음** |
| AWS S3 서울 | 신규 크레딧 | 약 $0.025(미확인, 제3자) | 월 100GB 무료 | 수명 주기·Object Lock |

### 선택

- **호스팅: Vultr 서울 `vc2-1c-1gb`($5/월)**
  - Docker Compose로 magus와 Caddy를 띄운다. Caddy가 Let's Encrypt로 HTTPS를 자동으로 붙인다.
  - 한국 지연이 가장 작다. 영구 디스크가 VM 자체라 볼륨 제약이 없다. 프록시가 없어 스트림·업로드 시간 제한도 없다.
  - DNS를 Cloudflare에 두면 **프록시를 끈 DNS 전용**으로 둔다. 무료 프록시는 응답을 125초에 끊는다.
- **백업: restic → Cloudflare R2**(APAC 위치 힌트)
  - 매일 04:00 KST에 호스트 cron이 `docker compose --profile backup run --rm backup`을 부른다(`deploy/backup.sh`).
  - restic은 암호화하고 중복을 없애고 증분으로 올린다. 그래서 일별 30개에 월별 12개를 더해도 R2 무료 10GB 안에 들어간다(첫 스냅샷 7.7MiB).
  - 보관은 `restic forget --keep-daily 30 --keep-monthly 12 --prune`이다.
    - 처음에는 일별 30개만 두었다. 2026-10-05 사용자 결정(#62 보완)으로 월별 12개를 더했다.
    - 30일이 지나서야 손상을 발견해도, 최대 1년 전까지 각 달 말 상태로 되돌릴 수 있게 하기 위해서다.
  - **R2 버킷에 수명 주기 규칙을 걸지 않는다.** 스냅샷끼리 데이터 파일을 나눠 쓰므로, 날짜로 지우면 새 스냅샷이 깨진다.
  - `index.sqlite`는 백업에서 뺀다. 원본 파일에서 `magus reindex`로 다시 만들기 때문에, 실행 중인 DB의 일관성 문제가 생기지 않는다. 임베딩은 EMBEDDINGS=none이라 다시 받을 것도 없다.
  - 매번 `restic check --read-data-subset=1/30`로 데이터의 1/30을 읽어 검사한다(한 달이면 전체).
- **알림**
  - 서버 오류(ERROR 로그)는 텔레그램 봇으로 보낸다(`magus/alerts.py`, 웹훅도 지원). 내용은 logsafe가 거른 종류·위치뿐이다.
  - 백업이 안 돌면 healthchecks.io(무료 20개)가 알린다. 핑이 오지 않거나 `/fail`이 오면 운영자에게 텔레그램으로 간다.
- **예상 비용**: VM $5 + 도메인. R2·알림은 무료 한도 안이다. Vultr 자동 백업(+$1)은 선택이다.

## Result

- **로컬 복구 훈련(2026-10-03, Docker, restic 공식 이미지, 로컬 저장소)**
  - 실데이터 사본 53.4MB를 `deploy/backup.sh`로 그대로 백업했다: 34초, 스냅샷 50.3MiB(index 제외), `restic check` 오류 없음.
  - `restic restore latest`로 2,396개 파일·디렉터리를 복구했다. 복구본에 index.sqlite는 없다.
  - magus 이미지에서 `magus reindex` 뒤 `magus outline --project-id book`(default 사용자)을 원본 사본과 비교했다: **66줄 모두 같다.** 첫 두 줄은 다음과 같다.
    - `프로젝트: 닿으려는 종 (book)`
    - `35장 + 서장·맺음·부록 1~3 · 8부 · 249,065자 · 미확인 문헌 297편 · 미연결 0 · 열린 미해결 86`
  - 사본·저장소·이미지는 훈련 뒤 지웠다.
- 같은 원리를 `tests/test_restore.py`로 고정했다(파일만 복구 → reindex → outline·ref_check·받은함이 같다).
- **컨테이너 원격 모드 점검**: `/healthz` ok, PRM의 resource = `PUBLIC_URL/mcp`, 토큰 없이 `/mcp` → 401, 실행 사용자 uid 10001(비root), Docker 헬스체크 healthy.
- **아직 못 한 것(사용자 계정 필요)**: 실제 VPS·도메인·HTTPS 발급, R2 백업, 서버에서의 복구 시험(`deploy/restore-test.sh`), 텔레그램 실제 수신. 절차는 docs/deploy.md에 있다.

## 위험

- VM 한 대·디스크 하나라 최대 24시간치를 잃을 수 있다. 줄이려면 백업을 더 자주 돌리거나 Vultr 자동 백업을 켠다.
- OS 패치와 SSH 보안은 운영자 몫이다(docs/deploy.md 체크리스트).
- **restic 비밀번호나 R2 키를 잃으면 백업을 읽을 수 없다.** 비밀번호 관리자에 따로 보관한다.
- 메모리 1GB는 pandoc·PDF 임포트에 빠듯할 수 있다. 스왑 1GB를 둔다.

**대안을 버린 이유**: Fly.io는 서울 리전이 없고 볼륨이 머신 하나에 묶이며 무료가 없다. Railway는 싱가포르뿐이고 요청 시간 제한이 있다. Hetzner는 아시아가 비싸다. Oracle 무료는 한가하면 회수될 수 있다. Lightsail($7, 3개월 무료)은 차선이다.

## 출처

- Fly.io: https://docs.fly.io/about/pricing · https://docs.fly.io/volumes/overview · https://docs.fly.io/reference/regions
- Railway: https://docs.railway.com/reference/pricing/plans · https://docs.railway.com/volumes/reference · https://docs.railway.com/networking/public-networking/specs-and-limits
- Vultr: https://api.vultr.com/v2/plans?type=vc2
- Lightsail: https://aws.amazon.com/lightsail/pricing/
- Hetzner: https://docs.hetzner.com/general/infrastructure-and-availability/price-adjustment/
- Oracle: https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm
- R2: https://developers.cloudflare.com/r2/pricing/ · https://developers.cloudflare.com/fundamentals/reference/connection-limits/
- B2: https://www.backblaze.com/cloud-storage/pricing
- restic: https://restic.readthedocs.io/en/stable/060_forget.html · SQLite: https://www.sqlite.org/lang_vacuum.html · Caddy: https://caddyserver.com/docs/automatic-https
- 알림: https://core.telegram.org/bots/faq · https://healthchecks.io/pricing/
