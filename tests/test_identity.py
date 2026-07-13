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

import importlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import declared_version

import arch_wiki_mcp
from arch_wiki_mcp import extractor

def test_the_package_version_is_the_declared_one():
    assert arch_wiki_mcp.__version__ == declared_version()


def test_the_user_agent_names_the_version_we_are_actually_running():
    """
    The User-Agent said 1.0 while the package said 1.7.0. If the wiki's operators
    ever need to identify the client behind a pattern of requests, we were telling
    them the wrong thing -- and we could not have told them the right thing,
    because nothing connected the two.
    """
    assert f"ArchWikiMCP/{arch_wiki_mcp.__version__}" in extractor.USER_AGENT


def test_the_user_agent_points_at_a_repository_that_exists():
    """https://github.com/user/arch-wiki-mcp is not this project, or any project."""
    assert "github.com/egarcia74/arch-wiki-mcp" in extractor.USER_AGENT
    assert "github.com/user/" not in extractor.USER_AGENT


@pytest.mark.parametrize("module", ["arch_wiki_mcp.server", "arch_wiki_mcp.extractor"])
def test_a_module_still_runs_as_a_script(module):
    """
    Both files have a __main__ block, and nothing ever ran them as scripts -- so
    when the version import broke the extractor entry point outright, the whole
    suite stayed green over a dead entry point. An entry point nothing exercises is
    an entry point nobody knows is broken.
    """
    repo = Path(__file__).parent.parent
    result = subprocess.run(
        [sys.executable, "-m", module],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, "ARCHWIKI_OFFLINE": "1", "PYTHONPATH": "src"},
    )

    assert "ModuleNotFoundError" not in result.stderr, result.stderr
    assert "Traceback" not in result.stderr, result.stderr


PACKAGE = Path(__file__).parent.parent / "src" / "arch_wiki_mcp"
SOURCES = sorted(PACKAGE.glob("*.py"))


REPO = Path(__file__).parent.parent

# Everything outside the package that reaches the live wiki in earnest. Not every
# file that mentions urlopen: test_failures.py opens a socket precisely to prove the
# suite cannot reach the wiki, and this module has to spell the User-Agent out in
# order to assert its shape. Those talk *about* the wiki; these talk *to* it.
LIVE_CALLERS = sorted(
    [*REPO.glob("scripts/*.py"), REPO / "tests" / "record_fixtures.py"]
)


@pytest.mark.parametrize("source", LIVE_CALLERS, ids=lambda p: p.name)
def test_nothing_that_talks_to_the_wiki_invents_its_own_identity(source):
    """
    The #19 tripwire scanned src/*.py only, so it never looked at the two scripts
    that also call the wiki -- and the fixture recorder went on introducing itself
    as ArchWikiMCP/1.0 (a version abandoned releases ago) with its own copy of the
    API endpoint. The drift this fix exists to end, alive in the one place the guard
    was not pointed at.

    Identity is a property of the project, not of the file that happens to make the
    request. Anything that reaches the wiki derives it.
    """
    text = source.read_text(encoding="utf-8")

    assert "ArchWikiMCP/" not in text, (
        f"{source.name} spells out a User-Agent; import extractor.USER_AGENT"
    )
    assert "wiki.archlinux.org/api.php" not in text, (
        f"{source.name} spells out the API endpoint; import extractor.API_ENDPOINT"
    )


def test_no_module_sits_beside_the_package():
    """
    A stray *module* beside the package is a second import identity waiting to
    happen -- the hazard the old layout carried, where `src` was both the layout
    directory and the importable package, so two sys.path entries could load the
    same file twice under different names.

    Modules, not entries: this first asserted that src/ held nothing but the
    package, and then `pip install -e .` -- which MCP_SETUP.md now tells every
    contributor to run -- wrote src/arch_wiki_mcp.egg-info beside it and failed
    the suite. An egg-info is not importable and was never the hazard; the test
    was arguing about one thing and checking another.
    """
    strays = sorted(p.name for p in PACKAGE.parent.glob("*.py"))

    assert not strays, f"a module beside the package can load twice: {strays}"


def test_the_legacy_namespace_is_gone():
    """`src` was the import package. It must not still resolve, or both can load."""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("src.extractor")


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
        f"arch_wiki_mcp.__version__, or it will silently lag the next release"
    )
