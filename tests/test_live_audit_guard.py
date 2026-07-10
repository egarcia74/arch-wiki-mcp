"""
The audit must not be able to pass without auditing.

extractor._fetch() honours ARCHWIKI_OFFLINE. A shell that still has it exported --
after a pytest run, or `make test` in the same session -- routes every fetch to
tests/fixtures. The audit then re-renders the same seven pinned pages it exists to
look past, prints "No invariant violations", and exits 0.

A green check that checked nothing is this repo's own failure mode, aimed at itself.
"""

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import live_audit


def test_the_guard_rejects_offline_mode():
    with pytest.raises(live_audit.OfflineModeError, match="ARCHWIKI_OFFLINE"):
        live_audit.require_live_mode({"ARCHWIKI_OFFLINE": "1"})


def test_the_guard_allows_a_live_environment():
    live_audit.require_live_mode({})  # must not raise


def test_the_audit_exits_nonzero_under_offline_mode_without_touching_the_network():
    """End to end: the script itself must refuse, not just the helper."""
    result = subprocess.run(
        [sys.executable, "scripts/live_audit.py", "GRUB"],
        cwd=REPO_ROOT,
        env={"PATH": "/usr/bin:/bin", "ARCHWIKI_OFFLINE": "1",
             "ARCHWIKI_FIXTURES": "tests/fixtures"},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 2, result.stdout
    assert "ARCHWIKI_OFFLINE is set" in result.stderr
    assert "No invariant violations" not in result.stdout
