"""`.claude/hooks/env_guard.py`(.env 보호 장치, 2026-10-09): 막는 명령·허용하는 두 꼴·재귀 찾기·입력을 못 읽으면 막음."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[1] / ".claude" / "hooks" / "env_guard.py"


def run(command: str | None, cwd: Path, raw: str | None = None) -> subprocess.CompletedProcess[str]:
    body = raw if raw is not None else json.dumps({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(cwd)})
    return subprocess.run([sys.executable, str(HOOK)], input=body.encode("utf-8"), capture_output=True, timeout=30)


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    (tmp_path / "deploy").mkdir()
    (tmp_path / "deploy" / ".env").write_text("SESSION_SECRET=fake\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize("command", [
    "cat deploy/.env", "less deploy/.env", "head -1 deploy/.env", "tail deploy/.env", "type deploy\\.env",
    "Get-Content deploy/.env", "python -c \"print(open('deploy/.env').read())\"", "powershell -c gc deploy/.env",
    "source deploy/.env", ". deploy/.env", "sha256sum deploy/.env", "wc -c deploy/.env", "awk '{print length($0)}' deploy/.env",
    "grep SESSION_SECRET deploy/.env", "grep -c SESSION_SECRET deploy/.env", "grep -c '^SESSION_SECRET=.' deploy/.env",
    "grep -c '^SESSION_SECRET=' deploy/.env; cat deploy/.env", "grep -c '^SESSION_SECRET=' deploy/.env\ncat deploy/.env",
    "grep -c '^SESSION_SECRET=' deploy/.env | cat", "cat deploy/.ENV", "cat deploy/.env.local", "cat .env.example",
    "ssh host \"grep -c '^A=' /opt/magus/deploy/.env\"",
])
def test_blocks_reading_values(tree: Path, command: str):
    r = run(command, tree)
    assert r.returncode == 2, command
    assert ".env 보호 장치가 막았다" in r.stderr.decode("utf-8")


@pytest.mark.parametrize("command", [
    "grep -c '^ANTHROPIC_API_KEY=' deploy/.env", 'grep -c "^SESSION_SECRET=" /opt/magus/deploy/.env', "grep -c '^A_1=' .env",
    "git check-ignore deploy/.env", "git check-ignore -v deploy/.env", "git check-ignore -q --no-index deploy/.env .env",
    "ls src", ".venv/Scripts/python -m pytest -q", "grep -rn x src", "grep -n x src/a.py", "rg x", "rg -n x src",
])
def test_allows(tree: Path, command: str):
    r = run(command, tree)
    assert r.returncode == 0, (command, r.stderr.decode("utf-8"))


@pytest.mark.parametrize("command", ["grep -rn SECRET deploy", "grep -R SECRET .", "grep --recursive SECRET", "egrep -rl x .",
                                     "rg -uu SECRET", "rg --hidden --no-ignore SECRET deploy", "grep -rn -e SECRET deploy"])
def test_blocks_recursive_search_over_env(tree: Path, command: str):
    assert run(command, tree).returncode == 2, command


def test_unreadable_input_blocks(tree: Path):
    assert run(None, tree, raw="not json").returncode == 2
    assert run(None, tree, raw=json.dumps({"tool_name": "Read", "tool_input": {"file_path": "x"}})).returncode == 0


def test_settings_wire_the_hook():
    settings = json.loads((HOOK.parents[1] / "settings.json").read_text(encoding="utf-8"))
    assert {"Read(./deploy/.env)", "Read(./**/.env)", "Read(./**/.env.*)"} <= set(settings["permissions"]["deny"])
    entry = settings["hooks"]["PreToolUse"][0]
    assert "Bash" in entry["matcher"] and "PowerShell" in entry["matcher"]
    assert "env_guard.py" in entry["hooks"][0]["command"]
