"""
The server must tell the truth about who it is.

Three copies of one fact drifted apart: pyproject said 1.7.0, the MCP initialize
response hardcoded 1.7.0 beside it, and the User-Agent -- the only thing the Arch
Wiki's operators ever see of us -- still said ArchWikiMCP/1.0 and pointed at
https://github.com/user/arch-wiki-mcp, a repository that does not exist.

For a project whose entire product is provenance, being unable to say correctly
which version of itself made a request is not a cosmetic fault. It is the same
class of error as an unpinned citation: a claim about identity that nothing backs.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import declared_version

import src
from src import extractor

def test_the_package_version_is_the_declared_one():
    assert src.__version__ == declared_version()


def test_the_user_agent_names_the_version_we_are_actually_running():
    """
    The User-Agent said 1.0 while the package said 1.7.0. If the wiki's operators
    ever need to identify the client behind a pattern of requests, we were telling
    them the wrong thing -- and we could not have told them the right thing,
    because nothing connected the two.
    """
    assert f"ArchWikiMCP/{src.__version__}" in extractor.USER_AGENT


def test_the_user_agent_points_at_a_repository_that_exists():
    """https://github.com/user/arch-wiki-mcp is not this project, or any project."""
    assert "github.com/egarcia74/arch-wiki-mcp" in extractor.USER_AGENT
    assert "github.com/user/" not in extractor.USER_AGENT


@pytest.mark.parametrize("script", ["src/mcp_server.py", "src/extractor.py"])
def test_a_module_still_runs_as_a_script(script):
    """
    Both files have a __main__ block, and nothing ever ran them as scripts -- so
    when the version import broke `python3 src/extractor.py` outright, the whole
    suite stayed green over a dead entry point. An entry point nothing exercises is
    an entry point nobody knows is broken.
    """
    repo = Path(__file__).parent.parent
    result = subprocess.run(
        [sys.executable, script],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, "ARCHWIKI_OFFLINE": "1"},
    )

    assert "ModuleNotFoundError" not in result.stderr, result.stderr
    assert "Traceback" not in result.stderr, result.stderr


SOURCES = [
    Path(__file__).parent.parent / "src" / "__init__.py",
    Path(__file__).parent.parent / "src" / "extractor.py",
    Path(__file__).parent.parent / "src" / "mcp_server.py",
]


@pytest.mark.parametrize("source", SOURCES, ids=lambda p: p.name)
def test_the_version_is_stated_once(source):
    """
    A tripwire against the drift returning. The literal belongs in pyproject and
    nowhere else -- in code or in prose. Every other statement of it is derived, and
    a version quoted in a comment goes stale exactly as silently as one in code.
    """
    version = declared_version()

    assert version not in source.read_text(), (
        f"{source.name} spells out the version {version!r}; derive it from "
        f"src.__version__, or it will silently lag the next release"
    )
