"""THE PLUGIN'S MEMORY TOOLS, OVER STDIO (2026-10-04). The Claude Code plugin
used to reach the memory as a remote HTTP server whose address and key came
from the plugin's own settings — so after `brethof-brain connect` (which saves
them in ~/.brethof-brain/config.json, never through the agent) the hooks
worked and the tools did not, and the plugin demanded the key at install,
which is exactly the step an agent cannot do for the person.

This bridge is the plugin's MCP server: newline-delimited JSON-RPC on stdin,
each request forwarded to <endpoint>/v1/mcp with the configured key (a locked
hosted memory is opened with the configured passphrase, as every hook does),
the answer written to stdout. The config is read on EVERY request, so the
tools work the moment `connect` finishes. Not connected yet: the handshake is
answered here, the tool list is empty, and the instructions say how to
connect.
"""
from __future__ import annotations

import json
import sys

from . import __version__
from .client import Client, ClientError
from .config import Config

MCP_PATH = "/v1/mcp"
NOT_CONNECTED = ("brethof-brain is installed but not connected to a memory yet. To finish, run "
                 "`brethof-brain connect` (plugin installs: python3 \"<plugin root>/connect.py\"): a window "
                 "on the person's screen takes their API key and passphrase — never ask for them in chat. "
                 "The memory tools appear in the next session.")


def _reply(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _local(msg: dict) -> dict | None:
    """The handshake and an empty tool list for a plugin not connected yet."""
    method, mid = msg.get("method"), msg.get("id")
    if method == "initialize":
        pv = (msg.get("params") or {}).get("protocolVersion") or "2025-06-18"
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": pv, "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "brethof-brain", "version": __version__},
            "instructions": NOT_CONNECTED}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": []}}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32002, "message": NOT_CONNECTED}}


def handle(msg: dict) -> dict | None:
    """One JSON-RPC message in, its answer out (None for a notification)."""
    is_request = "id" in msg and msg.get("method") is not None
    cfg = Config.load()
    if not cfg.configured():
        return _local(msg) if is_request else None
    try:
        resp = Client(cfg, timeout=120.0).post(MCP_PATH, msg)
    except ClientError as e:
        if not is_request:
            return None                    # a notification has no answer, even a failed one
        return {"jsonrpc": "2.0", "id": msg.get("id"),
                "error": {"code": -32000, "message": f"brethof-brain: {e}"}}
    return resp if is_request else None


def main() -> int:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            _reply({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}})
            continue
        out = handle(msg) if isinstance(msg, dict) else None
        if out is not None:
            _reply(out)
    return 0
