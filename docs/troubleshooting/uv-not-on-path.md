# uv가 없고, 설치한 뒤에도 PATH에 잡히지 않음

- 날짜: 2026-10-03
- 단계: 1단계 착수 시점

## 문제상황

- 스택이 uv를 요구했는데, 이 PC(Windows 11)에는 uv가 없었다. `which uv` 결과가 비어 있었다.
- `python -m pip install --user uv`로 설치했다. 그런데 실행 파일이 `%APPDATA%\Python\Python313\Scripts\uv.exe`에 놓였고, 이 폴더는 PATH에 없었다. 그래서 `uv` 명령은 여전히 `command not found`였다.
- 참고: PC에는 Python 3.13(기본)과 3.12(`py -3.12`)가 함께 있다. 프로젝트는 3.12가 필요하다.

## 시도한 것들

1. `which uv` / `uv --version`: 실패. 설치되어 있지 않았다.
2. `python -m pip install --user uv`: 설치는 됐지만 user Scripts 폴더가 PATH에 없어서 바로 실행되지 않았다.
3. 전체 경로로 `uv.exe --version`을 실행했다: `uv 0.12.22`로 정상 동작했다.

## 최종 해결법

- 개발 중에는 uv를 전체 경로로 실행한다. Bash에서는 `~/AppData/Roaming/Python/Python313/Scripts/uv.exe`, PowerShell에서는 `& "$env:APPDATA\Python\Python313\Scripts\uv.exe"`.
- `uv init --lib --python 3.12`로 `.python-version=3.12`를 고정했다. 그래서 uv가 3.12로 `.venv`를 만든다.
- **실행 경로가 uv에 의존하지 않게 했다.** Claude Desktop 설정은 `uv run` 대신 `.venv\Scripts\magus.exe serve`를 직접 실행한다. PATH와 uv 위치에 상관없이 서버가 뜨고, 시작도 빠르다.
- 영구적으로 해결하려면 두 방법 중 하나를 쓴다. user Scripts 폴더를 PATH에 추가하거나, 공식 설치 스크립트(`irm https://astral.sh/uv/install.ps1 | iex`)를 쓰면 이미 PATH에 있는 `~/.local/bin`에 설치된다. 이 결정은 사용자에게 맡겼다.

## 이력서 소재 한 줄

개발 도구가 PATH에 잡히지 않는 Windows 환경에서, 서버 실행 경로를 venv 진입점으로 고정해 런타임이 빌드 도구에 의존하지 않게 했다.
