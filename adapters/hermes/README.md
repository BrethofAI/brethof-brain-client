# brethof-mind cloud + Hermes

[Hermes](https://github.com/NousResearch/hermes-agent) is MCP-native, so it
needs **no extra code** to use brethof-mind cloud — you register the remote MCP
endpoint and Hermes auto-discovers all 15 memory tools (`recall`, `save_memory`,
`get_memory`, `semantic_search`, `query_raw`, …).

## Wire it up

Add a `brethof-mind` server under `mcp_servers:` in your Hermes `cli-config.yaml`
(see `mcp_servers.example.yaml` here):

```yaml
mcp_servers:
  brethof-mind:
    url: https://api.brethof.cloud/v1/mcp
    headers:
      Authorization: "Bearer bm_live_your_key_here"
    timeout: 60
    connect_timeout: 30
```

Keep your key out of shared configs — Hermes reads secrets from `~/.hermes/.env`,
so prefer putting the key there and referencing it if your Hermes version
supports env expansion in headers; otherwise the value above lives only in your
private local config.

Restart Hermes; the tools appear automatically. Verify with `hermes` →
`/tools` (you should see the brethof-mind tools) or just ask it to
`recall` something.

## How it fits Hermes's own memory

Hermes ships a small **note memory** (`MEMORY.md` + `USER.md`, ~a few hundred
tokens, injected into the system prompt). That is complementary, not redundant:

| | Hermes note memory | brethof-mind cloud |
|---|---|---|
| Size | tiny, hand-curated | unbounded, searchable |
| Shape | always-on system-prompt notes | on-demand RAG (vector + keyword + graph) |
| Scope | this Hermes instance | shared across all your agents |

Keep Hermes's note memory for a handful of always-true facts; use brethof-mind
for the deep, cross-agent, searchable store. If you want brethof-mind to be the
single memory, you can lower `memory_char_limit` / disable `user_profile_enabled`
in Hermes and lean on `recall`/`save_memory`.

## Archiving Hermes conversations (optional)

The MCP tools give Hermes read/write memory. If you also want Hermes *sessions*
archived into the cloud chat store (like the Claude Code `Stop` hook does), call
the programmatic API from a Hermes session hook:

```python
from brethof_mind_client import MindClient
MindClient().archive_turns("hermes", session_id, turns)
```

where `turns` is `[{index, line_type: "user"|"assistant", text, timestamp}]`.
