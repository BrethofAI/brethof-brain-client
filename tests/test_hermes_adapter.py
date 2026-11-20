"""The Hermes adapter is a MemoryProvider: its lifecycle IS the ambient
contract. These pin the wiring without Hermes installed — a stub base class
stands in for agent.memory_provider — and the box is a fake urlopen."""
import importlib.util
import json
import pathlib
import sys
import types
import urllib.error

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
ADAPTER = ROOT / "adapters" / "hermes" / "__init__.py"


@pytest.fixture
def provider_module(monkeypatch, tmp_path):
    # Hermes's base class, stubbed with the abstract surface the loader relies on.
    agent = types.ModuleType("agent")
    mp = types.ModuleType("agent.memory_provider")

    class MemoryProvider:  # noqa: D401 — stand-in
        pass

    mp.MemoryProvider = MemoryProvider
    agent.memory_provider = mp
    monkeypatch.setitem(sys.modules, "agent", agent)
    monkeypatch.setitem(sys.modules, "agent.memory_provider", mp)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("BRETHOF_BRAIN_HOME", str(tmp_path / "nohome"))
    monkeypatch.setenv("BRETHOF_BRAIN_API_KEY", "bd_test")
    monkeypatch.setenv("BRETHOF_BRAIN_ENDPOINT", "http://hub.test:8600/")
    monkeypatch.setenv("BRETHOF_BRAIN_PROJECT", "rigproj")
    spec = importlib.util.spec_from_file_location("brethof_hermes", ADAPTER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Resp:
    def __init__(self, body: dict, status: int = 200):
        self._body = json.dumps(body).encode()
        self.status = status

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _fake_urlopen(calls, answers):
    """answers: a list of (status, body) consumed per call, or a function of
    the request body (the prompt parts are asked in parallel, so their order
    is not fixed); status >= 400 raises HTTPError."""
    import threading
    lock = threading.Lock()

    def urlopen(req, timeout=None):
        body_in = json.loads(req.data.decode())
        with lock:
            calls.append((req.full_url, body_in, dict(req.headers), timeout))
            status, body = answers(req.full_url, body_in) if callable(answers) else answers.pop(0)
        if status >= 400:
            raise urllib.error.HTTPError(req.full_url, status, "x", {}, None)
        return _Resp(body, status)
    return urlopen


def test_config_precedence_env_then_hermes_env_file_then_client_file(provider_module, monkeypatch, tmp_path):
    (tmp_path / ".env").write_text("BRETHOF_BRAIN_PROJECT=fromfile\n")
    cfg = provider_module.load_config()
    assert cfg["project"] == "rigproj"          # env wins over the .env file
    assert cfg["endpoint"] == "http://hub.test:8600"   # trailing slash stripped
    monkeypatch.delenv("BRETHOF_BRAIN_PROJECT")
    assert provider_module.load_config()["project"] == "fromfile"


def test_default_endpoint_is_the_hubs_front_door(provider_module, monkeypatch):
    monkeypatch.delenv("BRETHOF_BRAIN_ENDPOINT")
    assert provider_module.load_config()["endpoint"] == "http://127.0.0.1:8600"


def test_the_paired_config_file_is_read(provider_module, monkeypatch, tmp_path):
    for v in ("BRETHOF_BRAIN_ENDPOINT", "BRETHOF_BRAIN_API_KEY"):
        monkeypatch.delenv(v)
    home = tmp_path / "paired"
    home.mkdir()
    (home / "config.json").write_text(json.dumps({"endpoint": "https://hub.example/m/main",
                                                  "api_key": "bd_paired"}))
    monkeypatch.setenv("BRETHOF_BRAIN_HOME", str(home))
    cfg = provider_module.load_config()
    assert cfg["endpoint"] == "https://hub.example/m/main" and cfg["api_key"] == "bd_paired"
    assert ("api.brethof" + ".cloud") not in ADAPTER.read_text()   # the retired plane, spelled apart so the guards do not trip on this test


def test_lifecycle_maps_onto_the_three_hooks(provider_module, monkeypatch):
    def answers(url, body):
        if url.endswith("/session-start"):
            return 200, {"status": "ok", "injection": "BRIEF"}
        if url.endswith("/prompt-submit"):
            return 200, {"status": "ok", "injection": f"PART{body['part']}" if body["part"] in (1, 7) else ""}
        return 200, {"status": "ok"}
    calls = []
    monkeypatch.setattr(provider_module.urllib.request, "urlopen", _fake_urlopen(calls, answers))
    p = provider_module.BrethofBrainProvider()
    assert p.is_available()
    p.initialize("sess-1", hermes_home="/x", platform="cli", agent_context="primary")
    assert p.system_prompt_block() == "BRIEF"
    # parts 1-7, joined in order (part 7 = the history of decisions)
    assert p.prefetch("what is the hub?") == "PART1\n\nPART7"
    p.sync_turn("hello", "hi there", session_id="sess-1")
    paths = [c[0].rsplit("/", 2)[-1] for c in calls]
    assert paths == ["session-start"] + ["prompt-submit"] * 7 + ["stop"]
    assert calls[0][1] == {"project": "rigproj", "source": "startup", "session_id": "sess-1"}
    asked = sorted(c[1]["part"] for c in calls[1:8])
    assert asked == [1, 2, 3, 4, 5, 6, 7]
    assert all(c[1]["prompt"] == "what is the hub?" and c[1]["session_id"] == "sess-1" for c in calls[1:8])
    turns = calls[8][1]["turns"]
    assert [t["line_type"] for t in turns] == ["user", "assistant"]
    assert [t["index"] for t in turns] == [0, 1] and all(t["embed"] for t in turns)
    assert all(c[2]["Authorization"] == "Bearer bd_test" for c in calls)
    assert not any("X-api-key" in c[2] or "X-API-Key" in c[2] for c in calls)
    assert p.get_tool_schemas() == []            # tools ride Hermes's MCP client


def test_non_primary_contexts_never_write(provider_module, monkeypatch):
    calls, answers = [], [(200, {"injection": ""})]
    monkeypatch.setattr(provider_module.urllib.request, "urlopen", _fake_urlopen(calls, answers))
    p = provider_module.BrethofBrainProvider()
    p.initialize("cron-1", agent_context="cron")
    p.sync_turn("a", "b")
    assert len(calls) == 1                       # session-start only, no archive


def test_no_unlock_remnant_a_refusal_is_just_a_failure(provider_module, monkeypatch):
    calls, answers = [], [(423, {})]
    monkeypatch.setattr(provider_module.urllib.request, "urlopen", _fake_urlopen(calls, answers))
    p = provider_module.BrethofBrainProvider()
    p.initialize("s")
    assert p.system_prompt_block() == "" and len(calls) == 1
    text = ADAPTER.read_text()
    assert "/unlock" not in text and "passphrase" not in text.lower()


def test_fail_open_on_any_box_error(provider_module, monkeypatch):
    def boom(req, timeout=None):
        raise OSError("box down")
    monkeypatch.setattr(provider_module.urllib.request, "urlopen", boom)
    p = provider_module.BrethofBrainProvider()
    p.initialize("s")
    assert p.system_prompt_block() == "" and p.prefetch("x") == ""
    p.sync_turn("a", "b")                        # no raise


def test_register_hands_the_provider_to_hermes(provider_module):
    got = {}

    class Ctx:
        def register_memory_provider(self, provider):
            got["p"] = provider

    provider_module.register(Ctx())
    assert got["p"].name == "brethof-brain"


def test_manifest_and_skills_ship_together():
    # a text check, never a YAML parse: CI installs only pytest and the client (no pyyaml)
    d = ROOT / "adapters" / "hermes"
    text = (d / "plugin.yaml").read_text()
    assert "name: brethof-brain" in text
    for s in ("recall", "onboard", "curate"):
        assert (d / "skills" / s / "SKILL.md").exists()
