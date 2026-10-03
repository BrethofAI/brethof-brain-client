#!/usr/bin/env python3
"""The Claude Code plugin's MCP server: the memory tools over stdio, with the
key and address read from ~/.brethof-brain/config.json (what `connect` saves).
See brethof_brain_client/mcpbridge.py."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from brethof_brain_client.mcpbridge import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
