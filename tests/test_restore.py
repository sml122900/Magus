"""백업에서 복구한 인스턴스가 같은 outline을 돌려준다(P1 완료 기준, 오프라인 시험).

백업은 data/의 원본 파일만 담는다(index.sqlite는 뺀다, deploy/backup.sh). 복구 = 파일을 새 폴더에 놓고
`magus reindex`. 원본 파일이 진실이고 SQLite는 인덱스라는 원칙이 지켜지면 outline·ref_check·이슈가 그대로다.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from magus.book.importer import import_manuscript
from magus.book.outline import build_outline
from magus.cli import main
from magus.melchior.check import after_refs_changed, check_chapter
from magus.melchior.refs import add_ref
from magus.store import LocalStore, Passage

FIXTURES = Path(__file__).parent / "fixtures" / "synthetic"


def test_restore_from_files_gives_same_outline(tmp_path: Path, monkeypatch, capsys):
    live = tmp_path / "live"
    store = LocalStore(live)
    import_manuscript(store, "alice", FIXTURES / "닿으려는_종_합성.docx", project_id="synth", synthetic=True)
    store.write_chapter("alice", "synth", 2, "고친 본문. Clack(2012)를 다시 인용한다.", "2장 고침")
    store.add_decision("alice", "synth", "문장은 짧게")
    store.add_issue("alice", "synth", "3장 연결 문단", chapter_number=3, origin="agent")
    add_ref(store, "alice", {"key": "clack2012"}, [Passage("네발동물의 기원", "1장")], book=store.get_ref("alice", "clack2012").book)
    after_refs_changed(store, "alice")  # 도구 ref_add와 같이 파생값을 맞춘다
    store.put_inbox("alice", "논문.txt", b"abc")
    before = build_outline(store, "alice", "synth")
    before_check = check_chapter(store, "alice", "synth", 1).as_dict()
    store.close()

    # 백업: index.sqlite*를 뺀 파일 전체(backup.sh와 같은 규칙) → 새 폴더에 복구
    restored = tmp_path / "restored"
    shutil.copytree(live, restored, ignore=shutil.ignore_patterns("index.sqlite*"))
    assert not (restored / "index.sqlite").exists()
    monkeypatch.setenv("DATA_DIR", str(restored))
    monkeypatch.setenv("USER_ID", "alice")
    main(["reindex"])
    main(["outline", "--project-id", "synth"])
    printed = capsys.readouterr().out
    assert before in printed  # CLI 출력(복구 확인 스크립트가 비교하는 것)과 같다

    again = LocalStore(restored)
    assert build_outline(again, "alice", "synth") == before
    assert check_chapter(again, "alice", "synth", 1).as_dict() == before_check
    assert again.get_ref("alice", "clack2012").status == "verified"
    assert [f.name for f in again.list_inbox("alice")] == ["논문.txt"]
    assert json.dumps(before_check, ensure_ascii=False).count("clack2012") == 1
    again.close()
