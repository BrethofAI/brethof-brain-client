#!/usr/bin/env python3
"""Containerized smoke test for brethof-mind cloud.

Runs INSIDE the OpenClaw-style test container: a non-Claude-Code, headless
Python agent exercising the full client against the live service. Proves the
whole loop works from a plain container — auth, the 15 MCP tools, and turn
archival — with clear PASS/FAIL output and a non-zero exit on any failure.

Config comes from the environment (BRETHOF_MIND_API_KEY, optionally
BRETHOF_MIND_ENDPOINT / BRETHOF_MIND_PROJECT).
"""
from __future__ import annotations

import os
import sys

from brethof_mind_client import MindClient
from brethof_mind_client.client import ClientError

PROJECT = os.environ.get("BRETHOF_MIND_PROJECT", "global")
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

    print("brethof-mind cloud — container smoke test")
    try:
        m = MindClient()
    except ClientError as e:
        print(f"  [FAIL] configure client — {e}")
        print("\nRESULT: FAIL (no credentials — set BRETHOF_MIND_API_KEY)")
        return 1

    print(f"endpoint: {m.cfg.endpoint}  project: {PROJECT}")

    # 1. transport + tool discovery
    try:
        tools = m.list_tools()
        check("MCP tools/list returns 15 tools", len(tools) == 15, f"got {len(tools)}")
    except Exception as e:  # noqa: BLE001
        check("MCP tools/list", False, str(e))

    # 2. auth + usage view
    try:
        u = m.usage()
        check("usage() authenticated", bool(u.get("plan")), f"plan={u.get('plan')}")
    except Exception as e:  # noqa: BLE001
        check("usage()", False, str(e))

    # 3. write → read round-trip
    try:
        m.save_memory(PROJECT, REC_ID, "reference", "Container smoke probe",
                      "Written by the OpenClaw-style test container. [[brethof-mind-client]]")
        got = m.get_memory(f"{PROJECT}:{REC_ID}")
        check("save_memory → get_memory round-trip", "smoke probe" in got.lower(),
              "record read back")
    except Exception as e:  # noqa: BLE001
        check("save/get round-trip", False, str(e))

    # 4. recall finds it
    try:
        hits = m.recall("container smoke probe", project=PROJECT, top_k=5)
        check("recall() finds the probe", REC_ID in hits, "in results")
    except Exception as e:  # noqa: BLE001
        check("recall()", False, str(e))

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

    print(f"\nRESULT: {'PASS' if failed == 0 else 'FAIL'}  ({passed} passed, {failed} failed)")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
