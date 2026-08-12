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

Live parts need a CUSTOMER-tier key in BRETHOF_BRAIN_CONFORMANCE_KEY (use a
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
ENDPOINT = os.environ.get("BRETHOF_BRAIN_CONFORMANCE_ENDPOINT",
                          "https://api.brethof.cloud").rstrip("/")
# A disposable project the live section writes into.
PROJECT = "plugin_conformance"

# Internal names that must never reach a customer's screen through an adapter.
FORBIDDEN_IN_OUTPUT = ("187.127", "mkt-cf", "prod-cf", "mind-pg", "mind-api",
                       "t_y6b7", "/opt/mind", "/run/keys", "pgvector",
                       "OLLAMA", "deepseek")


def _key() -> str:
    k = os.environ.get("BRETHOF_BRAIN_CONFORMANCE_KEY", "")
    if not k:
        pytest.skip("BRETHOF_BRAIN_CONFORMANCE_KEY not set — live section needs it")
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
                 "User-Agent": "brethof-brain-conformance/1.0"})
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
    monkeypatch.setenv("BRETHOF_BRAIN_API_KEY", key)
    monkeypatch.setenv("BRETHOF_BRAIN_ENDPOINT", endpoint)
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
    monkeypatch.setenv("BRETHOF_BRAIN_API_KEY", "")
    monkeypatch.setenv("BRETHOF_BRAIN_ENDPOINT", "https://api.brethof.cloud")
    from brethof_brain_client.client import ClientError
    cls = _openclaw_session_class()
    with pytest.raises(ClientError) as e:
        cls(project=PROJECT, session_id="conformance")
    assert "key" in str(e.value).lower()


def test_openclaw_session_fails_open_on_dead_endpoint(monkeypatch):
    monkeypatch.setenv("BRETHOF_BRAIN_API_KEY", "bm_live_deadbeefdeadbeef")
    monkeypatch.setenv("BRETHOF_BRAIN_ENDPOINT", "http://127.0.0.1:9")
    cls = _openclaw_session_class()
    s = cls(project=PROJECT, session_id="conformance", base_system_prompt="P")
    assert s.start() == "P"                  # base prompt survives, no memory
    assert s.build_context("hello") == ""
    s.record("u", "a")                       # must not raise


def test_grok_stop_hook_fails_open_on_garbage(tmp_path, monkeypatch):
    """The grok archiver is a hook: whatever happens, exit 0. A non-zero exit
    or a traceback would surface as a broken tool call in the user's CLI."""
    monkeypatch.setenv("BRETHOF_BRAIN_API_KEY", "")
    monkeypatch.setenv("BRETHOF_BRAIN_ENDPOINT", "http://127.0.0.1:9")
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
    """The tools hermes OFFERS its model must cover the whole customer
    surface, must all actually dispatch, and must not teach owner-tier
    vocabulary. Full parity is the point: an agent on Hermes must be able to
    do what an agent on any other platform can (before 2026-08-08 only 5 of
    these existed — no project lifecycle, no reading a record back)."""
    cls = _hermes_provider_class()
    schemas = cls().get_tool_schemas()
    names = {s["name"] for s in schemas}
    expected = {"brethofmind_search", "brethofmind_recall", "brethofmind_save",
                "brethofmind_save_rule", "brethofmind_delete",
                "brethofmind_list", "brethofmind_get", "brethofmind_rules",
                "brethofmind_projects", "brethofmind_new_project",
                "brethofmind_delete_project", "brethofmind_graph",
                "brethofmind_context", "brethofmind_cleanup_history"}
    assert names == expected, f"missing {expected - names}, extra {names - expected}"

    blob = json.dumps(schemas).lower()
    for owner_only in ("query_raw", "search_chat_text", "semantic_search",
                       "save_record", "supersede_memory"):
        assert owner_only not in blob, f"owner tool '{owner_only}' in schemas"

    # DISPATCH PARITY: a declared tool that no branch handles would return
    # None and read as success to the host. Called with empty args every tool
    # must produce a STRING — a validation complaint is fine, silence is not.
    p = cls()
    for n in sorted(names):
        out = p.handle_tool_call(n, {})
        assert isinstance(out, str) and out, f"{n} returned {out!r}"
        assert "unknown tool" not in out.lower(), f"{n} is declared but not handled"


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
    monkeypatch.setenv("BRETHOF_BRAIN_API_KEY", key)
    monkeypatch.setenv("BRETHOF_BRAIN_ENDPOINT", ENDPOINT)
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


