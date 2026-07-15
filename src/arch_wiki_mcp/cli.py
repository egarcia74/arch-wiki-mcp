"""
The command line: argv into a tool call, or into one of the modes.

`main()` is the entry point pip installs and `python -m arch_wiki_mcp.server`
runs. It routes the mode flags (`--stdio`, `--check`) through `_MODE_DISPATCH`
and everything else through the same tool machinery the MCP transport uses -- so
the shell and a client refuse the same calls for the same reasons, only the
envelope differs. The tools and their schema live in tools.py; the stdio
transport in protocol.py; the registration preflight in registration.py.
"""

import json
import sys
from typing import Any, Dict

from arch_wiki_mcp.tools import (
    InvalidParamsError,
    UnknownToolError,
    _error_payload,
    _INPUT_SCHEMAS,
    _TOOL_DISPATCH,
    handle_tool_call,
)
from arch_wiki_mcp.protocol import run_mcp_server
from arch_wiki_mcp.registration import run_preflight


def _cli_parameters(tool: str) -> list:
    """Positional CLI order for a tool: its required parameters, then the rest."""
    properties = _INPUT_SCHEMAS[tool]["properties"]
    required = _INPUT_SCHEMAS[tool]["required"]
    return list(required) + [name for name in properties if name not in required]


def _cli_usage() -> str:
    """
    Generated from the schema, not restated beside it.

    The argv ladder used to spell out every tool and parameter by hand -- a
    fourth copy of the tool list after _TOOLS, _INPUT_SCHEMAS and _TOOL_DISPATCH,
    with the usage text a fifth. A tool added to the schema now appears here.
    """
    lines = ["Usage: arch-wiki-mcp <tool> <args...>", "", "Available tools:"]
    for tool in _TOOL_DISPATCH:
        required = set(_INPUT_SCHEMAS[tool]["required"])
        params = " ".join(
            f"<{name}>" if name in required else f"[{name}]"
            for name in _cli_parameters(tool)
        )
        lines.append(f"  {tool} {params}")
    lines += ["", "Or:"]
    lines += [
        f"  arch-wiki-mcp {flag}  ({description})"
        for flag, (_, _, description) in _MODE_DISPATCH.items()
    ]
    lines += ["", "Check a registration you already have:", "  arch-wiki-mcp --check <config-file>"]
    return "\n".join(lines)


def _cli_arguments(tool: str, argv: list) -> dict:
    """
    Build a tool call from positional CLI arguments, typed by the schema.

    Raises InvalidParamsError rather than letting IndexError or int() escape: the
    argv build sat outside the try below, so `page` with no argument answered a
    shell with a raw traceback while the same mistake over MCP got a clean coded
    error. Same fault, two shapes.
    """
    if tool not in _INPUT_SCHEMAS:
        raise UnknownToolError(f"Unknown tool: {tool}")

    properties = _INPUT_SCHEMAS[tool]["properties"]
    parameters = _cli_parameters(tool)

    # zip() stops at the shorter sequence, so `section GRUB Installation extra`
    # silently ignored `extra` and reported success. Fewer arguments than parameters
    # is legitimate (they may be optional) and the schema catches a missing required
    # one; more than there are places to put is simply a mistake.
    if len(argv) > len(parameters):
        raise InvalidParamsError(
            f"{tool} takes at most {len(parameters)} argument(s), got {len(argv)}: "
            f"{' '.join(argv[len(parameters):])}"
        )

    arguments: Dict[str, Any] = {}

    for name, raw in zip(parameters, argv):
        if properties[name]["type"] == "integer":
            try:
                arguments[name] = int(raw)
            except ValueError:
                raise InvalidParamsError(
                    f"{tool}.{name} must be an integer, got {raw!r}"
                ) from None
        else:
            arguments[name] = raw

    # Anything still missing is caught by _validate_arguments against the schema,
    # so the CLI and the MCP transport refuse the same calls for the same reason.
    return arguments


# The modes, declared rather than accumulated as an argv ladder -- the same reason
# _TOOL_DISPATCH and _METHOD_DISPATCH exist. Two `len(sys.argv) == 2 and ...`
# clauses had already grown here, and _cli_usage() was restating them by hand: the
# fourth-copy problem this file has now solved three times.
#
# Handlers take their own arguments. --check grew one -- a config file to check --
# and a table whose entries could not accept arguments would have pushed that back
# into the ladder it exists to prevent.
# (handler, how many arguments it takes, what it does). The arity is declared, not
# discovered: it was an exception raised from inside the handler, and the try that
# caught it wrapped the whole lifetime of run_mcp_server() -- so an arity error
# escaping the RPC loop would have printed CLI usage into a JSON-RPC session.
_MODE_DISPATCH = {
    "--stdio": (run_mcp_server, 0, "run as an MCP server over stdio"),
    "--check": (
        run_preflight,
        1,
        "print a registration a client can use; with a config file, check the one it has",
    ),
}


def main():
    """
    Entry point - detect MCP mode vs CLI mode.

    MCP mode: Running via stdio (no args)
    CLI mode: Direct invocation with args
    """
    # No arguments *is* --stdio: the default is an entry in the table, not a branch
    # above it, or the table stops being the one statement of what modes exist.
    argv = sys.argv[1:] or ["--stdio"]

    if argv[0] in _MODE_DISPATCH:
        handler, takes, _ = _MODE_DISPATCH[argv[0]]
        rest = argv[1:]

        if len(rest) > takes:
            # The flag exists; the arity is wrong. Said plainly, because the ladder
            # used to fall through and report "Unknown tool: --check", which sends the
            # reader looking for a tool they never asked for.
            expected = "no arguments" if takes == 0 else f"at most {takes} argument"
            print(f"{argv[0]} takes {expected}\n\n{_cli_usage()}", file=sys.stderr)
            sys.exit(1)

        handler(*([rest] if takes else []))
        return

    tool = argv[0]

    # A failed call must not leave the shell believing it succeeded: the payload
    # goes to stderr and the exit status is non-zero, so a caller that only
    # checks $? still fails closed. Same breadth and same payload as the MCP
    # transport -- both answer "this call failed"; only the envelope differs.
    # The argv build is inside the try for exactly that reason: outside it, a
    # missing argument was a traceback here and a coded error there.
    try:
        result = handle_tool_call(tool, _cli_arguments(tool, argv[1:]))
    except UnknownToolError as e:
        print(f"{e}\n\n{_cli_usage()}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(json.dumps(_error_payload(e), indent=2, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)

    print(json.dumps(result, indent=2, ensure_ascii=False))
