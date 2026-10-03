# Desktop에서 상대 경로가 엉뚱한 곳을 가리킴 (fixtures/papers/…)

- 날짜: 2026-10-03 (P0 마무리 라운드)

## 문제상황

- README에 "fixtures/papers/<파일>.pdf를 문헌으로 등록해 줘"라는 ref_add 시연을 적으려 했다. 이 말을 들은 Claude는 `file_path="fixtures/papers/<파일>.pdf"`처럼 상대 경로를 그대로 넘긴다.
- 서버는 `Path(file_path).expanduser()`로 열었다. 그래서 상대 경로가 **서버 프로세스의 작업 폴더** 기준으로 풀렸다.
- Claude Desktop은 MCP 서버를 어느 작업 폴더에서 띄울지 설정으로 정해 두지 않는다. 설정에는 command·args·env만 있다.
  - 테스트와 CLI는 프로젝트 루트에서 돌기 때문에 이 문제가 드러나지 않았다.
- book_import(path)와 idea_add_conversation(path)도 같은 구조였다.

## 시도한 것들

1. Desktop 로그에서 실제 작업 폴더를 확인하려 했다. 그런데 로그는 프로젝트 폴더 밖에 있고, 이번 라운드 규칙상 사용자가 지시하지 않은 파일은 읽지 않는다. 대신 서버 시작 로그에 files_root를 찍게 했다. 다음 실행부터는 사용자가 볼 수 있다.
2. 기준 후보를 비교했다.
   - 작업 폴더: 정해져 있지 않다.
   - DATA_DIR: 사용자가 말하는 `fixtures/…`는 data 안에 없다.
   - DATA_DIR의 부모: Desktop 설정의 `DATA_DIR=C:\project_2026\Magus\data`에서 자연스럽게 프로젝트 폴더가 나온다.
3. 같은 시연에서 두 번째 문제가 보였다. 사용자는 "이 PDF를 등록해 줘"라고만 하고 저자·연도를 말하지 않는다. 그러면 bib에서 key를 만들 수 없어 ref_add가 실패한다.
   - 그런데 참고문헌 299편이 이미 unverified로 들어 있다. PDF 첫머리에 제목이 있으니, 그것으로 찾으면 된다.

## 최종 해결법

- `magus/paths.py`의 `resolve_input(path, root)`
  - 절대 경로는 그대로 쓰고, 상대 경로는 `FILES_DIR`(기본 `DATA_DIR`의 부모) 기준으로 푼다.
  - 파일이 없으면 어디를 찾았는지와 기준 폴더를 오류에 함께 적는다.
- ref_add·book_import·idea_add_conversation이 모두 이 함수를 쓴다. `Settings.files_root`를 build_tools로 넘긴다.
- ref_add는 key도 저자·연도도 없으면 제목으로 찾는다(`refs.key_by_title`).
  - bib 제목이나 전문 첫머리 5,000자를 정규화하고, 그 안에 12자 이상의 참고문헌 제목이 그대로 들어 있는 문헌을 찾는다.
  - 하나일 때만 고르고, 여럿이면 key를 달라고 한다.
- 검증
  - `tests/test_stdio.py::test_relative_file_path_from_other_cwd`: 다른 작업 폴더에서 서버를 하위 프로세스로 띄우고, `bib={}`와 상대 경로로 PDF를 등록한다.
  - 실데이터 사본에 제목만 적힌 PDF로 리허설했다: kremer1993이 verified로 바뀌고, 인용 장은 30·32·35장이다.
- 교훈: Desktop처럼 남이 띄우는 프로세스에서는 작업 폴더를 가정하면 안 된다. 테스트도 일부러 다른 작업 폴더에서 띄워야 드러난다.

## 이력서 소재 한 줄

MCP 서버가 클라이언트(Desktop)가 정하지 않은 작업 폴더에서 실행된다는 점을 짚어 상대 경로 기준을 설정값으로 고정하고, 다른 작업 폴더에서 하위 프로세스를 띄우는 회귀 테스트로 확인했다.
