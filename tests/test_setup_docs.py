"""
A setup document must not tell a reader to run something that does not exist.

The rename in #22 moved src/mcp_server.py to src/arch_wiki_mcp/server.py and left
its callers behind. CI invoked the dead path; so did the maintainer's own
registered MCP server, which had been working for months and simply stopped. The
suite stayed green through all of it -- 435 tests, not one of which ever read a
setup document or ran an entry point. The client reported "Failed to connect",
which names the symptom and nothing whatever about the cause.

The registration is the last entry point, and the only one that lives outside the
repository: a path in a config file on a user's machine, written once and never
revisited. Nothing here can reach in and fix a stale one. What it can do is stop
handing out paths that rot -- so `--check` resolves the command from the running
interpreter, and the docs point at `--check` rather than spelling a path out.

So: a path a document names must exist, a command a document tells you to run must
be one this package installs, and the preflight that prints a registration must
print one that actually starts a server.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import REPO, declared_scripts

def _tracked_documents() -> list:
    """
    Every document git knows about -- asked of git, not listed by hand.

    This began as four filenames I remembered, and test_identity.py one file over is
    the post-mortem of precisely that mistake: the #19 tripwire scanned src/*.py, so
    it never looked at the two scripts that also talked to the wiki, and they drifted
    for releases. A guard certifies whatever it was not pointed at. My list had
    already missed MCP_PROTOCOL.md and ARCH_WIKI_MCP_CONSTITUTION.md, both of which
    name repo paths.

    Globbing chosen directories only moves the omission down a level -- a docs/, a
    CONTRIBUTING.md, a workflow saved as .yaml. git is the authority on what is in
    the repository, the same way pyproject is the authority on the version, and it
    excludes .venv and caches by construction.
    """
    # A source tarball -- the GitHub /archive/ zip an AUR PKGBUILD builds from --
    # ships tests/ and no .git. Asked there, git exits 128, and at collection time
    # that is not a failed test but an aborted suite, all of it, behind an exit code
    # that explains nothing.
    #
    # Returning nothing skips *only* the two tests parametrized over documents. It
    # must not skip the module: the preflight tests below need no git at all, and a
    # packaging build is the place where "does the installed entry point actually
    # start a server" most wants asking. A guard that opts out of more than it has
    # to is the same error as one scoped to less than it should be.
    if not (REPO / ".git").exists():
        return []

    tracked = subprocess.run(
        ["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout.split()

    return sorted(
        REPO / name
        for name in tracked
        if name.endswith((".md", ".yml", ".yaml")) or Path(name).name == "Makefile"
    )


INSTRUCTIONS = _tracked_documents()

# A repo-relative path as it appears in a command or a config. `*` is admitted so a
# glob is captured whole and resolved as one, rather than truncated to a prefix that
# exists nowhere. The trailing class excludes punctuation, so a path at the end of a
# sentence is not captured with its full stop attached.
PATH_LIKE = re.compile(r"(?<![\w./*-])((?:src|tests|scripts|\.github)/[\w./*-]*[\w/*-])")

# The leading token of a shell line: what a reader actually copies out of a fence.
BASH_FENCE = re.compile(r"```(?:bash|sh|console)\n(.*?)```", re.S)
COMMAND_LINE = re.compile(r"^\s*([\w-]+)", re.M)

# Commands belonging to this project, as opposed to git, pip, make and python.
OURS = re.compile(r"arch[-_]wiki")


@pytest.mark.parametrize("document", INSTRUCTIONS, ids=lambda p: p.name)
def test_no_document_names_a_path_that_does_not_exist(document):
    """
    The tripwire for the whole class. `python3 src/mcp_server.py --stdio` sat in
    MCP_SETUP.md and in tests.yml after the file it names was deleted, and nothing
    in the suite was capable of noticing -- a document is not imported, so it never
    raises ModuleNotFoundError. It just goes on being wrong, quietly, to everyone
    who follows it.
    """
    missing = sorted(
        path
        for path in PATH_LIKE.findall(document.read_text(encoding="utf-8"))
        # A glob is satisfied by anything it matches; a plain path by itself.
        if not (list(REPO.glob(path)) if "*" in path else (REPO / path).exists())
    )

    assert not missing, f"{document.name} names paths that do not exist: {missing}"


@pytest.mark.parametrize("document", INSTRUCTIONS, ids=lambda p: p.name)
def test_a_documented_command_is_one_this_package_installs(document):
    """
    A doc may tell a reader to run `arch-wiki-mcp` only because `pip install -e .`
    creates it. Anything else in that namespace is a command they cannot have.

    This first read only JSON `"command":` keys -- and the doc rewrite in this same
    change moved every runnable instruction into bash fences, so the check was left
    asserting over an empty set. It could not have failed. A guard aimed at the
    notation a fix removed is not a guard.
    """
    text = document.read_text(encoding="utf-8")
    declared = declared_scripts()

    invoked = {
        command
        for fence in BASH_FENCE.findall(text)
        for command in COMMAND_LINE.findall(fence)
        if OURS.match(command)
    }
    invoked |= {
        command
        for command in re.findall(r'"command":\s*"([^"]+)"', text)
        if OURS.match(command)
    }

    invented = invoked - declared
    assert not invented, (
        f"{document.name} tells a reader to run commands nothing installs: "
        f"{sorted(invented)}; pyproject declares {sorted(declared)}"
    )


@pytest.fixture(scope="module")
def preflight():
    """One spawn: --check takes no input and its answer does not vary."""
    return subprocess.run(
        [sys.executable, "-m", "arch_wiki_mcp.server", "--check"],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_the_preflight_reports_a_healthy_install(preflight):
    assert preflight.returncode == 0, preflight.stderr


def test_the_preflight_prints_a_registration_a_client_can_paste(preflight):
    """stdout is the config and nothing but the config, so it can be redirected."""
    server = json.loads(preflight.stdout)["mcpServers"]["arch-wiki"]

    assert Path(server["command"]).is_absolute(), (
        "a relative command resolves only against a PATH the client may not have"
    )
    assert Path(server["command"]).exists(), "the preflight printed a command that is not there"
    assert "--stdio" in server["args"]


def test_the_registration_the_preflight_prints_actually_starts_a_server(preflight):
    """
    The one assertion that would have caught this outright: run what we hand the
    user, and require an MCP handshake back. A registration nobody executes is a
    registration nobody knows is dead -- which is the whole story of this fix.
    """
    server = json.loads(preflight.stdout)["mcpServers"]["arch-wiki"]

    # Without PYTHONPATH, as a client would spawn it: the registration must stand on
    # the install, not on an environment this suite happens to be running under.
    environment = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}

    result = subprocess.run(
        [server["command"], *server["args"]],
        input='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}\n',
        capture_output=True,
        text=True,
        timeout=60,
        env=environment,
    )

    response = json.loads(result.stdout.splitlines()[0])
    assert response["result"]["serverInfo"]["name"] == "arch-wiki-mcp", result.stderr


def test_an_uninstalled_package_is_named_as_the_problem(monkeypatch):
    """
    "Failed to connect" is what the client says for a dead path, a missing package,
    a syntax error and a firewall alike. The preflight exists to say which.
    """
    from arch_wiki_mcp import server

    def _not_installed(_name):
        raise server.metadata.PackageNotFoundError(_name)

    monkeypatch.setattr(server.metadata, "version", _not_installed)

    with pytest.raises(SystemExit) as exit_code:
        server.run_preflight()

    assert exit_code.value.code != 0, "an uninstalled package reported as healthy"


def test_a_mode_flag_with_arguments_is_not_reported_as_an_unknown_tool(monkeypatch, capsys):
    """
    `--check bogus` fell through the argv ladder to `tool = "--check"` and answered
    "Unknown tool: --check". The flag exists; the arity is wrong. Telling a reader
    their flag does not exist sends them looking for one that does.
    """
    from arch_wiki_mcp import server

    monkeypatch.setattr(sys, "argv", ["arch-wiki-mcp", "--check", "bogus"])

    with pytest.raises(SystemExit) as exit_code:
        server.main()

    assert exit_code.value.code != 0
    assert "Unknown tool" not in capsys.readouterr().err


def test_the_setup_guide_points_at_the_preflight():
    """
    A path a human copies is a path that rots. The guide must send them to the
    command that resolves one, or we are back where we started.
    """
    guide = (REPO / "MCP_SETUP.md").read_text(encoding="utf-8")

    assert "--check" in guide, "the setup guide never mentions the preflight"
