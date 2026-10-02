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
