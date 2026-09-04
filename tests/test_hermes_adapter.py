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
    monkeypatch.setenv("BRETHOF_BRAIN_API_KEY", "bmv2_test")
    monkeypatch.setenv("BRETHOF_BRAIN_ENDPOINT", "http://box.test:8610/")
    monkeypatch.setenv("BRETHOF_BRAIN_PROJECT", "rigproj")
    monkeypatch.delenv("BRETHOF_BRAIN_UNLOCK_PASSPHRASE", raising=False)
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
    """answers: list of (status, body) consumed per call; 423 raises HTTPError."""
    def urlopen(req, timeout=None):
        calls.append((req.full_url, json.loads(req.data.decode()), dict(req.headers), timeout))
        status, body = answers.pop(0)
        if status >= 400:
            raise urllib.error.HTTPError(req.full_url, status, "x", {}, None)
        return _Resp(body, status)
    return urlopen


def test_config_precedence_env_then_hermes_env_file_then_client_file(provider_module, monkeypatch, tmp_path):
    (tmp_path / ".env").write_text("BRETHOF_BRAIN_LOCK_AFTER_MINUTES=30\nBRETHOF_BRAIN_PROJECT=fromfile\n")
    cfg = provider_module.load_config()
    assert cfg["project"] == "rigproj"          # env wins over the .env file
    assert cfg["lock_after_minutes"] == 30       # the .env file fills what env lacks
    assert cfg["endpoint"] == "http://box.test:8610"   # trailing slash stripped
    monkeypatch.delenv("BRETHOF_BRAIN_PROJECT")
    assert provider_module.load_config()["project"] == "fromfile"


def test_default_endpoint_is_the_customers_box(provider_module, monkeypatch):
    monkeypatch.delenv("BRETHOF_BRAIN_ENDPOINT")
    assert provider_module.load_config()["endpoint"] == "http://127.0.0.1:8610"
    assert ("api.brethof" + ".cloud") not in ADAPTER.read_text()   # the retired plane, spelled apart so the guards do not trip on this test


def test_lifecycle_maps_onto_the_three_hooks(provider_module, monkeypatch):
    calls, answers = [], [(200, {"status": "ok", "injection": "BRIEF"}),
                          (200, {"status": "ok", "injection": "RECALL"}),
                          (200, {"status": "ok"})]
    monkeypatch.setattr(provider_module.urllib.request, "urlopen", _fake_urlopen(calls, answers))
    p = provider_module.BrethofBrainProvider()
    assert p.is_available()
    p.initialize("sess-1", hermes_home="/x", platform="cli", agent_context="primary")
    assert p.system_prompt_block() == "BRIEF"
    assert p.prefetch("what is the hub?") == "RECALL"
    p.sync_turn("hello", "hi there", session_id="sess-1")
    paths = [c[0].rsplit("/", 2)[-1] for c in calls]
    assert paths == ["session-start", "prompt-submit", "stop"]
    assert calls[0][1] == {"project": "rigproj", "source": "startup", "session_id": "sess-1"}
    assert calls[1][1]["prompt"] == "what is the hub?" and calls[1][1]["session_id"] == "sess-1"
    turns = calls[2][1]["turns"]
    assert [t["line_type"] for t in turns] == ["user", "assistant"]
    assert [t["index"] for t in turns] == [0, 1] and all(t["embed"] for t in turns)
    assert calls[0][2]["Authorization"] == "Bearer bmv2_test"
    assert p.get_tool_schemas() == []            # tools ride Hermes's MCP client


def test_non_primary_contexts_never_write(provider_module, monkeypatch):
    calls, answers = [], [(200, {"injection": ""})]
    monkeypatch.setattr(provider_module.urllib.request, "urlopen", _fake_urlopen(calls, answers))
    p = provider_module.BrethofBrainProvider()
    p.initialize("cron-1", agent_context="cron")
    p.sync_turn("a", "b")
    assert len(calls) == 1                       # session-start only, no archive


def test_locked_hosted_memory_is_unlocked_once_and_retried(provider_module, monkeypatch):
    monkeypatch.setenv("BRETHOF_BRAIN_UNLOCK_PASSPHRASE", "open-sesame")
    monkeypatch.setenv("BRETHOF_BRAIN_LOCK_AFTER_MINUTES", "60")
    calls, answers = [], [(423, {}), (200, {"ok": True}), (200, {"injection": "BRIEF"})]
    monkeypatch.setattr(provider_module.urllib.request, "urlopen", _fake_urlopen(calls, answers))
    p = provider_module.BrethofBrainProvider()
    p.initialize("s", agent_context="primary")
    assert p.system_prompt_block() == "BRIEF"
    assert calls[1][0].endswith("/unlock")
    assert calls[1][1] == {"passphrase": "open-sesame", "idle_seconds": 3600}
    assert "Authorization" not in calls[1][2]    # the passphrase IS the authentication
    assert calls[2][0].endswith("/session-start")


def test_without_a_passphrase_a_locked_memory_is_reported_not_opened(provider_module, monkeypatch):
    calls, answers = [], [(423, {})]
    monkeypatch.setattr(provider_module.urllib.request, "urlopen", _fake_urlopen(calls, answers))
    p = provider_module.BrethofBrainProvider()
    p.initialize("s")
    assert p.system_prompt_block() == "" and len(calls) == 1


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
