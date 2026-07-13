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
    # A skip marker, not an empty list. Skipping *only* the two document tests is the
    # point -- the preflight tests below need no git, and a packaging build is exactly
    # where "does the installed entry point actually start a server" most wants asking.
    # But an empty set would now abort collection, because empty_parameter_set_mark is
    # fail_at_collect: a guard over nothing is an error here. This is the one place
    # where nothing to guard is the honest answer, so it says so out loud rather than
    # arriving as an empty list indistinguishable from a set that rotted away.
    if not (REPO / ".git").exists():
        return [pytest.param(None, id="no-git", marks=pytest.mark.skip(reason="no .git: source tarball"))]

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

# Everything a reader can execute: a shell command, or a config they paste into a
# client. Read whole, never line by line -- see _runnable().
RUNNABLE_FENCE = re.compile(r"```(?:bash|sh|console|json)\n(.*?)```", re.S)

# Commands belonging to this project, as opposed to git, pip, make and python.
OURS = re.compile(r"arch[-_]wiki")

# The shapes that decay: a count of tests, and a ratio over the corpus.
#
# Not every number. A port, a timeout, a Python version, a JSON-RPC code and an exit
# status are constants -- prose may name them and they will still be true tomorrow.
# Nor a figure in a post-mortem: "a live audit of 1834 sections spent its budget
# re-fetching the same 37 pages" is a record of something that happened, in the same
# way a changelog records a path that is gone, and neither is a claim about now.
#
# What is forbidden is the *status* claim -- the number that purports to describe the
# project as it stands, and silently stops doing so on the next commit.
MEASURED_COUNT = re.compile(
    r"\b\d+\s+(?:offline\s+)?tests\b"                     # "210 offline tests"
    r"|\b\d+\s+passing\b"                                 # "144 passing"
    r"|\b\d+\s*/\s*\d+\s+(?:sections|blocks|pages)\b"     # "432/432 sections"
    # "121 of 432 sections", and "116 of the 327 code blocks" -- the filler words
    # `the` and `code` between the count and its unit hid the second form from an
    # earlier version of this arm, so a stale ratio sat on the README front page
    # under the very guard that forbids it. The unit noun anchors it; a bounded run
    # of non-digit words may sit between.
    r"|\b\d+\s+of\s+(?:the\s+)?\d+(?:\s+[a-z]+){0,2}?\s+(?:sections|blocks|pages|tests)\b"
    r"|\bacross\s+\d+\s+(?:sections|blocks|pages)\b",     # "0 across 151 blocks"
    re.I,
)
# The ratio arm is anchored on the *unit*, not on punctuation. It first matched
# `\d+ of \d+\s*\)` -- a closing bracket -- which caught "(121 of 432)" and waved
# through "121 of 432 sections", the same sentence with the parenthesis removed. That
# is this file's own complaint about the JSON blind spot, one register over: a guard
# keyed on a favourite notation rather than on the shape it claims to forbid.
#
# Counting *admonitions*, *results* or *messages* stays legal, which is what keeps the
# post-mortems above this line ("7 of 108 {{bc}} blocks were recovered") from tripping
# it -- they are records of what happened, not claims about what is true now.

# The rot lived worst where a document guard structurally cannot look: the docstring
# of extract_section_wikitext(), the function the invariant is *about*, still said
# "432 sections ... (121 of 432)" long after both were wrong.
COUNTED = INSTRUCTIONS + sorted((REPO / "src" / "arch_wiki_mcp").glob("*.py"))


@pytest.mark.parametrize("document", COUNTED, ids=lambda p: p.name if p else "no-git")
def test_no_document_publishes_a_count_that_nothing_updates(document):
    """
    A number in prose goes stale exactly as silently as one in code.

    This is #19 again -- the User-Agent that went on naming a version abandoned
    releases earlier -- in the register where it is hardest to see, because no
    import fails and no test turns red. The README advertised "210 offline tests"
    while the suite had 458. Three documents justified how the parser slices every
    section it returns by citing "432/432 sections; byte indexing 121/432", counted
    once by hand; fixtures were added afterwards and the true figures had drifted to
    461 and 124. The *claim* stayed true and its evidence quietly rotted.

    So: counts belong in the tests, where changing one fails something.
    CORPUS_SECTIONS and TOTAL_CODE_TEMPLATES are pinned there. Prose states the
    invariant -- "every recorded section resolves onto its own heading" -- which is
    both stronger and incapable of going out of date.
    """
    found = MEASURED_COUNT.findall(document.read_text(encoding="utf-8"))

    assert not found, (
        f"{document.name} publishes a count nothing keeps true; state the invariant "
        f"and pin the number in a test instead"
    )


