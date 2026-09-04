---
name: onboard
description: "First-run setup of brethof-brain — explain it in a few lines, then build the user's memory (projects, purposes, rules, folder mapping) with them. Trigger on: onboard, set up memory, first run."
version: 2.0.0
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [memory, onboarding, brethof-brain]
    related_skills: [recall, curate]
---

# Onboard — build the user's memory with them

You are onboarding a new user to **brethof-brain**, their persistent memory.
Their memory starts empty; explain the little that matters and build their
first projects WITH them, using the memory tools. Conversational and concrete
— a guided setup, not a lecture. Wait for answers.

## 0. Sense the state
`list_projects` and `session_context`. Empty → a fresh memory, proceed. Projects
already there → treat this as a re-tune: confirm before changing anything.

## 1. Explain what this is (a few lines, not a wall)
- Memory that survives across sessions and machines. At every session start you
  are handed the standing rules, each project's purpose, the last sessions'
  handover notes; on every prompt, the records that bear on it arrive before
  you answer. You do not have to search — but you can (the recall skill).
- Everything said is archived and searchable. What is worth keeping becomes a
  **record** — the service's curator decides that from what is said; you never
  write records by hand.
- **Four doors**, nothing else writes: `save_project` / `save_general` (a fact,
  a decision, a measurement — into history at once; the curator keeps a record
  if a future session must be handed it); `save_note` (where your work stands,
  for whoever picks the project up); `save_playbook` (how a thing is done);
  `save_rule` (a standing convention every session must follow).
- Memory is organised by **project** — one per codebase, product or long-running
  topic — and each project's one-line **purpose** teaches its curator what
  matters there.
Invite a question, then move on.

## 2. Interview (one topic at a time; keep it short)
1. **Projects** — which codebases or areas do they work in?
2. **Purpose** — for each: one or two sentences, what it IS and what should be
   remembered there.
3. **Rules** — conventions to enforce every time. Cross-cutting → a general
   rule; one project's own → that project's rule. Imperative and short.

## 3. Write it (confirm the plan first, then do it — all through the tools)
- `add_project(project, purpose, rules)` for each project — the purpose is what
  teaches the Brain from day one. Project keys match `[a-z][a-z0-9_]{0,15}`.
- `save_rule` for each convention; it asks where the rule must live — answer
  honestly (every project, this project, or knowledge).

## 4. The project this agent works in
Hermes archives to ONE project per agent: `BRETHOF_BRAIN_PROJECT` in
`~/.hermes/.env` (or `default_project` in `~/.brethof-brain/config.json`).
Without it, work files under `global`. Tell the user which project this agent
uses and change it if they say so.

## 5. Close
Summarise what you created. From now on: say what you learn and decide — the
memory listens; before a session ends, `save_note` where things stand. Never
invent projects or rules they did not ask for.