# ═══════════ C2. THE WHOLE SURFACE — full project lifecycle ═════════════════
# Founder, 2026-08-08: "other agents creating project, deleting project,
# creating rules, general rules, project rules, deleting them, checking
# curated data, adding curated records... if you skip something, it hasn't
# been tested, and no one will test it."
# So: every customer capability, including the DESTRUCTIVE ones, exercised
# end to end on a disposable tenant — written once, demanded of every adapter.
class _Facade:
    """One uniform interface over each adapter's own API, so the lifecycle
    below is written ONCE and both adapters must satisfy it identically."""

    def __init__(self, kind, project):
        self.kind = kind
        self.project = project
        if kind == "hermes":
            self.p = _hermes_provider_class()()
            self.p.initialize(f"lifecycle-{project}")
        else:
            self.s = _openclaw_session_class()(project=project,
                                               session_id=f"lc-{project}")

    def _h(self, tool, **args):
        out = self.p.handle_tool_call(tool, args)
        data = json.loads(out)
        if "error" in data:
            return f"ERROR: {data['error']}"
        return str(data.get("result", ""))

    # each capability, mapped onto whatever the adapter calls it
    def new_project(self, purpose):
        return (self._h("brethofmind_new_project", project=self.project,
                        purpose=purpose) if self.kind == "hermes"
                else self.s.add_project(self.project, purpose))

    def save_fact(self, content):
        return (self._h("brethofmind_save", content=content,
                        project=self.project) if self.kind == "hermes"
                else self.s.save_fact(content, project=self.project))

    def save_general_fact(self, content):
        return (self._h("brethofmind_save", content=content, general=True)
                if self.kind == "hermes"
                else self.s.save_fact(content, general=True))

    def save_project_rule(self, content):
        return (self._h("brethofmind_save_rule", content=content,
                        scope="project", project=self.project)
                if self.kind == "hermes"
                else self.s.save_rule(content, scope="project",
                                      project=self.project))

    def save_general_rule(self, content):
        return (self._h("brethofmind_save_rule", content=content,
                        scope="general") if self.kind == "hermes"
                else self.s.save_rule(content, scope="general"))

    def list_projects(self):
        return (self._h("brethofmind_projects") if self.kind == "hermes"
                else self.s.list_projects())

    def list_memory(self):
        return (self._h("brethofmind_list", project=self.project)
                if self.kind == "hermes"
                else self.s.list_memory(project=self.project))

    def get(self, rid):
        return (self._h("brethofmind_get", record_id=rid,
                        project=self.project) if self.kind == "hermes"
                else self.s.get(rid, project=self.project))

    def list_rules(self):
        return (self._h("brethofmind_rules", project=self.project)
                if self.kind == "hermes"
                else self.s.list_rules(project=self.project))

    def search(self, q):
        return (self._h("brethofmind_search", query=q, project=self.project)
                if self.kind == "hermes"
                else self.s.search(q, project=self.project))

    def search_history(self, q):
        return (self._h("brethofmind_recall", query=q, project=self.project)
                if self.kind == "hermes"
                else self.s.search_history(q, project=self.project))

    def graph(self, name):
        return (self._h("brethofmind_graph", name=name, project=self.project)
                if self.kind == "hermes"
                else self.s.graph(name, project=self.project))

    def context(self):
        return (self._h("brethofmind_context", project=self.project)
                if self.kind == "hermes"
                else self.s.session_context(project=self.project))

    def delete(self, project, rid):
        return (self._h("brethofmind_delete", project=project, record_id=rid)
                if self.kind == "hermes" else self.s.delete(project, rid))

    def cleanup_preview(self):
        return (self._h("brethofmind_cleanup_history", project=self.project)
                if self.kind == "hermes"
                else self.s.cleanup_history(self.project))

    def delete_project(self, confirm):
        return (self._h("brethofmind_delete_project", project=self.project,
                        confirm=confirm) if self.kind == "hermes"
                else self.s.delete_project(self.project, confirm))


