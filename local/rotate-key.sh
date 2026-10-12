#!/bin/bash
# Replace your memory key in one step (a leaked key, a machine you gave away):
#
#   ./rotate-key.sh
#
# A new key goes into this stack's key file and into your agents' config
# (~/.brethof-brain/config.json); the old key stops working at once. The
# running memory and your agents pick the new one up by themselves — nothing
# restarts, and the key is never printed. BRAIN_SHOW_KEY=1 shows it, for a
# tool you wired by hand.
#
# This is the memory key, the one your agents use. The hub key (learning) is
# replaced by ./login.sh.
set -euo pipefail
cd "$(dirname "$0")"
exec bash mint-key.sh --rotate
