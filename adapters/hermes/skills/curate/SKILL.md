---
name: curate
description: "Close the session into brethof-brain — file what this session found and decided, then leave the handover note. Trigger on: curate, wrap up, remember this, save what we did, close the session."
version: 2.0.0
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [memory, curate, brethof-brain]
    related_skills: [recall, onboard]
---

# Curate — close this session into memory

The curator keeps records from what is SAID, so your job is to say the durable
things clearly, then leave the note the next session picks up. Be thorough and
honest; nothing here is deleted by you.

1. **Recover the whole session.** If context was compressed, rebuild the early
   half with `search_history` (your turns are archived) and work from that.
2. **File the findings** — one `save_project` per durable thing, in the project
   it belongs to: every decision with its why, every measured result, every
   trap found and its fix, every dead end ruled out. A correction to something
   saved earlier is simply another save. Skip anything a session would not need
   to be handed.
3. **Procedures** — anything of the form "how to do this" that took work to
   find goes through `save_playbook`, not a save.
4. **Rules** — a lasting convention the human stated, or a correction they gave
   you, goes through `save_rule`.
5. **The note** — `save_note(project, session_id, title, body)`: where this
   thread stands, what is live, what is next; under 2,000 characters. The
   session id is in your BRAIN briefing. Writing again replaces your note.
6. **Report** in a few lines: what you filed, the note's title, anything left
   open. Records, pruning and consolidation are the service's work, not yours.
