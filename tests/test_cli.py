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
