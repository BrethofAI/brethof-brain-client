"""Test setup: isolate all client state into a throwaway temp dir BEFORE any
brethof_brain_client module is imported (config freezes its paths at import).
conftest.py is imported by pytest first, so setting the env here is reliable."""
import os
import tempfile

os.environ["BRETHOF_BRAIN_HOME"] = tempfile.mkdtemp(prefix="bmtest-")
# Ensure a clean auth state regardless of the host environment.
os.environ.pop("BRETHOF_BRAIN_API_KEY", None)
os.environ.pop("BRETHOF_BRAIN_ENDPOINT", None)
os.environ.pop("BRETHOF_BRAIN_PROJECT", None)
os.environ.pop("BRETHOF_BRAIN_DEFAULT_PROJECT", None)
# The client still honors the pre-rename env names — clear those too.
os.environ.pop("BRETHOF_MIND_HOME", None)
os.environ.pop("BRETHOF_MIND_API_KEY", None)
os.environ.pop("BRETHOF_MIND_ENDPOINT", None)
os.environ.pop("BRETHOF_MIND_PROJECT", None)
os.environ.pop("BRETHOF_MIND_DEFAULT_PROJECT", None)
