"""Test helpers: make src/ importable and give every test run a private, empty $HOME / XDG tree."""

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "tests"
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(TESTS))


def sandbox_env(home: Path) -> dict:
    """Environment for subprocesses that must never touch the real user's files."""
    env = dict(os.environ)
    env.update({
        "HOME": str(home), "XDG_CONFIG_HOME": str(home / ".config"), "XDG_DATA_HOME": str(home / ".local/share"),
        "XDG_STATE_HOME": str(home / ".local/state"), "XDG_CACHE_HOME": str(home / ".cache"),
        "XDG_RUNTIME_DIR": str(home / "run"), "PYTHONPATH": str(ROOT / "src"),
    })
    (home / "run").mkdir(parents=True, exist_ok=True, mode=0o700)
    return env


def new_home() -> tempfile.TemporaryDirectory:
    return tempfile.TemporaryDirectory(prefix="void-test-home-")
