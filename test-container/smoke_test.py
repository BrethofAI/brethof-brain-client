#!/usr/bin/env python3
"""Containerized smoke test for brethof-brain cloud.

Runs INSIDE the OpenClaw-style test container: a non-Claude-Code, headless
Python agent exercising the full client against the live service. Proves the
whole loop works from a plain container — auth, the customer MCP tools, and turn
archival — with clear PASS/FAIL output and a non-zero exit on any failure.

Config comes from the environment (BRETHOF_BRAIN_API_KEY, optionally
BRETHOF_BRAIN_ENDPOINT / BRETHOF_BRAIN_PROJECT).
"""
from __future__ import annotations

import os
import sys
import time

from brethof_brain_client import MindClient
from brethof_brain_client.client import ClientError

# Windows consoles default to cp1252 — make our own output crash-proof so a
# '→' in a label can't turn a passing check into a bogus FAIL.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

PROJECT = os.environ.get("BRETHOF_BRAIN_PROJECT", "global")
REC_ID = "openclaw_container_probe"          # UPSERT id → test is re-runnable
SESSION = "openclaw-container-smoke"


def main() -> int:
    passed, failed = 0, 0

    def check(name, cond, detail=""):
        nonlocal passed, failed
        ok = bool(cond)
        passed += ok
        failed += (not ok)
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
        return ok

    print("brethof-brain cloud — container smoke test")
    try:
        m = MindClient()
    except ClientError as e:
        print(f"  [FAIL] configure client — {e}")
        print("\nRESULT: FAIL (no credentials — set BRETHOF_BRAIN_API_KEY)")
        return 1

    print(f"endpoint: {m.cfg.endpoint}  project: {PROJECT}")

    # 1. transport + tool discovery.
    # NO MAGIC NUMBER: this asserted "15 tools" and failed the day the
    # surface grew to 16 — a number in a test is a fact that rots. What
    # matters is that the tools this library CALLS actually exist.
    try:
        tools = {t["name"] for t in m.list_tools()}
        needed = {"search_brain", "search_history", "get_record",
                  "list_brain", "list_projects", "list_rules", "graph",
                  "session_context", "save_project", "save_general",
                  "save_project_rule", "save_general_rule", "delete_record",
                  "add_project", "delete_project", "cleanup_history"}
        missing = sorted(needed - tools)
        check("every tool this client calls exists on the live surface",
              not missing, f"{len(tools)} tools; missing {missing}" if missing
              else f"{len(tools)} tools")
    except Exception as e:  # noqa: BLE001
        check("MCP tools/list", False, str(e))

    # 2. auth + usage view
    try:
        u = m.usage()
        check("usage() authenticated", bool(u.get("plan")), f"plan={u.get('plan')}")
    except Exception as e:  # noqa: BLE001
        check("usage()", False, str(e))

    # 3. write → read round-trip, through the CUSTOMER doors. Saves are
    # INTENTS filed asynchronously by the service, so the read polls instead
    # of assuming the record is there the instant save returns.
    try:
        m.save_project(f"Container smoke probe {REC_ID}: written by the "
                       f"containerised install test to prove a brand-new "
                       f"account can save and read back.", PROJECT)
        found = ""
        for _ in range(24):
            time.sleep(5)
            found = m.search_brain(REC_ID, project=PROJECT)
            if REC_ID.lower() in found.lower():
                break
        check("save_project → search_brain round-trip",
              REC_ID.lower() in found.lower(), "record read back")
    except Exception as e:  # noqa: BLE001
        check("save/read round-trip", False, str(e))

    # 4. the second store — the raw conversation archive — answers too
    try:
        m.search_history("container", project=PROJECT)
        check("search_history() answers", True, "ok")
    except Exception as e:  # noqa: BLE001
        check("search_history()", False, str(e))

    # 5. archive a turn
    try:
        env = m.archive_turns(PROJECT, SESSION, [
            {"index": 0, "line_type": "user",
             "text": "Container test: archive this turn.", "embed": True},
            {"index": 1, "line_type": "assistant",
             "text": "Archived from the OpenClaw test container.", "embed": True},
        ])
        check("archive_turns() accepted", env.get("status") == "ok",
              f"status={env.get('status')} archived={env.get('archived')}")
    except Exception as e:  # noqa: BLE001
        check("archive_turns()", False, str(e))

    # 6. hooks path — the generic AgentHooks used by the OpenClaw adapter
    try:
        from brethof_brain_client import AgentHooks
        h = AgentHooks(project=PROJECT, session_id="container-hooks")
        block = h.session_start()
        check("AgentHooks.session_start()", isinstance(block, str), f"{len(block)} chars")
        env = h.archive("container hook test: user turn",
                        "container hook test: assistant turn")
        check("AgentHooks.archive()", env.get("status") == "ok",
              f"status={env.get('status')}")
    except Exception as e:  # noqa: BLE001
        check("AgentHooks (session_start + archive)", False, str(e))

    # 7. OpenClaw MemorySession wrapper end-to-end
    try:
        import openclaw_hooks
        check("OpenClaw MemorySession demo", openclaw_hooks.demo(), "two-turn session")
    except Exception as e:  # noqa: BLE001
        check("OpenClaw MemorySession demo", False, str(e))

    print(f"\nRESULT: {'PASS' if failed == 0 else 'FAIL'}  ({passed} passed, {failed} failed)")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
