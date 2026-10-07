"""P1 3단계: 받은함. 파일 이름 안전성, 한도(업로드 크기·저장 용량), 경로 인자 해석(원격은 이름만), CLI."""

from __future__ import annotations

from pathlib import Path

import pytest
from mcp import Client

from magus.cli import main
from magus.config import Settings
from magus.inbox import FileResolver, LimitError, safe_filename, save_upload
from magus.server import build_server
from magus.store import LocalStore

pytestmark = pytest.mark.anyio
FIXTURES = Path(__file__).parent / "fixtures" / "synthetic"


@pytest.mark.parametrize("bad", ["../원고.docx", "a/b.docx", "a\\b.docx", ".hidden.docx", "CON.docx", "x.exe", "", "원고"])
def test_unsafe_names_are_rejected(bad):
    with pytest.raises(ValueError):
        safe_filename(bad)


def test_safe_names():
    assert safe_filename(" 닿으려는 종 (최종).docx ") == "닿으려는 종 (최종).docx"
    assert safe_filename("kremer1993.PDF") == "kremer1993.PDF"


def test_upload_limits(store: LocalStore):
    save_upload(store, "alice", "a.pdf", b"x" * 600, max_upload=1000, max_user=2000)
    with pytest.raises(LimitError, match="파일이 너무 크다: .*한 개 한도"):
        save_upload(store, "alice", "b.pdf", b"x" * 1001, max_upload=1000, max_user=10_000)
    save_upload(store, "alice", "a.pdf", b"y" * 900, max_upload=1000, max_user=2000)  # 같은 이름 덮어쓰기는 이전 크기를 뺀다
    with pytest.raises(LimitError, match="저장 용량 한도를 넘는다"):
        save_upload(store, "alice", "c.pdf", b"z" * 1000, max_upload=1000, max_user=1500)
    assert [(f.name, f.size) for f in store.list_inbox("alice")] == [("a.pdf", 900)]
    assert store.list_inbox("bob") == [] and store.usage_bytes("bob") == 0
    assert store.delete_inbox("alice", "a.pdf") and not store.delete_inbox("alice", "a.pdf")


def test_resolver_remote_takes_inbox_names_only(store: LocalStore, tmp_path: Path):
    outside = tmp_path / "secret.txt"
    outside.write_text("서버 파일", encoding="utf-8")
    store.put_inbox("alice", "논문.txt", b"abc")
    remote, local = FileResolver(store), FileResolver(store, tmp_path, local_paths=True)
    assert remote("alice", "논문.txt") == (store.inbox_path("alice", "논문.txt"), "inbox/논문.txt")
    for escape in (str(outside), "../../secret.txt", "secret.txt"):
        with pytest.raises(FileNotFoundError, match="올린 파일에"):
            remote("alice", escape)
    with pytest.raises(FileNotFoundError):
        remote("bob", "논문.txt")  # 다른 사람의 받은함
    assert local("alice", "secret.txt") == (outside.resolve(), str(outside.resolve()))  # 로컬(stdio) 개발용만


async def test_files_list_and_import_from_inbox(settings: Settings, store: LocalStore):
    store.put_inbox(settings.user_id, "원고.docx", (FIXTURES / "닿으려는_종_합성.docx").read_bytes())
    async with Client(build_server(settings, store)) as client:
        listed = "".join(b.text for b in (await client.call_tool("files_list", {})).content)
        assert listed.startswith("올린 파일 1개 · 사용 ") and "- 원고.docx · " in listed and "원고(book_import)" in listed
        imported = await client.call_tool("book_import", {"path": "원고.docx", "project_id": "synth"})
        assert not imported.is_error and "장 7개(" in imported.content[0].text


def test_inbox_cli(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("USER_ID", "alice")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MAX_UPLOAD_MB", "0.001")  # 1,000바이트
    small, big = tmp_path / "작은.md", tmp_path / "큰.pdf"
    small.write_text("**사용자:** 안녕", encoding="utf-8")
    big.write_bytes(b"x" * 2000)
    main(["inbox", "--add", str(small)])
    assert "- 작은.md · " in capsys.readouterr().out
    with pytest.raises(SystemExit):
        main(["inbox", "--add", str(big)])
    assert "파일이 너무 크다" in capsys.readouterr().err
    main(["inbox", "--remove", "작은.md"])
    assert "올린 파일이 없다" in capsys.readouterr().out


def test_limits_from_env():
    s = Settings.from_env({"MAX_UPLOAD_MB": "20", "MAX_USER_MB": "500", "MAX_REQUEST_MB": "1.5"})
    assert (s.max_upload_bytes, s.max_user_bytes, s.max_request_bytes) == (20_000_000, 500_000_000, 1_500_000)
    with pytest.raises(ValueError, match="MAX_USER_MB"):
        Settings.from_env({"MAX_USER_MB": "-1"})


def test_size_text():
    from magus.inbox import size_text

    assert (size_text(41_781), size_text(10), size_text(6_719_586)) == ("42 KB", "1 KB", "6.7 MB")
