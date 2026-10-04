#!/usr/bin/env python3
"""Connect this computer to your brethof-brain memory — the plugin's way to
run `brethof-brain connect` with no pip install: a window on your screen takes
the API key (and a hosted memory's passphrase), checks them with your memory
and saves them; an agent running this never sees them.

    python3 connect.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from brethof_brain_client.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(["connect", *sys.argv[1:]]))
