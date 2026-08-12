"""Transcript turn extraction + offset bookkeeping."""
import json

from brethof_brain_client import transcript


def _write(tmp_path, lines, name="t.jsonl", tail=""):
    p = tmp_path / name
    p.write_text("\n".join(json.dumps(x) for x in lines) + "\n" + tail,
                 encoding="utf-8")
    return str(p)


def test_extract_turns(tmp_path):
    lines = [
        {"type": "user", "timestamp": "t0",
         "message": {"role": "user", "content": "hello world"}},
        {"type": "assistant",
         "message": {"role": "assistant", "content": [
             {"type": "text", "text": "hi there"},
             {"type": "tool_use", "name": "Bash"}]}},
        {"type": "user",   # tool_result arrives as a list-form user message
         "message": {"role": "user", "content": [
             {"type": "tool_result", "content": [{"type": "text", "text": "SECRET FILE"}]}]}},
        {"type": "system", "content": "ignored"},   # non-conversation line, dropped
    ]
    tj = _write(tmp_path, lines)
    turns, off, idx = transcript.read_new_turns(tj, "sess-extract-1")
    # tool_result content is DROPPED entirely (privacy contract), so 2 turns.
    assert len(turns) == 2
    assert turns[0]["line_type"] == "user" and turns[0]["embed"] is True
    assert "hi there" in turns[1]["text"] and turns[1]["embed"] is True
    assert all("SECRET FILE" not in t["text"] for t in turns)
    assert idx == 2 and off > 0
    assert [t["index"] for t in turns] == [0, 1]
    # every turn carries the byte offset just past its own line
    assert all(t["_offset"] > 0 for t in turns)
    assert turns[0]["_offset"] < turns[1]["_offset"] <= off


def test_list_form_user_text_is_kept(tmp_path):
    # A genuine user message can arrive as list-form typed text blocks — that IS
    # dialogue and must be captured (tool_result blocks alongside it dropped).
    lines = [
        {"type": "user", "message": {"role": "user", "content": [
            {"type": "text", "text": "please check this"},
            {"type": "tool_result", "content": [{"type": "text", "text": "NOPE"}]}]}},
    ]
    tj = _write(tmp_path, lines)
    turns, _, _ = transcript.read_new_turns(tj, "sess-listform")
    assert len(turns) == 1
    assert turns[0]["text"] == "please check this" and turns[0]["embed"] is True


def test_partial_last_line_left_for_next_pass(tmp_path):
    full = {"type": "user", "message": {"role": "user", "content": "first"}}
    tj = _write(tmp_path, [full], tail='{"type": "user", "message": {"role": "u')
    turns, off, idx = transcript.read_new_turns(tj, "sess-partial")
    assert len(turns) == 1 and idx == 1
    # the offset must stop BEFORE the unterminated tail, not swallow it
    with open(tj, "rb") as f:
        data = f.read()
    assert off == data.index(b"\n") + 1
    # once the writer finishes the line, it is picked up from that offset
    transcript.save_state("sess-partial", off, idx)
    with open(tj, "ab") as f:
        f.write(b'ser", "content": "second half"}}\n')
    turns2, off2, idx2 = transcript.read_new_turns(tj, "sess-partial")
    assert len(turns2) == 1 and "second half" in turns2[0]["text"]
    assert idx2 == 2 and off2 == len(data) + len(b'ser", "content": "second half"}}\n')


def test_truncated_transcript_resets_state(tmp_path):
    lines = [{"type": "user", "message": {"role": "user", "content": "hello"}}]
    tj = _write(tmp_path, lines)
    # stored offset points far past the (rewritten, shorter) file
    transcript.save_state("sess-trunc", 10_000, 57)
    turns, off, idx = transcript.read_new_turns(tj, "sess-trunc")
    # reset to (0, 0) and re-read — idempotent server upsert makes this safe
    assert len(turns) == 1 and turns[0]["index"] == 0
    assert idx == 1 and 0 < off <= 10_000


def test_empty_and_missing(tmp_path):
    assert transcript.read_new_turns("", "s")[0] == []
    assert transcript.read_new_turns(str(tmp_path / "nope.jsonl"), "s")[0] == []


def test_state_roundtrip():
    transcript.save_state("sess-rt", 123, 5)
    s = transcript.load_state("sess-rt")
    assert s["offset"] == 123 and s["next_index"] == 5
    # a never-seen session has a clean zero state
    assert transcript.load_state("sess-never")["offset"] == 0
