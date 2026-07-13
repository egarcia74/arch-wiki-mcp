"""
Arch Wiki MCP.

The version lives here, once. It used to be stated three times -- pyproject, the
MCP initialize response, and the HTTP User-Agent -- and the three had already
drifted, the User-Agent still naming a version left behind releases earlier. For
a project whose product is provenance, being unable to say correctly which build
made a request is not cosmetic. It is a claim about identity that nothing backs.
"""

import re
from importlib.metadata import PackageNotFoundError, version as _installed_version
from pathlib import Path

_DISTRIBUTION = "arch-wiki-mcp"

# Read from pyproject only when the package is not installed. tomllib is 3.11+ and
# the floor is 3.10, so this reads the one line it needs rather than taking a tomli
# dependency in a project whose selling point is having none.
_PROJECT_TABLE = re.compile(r"^\[project\]$(.*?)^\[", re.M | re.S)
_VERSION_LINE = re.compile(r'^version\s*=\s*"([^"]+)"', re.M)


_PYPROJECT = Path(__file__).parent.parent.parent / "pyproject.toml"


def _version_from_source_tree() -> str:
    table = _PROJECT_TABLE.search(_PYPROJECT.read_text(encoding="utf-8"))
    if table:
        found = _VERSION_LINE.findall(table.group(1))
        if len(found) == 1:
            return found[0]
    raise RuntimeError(f"cannot determine version: no single [project] version in {_PYPROJECT}")


def _resolve_version() -> str:
    """
    The source tree wins when there is one, because that is the code being run.

    Metadata-first looked tidier and was wrong: with an older wheel installed and a
    bumped clone on sys.path, the process executes the clone's code and reports the
    wheel's version -- the same drift this file exists to end, re-entering through
    the metadata door. A pyproject.toml beside the package describes *this* code.
    Falling back to installed metadata covers the wheel, where there is no
    pyproject and the metadata is the only honest answer.
    """
    if _PYPROJECT.is_file():
        return _version_from_source_tree()

    try:
        return _installed_version(_DISTRIBUTION)
    except PackageNotFoundError as exc:
        raise RuntimeError(
            f"cannot determine version: no {_PYPROJECT} and {_DISTRIBUTION!r} is not installed"
        ) from exc


__version__ = _resolve_version()

REPOSITORY_URL = "https://github.com/egarcia74/arch-wiki-mcp"
