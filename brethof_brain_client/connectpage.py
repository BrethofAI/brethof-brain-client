"""THE CONNECT WINDOW (founder 2026-10-04: "when the installation coming, some
window will pop up and it will put the things in"). The client needs two
things — the API key and, for a hosted memory, its passphrase — and the agent
running the install must never see either, nor can it answer a hidden prompt
(there is no terminal under an agent). So the client serves ONE page on
127.0.0.1, at a random port and a random path, opens it in the person's own
browser, takes what is asked, PROVES it on the memory itself (the unlock door,
then a session-start with the key), and only then hands it back to be saved.
Nothing typed here leaves this machine except to the person's own memory.
"""
from __future__ import annotations

import html
import http.server
import json
import secrets
import socketserver
import threading
import urllib.error
import urllib.parse
import urllib.request

PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>brethof-brain — connect</title>
<style>body{{font:16px/1.5 system-ui,sans-serif;max-width:34rem;margin:3rem auto;padding:0 1rem;color:#222}}
label{{display:block;font-weight:600;margin-top:1rem}}small{{display:block;color:#666;font-weight:400}}
input{{font:inherit;width:100%;padding:.55rem;margin:.3rem 0;box-sizing:border-box}}
button{{font:inherit;padding:.6rem 1.4rem;margin-top:1.2rem}}.err{{color:#b00}}.ok{{color:#070}}
.warn{{color:#b00;font-weight:600;border:2px solid #b00;padding:.6rem .8rem;margin:.6rem 0}}</style></head><body>
<h1>Connect brethof-brain</h1>{body}</body></html>"""


def _is_local(endpoint: str) -> bool:
    host = urllib.parse.urlparse(endpoint).hostname or ""
    return host in ("127.0.0.1", "localhost", "::1")


def _form(fields: dict, err: str = "") -> str:
    ep = html.escape(fields.get("endpoint", ""))
    parts = ['<p>Your agent is installing your memory. What you type here is checked with your memory, '
             'saved on this computer only (<code>~/.brethof-brain/config.json</code>, readable by you alone) '
             'and never shown to the agent.</p>']
    if err:
        parts.append(f'<p class="err">{html.escape(err)}</p>')
    parts.append('<form method="post">')
    if "endpoint" in fields:
        parts.append('<label>Where your memory is<small>A memory on this computer is found by itself; '
                     'a hosted one shows its address in your panel at brethof.ai/account.</small></label>'
                     f'<input name="endpoint" value="{ep}" required>')
    if "key" in fields:
        parts.append('<label>API key<small>Starts with bmv2_. A memory on this computer printed it once at '
                     'install; a hosted one makes keys in your panel.</small></label>'
                     '<input type="password" name="key" autocomplete="off" required autofocus>')
    if "passphrase" in fields:
        parts.append('<label>Passphrase<small>Hosted memories only — it unlocks your memory when it has '
                     'been idle. Leave empty for a memory on this computer.</small></label>'
                     '<p class="warn">If you forget your passphrase, your memory can never be opened again — '
                     'by you or by us. There is no way to recover it. Keep it somewhere safe.</p>'
                     '<input type="password" name="passphrase" autocomplete="current-password">'
                     '<label>Passphrase again<small>Type it once more, to be sure it is right.</small></label>'
                     '<input type="password" name="passphrase2" autocomplete="off">')
    parts.append('<button type="submit">Connect</button></form>')
    return "".join(parts)


def _post(url: str, body: dict, user_agent: str, key: str = "") -> int:
    h = {"Content-Type": "application/json", "User-Agent": user_agent}
    if key:
        h["Authorization"] = "Bearer " + key
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=h)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except (urllib.error.URLError, OSError):
        return 0


def check(endpoint: str, key: str, passphrase: str, user_agent: str) -> str:
    """'' when the memory takes these values; otherwise what to tell the person."""
    endpoint = endpoint.rstrip("/")
    if not endpoint.startswith(("https://", "http://127.0.0.1", "http://localhost")):
        return "The address must start with https:// (or be this computer)."
    if passphrase:
        st = _post(endpoint + "/unlock", {"passphrase": passphrase}, user_agent)
        if st in (401, 403):
            return "That passphrase did not open your memory."
        if st not in (200, 204):
            return f"Your memory did not answer the unlock ({st or 'unreachable'}) — check the address."
    if key:
        st = _post(endpoint + "/v1/hooks/session-start", {"project": "global", "session_id": "connect"},
                   user_agent, key)
        if st == 423:
            return "Your memory is locked — type its passphrase too."
        if st in (401, 403):
            return "Your memory did not accept that key."
        if st != 200:
            return f"Your memory answered {st or 'nothing'} — check the address."
    return ""


class _LocalServer(http.server.HTTPServer):
    """HTTPServer without its reverse-DNS lookup. HTTPServer.server_bind asks
    socket.getfqdn() for the bound address's name; on macOS that lookup can
    hang for many seconds, so the window opened late or not at all — the CI
    macOS jobs failed on it from 1.2.12 to 1.2.15 (2026-10-04). We only ever
    serve 127.0.0.1 and never use the name."""

    def server_bind(self):
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = "127.0.0.1", self.server_address[1]


def serve(fields: dict, user_agent: str, open_url, endpoint: str = "", timeout_s: float = 900.0) -> dict:
    """Serve the one-shot page with `fields` (endpoint/key/passphrase, each
    with its starting value), open it, wait for values the memory accepts;
    answer them ({} when nobody came before the time ran out)."""
    path = "/" + secrets.token_urlsafe(16)
    got: dict = {}
    done = threading.Event()

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):              # nothing on the agent's screen
            pass

        def _send(self, body: str, code: int = 200):
            data = PAGE.format(body=body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path != path or done.is_set():
                return self._send("<p>Nothing here.</p>", 404)
            self._send(_form(fields))

        def do_POST(self):
            if self.path != path or done.is_set():
                return self._send("<p>Nothing here.</p>", 404)
            n = min(int(self.headers.get("Content-Length") or 0), 8192)
            q = urllib.parse.parse_qs(self.rfile.read(n).decode("utf-8", "replace"))
            v = {k: (q.get(k, [""])[0]).strip() for k in ("endpoint", "key", "passphrase", "passphrase2")}
            ep = v["endpoint"] or fields.get("endpoint", "") or endpoint
            key = v["key"] if "key" in fields else ""
            pp = v["passphrase"] if "passphrase" in fields else ""
            if "passphrase" in fields and "key" not in fields and not pp:
                return self._send(_form(fields, "Type the passphrase first."))
            if pp != (v["passphrase2"] if "passphrase" in fields else ""):
                kept = {**fields, "endpoint": ep} if "endpoint" in fields else fields
                return self._send(_form(kept, "The two passphrases are not the same — type them again."))
            why = check(ep, key, pp, user_agent)
            if why:
                kept = {**fields, "endpoint": ep} if "endpoint" in fields else fields
                return self._send(_form(kept, why))
            got.update({"endpoint": ep.rstrip("/"), "key": key, "passphrase": pp})
            self._send('<p class="ok">Connected. Your agent can carry on — you can close this tab.</p>')
            done.set()

    srv = _LocalServer(("127.0.0.1", 0), H)
    url = f"http://127.0.0.1:{srv.server_address[1]}{path}"
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        opened = open_url(url)
        print(("A window opened on your screen — fill it in there; nothing is shown here." if opened else
               "Open this page on this computer to connect your memory:") + f"\n  {url}", flush=True)
        done.wait(timeout_s)
    finally:
        srv.shutdown()
        srv.server_close()
    return got
