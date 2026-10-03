#!/bin/bash
# Create the key your agent uses to reach YOUR memory. Run once, before the
# first `docker compose up`.
#
# The key is shown ONCE and never stored: this stack keeps only its SHA-256
# hash, so nobody -- including us -- can read it back out of your files. Lose
# it and you mint another; there is no recovery and none is needed.
#
# WHY A KEY AT ALL ON YOUR OWN MACHINE. The API listens on loopback, and
# loopback is not a boundary: every process on the box, every container, and
# anything that talks a browser into a request can reach it. The key is what
# separates your agent from everything else running as you.
set -euo pipefail
cd "$(dirname "$0")"

KEYDIR=${BRAIN_KEY_DIR:-./keys}
KEYFILE=$KEYDIR/v2keys
TENANT=${BRAIN_TENANT:-memory}

if [ -e "$KEYFILE" ]; then
  echo "$KEYFILE already exists. Delete it to mint a new key -- and update" >&2
  echo "your agent's config when you do, because the old one stops working." >&2
  exit 1
fi

# [a-z0-9_]{3,40}: this becomes the Postgres database name.
printf '%s' "$TENANT" | grep -qE '^[a-z0-9_]{3,40}$' \
  || { echo "BRAIN_TENANT must be 3-40 chars of a-z, 0-9, _" >&2; exit 1; }

KEY="bmv2_$(head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n')"
HASH=$(printf '%s' "$KEY" | sha256sum | cut -d' ' -f1)

mkdir -p "$KEYDIR"
# ':customer' = the tool tier. The product speaks the brain vocabulary
# (search_brain, save_general, ...) — the same names every guide teaches.
printf '%s:%s:customer\n' "$HASH" "$TENANT" > "$KEYFILE"
# 0644 DELIBERATELY, and it is not a loosened secret: this file holds a
# SHA-256 hash and a database name, never the key. The key is 192 bits of
# randomness, so the hash is not attackable the way a password hash is -- and
# the container runs as its own uid, which cannot read a 0600 file owned by
# you under rootless podman. Choosing perms that work on every runtime beats
# making each customer debug a uid mismatch to protect a value that is public
# by construction.
chmod 644 "$KEYFILE"

# THE KEY GOES STRAIGHT INTO THE CLIENT'S CONFIG (2026-10-04): an agent runs
# this install, and a key printed here lands in its chat — so it is written to
# ~/.brethof-brain/config.json (0600, pointed at this memory) and never shown.
# BRAIN_SHOW_KEY=1 shows it as well, for wiring another tool by hand.
PORT=${BRAIN_API_PORT:-8610}
SAVED=""
if [ "${BRAIN_SHOW_KEY:-0}" != "1" ] && command -v python3 >/dev/null 2>&1; then
  SAVED=$(BRAIN_NEW_KEY="$KEY" BRAIN_NEW_ENDPOINT="http://127.0.0.1:$PORT" python3 -c '
import json, os
d = os.environ.get("BRETHOF_BRAIN_HOME") or os.path.join(os.path.expanduser("~"), ".brethof-brain")
os.makedirs(d, exist_ok=True)
p = os.path.join(d, "config.json")
try:
    conf = json.load(open(p, encoding="utf-8"))
except Exception:
    conf = {}
conf["api_key"], conf["endpoint"] = os.environ["BRAIN_NEW_KEY"], os.environ["BRAIN_NEW_ENDPOINT"]
conf.setdefault("default_project", "global")
tmp = p + ".tmp"
fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, "w", encoding="utf-8") as f:
    json.dump(conf, f, indent=2)
os.replace(tmp, p)
os.chmod(p, 0o600)
print(p)
' || true)
fi
if [ -n "$SAVED" ]; then
  cat <<TXT

  Your memory key is saved for your agents: $SAVED
  (readable by you only; it is not shown here). The brethof-brain hooks and
  plugins read it from there.

  Stored on the memory side: $KEYFILE (the hash only)

TXT
else
  cat <<TXT

  Your memory key -- copy it now, it is not shown again:

    $KEY

  Point your agent at this stack with:

    "brain": {
      "type": "http",
      "url": "http://127.0.0.1:${PORT}/v1/mcp",
      "headers": { "Authorization": "Bearer $KEY" }
    }

  Stored: $KEYFILE (the hash only)

TXT
fi
