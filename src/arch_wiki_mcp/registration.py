"""
Diagnose and repair MCP client registrations of this server.

`--check` with no argument prints the registration that works on this machine.
`--check <config>` reads a client config, finds the registrations in it that are
ours, and *runs* them -- because "Failed to connect" names a dead path, a missing
package and an import error identically, and the only way to tell which is to start
the command and ask who answered. This module is that machinery; server.py wires it
to the CLI.
"""

import json
import os
import re
import shutil
import subprocess
import sys
from importlib import metadata
from pathlib import Path
from typing import Any, Optional, Tuple

from arch_wiki_mcp import _DISTRIBUTION

# This module, as an installed client must name it.
MODULE = "arch_wiki_mcp.server"

# A registration that does not answer in this long is not one a client will wait for
# either. Unbounded here would hang `--check` forever on a server that starts and
# then says nothing -- the failure mode this command exists to diagnose.
HANDSHAKE_TIMEOUT = 15


def _installed_command() -> Optional[Path]:
    """
    The console script pip actually created for this module, asked of the installer.

    Not `Path(sys.executable).parent / "arch-wiki-mcp"`: that transcribes the very
    name this whole command exists to stop people transcribing. Rename the script in
    pyproject and a hand-spelled copy silently stops matching -- and because the
    fallback below still works, nothing would fail. The installer recorded the name;
    ask it. (shutil.which also gets Windows' `Scripts/arch-wiki-mcp.exe` right, which
    path arithmetic does not.)
    """
    for entry in metadata.distribution(_DISTRIBUTION).entry_points:
        # `.module` is the parsed left half of "pkg.mod:func" -- matching on it means
        # renaming main() does not silently drop us to the fallback below.
        if entry.group == "console_scripts" and entry.module == MODULE:
            found = shutil.which(entry.name, path=str(Path(sys.executable).parent))
            if found:
                return Path(found)
    return None


def _registration() -> dict:
    """The command an MCP client should spawn, resolved rather than transcribed."""
    console_script = _installed_command()

    if console_script:
        command, args = str(console_script), ["--stdio"]
    else:
        # A `pip install --user` puts the script somewhere this interpreter cannot
        # see. The interpreter itself is still a path we know to be right.
        command, args = sys.executable, ["-m", MODULE, "--stdio"]

    return {"mcpServers": {"arch-wiki": {"command": command, "args": args}}}


def _installed_version() -> str:
    """The installed distribution, or the reason no client can start one."""
    try:
        return metadata.version(_DISTRIBUTION)
    except metadata.PackageNotFoundError:
        print(
            f"{_DISTRIBUTION} is not installed, so no MCP client can start it.\n"
            "  Run: pip install -e .\n"
            f"  (using the interpreter you intend the client to use: {sys.executable})",
            file=sys.stderr,
        )
        sys.exit(1)


# A registration is an object with a command. That is the whole shape.
#
# NOT a table of where each client keeps its config. Claude Code nests servers under
# a per-project key, Claude Desktop does not; Cline lives in VS Code's globalStorage,
# which forks again for Cursor and Windsurf. Encoding those paths would be a registry
# of other people's file layouts -- external paths that rot without notice, which is
# precisely the bug this command exists to end, reproduced one layer out. The reader
# names the file; we read whatever shape they hand us.
def _registrations_in(config: Any, at: str = "", key: str = "") -> list:
    """Returns (where it sits, the name it is filed under, the entry)."""
    found = []

    if isinstance(config, dict):
        if isinstance(config.get("command"), str):
            found.append((at or "<root>", key, config))
        for name, value in config.items():
            found += _registrations_in(value, f"{at}.{name}" if at else name, name)
    elif isinstance(config, list):
        for index, value in enumerate(config):
            found += _registrations_in(value, f"{at}[{index}]", key)

    return found


# Ours, as opposed to every other server in the same file.
_OURS = re.compile(r"arch[-_]wiki", re.I)


# The programs for which a script path or a `-m` module is a thing to *run*. For
# anything else -- touch, npx, a shell -- those same tokens are just data.
_PYTHON = re.compile(r"python(\d+(\.\d+)?)?")


