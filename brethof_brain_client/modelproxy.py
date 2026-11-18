"""THE MODEL PROXY — memory one layer down, for any app that lets you set its
model's address (Grok App driving Grok Build, Cursor, Hermes, Zed, ...).

The app points its model at this proxy instead of the model itself
(an OpenAI-compatible ``/v1``); the proxy passes every request through to
the real model, except that on ``/v1/chat/completions`` it

  - adds the memory to each NEW user message before the model reads it: the
    brief on a conversation's first message, the recall for that message on
    every one. Agents call the model many times per message (after every tool
    run); the same block is re-attached to that message on every later call,
    so the model never loses it mid-task and the conversation stays stable;
  - archives the turn — the user's own words and the model's final answer —
    once the model answers without asking for a tool.

Why this layer (2026-11-18): Grok App takes a "CLI path" but starts its chat
sessions with its own downloaded Grok inside a sandbox, so a program between
the app and the agent is bypassed. Every app still sends the model's calls to
the address it was given — that is the one door they all share.

The project comes from the working folder named in the agent's system prompt
(the first absolute path there that is a real folder), or
``BRETHOF_BRAIN_PROJECT``. The conversation (the memory's session) is the hash
of its first user message and system prompt.

FAIL-OPEN: no key, the memory down, a body we cannot read — the request goes
through untouched. Stdlib only.

    brethof-brain-model-proxy --upstream http://127.0.0.1:11434/v1 --port 8281
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional

from .acp import _load_index, _save_index
from .config import Config
from .hooks_api import AgentHooks

HEADER = ("Context from the user's long-term memory (Brethof Brain), added before this "
          "message. Use what bears on the request; ignore the rest. Not part of the user's words.")
MARK = "<memory>\n"
CACHE_MAX = 2000
HOP = {"host", "content-length", "connection", "transfer-encoding", "keep-alive", "accept-encoding"}


def _log(msg: str) -> None:
    if os.environ.get("BRETHOF_BRAIN_DEBUG"):
        sys.stderr.write(f"brethof-brain-model-proxy: {msg}\n")
        sys.stderr.flush()


def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(p.get("text", "")) for p in content
                         if isinstance(p, dict) and p.get("type") in ("text", "input_text"))
    return ""


def _with_block(content, block: str):
    if isinstance(content, str):
        return block + "\n\n" + content
    if isinstance(content, list):
        kind = next((p.get("type") for p in content if isinstance(p, dict)
                     and p.get("type") in ("text", "input_text")), "text")
        return [{"type": kind, "text": block}] + content
    return content


_PATH = re.compile(r"(/[^\s'\"`<>|:;,]+)")
# How agents name their folder: Grok sends "Workspace Path: ..." in a
# <user_info> message (2026-11-18), others say working directory / cwd.
_LABELLED = re.compile(r"(?im)^\s*(?:workspace path|working directory|current working directory|cwd|"
                       r"workspace|project (?:root|path|directory))\s*[:=]\s*(/\S+)")
_QUERY = re.compile(r"<user_query>\s*(.*?)\s*</user_query>", re.S)


def said_of(text: str) -> str:
    """The person's own words in a user message: inside Grok's <user_query>
    wrapper when there is one, else the whole message."""
    m = _QUERY.search(text or "")
    return m.group(1) if m else (text or "")


def folder_of(messages: list) -> str:
    """The working folder the agent was told about: a labelled line in any
    message first ("Workspace Path:", "Working directory:", "cwd:"), else the
    first absolute path in the system prompt that is a real folder outside the
    agent's own files."""
    for m in messages:
        for p in _LABELLED.findall(_text(m.get("content"))):
            p = p.rstrip(".)]}")
            if os.path.isdir(p):
                return p
    home = os.path.expanduser("~")
    for m in messages:
        if m.get("role") in ("system", "developer"):
            for p in _PATH.findall(_text(m.get("content"))):
                p = p.rstrip(".)]}")
                if (len(p) > 1 and os.path.isdir(p) and p not in ("/", "/tmp", home)
                        and not p.startswith((home + "/.", "/tmp/", "/usr/", "/etc/"))):
                    return p
    return ""


