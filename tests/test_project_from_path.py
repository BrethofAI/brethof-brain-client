"""An unmapped folder must become its OWN project, never a global dump."""
from brethof_mind_client.config import Config, project_from_path


def test_derives_from_folder_name():
    assert project_from_path(r"D:\Programming\Brainstorming") == "brainstorming"
    assert project_from_path("/home/me/work/acme-site") == "acme_site"
    assert project_from_path(r"C:\dev\Monster Studio") == "monster_studio"


def test_skips_generic_containers_and_uses_parent():
    # …/payments/src -> 'payments', not 'src'
    assert project_from_path("/home/me/payments/src") == "payments"
    # nothing usable at all
    assert project_from_path("/tmp") == ""
    assert project_from_path("") == ""


def test_key_rule_is_respected():
    long_name = "/x/" + "a" * 40
    got = project_from_path(long_name)
    assert got and len(got) <= 16 and got.isascii()
    assert project_from_path("/x/2026-archive").startswith("p_")


def test_unmapped_cwd_does_not_fall_into_global():
    cfg = Config(endpoint="e", api_key="k", default_project="global",
                 projects=[{"path": "/home/me/mapped", "key": "mapped"}])
    assert cfg.project_for("/home/me/mapped/deep") == "mapped"
    assert cfg.project_for("/home/me/newthing") == "newthing"
    assert cfg.project_for("/home/me/newthing") != "global"


def test_generic_folder_still_falls_back_to_default():
    cfg = Config(endpoint="e", api_key="k", default_project="global",
                 projects=[])
    assert cfg.project_for("/tmp") == "global"


def test_explicit_default_project_still_wins():
    """A configured default is an instruction — deriving must not override
    it (aurora-style deployments pin one project on purpose)."""
    cfg = Config(endpoint="e", api_key="k", default_project="companion",
                 projects=[])
    assert cfg.project_for("/home/me/whatever") == "companion"
