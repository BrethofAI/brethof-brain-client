"""brethof-brain login — the device flow (2026-10-04, the control plane's
contract): the human approves a code; the key reaches the config file and is
never printed."""
import json
import types

from brethof_brain_client import cli


def _run(monkeypatch, capsys, answers):
    calls = []

    def post(url, body, timeout=30.0):
        calls.append((url.rsplit("/", 1)[-1], body))
        return answers.pop(0)
    monkeypatch.setattr(cli, "_post_json", post)
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: False)
    rc = cli.cmd_login(types.SimpleNamespace(control="https://cp.test"), sleep=lambda s: calls.append(("sleep", s)))
    out = capsys.readouterr()
    return rc, calls, out


def test_an_approved_code_writes_the_key_and_never_prints_it(monkeypatch, capsys, tmp_path):
    key = "bmv2_" + "c" * 48
    rc, calls, out = _run(monkeypatch, capsys, [
        (200, {"device_code": "DEV-SECRET", "user_code": "ABCD-EFGH", "interval": 5, "expires_in": 600,
               "verification_uri_complete": "https://brethof.ai/account/device/?code=ABCD-EFGH"}),
        (400, {"error": "authorization_pending"}),
        (400, {"error": "slow_down"}),
        (200, {"api_key": key, "endpoint": "https://memory.brethof.cloud/t/abc123", "needs_passphrase": True}),
    ])
    assert rc == 0
    assert "ABCD-EFGH" in out.out and "DEV-SECRET" not in out.out + out.err
    assert key not in out.out + out.err
    assert [c for c in calls if c[0] == "sleep"] == [("sleep", 5), ("sleep", 5), ("sleep", 10)]   # slow_down adds 5 s
    saved = json.load(open(cli.CONFIG_PATH))
    assert saved["api_key"] == key and saved["endpoint"] == "https://memory.brethof.cloud/t/abc123"
    assert "passphrase" in out.err                       # told how to add it; never asked off a terminal


def test_a_refusal_is_said_and_nothing_is_saved(monkeypatch, capsys):
    import os
    before = open(cli.CONFIG_PATH).read() if os.path.exists(cli.CONFIG_PATH) else None
    rc, _, out = _run(monkeypatch, capsys, [
        (200, {"device_code": "D", "user_code": "WXYZ-1234", "interval": 1, "expires_in": 600,
               "verification_uri": "https://brethof.ai/account/device/"}),
        (400, {"error": "access_denied", "error_description": "Your memory runs on your own machine"}),
    ])
    assert rc == 1 and "own machine" in out.err
    after = open(cli.CONFIG_PATH).read() if os.path.exists(cli.CONFIG_PATH) else None
    assert before == after