class Memory:
    """The memory side, shared by all requests."""

    def __init__(self, cfg: Optional[Config] = None):
        try:
            self.cfg = cfg or Config.load()
        except Exception:                                           # noqa: BLE001
            self.cfg = None
        self.on = bool(self.cfg and self.cfg.configured())
        self.blocks: dict[str, str] = {}        # user-message key -> the block given to it
        self.hooks: dict[str, AgentHooks] = {}  # conversation -> its hooks
        self.archived: set[str] = set()
        self.lock = threading.Lock()

    def _dump(self, messages: list) -> None:
        d = os.environ.get("BRETHOF_BRAIN_PROXY_DUMP")
        size = sum(len(_text(m.get("content"))) for m in messages if m.get("role") in ("system", "developer"))
        if d and size >= getattr(self, "_dumped", 0):
            self._dumped = size
            try:
                with open(d, "w", encoding="utf-8") as f:
                    json.dump(messages, f, ensure_ascii=False, indent=1)
            except OSError:
                pass

    def conversation(self, messages: list) -> str:
        self._dump(messages)
        system = "".join(_text(m.get("content")) for m in messages if m.get("role") in ("system", "developer"))[:4000]
        # the conversation's FIRST QUESTION names it: Grok's first user message
        # is a <user_info> block, the same for every chat in a folder on a day
        users = [_text(m.get("content")) for m in messages if m.get("role") == "user"]
        first = next((u for u in users if _QUERY.search(u)), users[0] if users else "")
        return "mp-" + hashlib.sha256((system + "\x00" + first).encode("utf-8", "replace")).hexdigest()[:24]

    def _hooks(self, conv: str, messages: list) -> Optional[AgentHooks]:
        with self.lock:
            h = self.hooks.get(conv)
            if h is None and self.on:
                project = os.environ.get("BRETHOF_BRAIN_PROJECT") or ""
                if not project:
                    folder = folder_of(messages)
                    if not folder:
                        # NO FOLDER, NO MEMORY: an app's side calls (a chat's
                        # title, a summary) name no folder — they pass through
                        # untouched instead of landing in a catch-all project
                        return None
                    project = self.cfg.project_for(folder)
                try:
                    h = AgentHooks(project=project, session_id=conv, config=self.cfg, timeout=8.0)
                    h._next_index = _load_index(conv)      # a restarted proxy carries on the turn numbers
                except Exception as e:                              # noqa: BLE001
                    _log(f"memory off for {conv} ({e})")
                    return None
                self.hooks[conv] = h
                _log(f"conversation {conv} -> project {project}")
            return h

    @staticmethod
    def _key(conv: str, i: int, text: str) -> str:
        return conv + ":" + str(i) + ":" + hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:16]

    def prepare(self, body: dict) -> tuple[dict, Optional[tuple]]:
        """Attach the memory to the user messages of a chat request. Returns
        the body to send and, when this call answers a NEW user message, what
        to archive once the answer is final: (conv, user text)."""
        msgs = body.get("messages")
        if not self.on or not isinstance(msgs, list) or not msgs:
            return body, None
        conv = self.conversation(msgs)
        users = [i for i, m in enumerate(msgs) if isinstance(m, dict) and m.get("role") == "user"]
        # WHERE THE APP MARKS THE PERSON'S WORDS (Grok: <user_query>), only
        # those messages are theirs — the app's own <user_info> and
        # <system-reminder> messages, even one sent AFTER the query, are not
        # (2026-11-18: a trailing "MCP servers connecting" reminder was
        # searched with and archived as the person's words)
        marked = [i for i in users if _QUERY.search(_text(msgs[i].get("content")))]
        if marked:
            users = marked
        if not users:
            return body, None
        last = users[-1]
        last_said = said_of(_text(msgs[last].get("content")))
        # a new turn: nothing but more user messages (reminders) after it —
        # no assistant reply, no tool result
        new_turn = all(m.get("role") == "user" for m in msgs[last + 1:]) if isinstance(msgs[-1], dict) else False
        pending = None
        for i in users:
            said = said_of(_text(msgs[i].get("content")))
            if not said.strip() or said.startswith(MARK):
                continue
            k = self._key(conv, i, said)
            block = self.blocks.get(k)
            if block is None and i == last and new_turn:
                block = self._memory(conv, msgs, said)
                with self.lock:
                    if len(self.blocks) > CACHE_MAX:
                        self.blocks.clear()
                    self.blocks[k] = block
                pending = (conv, said, k)
            if block:
                msgs[i] = dict(msgs[i], content=_with_block(msgs[i].get("content"), block))
        if pending is None and not new_turn and last_said.strip() and not last_said.startswith(MARK):
            # a tool-loop call: the answer that ends the turn is archived then
            pending = (conv, last_said, self._key(conv, last, last_said))
        return body, pending

    def prepare_responses(self, body: dict) -> tuple[dict, Optional[tuple]]:
        """OpenAI's Responses format (Grok's subscription route, 2026-11-18):
        `input` is a list of items — messages, tool calls, tool outputs — and
        the whole history is resent each call (store: false). Viewed as chat
        messages (a tool item counts as a non-user turn), handled by prepare(),
        and the user messages' content written back."""
        items = body.get("input")
        if not isinstance(items, list):
            return body, None
        view = []
        for it in items:
            if isinstance(it, dict) and it.get("type", "message") == "message":
                view.append({"role": it.get("role"), "content": it.get("content")})
            else:
                view.append({"role": "tool", "content": ""})
        if isinstance(body.get("instructions"), str) and body["instructions"]:
            view.insert(0, {"role": "system", "content": body["instructions"]})
        shift = 1 if view and len(view) > len(items) else 0
        _, pending = self.prepare({"messages": view})
        for i, it in enumerate(items):
            v = view[i + shift]
            if isinstance(it, dict) and it.get("type", "message") == "message" and v.get("content") is not it.get("content"):
                it["content"] = v["content"]
        return body, pending

    def _memory(self, conv: str, msgs: list, said: str) -> str:
        h = self._hooks(conv, msgs)
        if h is None:
            return ""
        parts = []
        if not getattr(h, "_briefed", False):
            h._briefed = True
            brief = h.session_start()
            if brief.strip():
                parts.append(brief.strip())
        recall = h.before_prompt_parts(said)
        if recall.strip():
            parts.append(recall.strip())
        return (MARK + HEADER + "\n\n" + "\n\n".join(parts) + "\n</memory>") if parts else ""

    def archive(self, pending: tuple, answer: str) -> None:
        conv, said, key = pending
        with self.lock:
            if key in self.archived:
                return
            self.archived.add(key)
        h = self.hooks.get(conv)
        if h is not None and (said.strip() or answer.strip()):
            _save_index(conv, h._next_index + bool(said.strip()) + bool(answer.strip()))
            h.archive(said, answer)
            _log(f"archived a turn of {conv}")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    upstream = ""
    memory: Memory

    def log_message(self, *a):
        pass

    def _forward(self, method: str) -> None:
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else None
        if os.environ.get("BRETHOF_BRAIN_DEBUG"):
            # what an app sends, never a secret: header names, and the auth
            # header's scheme and length only
            auth = self.headers.get("Authorization") or ""
            shown = (auth.split(" ", 1)[0] + f" <{len(auth)} chars>") if auth else "none"
            _log(f"{method} {self.path} | auth {shown} | headers {sorted(k.lower() for k in self.headers.keys())}"
                 f" | {len(raw or b'')} bytes")
        dump = os.environ.get("BRETHOF_BRAIN_PROXY_DUMP_RESPONSES")
        if dump and raw and self.path.rstrip("/").endswith("/responses"):
            try:
                with open(dump, "wb") as f:
                    f.write(raw)
            except OSError:
                pass
        # MODEL RENAME (tests): BRETHOF_BRAIN_MODEL_MAP="grok-4.7=glm-5.3-flash:cloud,*=glm-5.3-flash:cloud"
        mmap = dict(x.split("=", 1) for x in os.environ.get("BRETHOF_BRAIN_MODEL_MAP", "").split(",") if "=" in x)
        if mmap and raw and method == "POST":
            try:
                b = json.loads(raw)
                if isinstance(b, dict) and b.get("model"):
                    to = mmap.get(b["model"]) or mmap.get("*")
                    if to:
                        _log(f"model {b['model']} -> {to}")
                        b["model"] = to
                        raw = json.dumps(b, ensure_ascii=False).encode("utf-8")
            except ValueError:
                pass
        pending, is_chat, stream = None, False, False
        responses = self.path.split("?")[0].rstrip("/").endswith("/responses")
        if method == "POST" and raw and (responses or self.path.split("?")[0].rstrip("/").endswith("/chat/completions")):
            try:
                body = json.loads(raw)
                is_chat, stream = True, bool(body.get("stream"))
                body, pending = (self.memory.prepare_responses(body) if responses else self.memory.prepare(body))
                raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
            except Exception as e:                                  # noqa: BLE001 — fail open
                _log(f"chat body passed through unread ({type(e).__name__}: {e})")
        path = self.path[3:] if self.path.startswith("/v1") else self.path
        req = urllib.request.Request(self.upstream.rstrip("/") + path, data=raw, method=method)
        for k, v in self.headers.items():
            if k.lower() not in HOP:
                req.add_header(k, v)
        try:
            resp = urllib.request.urlopen(req, timeout=900)
        except urllib.error.HTTPError as e:
            resp = e
        except Exception as e:                                      # noqa: BLE001
            data = json.dumps({"error": {"message": f"upstream unreachable: {e}"}}).encode()
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        self.send_response(resp.status if hasattr(resp, "status") else resp.code)
        for k, v in resp.headers.items():
            if k.lower() not in HOP:
                self.send_header(k, v)
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        answer, final = [], None
        try:
            for line in iter(resp.readline, b""):
                self.wfile.write(f"{len(line):x}\r\n".encode() + line + b"\r\n")
                self.wfile.flush()
                if is_chat and pending:
                    final = _read_piece(line, stream, answer, final)
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        if is_chat and pending and final == "stop":
            text = "".join(answer).strip()
            if text:
                threading.Thread(target=self.memory.archive, args=(pending, text), daemon=True).start()

    def do_POST(self):
        self._forward("POST")

    def do_GET(self):
        self._forward("GET")


