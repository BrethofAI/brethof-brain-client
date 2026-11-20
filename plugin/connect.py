#!/usr/bin/env python3
"""Connect this computer to your Brain hub — the plugin's way to run
`brethof-brain connect` with no pip install: it pairs with the hub on this
machine (or the one named with --endpoint), the hub's owner approves the code
on the hub's settings page, and the device key is saved without being shown;
an agent running this never sees it.

    python3 connect.py [--endpoint https://your-hub]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from brethof_brain_client.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(["connect", *sys.argv[1:]]))
