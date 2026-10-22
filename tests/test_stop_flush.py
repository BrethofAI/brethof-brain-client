"""The Stop hook's chunked flush: bounded batches, state committed per
confirmed chunk, auth failures surfaced instead of swallowed."""
import io
import json
import sys

import pytest

from brethof_brain_client import hook, transcript
from brethof_brain_client.client import ClientError


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
    monkeypatch.setenv("BRETHOF_BRAIN_API_KEY", "bm_test_dummy")
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
    assert "key rejected" in ctx and "brethof-brain" in ctx


def _run(event, payload):
    sys.stdin = io.StringIO(json.dumps(payload))
    try:
        return hook.main([event])
    finally:
        sys.stdin = sys.__stdin__


@pytest.mark.parametrize("reply_field", ["last_assistant_message", "assistant_response"])
def test_a_harness_without_a_transcript_archives_the_turn_from_its_hooks(tmp_path, fake_client, reply_field):
    # Devin (last_assistant_message) and Kiro (assistant_response) pass no
    # transcript_path: the prompt is kept at prompt-submit, the reply comes
    # with the stop payload (2026-10-03)
    sid = f"nots-{reply_field}"
    base = {"cwd": str(tmp_path), "session_id": sid}
    assert _run("prompt-submit", {**base, "prompt": "what is X?"}) == 0
    assert _run("stop", {**base, reply_field: "X is 7."}) == 0
    stop = [c for c in fake_client.calls if "turns" in c][-1]
    assert [(t["line_type"], t["text"], t["index"]) for t in stop["turns"]] == \
        [("user", "what is X?", 0), ("assistant", "X is 7.", 1)]
    # the next turn carries on the index, and the kept prompt was cleared
    assert _run("prompt-submit", {**base, "prompt": "and Y?"}) == 0
    assert _run("stop", {**base, reply_field: "Y is 8."}) == 0
    stop = [c for c in fake_client.calls if "turns" in c][-1]
    assert [t["index"] for t in stop["turns"]] == [2, 3] and stop["turns"][0]["text"] == "and Y?"


def test_kiro_v3_stop_reads_the_reply_from_its_session_file(tmp_path, fake_client, monkeypatch):
    # Kiro CLI V3 (2026-10-21, kiro-cli 2.33.0 --v3): Stop carries only
    # session_id, hook_event_name and cwd; the reply is in the session's own
    # messages.jsonl — the "assistant" Say events after the last "user" event
    monkeypatch.setenv("KIRO_HOME", str(tmp_path / "kiro"))
    sid = "sess_95e83fa2-5b11-4089-b039-cd18dc07793f"
    d = tmp_path / "kiro" / "sessions" / "7caf67e728b46fbb" / sid
    d.mkdir(parents=True)
    ev = lambda **p: json.dumps({"id": "x", "payload": p})
    (d / "messages.jsonl").write_text("\n".join([
        ev(type="user", content="an older prompt"),
        ev(type="assistant", content="an older reply", operationType="Say"),
        ev(type="user", content="what is X?"),
        ev(type="turn_start", executionId="e"),
        ev(type="assistant", content="X is 7.", operationType="Say"),
        ev(type="assistant", content="...", operationType="Reasoning"),
        ev(type="turn_end", stopReason="end_turn"),
    ]) + "\n", encoding="utf-8")
    base = {"cwd": str(tmp_path), "session_id": sid}
    assert _run("prompt-submit", {**base, "hook_event_name": "UserPromptSubmit", "prompt": "what is X?"}) == 0
    assert _run("stop", {**base, "hook_event_name": "Stop"}) == 0
    stop = [c for c in fake_client.calls if "turns" in c][-1]
    assert [(t["line_type"], t["text"]) for t in stop["turns"]] == \
        [("user", "what is X?"), ("assistant", "X is 7.")]


