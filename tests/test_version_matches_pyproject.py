"""__version__ must equal the packaged version — it is not cosmetic.

It rides on every request as the User-Agent and the X-BM-Client header, so a
stale literal makes server-side telemetry and any version gating read the
wrong client. Found drifted 1.0.1 vs 1.1.0 on 2026-08-14.
"""
import pathlib
import re

from brethof_brain_client import __version__

PYPROJECT = pathlib.Path(__file__).resolve().parent.parent / "pyproject.toml"


def test_version_matches_pyproject():
    text = PYPROJECT.read_text(encoding="utf-8")
    declared = re.search(r'^version\s*=\s*"([^"]+)"', text, re.M)
    assert declared, "no version in pyproject.toml"
    assert __version__ == declared.group(1), (
        f"__init__.py says {__version__}, pyproject.toml says {declared.group(1)} — "
        "bump both or the server sees the wrong client version")
