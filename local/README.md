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
published sha256, loads them, mints your memory key (shown once), and starts
the stack. Everything it does is printed as it happens; nothing needs sudo
and nothing is written outside this directory.

## Upgrade

```bash
./install.sh
```

The same script: it reads the current published version, downloads only
what changed, and restarts the stack. Your data directory is untouched —
memory survives every upgrade.

## What's what

| File | Role |
|---|---|
| `compose.yml` | the stack — three containers, loopback only |
| `.env` | your passphrase, db password, hub key, dials |
| `keys/v2keys` | sha256 of your memory key (the key itself is never stored) |
| `data/` | your memory — ciphertext only; back this up |
| `model/` | the embedding model (recreatable — the installer re-downloads it) |

Learning (curation of what your agents say) needs `BRAIN_HUB_KEY` from your
account panel in `.env`. Without it, archiving and recall still work fully —
the box never phones home for them.
