"""An unmapped session resolves to its REPOSITORY, not to whatever folder it sits in.

Deriving from the raw cwd forked one repo across three project names in a
single morning (2026-08-14): brethof-workstation-setup became
'brethof_workstat', and its ansible/roles subfolder became 'roles'. The chat
archive is immutable, so a split can never be re-joined — the only fix is not
to split.
"""
from brethof_brain_client.config import Config, _repo_root


def _repo(tmp_path, name):
    root = tmp_path / name
    (root / ".git").mkdir(parents=True)
    return root


def test_subdirectory_of_a_repo_resolves_to_the_repo(tmp_path):
    root = _repo(tmp_path, "brethof-workstation-setup")
    deep = root / "ansible" / "roles"
    deep.mkdir(parents=True)
    c = Config(projects=[], default_project="global")
    assert c.project_for(str(deep)) == c.project_for(str(root))
    assert c.project_for(str(deep)) == "brethof_workstat"   # not "roles"


def test_git_worktree_file_counts_as_a_root(tmp_path):
    # A worktree/submodule has .git as a FILE, not a directory.
    root = tmp_path / "checkout"
    (root / "sub").mkdir(parents=True)
    (root / ".git").write_text("gitdir: /elsewhere/.git/worktrees/x\n")
    assert _repo_root(str(root / "sub")) == str(root)


def test_outside_a_repo_still_gets_its_own_project(tmp_path):
    # The 2026-08-07 rule stands: an unmapped location keeps its own project
    # rather than pouring a whole session into the shared 'global' layer.
    loose = tmp_path / "KINGSTON"
    loose.mkdir()
    c = Config(projects=[], default_project="global")
    assert c.project_for(str(loose)) == "kingston"


def test_explicit_mapping_still_wins_over_the_repo_root(tmp_path):
    root = _repo(tmp_path, "brethof-website")
    deep = root / "sites" / "voice"
    deep.mkdir(parents=True)
    c = Config(projects=[{"path": str(root), "key": "web"}],
               default_project="global")
    assert c.project_for(str(deep)) == "web"


def test_repo_root_never_raises_on_a_silly_path():
    assert _repo_root("") == ""
    assert _repo_root("/nonexistent/path/that/does/not/exist") == ""
