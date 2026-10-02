# Magus

책을 쓰는 사람의 세 책장을 Claude에게 MCP로 열어 주는 서버입니다.

- **Casper · 몰약**: 영감. 내가 한 말과 AI가 한 말을 구분해 보존합니다.
- **Melchior · 황금**: 문헌. 검증된(verified) 출처만 인용할 수 있습니다.
- **Balthasar · 유향**: 문체. 내 취향을 근거와 함께 기록합니다.
- **book**: 원고. 장 단위로 저장하고, 버전을 남기고, 결정과 미해결 사항을 기록합니다.

세 현자는 토론하지 않습니다. 선물을 바칠 뿐이고, 받고 결정하는 것은 저자입니다.

## 설치

```
uv sync
uv run pytest
```

### uv가 PATH에 없을 때

`pip install --user uv`로 설치하면 uv.exe가 PATH에 없는 user Scripts 폴더에 놓입니다. 이때는 전체 경로로 실행하세요.

```powershell
# PowerShell
& "$env:APPDATA\Python\Python313\Scripts\uv.exe" sync
& "$env:APPDATA\Python\Python313\Scripts\uv.exe" run pytest
```

```bash
# Git Bash
UV=~/AppData/Roaming/Python/Python313/Scripts/uv.exe
$UV sync && $UV run pytest
```

uv는 설치와 테스트에만 씁니다. 서버는 `uv sync`로 만들어진 `.venv\Scripts\magus.exe`를 직접 실행하므로, Claude Desktop 설정에는 uv가 필요 없습니다.

## Claude Desktop 연결

Claude Desktop에서 **설정 → 개발자 → 구성 편집**을 누르면 `claude_desktop_config.json`이 열립니다.
`mcpServers`에 아래 항목을 추가하세요. 경로는 리포 위치에 맞게 바꿉니다.

```json
{
  "mcpServers": {
    "magus": {
      "command": "C:\\project_2026\\Magus\\.venv\\Scripts\\magus.exe",
      "args": ["serve"],
      "env": {
        "USER_ID": "default",
        "DATA_DIR": "C:\\project_2026\\Magus\\data",
        "EMBEDDINGS": "none"
      }
    }
  }
}
```

macOS나 Linux에서는 `command`를 `.venv/bin/magus`로 바꿉니다.
`"command": "uv", "args": ["--directory", "<리포 경로>", "run", "magus", "serve"]` 형태로도 실행할 수 있습니다.

저장한 뒤 Claude Desktop을 **완전히 종료**하고(트레이 아이콘 → 종료) 다시 실행하세요.

## 환경변수

| 변수 | 기본값 | 설명 |
|---|---|---|
| `USER_ID` | `default` | 사용자 id |
| `DATA_DIR` | `./data` | 원본 파일과 인덱스(index.sqlite)를 두는 위치 |
| `EMBEDDINGS` | `none` | `none` \| `voyage` \| `openai` |
| `VOYAGE_API_KEY` / `OPENAI_API_KEY` | — | 임베딩 제공자를 쓸 때만 필요합니다 |

## 명령

```
uv run magus serve        # MCP 서버(stdio). Claude Desktop이 실행합니다.
uv run magus seed-demo    # 확인용 가짜 프로젝트를 만듭니다.
uv run magus reindex      # 원본 파일로 index.sqlite를 다시 만듭니다. ch-NN.md를 직접 고친 뒤에 실행하세요.
```

## 데이터

원본은 모두 `DATA_DIR` 아래에 사람이 읽을 수 있는 파일로 저장됩니다. `index.sqlite`는 이 파일들로 언제든 다시 만들 수 있습니다.

```
data/users/<user_id>/projects/<project_id>/book/ch-01.md …   장 본문(front matter + markdown)
data/users/<user_id>/projects/<project_id>/versions/          이전 버전
data/users/<user_id>/projects/<project_id>/decisions.md       결정
data/users/<user_id>/projects/<project_id>/issues.md          미해결
data/users/<user_id>/shelf/{casper,melchior,balthasar}/       세 책장
```
