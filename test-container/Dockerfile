# OpenClaw-style test container for brethof-brain cloud.
# Build from the REPO ROOT so it can install the client package:
#   docker build -f test-container/Dockerfile -t brethof-brain-smoke .
FROM python:3.12-slim

WORKDIR /app

# Install the client (stdlib-only, so this is fast and dependency-free).
COPY pyproject.toml README.md LICENSE ./
COPY brethof_brain_client ./brethof_brain_client
RUN pip install --no-cache-dir .

COPY test-container/smoke_test.py ./smoke_test.py
COPY adapters/openclaw/openclaw_hooks.py ./openclaw_hooks.py

# Credentials are injected at run time via env (never baked into the image).
#   docker run --rm -e BRETHOF_BRAIN_API_KEY=bm_... brethof-brain-smoke
ENTRYPOINT ["python", "smoke_test.py"]
