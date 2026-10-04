#!/usr/bin/env node
// Gemini CLI EXTENSION launcher (2026-10-04). The gallery installs the whole
// repo as an extension whose hooks are a fixed file (hooks/hooks.json at the
// repo root), so the hook cannot name the Python that ran a setup script the
// way setup.py does. Gemini CLI always has Node, so this finds a real Python —
// python3, python, then the Windows `py -3` launcher, skipping the Microsoft
// Store stub (exit 9009) — and runs gemini_hook.py with the hook's own stdin.
// Fail-open: no usable Python, exit 0 and the session is never blocked.
"use strict";
const { spawnSync } = require("child_process");
const path = require("path");
const fs = require("fs");

const hook = path.join(__dirname, "gemini_hook.py");
let input = Buffer.alloc(0);
try { input = fs.readFileSync(0); } catch (e) { /* no stdin */ }

for (const [cmd, pre] of [["python3", []], ["python", []], ["py", ["-3"]]]) {
  const r = spawnSync(cmd, [...pre, hook], { input, stdio: ["pipe", "pipe", "pipe"], windowsHide: true });
  if (r.error || r.status === 9009) continue;      // not on PATH, or the Store stub
  if (r.stdout) process.stdout.write(r.stdout);
  if (r.stderr) process.stderr.write(r.stderr);
  process.exit(r.status === null ? 0 : r.status);
}
process.exit(0);
