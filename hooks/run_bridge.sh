#!/bin/sh
# Plugin MCP launcher (the memory tools over stdio) — the same two jobs as run_hook.sh:
#  1. Resolve a REAL Python: on Windows, `python3` on PATH is often the
#     Microsoft Store app-execution stub under WindowsApps, which opens the
#     Store instead of running the script — skip anything living there.
#  2. Keep secrets out of argv: the API key reaches hook_entry.py via the
#     CLAUDE_PLUGIN_OPTION_* environment (exported by Claude Code from the
#     plugin's user config), never on the command line.
# Fail-open by contract: no usable Python -> exit 0, the session is never blocked.
root="$(cd "$(dirname "$0")/.." && pwd)"
for p in python3 python py; do
  path="$(command -v "$p" 2>/dev/null)" || continue
  [ -n "$path" ] || continue
  case "$path" in *WindowsApps*) continue ;; esac
  exec "$path" "$root/mcp_bridge.py" "$@"
done
exit 0
