---
name: curate
description: "Save something to brethof-mind memory explicitly — a decision, convention, or fact that must be remembered exactly as stated. Memory also learns automatically from every exchange; use this when precision or immediacy matters. Trigger on: remember this, save to memory, don't forget, note this down."
version: 2.0.0
platforms: [linux, macos, windows]
---

# Save to memory — explicit remembering

brethof-mind learns from your conversations **automatically**: the memory
service curates every exchange as it happens, keeps what is durable, updates
what changed, and discards what went stale. You do NOT need to summarize
sessions, run end-of-session curation, or maintain memory hygiene — that is
the service's job now, and doing it by hand just duplicates it.

Use this skill for the cases automation shouldn't guess at:
- The user says **"remember this"** — save their exact intent.
- A **decision or convention** was settled and must be recorded precisely.
- A fact matters for **other projects** than the one you're in.

## Your tools
- `the memory save tool your brethof-mind MCP server lists (save_project / save_general, or save_memory on a full-access key)` — save one durable fact. Write
  it self-contained: a reader a month from now must understand it without
  this conversation. Include concrete names, dates, numbers.
- `search_memory(query)` — check first whether memory already holds it;
  if a result already says the same thing, saving again is noise.
- `delete_memory` — remove a saved memory the user
  says is wrong or dead. Conversation history is never touched by this.

## Steps
1. Search first. If memory already knows it, stop — or save only the delta.
2. Save ONE fact per call, self-contained, under the project it is about.
3. Confirm to the user in one line what was saved and where.

Most of what happens in a session should NOT be explicitly saved — the
automatic layer already has it. Explicit saves are for emphasis, not bulk.
