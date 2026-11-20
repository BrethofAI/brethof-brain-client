"""Connecting a machine, local-first (2026-11-20): `connect` is `pair` with the
hub found by itself — the one named, the one this machine is paired with, or
the hub on this machine's front door. The hosted device login (`login`) and
the window that took a key and a passphrase are gone."""
import json
import types

from brethof_brain_client import cli


def _connect(monkeypatch, endpoint="", local_hub=True, saved=None):
    seen = {}
    if saved is not None:
        cli.save_file(saved)
    monkeypatch.setattr(cli, "_local_hub_here", lambda: local_hub)
    monkeypatch.setattr(cli, "cmd_pair", lambda a: seen.update(vars(a)) or 0)
    rc = cli.cmd_connect(types.SimpleNamespace(endpoint=endpoint, no_browser=True))
    return rc, seen


def test_connect_pairs_with_the_hub_on_this_machine(monkeypatch, tmp_path):
    rc, seen = _connect(monkeypatch)
    assert rc == 0 and seen["hub"] == "http://127.0.0.1:8600" and seen["memory"] == ""


def test_connect_pairs_again_with_the_hub_and_memory_it_already_has(monkeypatch):
    rc, seen = _connect(monkeypatch, saved={"endpoint": "https://hub.example/m/team", "api_key": "bd_x"})
    assert rc == 0 and seen["hub"] == "https://hub.example" and seen["memory"] == "team"


def test_connect_without_any_hub_says_how(monkeypatch, capsys):
    import os
    if os.path.exists(cli.CONFIG_PATH):
        os.remove(cli.CONFIG_PATH)
    rc, seen = _connect(monkeypatch, local_hub=False)
    assert rc == 2 and not seen and "brethof-brain pair" in capsys.readouterr().err


def test_there_is_no_hosted_login_any_more():
    import pytest
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["login"])


def test_an_unconnected_plugin_tells_the_agent_the_one_command_and_stays_quiet_elsewhere(capsys, monkeypatch, tmp_path):
    from brethof_brain_client import hook
    monkeypatch.setattr(hook.Config, "load", classmethod(lambda c: types.SimpleNamespace(configured=lambda: False)))
    import io, sys
    sys.stdin = io.StringIO("{}")
    try:
        assert hook.main(["session-start", "1"]) == 0
        out = capsys.readouterr().out
        assert "connect.py" in out and "never see" in out
        sys.stdin = io.StringIO("{}")
        assert hook.main(["prompt-submit"]) == 0 and capsys.readouterr().out == ""
        sys.stdin = io.StringIO("{}")
        assert hook.main(["session-start", "2"]) == 0 and capsys.readouterr().out == ""
    finally:
        sys.stdin = sys.__stdin__


def test_copilot_is_known_by_its_own_variable(monkeypatch, capsys):
    # A Copilot CLI plugin install cannot set BRETHOF_BRAIN_HOOK_FLAT; Copilot
    # marks every hook process with COPILOT_CLI and reads a flat answer.
    import json as _json
    from brethof_brain_client import hook
    monkeypatch.delenv("BRETHOF_BRAIN_HOOK_FLAT", raising=False)
    monkeypatch.setenv("COPILOT_CLI", "1")
    hook._emit_context("SessionStart", "hello")
    assert _json.loads(capsys.readouterr().out) == {"additionalContext": "hello"}
    monkeypatch.delenv("COPILOT_CLI")
    hook._emit_context("SessionStart", "hello")
    assert "hookSpecificOutput" in _json.loads(capsys.readouterr().out)
