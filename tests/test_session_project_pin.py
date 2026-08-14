"""A session's project is decided once and survives the cwd moving under it.

Claude Code reports the working directory as it stands when each hook fires,
and the shell keeps its directory between commands. On 2026-08-14 a session
started at a repo root, a job stepped into ansible/roles, and every later turn
filed under a project called 'roles'; a recovery run on a USB mount did the
same as 'kingston'. *_chat is immutable, so a split cannot be re-joined.
"""
import pytest

import brethof_brain_client.transcript as tr
from brethof_brain_client.config import Config
from brethof_brain_client.hook import _project


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    monkeypatch.setattr(tr, "STATE_DIR", str(tmp_path / "state"))
    monkeypatch.delenv("BRETHOF_BRAIN_PROJECT", raising=False)
    monkeypatch.delenv("BRETHOF_MIND_PROJECT", raising=False)


def _repo(tmp_path, name):
    root = tmp_path / name
    (root / ".git").mkdir(parents=True)
    return root


def test_pin_survives_the_cwd_drifting_mid_session(tmp_path):
    repo = _repo(tmp_path, "Girls_SHELTER")
    usb = tmp_path / "KINGSTON"
    usb.mkdir()
    cfg = Config(projects=[{"path": str(repo), "key": "gs"}], default_project="global")

    assert _project(cfg, {"session_id": "s1", "cwd": str(repo)}) == "gs"
    # the agent cds onto a USB stick, then into a subfolder — same session
    assert _project(cfg, {"session_id": "s1", "cwd": str(usb)}) == "gs"
    assert _project(cfg, {"session_id": "s1", "cwd": str(repo / "tools")}) == "gs"


def test_a_guess_is_used_but_never_pinned(tmp_path):
    # A shell that opens in $HOME must not lock the session to "brethofai".
    loose = tmp_path / "brethofai"
    loose.mkdir()
    repo = _repo(tmp_path, "Novels")
    cfg = Config(projects=[{"path": str(repo), "key": "nv"}], default_project="global")

    assert _project(cfg, {"session_id": "s2", "cwd": str(loose)}) == "brethofai"
    assert _project(cfg, {"session_id": "s2", "cwd": str(repo)}) == "nv"
    assert _project(cfg, {"session_id": "s2", "cwd": str(loose)}) == "nv"   # now pinned


def test_explicit_env_override_outranks_a_pin(tmp_path, monkeypatch):
    repo = _repo(tmp_path, "Novels")
    cfg = Config(projects=[{"path": str(repo), "key": "nv"}], default_project="global")
    assert _project(cfg, {"session_id": "s3", "cwd": str(repo)}) == "nv"
    monkeypatch.setenv("BRETHOF_BRAIN_PROJECT", "aurora")
    assert _project(cfg, {"session_id": "s3", "cwd": str(repo)}) == "aurora"


def test_flushing_the_transcript_does_not_wipe_the_pin(tmp_path):
    repo = _repo(tmp_path, "Novels")
    cfg = Config(projects=[{"path": str(repo), "key": "nv"}], default_project="global")
    assert _project(cfg, {"session_id": "s4", "cwd": str(repo)}) == "nv"
    tr.save_state("s4", offset=1234, next_index=7)          # the stop hook's flush
    assert tr.load_project("s4") == "nv"
    assert tr.load_state("s4") == {"offset": 1234, "next_index": 7}


def test_no_session_id_still_resolves(tmp_path):
    repo = _repo(tmp_path, "Novels")
    cfg = Config(projects=[{"path": str(repo), "key": "nv"}], default_project="global")
    assert _project(cfg, {"cwd": str(repo)}) == "nv"
