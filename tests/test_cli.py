import pytest

from magus.cli import main


@pytest.mark.parametrize("argv", [["seed-demo"], ["import", "x.docx", "--synthetic"]])
def test_synthetic_data_never_goes_to_default_user(argv, monkeypatch, tmp_path):
    monkeypatch.setenv("USER_ID", "default")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    with pytest.raises(SystemExit) as e:
        main(argv)
    assert e.value.code == 2
    assert not (tmp_path / "data" / "users" / "default").exists()


def test_seed_demo_for_demo_user(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("USER_ID", "demo")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    main(["seed-demo"])
    assert "생성: demo" in capsys.readouterr().out


def test_alias_command_links_confirmed_transliteration(monkeypatch, tmp_path, capsys):
    # 음역 추정은 저장하지 않는다. 사용자가 확정하면 magus alias로 넣는다(사용자 결정 #28).
    from magus.melchior.bibliography import import_bibliography
    from magus.melchior.check import check_text
    from magus.store import LocalStore

    monkeypatch.setenv("USER_ID", "alice")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    store = LocalStore(tmp_path / "data")
    import_bibliography(store, "alice", "Hayashi, R. (2016). Population as a source of long-term growth. Springer.")
    assert [g.matched_by for g in check_text(store, "alice", "하야시(2016)").groups] == ["음역 추정"]
    store.close()
    main(["alias", "hayashi2016", "하야시"])
    assert "hayashi2016 ← 하야시2016" in capsys.readouterr().out
    store = LocalStore(tmp_path / "data")
    assert [(g.key, g.matched_by) for g in check_text(store, "alice", "하야시(2016)").groups] == [("hayashi2016", "alias")]
    store.close()
    with pytest.raises(SystemExit):
        main(["alias", "nobody1999", "아무개"])
