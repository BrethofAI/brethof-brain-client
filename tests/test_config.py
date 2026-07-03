"""Config + project resolution — pure, cross-OS (path handling differs per OS)."""
from brethof_mind_client.config import Config, valid_project


def test_valid_project():
    assert valid_project("global")
    assert valid_project("my_proj1")
    assert not valid_project("Bad")          # uppercase
    assert not valid_project("1bad")         # leading digit
    assert not valid_project("")             # empty
    assert not valid_project("way_too_long_a_key")  # > 16 chars


def test_project_for_env_override(monkeypatch):
    monkeypatch.setenv("BRETHOF_MIND_PROJECT", "envproj")
    c = Config(projects=[{"path": "/a", "key": "aproj"}], default_project="defproj")
    assert c.project_for("/a/sub") == "envproj"       # env wins over everything


def test_project_for_longest_prefix(monkeypatch):
    monkeypatch.delenv("BRETHOF_MIND_PROJECT", raising=False)
    c = Config(projects=[{"path": "/work/acme", "key": "acme"},
                         {"path": "/work", "key": "work"}],
               default_project="defproj")
    assert c.project_for("/work/acme/src") == "acme"  # longest prefix wins
    assert c.project_for("/work/other") == "work"
    assert c.project_for("/elsewhere") == "defproj"   # falls back to default


def test_default_project_env(monkeypatch):
    monkeypatch.delenv("BRETHOF_MIND_PROJECT", raising=False)
    monkeypatch.setenv("BRETHOF_MIND_DEFAULT_PROJECT", "softdefault")
    c = Config.load()
    # No file config in the test home → the soft-default env is used, and it must
    # NOT hard-override a matching path mapping (that's the whole point).
    assert c.default_project == "softdefault"
    assert c.project_for("/anything") == "softdefault"
