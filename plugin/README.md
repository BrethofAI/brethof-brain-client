# brethof-brain — the Claude Code plugin

Long-term memory for your agents. Every session opens with a brief from your
memory, every prompt arrives with the records that bear on it, and every
exchange is archived so it can be found again. The same memory serves every
proven harness — the full list and the other installs are in the
[client repository](https://github.com/BrethofAI/brethof-brain-client).

You need a brethof-brain account: sign up at
[brethof.ai/brain](https://brethof.ai/brain/), choose where your memory lives
(on your own machine, or hosted by us, encrypted under your passphrase) and
copy your API key from the panel.

## Install

```
claude plugin marketplace add BrethofAI/brethof-brain-client
claude plugin install brethof-brain@brethof
```

Then connect this computer to your memory:

```
python3 "<plugin folder>/connect.py"
```

A window opens on your own screen. Paste the API key and, for a hosted
memory, your passphrase (twice — a forgotten passphrase can never be
recovered). The window checks both with your memory and saves them in
`~/.brethof-brain/config.json`. Your agent never sees either. The hooks and the
memory tools load at the next session start.

## What it does

- **Hooks** (`hooks/hooks.json`): at session start the brief, on every prompt
  the matching records, at the end of each turn the exchange is archived,
  before a compact the archive is checked complete.
- **Memory tools** (`.mcp.json`, server `brain`): search, save and read your
  memory, run locally over stdio by `mcp_bridge.py`.
- **Commands**: `/recall`, `/curate`, `/onboard`.

## Claude Code and Cowork

**Claude Code** gets all of it: the brief at session start, the matching
records on every prompt, every exchange archived, and the memory tools.

**Cowork** gets the memory tools only. Cowork does not run plugin hooks, so
there is no brief at session start, no records arriving with your prompts,
and Cowork conversations are not archived into your memory. What does work:
your agent can search and read the memory your Claude Code sessions built,
and save facts, notes and playbooks into it. Ask it to check the memory when
you start, and to save what matters before you stop. Connect the computer
once first (`connect.py`, above) — Cowork does not ask for plugin settings.

## Where your data goes

The hooks and tools talk to your own memory: `127.0.0.1:8610` for a memory on
your machine, or your hosted address on `memory.brethof.cloud`. Your memory
sends the exchanges it needs processed to our hub (`hub.brethof.ai`), which
processes them and stores none of it. The API key is read from
`~/.brethof-brain/config.json` (or the `BRETHOF_BRAIN_API_KEY` variable) and is
sent only to those brethof addresses. Details: the
[privacy page](https://brethof.ai/brain/privacy/).

Python 3.9+ on PATH is required; the plugin has no other dependencies.

## License

Source-available under the brethof-brain Client License — see `LICENSE`.
