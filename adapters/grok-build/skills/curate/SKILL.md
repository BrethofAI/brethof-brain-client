---
name: curate
description: "Save something to brethof-brain memory explicitly — a decision, convention, or fact that must be remembered exactly as stated. Memory also learns automatically from every exchange; use this when precision or immediacy matters. Trigger on: remember this, save to memory, don't forget, note this down."
version: 2.0.0
platforms: [linux, macos, windows]
---

# Save to memory — explicit remembering

brethof-brain learns from your conversations **automatically**: the memory
service curates every exchange as it happens, keeps what is durable, updates
what changed, and discards what went stale. You do NOT need to summarize
sessions, run end-of-session curation, or maintain memory hygiene — that is
the service's job now, and doing it by hand just duplicates it.

Use this skill for the cases automation shouldn't guess at:
- The user says **"remember this"** — save their exact intent.
- A **decision or convention** was settled and must be recorded precisely.
- A fact matters for **other projects** than the one you're in.

## Your tools
- `save_project(content, project)` / `save_general(content)` — save one
  durable fact. State it self-contained: a reader a month from now must
  understand it without this conversation; include concrete names, dates,
  numbers. The memory service does the filing — placement, dedupe, and
  superseding of stale records are its job, not yours.
- `save_rule(content, project)` — one door; it replies with a question and a token, and your answer ('1' every project / '2' this project / '3' knowledge) plus that token in a second call files it —
  save a RULE: a standing convention that must bind every future session
  without being looked up. THE TEST: does it change what you DO every
  session? A fact, setting, or measurement is knowledge — save it with the
  fact tools, never as a rule. General rules load in every project; use
  them sparingly.
- `search_brain(query)` — check first whether memory already holds it;
  if a result already says the same thing, saving again is noise.
- `delete_record` — remove a saved memory the user
  says is wrong or dead. Conversation history is never touched by this.

## Steps
1. Search first. If memory already knows it, stop — or save only the delta.
2. Decide the kind: standing convention → rule tool; everything else → fact
   tool, under the project it is about. ONE fact per call.
3. Confirm to the user in one line what was saved and where.

Most of what happens in a session should NOT be explicitly saved — the
automatic layer already has it. Explicit saves are for emphasis, not bulk.
