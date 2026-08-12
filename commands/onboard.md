---
description: First-run setup — explain brethof-brain, then build your memory (projects, rules, index) with you
---
You are onboarding a new user to **brethof-brain cloud** (their shared agent
memory). Their tenant starts empty; your job is to TEACH the system and build
their PERSONAL layer WITH them, using the memory tools. Be conversational and
concrete — a guided setup, not a lecture. There is nothing to install and no
local database — the tenant lives on the server; you write to it with the tools.

## 0. Sense the state
Try `get_record global:memory_index` and `list_brain global`. If empty, this is
a fresh tenant — proceed. If they already have projects/records, treat this as a
re-tune: confirm before overwriting anything.

## 1. Explain what this is (a few lines, not a wall)
- A memory that survives across sessions and is SHARED across your agents: a
  curated brain you look things up in, plus an immutable archive of every
  conversation (`*_chat`).
- **Tiered indexes**: one GENERAL index (the router) + one index PER PROJECT.
  You never load everything — you follow the indexes to what you need.
- **Tables**: one curated table per project; `*_chat` (immutable transcript
  archive); `rules` (conventions loaded every session); `state` (one status row
  per area).
- **The discipline**: delete what's superseded (no "obsolete" flag), `*_chat` is
  sacred, update-don't-fork. `/curate` at the end of a session saves + prunes.
Invite a question, then move on.

## 2. Interview (one topic at a time — keep it short; WAIT for answers)
1. **Projects** — which codebases/areas do you work in, and where do they live
   (absolute path or a distinctive substring)? Each becomes a project key (its
   own memory table).
2. **What to remember** — for each project, what should the agent reliably
   recall next time (decisions, conventions, gotchas, where things live)?
3. **Hard rules** — any conventions to enforce every time (cross-cutting →
   `area='all'`; project-specific → that project's area)? Imperative and short.

## 3. Write their memory (confirm the plan first, then do it — all via tools)
- **Per-project index** — for each project, `save_memory` a `<key>:memory_index`
  record (memory_type `reference`) with a short "what's here / where to look"
  stub they can grow. The first write auto-creates the project's table.
- **General index** — `save_memory` `global:memory_index`: a lean router listing
  their projects + a one-line pointer to each project index.
- **Their rules** — `save_memory` each into the `rules` table (project = `rules`,
  correct `area`). Imperative, no hedge.
- **state** — optionally seed a `state:<area>` row per active project with a
  one-line status.

## 4. Configure the client's project mapping
So each working directory uses the right project, tell them to map directories to
project keys — set `default_project` (or a `projects` list of `{path, key}`) in
`~/.brethof-brain/config.json`, or per-session via `$BRETHOF_BRAIN_PROJECT`. Without
a mapping everything goes to `global`.

## 5. Close
Summarise what you wrote (projects, index, rules, mapping). From now on, end
sessions with `/curate` and run `/heal` about weekly. Rules while onboarding:
don't invent projects or rules they didn't ask for; confirm before overwriting an
existing index; never touch `*_chat`.
