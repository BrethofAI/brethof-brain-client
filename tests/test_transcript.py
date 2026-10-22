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


def test_a_claude_code_projects_thread_archives_the_words_not_the_framing(tmp_path):
    # Claude Code Projects (beta) cloud thread, shapes measured 2026-10-22: the
    # platform's <session-context> line is dropped, the <wake> envelope gives
    # up only the human's words (HTML-unescaped), the answer posted through
    # hearthbot post_message is the assistant's text, and the other hearthbot
    # tools leave no marker.
    wake = ('<wake reason="mention" current-time="2026-10-22T21:33:06Z">\n  <project id="chan_x" type="project">\n'
            '    <thread ts="cmsg_1">\n      <message trigger="true" from="human" trust="principal" author="P" '
            'id="cmsg_2" sent-at="2026-10-22T21:33:02Z" mention="true">What is &#34;RIGCANARY&#34;?</message>\n'
            '    </thread>\n  </project>\n  <system-note>You are the session for this thread.</system-note>\n</wake>\n')
    lines = [
        {"type": "user", "message": {"role": "user", "content":
            '<session-context nonce="abc">\nGitHub login: `someone`\n# PR attribution (required)\n</session-context>'}},
        {"type": "user", "message": {"role": "user", "content": wake}},
        {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "name": "mcp__hearthbot__post_message", "input": {"text": "0e72ecfa"}}]}},
        {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "name": "mcp__hearthbot__no_reply_needed", "input": {"reason": "done"}}]}},
        {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "text", "text": "posted"}, {"type": "tool_use", "name": "Bash", "input": {}}]}},
    ]
    turns, _, _ = transcript.read_new_turns(_write(tmp_path, lines), "sess-projects")
    assert [(t["line_type"], t["text"]) for t in turns] == [
        ("user", 'What is "RIGCANARY"?'),
        ("assistant", "0e72ecfa"),
        ("assistant", "posted\n[tool_use: Bash]")]
    assert all("session-context" not in t["text"] and "system-note" not in t["text"] for t in turns)


def test_ordinary_user_text_that_mentions_wake_is_kept_as_is(tmp_path):
    lines = [{"type": "user", "message": {"role": "user", "content": "what does <wake> do in Projects?"}}]
    turns, _, _ = transcript.read_new_turns(_write(tmp_path, lines), "sess-not-projects")
    assert turns[0]["text"] == "what does <wake> do in Projects?"
