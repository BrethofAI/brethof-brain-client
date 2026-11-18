"""The model proxy (2026-11-18): memory for any app that lets you set its
model's address. The memory goes into each new user message before the model
reads it and stays on that message for the whole tool loop; the turn is
archived once, when the model answers without asking for a tool."""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from brethof_brain_client import modelproxy
from brethof_brain_client.config import Config


def _server(handler):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A fake model (answers with a tool call when asked to), a fake memory,
    and the proxy between them."""
    seen, memory_calls = [], []
    folder = tmp_path / "shop"
    folder.mkdir()

    class Model(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append(body)
            ask_tool = body["messages"][-1]["role"] == "user" and "use a tool" in json.dumps(body["messages"][-1])
            if body.get("stream"):
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                for t in ("The answer ", "is 42."):
                    self.wfile.write(b"data: " + json.dumps({"choices": [{"delta": {"content": t}}]}).encode() + b"\n\n")
                self.wfile.write(b"data: " + json.dumps({"choices": [{"delta": {}, "finish_reason": "stop"}]}).encode() + b"\n\n")
                self.wfile.write(b"data: [DONE]\n\n")
                return
            if ask_tool:
                msg, fin = {"role": "assistant", "content": None, "tool_calls": [{"id": "t1", "type": "function",
                            "function": {"name": "read", "arguments": "{}"}}]}, "tool_calls"
            else:
                msg, fin = {"role": "assistant", "content": "Done: it is SQLite."}, "stop"
            data = json.dumps({"choices": [{"message": msg, "finish_reason": fin}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    class Memory(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            memory_calls.append((self.path, body))
            out = {"/v1/hooks/session-start": {"injection": "BRIEF-1"},
                   "/v1/hooks/prompt-submit": {"injection": f"RECALL for {body.get('prompt')}"
                                               if body.get("part") == 1 else ""}}.get(self.path, {"status": "ok"})
            data = json.dumps(out).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    model, mem = _server(Model), _server(Memory)
    monkeypatch.setenv("BRETHOF_BRAIN_API_KEY", "bd_test")
    monkeypatch.setenv("BRETHOF_BRAIN_ENDPOINT", f"http://127.0.0.1:{mem.server_port}")
    monkeypatch.delenv("BRETHOF_BRAIN_PROJECT", raising=False)
    proxy = modelproxy.serve(f"http://127.0.0.1:{model.server_port}/v1", port=0, memory=modelproxy.Memory(Config.load()))
    threading.Thread(target=proxy.serve_forever, daemon=True).start()
    yield types_ns(proxy=proxy, seen=seen, memory=memory_calls, folder=str(folder))
    for s in (proxy, model, mem):
        s.shutdown()


def types_ns(**kw):
    import types
    return types.SimpleNamespace(**kw)


def chat(w, messages, stream=False):
    import urllib.request
    r = urllib.request.Request(f"http://127.0.0.1:{w.proxy.server_port}/v1/chat/completions",
                               data=json.dumps({"model": "m", "stream": stream, "messages": messages}).encode(),
                               headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(r, timeout=30) as resp:
        return resp.read().decode()


def grok_messages(folder, question, extra=()):
    """Grok Build's shape: a system prompt with no folder, a <user_info>
    message naming it, reminders, then the person's words in <user_query>."""
    return [{"role": "system", "content": "You are Grok. See /home/x/.grok/docs/user-guide/ for help."},
            {"role": "user", "content": f"<user_info>\nOS Version: linux\nWorkspace Path: {folder}\n</user_info>"},
            {"role": "user", "content": "<system-reminder>\nworkflows are available\n</system-reminder>"},
            {"role": "user", "content": f"<user_query>\n{question}\n</user_query>"}, *extra]


def wait_for(cond, s=5.0):
    end = time.time() + s
    while time.time() < end and not cond():
        time.sleep(0.05)
    return cond()


def test_a_whole_tool_loop_keeps_the_memory_and_archives_once(world):
    first = grok_messages(world.folder, "which database? use a tool")
    chat(world, first)
    sent = world.seen[-1]["messages"][-1]["content"]
    assert "BRIEF-1" in sent and "RECALL for which database? use a tool" in sent and sent.endswith("</user_query>")
    starts = [b for p, b in world.memory if p == "/v1/hooks/session-start"]
    assert starts and starts[0]["project"] == "shop"                         # from Grok's Workspace Path
    assert not [p for p, _ in world.memory if p == "/v1/hooks/stop"]          # a tool call is not the answer
    # the agent runs the tool and calls again: same history plus the result
    loop = first + [{"role": "assistant", "content": None, "tool_calls": [{"id": "t1", "type": "function",
                     "function": {"name": "read", "arguments": "{}"}}]},
                    {"role": "tool", "tool_call_id": "t1", "content": "db.sqlite"}]
    chat(world, loop)
    again = world.seen[-1]["messages"][3]["content"]
    assert again == sent                                                       # the same block, re-attached
    assert len([p for p, _ in world.memory if p == "/v1/hooks/session-start"]) == 1   # no second recall
    assert wait_for(lambda: any(p == "/v1/hooks/stop" for p, _ in world.memory))
    stop = [b for p, b in world.memory if p == "/v1/hooks/stop"]
    assert len(stop) == 1 and [t["text"] for t in stop[0]["turns"]] == ["which database? use a tool",
                                                                        "Done: it is SQLite."]


def test_a_streamed_answer_is_archived(world):
    out = chat(world, grok_messages(world.folder, "what is the answer?"), stream=True)
    assert "is 42." in out
    assert wait_for(lambda: any(p == "/v1/hooks/stop" for p, _ in world.memory))
    stop = next(b for p, b in world.memory if p == "/v1/hooks/stop")
    assert stop["turns"][-1]["text"] == "The answer is 42."


def test_a_side_call_with_no_folder_passes_untouched(world):
    msgs = [{"role": "system", "content": "Write a short title for this chat."},
            {"role": "user", "content": "which database?"}]
    chat(world, msgs)
    assert world.seen[-1]["messages"] == msgs and world.memory == []


def test_two_chats_in_one_folder_are_two_sessions(world):
    chat(world, grok_messages(world.folder, "first chat question"))
    chat(world, grok_messages(world.folder, "second chat question"))
    sids = {b["session_id"] for p, b in world.memory if p == "/v1/hooks/session-start"}
    assert len(sids) == 2


def test_memory_off_passes_everything_through():
    import types
    m = modelproxy.Memory(types.SimpleNamespace(configured=lambda: False))
    body = {"messages": [{"role": "user", "content": "hi"}]}
    assert m.prepare(json.loads(json.dumps(body)))[0] == body and m.on is False