def _read_piece(line: bytes, stream: bool, answer: list, final):
    """Collect the answer's text and its finish reason from a response line
    (SSE chunk when streaming, the whole JSON otherwise)."""
    s = line.decode("utf-8", "replace").strip()
    if '"response.' in s or '"output"' in s:
        return _read_responses_piece(s, stream, answer, final)
    if stream:
        if not s.startswith("data:") or s == "data: [DONE]":
            return final
        s = s[5:].strip()
    if not s.startswith("{"):
        return final
    try:
        d = json.loads(s)
    except ValueError:
        return final
    for c in d.get("choices") or []:
        part = c.get("delta") if stream else c.get("message")
        if isinstance(part, dict) and isinstance(part.get("content"), str):
            answer.append(part["content"])
        if c.get("finish_reason"):
            final = c["finish_reason"]
    return final


def _read_responses_piece(s: str, stream: bool, answer: list, final):
    """Responses format: output_text deltas while streaming, and the finished
    response (its output items) at response.completed or as the whole body.
    A turn is final when the response asks for no tool (no function_call)."""
    if stream:
        if not s.startswith("data:"):
            return final
        s = s[5:].strip()
    try:
        d = json.loads(s)
    except ValueError:
        return final
    if d.get("type") == "response.output_text.delta" and isinstance(d.get("delta"), str):
        answer.append(d["delta"])
        return final
    r = d.get("response") if d.get("type") in ("response.completed", "response.done") else (d if "output" in d else None)
    if not isinstance(r, dict):
        return final
    out = r.get("output") or []
    if not stream and not answer:
        for it in out:
            for c in (it.get("content") or []) if isinstance(it, dict) else []:
                if isinstance(c, dict) and c.get("type") == "output_text":
                    answer.append(str(c.get("text") or ""))
    calls = any(isinstance(it, dict) and it.get("type") in ("function_call", "custom_tool_call", "local_shell_call")
                for it in out)
    return "tool_calls" if calls else "stop"


def serve(upstream: str, host: str = "127.0.0.1", port: int = 8281, memory: Optional[Memory] = None):
    Handler.upstream = upstream
    Handler.memory = memory or Memory()
    srv = ThreadingHTTPServer((host, port), Handler)
    _log(f"listening on {host}:{port} -> {upstream} (memory {'on' if Handler.memory.on else 'OFF: no key'})")
    return srv


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="brethof-brain-model-proxy")
    ap.add_argument("--upstream", default=os.environ.get("BRETHOF_BRAIN_UPSTREAM", "http://127.0.0.1:11434/v1"))
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=int(os.environ.get("BRETHOF_BRAIN_PROXY_PORT", "8281")))
    a = ap.parse_args(argv)
    srv = serve(a.upstream, a.host, a.port)
    print(f"brethof-brain model proxy on http://{a.host}:{a.port}/v1 -> {a.upstream}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
