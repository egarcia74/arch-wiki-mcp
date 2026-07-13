"""
Offline test harness.

The extractor reads fixtures instead of the network when ARCHWIKI_OFFLINE is
set. Nothing set it before, so the suite silently hit the live wiki and the
recorded fixtures were never exercised. Setting it here makes tests/fixtures/
the authoritative source for the whole suite.

ARCHWIKI_FIXTURES must be absolute: extractor._fetch_offline defaults to the
relative "tests/fixtures", which only resolves when pytest runs from the repo
root.
"""

import json
import os
import re
import socket
from functools import lru_cache
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


from arch_wiki_mcp.extractor import fixture_filename

# Offline mode must be active before any test imports trigger a fetch.
os.environ["ARCHWIKI_OFFLINE"] = "1"
os.environ["ARCHWIKI_FIXTURES"] = str(FIXTURES_DIR)


@pytest.fixture(scope="session", autouse=True)
def block_network():
    """
    Make "the suite performs no network I/O" a property, not a promise.

    ARCHWIKI_OFFLINE routes fetches to fixtures, but nothing stopped a new code
    path from reaching wiki.archlinux.org and quietly making the suite depend on
    the live wiki again -- which is how the previous suite decayed.
    """
    if os.environ.get("ARCHWIKI_ALLOW_NETWORK"):
        yield
        return

    def deny(*_args, **_kwargs):
        raise RuntimeError(
            "Network access during tests. Record a fixture instead: "
            "python tests/record_fixtures.py <page>"
        )

    # socket.create_connection and urlopen both route through socket.connect,
    # so this one patch covers every path out.
    original_connect = socket.socket.connect
    socket.socket.connect = deny
    try:
        yield
    finally:
        socket.socket.connect = original_connect


@lru_cache(maxsize=None)
def load_parse(page: str) -> dict:
    """Load a recorded action=parse response by page title."""
    with open(FIXTURES_DIR / fixture_filename("parse", page)) as handle:
        return json.load(handle)["parse"]


def load_wikitext(page: str) -> str:
    return load_parse(page)["wikitext"]["*"]


# Pinned from the committed fixture rather than transcribed by hand, so
# re-recording GRUB moves this in one place.
GRUB_REVID = load_parse("GRUB")["revid"]

# Fixture keys, so a re-record moves one line rather than several. Spelled in
# two test modules apiece, they could drift and quietly leave a test exercising
# a fixture it no longer names.
MISSING_PAGE = "Nonexistent page xyz"
TRANSCLUDED_PAGE = "Transcluded example"


# Read here, independently of arch_wiki_mcp.__version__, on purpose. A test that asked the
# code under test what version it thinks it is would agree with any bug in the
# resolver. pyproject is the authority; this reads the authority.
#
# tomllib is 3.11+ and the floor is 3.10, so this reads the one line it needs
# rather than taking a tomli dependency in a project whose selling point is none.
_PROJECT_TABLE = re.compile(r"^\[project\]$(.*?)^\[", re.M | re.S)
_VERSION_LINE = re.compile(r'^version\s*=\s*"([^"]+)"', re.M)


REPO = Path(__file__).parent.parent


def declared_version() -> str:
    """The version in pyproject.toml, which every other statement of it derives from."""
    table = _PROJECT_TABLE.search((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    assert table, "no [project] table in pyproject.toml"
    versions = _VERSION_LINE.findall(table.group(1))
    assert len(versions) == 1, f"expected one version in [project], found {versions}"
    return versions[0]


# Same reasoning, same authority: the scripts pip will actually create.
_SCRIPTS_TABLE = re.compile(r"^\[project\.scripts\]$(.*?)(?:^\[|\Z)", re.M | re.S)
_SCRIPT_LINE = re.compile(r"^([\w.-]+)\s*=", re.M)


def declared_scripts() -> set:
    """The console scripts pyproject declares -- the only commands an install provides."""
    table = _SCRIPTS_TABLE.search((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    return set(_SCRIPT_LINE.findall(table.group(1))) if table else set()
