"""ADAPTER FRESHNESS — the adapters teach a tool vocabulary they do not own.

The customer tool surface lives on the server and moves with the product; every
adapter (openclaw, hermes, grok-build) hand-writes tool names into code, MCP
configs and SKILL files. History shows they rot silently: by 2026-08-08 the
adapters referenced `save_state` (never existed on v2), `recall`/`save_memory`
(owner-tier only) and `search_chat` (pre-rename) — all dead words for a
customer key. This test makes that rot loud: every tool-shaped reference in
adapters/ must exist in the LIVE customer tools/list.

Needs BRETHOF_BRAIN_FRESHNESS_KEY (any customer-tier key; conftest scrubs the
normal auth vars for isolation) — skipped when absent, so the offline suite
stays green; run it wherever the live API is reachable.
"""
import json
import os
import pathlib
import re
import urllib.request

import pytest

ADAPTERS = pathlib.Path(__file__).resolve().parents[1] / "adapters"
SCAN_SUFFIXES = {".py", ".md", ".yaml", ".yml", ".toml", ".json"}

# A reference "looks like a tool" when it is verb_noun in our tool grammar, or
# one of the known single-word tools past and present. Single words only count
# when quoted/backticked/called — bare prose ("we recall the fact") is English,
# not a tool reference.
VERB_PATTERN = re.compile(
    r"\b((?:save|search|list|get|delete|add|cleanup|load|supersede)_[a-z_]+)\b")
SINGLE_WORD_TOOLS = ("recall", "graph", "session_context", "memory_health",
                     "semantic_search")
SINGLE_PATTERN = re.compile(
    r"""["'`(](%s)["'`)]""" % "|".join(SINGLE_WORD_TOOLS))
# Snake_case that matches the verb grammar but is not a tool reference —
# stdlib-ish helpers plus the adapters' OWN wrapper method names.
# save_rule LEFT this set 2026-08-14: it was the openclaw wrapper's method
# name back when the server tools were save_general_rule/save_project_rule;
# it is now the ONE server-side rule door and must count as a reference.
NOT_TOOLS = {"load_env", "get_json", "save_file", "load_config", "load_json",
             "get_config", "add_argument", "get_env",
             "save_fact"}


def live_customer_tools() -> set[str]:
    key = os.environ.get("BRETHOF_BRAIN_FRESHNESS_KEY", "")
    endpoint = os.environ.get("BRETHOF_BRAIN_FRESHNESS_ENDPOINT",
                              "https://api.brethof.cloud").rstrip("/")
    if not key:
        pytest.skip("BRETHOF_BRAIN_FRESHNESS_KEY not set — needs the live API")
    body = json.dumps({"jsonrpc": "2.0", "id": 1,
                       "method": "tools/list"}).encode()
    req = urllib.request.Request(
        endpoint + "/mcp", data=body,
        headers={"Authorization": "Bearer " + key,
                 "Content-Type": "application/json",
                 "User-Agent": "brethof-brain-client-tests/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        payload = json.load(r)
    tools = {t["name"] for t in payload["result"]["tools"]}
    assert tools, "live tools/list came back empty — cannot judge freshness"
    return tools


def referenced_tools(path: pathlib.Path) -> set[str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix == ".py":
        # In code, a tool reference is a STRING (a name sent to an API);
        # bare identifiers are the adapter's own functions, not references.
        # Single-word tools count only as a WHOLE string ("recall") — inside
        # prose they are English (or a /skill name), not a tool call.
        strings = re.findall(r"""["'`]([^"'`\n]+)["'`]""", text)
        found = set(VERB_PATTERN.findall(" ".join(strings))) | {
            s for s in strings if s in SINGLE_WORD_TOOLS}
    else:
        found = set(VERB_PATTERN.findall(text)) | set(
            SINGLE_PATTERN.findall(text))
    return found - NOT_TOOLS


def adapter_files():
    for p in sorted(ADAPTERS.rglob("*")):
        if (p.is_file() and p.suffix in SCAN_SUFFIXES
                and "__pycache__" not in p.parts):
            yield p


def test_adapters_reference_only_live_tools():
    live = live_customer_tools()
    violations = []
    for path in adapter_files():
        dead = referenced_tools(path) - live
        if dead:
            rel = path.relative_to(ADAPTERS.parent)
            violations.append(f"{rel}: {', '.join(sorted(dead))}")
    assert not violations, (
        "Adapters reference tools the live customer surface does not expose "
        "(rename, removal, or tier mismatch):\n  " + "\n  ".join(violations))


def test_adapters_teach_the_rules_door():
    """Every adapter's taught surface must include the rules door — an agent
    that cannot save law is running a pre-2026-08-07 model of the product."""
    live_customer_tools()                       # same skip-without-key gate
    for name in ("openclaw", "hermes", "grok-build"):
        refs = set()
        for path in adapter_files():
            if name in path.parts:
                refs |= referenced_tools(path)
        assert refs & {"save_rule"}, (
            f"adapter '{name}' never mentions the rules door (save_rule — "
            "the ONE door since 2026-08-14; the split "
            "save_general_rule/save_project_rule surface is gone)")
