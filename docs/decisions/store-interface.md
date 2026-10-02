# Store 인터페이스: 파일 우선 쓰기와 인덱스 재생성

- 날짜: 2026-10-03
- 단계: 1단계(뼈대)
- 코드: `src/magus/store/base.py`, `src/magus/store/local.py`, `src/magus/store/schema.py`

## Problem

- 동기가 된 사례에서 원고가 두 파일로 갈라졌고, 단일 진실 원천이 없었다. 저자가 직접 읽고 고칠 수 있는 원본이 필요하다.
- 제약 1: 원본은 사람이 읽을 수 있는 파일(markdown/json)이어야 한다. SQLite는 인덱스이고, 인덱스는 언제든 파일에서 다시 만들 수 있어야 한다.
- 제약 2: SaaS 전환을 대비해야 한다. 모든 레코드에 user_id가 있어야 하고, 단일 사용자를 가정하지 않으며, P1에서 Postgres + 객체 스토리지로 바꿀 수 있어야 한다.
- 제약 3: MCPServer는 동기 도구를 워커 스레드에서 실행한다. 파일과 인덱스를 함께 갱신하는 작업이 서로 끼어들면 안 된다.

## Action

- `Store`를 `typing.Protocol`로 정의했다(`store/base.py`). 모든 메서드가 `user_id`를 첫 인자로 받는다. 저장소는 "현재 사용자"를 모르고, user_id를 정하는 곳은 서버의 `current_user()` 한 군데뿐이다.
- P0 구현 `LocalStore`의 규칙
  - **파일을 먼저 쓰고 인덱스를 나중에 쓴다.** 파일은 임시 파일에 쓴 뒤 `os.replace`로 교체한다. 그래서 원본이 반쯤 쓰인 상태로 남지 않는다.
  - 장을 덮어쓰기 전에는 직전 파일을 front matter째 `versions/ch-NN.vK.md`로 복사한다. 사람이 파일을 직접 고친 경우에도 그 내용이 보존된다.
  - `reindex()`: 테이블을 모두 지우고, `users/*/projects/*`를 훑어 인덱스를 다시 만든다.
  - 스키마를 바꿀 때는 `SCHEMA_VERSION`을 올린다. 시작 시 `PRAGMA user_version`이 다르면 자동으로 `reindex()`가 돈다. 그래서 마이그레이션 코드가 필요 없다.
  - 모든 테이블에 `user_id` 열이 있고, 모든 쿼리를 `user_id`로 필터한다.
  - 공개 메서드는 `RLock`으로 감쌌고, SQLite는 `check_same_thread=False`로 연다.
  - 결정·미해결 번호(`D3`, `I3`)는 파일에 적힌다. 재생성해도 사용자가 보던 번호가 바뀌지 않는다.
  - **한 번 준 번호는 다시 쓰지 않는다**(1단계 검토 반영). 마지막 번호를 `project.json`의 `last_decision_id`/`last_issue_id`에 남긴다. 그래서 사람이 md에서 마지막 항목을 지워도 다음 번호가 앞당겨지지 않는다. 새 번호는 max(기록된 마지막 번호, 파일의 최대 번호) + 1이다.
- 비교한 대안
  - **SQLite를 원본으로 두고 파일로 내보내기**: 사람이 파일을 고치면 반영할 경로가 없다. 원칙("원본은 파일")에도 어긋난다.
  - **파일만 쓰고 인덱스 없음**: 장 목록 정도는 충분하다. 하지만 FTS5 검색과 벡터 BLOB을 붙일 곳이 없다.
  - **처음부터 Postgres**: P0는 단일 사용자 로컬 도구다. 설치 부담만 늘고, 인터페이스 분리만으로도 P1 전환 준비가 된다.

## Result

- 테스트가 모두 통과한다(`uv run pytest`, 1단계 검토 반영 후 35개). 이 결정을 직접 검증하는 테스트:
  - `test_reindex_rebuilds_same_index`: reindex 전후로 프로젝트·부·장·결정·미해결·변경 이력 스냅샷이 같다.
  - `test_index_recreated_when_schema_version_changes`: 인덱스 행을 지우고 user_version을 바꾼 뒤 다시 열면, 파일에서 원래 상태로 복구된다.
  - `test_other_user_sees_nothing`: 다른 user_id로는 조회 결과가 비고, 쓰기는 거부된다.
  - `test_files_are_the_source`: 장, 이전 버전, decisions.md, issues.md가 사람이 읽을 수 있는 형태로 디스크에 있다.
  - `test_numbers_are_never_reused`: md에서 I3·D2를 지운 뒤 새로 추가하면 I4·D3이 나오고, reindex 뒤에도 [1, 2, 4]가 유지된다.
- 한계: 결정·미해결 번호 매기기는 프로세스 안의 락에만 보호된다. CLI와 서버가 동시에 쓰면 번호가 충돌할 수 있다(P0에서는 허용).

> 대안을 버린 이유: SQLite를 원본으로 두면 사람이 고친 파일이 반영되지 않고, 인덱스가 없으면 검색을 붙일 곳이 없다. 그래서 "파일이 원본, SQLite는 버려도 되는 인덱스"로 정했다.
