"""
The MCP protocol: JSON-RPC 2.0 over stdio.

This is the transport. It reads a request off stdin, routes it through
`_METHOD_DISPATCH` to a handler, and writes the envelope back -- keeping the
distinction MCP draws between a fault in the request (a protocol error, nothing
ran) and a tool that ran and failed (an isError result). The tools themselves,
and the schema that validates a call, live in tools.py; this module serves them.
"""

import json
import logging
import sys
from typing import Optional

from arch_wiki_mcp import _DISTRIBUTION, __version__, extractor
from arch_wiki_mcp.tools import (
    InvalidParamsError,
    UnknownToolError,
    _error_payload,
    _TOOLS,
    handle_tool_call,
)


# The name this server answers an `initialize` with. It is the distribution's name
# because they are the same thing -- and it was spelled out twice, so a rename would
# have left the MCP identity behind, which is #19 in a different register.
SERVER_NAME = _DISTRIBUTION


# stderr by default, which keeps JSON-RPC on stdout clean.
logger = logging.getLogger(__name__)


def _tool_result(msg_id: int, payload: dict, is_error: bool = False) -> dict:
    """
    Wrap a tool's payload in the JSON-RPC envelope.

    isError is the only signal that separates "the wiki says no" from "the wiki
    says this". Without it the text of an error reads exactly like evidence.
    """
    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "result": {
            "content": [{
                "type": "text",
                "text": json.dumps(payload, indent=2, ensure_ascii=False)
            }],
            "isError": is_error,
        }
    }


def _protocol_error(msg_id: Optional[int], message: str, code: int = -32602) -> dict:
    """A fault in the request itself: nothing ran, so there is no tool result."""
    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "error": {"code": code, "message": message}
    }


def _tool_error_result(msg_id: int, exc: Exception) -> dict:
    """A tool that ran and failed, reported so a caller cannot read it as evidence."""
    return _tool_result(msg_id, _error_payload(exc), is_error=True)


def _send_response(response: dict):
    """Send JSON-RPC response to stdout."""
    print(json.dumps(response), flush=True)


def _handle_initialize(msg_id: int) -> dict:
    """
    The one protocol version we implement, and the identity we answer with.

    protocolVersion is a literal because MCP_PROTOCOL.md is pinned against it: the
    document is the contract, and a version bumped here without updating there fails
    the suite. name and version are derived, not restated -- the same fact the
    User-Agent and pyproject carry, stated once so the three cannot drift.
    """
    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "result": {
            "protocolVersion": "2024-11-05",
            "serverInfo": {"name": SERVER_NAME, "version": __version__},
            "capabilities": {"tools": {}, "prompts": {}}
        }
    }


def _handle_prompts_list(msg_id: int) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "result": {
            "prompts": [{
                "name": "arch-wiki-usage",
                "description": "How to use Arch Wiki MCP without becoming a liar",
                "arguments": []
            }]
        }
    }