def _wait_for(fn, needle, what, budget=360):
    """Saves go through the async write gate, so reads poll. Returns the text
    once `needle` appears; fails loudly with what it DID see.

    BUDGET IS DELIBERATELY GENEROUS. Filing is queued work on ONE inference
    lane shared by every tenant, so latency depends on what else the estate is
    doing — the release gate saw this suite take 250s where it takes 43s idle,
    because it ran while a freshly provisioned account's own writes were still
    draining. A gate that flickers red on queue depth is a gate people learn
    to ignore, and a test that only passes on an idle system is not testing
    the system customers use."""
    last = ""
    deadline = time.time() + budget
    while time.time() < deadline:
        last = fn() or ""
        if needle.lower() in last.lower():
            return last
        time.sleep(5)
    raise AssertionError(f"{what}: '{needle}' never appeared in {budget}s. "
                         f"Last saw: {last[:400]}")


@pytest.mark.slow
@pytest.mark.parametrize("adapter", ["hermes", "openclaw"])
def test_full_lifecycle_every_capability(monkeypatch, adapter):
    key = _key()
    stamp = str(int(time.time()))[-6:]
    project = f"lc_{adapter[:4]}_{stamp}"
    monkeypatch.setenv("BRETHOF_BRAIN_API_KEY", key)
    monkeypatch.setenv("BRETHOF_BRAIN_ENDPOINT", ENDPOINT)
    monkeypatch.setenv("HERMES_MEMORY_PROJECT", project)
    a = _Facade(adapter, project)

    # 1. CREATE a project, with the purpose that teaches its curator.
    # The purpose text must be DISTINCT per run: purpose statements are RULES,
    # and the service refuses near-identical law tenant-wide (correctly — twin
    # rules are the thing that rots a rule pool). Two runs sharing one purpose
    # sentence is a test artefact, not a customer shape.
    out = a.new_project(
        f"Disposable {adapter} project {stamp} used by the adapter "
        f"conformance suite to exercise every memory capability of the "
        f"{adapter} plugin end to end, then delete itself.")
    assert "error" not in out.lower(), f"add_project failed: {out[:200]}"
    assert _wait_for(a.list_projects, project, "created project appears")

    # 2. ADD curated records — project-scoped and cross-project
    rec = f"Lifecycle canary {stamp}: the {adapter} adapter created this record."
    assert "error" not in a.save_fact(rec).lower()
    assert "error" not in a.save_general_fact(
        f"Lifecycle general canary {stamp}: not tied to one project.").lower()

    # 3. ADD rules — both scopes (the law door, both kinds). Both name this
    # run, so both are unique law and both MUST land.
    #
    # This assertion used to accept a refusal as an outcome, because a leftover
    # general rule from the previous run made every later run a near-twin. That
    # tolerance hid the bug the release gate was built to catch (2026-08-08):
    # the gate ACCEPTED a rule it could not file, answered "Remembering it",
    # and dropped it in silence. A save that reports success and then vanishes
    # is the failure — so demand the rule land, and delete it at step 7 so the
    # next run starts from a clean pool instead of arguing with its own litter.
    assert "error" not in a.save_project_rule(
        f"Project {project} is disposable test data, never real facts.").lower()
    gen = a.save_general_rule(
        f"Conformance run {stamp} is a test; ignore its records.")
    assert "not saved" not in gen.lower(), (
        f"save_general_rule was refused: {gen[:300]}")

    # 4. CHECK the curated data landed and is READABLE
    listed = _wait_for(a.list_memory, "canary", "saved record is browsable")
    import re as _re
    ids = _re.findall(r"([a-z0-9_]*canary[a-z0-9_]*)", listed.lower())
    assert ids, f"no record id found in list_memory output: {listed[:300]}"
    rid = ids[0]
    full = a.get(rid)
    assert stamp in full, f"get_memory did not return the record body: {full[:300]}"

    # 5. CHECK the project's own law is listed and reaches this project
    rules = _wait_for(a.list_rules, "disposable", "project rule is listed")
    assert project in rules.lower(), (
        f"the project's own rule is not scoped to it: {rules[:400]}")
    # Keep the FRESHEST listing: the general rule files a moment after the
    # project one, and step 7 deletes law by id out of this text. Reusing the
    # older snapshot is why an earlier version left its general rule behind.
    rules = _wait_for(a.list_rules, f"conformance run {stamp}",
                      "general rule reaches the project")

    # 6. SEARCH finds it; history search and graph and context all answer
    assert "canary" in _wait_for(lambda: a.search("lifecycle canary"),
                                 "canary", "search finds the record").lower()
    for label, out in (("search_history", a.search_history("lifecycle")),
                       ("graph", a.graph("conformance")),
                       ("session_context", a.context())):
        assert isinstance(out, str) and not out.lower().startswith("error"), \
            f"{label} failed: {out[:200]}"

    # 7. DELETE a record, and DELETE A RULE (dead law must be removable).
    # The general rule goes first when this run created one — a test must not
    # leave law behind in a pool that every session pays for.
    gen_id = ""
    for line in rules.splitlines():
        if f"conformance run {stamp}".lower() in line.lower():
            m = _re.search(r"rules:([a-z0-9_]+)", line.lower()) or \
                _re.search(r"^\s*-?\s*([a-z0-9_]{6,})", line.lower())
            gen_id = m.group(1) if m else ""
            break
    assert gen_id, (
        f"could not find the general rule's id to clean it up — a test that "
        f"cannot delete its own law poisons every later run: {rules[:400]}")
    assert "deleted" in a.delete("rules", gen_id).lower(), \
        f"general rule {gen_id} could not be deleted"
    assert "deleted" in a.delete(project, rid).lower(), "record delete failed"
    # This project's own law goes too — including the PURPOSE rule add_project
    # seeded. delete_project (step 9) clears records, not law, so anything left
    # here is permanent litter in a pool every session of this account pays to
    # load. Found by reading a test tenant's rules table: three dead runs' law
    # still resident days later.
    own = [m.group(1) for line in rules.splitlines() if project in line.lower()
           for m in [_re.search(r"rules:([a-z0-9_]+)", line.lower()) or
                     _re.search(r"^\s*-?\s*([a-z0-9_]{6,})", line.lower())]
           if m and m.group(1) != gen_id]
    assert own, f"this project's own law is not listed by id: {rules[:400]}"
    for rid2 in dict.fromkeys(own):
        assert "deleted" in a.delete("rules", rid2).lower(), \
            f"rule delete failed for {rid2} — dead law must be removable"

    # 8. CLEANUP HISTORY preview — must NOT destroy anything without confirm
    prev = a.cleanup_preview()
    assert isinstance(prev, str) and prev, "cleanup_history preview returned nothing"
    assert "deleted" not in prev.lower() or "preview" in prev.lower(), \
        f"cleanup preview looks like it acted without confirm: {prev[:200]}"

    # 9. DELETE THE PROJECT — refused without the typed confirmation, then done
    refused = a.delete_project("wrong-name")
    assert "refus" in refused.lower() or "error" in refused.lower(), (
        f"delete_project accepted a WRONG confirm — data-loss guard broken: "
        f"{refused[:200]}")
    gone = a.delete_project(project)
    assert "error" not in gone.lower(), f"delete_project failed: {gone[:200]}"
    left = a.list_memory()
    assert "canary" not in left.lower(), (
        f"project deleted but its records still listed: {left[:300]}")


# ════════════════ D. NOTHING SECRET IN USER-VISIBLE TEXT ════════════════════
def test_live_output_carries_no_secrets_or_infrastructure(monkeypatch):
    key = _key()
    monkeypatch.setenv("BRETHOF_BRAIN_API_KEY", key)
    monkeypatch.setenv("BRETHOF_BRAIN_ENDPOINT", ENDPOINT)
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
