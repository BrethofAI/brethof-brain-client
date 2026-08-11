---
name: onboard
description: "First-run setup: connect brethof-mind cloud memory and explain how it works. Run once after installing the plugin. Trigger on: onboard, set up memory, first run, initialize memory."
version: 2.0.0
platforms: [linux, macos, windows]
---

# Onboard — connect brethof-mind memory

Guide a new user through connecting their brethof-mind cloud memory. Be
conversational and concrete — a guided setup, not a lecture. There is
nothing to install server-side and no local database: memory lives in the
cloud and starts working on the first conversation.

## 1. The key
- The user creates an API key in their account panel:
  **brethof.ai/account → Memory tab → New key** (2FA required once).
- Put it in the environment: the brethof-mind MCP server entry in your ~/.grok config (see mcp_servers.example.toml).
- Never echo the key back, never store it in memory or logs.

## 2. Verify the connection
Call `search_brain("test")`. Any well-formed response — even "no
results" — means the key works. An auth error means the key is wrong or
revoked: back to the panel.

## 3. Explain how it works (a few lines, in your own words)
- **Memory is automatic.** Every exchange is archived, and the memory
  service curates it as you work — decisions, facts, and corrections land
  in memory within seconds, without anyone summarizing anything.
- **Projects are just names.** Pass a project when saving or searching;
  it exists the moment it's first used. No setup, no limit on how many.
- **Recall is unlimited** on every plan — search freely, always.
- **Two stores**: saved memory (current truth, curated) and conversation
  history (complete, raw). The /recall skill explains when to use which.
- **Two kinds of saves**: FACTS (`save_project` / `save_general`) and
  RULES (`save_project_rule` / `save_general_rule`). A rule is a standing
  convention that binds every session; everything else is a fact.
- **Explicit saves** are for emphasis: "remember this" → /curate skill.
- Usage and plan live in the account panel; the service emails a heads-up
  when usage approaches the plan's allowance.

## 4. First real moment
Ask the user to tell you one durable fact about their work (a preference,
a convention, a current goal) and save it with `save_project` (or
`save_general` if it isn't tied to one project). Then search for it —
showing the round trip beats explaining it.
