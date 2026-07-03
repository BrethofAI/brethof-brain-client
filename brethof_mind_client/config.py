"""Client configuration + project resolution.

Resolution order for every setting: environment variable, then
``~/.brethof-mind/config.json``, then a built-in default. The config file is the
ONLY place your API key is stored on disk; keep it readable by you alone (the
``brethof-mind setup`` command chmods it 600 on POSIX).

config.json shape (all keys optional except api_key)::

    {
      "endpoint": "https://api.brethof.cloud",
      "api_key": "bm_live_...",
      "default_project": "global",
      "projects": [
        {"path": "/home/me/work/acme", "key": "acme"},
        {"path": "/home/me/work/blog", "key": "blog"}
      ]
    }

Project resolution for a given working directory:
  1. ``$BRETHOF_MIND_PROJECT`` if set (explicit override),
  2. the ``projects`` entry whose ``path`` is the longest prefix of the cwd,
  3. ``default_project`` (config or "global").

A project key must match the data plane's rule: ``[a-z][a-z0-9_]{0,15}``.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

from . import DEFAULT_ENDPOINT

CONFIG_DIR = os.path.expanduser(os.environ.get("BRETHOF_MIND_HOME", "~/.brethof-mind"))
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
STATE_DIR = os.path.join(CONFIG_DIR, "state")
SPOOL_DIR = os.path.join(CONFIG_DIR, "spool")

_PROJECT_RE = re.compile(r"^[a-z][a-z0-9_]{0,15}$")


def valid_project(name: str) -> bool:
    return bool(_PROJECT_RE.match(name or ""))


def _load_file() -> dict:
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


@dataclass
class Config:
    endpoint: str = DEFAULT_ENDPOINT
    api_key: str = ""
    default_project: str = "global"
    projects: list = field(default_factory=list)
    raw: dict = field(default_factory=dict)

    @classmethod
    def load(cls) -> "Config":
        f = _load_file()
        endpoint = (os.environ.get("BRETHOF_MIND_ENDPOINT")
                    or f.get("endpoint") or DEFAULT_ENDPOINT).rstrip("/")
        api_key = os.environ.get("BRETHOF_MIND_API_KEY") or f.get("api_key") or ""
        default_project = (os.environ.get("BRETHOF_MIND_DEFAULT_PROJECT")
                           or f.get("default_project") or "global")
        projects = f.get("projects") if isinstance(f.get("projects"), list) else []
        return cls(endpoint=endpoint, api_key=api_key.strip(),
                   default_project=default_project, projects=projects, raw=f)

    def configured(self) -> bool:
        return bool(self.api_key)

    def project_for(self, cwd: str) -> str:
        """Resolve the project for a working directory (see module docstring)."""
        env = os.environ.get("BRETHOF_MIND_PROJECT")
        if env and valid_project(env):
            return env
        cwd_n = os.path.normcase(os.path.abspath(cwd or os.getcwd()))
        best_key, best_len = None, -1
        for p in self.projects:
            if not isinstance(p, dict):
                continue
            path, key = p.get("path"), p.get("key")
            if not path or not key or not valid_project(key):
                continue
            path_n = os.path.normcase(os.path.abspath(os.path.expanduser(path)))
            if (cwd_n == path_n or cwd_n.startswith(path_n + os.sep)) and len(path_n) > best_len:
                best_key, best_len = key, len(path_n)
        if best_key:
            return best_key
        dp = self.default_project
        return dp if valid_project(dp) else "global"


def ensure_dirs() -> None:
    for d in (CONFIG_DIR, STATE_DIR, SPOOL_DIR):
        os.makedirs(d, exist_ok=True)


def save_file(data: dict) -> None:
    """Write config.json and lock it down to the owner on POSIX."""
    ensure_dirs()
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, CONFIG_PATH)
    try:
        os.chmod(CONFIG_PATH, 0o600)  # no-op semantics on Windows, correct on POSIX
    except OSError:
        pass
