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


def test_login_sends_its_own_user_agent_and_names_an_edge_block(monkeypatch):
    # Cloudflare answers 403 "error code: 1010" to Python's default agent
    import io
    import urllib.error
    import urllib.request
    seen = {}

    def fake(req, timeout=30.0):
        seen["ua"] = req.get_header("User-agent")
        raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {}, io.BytesIO(b"error code: 1010"))
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    st, body = cli._post_json("https://cp.test/v1/device/code", {})
    assert seen["ua"].startswith("brethof-brain-client/")
    assert st == 403 and body["error"] == "blocked" and "edge" in body["error_description"]


def test_an_unconnected_plugin_tells_the_agent_the_one_command_and_stays_quiet_elsewhere(capsys, monkeypatch, tmp_path):
    from brethof_brain_client import hook
    monkeypatch.setattr(hook.Config, "load", classmethod(lambda c: types.SimpleNamespace(configured=lambda: False)))
    import io, sys
    sys.stdin = io.StringIO("{}")
    try:
        assert hook.main(["session-start", "1"]) == 0
        out = capsys.readouterr().out
        assert "connect.py" in out and "never see" in out
        sys.stdin = io.StringIO("{}")
        assert hook.main(["prompt-submit"]) == 0 and capsys.readouterr().out == ""
        sys.stdin = io.StringIO("{}")
        assert hook.main(["session-start", "2"]) == 0 and capsys.readouterr().out == ""
    finally:
        sys.stdin = sys.__stdin__


def test_the_connect_window_checks_the_values_and_wants_the_passphrase_twice(monkeypatch):
    import threading
    import urllib.parse
    import urllib.request
    from brethof_brain_client import connectpage
    monkeypatch.setattr(connectpage, "check", lambda ep, key, pp, ua: "" if key == "bmv2_good" else "Your memory did not accept that key.")
    url = {}
    opened = threading.Event()

    def open_url(u):
        url["u"] = u
        opened.set()
        return True
    out = {}
    t = threading.Thread(target=lambda: out.update(connectpage.serve(
        {"endpoint": "https://memory.example/t/x", "key": "", "passphrase": ""}, "ua", open_url, timeout_s=20)))
    t.start()
    opened.wait(5)
    page = urllib.request.urlopen(url["u"]).read().decode()
    assert "can never be opened again" in page and "Passphrase again" in page

    def post(**f):
        return urllib.request.urlopen(urllib.request.Request(url["u"], urllib.parse.urlencode(f).encode())).read().decode()
    assert "did not accept" in post(endpoint="https://memory.example/t/x", key="bmv2_bad", passphrase="p", passphrase2="p")
    assert "not the same" in post(endpoint="https://memory.example/t/x", key="bmv2_good", passphrase="p", passphrase2="q")
    assert "Connected" in post(endpoint="https://memory.example/t/x", key="bmv2_good", passphrase="p", passphrase2="p")
    t.join(5)
    assert out == {"endpoint": "https://memory.example/t/x", "key": "bmv2_good", "passphrase": "p"}
    try:                                       # one shot: the page is gone
        urllib.request.urlopen(url["u"], timeout=2)
        assert False, "the page outlived its one use"
    except Exception:
        pass


def test_the_connect_window_opens_at_once_even_when_name_lookups_hang(monkeypatch):
    # macOS: HTTPServer's bind asked socket.getfqdn() for 127.0.0.1's name and
    # the lookup hung, so the window opened late (the CI macOS jobs, 1.2.12 to
    # 1.2.15). The window's server must never look a name up.
    import socket
    import threading
    import time
    from brethof_brain_client import connectpage
    monkeypatch.setattr(socket, "getfqdn", lambda *a: time.sleep(30) or "slow.example")
    opened = threading.Event()
    t = threading.Thread(target=lambda: connectpage.serve(
        {"key": ""}, "ua", lambda u: opened.set() or True, timeout_s=1), daemon=True)
    t0 = time.monotonic()
    t.start()
    assert opened.wait(3), "the connect window did not open within 3 s"
    assert time.monotonic() - t0 < 3
    t.join(5)


def test_copilot_is_known_by_its_own_variable(monkeypatch, capsys):
    # A Copilot CLI plugin install cannot set BRETHOF_BRAIN_HOOK_FLAT; Copilot
    # marks every hook process with COPILOT_CLI and reads a flat answer.
    import json as _json
    from brethof_brain_client import hook
    monkeypatch.delenv("BRETHOF_BRAIN_HOOK_FLAT", raising=False)
    monkeypatch.setenv("COPILOT_CLI", "1")
    hook._emit_context("SessionStart", "hello")
    assert _json.loads(capsys.readouterr().out) == {"additionalContext": "hello"}
    monkeypatch.delenv("COPILOT_CLI")
    hook._emit_context("SessionStart", "hello")
    assert "hookSpecificOutput" in _json.loads(capsys.readouterr().out)
