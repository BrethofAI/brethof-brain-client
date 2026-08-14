"""Client configuration + project resolution.

Resolution order for every setting: environment variable (``BRETHOF_BRAIN_*``
first, then the ``CLAUDE_PLUGIN_OPTION_*`` variables Claude Code exports from a
plugin's user config), then ``~/.brethof-brain/config.json``, then a built-in
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
  1. ``$BRETHOF_BRAIN_PROJECT`` if set (explicit override),
  2. the ``projects`` entry whose ``path`` is the longest prefix of the cwd,
  3. an EXPLICIT ``default_project`` (set in config or env) — a stated
     instruction always wins,
  4. otherwise the folder's own name, sanitised into a project key — an
     unmapped working directory gets its OWN project, because a project
     is a folder; new work must never pour into the shared 'global'
     layer by default,
  5. "global" only when no usable name can be derived (a generic
     container folder such as ``src`` or ``tmp``).

A project key must match the data plane's rule: ``[a-z][a-z0-9_]{0,15}``.
"""
from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass, field

from . import DEFAULT_ENDPOINT

_ENV_HOME = (os.environ.get("BRETHOF_BRAIN_HOME")
             or os.environ.get("BRETHOF_MIND_HOME"))   # pre-rename env, still honored
CONFIG_DIR = os.path.expanduser(_ENV_HOME or "~/.brethof-brain")
# A pre-rename install keeps its config in ~/.brethof-mind; until that dir is
# migrated, fall back to it rather than silently running unconfigured. An
# EXPLICIT home override is an instruction — never fall back around it.
if (not _ENV_HOME
        and not os.path.exists(os.path.join(CONFIG_DIR, "config.json"))
        and os.path.exists(os.path.expanduser("~/.brethof-mind/config.json"))):
    CONFIG_DIR = os.path.expanduser("~/.brethof-mind")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
STATE_DIR = os.path.join(CONFIG_DIR, "state")
SPOOL_DIR = os.path.join(CONFIG_DIR, "spool")

_PROJECT_RE = re.compile(r"^[a-z][a-z0-9_]{0,15}$")


def valid_project(name: str) -> bool:
    return bool(_PROJECT_RE.match(name or ""))


# Folder names that describe a location, not a body of work — deriving a
# project from them would file real work under a meaningless name.
_GENERIC_DIRS = {
    "src", "code", "repo", "repos", "work", "workspace", "projects",
    "project", "dev", "temp", "tmp", "test", "tests", "new", "untitled",
    "documents", "downloads", "desktop", "home", "users", "user", "root",
    "programming", "git", "build", "dist", "app", "apps", "main",
}


def _repo_root(path: str) -> str:
    """The nearest enclosing repository root, or "" when there is none.

    Walks up looking for a ``.git`` entry — a directory in a normal clone, a
    FILE in a worktree or submodule, so both are matched by existence rather
    than isdir. Bounded to 64 levels and stops at the filesystem root, so a
    pathological path cannot spin. Never raises: a permission error on a
    parent must degrade to "not a repo", never break a hook."""
    cur = path or ""
    for _ in range(64):
        if not cur:
            return ""
        try:
            if os.path.exists(os.path.join(cur, ".git")):
                return cur
        except OSError:
            return ""
        parent = os.path.dirname(cur)
        if parent == cur:            # reached / or a drive root
            return ""
        cur = parent
    return ""


def project_from_path(path: str) -> str:
    """A project key derived from the LAST meaningful folder of a path.

    Lowercase, non-alphanumerics to underscores, trimmed to the data
    plane's key rule. Returns "" when nothing usable comes out (a generic
    container name, a leading digit, an empty basename) — the caller then
    falls back to its configured default."""
    parts = [p for p in re.split(r"[\\/]+", (path or "").strip()) if p]
    for raw in reversed(parts[-2:] or parts):          # folder, else parent
        name = re.sub(r"[^a-z0-9]+", "_", raw.lower()).strip("_")[:16]
        name = re.sub(r"_+", "_", name)
        # len<2 also drops drive letters ("D:" -> "d"), which are a path
        # artifact, never a project.
        if len(name) < 2 or name in _GENERIC_DIRS:
            continue
        if name[0].isdigit():
            name = "p_" + name[:14]
        if valid_project(name):
            return name
    return ""


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
        endpoint = (_env("BRETHOF_BRAIN_ENDPOINT", "BRETHOF_MIND_ENDPOINT",
                         "CLAUDE_PLUGIN_OPTION_ENDPOINT",
                         "CLAUDE_PLUGIN_OPTION_endpoint")
                    or f.get("endpoint") or DEFAULT_ENDPOINT).rstrip("/")
        api_key = (_env("BRETHOF_BRAIN_API_KEY", "BRETHOF_MIND_API_KEY",
                        "CLAUDE_PLUGIN_OPTION_API_KEY",
                        "CLAUDE_PLUGIN_OPTION_api_key")
                   or f.get("api_key") or "")
        default_project = (_env("BRETHOF_BRAIN_DEFAULT_PROJECT",
                                "BRETHOF_MIND_DEFAULT_PROJECT",
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
        return self.resolve(cwd)[0]

    def resolve(self, cwd: str) -> tuple:
        """(project, confident) for a working directory.

        ``confident`` means the answer came from something that actually
        states where the work lives — an explicit override, a configured
        mapping, or a repository root — rather than from the name of whatever
        folder the process happens to be standing in. Callers that persist a
        choice across a session should only pin a confident one."""
        env = (os.environ.get("BRETHOF_BRAIN_PROJECT")
               or os.environ.get("BRETHOF_MIND_PROJECT"))
        if env:
            if valid_project(env):
                return env, True
            # An explicit override that silently vanished would misroute a whole
            # session's memory — warn once per invocation (stderr never breaks
            # a hook; it only shows in hook debug output).
            try:
                sys.stderr.write(
                    f"brethof-brain: ignoring invalid BRETHOF_BRAIN_PROJECT={env!r} "
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
            return best_key, True
        dp = self.default_project
        # UNMAPPED FOLDER => ITS OWN PROJECT, never a dump into the shared
        # layer (2026-08-07). A project IS a folder; when a new working
        # directory appears, the memory that belongs to it is its own, and
        # 'global' is only for facts true across projects. The old
        # fall-through silently poured whole sessions into global — one
        # unmapped folder cost 5,600 turns of a mixed archive that can
        # never be cleanly re-filed. Separation is only cheap at write
        # time. An EXPLICIT default_project is still an instruction and
        # wins: this only replaces the implicit 'global' catch-all.
        if dp == "global":
            # ANCHOR ON THE REPOSITORY ROOT, not the folder we happen to be
            # standing in (2026-08-14). A project is a body of work, and a
            # body of work is a repo — so a session run from a subdirectory
            # belongs to the SAME project as one run from the top. Deriving
            # from the raw cwd forked one repo across three names in a single
            # morning ('brethof-workstation-setup' -> brethof_workstat, and
            # its ansible/roles subfolder -> 'roles'), and the chat archive is
            # immutable, so a split can never be re-joined afterwards.
            # Outside a repo we still derive from the folder: an unmapped
            # location keeps its own project rather than polluting 'global'.
            root = _repo_root(cwd_n)
            derived = project_from_path(root or cwd_n)
            if derived:
                # CONFIDENT only when a repository said so. A bare folder name
                # is a guess: the session may simply be passing through (a
                # shell that started in $HOME, a job that stepped onto a USB
                # mount), and a guess must never outrank a later real answer.
                return derived, bool(root)
        return (dp if valid_project(dp) else "global"), False


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
