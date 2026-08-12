---
name: recall
description: "Recall from brethof-brain memory — current truth first, full conversation history second. Use before asking the user something that may already be answered. Trigger on: recall, remember, what did we decide, look it up, check memory."
version: 2.0.0
platforms: [linux, macos, windows]
---

# Recall — search brethof-brain memory

Find what's already known before assuming or asking. Recall is unlimited —
search as often as you like, on every plan.

## The two stores, and which to trust
- `search_brain(query)` — **saved memory: the current truth.** The
  service keeps it curated — superseded decisions are updated or removed, so
  what you find here is what the team believes NOW. Start here, always.
- `search_history(query)` — **conversation history: complete but raw.**
  Everything ever said, including ideas later reversed. Use it to recover
  detail the curated answer lacks ("what exactly was the error message",
  "when did we first discuss X") — and treat old statements as snapshots of
  their moment, not as current truth.

## Steps
1. `search_brain` with natural-language keywords for the topic (not
   boolean `X OR Y`, not bare project names).
2. Thin result? Re-probe once with different wording — different words
   surface different memories.
3. Need the play-by-play or an exact string? `search_history`.

Then synthesise ONE grounded answer:
- Say which memories you used.
- If curated memory and old history disagree, curated memory wins — history
  is how it looked then, memory is how it is now.
- If the answer isn't in memory, say so plainly — never assert memory
  contents from assumption.
