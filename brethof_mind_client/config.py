"""Client configuration + project resolution.

Resolution order for every setting: environment variable (``BRETHOF_MIND_*``
first, then the ``CLAUDE_PLUGIN_OPTION_*`` variables Claude Code exports from a
plugin's user config), then ``~/.brethof-mind/config.json``, then a built-in
default. The config file is where the CLI stores your API key on disk (created
owner-readable-only); the Claude Code plugin path never writes it to this file —
Claude Code holds it and passes it via the environment.

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
import sys
from dataclasses import dataclass, field

from . import DEFAULT_ENDPOINT

CONFIG_DIR = os.path.expanduser(os.environ.get("BRETHOF_MIND_HOME", "~/.brethof-mind"))
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
STATE_DIR = os.path.join(CONFIG_DIR, "state")
SPOOL_DIR = os.path.join(CONFIG_DIR, "spool")

_PROJECT_RE = re.compile(r"^[a-z][a-z0-9_]{0,15}$")


def valid_project(name: str) -> bool:
    return bool(_PROJECT_RE.match(name or ""))


def _env(*names: str) -> str:
    """First non-empty value among the given environment variables."""
    for n in names:
        v = os.environ.get(n)
        if v:
            return v
    return ""


def _load_file() -> dict:
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _real(path: str) -> str:
    """Canonical comparable form of a path: expanded, absolute, symlinks
    resolved, case-normalized (Windows)."""
    return os.path.normcase(os.path.realpath(os.path.abspath(os.path.expanduser(path))))


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
        endpoint = (_env("BRETHOF_MIND_ENDPOINT", "CLAUDE_PLUGIN_OPTION_ENDPOINT",
                         "CLAUDE_PLUGIN_OPTION_endpoint")
                    or f.get("endpoint") or DEFAULT_ENDPOINT).rstrip("/")
        api_key = (_env("BRETHOF_MIND_API_KEY", "CLAUDE_PLUGIN_OPTION_API_KEY",
                        "CLAUDE_PLUGIN_OPTION_api_key")
                   or f.get("api_key") or "")
        default_project = (_env("BRETHOF_MIND_DEFAULT_PROJECT",
                                "CLAUDE_PLUGIN_OPTION_PROJECT",
                                "CLAUDE_PLUGIN_OPTION_project")
                           or f.get("default_project") or "global")
        projects = f.get("projects") if isinstance(f.get("projects"), list) else []
        return cls(endpoint=endpoint, api_key=api_key.strip(),
                   default_project=default_project, projects=projects, raw=f)

    def configured(self) -> bool:
        return bool(self.api_key)

    def project_for(self, cwd: str) -> str:
        """Resolve the project for a working directory (see module docstring)."""
        env = os.environ.get("BRETHOF_MIND_PROJECT")
        if env:
            if valid_project(env):
                return env
            # An explicit override that silently vanished would misroute a whole
            # session's memory — warn once per invocation (stderr never breaks
            # a hook; it only shows in hook debug output).
            try:
                sys.stderr.write(
                    f"brethof-mind: ignoring invalid BRETHOF_MIND_PROJECT={env!r} "
                    "(must match [a-z][a-z0-9_]{0,15})\n")
            except Exception:
                pass
        cwd_n = _real(cwd or os.getcwd())
        best_key, best_len = None, -1
        for p in self.projects:
            if not isinstance(p, dict):
                continue
            path, key = p.get("path"), p.get("key")
            if not path or not key or not valid_project(key):
                continue
            path_n = _real(path)
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
    """Write config.json atomically, owner-readable from the first byte on
    POSIX (0600 at open, so no world-readable window and no orphaned readable
    .tmp). On Windows the user-profile ACLs provide the equivalent."""
    ensure_dirs()
    tmp = CONFIG_PATH + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, CONFIG_PATH)
    try:
        os.chmod(CONFIG_PATH, 0o600)  # no-op semantics on Windows, correct on POSIX
    except OSError:
        pass
