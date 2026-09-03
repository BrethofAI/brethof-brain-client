# brethof-brain for Gemini CLI

Full ambient contract via Gemini CLI's native hooks (shipped December
2025, Claude-Code-shaped down to the output schema):

- **Session brief** — `SessionStart` injects your project's memory as the
  first turn in history.
- **Ambient recall** — `BeforeAgent` fires on every user prompt and pulls
  the matching memory in ahead of the answer.
- **Archive** — `AfterAgent` and `SessionEnd` ship the session transcript
  to your Brain's complete chat archive.

Every hook is fail-open: if the Brain is unreachable, Gemini CLI just
runs without memory.

## Install

1. Get the client next to the hook (either works):
   ```bash
   pip install git+https://github.com/BrethofAI/brethof-brain-client.git
   ```
   or run straight from a checkout of this repo — the hook bootstraps its
   own `sys.path`.

2. Merge `settings.json.example` into `~/.gemini/settings.json` (all
   projects) or `<repo>/.gemini/settings.json` (one project), fixing the
   absolute path to `gemini_hook.py`. (Hook timeouts here are in
   **milliseconds** — Gemini's convention.)

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

## Troubleshooting

`BRETHOF_BRAIN_HOOK_DEBUG=1` makes the hook print tracebacks to stderr
instead of failing silently. A rejected API key prints one loud line;
everything transient stays quiet by contract.
