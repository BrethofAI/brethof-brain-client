"""ADAPTER CONFORMANCE — the contract every customer plugin must satisfy.

Plugins are where this product breaks: each one hand-wires a foreign agent
platform to our API, on someone else's machine, with a customer's key. The
freshness test (test_adapter_freshness.py) proves an adapter's VOCABULARY is
current. This proves its BEHAVIOUR:

  A. FAIL-OPEN — memory must never break the user's session. No key, a dead
     key, an unreachable endpoint, a garbage response: every one degrades to
     "no memory" and returns, never raises. This is the promise that lets a
     customer wire memory into a production agent at all.
  B. CUSTOMER SURFACE ONLY — an adapter must never call, offer or name a tool
     the customer's key does not have (an owner-tier name is both a leak and
     a 404 for the customer).
  C. THE REAL WORK — session-start injects, turns archive, a fact saves, a
     rule saves as law, and both come back from search.
  D. NO SECRETS IN USER-VISIBLE TEXT — nothing an adapter returns may carry
     the API key, a tenant id, or our internal infrastructure names.

Live parts need a CUSTOMER-tier key in BRETHOF_MIND_CONFORMANCE_KEY (use a
disposable test tenant — section C writes). Without it those skip and the
offline contract (A, B, D) still runs everywhere.
"""
from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import sys
import time
import types
import urllib.request

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
ADAPTERS = REPO / "adapters"
ENDPOINT = os.environ.get("BRETHOF_MIND_CONFORMANCE_ENDPOINT",
                          "https://api.brethof.cloud").rstrip("/")
# A disposable project the live section writes into.
PROJECT = "plugin_conformance"

# Internal names that must never reach a customer's screen through an adapter.
FORBIDDEN_IN_OUTPUT = ("187.127", "mkt-cf", "prod-cf", "mind-pg", "mind-api",
                       "t_y6b7", "/opt/mind", "/run/keys", "pgvector",
                       "OLLAMA", "deepseek")


def _key() -> str:
    k = os.environ.get("BRETHOF_MIND_CONFORMANCE_KEY", "")
    if not k:
        pytest.skip("BRETHOF_MIND_CONFORMANCE_KEY not set — live section needs it")
    return k


def _load(path: pathlib.Path, name: str):
    """Import an adapter file by path (adapters are not importable packages)."""
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# ── the hermes provider needs its host platform's ABC; stub it ──────────────
def _hermes_provider_class():
    """Load the hermes plugin with a stand-in for Hermes' own imports. We are
    testing OUR file's behaviour, not Hermes — the real-loader path is proven
    separately by driving `hermes -z`."""
    if "agent" not in sys.modules:
        agent = types.ModuleType("agent")
        mp = types.ModuleType("agent.memory_provider")

        class MemoryProvider:            # minimal stand-in for the ABC
            pass

        mp.MemoryProvider = MemoryProvider
        agent.memory_provider = mp
        sys.modules["agent"] = agent
        sys.modules["agent.memory_provider"] = mp
    mod = _load(ADAPTERS / "hermes" / "brethofmind_cloud" / "__init__.py",
                "conformance_hermes_plugin")
    return mod.BrethofMindCloudProvider


def _openclaw_session_class():
    sys.path.insert(0, str(REPO))
    return _load(ADAPTERS / "openclaw" / "openclaw_hooks.py",
                 "conformance_openclaw").MemorySession


