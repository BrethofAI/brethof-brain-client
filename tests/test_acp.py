"""The ACP middle program (2026-11-18): memory for agents a GUI drives over
ACP (Grok Build under Grok App). The memory goes into each prompt before the
agent sees it; the turn is archived from what passes through; everything else
— and everything when the memory is off — goes through untouched."""
import json
import os
import subprocess
import sys
import textwrap
import threading
import types
from http.server import BaseHTTPRequestHandler, HTTPServer

from brethof_brain_client import acp, cli, grok_app


def j(o):
    return (json.dumps(o) + "\n").encode()


class FakeHooks:
    def __init__(self):
        self.calls, self._next_index = [], 0

    def session_start(self):
        self.calls.append(("start",))
        return "BRIEF: the project's rules"

    def before_prompt(self, text):
        self.calls.append(("recall", text))
        return f"RECALL for {text}"

    def archive(self, user, reply):
        self.calls.append(("archive", user, reply))
        self._next_index += 2

    def end_session(self):
        self.calls.append(("end",))


def middle_with(hooks):
    m = acp.Middle(cfg=types.SimpleNamespace(configured=lambda: True, project_for=lambda cwd: "p"))
    m._session = lambda sid, cwd="": m.sessions.setdefault(sid, acp._Session(hooks))
    return m


def prompt(i, sid, text):
    return j({"jsonrpc": "2.0", "id": i, "method": "session/prompt",
              "params": {"sessionId": sid, "prompt": [{"type": "text", "text": text}]}})


def test_which_arguments_start_a_session():
    assert acp.is_session(["agent", "--always-approve", "stdio"])
    assert acp.is_session(["acp"]) and acp.is_session(["agent", "acp"])
    assert not acp.is_session(["--version"]) and not acp.is_session(["login"])
    assert not acp.is_session(["agent", "--help"]) and not acp.is_session([])


def test_the_brief_on_the_first_prompt_and_recall_on_every_one():
    h = FakeHooks()
    m = middle_with(h)
    first = json.loads(m.from_client(prompt(1, "s1", "fix the build")))
    blocks = first["params"]["prompt"]
    assert blocks[1] == {"type": "text", "text": "fix the build"}            # the user's words untouched
    assert "BRIEF" in blocks[0]["text"] and "RECALL for fix the build" in blocks[0]["text"]
    second = json.loads(m.from_client(prompt(2, "s1", "and the tests")))
    assert "BRIEF" not in second["params"]["prompt"][0]["text"]
    assert [c[0] for c in h.calls] == ["start", "recall", "recall"]


def test_the_turn_is_archived_with_the_users_words_not_our_block():
    h = FakeHooks()
    m = middle_with(h)
    m.from_client(prompt(7, "s1", "what is the relay?"))
    for t in ("The relay ", "is a door."):
        m.from_agent(j({"jsonrpc": "2.0", "method": "session/update", "params": {
            "sessionId": "s1", "update": {"sessionUpdate": "agent_message_chunk",
                                          "content": {"type": "text", "text": t}}}}))
    m.from_agent(j({"jsonrpc": "2.0", "id": 7, "result": {"stopReason": "end_turn"}}))
    for t in threading.enumerate():
        if t is not threading.current_thread() and t.daemon:
            t.join(timeout=2)
    assert ("archive", "what is the relay?", "The relay is a door.") in h.calls


def test_the_agents_own_requests_and_their_answers_pass_untouched():
    m = middle_with(FakeHooks())
    m.from_client(prompt(3, "s1", "x"))
    # the agent asks the GUI for permission with the SAME id as a pending prompt
    m.from_agent(j({"jsonrpc": "2.0", "id": 3, "method": "session/request_permission", "params": {}}))
    assert 3 in m.pending                                                   # not mistaken for the prompt's answer
    reply = j({"jsonrpc": "2.0", "id": 3, "result": {"outcome": {"outcome": "selected", "optionId": "a"}}})
    assert m.from_client(reply) == reply


def test_memory_off_or_unreadable_means_untouched_bytes():
    off = acp.Middle(cfg=types.SimpleNamespace(configured=lambda: False))
    line = prompt(1, "s1", "hello")
    assert off.from_client(line) == line
    on = middle_with(FakeHooks())
    for junk in (b"not json\n", b"[1,2]\n", j({"jsonrpc": "2.0", "method": "session/prompt", "params": {}})):
        assert on.from_client(junk) == junk