def test_a_stop_without_a_reply_or_session_file_archives_the_prompt_alone(tmp_path, fake_client, monkeypatch):
    monkeypatch.setenv("KIRO_HOME", str(tmp_path / "nokiro"))
    monkeypatch.setattr(hook, "_kiro_v3_reply", lambda sid: "")
    base = {"cwd": str(tmp_path), "session_id": "sess_none"}
    _run("prompt-submit", {**base, "prompt": "lonely"})
    _run("stop", {**base, "hook_event_name": "Stop"})
    stop = [c for c in fake_client.calls if "turns" in c][-1]
    assert [t["line_type"] for t in stop["turns"]] == ["user"]


def test_a_deferred_payload_archive_keeps_the_prompt_for_the_next_try(tmp_path, fake_client):
    sid = "nots-deferred"
    base = {"cwd": str(tmp_path), "session_id": sid}
    _run("prompt-submit", {**base, "prompt": "keep me"})
    fake_client.envelope = {"status": "over_cap"}
    _run("stop", {**base, "last_assistant_message": "r"})
    assert transcript.load_pending_prompt(sid) == "keep me"
    assert transcript.load_state(sid)["next_index"] == 0


def test_plain_mode_prints_the_text_itself_as_utf8(capfdbinary, monkeypatch):
    monkeypatch.setenv("BRETHOF_BRAIN_HOOK_PLAIN", "1")
    hook._emit_context("UserPromptSubmit", "the memory block — ★")
    assert capfdbinary.readouterr().out == "the memory block — ★".encode("utf-8")


def test_goose_gets_its_brief_and_recall_through_the_turn_file(tmp_path, fake_client, monkeypatch):
    # goose shows the model only the GOOSE_MOIM_MESSAGE_FILE, read after the
    # prompt hook ran; its payload names the prompt "message" (2026-10-03)
    f = tmp_path / "turn.txt"
    monkeypatch.setattr(hook, "TURN_FILE", str(f))
    fake_client.envelope = {"status": "ok", "injection": "MEMORY"}
    base = {"session_id": "goose-1", "event": "SessionStart"}
    assert _run("session-start", base) == 0
    assert not f.exists()                               # the brief waits for the first prompt
    assert _run("prompt-submit", {"session_id": "goose-1", "message": "what is X?"}) == 0
    assert f.read_text() == "MEMORY\n\nMEMORY"          # brief + recall
    fake_client.envelope = {"status": "ok", "injection": ""}
    assert _run("prompt-submit", {"session_id": "goose-1", "message": "and Y?"}) == 0
    assert f.read_text() == ""                          # nothing stale on a later turn
    assert _run("stop", {"session_id": "goose-1", "last_assistant_message": "Y is 8."}) == 0
    stop = [c for c in fake_client.calls if "turns" in c][-1]
    assert [t["text"] for t in stop["turns"]] == ["and Y?", "Y is 8."]


def test_the_archive_mode_can_come_on_the_command_line(tmp_path, fake_client, monkeypatch):
    # ZCode's process handlers carry no environment (2026-10-03)
    monkeypatch.delenv("BRETHOF_BRAIN_ARCHIVE", raising=False)
    base = {"session_id": "zc-1", "transcript_path": str(tmp_path / "one-line.jsonl")}
    sys.stdin = io.StringIO(json.dumps({**base, "prompt": "hi"}))
    try:
        hook.main(["prompt-submit", "--archive=hooks"])
        sys.stdin = io.StringIO(json.dumps({**base, "last_assistant_message": "hello"}))
        hook.main(["stop", "--archive=hooks"])
    finally:
        sys.stdin = sys.__stdin__
    stop = [c for c in fake_client.calls if "turns" in c][-1]
    assert [t["text"] for t in stop["turns"]] == ["hi", "hello"]


def test_a_projects_thread_recalls_on_the_human_words(tmp_path, fake_client):
    wake = ('<wake reason="mention"><project id="c"><thread ts="t"><message trigger="true" from="human" '
            'author="P">what is DEEPCANARY?</message></thread></project><system-note>x</system-note></wake>')
    _run("prompt-submit", {"cwd": str(tmp_path), "session_id": "proj-recall", "prompt": wake})
    sent = [c for c in fake_client.calls if "prompt" in c][-1]
    assert sent["prompt"] == "what is DEEPCANARY?"
