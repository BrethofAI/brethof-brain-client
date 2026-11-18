"""THE ACP MIDDLE PROGRAM — memory for agents that speak the Agent Client
Protocol (Grok Build's `grok agent stdio`, Cursor's `agent acp`, ...), driven
by a GUI such as Grok App, Zed or JetBrains.

The GUI starts this program in place of the agent; this program starts the
real agent and passes every byte through, except that it

  - adds the memory to each prompt BEFORE the agent sees it: the session's
    brief on its first prompt, and the recall for that prompt on every one
    (a text block put in front of the user's own, in ``session/prompt``);
  - archives each turn (the user's words, without our block, and the agent's
    streamed reply) when the agent answers the prompt;
  - hands the memory a session's waiting turns when the GUI goes away.

Nothing of the agent's or the GUI's changes, so both keep updating on their
own. Any command that is not an ACP session (``--version``, ``login``,
``models``, ...) is handed straight to the real agent with ``exec``.

FAIL-OPEN, like every hook here: no key configured, the memory unreachable, a
message we cannot read — the bytes go through untouched and the agent works
as if we were not there. The archive spools to disk across an outage
(hooks_api.AgentHooks).

Usage (an installer writes the wrapper the GUI is pointed at):

    brethof-brain-acp --real /path/to/grok -- agent --always-approve stdio

Found the shape 2026-11-18: Grok Build 1.0.89 answered NONE to "list every
secret word" straight, and the word only this program knew when run through
it. Grok's agent options go BEFORE ``stdio``.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from typing import Optional

from .config import STATE_DIR, Config, ensure_dirs
from .hooks_api import AgentHooks

RECALL_TIMEOUT_S = float(os.environ.get("BRETHOF_BRAIN_ACP_TIMEOUT_S", "8"))
HEADER = ("Context from the user's long-term memory (Brethof Brain), added before this "
          "message. Use what bears on the request; ignore the rest. Not part of the user's words.")


def is_session(args: list[str]) -> bool:
    """True when these arguments start an ACP session: Grok Build's
    ``agent [options] stdio``, Cursor's ``acp``/``agent acp``, or anything
    when BRETHOF_BRAIN_ACP_ALWAYS=1 (an agent that only ever speaks ACP)."""
    if os.environ.get("BRETHOF_BRAIN_ACP_ALWAYS") == "1":
        return True
    if not args:
        return False
    if args[0] == "agent" and "stdio" in args[1:]:
        return True
    return args[0] == "acp" or args[:2] == ["agent", "acp"]


def _log(msg: str) -> None:
    if os.environ.get("BRETHOF_BRAIN_DEBUG"):
        try:
            sys.stderr.write(f"brethof-brain-acp: {msg}\n")
            sys.stderr.flush()
        except Exception:                                           # noqa: BLE001
            pass


def _text_of(blocks) -> str:
    if not isinstance(blocks, list):
        return ""
    return "\n".join(str(b.get("text", "")) for b in blocks
                     if isinstance(b, dict) and b.get("type") == "text").strip()


class _Session:
    def __init__(self, hooks: Optional[AgentHooks]):
        self.hooks = hooks
        self.briefed = False
        self.chunks: list[str] = []
        self.lock = threading.Lock()      # one session's turns go up in order


class Middle:
    """The bookkeeping between the two streams; the pumps are in run()."""

    def __init__(self, cfg: Optional[Config] = None):
        try:
            self.cfg = cfg or Config.load()
        except Exception:                                           # noqa: BLE001
            self.cfg = None
        self.on = bool(self.cfg and self.cfg.configured())
        self.sessions: dict[str, _Session] = {}
        self.pending: dict = {}           # client request id -> what it was
        self.lock = threading.Lock()
        self.archiving: list[threading.Thread] = []

    # ── the session's memory hooks, one AgentHooks per ACP session ──────
    def _session(self, sid: str, cwd: str = "") -> _Session:
        with self.lock:
            s = self.sessions.get(sid)
            if s is None:
                hooks = None
                if self.on:
                    try:
                        hooks = AgentHooks(project=self.cfg.project_for(cwd or os.getcwd()),
                                           session_id=sid, config=self.cfg, timeout=RECALL_TIMEOUT_S)
                        hooks._next_index = _load_index(sid)
                    except Exception as e:                          # noqa: BLE001
                        _log(f"memory off for this session ({e})")
                s = self.sessions[sid] = _Session(hooks)
            return s

    # ── client -> agent ─────────────────────────────────────────────────
    def from_client(self, line: bytes) -> bytes:
        try:
            m = json.loads(line)
        except ValueError:
            return line
        if not isinstance(m, dict) or "method" not in m:
            return line                   # a reply to the agent's own request
        method, params, rid = m.get("method"), m.get("params") or {}, m.get("id")
        try:
            if method == "session/new" and rid is not None:
                self.pending[rid] = ("new", str(params.get("cwd") or ""))
            elif method == "session/load" and params.get("sessionId"):
                self._session(str(params["sessionId"]), str(params.get("cwd") or ""))
            elif method == "session/prompt" and params.get("sessionId"):
                sid = str(params["sessionId"])
                said = _text_of(params.get("prompt"))
                s = self._session(sid)
                s.chunks = []
                block = self._memory(s, said)
                if rid is not None:
                    self.pending[rid] = ("prompt", sid, said)
                if block:
                    params["prompt"].insert(0, {"type": "text", "text": block})
                    return (json.dumps(m, ensure_ascii=False) + "\n").encode("utf-8")
        except Exception as e:                                      # noqa: BLE001 — fail open
            _log(f"passed through unread ({type(e).__name__}: {e})")
        return line

    def _memory(self, s: _Session, said: str) -> str:
        if s.hooks is None:
            return ""
        parts = []
        if not s.briefed:
            s.briefed = True
            brief = s.hooks.session_start()
            if brief.strip():
                parts.append(brief.strip())
        recall = s.hooks.before_prompt_parts(said) if said else ""
        if recall.strip():
            parts.append(recall.strip())
        if not parts:
            return ""
        return "<memory>\n" + HEADER + "\n\n" + "\n\n".join(parts) + "\n</memory>"

    # ── agent -> client ─────────────────────────────────────────────────
    def from_agent(self, line: bytes) -> None:
        try:
            m = json.loads(line)
        except ValueError:
            return
        if not isinstance(m, dict):
            return
        try:
            if m.get("method") == "session/update":
                p = m.get("params") or {}
                u = p.get("update") or {}
                if u.get("sessionUpdate") == "agent_message_chunk":
                    c = u.get("content") or {}
                    if c.get("type") == "text":
                        self._session(str(p.get("sessionId") or "")).chunks.append(str(c.get("text") or ""))
                return
            if "method" in m or m.get("id") not in self.pending:
                return
            what = self.pending.pop(m["id"])
            if "result" not in m:
                return                    # an error answer: nothing to record
            r = m.get("result") or {}
            if what[0] == "new" and r.get("sessionId"):
                self._session(str(r["sessionId"]), what[1])
            elif what[0] == "prompt":
                _, sid, said = what
                s = self._session(sid)
                reply, s.chunks = "".join(s.chunks).strip(), []
                if s.hooks is not None and (said or reply):
                    t = threading.Thread(target=self._archive, args=(sid, s, said, reply), daemon=True)
                    t.start()
                    self.archiving.append(t)
        except Exception as e:                                      # noqa: BLE001
            _log(f"could not read an agent message ({type(e).__name__}: {e})")

    def _archive(self, sid: str, s: _Session, said: str, reply: str) -> None:
        with s.lock:                      # never the shared lock: a slow memory must not stall the stream
            # the turn numbers are reserved on disk FIRST: a GUI that closes
            # mid-call must not leave a resumed session reusing them
            _save_index(sid, s.hooks._next_index + bool(said.strip()) + bool(reply.strip()))
            s.hooks.archive(said, reply)

    def drain(self, timeout: float = 15.0) -> None:
        """Let the archives in flight finish before the program leaves."""
        import time
        end = time.time() + timeout
        for t in list(self.archiving):
            t.join(timeout=max(0.0, end - time.time()))

    def close(self) -> None:
        """The GUI went away: hand the memory every session's waiting turns."""
        for s in list(self.sessions.values()):
            if s.hooks is not None and s.hooks._next_index:
                try:
                    s.hooks.end_session()
                except Exception:                                   # noqa: BLE001
                    pass


