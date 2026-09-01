#!/bin/bash
# brethof-brain local install — one script from nothing to a running memory.
#
# What it does, in order, all of it visible:
#   1. checks you have docker (or podman) with compose
#   2. downloads the embedding model from downloads.brethof.ai (2.2 GB,
#      one-time, resumable) and verifies its sha256
#   3. downloads the container images bundle and verifies its sha256
#   4. loads the images and pins the version into .env
#   5. mints your memory key (shown once) if you don't have one
#   6. starts the stack and waits for it to answer
#
# Nothing here needs sudo, phones home, or writes outside this directory.
# Re-running is safe: finished steps are skipped, and running it with a
# newer published version is exactly how you upgrade.
set -euo pipefail
cd "$(dirname "$0")"

DL="${BRAIN_DL_URL:-https://downloads.brethof.ai/brain}"
MODEL_FILE=embeddinggemma-300m-fp32.tar.gz

say()  { printf '\n== %s\n' "$*"; }
fail() { echo "INSTALL FAILED: $*" >&2; exit 1; }

say "runtime check"
if command -v docker >/dev/null && docker compose version >/dev/null 2>&1; then
    ENGINE=docker; COMPOSE="docker compose"
elif command -v podman >/dev/null && command -v podman-compose >/dev/null; then
    ENGINE=podman; COMPOSE="podman-compose"
else
    fail "need docker with the compose plugin, or podman + podman-compose"
fi
echo "using $ENGINE"

say "embedding model (local semantic search — text never leaves this machine)"
if [ -d model/embeddinggemma-300m-onnx ]; then
    echo "already present — skipped"
else
    mkdir -p model
    curl -fL -C - -o "model/$MODEL_FILE" "$DL/models/$MODEL_FILE" \
        || fail "model download"
    curl -fsSL -o "model/$MODEL_FILE.sha256" "$DL/models/$MODEL_FILE.sha256" \
        || fail "model checksum download"
    (cd model && sha256sum -c "$MODEL_FILE.sha256") \
        || fail "model checksum MISMATCH — delete model/ and rerun"
    tar xzf "model/$MODEL_FILE" -C model \
        || fail "model extract"
    rm -f "model/$MODEL_FILE" "model/$MODEL_FILE.sha256"
    echo "model verified and extracted"
fi

say "container images"
VERSION="${BRAIN_VERSION:-$(curl -fsSL "$DL/latest.txt")}"
[ -n "$VERSION" ] || fail "could not resolve the current version"
echo "version: $VERSION"
BUNDLE="brain-images-$VERSION.tar.gz"
if $ENGINE image inspect "downloads.brethof.ai/brain-api:$VERSION" >/dev/null 2>&1; then
    echo "images for $VERSION already loaded — skipped"
else
    curl -fL -C - -o "$BUNDLE" "$DL/images/$BUNDLE" || fail "images download"
    curl -fsSL -o "$BUNDLE.sha256" "$DL/images/$BUNDLE.sha256" \
        || fail "images checksum download"
    sha256sum -c "$BUNDLE.sha256" \
        || fail "images checksum MISMATCH — delete $BUNDLE and rerun"
    $ENGINE load -i "$BUNDLE" || fail "image load"
    rm -f "$BUNDLE" "$BUNDLE.sha256"
    echo "images loaded"
fi

say "your .env"
[ -f .env ] || cp env.example .env
# pin the version this install proved
if grep -q '^BRAIN_VERSION=' .env; then
    sed -i.bak "s/^BRAIN_VERSION=.*/BRAIN_VERSION=$VERSION/" .env && rm -f .env.bak
else
    printf '\nBRAIN_VERSION=%s\n' "$VERSION" >> .env
fi
# a db password is plumbing, not a choice — generate it once
if ! grep -qE '^BRAIN_DB_PASSWORD=.+' .env; then
    PW=$(head -c 16 /dev/urandom | od -An -tx1 | tr -d ' \n')
    sed -i.bak "s/^BRAIN_DB_PASSWORD=.*/BRAIN_DB_PASSWORD=$PW/" .env 2>/dev/null \
        || printf 'BRAIN_DB_PASSWORD=%s\n' "$PW" >> .env
    rm -f .env.bak
    echo "BRAIN_DB_PASSWORD generated"
fi
# the passphrase is YOUR memory's encryption key — never generated silently
if ! grep -qE '^(BRAIN_PASSPHRASE|BRAIN_PASSPHRASE_FILE)=.+' .env; then
    fail "set BRAIN_PASSPHRASE in .env first — it encrypts your memory on
disk and only you hold it. We never see it and cannot recover it.
Then rerun this script."
fi
chmod 600 .env

say "memory key"
if [ -f keys/v2keys ]; then
    echo "key already minted — skipped"
else
    bash mint-key.sh
fi

say "starting the stack"
$COMPOSE up -d || fail "compose up"
for i in $(seq 1 60); do
    curl -sf http://127.0.0.1:8610/v1/health >/dev/null && break
    sleep 5
    [ "$i" = 60 ] && { $ENGINE logs brain-api 2>&1 | tail -20; fail "stack never became healthy"; }
done

say "DONE — your memory answers on http://127.0.0.1:8610/v1/mcp"
echo "   (add BRAIN_HUB_KEY from your account panel to .env to turn on"
echo "    learning — recall and archiving work without it)"
