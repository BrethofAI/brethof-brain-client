# brethof-brain for Cursor

Cloud memory for [Cursor](https://cursor.com) via its native hooks system:

- **Session brief** — `sessionStart` injects your project's memory as
  `additional_context` before the first turn.
- **Archive** — `stop` (per turn) and `sessionEnd` (final pass) ship the
  session transcript to your Brain's complete chat archive.

Cursor's `beforeSubmitPrompt` hook is gate-only by design — it cannot add
context — so there is **no per-prompt ambient recall** on this platform.
Add the MCP block (see [`adapters/editors/README.md`](../editors/README.md))
for the explicit tool doors (`search_brain`, saves, ledger, playbooks), and
the session brief teaches the agent to use them.

Every hook is fail-open: if the Brain is unreachable, Cursor just runs
without memory.

## Install

1. Get the client next to the hook (either works):
   ```bash
   pip install git+https://github.com/BrethofAI/brethof-brain-client.git
   ```
   or run straight from a checkout of this repo — the hook bootstraps its
   own `sys.path`.

2. Copy `hooks.json.example` into `~/.cursor/hooks.json` (all projects) or
   `<repo>/.cursor/hooks.json` (one project), fixing the absolute path to
   `cursor_hook.py`.

3. Configure the key — `~/.brethof-brain/config.json`:
   ```json
   {
     "api_key": "bmv2_...",
     "endpoint": "http://127.0.0.1:8610",
     "default_project": "my-project"
   }
   ```
   Environment variables override the file: `BRETHOF_BRAIN_API_KEY`,
   `BRETHOF_BRAIN_ENDPOINT`, `BRETHOF_BRAIN_PROJECT`.

Works in the Cursor IDE and the Cursor CLI (`agent`). Hooks load from
user, project, team, and enterprise levels — this adapter rides the user
or project level.

## Troubleshooting

`BRETHOF_BRAIN_HOOK_DEBUG=1` makes the hook print tracebacks to stderr
instead of failing silently. A rejected API key prints one loud line —
everything else transient stays quiet by contract.
