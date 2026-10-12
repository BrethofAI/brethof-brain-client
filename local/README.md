# brethof-brain — local install

Your memory runs on your machine: an encrypted Postgres, a local embedding
model (text never leaves the box to be searched), and the same API container
we run in the cloud, listening on loopback only. The curation intelligence
is not in these images — it runs on our hub against your licence key.

## Install

```bash
git clone https://github.com/BrethofAI/brethof-brain-client
cd brethof-brain-client/local
cp env.example .env       # set BRAIN_PASSPHRASE — it encrypts your memory,
                          # only you hold it, we cannot recover it
./install.sh
```

Windows (Docker Desktop): same steps, then `powershell -ExecutionPolicy
Bypass -File install.ps1`.

The script downloads the embedding model (2.2 GB, one-time) and the current
container images from `downloads.brethof.ai`, verifies both against their
published sha256, loads them, mints your memory key, connects the memory to
your brethof.ai account, and starts the stack. Everything it does is printed
as it happens; nothing needs sudo and nothing is written outside this
directory and your agents' config (`~/.brethof-brain/config.json`).

No key is ever shown, so an agent can run the whole install for you:

- **your memory key** (what your agents use) goes straight into your agents'
  config;
- **your hub key** (what makes the memory learn): the installer prints a
  link and a short code — open the link while signed in to brethof.ai,
  check the code, press Approve, and the key comes back into `.env` by
  itself. Skipped or timed out? Run `./login.sh` any time.

## Upgrade

```bash
./install.sh
```

The same script: it reads the current published version, downloads only
what changed, and restarts the stack. Your data directory is untouched —
memory survives every upgrade.

## Replacing a key

```bash
./rotate-key.sh     # a new memory key; the old one stops working at once
./login.sh          # a new hub key, approved on brethof.ai like the first
```

Nothing restarts and nothing is printed: the running memory reads its key
file again when it changes, and your agents read their config on every call.
A tool you wired by hand needs the new memory key — `BRAIN_SHOW_KEY=1
./rotate-key.sh` shows it. A memory has one hub key: a second machine still
holding the old one stops learning until you run `./login.sh` there
(recording and search keep working).

Windows: `rotate-key.ps1` and `login.ps1`, run with
`powershell -ExecutionPolicy Bypass -File …`.

## What's what

| File | Role |
|---|---|
| `compose.yml` | the stack — three containers, loopback only |
| `.env` | your passphrase, db password, hub key, dials |
| `keys/v2keys` | sha256 of your memory key (the key itself is never stored) |
| `rotate-key.sh` / `login.sh` | replace the memory key / the hub key |
| `data/` | your memory — ciphertext only; back this up |
| `model/` | the embedding model (recreatable — the installer re-downloads it) |

Learning (curation of what your agents say) needs the hub key in `.env`
(`./login.sh` puts it there). Without it, archiving and recall still work
fully — the box never phones home for them.
