"""THE HUB CONTRACT (local-first, 2026-11-20) — every adapter reaches memory
through the hub's front door, the way `brethof-brain pair` set it up:

  1. the endpoint and key come from ~/.brethof-brain/config.json (or the
     BRETHOF_BRAIN_* environment), the default is the hub at :8600 — never
     the retired per-memory port, never the retired hosted plane;
  2. the key travels as `Authorization: Bearer` (the hub refuses X-API-Key);
  3. prompt context is asked as parts 1-7 — the legacy no-part blob never
     carries the history of decisions (part 7);
  4. no hosted remnant: no unlock, no passphrase, no idle lock.

The JS adapters are driven for real with node (tests/adapter_driver.mjs)
against a fake hub that records every request.
"""
from __future__ import annotations

import io
import json
import os
import pathlib
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
ADAPTERS = REPO / "adapters"
DRIVER = REPO / "tests" / "adapter_driver.mjs"
# spelled apart so this file does not trip its own scan
RETIRED = ("86" + "10", "brethof" + ".cloud", "bmv2" + "_", "/un" + "lock", "pass" + "phrase",
           "lock_after" + "_minutes", "lockAfter" + "Minutes", "x-api" + "-key")
JS_ADAPTERS = ("cline", "opencode", "dsh", "amp", "pi", "openclaw-gateway", "openclaw-gateway-ts")


def _adapter_files():
    for p in sorted(ADAPTERS.rglob("*")):
        if p.is_file() and "__pycache__" not in p.parts and "gemini-cli" not in p.parts:
            yield p


@pytest.mark.parametrize("needle", RETIRED)
def test_no_adapter_names_a_retired_endpoint_or_hosted_remnant(needle):
    hits = [str(p.relative_to(REPO)) for p in _adapter_files()
            if needle.lower() in p.read_text(encoding="utf-8", errors="replace").lower()]
    assert not hits, f"{needle!r} still in: {hits}"


def test_core_client_carries_no_hosted_remnant():
    for p in (REPO / "brethof_brain_client").glob("*.py"):
        text = p.read_text(encoding="utf-8").lower()
        for needle in RETIRED:
            assert needle.lower() not in text, f"{needle!r} in {p.name}"


def test_every_js_adapter_defaults_to_the_hub_and_sends_bearer():
    for rel in ("cline/lib/index.js", "opencode/lib/index.js", "dsh/lib/index.js",
                "amp/brethof-brain.ts", "pi/brethof-brain.ts",
                "openclaw-gateway/index.ts", "openclaw-gateway/index.mjs"):
        text = (ADAPTERS / rel).read_text(encoding="utf-8")
        assert "http://127.0.0.1:8600" in text, rel
        assert "config.json" in text, f"{rel} does not read the paired config file"
        assert "Bearer " in text, rel
        assert "[1, 2, 3, 4, 5, 6, 7]" in text, f"{rel} does not ask prompt parts 1-7"


# ── a fake hub ─────────────────────────────────────────────────────────────

class _Hub:
    def __init__(self):
        self.seen: list = []
        hub = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("content-length") or 0)) or b"{}")
                hub.seen.append({"path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()},
                                 "body": body})
                if self.path.endswith("/session-start"):
                    out = {"status": "ok", "injection": "BRIEF-TEXT"}
                elif self.path.endswith("/prompt-submit"):
                    part = body.get("part")
                    out = {"status": "ok", "injection": f"PART-{part}" if part else "LEGACY-BLOB"}
                else:
                    out = {"status": "ok", "archived": len(body.get("turns") or [])}
                data = json.dumps(out).encode()
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self):
        self.srv.shutdown()


@pytest.fixture
def hub(tmp_path, monkeypatch):
    h = _Hub()
    home = tmp_path / "home"
    home.mkdir()
    (home / "config.json").write_text(json.dumps({"endpoint": h.url, "api_key": "bd_contract_test"}))
    monkeypatch.setenv("BRETHOF_BRAIN_HOME", str(home))        # the JS adapters read it per run
    from brethof_brain_client import config as _config          # the Python client fixed it at import
    monkeypatch.setattr(_config, "CONFIG_PATH", str(home / "config.json"))
    for v in ("BRETHOF_BRAIN_ENDPOINT", "BRETHOF_BRAIN_API_KEY"):
        monkeypatch.delenv(v, raising=False)
    yield h
    h.close()