# ── the whole program, over real pipes, a fake agent and a fake memory ───
AGENT = textwrap.dedent('''
    import json, sys
    for line in sys.stdin:
        m = json.loads(line)
        if m.get("method") == "initialize":
            out = {"jsonrpc": "2.0", "id": m["id"], "result": {"protocolVersion": 1}}
        elif m.get("method") == "session/new":
            out = {"jsonrpc": "2.0", "id": m["id"], "result": {"sessionId": "sess-1"}}
        elif m.get("method") == "session/prompt":
            seen = " | ".join(b["text"] for b in m["params"]["prompt"])
            print(json.dumps({"jsonrpc": "2.0", "method": "session/update", "params": {"sessionId": "sess-1",
                  "update": {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "I saw: " + seen}}}}), flush=True)
            out = {"jsonrpc": "2.0", "id": m["id"], "result": {"stopReason": "end_turn"}}
        else:
            continue
        print(json.dumps(out), flush=True)
''')


def test_end_to_end_through_real_pipes(tmp_path):
    hits = []

    class Memory(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            hits.append((self.path, body))
            out = {"/v1/hooks/session-start": {"injection": "BRIEF-77"},
                   "/v1/hooks/prompt-submit": {"injection": "RECALL-88"}}.get(self.path, {"status": "ok"})
            data = json.dumps(out).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):
            pass
    srv = HTTPServer(("127.0.0.1", 0), Memory)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    agent = tmp_path / "agent.py"
    agent.write_text(AGENT)
    env = dict(os.environ, BRETHOF_BRAIN_API_KEY="bd_test", BRETHOF_BRAIN_PROJECT="proj",
               BRETHOF_BRAIN_ENDPOINT=f"http://127.0.0.1:{srv.server_port}", BRETHOF_BRAIN_ACP_ALWAYS="1",
               PYTHONPATH=os.path.join(os.path.dirname(__file__), ".."))
    feed = b"".join([
        j({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": 1}}),
        j({"jsonrpc": "2.0", "id": 2, "method": "session/new", "params": {"cwd": str(tmp_path), "mcpServers": []}}),
        prompt(3, "sess-1", "what did we decide?")])
    p = subprocess.run([sys.executable, "-m", "brethof_brain_client.acp", "--real", sys.executable, "--", str(agent)],
                       input=feed, capture_output=True, env=env, timeout=60)
    srv.shutdown()
    out = [json.loads(x) for x in p.stdout.splitlines() if x.strip()]
    said = next(o for o in out if o.get("method") == "session/update")["params"]["update"]["content"]["text"]
    assert "BRIEF-77" in said and "RECALL-88" in said and said.endswith("what did we decide?")
    assert any(o.get("id") == 3 and o["result"]["stopReason"] == "end_turn" for o in out)
    paths = [h[0] for h in hits]
    assert paths[:2] == ["/v1/hooks/session-start", "/v1/hooks/prompt-submit"]
    stop = next(b for pth, b in hits if pth == "/v1/hooks/stop")
    assert stop["project"] == "proj" and stop["session_id"] == "sess-1"
    assert [t["text"] for t in stop["turns"]] == ["what did we decide?", "I saw: " + said[len("I saw: "):]]
    assert "/v1/hooks/pre-compact" in paths                                # the sitting's end handed over


def test_grok_app_installer_sets_the_cli_path_and_undo_restores(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("GROK_APP_HOME", str(tmp_path / "app"))
    monkeypatch.setattr(grok_app, "LAUNCHER_DIR", str(tmp_path / "bin"))
    (tmp_path / "app").mkdir()
    settings = tmp_path / "app" / "settings.json"
    settings.write_text(json.dumps({"locale": "en", "theme": "dark"}))
    grok = tmp_path / "grok"
    grok.write_text("#!/bin/sh\necho grok 1.0.89\n")
    grok.chmod(0o755)
    assert grok_app.cmd_grok_app(types.SimpleNamespace(grok=str(grok), undo=False)) == 0
    data = json.loads(settings.read_text())
    launcher = data["manualCliPath"]
    assert data["locale"] == "en" and data["theme"] == "dark" and os.access(launcher, os.X_OK)
    assert subprocess.run([launcher, "--version"], capture_output=True, text=True,
                          env=dict(os.environ, PYTHONPATH=os.path.join(os.path.dirname(__file__), ".."))
                          ).stdout.strip() == "grok 1.0.89"                # passes straight through
    assert grok_app.cmd_grok_app(types.SimpleNamespace(grok="", undo=True)) == 0
    data = json.loads(settings.read_text())
    assert "manualCliPath" not in data and data["theme"] == "dark" and not os.path.exists(launcher)
