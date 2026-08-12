#!/usr/bin/env python3
"""Plugin hook entrypoint.

The Claude Code plugin bundles the ``brethof_brain_client`` package alongside this
file and points its hooks here, so users don't need a separate ``pip install`` —
only a Python interpreter on PATH. This shim puts the bundled package on
``sys.path`` and dispatches to the real hook handler, which reads the event name
from argv (``session-start`` / ``prompt-submit`` / ``stop`` / ``pre-compact``).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from brethof_brain_client.hook import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
