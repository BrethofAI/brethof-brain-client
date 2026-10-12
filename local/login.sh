#!/bin/bash
# Connect this memory to your brethof.ai account, so it learns: the hub key.
#
#   ./login.sh
#
# It prints a link and a short code. Open the link while signed in to
# brethof.ai, check the code is the one shown here, and press Approve. The
# hub key then comes straight back to this script and is written into .env —
# it is never printed, so an agent running the install never sees it.
#
# One hub key per memory: a new one replaces the old. Running this again is
# how the hub key is rotated, and a second machine still holding the old key
# stops learning until it is connected again (recall and the archive keep
# working there — they never need the hub).
#
# Needs python3 (it does the polling and writes .env itself, so the key is
# never put on a command line). Without python3: paste the hub key from your
# account panel into .env as BRAIN_HUB_KEY= by hand.
set -euo pipefail
cd "$(dirname "$0")"

command -v python3 >/dev/null 2>&1 || {
    echo "login.sh needs python3. Without it, copy the hub key from your account panel" >&2
    echo "into .env as BRAIN_HUB_KEY=..., then run: docker compose up -d" >&2
    exit 1
}
[ -f .env ] || cp env.example .env

BRAIN_CONTROL_URL="${BRETHOF_BRAIN_CONTROL_URL:-https://api.brethof.ai}" \
BRAIN_CLIENT_NAME="brethof-brain local install on $(hostname 2>/dev/null || echo this machine)" \
python3 - <<'PY'
import json, os, subprocess, sys, time, urllib.error, urllib.request

control = os.environ["BRAIN_CONTROL_URL"].rstrip("/")


def post(path, body):
    req = urllib.request.Request(control + path, json.dumps(body).encode(),
                                 {"Content-Type": "application/json",
                                  "User-Agent": "brethof-brain-local-kit"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:      # the RFC 8628 answers come as 4xx
        try:
            return e.code, json.load(e)
        except Exception:
            return e.code, {}
    except Exception as e:                    # no network, DNS, TLS
        return 0, {"error_description": str(e)}


st, code = post("/v1/device/code", {"product": "brain-local",
                                     "client_name": os.environ["BRAIN_CLIENT_NAME"][:80]})
if st != 200 or not code.get("device_code"):
    sys.exit(f"login failed: could not start the sign-in ({st}: "
             f"{code.get('error_description') or code.get('error') or 'no answer'})")
link = code.get("verification_uri_complete") or code.get("verification_uri")
print("To connect this memory to your brethof.ai account, open this page while signed in:")
print(f"  {link}")
print(f"check that it shows the code  {code.get('user_code')}  and press Approve.", flush=True)
# a browser only where a desktop session exists — never a text browser in an
# agent's terminal
if os.environ.get("BRAIN_NO_BROWSER") != "1":
    opener = ["open"] if sys.platform == "darwin" else (
        ["xdg-open"] if os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY") else None)
    if opener:
        try:
            subprocess.Popen(opener + [link], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            pass

interval = max(1, int(code.get("interval") or 5))
deadline = time.time() + int(code.get("expires_in") or 600)
while True:
    if time.time() > deadline:
        sys.exit("login failed: the code expired before it was approved — run ./login.sh again")
    time.sleep(interval)
    st, tok = post("/v1/device/token", {"device_code": code["device_code"]})
    if st == 200 and tok.get("hub_key"):
        break
    err = tok.get("error", "")
    if err == "authorization_pending":
        continue
    if err == "slow_down":
        interval += 5
        continue
    sys.exit(f"login failed: {tok.get('error_description') or err or f'HTTP {st}'}")

# write .env: replace or add the one line, 0600, atomically; the key never
# leaves this process except into the file
lines, done = [], False
with open(".env", encoding="utf-8") as f:
    for ln in f.read().splitlines():
        if ln.startswith("BRAIN_HUB_KEY="):
            if not done:
                lines.append("BRAIN_HUB_KEY=" + tok["hub_key"])
                done = True
            continue
        lines.append(ln)
if not done:
    lines.append("BRAIN_HUB_KEY=" + tok["hub_key"])
fd = os.open(".env.tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, "w", encoding="utf-8") as f:
    f.write("\n".join(lines) + "\n")
os.replace(".env.tmp", ".env")
os.chmod(".env", 0o600)
print("connected: the hub key is in .env (not shown here)"
      + (" — it replaces the previous one; another machine still using the old key"
         " learns again once it is connected" if tok.get("replaced") else ""))
PY

# a running memory reads .env only when its container is created — recreate
# THIS install's api container if it is up (asked through this folder's
# compose project, never by a container name another stack could share).
# The key is already saved, so a failure here is a note, not a failed login.
if [ -f compose.yml ]; then
    if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
        COMPOSE="docker compose"
    elif command -v podman-compose >/dev/null 2>&1; then
        COMPOSE="podman-compose"
    else
        COMPOSE=""
    fi
    if [ -n "$COMPOSE" ] && [ -n "$($COMPOSE ps -q brain-api 2>/dev/null)" ]; then
        $COMPOSE up -d brain-api >/dev/null 2>&1 \
            && echo "your running memory now uses it" \
            || echo "restart your memory so it uses the new key: $COMPOSE up -d" >&2
    fi
fi
exit 0
