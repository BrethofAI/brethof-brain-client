# OpenClaw-style test container for brethof-mind cloud.
# Build from the REPO ROOT so it can install the client package:
#   docker build -f test-container/Dockerfile -t brethof-mind-smoke .
FROM python:3.12-slim

WORKDIR /app

# Install the client (stdlib-only, so this is fast and dependency-free).
COPY pyproject.toml README.md LICENSE ./
COPY brethof_mind_client ./brethof_mind_client
RUN pip install --no-cache-dir .

COPY test-container/smoke_test.py ./smoke_test.py

# Credentials are injected at run time via env (never baked into the image).
#   docker run --rm -e BRETHOF_MIND_API_KEY=bm_... brethof-mind-smoke
ENTRYPOINT ["python", "smoke_test.py"]