def _executes(command: str, args: list) -> list:
    """
    The arguments naming something *this command* will run, not something it is told
    about.

    This is the whole safety of the feature, and it took two passes to get right.
    First it matched every argument -- so a filesystem server granted access to this
    repository (`npx @mcp/server-filesystem /home/you/code/arch-wiki-mcp`) was read as
    ours and executed. Then it matched a `.py` or `-m` argument regardless of the
    command -- so `touch /tmp/arch-wiki-mcp.py`, which runs nothing, was read as ours
    and executed too. A path ending in .py is a script only to a program that runs
    scripts; to `touch` it is a filename.

    So the command decides. Only when it is a Python interpreter does a `.py`/`.pyz`
    argument, or the module after `-m`, name something it will execute.
    """
    if not _PYTHON.fullmatch(Path(command).name):
        return []

    return [
        arg
        for index, arg in enumerate(args)
        if str(arg).endswith((".py", ".pyz")) or (index and args[index - 1] == "-m")
    ]


def _is_ours(key: str, entry: dict) -> bool:
    """
    The name it is filed under, the command's own name, and what that command runs.

    The key counts: an entry whose command is wrong in every part still says which
    server it was *meant* to be (`"arch-wiki": {...}`), and reading only the command
    called that "no Arch Wiki MCP server registered" -- not merely unhelpful but wrong,
    and it sends the reader to add a second entry beside the broken one.

    The key, though, and not the path to it: Claude Code files servers under the
    project directory, which here is *called* arch-wiki-mcp, so matching the path made
    every server in this repo's config look like ours.

    And the command's basename, not the whole path, for the same reason -- a venv
    inside this checkout puts `arch-wiki-mcp` in every absolute path it holds.
    """
    command = str(entry["command"])
    args = [str(a) for a in entry.get("args") or []]
    words = [key, Path(command).name, *_executes(command, args)]

    return any(_OURS.search(word) for word in words)


def _child_environment(entry: dict) -> dict:
    """
    The environment the *client* would spawn it in, not the one we happen to be in.

    Inheriting ours quietly blesses the failure this command exists to catch: with a
    venv activated, `python3 -m arch_wiki_mcp.server` answers healthy here and dies in
    the GUI client, which has neither VIRTUAL_ENV nor PYTHONPATH. A registration that
    only works because of the shell you checked it from is exactly the registration
    that will not work.
    """
    environment = {
        key: value
        for key, value in os.environ.items()
        if key not in ("PYTHONPATH", "VIRTUAL_ENV")
    }
    environment.update({str(k): str(v) for k, v in (entry.get("env") or {}).items()})
    return environment


def _answers(argv: list, environment: dict) -> Tuple[Optional[str], Optional[str], str]:
    """
    Run the registration and ask who answered. Returns (name, version, why-not).

    The whole point. A registration is not a string to be compared with another string
    -- it is a command a client executes, and the only honest question is whether
    executing it produces this server. Everything else is a guess about a path, which
    is how the dead one survived for months.
    """
    try:
        answer = subprocess.run(
            argv,                      # a list, never a shell string
            input='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}\n',
            capture_output=True,
            text=True,
            timeout=HANDSHAKE_TIMEOUT,
            env=environment,
        )
    except subprocess.TimeoutExpired:
        return None, None, f"it started and said nothing for {HANDSHAKE_TIMEOUT}s"
    except OSError as exc:
        return None, None, str(exc)

    try:
        served = json.loads(answer.stdout.splitlines()[0])["result"]["serverInfo"]
        return served["name"], served.get("version"), ""
    except (ValueError, IndexError, KeyError, TypeError):
        # Its own last word on the matter beats any guess of ours: python says
        # "No module named arch_wiki_mcp", or "can't open file ...: No such file".
        spoke = [line for line in answer.stderr.splitlines() if line.strip()]
        return None, None, spoke[-1] if spoke else "it answered no MCP initialize"


