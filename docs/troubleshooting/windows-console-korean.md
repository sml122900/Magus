# Windows 콘솔에서 한글 출력이 깨짐 (서버 stdio는 이상 없음)

- 날짜: 2026-10-03
- 단계: 1단계 테스트·디버깅 중

## 문제상황

- Git Bash에서 pytest와 디버그 스크립트를 실행하면, 실패 메시지의 한글이 `��`처럼 깨져 나왔다. 예: `assert text.count("### ��") == 8`. 그래서 outline 실패 원인을 출력만 보고는 읽을 수 없었다.
- 원인: 출력이 파이프로 넘어갈 때 Python이 로캘 인코딩(cp949)으로 stdout을 쓴다. 이 출력을 UTF-8로 읽는 쪽에서 깨진다.
- 걱정했던 것: MCP 서버의 stdio도 Windows에서 같은 문제를 겪으면, Claude Desktop에 한글 원고가 깨진 채 전달된다.

## 시도한 것들

1. 디버그 실행에 `PYTHONIOENCODING=utf-8`을 붙였다. 콘솔에서 한글이 정상으로 보였다. 이렇게 확인한 실제 원인은 테스트 산식 오류였다(35장을 5장씩 나눠 부가 7개로 계산됨).
2. 서버 쪽은 SDK 코드(`mcp/server/stdio.py`)를 확인했다. SDK가 stdin/stdout의 바이너리 버퍼를 UTF-8 `TextIOWrapper`로 다시 감싼다("std handles' platform encodings are unreliable" 주석). 그래서 콘솔 로캘의 영향을 받지 않는다.
3. 추측에 머물지 않으려고 실제 경로를 테스트로 만들었다. `tests/test_stdio.py`는 `python -m magus serve`를 하위 프로세스로 띄워 stdio로 연결하고, 한글 outline("# 데모: 물에서 뭍으로", "물가의 망설임")을 그대로 받는지 확인한다.

## 최종 해결법

- **서버 stdio**: 문제가 없다. SDK가 UTF-8을 강제한다. 회귀를 막기 위해 `test_stdio.py`를 상시 테스트로 둔다.
- **개발 콘솔**: 한글 출력을 사람이 읽어야 할 때는 `PYTHONIOENCODING=utf-8`을 붙여 실행한다. 예: `PYTHONIOENCODING=utf-8 .venv/Scripts/magus.exe seed-demo`. status.md 환경 메모에도 적었다.
- 서버 로그는 stdout을 오염시키지 않도록 모두 stderr로 보낸다(`cli.py`의 `logging.basicConfig(stream=sys.stderr)`).

## 이력서 소재 한 줄

Windows의 cp949 콘솔과 UTF-8 MCP stdio를 구분해 진단하고, 하위 프로세스 stdio 통합 테스트로 한글 전송 경로를 회귀 테스트에 고정했다.
