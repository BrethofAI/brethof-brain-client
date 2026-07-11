"""HTTP transport to the brethof-mind data plane.

Two methods — ``post`` and ``get`` — that speak the uniform response envelope
(``{status, injection, notice, retry_after, ...}``). It is deliberately
fail-soft: a hook must NEVER break the user's session, so network/HTTP errors
raise :class:`ClientError` for the caller to swallow rather than propagating.
A 2xx response that is not a JSON object is ALSO a ClientError — the caller
must never mistake an edge anomaly (empty body, HTML page) for a confirmed
write.

Every request carries a real ``User-Agent`` and an ``X-BM-Client`` header —
the data plane's edge treats missing/automated user-agents as bots, so the
default ``Python-urllib`` UA would be challenged. We set our own.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from . import USER_AGENT, __version__
from .config import Config


class ClientError(Exception):
    """Any failure talking to the data plane (network, HTTP, decode)."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


def _http_error_detail(e: urllib.error.HTTPError) -> str:
    """First bytes of an error body — lets callers tell a WAF block page
    from a plain auth rejection."""
    try:
        return e.read().decode("utf-8", "replace")[:200]
    except Exception:
        return ""


class Client:
    def __init__(self, cfg: Config, timeout: float = 10.0):
        self.cfg = cfg
        self.timeout = timeout

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.cfg.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
            "X-BM-Client": __version__,
        }

    def _request(self, path: str, data: bytes | None, method: str,
                 timeout: float | None) -> dict:
        if not self.cfg.api_key:
            raise ClientError("no API key configured (run: brethof-mind setup)")
        try:
            req = urllib.request.Request(self.cfg.endpoint + path, data=data,
                                         headers=self._headers(), method=method)
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as r:
                body = r.read()
        except urllib.error.HTTPError as e:
            raise ClientError(f"HTTP {e.code} on {path}: {_http_error_detail(e)}",
                              status_code=e.code)
        except urllib.error.URLError as e:
            raise ClientError(f"network error on {path}: {e.reason}")
        except ClientError:
            raise
        except Exception as e:  # noqa: BLE001 — incl. ValueError on a bad endpoint URL
            raise ClientError(f"bad request for {path}: {e}")
        try:
            obj = json.loads(body or b"")
        except Exception:
            raise ClientError(f"bad JSON from {path}")
        if not isinstance(obj, dict) or not obj:
            # An empty/non-object 2xx is NOT a confirmation — never fabricate
            # a success envelope from it (a caller would commit state on it).
            raise ClientError(f"non-envelope response from {path}")
        return obj

    def post(self, path: str, payload: dict, timeout: float | None = None) -> dict:
        """POST JSON to ``<endpoint><path>`` and return the decoded envelope.

        Raises ClientError on transport/HTTP failure (including 401/403 so the
        caller can distinguish auth problems from an ``ok`` envelope)."""
        # ensure_ascii=False: the payload is mostly transcript text; escaping
        # non-ASCII would inflate it ~6x on the wire for non-English sessions.
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        return self._request(path, data, "POST", timeout)

    def get(self, path: str, timeout: float | None = None) -> dict:
        return self._request(path, None, "GET", timeout)