def live_customer_tools() -> set[str]:
    body = json.dumps({"jsonrpc": "2.0", "id": 1,
                       "method": "tools/list"}).encode()
    req = urllib.request.Request(
        ENDPOINT + "/mcp", data=body,
        headers={"Authorization": "Bearer " + _key(),
                 "Content-Type": "application/json",
                 "User-Agent": "brethof-mind-conformance/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return {t["name"] for t in json.load(r)["result"]["tools"]}


# ════════════════════════ A. FAIL-OPEN ══════════════════════════════════════
@pytest.mark.parametrize("key,endpoint,label", [
    ("", "https://api.brethof.cloud", "no key at all"),
    ("bm_live_deadbeefdeadbeefdeadbeefdeadbeef", "https://api.brethof.cloud",
     "key that does not exist"),
    ("bm_live_deadbeefdeadbeefdeadbeefdeadbeef", "http://127.0.0.1:9",
     "endpoint refusing connections"),
])
def test_hermes_provider_fails_open(monkeypatch, tmp_path, key, endpoint, label):
    """Every hermes memory hook degrades to nothing — never raises.

    HERMES_HOME is redirected at an empty dir on purpose: the provider resolves
    config env-first then from $HERMES_HOME/.env (by design, because not every
    Hermes entrypoint loads the user .env before plugins import). Without this
    redirect a developer's real key leaks in and the no-key case never runs."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("BRETHOF_MIND_API_KEY", key)
    monkeypatch.setenv("BRETHOF_MIND_ENDPOINT", endpoint)
    monkeypatch.setenv("HERMES_MEMORY_PROJECT", PROJECT)
    cls = _hermes_provider_class()
    p = cls()
    p.initialize("conformance-session")            # must not raise
    assert p.system_prompt_block() == "", f"{label}: injected something anyway"
    p.queue_prefetch("anything")
    assert p.prefetch("anything") == ""
    p.sync_turn("user said this", "assistant said that")   # must not raise
    # The deliberate tools answer with an error STRING, never an exception.
    out = p.handle_tool_call("brethofmind_search", {"query": "x"})
    assert isinstance(out, str) and out, f"{label}: tool call returned nothing"


def test_openclaw_session_refuses_to_start_without_a_key(monkeypatch):
    """OpenClaw's wrapper is constructed explicitly by the integrator, so an
    unconfigured key must raise a NAMED, actionable error at construction —
    not fail silently halfway through a run."""
    monkeypatch.setenv("BRETHOF_MIND_API_KEY", "")
    monkeypatch.setenv("BRETHOF_MIND_ENDPOINT", "https://api.brethof.cloud")
    from brethof_mind_client.client import ClientError
    cls = _openclaw_session_class()
    with pytest.raises(ClientError) as e:
        cls(project=PROJECT, session_id="conformance")
    assert "key" in str(e.value).lower()


def test_openclaw_session_fails_open_on_dead_endpoint(monkeypatch):
    monkeypatch.setenv("BRETHOF_MIND_API_KEY", "bm_live_deadbeefdeadbeef")
    monkeypatch.setenv("BRETHOF_MIND_ENDPOINT", "http://127.0.0.1:9")
    cls = _openclaw_session_class()
    s = cls(project=PROJECT, session_id="conformance", base_system_prompt="P")
    assert s.start() == "P"                  # base prompt survives, no memory
    assert s.build_context("hello") == ""
    s.record("u", "a")                       # must not raise


def test_grok_stop_hook_fails_open_on_garbage(tmp_path, monkeypatch):
    """The grok archiver is a hook: whatever happens, exit 0. A non-zero exit
    or a traceback would surface as a broken tool call in the user's CLI."""
    monkeypatch.setenv("BRETHOF_MIND_API_KEY", "")
    monkeypatch.setenv("BRETHOF_MIND_ENDPOINT", "http://127.0.0.1:9")
    import subprocess
    hook = ADAPTERS / "grok-build" / "grok_hook.py"
    for payload in ('{"transcriptPath": "/nonexistent/path.jsonl"}',
                    '{"not": "a known shape"}',
                    'not even json'):
        r = subprocess.run([sys.executable, str(hook), "stop"],
                           input=payload, text=True, capture_output=True,
                           timeout=60)
        assert r.returncode == 0, (
            f"grok stop hook exited {r.returncode} on {payload[:30]!r} — "
            f"a hook must always exit 0. stderr: {r.stderr[:300]}")


# ════════════════════ B. CUSTOMER SURFACE ONLY ══════════════════════════════
def test_hermes_tool_schemas_are_customer_shaped():
    """The tools hermes OFFERS its model must be our wrappers, and their
    descriptions must not teach owner-tier vocabulary."""
    cls = _hermes_provider_class()
    schemas = cls().get_tool_schemas()
    names = {s["name"] for s in schemas}
    assert names == {"brethofmind_search", "brethofmind_recall",
                     "brethofmind_save", "brethofmind_save_rule",
                     "brethofmind_delete"}, names
    blob = json.dumps(schemas).lower()
    for owner_only in ("query_raw", "search_chat_text", "semantic_search",
                       "save_record", "supersede_memory"):
        assert owner_only not in blob, f"owner tool '{owner_only}' in schemas"


def test_every_adapter_call_targets_a_live_customer_tool():
    """The tool names adapters actually SEND must all exist for a customer
    key — the freshness test covers text, this covers the live wire."""
    live = live_customer_tools()
    sent: set[str] = set()
    for path, kinds in ((ADAPTERS / "hermes" / "brethofmind_cloud" / "__init__.py",
                         "hermes"),
                        (ADAPTERS / "openclaw" / "openclaw_hooks.py", "openclaw")):
        text = path.read_text(encoding="utf-8")
        import re
        # calls look like _mcp("tool", ...) / _tool("tool", ...)
        sent |= set(re.findall(r"_(?:mcp|tool)\(\s*[\"']([a-z_]+)[\"']", text))
    assert sent, "found no tool calls to check — the probe is broken"
    dead = sent - live
    assert not dead, f"adapters call tools a customer key does not have: {dead}"


# ════════════════════ C. THE REAL WORK (live) ═══════════════════════════════
@pytest.mark.parametrize("adapter", ["hermes", "openclaw"])
def test_live_roundtrip(monkeypatch, adapter):
    """Session-start injects, a turn archives, a fact saves, a rule saves —
    through the adapter's own code, against the live service."""
    key = _key()
    monkeypatch.setenv("BRETHOF_MIND_API_KEY", key)
    monkeypatch.setenv("BRETHOF_MIND_ENDPOINT", ENDPOINT)
    monkeypatch.setenv("HERMES_MEMORY_PROJECT", PROJECT)
    stamp = str(int(time.time()))
    fact = (f"Conformance canary {stamp}: the {adapter} adapter completed a "
            f"live save through its own code path.")

    if adapter == "hermes":
        p = _hermes_provider_class()()
        p.initialize(f"conformance-{stamp}")
        block = p.system_prompt_block()
        p.sync_turn(f"probe {stamp}", "reply")
        saved = p.handle_tool_call("brethofmind_save",
                                   {"content": fact, "project": PROJECT})
        ruled = p.handle_tool_call("brethofmind_save_rule",
                                   {"content": "plugin_conformance is a "
                                               "disposable test project.",
                                    "scope": "project", "project": PROJECT})
        found = p.handle_tool_call("brethofmind_search",
                                   {"query": "conformance canary"})
    else:
        s = _openclaw_session_class()(project=PROJECT,
                                      session_id=f"conformance-{stamp}",
                                      base_system_prompt="P")
        block = s.start()
        env = s.record(f"probe {stamp}", "reply")
        assert env.get("status") == "ok", f"archive failed: {env}"
        saved = s.save_fact(fact, project=PROJECT)
        ruled = s.save_rule("plugin_conformance is a disposable test project.",
                            project=PROJECT)
        found = ""

    assert isinstance(block, str) and block, "session-start injected nothing"
    for label, out in (("save", saved), ("rule", ruled)):
        assert "error" not in out.lower(), f"{adapter} {label} failed: {out[:200]}"
    if found:
        assert "error" not in found.lower(), f"search failed: {found[:200]}"


# ════════════════ D. NOTHING SECRET IN USER-VISIBLE TEXT ════════════════════
def test_live_output_carries_no_secrets_or_infrastructure(monkeypatch):
    key = _key()
    monkeypatch.setenv("BRETHOF_MIND_API_KEY", key)
    monkeypatch.setenv("BRETHOF_MIND_ENDPOINT", ENDPOINT)
    monkeypatch.setenv("HERMES_MEMORY_PROJECT", PROJECT)
    p = _hermes_provider_class()()
    p.initialize("conformance-secrets")
    seen = "\n".join([
        p.system_prompt_block(),
        p.handle_tool_call("brethofmind_search", {"query": "conformance"}),
        p.handle_tool_call("brethofmind_delete",
                           {"project": PROJECT, "record_id": "nope_missing"}),
    ])
    assert key not in seen, "THE API KEY appeared in adapter output"
    hits = [n for n in FORBIDDEN_IN_OUTPUT if n.lower() in seen.lower()]
    assert not hits, f"internal names leaked to the user: {hits}"
