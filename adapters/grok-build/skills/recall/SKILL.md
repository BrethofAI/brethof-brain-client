---
name: recall
description: "Recall from brethof-mind memory by meaning and keyword — curated decisions/conventions/runbooks AND past sessions. Use before asking the user something that may already be answered. Trigger on: recall, remember, what did we decide, look it up, check memory."
version: 1.0.0
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [memory, recall, brethof-mind]
    related_skills: [curate]
---

# Recall — search brethof-mind memory

Find what's already known before assuming or asking. brethof-mind is shared
long-term memory; search it first.

## Your tools
- `brethofmind_search(query)` — curated memory across ALL projects (decisions,
  conventions, runbooks, status). Results start with their full id `table:key`.
- `brethofmind_recall(query)` — the chat archive (past sessions): what was
  discussed, decided, or tried before.

## Steps
1. **Start with `brethofmind_search`** using NATURAL-LANGUAGE keywords for the
   topic (not boolean `X OR Y`, not bare project keys).
2. If it's about a past conversation ("what did we decide", "did we try…"), also
   `brethofmind_recall`.
3. Re-probe once with a rephrased query if the first pass is thin — different
   wording surfaces different records.

Then synthesise ONE grounded answer:
- Cite the record ids you used.
- Check provenance; flag anything that looks stale or volatile.
- If the answer isn't in memory, say so plainly — never assert memory contents
  from assumption.