# A resumed session continues its turn numbers (the archive orders by them).
def _index_path(sid: str) -> str:
    safe = "".join(c for c in sid if c.isalnum() or c in "-_")[:120] or "default"
    return os.path.join(STATE_DIR, f"acp-{safe}.json")


def _load_index(sid: str) -> int:
    try:
        with open(_index_path(sid), encoding="utf-8") as f:
            return int(json.load(f).get("next_index", 0))
    except Exception:                                               # noqa: BLE001
        return 0


def _save_index(sid: str, n: int) -> None:
    try:
        ensure_dirs()
        tmp = _index_path(sid) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"next_index": n}, f)
        os.replace(tmp, _index_path(sid))
    except Exception:                                               # noqa: BLE001
        pass


def run(real: str, args: list[str]) -> int:
    if not is_session(args):
        os.execvp(real, [real] + args)    # --version, login, models ...: theirs
    child = subprocess.Popen([real] + args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, bufsize=0)
    mid = Middle()
    _log(f"session through the memory ({'on' if mid.on else 'OFF: no key configured'})")

    def up() -> None:
        try:
            for line in sys.stdin.buffer:
                child.stdin.write(mid.from_client(line))
                child.stdin.flush()
        except (BrokenPipeError, OSError):
            pass
        finally:
            try:
                child.stdin.close()
            except OSError:
                pass

    threading.Thread(target=up, daemon=True).start()

    # A GUI closes its agent with a signal: finish what is in flight, hand
    # the memory the waiting turns, then go — the agent goes with us.
    import signal

    def leave(signum, _frame):
        try:
            child.terminate()
        except OSError:
            pass
        mid.drain()
        mid.close()
        os._exit(0)
    for sig in (signal.SIGTERM, signal.SIGINT, getattr(signal, "SIGHUP", None)):
        if sig is not None:
            try:
                signal.signal(sig, leave)
            except (ValueError, OSError):
                pass
    out = sys.stdout.buffer
    try:
        for line in child.stdout:
            mid.from_agent(line)          # noted FIRST: a GUI may close the moment it has the answer
            out.write(line)               # the agent's bytes, untouched
            out.flush()
    except (BrokenPipeError, OSError):
        pass
    code = child.wait()
    mid.drain()
    mid.close()
    return code


def main(argv: Optional[list[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    real = os.environ.get("BRETHOF_BRAIN_REAL_AGENT", "")
    if argv[:1] == ["--real"] and len(argv) > 1:
        real, argv = argv[1], argv[2:]
    if argv[:1] == ["--"]:
        argv = argv[1:]
    if not real:
        sys.stderr.write("brethof-brain-acp: which agent? pass --real /path/to/agent "
                         "(or set BRETHOF_BRAIN_REAL_AGENT)\n")
        return 2
    return run(real, argv)


if __name__ == "__main__":
    sys.exit(main())
