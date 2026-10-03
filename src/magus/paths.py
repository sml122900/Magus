"""도구가 받은 파일 경로를 푼다.

Claude Desktop은 서버를 어느 작업 폴더에서 띄우는지 정해 두지 않는다. 그래서 "fixtures/papers/논문.pdf" 같은
상대 경로는 작업 폴더가 아니라 FILES_DIR(기본: DATA_DIR의 부모 = 프로젝트 폴더) 기준으로 푼다.
"""

from __future__ import annotations

from pathlib import Path


def resolve_input(path: str, root: Path | None) -> Path:
    """절대 경로는 그대로, 상대 경로는 root 기준. 없으면 FileNotFoundError(어디를 찾았는지 함께)."""
    raw = Path(path.strip().strip("\"'")).expanduser()
    resolved = (raw if raw.is_absolute() else (root or Path.cwd()) / raw).resolve()
    if not resolved.is_file():
        where = "" if raw.is_absolute() else f" (상대 경로는 {root or Path.cwd()} 기준으로 푼다)"
        raise FileNotFoundError(f"파일이 없다: {resolved}{where}")
    return resolved