def _diagnose(entry: dict) -> Tuple[str, str]:
    """(verdict, explanation) for one registration a client would spawn."""
    command = str(entry["command"])
    args = [str(a) for a in entry.get("args") or []]
    environment = _child_environment(entry)

    # Resolved against the client's PATH, not ours. An entry may set env.PATH so a
    # bare command is findable -- checking it against our PATH would call a working
    # registration "no such command", or worse, run a different binary of the same
    # name than the client would.
    resolved = shutil.which(command, path=environment.get("PATH"))
    if resolved is None:
        if Path(command).exists():
            return "dead", f"it is there but not executable: chmod +x {command}"
        return "dead", f"no such command: {command}"

    name, version, why_not = _answers([resolved, *args], environment)

    if name is None:
        return "dead", why_not
    if not _OURS.search(name):
        return "foreign", f"it answers as {name!r}, which is not this server"
    if not Path(command).is_absolute():
        return (
            "fragile",
            f"answers as {version}, but `{command}` is resolved from PATH -- and a GUI "
            "client inherits the desktop session's PATH, not your shell's",
        )

    return "healthy", f"answers as {version}"


# One taxonomy, stated once: how it prints, and whether a client can start it.
_VERDICTS = {
    "healthy": ("OK ", False),
    "fragile": ("?? ", False),
    "dead": ("XX ", True),
    "foreign": ("XX ", True),
}


def check_registration(config_path: str):
    """
    Does the registration you already have actually work?

    `--check` alone prints the registration that *would* work. It cannot tell you the
    one in your config is dead, and that is the failure this project actually shipped:
    a path written into a config months earlier, pointing at a file a rename deleted,
    reported by the client as "Failed to connect" -- three words that name a dead path,
    a missing package, an import error and a firewall identically.

    This reads the file you name, finds every registration in it that mentions this
    project, and *runs* them. Not compares -- runs. A registration is a command a
    client executes; whether it works is a question with an answer, and asking a human
    to eyeball two paths instead is the transcription this whole command exists to
    abolish.
    """
    installed = _installed_version()
    path = Path(config_path).expanduser()

    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"no such config file: {path}", file=sys.stderr)
        sys.exit(1)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"cannot read {path}: {exc}", file=sys.stderr)
        sys.exit(1)

    every = _registrations_in(config)
    ours = [(where, entry) for where, key, entry in every if _is_ours(key, entry)]

    if not ours:
        print(
            f"{path} registers no Arch Wiki MCP server.\n"
            f"(It has {len(every)} MCP registration(s), none of them ours. They are not "
            "read further, and never run.)\n"
            "\nAdd this one:",
            file=sys.stderr,
        )
        print(json.dumps(_registration(), indent=2))
        sys.exit(1)

    print(f"{path}", file=sys.stderr)
    failing = 0
    for where, entry in ours:
        spawned = " ".join([str(entry["command"]), *(str(a) for a in entry.get("args") or [])])
        # Said before it is run, not after: a registration that hangs, or that is not
        # the server it claims to be, must be attributable to the line that spawned it.
        print(f"      {spawned}", file=sys.stderr)

        verdict, why = _diagnose(entry)
        mark, fails = _VERDICTS[verdict]
        print(f"  {mark} {where}\n      {why}\n", file=sys.stderr)
        failing += fails

    if not failing:
        print(f"Registration is live. Installed: {_DISTRIBUTION} {installed}.", file=sys.stderr)
        return

    print(f"{failing} registration(s) a client cannot start. Replace with:", file=sys.stderr)
    print(json.dumps(_registration(), indent=2))
    sys.exit(1)


def run_preflight(argv: list):
    """
    Answer the one question a failed registration cannot: *why*.

    An MCP client reports a dead path, an uninstalled package, an import error and
    a blocked port identically -- "Failed to connect". With no argument this prints
    the registration that works on *this* machine (stdout, so it can be redirected
    straight into a config). Given a config file, it checks the registration you
    already have, by running it.
    """
    if argv:
        check_registration(argv[0])
        return

    installed = _installed_version()
    registration = _registration()

    print(
        f"{_DISTRIBUTION} {installed} is installed and ready.\n"
        f"  package: {Path(__file__).parent}\n\n"
        "The registration below (on stdout, so it can be redirected into a config)\n"
        "is absolute on purpose: a bare command name resolves only if the client\n"
        "inherits a PATH that has it, and GUI clients often do not.\n"
        "\nTo check a registration you already have:  arch-wiki-mcp --check <config>",
        file=sys.stderr,
    )
    print(json.dumps(registration, indent=2))
