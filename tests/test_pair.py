"""brethof-brain pair (2026-11-17, the local-first brain): the hub's owner
approves the code; this device's key lands in the config and is never printed."""
import json
import types

import pytest

from brethof_brain_client import cli


def _run(monkeypatch, capsys, answers, hub="http://127.0.0.1:8600", memory=""):
    calls = []

    def post(url, body, timeout=30.0):
        calls.append((url.rsplit("/", 1)[-1], body))
        return answers.pop(0)
    monkeypatch.setattr(cli, "_post_json", post)
    rc = cli.cmd_pair(types.SimpleNamespace(hub=hub, name="laptop", memory=memory), sleep=lambda s: None)
    return rc, calls, capsys.readouterr()


def test_approved_writes_key_and_never_prints_it(monkeypatch, capsys):
    key = "bd_" + "k" * 43
    rc, calls, out = _run(monkeypatch, capsys, [
        (200, {"ok": True, "pair": "pr_1", "code": "ABC-DEF", "secret": "SEKRET", "expires_in": 900,
               "approve_at": "http://127.0.0.1:8600/settings"}),
        (200, {"ok": True, "state": "pending"}),
        (200, {"ok": True, "state": "approved", "key": key, "memories": ["main"]}),
    ])
    assert rc == 0
    assert "ABC-DEF" in out.out and key not in out.out + out.err and "SEKRET" not in out.out + out.err
    saved = json.load(open(cli.CONFIG_PATH))
    assert saved["api_key"] == key and saved["endpoint"] == "http://127.0.0.1:8600"
    assert saved["device_id"] == calls[0][1]["client_id"]


def test_same_install_reuses_its_device_id(monkeypatch, capsys):
    ok = lambda: [(200, {"pair": "p", "code": "C", "secret": "s"}),
                  (200, {"state": "approved", "key": "bd_x", "memories": ["team"]})]
    _run(monkeypatch, capsys, ok(), memory="team")
    first = json.load(open(cli.CONFIG_PATH))
    assert first["endpoint"] == "http://127.0.0.1:8600/m/team"
    rc, calls, _ = _run(monkeypatch, capsys, ok())
    assert rc == 0 and calls[0][1]["client_id"] == first["device_id"]


def test_denied_is_an_error(monkeypatch, capsys):
    rc, _, out = _run(monkeypatch, capsys, [(200, {"pair": "p", "code": "C", "secret": "s"}),
                                            (200, {"state": "denied"})])
    assert rc == 1 and "denied" in out.err


@pytest.mark.parametrize("url,ok", [("http://127.0.0.1:8600", True), ("http://192.168.1.20:8600", True),
                                    ("http://hub.lan:8600", True), ("https://brain.example.com", True),
                                    ("http://brain.example.com", False), ("brain.example.com", True)])
def test_hub_address_rule(url, ok):
    if ok:
        assert cli._hub_url(url)
    else:
        with pytest.raises(ValueError):
            cli._hub_url(url)
