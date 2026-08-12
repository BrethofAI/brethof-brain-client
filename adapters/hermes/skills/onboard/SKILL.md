---
name: onboard
description: "First-run setup: connect brethof-brain cloud memory and explain how it works. Run once after installing the plugin. Trigger on: onboard, set up memory, first run, initialize memory."
version: 2.0.0
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [memory, onboard, setup, brethof-brain]
    related_skills: [curate, recall]
---

# Onboard — connect brethof-brain memory

Guide a new user through connecting their brethof-brain cloud memory. Be
conversational and concrete — a guided setup, not a lecture. There is
nothing to install server-side and no local database: memory lives in the
cloud and starts working on the first conversation.

## 1. The key
- The user creates an API key in their account panel:
  **brethof.ai/account → Memory tab → New key** (2FA required once).
- Put it in the environment: `BRETHOF_BRAIN_API_KEY=<key>` (and optionally
  `HERMES_MEMORY_PROJECT=<project>` for this agent's default project).
- Never echo the key back, never store it in memory or logs.

## 2. Verify the connection
Call `brethofmind_search("test")`. Any well-formed response — even "no
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
- **Explicit saves** are for emphasis: "remember this" → /curate skill.
- Usage and plan live in the account panel; the service emails a heads-up
  when usage approaches the plan's allowance.

## 4. First real moment
Ask the user to tell you one durable fact about their work (a preference,
a convention, a current goal) and save it with `brethofmind_save`. Then
search for it — showing the round trip beats explaining it.