def _handle_prompts_get(msg_id: int, params: dict) -> dict:
    prompt_name = params.get("name")
    if prompt_name == "arch-wiki-usage":
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "messages": [{
                    "role": "user",
                    "content": {
                        "type": "text",
                        "text": """You are an AI agent using the Arch Wiki MCP.

NON-NEGOTIABLE RULES (Truth Perimeter)
1) You must use the MCP as your only source for Arch Linux instructions in this workflow.
2) You must not synthesize commands, flags, paths, or steps that are not explicitly returned by the MCP.
3) Every claim or command you present must include provenance:
   - revision_url -- cite THIS one. It names the revision below (?oldid=), so it
     still identifies the text you quoted after the page moves on. (It renders that
     revision; a rendered old revision still transcludes templates as they are now,
     so it pins the article rather than every detail of the page. The wikitext the
     hashes cover is fixed.) source_url follows the page and will show a reader
     something else entirely.
   - source_url (with anchor if applicable) -- the live page, for a reader who
     wants the current state rather than the quoted one
   - revid
   - content_hash
   - extraction_method (if provided)
   revision_wikitext_url returns that revision's wikitext -- the exact bytes
   content_hash covers -- from the wiki's API, which a script can actually fetch.
   (Cite revision_url to a human; fetch revision_wikitext_url to check a hash.) A
   reader fetches it, NFC-normalizes, and re-hashes; that is what makes the citation
   falsifiable, and it is why the hash and the revision URLs must travel together. A
   hash beside a URL that has since changed proves nothing. content_hash_cleaned
   covers `content`, the rendered text you show --
   only this MCP can confirm that one, because the wiki never held that string.
   The hash is a fingerprint, not a signature: it shows the text matches the named
   revision, and says nothing about who produced the response. Do not claim more.

   wikitext_hash (page() only) covers the WHOLE page's wikitext, not any one
   block. Do not present it as attesting a fragment; content_hash does that.
4) If commands() returns an empty list, you MUST NOT infer a pacman command from prose.
   - Instead: call section() and quote the exact sentence(s) that describe what to do.
5) If a page/section is missing, you must fail closed:
   - return NotFound / empty result
   - do not suggest “closest match”
6) You must surface warnings and notes returned by warnings() before presenting related commands.
7) You must not merge multiple pages into a “unified guide” unless the user explicitly requests multi-page output AND you preserve page-level provenance per fragment.

SEARCH RESULTS ARE POINTERS, NOT EVIDENCE
search() carries no revid and no hash (nor does sections(), which is a map of anchors,
not evidence; everything else carries a revision and can be cited). It tells you which
page to open, and nothing it returns may be quoted. `snippet` is the wiki's match
context as plain text -- a truncated fragment of a revision nobody named, so a token cut
in half (a:C++|C++]]) keeps its brackets. `match` is "title" for the exact page (which
comes first when one exists) or "text" for a full-text hit, in the wiki's own order;
this MCP does not re-rank them. `pageid` is MediaWiki's numeric id -- pass `title` to
the other tools, not it. To say anything about a page, call section(), commands() or
warnings() and cite what they return.

WHICH FIELD IS VERBATIM
Three tools return the same evidence twice. Neither field may be edited by you.
   - commands(): show `content`, cite `content_raw` + content_hash.
   - warnings(): show `message`, cite `message_raw` + content_hash.
   - section():  show `content`, cite `content_raw` + content_hash.
The shown field already has wikitext markup resolved by this MCP ('' '' emphasis,
{{ic|...}}, [[links]]). Do not resolve it yourself and do not undo it.
content_hash_cleaned / message_hash_cleaned attest the shown text.

In section().content, a fenced ``` block is a command block the wiki wrote; prose is
prose. A '#' begins a heading, never a shell prompt -- outside a fence the wiki's own
numbered list renders as "1.", so a '#' you see inside a fence is a real root prompt.
Do not lift a fenced block out of section() and present it as a command: call
commands(), which returns it with its own hash and placeholders. If a template appears
raw ({{Accuracy|...}}), this MCP could not render it: report it as-is rather than
paraphrasing or dropping it.

Text the wiki wrapped in <nowiki> is literal and reaches you unchanged -- braces,
[[brackets]], ''apostrophes'' and <!-- comments --> alike. A {{ic|text}} in content may
therefore be a template we could not render, or the exact characters the wiki displays.
You cannot tell them apart and need not: report it as-is either way. An <!-- HTML
comment --> inside a code block is part of the file the wiki is showing; keep it.

A quoted template is never evidence. A page documenting syntax writes
<nowiki>{{bc|echo hi}}</nowiki>: that is prose ABOUT a template, not a command block.
commands() will not return it, warnings() will not raise a warning from it, and links()
will not offer its [[targets]] as navigation. It reaches you as the literal text the
wiki prints. Quote it as prose; never as a command, never as something the article
instructs you to do.

WHERE A WARNING'S TYPE CAME FROM
A translated page rarely writes {{Warning}}. The French Installation guide writes
{{Attention}}, a redirect to Template:Warning (Français), so the type WARNING appears
nowhere in that article's wikitext and its revid does not attest it. When a type was
learned that way the block carries `alias` (the redirect, "Attention"), `alias_target`
(where it points) and `alias_revid` (the revision of the REDIRECT PAGE -- not of the
article, and not of the redirect's target). All three are null when the template spelled
its own type ({{Warning}}, {{Note (Español)}}), which the article's revid already covers.
If `alias` is set, the type rests on a page other than the one you are citing: cite
"Template:<alias>" at alias_revid -- that pair names one page at one revision, and
alias_revision_url is that pair as a link you can follow -- and say separately that
it redirects to alias_target. Never cite alias_target at alias_revid: that revision
belongs to the redirect, not to its destination, so the pair names no page that exists.
Never present a redirect-derived WARNING as though the article itself declared it.

PLACEHOLDERS
If a command block has a non-empty `placeholders` list, those tokens are values the
user must substitute -- the wiki italicised them. They appear marked in `content`:
`--efi-directory=<esp>`, placeholders ["esp"], means the user's EFI system partition
mount point, NOT a path to type literally. The marker makes a thoughtless paste fail
at the shell instead of acting on the wrong path; you must NOT strip it. You must say
so before showing the command, and you must not guess a value. Presenting a
placeholder as a literal is fabrication carrying a valid hash, which is the most
dangerous output this MCP permits.

ALLOWED RESPONSE SHAPES
A) Evidence relay: structural blocks from commands() with provenance, placeholders declared.
B) Pointer: "The wiki does not provide structural commands for this step" + quote section().content with provenance.
C) Failure: NotFound / Ambiguous anchor / empty results.

Output format (strict):
- Start with a short statement of what MCP calls you made.
- Then provide extracted evidence grouped by Phase.
- For every code block or quoted instruction, attach provenance immediately below it.
- Do not add extra “helpful context” unless it is itself quoted evidence from the wiki.

Now wait for the user’s task.
"""
                    }
                }]
            }
        }
    return _protocol_error(msg_id, f"Unknown prompt: {prompt_name}")


