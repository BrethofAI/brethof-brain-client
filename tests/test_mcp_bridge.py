"""The plugin's memory tools over stdio (2026-10-04): the key comes from the
config `connect` saves, read on every request; not connected → a handshake,
no tools, and how to connect."""
import types

from brethof_brain_client import mcpbridge


def test_not_connected_answers_the_handshake_and_says_how_to_connect(monkeypatch):
    monkeypatch.setattr(mcpbridge.Config, "load", classmethod(lambda c: types.SimpleNamespace(configured=lambda: False)))
    init = mcpbridge.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}})
    assert init["result"]["protocolVersion"] == "2025-06-18" and "connect" in init["result"]["instructions"]
    assert mcpbridge.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"] == []
    assert mcpbridge.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    call = mcpbridge.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "search_brain"}})
    assert "connect" in call["error"]["message"]


def test_connected_forwards_and_reads_the_config_each_time(monkeypatch):
    seen = []

    class C:
        def __init__(self, cfg, timeout=None):
            pass

        def post(self, path, payload, timeout=None):
            seen.append((path, payload["method"]))
            return {"jsonrpc": "2.0", "id": payload.get("id"), "result": {"tools": [{"name": "search_brain"}]}}
    loads = []
    monkeypatch.setattr(mcpbridge.Config, "load", classmethod(lambda c: loads.append(1) or types.SimpleNamespace(configured=lambda: True)))
    monkeypatch.setattr(mcpbridge, "Client", C)
    out = mcpbridge.handle({"jsonrpc": "2.0", "id": 7, "method": "tools/list"})
    assert out["result"]["tools"][0]["name"] == "search_brain" and seen == [("/v1/mcp", "tools/list")]
    mcpbridge.handle({"jsonrpc": "2.0", "id": 8, "method": "tools/list"})
    assert len(loads) == 2                      # a connect mid-session is picked up


def test_the_plugin_needs_no_key_at_install_and_sets_no_endpoint_default():
    import json
    import pathlib
    root = pathlib.Path(__file__).resolve().parent.parent
    uc = json.loads((root / ".claude-plugin" / "plugin.json").read_text())["userConfig"]
    assert uc["api_key"]["required"] is False
    # a default here is exported to the hooks and would outrank the hosted
    # address `connect` saved
    assert "default" not in uc["endpoint"] and "default" not in uc["project"]
    mcp = json.loads((root / ".mcp.json").read_text())["mcpServers"]["brain"]
    assert mcp["type"] == "stdio" and "run_bridge.sh" in mcp["args"][0]
