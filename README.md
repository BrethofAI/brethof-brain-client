# brethof-brain client

Thin client for **[brethof-brain](https://brethof.ai/brain/)** — persistent
memory for your AI agents. It gives your agents persistent, searchable
memory across sessions: it remembers past decisions, conversations, and project
context so you don't re-explain yourself every time.

Fully supported: **Claude Code**, **Codex**, **Qwen Code**, **OpenClaw**, **Hermes Agent**,
**DeepSeek Harness (dsh)**, **Cline**, **OpenCode**, and **Kilo Code** —
supported means the complete ambient loop (session brief, per-prompt
recall, automatic archiving), proven by our test rig against the real
platform. Any MCP-compatible client can additionally use the memory tools
on demand — that is a toolbox, not the ambient loop. Every supported
platform is re-verified against its newest release on a fresh virtual machine,
with the results judged server-side — a version bump that breaks an
integration is caught by us, not by you.

## How it works

The client is deliberately tiny. All the real work — storage, embeddings,
retrieval-augmented recall — happens on the brethof-brain service. The client
only:

1. forwards agent **hook events** to the service over HTTPS, and pastes back
   the memory it returns, and
2. wires the **MCP** endpoint so the memory tools are available on demand —
   search (`search_brain`, `search_history`, `get_record`, `graph`) and the
   four doors that write: `save_project` / `save_general` (a fact into the
   project's history; the service's curator decides whether it becomes a
   record — nothing writes records by hand), `save_note` (your session's
   handover), `save_playbook` (a procedure), `save_rule` (a standing
   convention), plus `add_project` with a one-line purpose.

It has **no third-party dependencies** — pure Python standard library, so it
runs anywhere Python 3.9+ does.

## Supported agents

| Agent | Adapter | What you get |
|---|---|---|
| **Claude Code** | built-in | Full: session memory injected, ambient recall every prompt, every turn archived, memory tools |
| **DeepSeek Harness (dsh)** | [`adapters/dsh/`](adapters/dsh/) | Full: native cordis plugin on dsh's typed extension points — injection, ambient recall, archival (npm: `brethof-brain-dsh`) |
| **Qwen Code** | [`adapters/qwen-code/`](adapters/qwen-code/) | Full: hooks (inject + recall + archive) + MCP tools |
| **Codex** (OpenAI) | [`adapters/codex/`](adapters/codex/) | Full: hooks (inject + recall) + archival via `notify` + MCP tools. One manual step: codex requires you to trust new hooks once — run `/hooks` and trust the brethof-brain entries |
| **OpenClaw** (gateway) | [`adapters/openclaw-gateway/`](adapters/openclaw-gateway/) | Full: native plugin — injection, ambient recall, archival (npm: `brethof-brain-openclaw`) |
| **Hermes Agent** (Nous Research) | [`adapters/hermes/`](adapters/hermes/) | Full: a Hermes MemoryProvider — brief in the system prompt, ambient recall every turn, every turn archived; memory tools via Hermes's native MCP client (`hermes plugins install BrethofAI/brethof-brain-client/adapters/hermes`). Proven on Linux and on Windows through Hermes's native installer |
| **Cline** | [`adapters/cline/`](adapters/cline/) | Full: `beforeModel` request overlay (brief + ambient recall) + `afterRun` archival (npm: `brethof-brain-cline`) |
| **OpenCode** | [`adapters/opencode/`](adapters/opencode/) | Full: one native plugin — persisted brief + recall parts, `session.idle` archival (npm: `brethof-brain-opencode`) |
| **Kilo Code** | [`adapters/opencode/`](adapters/opencode/) | Full: the same plugin file, dropped into `~/.config/kilo/plugin/` — covers Kilo's CLI, VS Code and JetBrains |
| **OpenClaw** (library) | [`adapters/openclaw/`](adapters/openclaw/) | `MemorySession` wrapper for agents with no hook system of their own |

Each adapter has its own README with install instructions. The table above
links to them. Capability wording is exact: it states what our test rig
proves against the live platform, nothing more.

### Claude Code (recommended)

The plugin bundles this client, wires the hooks + the memory tools, and adds
the `/recall` `/curate` `/onboard` commands — no `pip install` needed,
only Python 3.9+ on your PATH.

```
/plugin marketplace add BrethofAI/brethof-brain-client
/plugin install brethof-brain@brethof
```

You'll be prompted for your **API key** (from
[brethof.ai/account](https://brethof.ai) → brethof-brain tab); Claude Code stores
it as plugin config (sensitive values go to your OS keychain where available)
and passes it to the hooks via the environment — never on a command line.
Restart Claude Code and memory is live. Commands are namespaced:
`/brethof-brain:recall`, `/brethof-brain:curate`, `/brethof-brain:onboard`.
`/curate` closes a session: it files what was found and leaves the handover
note. Curation, consolidation and healing of the memory itself are the
service's work — there is nothing weekly for you to run.

### OpenClaw

A native gateway plugin: session memory and ambient recall are appended to
the system context each turn, every finished turn is archived. One install,
one config opt-in (`hooks.allowConversationAccess` — OpenClaw gates
conversation content for non-bundled plugins).

```bash
openclaw plugins install --force --accept-capabilities brethof-brain-openclaw
```

(OpenClaw 2026.8.2+ asks you to accept the plugin's declared
`allowConversationAccess` capability at install — archival reads the
conversation; that is the product — and `--force` because the package is
outside ClawHub review: you are the review.)

See [`adapters/openclaw-gateway/README.md`](adapters/openclaw-gateway/README.md).

### Hermes Agent

brethof-brain is a Hermes **memory provider** — the one plugin type Hermes
selects for memory. Works wherever Hermes runs: Linux, macOS, and Windows on
either of Hermes's two paths (the native PowerShell installer, or WSL2). Two
commands, then your key:

```bash
hermes plugins install BrethofAI/brethof-brain-client/adapters/hermes --no-enable
hermes config set memory.provider brethof-brain
```

```
# ~/.hermes/.env
BRETHOF_BRAIN_API_KEY=bmv2_...
BRETHOF_BRAIN_PROJECT=my-agent
```

Restart Hermes; `hermes memory status` shows `brethof-brain` active. For the
memory tools on demand, add the Brain's MCP server to `mcp_servers` in
`~/.hermes/config.yaml`. See [`adapters/hermes/README.md`](adapters/hermes/README.md).

### Qwen Code

Qwen Code ships Claude-style hooks, so it gets the full contract — one
setup script wires hooks, MCP and `~/.qwen/QWEN.md`. See
[`adapters/qwen-code/README.md`](adapters/qwen-code/README.md).

### Codex

`python3 adapters/codex/setup.py` registers the MCP server (bearer token
via env, never in a file), installs the turn archiver on Codex's `notify`
channel, and pre-wires `hooks.json` so context injection activates the
moment Codex fires hooks in headless mode. See
[`adapters/codex/README.md`](adapters/codex/README.md).

### Cline

A request-only overlay on Cline's `beforeModel` / `afterRun` extension
points — session brief and ambient recall ride into each request without
touching your stored conversation, and every finished run is archived.
Install: `cline plugin install npm:brethof-brain-cline` (a bare name would
look in Cline's official registry, not npm). See
[`adapters/cline/README.md`](adapters/cline/README.md).

### OpenCode & Kilo Code

One native plugin covers both: the session brief and per-prompt recall are
appended as persisted synthetic message parts, and `session.idle` archives
the turns. Drop the plugin file into `~/.config/opencode/plugins/`
(OpenCode) or `~/.config/kilo/plugin/` (Kilo — CLI, VS Code and JetBrains
alike): from this repo, `adapters/opencode/lib/index.js`, or from npm —
`npm pack brethof-brain-opencode` and take `package/lib/index.js`. See [`adapters/opencode/README.md`](adapters/opencode/README.md).

### Other editors and MCP clients

Any MCP-compatible client can use the memory **tools** on demand (search,
save, rules, projects) with one config block — that is a toolbox, not the
ambient memory loop above. Exact blocks and auth notes per editor:
[`adapters/editors/README.md`](adapters/editors/README.md).

### DeepSeek Harness (dsh)

A **native cordis plugin** on dsh's own typed extension points — session
injection, per-prompt ambient recall, per-turn archival, all fail-open.
Install with `dsh plugin --profile <name> add brethof-brain-dsh` (or from
this repo's checkout) and note the one dsh-specific rule: your API key goes
in `~/.brethof-brain/config.json`, because dsh scrubs `*_API_KEY` from hook
environments by design. Full details:
[`adapters/dsh/README.md`](adapters/dsh/README.md).

### OpenClaw (library wrapper)

For agents with no hook system at all: a `MemorySession` wrapper —
`start()` / `build_context()` / `record()` around your model loop. See
[`adapters/openclaw/README.md`](adapters/openclaw/README.md).

## What leaves your machine (read this)

The client is source-available precisely so you can verify this yourself — read
[`brethof_brain_client/`](brethof_brain_client/); it's a few hundred lines.

- On **session start** and **each prompt**, it sends your **project name** and
  (for ambient recall) your **current prompt text** to the service, and injects
  the memory that comes back.
- On **each assistant turn** (the `Stop` hook), it reads the *new* lines of your
  agent transcript and sends them to be archived as your memory — this
  includes your messages, the assistant's replies, its thinking blocks, and
  one-line tool-call markers (`[tool_use: Bash]`). **Tool outputs are dropped
  client-side**: the contents of files the assistant reads and the output of
  commands it runs never leave your machine. A local offset file
  (`~/.brethof-brain/state/`) ensures each line is sent once.
- Every request is authenticated with **your API key** and goes only to **your
  endpoint** — your own memory container. Where that is depends on the shape
  you chose in the account panel:
  - **Local** (the default endpoint, `http://127.0.0.1:8610`): the memory
    container runs on your machine; conversations are archived there and
    never stored by us.
  - **Hosted**: your container runs in our cloud at
    `https://memory.brethof.cloud/t/<your-tenant>`, encrypted under a
    passphrase only you hold — add `unlock_passphrase` to your config and
    the client unlocks it at session start and lets it lock itself when you
    step away (`lock_after_minutes`, 5–60).

Nothing else is collected. The client never sends files, environment variables,
or anything outside the transcript text described above. If a hook can't reach
the service it fails silent — your session is never blocked. Two exceptions to
silence, both persistent conditions where staying quiet would lose history: a
**rejected API key** shows a one-line notice at the next session start, and a
**TLS trust failure** prints one line to stderr (seen on brand-new Windows
machines, which load root certificates lazily — open the endpoint once in a
browser and it is fixed for good).

## Getting your memory (two shapes)

Your memory lives in a container. Where that container runs is the one choice
you make, once, in the [account panel](https://brethof.ai/account/):

**On your machine (local).** The panel mints your **hub key** (shown once) —
it goes into the container's configuration and is how your memory reaches the
thinking service. You run the container yourself (install guide:
[brethof.ai/guides](https://brethof.ai/guides/)), mint your **memory key**
during its setup, and you're done — the client's default endpoint
(`http://127.0.0.1:8610`) already points at it. Your conversations never
leave your hardware; only the pieces being curated transit the hub.

**On our cloud (hosted).** The panel creates your container, encrypted under
a **passphrase only you hold**, and shows your endpoint
(`https://memory.brethof.cloud/t/<tenant>`) and **memory key** once. Put all
three in your config — endpoint, `api_key`, `unlock_passphrase` — and the
client unlocks your memory at session start; it locks itself after
`lock_after_minutes` (5–60) of quiet.

## Install as a library / CLI (alternative)

For non-plugin use (scripting, other agents), install straight from the repo:

```bash
pip install git+https://github.com/BrethofAI/brethof-brain-client.git
# or pin a release (tags follow the package version):
pip install git+https://github.com/BrethofAI/brethof-brain-client.git@v1.2.1
```

(There is no PyPI package — the client is installed from source, so you get
exactly the code you can read here.)

Get an API key from [brethof.ai/account](https://brethof.ai) (the brethof-brain
tab), then:

```bash
brethof-brain setup --api-key bmv2_xxxxxxxx
brethof-brain install-hooks      # auto-load & archive memory in Claude Code
brethof-brain mcp-command        # prints the `claude mcp add …` line to run
```

Restart Claude Code (or open a new session) and your memory is live. Check
everything with:

```bash
brethof-brain doctor
brethof-brain status
```

## Configuration

Settings resolve from environment variables, then `~/.brethof-brain/config.json`,
then defaults. With the **CLI install**, the config file is where your key is
stored — `setup` creates it owner-readable-only (`0600`) on Linux/macOS; on
Windows your user-profile ACLs protect it. With the **plugin install**, Claude
Code holds the key instead and the config file isn't needed.

```json
{
  "endpoint": "http://127.0.0.1:8610",
  "api_key": "bmv2_…",
  "unlock_passphrase": "only for the hosted shape — unlocks your memory",
  "lock_after_minutes": 15,
  "default_project": "global",
  "projects": [
    { "path": "/home/me/work/acme", "key": "acme" },
    { "path": "/home/me/work/blog", "key": "blog" }
  ]
}
```

- **Projects** partition your memory. The client picks a project per working
  directory: `$BRETHOF_BRAIN_PROJECT` wins, else the longest matching `path`
  prefix, else `default_project`. A project key matches `[a-z][a-z0-9_]{0,15}`.
- Env overrides: `BRETHOF_BRAIN_ENDPOINT`, `BRETHOF_BRAIN_API_KEY`,
  `BRETHOF_BRAIN_PROJECT` (this session's project), `BRETHOF_BRAIN_DEFAULT_PROJECT`
  (fallback default), `BRETHOF_BRAIN_HOME` (move `~/.brethof-brain` elsewhere).
- Corporate proxies work out of the box: the client honors the standard
  `HTTPS_PROXY` / `HTTP_PROXY` environment variables.

## Commands

| Command | Does |
|---|---|
| `brethof-brain setup` | Save credentials, verify connectivity |
| `brethof-brain install-hooks` | Add the hooks to `~/.claude/settings.json` (idempotent, backs up first) |
| `brethof-brain uninstall-hooks` | Remove them |
| `brethof-brain mcp-command` | Print the `claude mcp add` line for the memory tools |
| `brethof-brain status` | Show your plan and usage |
| `brethof-brain doctor` | Diagnose config, connectivity, and hook wiring |

## Uninstall

```bash
brethof-brain uninstall-hooks
claude mcp remove brethof-brain
pip uninstall brethof-brain-client
```

## License

Source-available under the **brethof-brain Client License** (see
[`LICENSE`](LICENSE)) — free to read, audit, and use with the brethof-brain
service; not for redistribution or building a competing service. Not affiliated
with Anthropic; "Claude" and "Claude Code" are trademarks of Anthropic.