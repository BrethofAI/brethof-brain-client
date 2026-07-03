"""HTTP transport to the brethof-mind data plane.

One method — ``post`` — that speaks the uniform response envelope
(``{status, injection, notice, retry_after, ...}``). It is deliberately
fail-soft: a hook must NEVER break the user's session, so network/HTTP errors
raise :class:`ClientError` for the caller to swallow rather than propagating.

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

    def post(self, path: str, payload: dict, timeout: float | None = None) -> dict:
        """POST JSON to ``<endpoint><path>`` and return the decoded envelope.

        Raises ClientError on transport/HTTP failure (including 401/403 so the
        caller can distinguish auth problems from an ``ok`` envelope)."""
        if not self.cfg.api_key:
            raise ClientError("no API key configured (run: brethof-mind setup)")
        url = self.cfg.endpoint + path
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=self._headers(),
                                     method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as r:
                body = r.read()
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8", "replace")[:200]
            except Exception:
                pass
            raise ClientError(f"HTTP {e.code} on {path}: {detail}", status_code=e.code)
        except urllib.error.URLError as e:
            raise ClientError(f"network error on {path}: {e.reason}")
        except Exception as e:  # noqa: BLE001
            raise ClientError(f"unexpected error on {path}: {e}")
        try:
            obj = json.loads(body or b"{}")
        except Exception:
            raise ClientError(f"bad JSON from {path}")
        return obj if isinstance(obj, dict) else {"status": "ok", "raw": obj}

    def get(self, path: str, timeout: float | None = None) -> dict:
        url = self.cfg.endpoint + path
        req = urllib.request.Request(url, headers=self._headers(), method="GET")
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as r:
                body = r.read()
        except urllib.error.HTTPError as e:
            raise ClientError(f"HTTP {e.code} on {path}", status_code=e.code)
        except urllib.error.URLError as e:
            raise ClientError(f"network error on {path}: {e.reason}")
        try:
            return json.loads(body or b"{}")
        except Exception:
            raise ClientError(f"bad JSON from {path}")
