"""
The registration you already have is the one nothing could check.

`--check` printed the registration that *would* work. It could not tell you the one
in your config was dead -- and that is the failure this project actually shipped. A
path written into a config months earlier, pointing at a file a rename deleted, and a
client that said only "Failed to connect": three words that name a dead path, a
missing package, an import error and a firewall identically.

So `--check <config>` reads the file you name, finds every registration in it that
mentions this project, and *runs* them. Not compares -- runs. A registration is a
command a client executes; whether it works is a question with an answer, and asking a
human to eyeball two paths instead is the transcription the whole command exists to
abolish.

Running them is not a new risk: the client already executes these commands at every
startup. This executes one of them once, bounded, and says what happened.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import REPO
from arch_wiki_mcp import registration


def _check(tmp_path, config: dict, path: str = ""):
    """Run `--check <config>` as a user does, and return (exit code, what they read)."""
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps(config), encoding="utf-8")

    environment = {**os.environ}
    if path:
        environment["PATH"] = path + os.pathsep + environment.get("PATH", "")

    result = subprocess.run(
        [sys.executable, "-m", "arch_wiki_mcp.server", "--check", str(config_file)],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=90,
        env=environment,
    )
    return result.returncode, result.stdout + result.stderr


def test_the_registration_offered_is_one_that_exists():
    """
    The oracle, checked independently. Every assertion below that a fix was offered
    compares against registration._registration() -- the code under test -- so a bug that
    printed a command that does not exist would agree with itself. This does not ask
    the code; it asks the filesystem.
    """
    command = Path(_working()["command"])

    assert command.is_absolute(), "the registration offered is not absolute"
    assert command.exists(), f"the registration offered names nothing: {command}"


def _working() -> dict:
    """The registration this machine would print -- the one that works."""
    return registration._registration()["mcpServers"]["arch-wiki"]


# The config as it stood when the MCP stopped connecting: Claude Code's own nesting,
# the path #22 deleted, and an unrelated server beside it.
STALE = {
    "projects": {
        str(REPO): {
            "mcpServers": {
                "arch-wiki": {
                    "type": "stdio",
                    "command": "python3",
                    "args": [f"{REPO}/src/mcp_server.py", "--stdio"],
                    "env": {},
                },
                "some-other-server": {
                    "command": "definitely-not-a-real-binary",
                    "args": ["--serve"],
                },
            }
        }
    }
}


def test_the_registration_that_started_all_this_is_named_as_dead(tmp_path):
    """
    The regression test for the whole session. This exact config -- a path a rename
    deleted, nested where Claude Code nests it -- produced "Failed to connect", and
    nothing in the repository could say why.
    """
    code, said = _check(tmp_path, STALE)

    assert code != 0
    assert "src/mcp_server.py" in said, "it did not name the dead path"
    # Its own words, not ours: "can't open file ...: [Errno 2] No such file or directory".
    assert "No such file" in said, said
    # And it must hand over the fix, not merely the diagnosis.
    assert _working()["command"] in said, "it diagnosed the failure and offered no cure"


def test_a_foreign_server_in_the_same_file_is_never_run(tmp_path):
    """
    The config holds other people's servers. We read the whole file to find ours --
    which means we must be sure about what is *not* ours before running anything.
    """
    code, said = _check(tmp_path, STALE)

    assert "definitely-not-a-real-binary" not in said, (
        "a server that is not ours was diagnosed, which means it was executed"
    )


def test_a_foreign_server_pointed_at_this_repo_is_never_run(tmp_path):
    """
    The one that proves it, because it asserts a side effect did not happen.

    Every other test here keys the entry `arch-wiki`, so they all pass on the key alone
    -- and `_is_ours` went on matching *arguments* for a release, unguarded. Arguments
    are full of directory paths, and a filesystem server granted access to this
    checkout looked exactly like us:

        "filesystem": {"command": "npx", "args": ["-y", "@mcp/server-filesystem",
                                                  "/home/you/code/arch-wiki-mcp"]}

    That is an ordinary thing to have registered, and `--check` ran it -- which for npx
    means fetching a package off the network and executing it, from a command whose
    own documentation promises to leave other servers alone.

    Asserting the output does not mention it is not enough: the output is what we print,
    and the harm is what the child does. So this one spawns `touch` and checks the file
    was never created.
    """
    victim = tmp_path / "PWNED"
    code, said = _check(tmp_path, {
        "mcpServers": {
            "filesystem": {
                "command": "/usr/bin/touch",
                "args": [str(victim), str(REPO)],   # this repo, in an argument
            }
        }
    })

    assert not victim.exists(), (
        "--check executed a server that is not ours; an argument naming this "
        "repository is not a claim about which program it is"
    )
    assert "none of them ours" in said, said


def test_a_live_registration_is_reported_live(tmp_path):
    code, said = _check(tmp_path, {"mcpServers": {"arch-wiki": _working()}})

    assert code == 0, said
    assert "live" in said.lower(), said


def test_a_registration_that_starts_but_answers_nothing_is_refused(tmp_path):
    """Keyed `arch-wiki`, and it runs, and it speaks no MCP. Only asking it reveals that."""
    code, said = _check(
        tmp_path,
        {"mcpServers": {"arch-wiki": {"command": "/bin/cat", "args": ["/dev/null"]}}},
    )

    assert code != 0
    assert "no MCP initialize" in said, said


def test_a_registration_that_answers_as_a_different_server_is_refused(tmp_path):
    """
    It speaks MCP. It handshakes. It is some other project's server, filed under our
    name -- and every check that compares paths, or merely proves *something* started,
    calls this healthy.
    """
    imposter = (
        "import sys, json; sys.stdin.readline(); "
        'print(json.dumps({"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2024-11-05",'
        '"serverInfo":{"name":"some-other-mcp","version":"9.9.9"}}}))'
    )
    code, said = _check(
        tmp_path,
        {"mcpServers": {"arch-wiki": {"command": sys.executable, "args": ["-c", imposter]}}},
    )

    assert code != 0
    assert "some-other-mcp" in said and "not this server" in said, said


def test_an_interpreter_without_the_package_says_so(tmp_path):
    """
    "Failed to connect" cannot tell a dead path from a package installed against the
    wrong interpreter. This can, because it does not guess -- it runs the thing and
    repeats what it said: "No module named 'arch_wiki_mcp'".
    """
    code, said = _check(tmp_path, {
        "mcpServers": {
            "arch-wiki": {
                "command": "/usr/bin/python3",
                "args": ["-m", "arch_wiki_mcp.server", "--stdio"],
            }
        }
    })

    assert code != 0
    assert "No module named" in said, said


def test_an_entry_whose_command_is_wrong_in_every_part_is_still_found(tmp_path):
    """
    The key is evidence. `"arch-wiki": {...}` says which server it was *meant* to be,
    and reading only the command reported this as "no Arch Wiki MCP server registered"
    -- which is not merely unhelpful, it is wrong, and it sends the reader to add a
    second entry beside the broken one.
    """
    code, said = _check(
        tmp_path,
        {"mcpServers": {"arch-wiki": {"command": "/bin/cat", "args": []}}},
    )

    assert "registers no Arch Wiki MCP server" not in said, said
    assert code != 0


def test_a_bare_command_is_flagged_rather_than_blessed(tmp_path):
    """
    It may well work in the shell you are typing in. That is the trap: a GUI client
    inherits the desktop session's PATH, not yours, so the config that passes here is
    exactly the one that fails in the app.

    The console script's directory is put on PATH explicitly, so this tests the
    *fragility* of a bare command and not whether the test runner happened to have one.
    """
    script = registration._installed_command()
    assert script, "the console script is not installed; this test would prove nothing"

    code, said = _check(
        tmp_path,
        {"mcpServers": {"arch-wiki": {"command": script.name, "args": ["--stdio"]}}},
        path=str(script.parent),
    )

    assert "PATH" in said, said
    assert code == 0, "a bare command that works is a warning, not a failure"


def test_a_config_with_no_registration_of_ours_offers_one(tmp_path):
    code, said = _check(tmp_path, {"mcpServers": {"other": {"command": "ls", "args": []}}})

    assert code != 0
    assert "registers no Arch Wiki MCP server" in said
    assert _working()["command"] in said, "it refused, and did not say what to add"


@pytest.mark.parametrize("shape", [
    pytest.param({"mcpServers": {"arch-wiki": None}}, id="null-entry"),
    pytest.param({"mcpServers": []}, id="list-where-an-object-was-expected"),
    pytest.param([], id="top-level-list"),
    pytest.param({"servers": [{"command": "x", "args": []}]}, id="servers-as-a-list"),
])
def test_a_config_shaped_unlike_ours_does_not_crash(tmp_path, shape):
    """
    We do not know the client. A registration is an object with a `command`, and the
    file around it may be anything -- so finding none is an answer, and a traceback
    is not.
    """
    code, said = _check(tmp_path, shape)

    assert "Traceback" not in said, said
    assert code != 0


def test_an_unreadable_config_says_so_rather_than_crashing(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{ not json", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-m", "arch_wiki_mcp.server", "--check", str(path)],
        cwd=REPO, capture_output=True, text=True, timeout=60,
    )

    assert result.returncode != 0
    assert "Traceback" not in result.stderr, result.stderr
    assert "cannot read" in result.stderr


def test_a_missing_config_says_so_rather_than_crashing(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "arch_wiki_mcp.server", "--check", str(tmp_path / "nope.json")],
        cwd=REPO, capture_output=True, text=True, timeout=60,
    )

    assert result.returncode != 0
    assert "Traceback" not in result.stderr, result.stderr
    assert "no such config file" in result.stderr


def test_a_registration_is_found_wherever_the_client_chose_to_put_it():
    """
    Not a table of where each client keeps its servers. Claude Code nests them under a
    per-project key; Claude Desktop does not; Cline lives in VS Code's globalStorage,
    which forks again for Cursor and Windsurf. Encoding those layouts would be a
    registry of *other people's paths* -- external, unowned, rotting without notice,
    which is the bug this command exists to end, rebuilt one layer out.

    A registration is an object with a command. That is the whole shape we look for.
    """
    deep = {"a": {"b": [{"c": {"mcpServers": {"arch-wiki": {"command": "x", "args": []}}}}]}}

    found = registration._registrations_in(deep)

    assert [where for where, _, _ in found] == ["a.b[0].c.mcpServers.arch-wiki"]


def test_our_own_environment_never_makes_a_dead_registration_look_healthy(tmp_path):
    """
    The false positive this command exists to prevent, and the one it could most
    easily commit.

    A client spawns the server with the desktop session's environment. We spawn it
    with ours -- and ours may have PYTHONPATH or VIRTUAL_ENV pointing at a source tree
    that makes an otherwise-dead registration import cleanly. It would answer, we would
    call it healthy, and the client would go on failing.

    So: PYTHONPATH is set here to the very source tree that would rescue it. The child
    must not inherit it, and the verdict must stay dead.
    """
    rescued = {**os.environ, "PYTHONPATH": str(REPO / "src")}
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({
        "mcpServers": {
            "arch-wiki": {
                "command": "/usr/bin/python3",     # a system python, without the package
                "args": ["-m", "arch_wiki_mcp.server", "--stdio"],
            }
        }
    }), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-m", "arch_wiki_mcp.server", "--check", str(config_file)],
        cwd=REPO, capture_output=True, text=True, timeout=90, env=rescued,
    )
    said = result.stdout + result.stderr

    assert result.returncode != 0, (
        "PYTHONPATH leaked into the child: a registration the client cannot start was "
        "called healthy, because our shell happened to be able to import it"
    )
    assert "No module named" in said, said


def test_a_data_argument_that_looks_like_a_script_is_not_executed(tmp_path):
    """
    The second escape from the same trap. The matcher learned to require a `.py`/`-m`
    argument -- but a path ending in .py is a script only to a program that runs
    scripts. `touch /tmp/arch-wiki-mcp.py` runs nothing; the .py is a filename. Matched
    without the command, that filesystem-cleanup entry was read as ours and executed.

    Proven the only honest way: the command is `touch`, and the test asserts the file
    it would create never appears.
    """
    victim = tmp_path / "PWNED"
    code, said = _check(tmp_path, {
        "mcpServers": {
            "cleanup": {
                "command": "/usr/bin/touch",
                "args": [str(victim), "/tmp/arch-wiki-mcp.py"],   # a .py it does NOT run
            }
        }
    })

    assert not victim.exists(), (
        "--check ran a command that is not a Python interpreter because an argument "
        "ended in .py; only the command decides what an argument means"
    )
    assert "none of them ours" in said, said


def test_a_bare_command_resolvable_only_by_the_entrys_env_is_found(tmp_path):
    """
    A client sets `env.PATH` so a bare command resolves. Checking it against *our*
    PATH -- which does not have that directory -- reports "no such command" for a
    registration the client starts every day, and could run a different binary of the
    same name than the client would. The command is resolved against the environment
    the client would give it.
    """
    bindir = tmp_path / "bin"
    bindir.mkdir()
    # A fake server on the entry's PATH but not ours: a python that answers as us.
    fake = bindir / "my-arch-wiki"
    payload = json.dumps({
        "jsonrpc": "2.0", "id": 1,
        "result": {"protocolVersion": "2024-11-05",
                   "serverInfo": {"name": "arch-wiki-mcp", "version": "x"}},
    })
    # Absolute shebang: it answers without needing anything on the entry's own PATH,
    # so what the test exercises is whether we *resolved* it there.
    fake.write_text(f"#!/bin/sh\nhead -n1 >/dev/null\nprintf '%s\\n' '{payload}'\n")
    fake.chmod(0o755)

    code, said = _check(tmp_path, {
        "mcpServers": {
            "arch-wiki": {"command": "my-arch-wiki", "args": [], "env": {"PATH": str(bindir)}}
        }
    })

    assert "no such command" not in said, (
        "resolved against our PATH, not the entry's: a working registration was called dead"
    )
    # It is found and runs; bare, so it is flagged fragile, not failed.
    assert "PATH" in said, said


def test_a_python_data_argument_is_not_mistaken_for_its_script(tmp_path):
    """
    The third escape, and the sharpest: the command *is* a Python interpreter, so a
    `.py` argument is plausibly a script -- but Python runs exactly one, the first
    positional (or the module after -m). `python foreign.py /x/arch-wiki.py` runs
    foreign.py; the arch-wiki path is that program's argv, not a second script. Reading
    every `.py` argument ran foreign servers whose data happened to end in .py, and
    `-c` is worse -- it runs inline code no argument names at all.

    tmp_path is never under an arch-wiki directory, so foreign.py's own path cannot
    match; only the trailing data argument does, and it must not count.

    Every command here is one that *would* create the victim file if it ran -- the
    interpreter is sys.executable (not a hardcoded path that might be absent), the
    script and the module both touch the file, and the inline code does too. So a
    matcher regression does not merely fail to prove innocence; it executes something
    that leaves a mark, and the assertion catches it. A security test that stays green
    whether or not the command ran is no test at all.
    """
    victim = tmp_path / "PWNED"
    touch = f"import pathlib; pathlib.Path({str(victim)!r}).touch()"

    foreign = tmp_path / "foreign.py"
    foreign.write_text(touch + "\n")
    (tmp_path / "pwn_module.py").write_text(touch + "\n")   # importable, and it bites
    env = {"PYTHONPATH": str(tmp_path)}                     # applied after the strip, so -m finds it

    for args in (
        [str(foreign), "/tmp/arch-wiki-mcp.py"],       # data .py after the script
        [str(foreign), "-m", "arch_wiki_mcp.server"],  # data -m after the script
        ["-c", touch, "/tmp/arch-wiki.py"],            # bare -c inline code
        [f"-c{touch}", "/tmp/arch-wiki.py"],           # ATTACHED -c: Python accepts -cCODE
        ["-mpwn_module", str(tmp_path / "arch-wiki-marker")],  # ATTACHED -m: module is pwn_module, marker is data
    ):
        victim.unlink(missing_ok=True)
        _check(tmp_path, {"mcpServers": {"x": {"command": sys.executable, "args": args, "env": env}}})
        assert not victim.exists(), (
            f"--check ran a Python command because a *data* argument named arch-wiki: {args}"
        )


def test_a_genuine_python_module_target_is_still_recognized(tmp_path):
    """The converse: `python -m arch_wiki_mcp.server` must still be seen as ours."""
    code, said = _check(tmp_path, {
        "mcpServers": {
            "arch-wiki": {"command": sys.executable, "args": ["-m", "arch_wiki_mcp.server", "--stdio"]}
        }
    })
    assert "registers no Arch Wiki MCP server" not in said, said


@pytest.mark.parametrize("entry,why", [
    pytest.param({"command": "python3", "args": "not-a-list"}, "`args` must be a list", id="args-string"),
    pytest.param({"command": "python3", "args": ["-m", "x"], "env": "not-a-dict"}, "`env` must be an object", id="env-string"),
])
def test_a_malformed_registration_is_a_verdict_not_a_traceback(tmp_path, entry, why):
    """
    This command diagnoses *broken* configs, so a field of the wrong type is a `dead`
    verdict with a reason -- not an AttributeError a reader has to decode. A client
    cannot start `"env": "..."` or `"args": "..."` either.
    """
    code, said = _check(tmp_path, {"mcpServers": {"arch-wiki": entry}})

    assert "Traceback" not in said, said
    assert code != 0
    assert why in said, said
