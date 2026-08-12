"""The fail-open contract: a hook must NEVER break the session — any condition
returns 0 and (for injecting events) emits nothing rather than a partial/garbage
line."""
import io
import json
import sys

from brethof_brain_client import hook


def test_unknown_event_is_noop():
    assert hook.main(["unknown-event"]) == 0
    assert hook.main([]) == 0


def test_unconfigured_emits_nothing(monkeypatch, capsys):
    monkeypatch.delenv("BRETHOF_BRAIN_API_KEY", raising=False)
    monkeypatch.setattr(sys, "stdin",
                        io.StringIO(json.dumps({"cwd": ".", "session_id": "s"})))
    assert hook.main(["session-start"]) == 0
    assert capsys.readouterr().out == ""      # no key → inject nothing, no crash


def test_unreachable_endpoint_fails_open(monkeypatch, capsys):
    monkeypatch.setenv("BRETHOF_BRAIN_API_KEY", "bm_test_dummy")
    monkeypatch.setenv("BRETHOF_BRAIN_ENDPOINT", "http://127.0.0.1:9")  # refused
    monkeypatch.setattr(sys, "stdin", io.StringIO(
        json.dumps({"cwd": ".", "session_id": "s", "prompt": "hi"})))
    assert hook.main(["prompt-submit"]) == 0   # network error → still exit 0
    assert capsys.readouterr().out == ""


def test_stop_no_transcript_is_noop(monkeypatch):
    monkeypatch.setenv("BRETHOF_BRAIN_API_KEY", "bm_test_dummy")
    monkeypatch.setattr(sys, "stdin",
                        io.StringIO(json.dumps({"cwd": ".", "session_id": "s"})))
    assert hook.main(["stop"]) == 0            # missing transcript_path → no-op
