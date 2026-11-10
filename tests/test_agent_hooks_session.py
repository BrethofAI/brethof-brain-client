"""AgentHooks names its session at the start and can end it (2026-11-10).

Found by an app built on the Brain: session_start posted the project only, so
the memory could not tell which sitting began; and nothing handed the memory a
sitting's last exchanges, which wait until a window of five fills."""
from brethof_brain_client import hooks_api


class _Rec:
    def __init__(self):
        self.calls = []

    def post(self, path, body, timeout=None):
        self.calls.append((path, body))
        return {"status": "ok", "injection": "brief"}


def _hooks(monkeypatch):
    class _Cfg:
        default_project = ""
        def configured(self):
            return True
    monkeypatch.setattr(hooks_api.Config, "load", staticmethod(lambda: _Cfg()))
    monkeypatch.setattr(hooks_api, "Client", lambda cfg, timeout=15.0: _Rec())
    return hooks_api.AgentHooks(project="u_fan1", session_id="sitting-1")


def test_session_start_names_the_session(monkeypatch):
    h = _hooks(monkeypatch)
    assert h.session_start() == "brief"
    assert h._http.calls[0] == ("/v1/hooks/session-start",
                                {"project": "u_fan1", "session_id": "sitting-1"})


def test_end_session_flushes_the_sitting_with_its_last_index(monkeypatch, tmp_path):
    monkeypatch.setattr(hooks_api, "SPOOL_DIR", str(tmp_path))
    h = _hooks(monkeypatch)
    h.archive("hi", "hello")
    h.archive("bye", "see you")
    h.end_session()
    path, body = h._http.calls[-1]
    assert path == "/v1/hooks/pre-compact"
    assert body == {"project": "u_fan1", "session_id": "sitting-1", "last_index": 3}


def test_end_session_fails_open(monkeypatch):
    h = _hooks(monkeypatch)
    def boom(*a, **k):
        raise hooks_api.ClientError("down")
    h._http.post = boom
    assert h.end_session() == {}