def _check(seen: list) -> None:
    assert seen, "the adapter never reached the hub"
    for r in seen:
        assert r["headers"].get("authorization") == "Bearer bd_contract_test", r["path"]
        assert "x-api-key" not in r["headers"]
    paths = [r["path"] for r in seen]
    assert "/v1/hooks/session-start" in paths
    parts = sorted(r["body"].get("part") or 0 for r in seen if r["path"] == "/v1/hooks/prompt-submit")
    assert parts == [1, 2, 3, 4, 5, 6, 7], parts
    stops = [r["body"] for r in seen if r["path"] == "/v1/hooks/stop"]
    assert stops, "nothing archived"
    kinds = [t["line_type"] for s in stops for t in s["turns"]]
    assert "user" in kinds and "assistant" in kinds


@pytest.mark.skipif(not shutil.which("node"), reason="node is not installed")
@pytest.mark.parametrize("adapter", JS_ADAPTERS)
def test_js_adapter_lifecycle_against_a_hub(hub, adapter):
    r = subprocess.run(["node", str(DRIVER), adapter, "contract", "what did we decide?", "we chose X"],
                       capture_output=True, text=True, timeout=60, env=dict(os.environ))
    assert r.returncode == 0, r.stderr[-2000:]
    out = json.loads(r.stdout.strip().splitlines()[-1])
    _check(hub.seen)
    assert "BRIEF-TEXT" in out["briefText"]
    ctx = out["contextText"]
    assert "PART-1" in ctx and "PART-7" in ctx and ctx.index("PART-1") < ctx.index("PART-7")
    assert "LEGACY-BLOB" not in ctx


def test_python_prompt_hook_without_a_part_asks_parts_1_to_7(hub, monkeypatch, capsys):
    """Every harness but Claude Code registers ONE prompt hook (no part
    argument): it must receive the joined parts, never the legacy blob."""
    from brethof_brain_client import hook
    from brethof_brain_client.config import Config
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(
        {"session_id": "s1", "prompt": "what did we decide?", "cwd": "/tmp"})))
    assert hook.main(["prompt-submit"]) == 0
    ctx = json.loads(capsys.readouterr().out)["hookSpecificOutput"]["additionalContext"]
    assert ctx.startswith("PART-1") and ctx.endswith("PART-7") and "LEGACY" not in ctx
    parts = sorted(r["body"].get("part") for r in hub.seen)
    assert parts == [1, 2, 3, 4, 5, 6, 7]
    assert Config.load().endpoint == hub.url          # the paired file, read


def test_python_prompt_hook_with_a_part_asks_just_that_part(hub, monkeypatch, capsys):
    from brethof_brain_client import hook
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(
        {"session_id": "s1", "prompt": "q", "cwd": "/tmp"})))
    assert hook.main(["prompt-submit", "7"]) == 0
    assert [r["body"].get("part") for r in hub.seen] == [7]


def test_agent_hooks_before_prompt_is_the_full_memory(hub):
    from brethof_brain_client.hooks_api import AgentHooks
    got = AgentHooks(project="contract", session_id="s").before_prompt("q")
    assert got.split("\n\n") == [f"PART-{n}" for n in range(1, 8)]


def test_default_endpoint_is_the_hub():
    from brethof_brain_client import DEFAULT_ENDPOINT
    assert DEFAULT_ENDPOINT == "http://127.0.0.1:8600"


def test_a_per_call_overlay_asks_ephemeral(hub):
    """A caller that hands the context to one model call only (MemorySession,
    the documented library usage) asks ephemerally, so the memory serves a
    record again on the next prompt instead of holding it back as seen."""
    import importlib.util
    from brethof_brain_client.hooks_api import AgentHooks
    AgentHooks(project="contract", session_id="s", ephemeral=True).before_prompt("q")
    assert [r["body"].get("ephemeral") for r in hub.seen] == [True] * 7
    hub.seen.clear()
    AgentHooks(project="contract", session_id="s").before_prompt("q")
    assert not any(r["body"].get("ephemeral") for r in hub.seen)
    spec = importlib.util.spec_from_file_location("ochooks", ADAPTERS / "openclaw" / "openclaw_hooks.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    assert m.MemorySession(project="contract", session_id="s").hooks.ephemeral is True
    assert m.MemorySession(project="contract", session_id="s", context_in_history=True).hooks.ephemeral is False
