import pytest

from magus.config import Settings


def test_defaults():
    s = Settings.from_env({})
    assert s.user_id == "default"
    assert s.embeddings == "none"
    assert s.data_dir.name == "data"


def test_rejects_unknown_embeddings():
    with pytest.raises(ValueError, match="EMBEDDINGS"):
        Settings.from_env({"EMBEDDINGS": "cohere"})


@pytest.mark.parametrize("bad", ["../etc", "a/b", "", "-x", "한글"])
def test_rejects_unsafe_user_id(bad):
    if bad == "":
        assert Settings.from_env({"USER_ID": bad}).user_id == "default"
        return
    with pytest.raises(ValueError, match="USER_ID"):
        Settings.from_env({"USER_ID": bad})


def test_files_root_defaults_to_data_dir_parent(tmp_path):
    # Desktop이 띄우는 작업 폴더와 무관하게, 상대 경로(fixtures/papers/…)는 프로젝트 폴더 기준이다
    s = Settings.from_env({"DATA_DIR": str(tmp_path / "data")})
    assert s.files_root == tmp_path.resolve()
    assert Settings.from_env({"DATA_DIR": str(tmp_path / "data"), "FILES_DIR": str(tmp_path / "x")}).files_root == (tmp_path / "x").resolve()
