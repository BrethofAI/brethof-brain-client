"""The Stop hook's chunked flush: bounded batches, state committed per
confirmed chunk, auth failures surfaced instead of swallowed."""
import io
import json
import sys

import pytest

from brethof_mind_client import hook, transcript
from brethof_mind_client.client import ClientError


def _transcript(tmp_path, n):
    p = tmp_path / "big.jsonl"
    lines = [json.dumps({"type": "user",
                         "message": {"role": "user", "content": f"msg {i}"}})
             for i in range(n)]
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(p)


class FakeClient:
    """Stands in for hook.Client: records batches, fails on command."""

    calls = []
    fail_after = None   # int -> raise ClientError on the Nth post (1-based)
    envelope = {"status": "ok"}

    def __init__(self, cfg, timeout=None):
        pass

    def post(self, path, payload, timeout=None):
        FakeClient.calls.append(payload)
        if (FakeClient.fail_after is not None
                and len(FakeClient.calls) >= FakeClient.fail_after):
            raise ClientError("boom", status_code=None)
        return dict(FakeClient.envelope)


@pytest.fixture()
def fake_client(monkeypatch):
    FakeClient.calls = []
    FakeClient.fail_after = None
    FakeClient.envelope = {"status": "ok"}
    monkeypatch.setattr(hook, "Client", FakeClient)
    monkeypatch.setenv("BRETHOF_MIND_API_KEY", "bm_test_dummy")
    return FakeClient


def _run_stop(tmp_path, transcript_path, session):
    stdin = io.StringIO(json.dumps({"cwd": str(tmp_path), "session_id": session,
                                    "transcript_path": transcript_path}))
    sys.stdin = stdin
    try:
        return hook.main(["stop"])
    finally:
        sys.stdin = sys.__stdin__


def test_backlog_flushes_in_bounded_chunks(tmp_path, fake_client):
    n = hook.MAX_TURNS_PER_FLUSH * 2 + 5   # forces 3 chunks
    tj = _transcript(tmp_path, n)
    assert _run_stop(tmp_path, tj, "sess-chunks") == 0
    assert len(fake_client.calls) == 3
    assert all(len(c["turns"]) <= hook.MAX_TURNS_PER_FLUSH for c in fake_client.calls)
    total = sum(len(c["turns"]) for c in fake_client.calls)
    assert total == n
    # no client-internal fields on the wire
    assert all("_offset" not in t for c in fake_client.calls for t in c["turns"])
    # everything confirmed -> offset at EOF, next run sends nothing
    fake_client.calls = []
    assert _run_stop(tmp_path, tj, "sess-chunks") == 0
    assert fake_client.calls == []


def test_mid_backlog_failure_keeps_confirmed_chunks(tmp_path, fake_client):
    n = hook.MAX_TURNS_PER_FLUSH * 2      # 2 chunks
    tj = _transcript(tmp_path, n)
    fake_client.fail_after = 2            # chunk 1 ok, chunk 2 dies
    assert _run_stop(tmp_path, tj, "sess-retry") == 0   # fail-open, exit 0
    state = transcript.load_state("sess-retry")
    assert state["next_index"] == hook.MAX_TURNS_PER_FLUSH  # chunk 1 committed
    # retry resumes from the failed chunk only — no re-send of chunk 1
    fake_client.calls = []
    fake_client.fail_after = None
    assert _run_stop(tmp_path, tj, "sess-retry") == 0
    assert len(fake_client.calls) == 1
    assert fake_client.calls[0]["turns"][0]["index"] == hook.MAX_TURNS_PER_FLUSH
    assert transcript.load_state("sess-retry")["next_index"] == n


def test_deferred_envelope_does_not_advance(tmp_path, fake_client):
    tj = _transcript(tmp_path, 3)
    fake_client.envelope = {"status": "over_cap", "notice": "cap hit"}
    assert _run_stop(tmp_path, tj, "sess-defer") == 0
    assert transcript.load_state("sess-defer")["next_index"] == 0  # nothing committed


def test_auth_failure_emits_notice(tmp_path, fake_client, capsys, monkeypatch):
    class AuthDead(FakeClient):
        def post(self, path, payload, timeout=None):
            raise ClientError("HTTP 401 on /v1/hooks/session-start", status_code=401)

    monkeypatch.setattr(hook, "Client", AuthDead)
    monkeypatch.setattr(sys, "stdin",
                        io.StringIO(json.dumps({"cwd": str(tmp_path), "session_id": "s"})))
    assert hook.main(["session-start"]) == 0            # still fail-open
    out = capsys.readouterr().out
    payload = json.loads(out)
    ctx = payload["hookSpecificOutput"]["additionalContext"]
    assert "key rejected" in ctx and "brethof-mind" in ctx