def _runnable(document) -> str:
    """
    The parts of a document a reader can execute.

    Prose is not one of them. This guard first read every line of every document, and
    the first thing it caught was CHANGELOG.md -- for the sentence recording that
    `python3 src/mcp_server.py --stdio` is *gone*. Which is what a changelog is: the
    one document whose job is to name what no longer exists.

    The obvious patch is to exempt CHANGELOG.md, and a hand-picked exemption is the
    mistake this file already carries a docstring apologising for. The honest fix is
    to stop overclaiming: the promise is that a document must not tell you to *run*
    something that is not there. Narrating a removal is not an instruction.

    A workflow or a Makefile, though, is executable from top to bottom -- it has no
    prose to protect. Reading only its `run:` lines missed a `run: |` block outright,
    which is how CI would most naturally spell a multi-line step. So: config files
    whole, markdown by its fences.

    And the fences include ```json, read whole. Matching `"command":` line by line had
    the identical blind spot one format over -- an MCP registration split across lines,

        "args": [
          "src/mcp_server.py",
          "--stdio"
        ]

    is how a client config is most naturally written, and is exactly where #22 lived.
    A guard that catches a bug in bash and misses it in JSON has picked a favourite
    notation, not a rule.

    What this does NOT guard, said plainly rather than left implied: a path named in
    prose or inline backticks. Rename extractor.py and MCP_PROTOCOL.md's mention of it
    goes stale, silently. That is doc-rot, and it is a real cost -- but the promise
    here is narrower and keepable: nothing this repository tells you to *run* will be
    missing when you run it.
    """
    text = document.read_text(encoding="utf-8")

    if document.suffix in (".yml", ".yaml") or document.name == "Makefile":
        return text

    return "\n".join(RUNNABLE_FENCE.findall(text))


@pytest.mark.parametrize("document", INSTRUCTIONS, ids=lambda p: p.name)
def test_no_document_tells_a_reader_to_run_a_path_that_does_not_exist(document):
    """
    The tripwire for the whole class. `python3 src/mcp_server.py --stdio` sat in
    MCP_SETUP.md and in tests.yml after the file it names was deleted, and nothing
    in the suite was capable of noticing -- a document is not imported, so it never
    raises ModuleNotFoundError. It just goes on being wrong, quietly, to everyone
    who follows it.
    """
    runnable = _runnable(document)

    missing = sorted(
        path
        for path in PATH_LIKE.findall(runnable)
        # A glob is satisfied by anything it matches; a plain path by itself.
        if not (list(REPO.glob(path)) if "*" in path else (REPO / path).exists())
    )

    assert not missing, (
        f"{document.name} tells a reader to run paths that do not exist: {missing}"
    )


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

    # Answered before it is indexed. A server that dies on startup writes nothing to
    # stdout, and `splitlines()[0]` on that is an IndexError -- a test that exists to
    # say *why* a registration does not start a server, failing with a traceback that
    # says nothing and throwing away the stderr that says everything. "Failed to
    # connect", reinvented inside the test written to replace it.
    assert result.stdout, f"the registered command produced no answer:\n{result.stderr}"

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
        server.run_preflight([])

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


def _commands_in(fence: str) -> list:
    """
    The lines a reader would type. A ```console fence is a *transcript* -- a prompted
    command, then what the machine said back -- so reading every line as a command
    made the guard demand that `XX` and `1` be listed as prerequisites. It could not
    tell an instruction from its output.

    A prompt is the structure that distinguishes them. Where there is one, only the
    prompted lines are commands; where there is none, every line is.
    """
    prompted = [line.lstrip()[2:] for line in fence.splitlines() if line.lstrip().startswith("$ ")]
    return prompted or fence.splitlines()


# A shell reads `FOO=bar cmd` as running `cmd`. So must we, or the assignment gets
# mistaken for a tool the reader has to go and install.
ENV_PREFIX = re.compile(r"^\s*(?:[A-Z_]+=\S*\s+)+")

# Not a tool anyone obtains: it is built into the shell.
BUILTIN = {"cd", "export", "source", "echo"}


def _prerequisites(text: str) -> str:
    """The section that promises what a reader needs before following the rest."""
    section = re.search(r"^### Prerequisites\s*$(.*?)^### ", text, re.M | re.S)
    return section.group(1) if section else ""


def test_the_setup_guide_asks_for_no_tool_it_did_not_tell_you_to_get():
    """
    The guard's own rule, one step out. It already refuses a command this package
    does not install -- but every command it *does* let through, it lets through
    silently, and the guide had grown four: pipx, git, claude, python3, against a
    Prerequisites list naming only Python.

    pipx was not hypothetical. The machine this was written on did not have it, and
    the very first thing `pipx install arch-wiki-mcp` did there was fail with
    "command not found". A setup document that opens by asking for a tool it never
    mentioned is the same failure as one that names a path it deleted: the reader
    does what it says, and it does not work.

    Prerequisites is the authority for what a reader is expected to have. A command
    in a fence must be ours, or listed there, or not a tool at all.
    """
    text = (REPO / "MCP_SETUP.md").read_text(encoding="utf-8")
    ours = declared_scripts()

    # The names Prerequisites *lists*, not the characters it contains. `command not
    # in listed` was a substring test against prose, and `pip` is a substring of
    # `pipx`: with pip removed from the list, the guard went on passing while the
    # fences went on saying `pip install -e .`. Blind, today, in the guard written
    # this morning to stop a document asking for a tool it never announced.
    #
    # Matching text where the structure was meant -- for the fifth time this week.
    listed = set(re.findall(r"[\w.-]+", _prerequisites(text)))

    unannounced = sorted({
        command
        for fence in BASH_FENCE.findall(text)
        for line in _commands_in(fence)
        for command in COMMAND_LINE.findall(ENV_PREFIX.sub("", line))[:1]
        if command not in BUILTIN
        and command not in ours
        and command not in listed
    })

    assert not unannounced, (
        f"MCP_SETUP.md tells a reader to run {unannounced}, and its Prerequisites "
        "never mention them"
    )
