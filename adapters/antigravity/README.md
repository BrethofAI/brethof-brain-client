# brethof-brain for Google Antigravity

Full ambient contract via Antigravity's native hooks:

- **Session brief + ambient recall** — `PreInvocation` fires before every
  model call; the adapter injects your project brief once per conversation
  and fresh recall whenever your latest message changes, as an *ephemeral*
  message — the model sees it, stored history never does.
- **Archive** — `Stop` ships the conversation transcript to your Brain's
  complete chat archive.

Every hook is fail-open: if the Brain is unreachable, Antigravity just
runs without memory.

## Install

1. Get the client next to the hook (either works):
   ```bash
   pip install brethof-brain-client
   ```
   or run straight from a checkout of this repo — the hook bootstraps its
   own `sys.path`.

2. Copy `hooks.json.example` into `~/.gemini/config/hooks.json` (all
   workspaces) or `<workspace>/.agents/hooks.json` (one workspace), fixing
   the absolute paths to `antigravity_hook.py`. (Timeouts are in seconds —
   Antigravity's convention.)

3. Configure the key — `~/.brethof-brain/config.json`:
   ```json
   {
     "api_key": "bm_live_...",
     "endpoint": "https://api.brethof.cloud",
     "default_project": "my-project"
   }
   ```
   Environment variables override the file: `BRETHOF_BRAIN_API_KEY`,
   `BRETHOF_BRAIN_ENDPOINT`, `BRETHOF_BRAIN_PROJECT`.

Hooks are verified solid on the Antigravity CLI (`agy`) and SDK surfaces;
community reports of hook reliability issues in the desktop IDE exist —
if the brief doesn't appear there, test the same config in the CLI.

## Troubleshooting

`BRETHOF_BRAIN_HOOK_DEBUG=1` makes the hook print tracebacks to stderr
instead of failing silently.
