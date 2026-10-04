"""The session-start hook writes the managed memory-provider block under
Claude Code (2026-09-29): Claude Code's own auto memory otherwise takes
"remember X" — measured on the rig (claude-code-mem@lin)."""
from __future__ import annotations

from brethof_brain_client import claude_files, hook


def _run(tmp_path, monkeypatch, env: dict, inp: dict | None = None):
    md = tmp_path / "CLAUDE.md"
    monkeypatch.setattr(claude_files, "CLAUDE_USER_MD", str(md))
    for k in ("CLAUDE_PLUGIN_ROOT", "CLAUDECODE", "BRETHOF_BRAIN_NO_CLAUDE_MD"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    hook._claude_block(inp or {})
    return md


def test_a_plugin_install_never_writes_it(tmp_path, monkeypatch):
    # Anthropic's directory flags a plugin that edits Claude's own files
    # (2026-10-04): under the plugin the block is a manual README step.
    assert not _run(tmp_path, monkeypatch, {"CLAUDE_PLUGIN_ROOT": "/x", "CLAUDECODE": "1"}).exists()


def test_written_under_claude_code_once_and_idempotent(tmp_path, monkeypatch):
    md = _run(tmp_path, monkeypatch, {"CLAUDECODE": "1"})
    text = md.read_text()
    assert text.count("Memory provider: the Brain") == 1 and "auto memory" in text
    assert "`graph`" not in text
    hook._claude_block({})
    assert md.read_text() == text


def test_the_transcript_path_alone_says_claude_code(tmp_path, monkeypatch):
    md = _run(tmp_path, monkeypatch, {}, {"transcript_path": "/home/u/.claude/projects/p/s.jsonl"})
    assert md.exists()


def test_other_harnesses_and_the_opt_out_leave_it_alone(tmp_path, monkeypatch):
    assert not _run(tmp_path, monkeypatch, {}, {}).exists()
    assert not _run(tmp_path, monkeypatch, {"CLAUDECODE": "1", "BRETHOF_BRAIN_NO_CLAUDE_MD": "1"}).exists()


def test_the_customers_own_text_is_kept(tmp_path, monkeypatch):
    md = tmp_path / "CLAUDE.md"
    md.write_text("# my own rules\n- tabs, never spaces\n")
    _run(tmp_path, monkeypatch, {"CLAUDECODE": "1"})
    text = md.read_text()
    assert text.startswith("# my own rules") and "Memory provider: the Brain" in text
