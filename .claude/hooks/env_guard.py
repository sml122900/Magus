""".env 보호 장치(PreToolUse 훅, 2026-10-09 사용자 지시). 셸 명령에 ".env"가 들어 있으면 막는다(종료 코드 2 + 이유).

예외는 정확히 두 꼴뿐이다(값을 읽지 않고 변수 이름 개수만 보거나, git이 무시하는지만 본다):
  grep -c '^이름=' <경로>/.env
  git check-ignore [-옵션…] <경로>/.env
cat·less·head·tail·type·Get-Content·python·powershell·source·길이·해시 명령은 모두 막힌다. 대소문자는 가리지 않는다(Windows는 .ENV도 같은 파일).
더해서: 재귀 grep(-r·-R·--recursive)·rg(-u·--no-ignore·--hidden)가 .env 파일이 든 폴더를 훑으면 막는다(감사 때 값이 찍힌 길).
입력 JSON을 읽지 못하면 막는다(실패하면 닫힘).
"""

from __future__ import annotations

import json
import os
import re
import shlex
import sys

PATH = r"[\w./:~\\-]*\.env"
ALLOWED = (
    re.compile(r"grep\s+-c\s+(['\"])\^[A-Za-z_][A-Za-z0-9_]*=\1\s+" + PATH),
    re.compile(r"git\s+check-ignore(?:\s+-{1,2}[a-z-]+)*(?:\s+" + PATH + r")+"),
)
WALK_LIMIT = 20_000  # 재귀 grep 대상 폴더를 이만큼만 훑는다. 넘으면 막는다(모르면 닫힘)
SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".pytest_cache", ".ruff_cache", ".worktrees"}


def block(reason: str) -> int:
    message = (f".env 보호 장치가 막았다: {reason}\n"
               ".env는 변수 이름 개수만 확인한다(grep -c '^이름=' <경로>/.env). 값을 읽는 명령은 하위 에이전트도 금지.\n")
    sys.stderr.buffer.write(message.encode("utf-8"))  # Windows 콘솔 코드 페이지와 상관없이 UTF-8
    sys.stderr.flush()
    return 2


def is_env_name(name: str) -> bool:
    low = name.lower()
    return (low == ".env" or low.startswith(".env.")) and low != ".env.example"


def holds_env(path: str) -> bool:
    """path가 .env 파일이거나 .env 파일을 품은 폴더면 True. 다 못 훑으면 True(닫힘)."""
    if os.path.isfile(path):
        return is_env_name(os.path.basename(path))
    if not os.path.isdir(path):
        return False
    seen = 0
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        seen += len(files) + len(dirs)
        if any(is_env_name(f) for f in files):
            return True
        if seen > WALK_LIMIT:
            return True
    return False


def recursive_targets(command: str) -> list[str] | None:
    """재귀로 훑는 grep·rg면 대상 경로 목록(없으면 ['.']), 아니면 None."""
    try:
        words = shlex.split(command, posix=True)
    except ValueError:
        return None
    for i, word in enumerate(words):
        name = os.path.basename(word).lower().removesuffix(".exe")
        if name not in ("grep", "egrep", "rg"):
            continue
        rest = words[i + 1:]
        cut = next((j for j, w in enumerate(rest) if w in ("|", ";", "&&", "||")), len(rest))
        rest = rest[:cut]
        flags = [w for w in rest if w.startswith("-")]
        if name == "rg":
            deep = any(f in ("--no-ignore", "--hidden", "-u", "-uu", "-uuu") or re.fullmatch(r"-[a-zA-Z]*u[a-zA-Z]*", f) for f in flags)
        else:
            deep = any(f in ("--recursive", "--dereference-recursive", "-d") or re.fullmatch(r"-[a-zA-Z]*[rR][a-zA-Z]*", f) for f in flags)
        if not deep:
            continue
        plain = [w for w in rest if not w.startswith("-")]
        pattern_given = any(f in ("-e", "--regexp") or f.startswith(("-e", "--regexp=", "-f", "--file=")) for f in flags)
        paths = plain if pattern_given else plain[1:]
        return paths or ["."]
    return None


def check(command: str, cwd: str) -> int:
    one = command.strip()
    if ".env" in one.lower():
        if "\n" not in one and any(p.fullmatch(one) for p in ALLOWED):
            return 0
        return block("명령에 .env가 들어 있다")
    targets = recursive_targets(one)
    if targets is not None:
        for t in targets:
            full = t if os.path.isabs(t) else os.path.join(cwd, t)
            if holds_env(full):
                return block(f"재귀 찾기 대상({t})에 .env 파일이 있다. Grep 도구(무시 목록을 지킴)를 쓰거나 대상을 좁힌다")
    return 0


def main() -> int:
    try:
        data = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace"))
    except ValueError:
        return block("훅 입력을 읽지 못했다")
    tool_input = data.get("tool_input") if isinstance(data, dict) else None
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(command, str):
        return 0
    cwd = data.get("cwd") if isinstance(data.get("cwd"), str) else os.getcwd()
    return check(command, cwd)


if __name__ == "__main__":
    sys.exit(main())
