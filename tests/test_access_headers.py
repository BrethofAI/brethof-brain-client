"""Cloudflare Access headers (1.2.26): an app whose memory sits behind a
Cloudflare Access app sets BRETHOF_BRAIN_CF_ACCESS_ID/_SECRET and every
request carries them; unset, nothing changes."""
import json

from brethof_brain_client import client as C
from brethof_brain_client.config import Config


class _Resp:
    status = 200
    def __init__(self, body=b'{"status":"ok"}'): self._b = body
    def read(self): return self._b
    def __enter__(self): return self
    def __exit__(self, *a): return False


def _cfg():
    c = Config()
    c.api_key, c.endpoint = "k", "https://mem.example"
    return c


def test_unset_sends_no_access_headers(monkeypatch):
    monkeypatch.delenv("BRETHOF_BRAIN_CF_ACCESS_ID", raising=False)
    monkeypatch.delenv("BRETHOF_BRAIN_CF_ACCESS_SECRET", raising=False)
    h = C.Client(_cfg())._headers()
    assert "CF-Access-Client-Id" not in h and h["Authorization"] == "Bearer k"


def test_one_half_alone_sends_nothing(monkeypatch):
    monkeypatch.setenv("BRETHOF_BRAIN_CF_ACCESS_ID", "id")
    monkeypatch.delenv("BRETHOF_BRAIN_CF_ACCESS_SECRET", raising=False)
    assert "CF-Access-Client-Id" not in C.Client(_cfg())._headers()


def test_set_every_request_carries_them(monkeypatch):
    monkeypatch.setenv("BRETHOF_BRAIN_CF_ACCESS_ID", "id.access")
    monkeypatch.setenv("BRETHOF_BRAIN_CF_ACCESS_SECRET", "sec")
    seen = []
    monkeypatch.setattr(C.urllib.request, "urlopen",
                        lambda req, timeout=0: (seen.append(dict(req.header_items())), _Resp())[1])
    cl = C.Client(_cfg())
    cl._request("/v1/x", json.dumps({}).encode(), "POST", None)
    cl._request("/v1/y", None, "GET", None)
    assert len(seen) == 2
    for h in seen:
        assert h["Cf-access-client-id"] == "id.access" and h["Cf-access-client-secret"] == "sec"
    assert seen[0]["Authorization"] == "Bearer k"
