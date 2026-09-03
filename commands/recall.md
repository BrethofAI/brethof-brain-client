---
description: Recall from brethof-brain — the hybrid search over curated memory and the full history, then the exact-string and history lanes
argument-hint: <topic or question>
---
Recall everything relevant to: $ARGUMENTS

1. **Start with `search_brain`** — hybrid search (vector + keyword, fused and
   ranked) over the curated memory AND the conversation archive in one list.
2. Follow the lanes where that list points:
   - **`search_history`** — the archive alone: past sessions in full, for
     what was said rather than what was kept.
   - **`get_record`** — the whole record behind a truncated preview.
   - **`graph`** — what the memory links together around a name: kinds,
     relations, what superseded what.
   - **`get_playbook`** — a procedure, when the answer is "how it is done".
3. Synthesize ONE grounded answer. Cite the record ids you used. Note dates
   and flag anything that looks stale. If the memory does not hold it, say so
   plainly — never assert memory contents from assumption.
