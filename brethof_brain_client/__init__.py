"""brethof-brain thin client.

A tiny, dependency-free client for brethof-brain cloud (https://brethof.cloud):
shared long-term memory for AI coding agents. The heavy lifting — SurrealDB,
embeddings, retrieval-augmented recall — runs on the data plane; this client
only forwards Claude Code hook events over HTTPS and wires the remote MCP
endpoint. Stdlib only, so it runs anywhere a Python 3.9+ interpreter does.

Source-available (see LICENSE — brethof-brain Client License; not open source).
Contains no secrets: your API key lives in ``~/.brethof-brain/config.json`` (or
``$BRETHOF_BRAIN_API_KEY``), never in this code.
"""

__version__ = "1.1.0"

DEFAULT_ENDPOINT = "https://api.brethof.cloud"
USER_AGENT = f"brethof-brain-client/{__version__}"


def __getattr__(name):
    # Lazy re-exports so `from brethof_brain_client import MindClient` works
    # without importing the api module (and its deps) at package load.
    if name in ("MindClient", "MindToolError"):
        from . import api
        return getattr(api, name)
    if name == "AgentHooks":
        from .hooks_api import AgentHooks
        return AgentHooks
    if name in ("Config",):
        from .config import Config
        return Config
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