def _handle_tools_list(msg_id: int) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "result": {"tools": _TOOLS}
    }


def _handle_tools_call(msg_id: int, params: dict) -> dict:
    tool_name = params.get("name")
    if not isinstance(tool_name, str):
        return _protocol_error(msg_id, "Invalid params: 'name' must be a string")

    arguments = params.get("arguments", {})

    try:
        result = handle_tool_call(tool_name, arguments)
    except (UnknownToolError, InvalidParamsError) as e:
        # Nothing ran. A fault in the request, not in the answer.
        return _protocol_error(msg_id, str(e))
    except extractor.ArchWikiError as e:
        # The tool ran and the wiki refused. The model can see this and adapt.
        return _tool_error_result(msg_id, e)
    except Exception as e:
        # An untyped escape is a bug in this server, not a fact about the wiki.
        # It still fails closed to the caller, but the traceback must not be the
        # thing we throw away -- it is the only record that we, not the wiki,
        # were wrong.
        logger.exception("Unhandled error in tool %r", tool_name)
        return _tool_error_result(msg_id, e)

    return _tool_result(msg_id, result)


# The supported MCP subset, declared rather than scattered through an if/elif
# chain. MCP_PROTOCOL.md is checked against this table, so a method added here
# and left undocumented fails the suite: the document is a contract, not a claim.
# Handlers that take no params are called with the id alone.
_METHOD_DISPATCH = {
    "initialize": lambda msg_id, params: _handle_initialize(msg_id),
    "prompts/list": lambda msg_id, params: _handle_prompts_list(msg_id),
    "prompts/get": lambda msg_id, params: _handle_prompts_get(msg_id, params),
    "tools/list": lambda msg_id, params: _handle_tools_list(msg_id),
    "tools/call": lambda msg_id, params: _handle_tools_call(msg_id, params),
}


def run_mcp_server():
    """Run as MCP server - JSON-RPC over stdio."""
    for line in sys.stdin:
        # Rebound per line. Carried over, a parse failure would answer with the
        # id of the previous -- already answered -- request, and a client keyed
        # on id would see that result overwritten by an error. JSON-RPC 2.0
        # requires a null id when the request id cannot be determined.
        msg_id = None
        try:
            try:
                message = json.loads(line)
            except json.JSONDecodeError as e:
                # -32700, not -32603. The line is the client's, and the fault is
                # in it; answering "Internal error" makes the server confess to a
                # bug that belongs to the request -- the conflation isError and
                # -32602 exist to end, one layer further down.
                _send_response(_protocol_error(None, f"Parse error: {e}", code=-32700))
                continue

            if not isinstance(message, dict):
                # Valid JSON, invalid request. `42` parses, and message.get() then
                # raised AttributeError into the catch-all below, which answered
                # -32603 Internal error -- us confessing to the caller's mistake.
                _send_response(
                    _protocol_error(None, "Invalid Request: not a JSON-RPC object", code=-32600)
                )
                continue

            # A notification is a message with NO id member, and expects no reply --
            # the client's notifications/initialized after the handshake. `"id": null`
            # is something else: a request carrying a null id, which JSON-RPC says to
            # answer (with a null id). Testing `msg_id is None` conflated the two, so
            # a client that sent an explicit null id was met with silence and waited
            # for a reply that was never coming.
            if "id" not in message:
                continue

            method = message.get("method")
            msg_id = message["id"]

            # `params` is an object by construction. A list reached params.get(),
            # raised AttributeError into the catch-all, and answered -32603 Internal
            # error -- the server confessing to a fault in the request.
            params = message.get("params", {})
            if not isinstance(params, dict):
                _send_response(
                    _protocol_error(msg_id, "Invalid params: 'params' must be an object")
                )
                continue

            handler = _METHOD_DISPATCH.get(method)
            if handler is None:
                _send_response(
                    _protocol_error(msg_id, f"Method not found: {method}", code=-32601)
                )
                continue

            _send_response(handler(msg_id, params))
        except Exception as e:
            # Genuinely ours: nothing above this point is the caller's fault.
            logger.exception("Unhandled error handling request %r", msg_id)
            _send_response(
                _protocol_error(msg_id, f"Internal error: {str(e)}", code=-32603)
            )
