---
name: onboard
description: "First-run setup: explain brethof-mind, then build the user's projects, rules, and indexes with them. Run once after installing the plugin. Trigger on: onboard, set up memory, first run, initialize memory."
version: 1.0.0
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [memory, onboard, setup, brethof-mind]
    related_skills: [curate]
---

# Onboard — first-run brethof-mind setup

Guide a new user through setting up their brethof-mind cloud memory, then build
their personal layer WITH them. Be conversational and concrete — a guided setup,
not a lecture. There is nothing to install and no local database: the tenant
lives on the server and its tables are created automatically on first write.

## 0. Sense the state
`brethofmind_search("memory_index")`. If nothing meaningful comes back, this is a
fresh tenant — proceed. If projects/rules already exist, treat this as a re-tune:
confirm before overwriting anything.

## 1. Explain what this is (a few lines)
- Memory that survives across sessions and is SHARED across your agents: a
  curated brain you look things up in, plus an immutable archive of every
  conversation.
- **Tiered indexes**: one GENERAL index (the router) + one PER PROJECT. You never
  load everything — you follow the indexes to what you need.
- **Tables**: one curated table per project; `*_chat` (immutable transcript
  archive); `rules` (conventions loaded every session); `state` (one status row
  per project/area).
- **The discipline**: delete what's superseded (no "obsolete" flag); `*_chat` is
  sacred; update-don't-fork.
- **`/curate`** at the end of a session saves + prunes; **`/heal`** ~weekly deep-cleans.

## 2. Interview (one topic at a time — keep it short; WAIT for answers)
1. **Projects** — which codebases/areas do you work in? Each becomes a project key
   (its own memory table, created on first write).
2. **What to remember** — for each project, what should you reliably recall next
   time (decisions, conventions, gotchas, where things live)?
3. **Hard rules** — conventions to enforce every time (cross-cutting → `area='all'`;
   project-specific → that project's area). Imperative and short.

## 3. Write their memory (confirm the plan first, then do it — all via tools)
- **Per-project index** — `brethofmind_save(project="<key>", record_id="memory_index", ...)`
  with a short "what's here / where to look" stub. The first save creates the table.
- **General index** — `brethofmind_save(project="global", record_id="memory_index", ...)`:
  a lean router listing their projects + a one-line pointer to each.
- **Their rules** — `brethofmind_save(project="rules", ...)` for each (right `area`).
- **state** — optionally seed a `state` row per active project with a one-line status.

## 4. Close
Summarise what you wrote (projects, indexes, rules). Tell them to end sessions
with `/curate` and run `/heal` about weekly. Rules for you: don't invent
projects/rules they didn't ask for; confirm before overwriting an index; never
touch `*_chat`.
