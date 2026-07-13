"""
Arch Wiki MCP Server
Thin wrapper around constitutional extractor - exposes wiki as MCP tools.
"""

import sys
import json
import logging
import os
import re
import shutil
import subprocess
from dataclasses import asdict
from importlib import metadata
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from arch_wiki_mcp import _DISTRIBUTION, __version__, extractor

# This module, as an installed client must name it.
MODULE = "arch_wiki_mcp.server"

# The name this server answers an `initialize` with. It is the distribution's name
# because they are the same thing -- and it was spelled out twice, so a rename would
# have left the MCP identity behind, which is #19 in a different register.
SERVER_NAME = _DISTRIBUTION

# A registration that does not answer in this long is not one a client will wait for
# either. Unbounded here would hang `--check` forever on a server that starts and
# then says nothing -- the failure mode this command exists to diagnose.
HANDSHAKE_TIMEOUT = 15

# stderr by default, which keeps JSON-RPC on stdout clean.
logger = logging.getLogger(__name__)

# Schema documentation constants
TITLE_DESC = "Page title or URL"
ANCHOR_DESC = "Optional section anchor"

# Declared in the schema and enforced at the boundary from that same declaration,
# so the two cannot drift. `limit` was advertised as an unbounded `number`, which
# promised every client that 1e9 -- or 2.5 -- was a fair thing to ask for.
SEARCH_LIMIT_DEFAULT = 10
SEARCH_LIMIT_MAX = 50


# The parse is a wiki concern, not a protocol one: it is the exact inverse of
# extractor.make_wiki_url() and encodes MediaWiki title semantics. It lives
# there, beside its inverse and the host it validates against. Re-exported
# because every tool below calls it.
extract_title_from_url = extractor.extract_title_from_url


# MCP Tool: search
def tool_search(query: str, limit: int = SEARCH_LIMIT_DEFAULT) -> dict:
    """
    Search Arch Wiki for pages matching query.
    
    Args:
        query: Search query string
        limit: Maximum number of results (default 10)
        
    Returns:
        {
            "results": List[Dict{title, pageid, snippet, url, match}]
        }

    A pointer, never evidence: no revid, no hash, nothing quotable. The exact-title
    match leads when one exists (match: "title"); the rest are the wiki's full-text
    hits in its own order (match: "text"), unranked by us. snippet is plain text and
    may keep the brackets of a token the wiki truncated. [] means the wiki's search
    found nothing -- not that the topic is undocumented under another name.
    """
    results = extractor.search(query, limit)
    return {"results": results}


# MCP Tool: page
def tool_page(title_or_url: str) -> dict:
    """
    Fetch full page with metadata.
    
    Args:
        title_or_url: Page title or wiki URL
        
    Returns:
        {
            "title": str,
            "pageid": int,
            "revid": int,
            "url": str,
            "revision_url": str,
            "revision_wikitext_url": str,
            "wikitext": str,
            "wikitext_hash": str,
            "sections": List[Dict]
        }
    """
    title = extract_title_from_url(title_or_url)
    return extractor.page(title)


# MCP Tool: sections
def tool_sections(title_or_url: str) -> dict:
    """
    List all sections in page with anchors and offsets.
    
    Args:
        title_or_url: Page title or wiki URL
        
    Returns:
        {
            "sections": List[Dict]
        }
    """
    title = extract_title_from_url(title_or_url)
    sections = extractor.sections(title)
    return {"sections": sections}


# MCP Tool: section
def tool_section(title_or_url: str, anchor: str) -> dict:
    """
    Extract single section with full provenance.
    
    Args:
        title_or_url: Page title or wiki URL
        anchor: Section anchor (e.g., "Installation")
        
    Returns:
        {
            "title": str,
            "url": str,
            "revision_url": str,
            "revision_wikitext_url": str,
            "revid": int,
            "timestamp": str or null,
            "section_anchor": str,
            "section_heading": str,
            "extraction_method": str,
            "content": str,
            "content_raw": str,
            "content_hash": str,
            "content_hash_cleaned": str
        }

    content is rendered for quoting: markdown headings, fenced code, resolved links.
    content_raw is the verbatim wikitext slice and is what content_hash covers, so the
    citation stays falsifiable against the wiki. content_hash_cleaned covers content.

    Serialized from the dataclass, so a new field cannot be dropped on the way out:
    hand-listing the keys once shipped `content_hash` attesting text no agent could see.
    """
    title = extract_title_from_url(title_or_url)
    return asdict(extractor.section(title, anchor))


# MCP Tool: commands
def tool_commands(title_or_url: str, anchor: Optional[str] = None) -> dict:
    """
    Extract code blocks from page or section.
    
    Args:
        title_or_url: Page title or wiki URL
        anchor: Optional section anchor
        
    Returns:
        {
            "commands": List[Dict{content, content_raw, content_hash,
                                  content_hash_cleaned, block_type, source_pattern,
                                  language, header, placeholders, source_url,
                                  revision_url, revision_wikitext_url, revid}]
        }

    content is runnable once its placeholders are substituted; those stay marked as
    <esp>. content_raw is the verbatim wikitext payload and is what content_hash covers.
    content_hash_cleaned covers content, so the cleaning step is attested too. Raises on
    a missing page or anchor; returns [] only when the page truly has no code blocks.

    A bodiless {{bc}} contributes no block: an empty command attested by the SHA-256
    of the empty string is evidence for nothing. Text the wiki wrapped in <nowiki> --
    braces, brackets, apostrophes, HTML comments -- reaches content unchanged.
    """
    title = extract_title_from_url(title_or_url)
    commands = extractor.commands(title, anchor)
    return {"commands": commands}


# MCP Tool: warnings
def tool_warnings(title_or_url: str, anchor: Optional[str] = None) -> dict:
    """
    Extract warning templates from page or section.
    
    Args:
        title_or_url: Page title or wiki URL
        anchor: Optional section anchor
        
    Returns:
        {
            "warnings": List[Dict{type, message, message_raw, content_hash,
                                  message_hash_cleaned, source_url, revision_url,
                                  revision_wikitext_url, revid, alias, alias_target,
                                  alias_revid, alias_revision_url}]
        }

    message is readable prose, safe to quote to a user. message_raw is the verbatim
    template body, and content_hash covers that. message_hash_cleaned covers message,
    so the text the agent actually quotes is attested too.

    Fails closed. A translated page writes {{Note (Español)}} or {{Attention}} (a
    redirect to Template:Warning (Français)), so template names are resolved against
    the wiki first. If they cannot be resolved this raises: an English-only subset
    would be an incomplete [] that the agent reads as "the wiki warns of nothing".

    A type learned from such a redirect is not attested by the article's revid, so
    the block carries the redirect that supplied it: alias, alias_target, and
    alias_revid -- the revision of the redirect page itself, which is what moves if
    someone repoints it. All three are null when the template spelled its own type.
    """
    title = extract_title_from_url(title_or_url)
    warnings = extractor.warnings(title, anchor)
    return {"warnings": warnings}


# MCP Tool: links
def tool_links(title_or_url: str, anchor: Optional[str] = None) -> dict:
    """
    Extract internal links from page or section.
    """
    title = extract_title_from_url(title_or_url)
    links = extractor.links(title, anchor)
    return {"links": links}


# MCP Server Implementation
class UnknownToolError(LookupError):
    """
    The client named a tool that does not exist.

    Not an extraction failure: nothing ran, and there is nothing for a model to
    self-correct from. MCP reserves protocol errors for exactly this -- a fault
    in the request rather than in the answer -- so it must not travel as an
    isError result alongside the tools that did run.
    """

    code = "unknown_tool"


_TOOLS = [
    {
        "name": "search",
        "description": (
            "Search Arch Wiki pages: the exact-title match first when one "
            "exists, then the wiki's full-text hits in its own order. A "
            "pointer, never evidence -- results carry no revid and no hash, "
            "and `snippet` is never quotable."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query", "minLength": 1, "pattern": "\\S"},
                "limit": {
                    "type": "integer",
                    "description": f"Max results (default {SEARCH_LIMIT_DEFAULT})",
                    "minimum": 1,
                    "maximum": SEARCH_LIMIT_MAX,
                    "default": SEARCH_LIMIT_DEFAULT,
                }
            },
            "required": ["query"],
            "additionalProperties": False
        }
    },
    {
        "name": "page",
        "description": "Get full page with metadata",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title_or_url": {"type": "string", "description": TITLE_DESC, "minLength": 1, "pattern": "\\S"}
            },
            "required": ["title_or_url"],
            "additionalProperties": False
        }
    },
    {
        "name": "sections",
        "description": "List all sections in page",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title_or_url": {"type": "string", "description": TITLE_DESC, "minLength": 1, "pattern": "\\S"}
            },
            "required": ["title_or_url"],
            "additionalProperties": False
        }
    },
    {
        "name": "section",
        "description": (
            "Get single section with provenance. Returns `content` (rendered for "
            "quoting: markdown headings, fenced code, resolved links) and "
            "`content_raw` (verbatim wikitext). content_hash attests content_raw; "
            "content_hash_cleaned attests content."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "title_or_url": {"type": "string", "description": TITLE_DESC, "minLength": 1, "pattern": "\\S"},
                "anchor": {"type": "string", "description": "Section anchor", "minLength": 1, "pattern": "\\S"}
            },
            "required": ["title_or_url", "anchor"],
            "additionalProperties": False
        }
    },
    {
        "name": "commands",
        "description": "Extract code blocks from page or section",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title_or_url": {"type": "string", "description": TITLE_DESC, "minLength": 1, "pattern": "\\S"},
                "anchor": {"type": "string", "description": ANCHOR_DESC, "minLength": 1, "pattern": "\\S"}
            },
            "required": ["title_or_url"],
            "additionalProperties": False
        }
    },
    {
        "name": "warnings",
        "description": (
            "Extract warning/note/tip templates from page or section, including "
            "localized ones on translated pages ({{Note (Español)}}, {{Attention}}). "
            "Raises rather than returning an incomplete list; [] means the wiki "
            "specifies no warning here. A type derived from a template redirect "
            "carries that redirect (alias, alias_target, alias_revid)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "title_or_url": {"type": "string", "description": TITLE_DESC, "minLength": 1, "pattern": "\\S"},
                "anchor": {"type": "string", "description": ANCHOR_DESC, "minLength": 1, "pattern": "\\S"}
            },
            "required": ["title_or_url"],
            "additionalProperties": False
        }
    },
    {
        "name": "links",
        "description": "Extract internal links from page or section",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title_or_url": {"type": "string", "description": TITLE_DESC, "minLength": 1, "pattern": "\\S"},
                "anchor": {"type": "string", "description": ANCHOR_DESC, "minLength": 1, "pattern": "\\S"}
            },
            "required": ["title_or_url"],
            "additionalProperties": False
        }
    }
]

_INPUT_SCHEMAS = {tool["name"]: tool["inputSchema"] for tool in _TOOLS}


class InvalidParamsError(ValueError):
    """
    The call itself is malformed: a missing argument, a wrong type, a value the
    schema forbids.

    Nothing ran, so this is a protocol error (-32602) and not an isError result
    -- the same class as an unknown tool. Unvalidated, a missing `title_or_url`
    surfaced as a KeyError and reached the agent as `internal_error`: this server
    confessing to a bug that belonged to the caller's request.
    """

    code = "invalid_params"


def _validate_value(tool: str, name: str, value: Any, spec: dict) -> Any:
    """
    Check one argument against the property the schema advertises for it.

    Every rule is read from `spec`, never assumed. Enforcing a rule the schema
    does not declare is the same lie as declaring one the code does not enforce,
    only told in the strict direction: a client that obeyed the advertised schema
    would still be refused, with no way to discover why.
    """
    declared = spec["type"]

    if declared == "string":
        if not isinstance(value, str):
            raise InvalidParamsError(
                f"{tool}.{name} must be a string, got {type(value).__name__}"
            )
        minimum_length = spec.get("minLength")
        if minimum_length is not None and len(value) < minimum_length:
            raise InvalidParamsError(
                f"{tool}.{name} must be at least {minimum_length} character(s), got {value!r}"
            )
        # Declared, not assumed. This checked minLength against value.strip(), so a
        # one-space string was refused although it satisfies the length the schema
        # advertises -- a rule enforced and nowhere stated, which is the same lie as
        # a rule stated and never enforced.
        pattern = spec.get("pattern")
        if pattern is not None and not re.search(pattern, value):
            raise InvalidParamsError(
                f"{tool}.{name} must contain a non-whitespace character, got {value!r}"
            )
        return value

    if declared == "integer":
        # bool is an int subclass in Python, so `limit=true` would otherwise pass
        # an isinstance check and reach the wiki as srlimit=1 -- a silently
        # truncated search that looks like a complete one.
        if isinstance(value, bool) or not isinstance(value, int):
            raise InvalidParamsError(
                f"{tool}.{name} must be an integer, got {type(value).__name__}"
            )
        low, high = spec.get("minimum"), spec.get("maximum")
        if low is not None and value < low:
            raise InvalidParamsError(f"{tool}.{name} must be >= {low}, got {value}")
        if high is not None and value > high:
            raise InvalidParamsError(f"{tool}.{name} must be <= {high}, got {value}")
        return value

    # Our schema declares a type this validator cannot check -- our fault, not the
    # caller's. Raised as InvalidParamsError it would refuse every well-formed call
    # to that tool with -32602, blaming the client for obeying a schema we
    # published: the exact confusion this validation exists to end. Let it escape
    # untyped, so the transport logs it as the server bug it is.
    raise NotImplementedError(
        f"{tool}.{name} declares type {declared!r}, which _validate_value cannot check"
    )


def _validate_arguments(tool: str, arguments: dict) -> dict:
    """
    Check a call against the schema the server advertises for that tool.

    Driven by the declaration rather than restating it, so `tools/list` and the
    runtime cannot disagree -- a schema the code does not honour is a lie told to
    every client that reads it. Defaults declared in the schema are applied here
    too, so the advertised default is the one that actually takes effect.
    """
    if not isinstance(arguments, dict):
        raise InvalidParamsError(f"{tool} arguments must be an object")

    schema = _INPUT_SCHEMAS[tool]
    properties = schema["properties"]

    if not schema.get("additionalProperties", True):
        unknown = sorted(set(arguments) - set(properties))
        if unknown:
            raise InvalidParamsError(
                f"{tool} got unexpected parameter(s): {', '.join(unknown)}"
            )

    missing = sorted(set(schema["required"]) - set(arguments))
    if missing:
        raise InvalidParamsError(f"{tool} is missing required parameter(s): {', '.join(missing)}")

    validated = {
        name: _validate_value(tool, name, value, properties[name])
        for name, value in arguments.items()
    }

    for name, spec in properties.items():
        if name not in validated and "default" in spec:
            validated[name] = spec["default"]

    return validated


_TOOL_DISPATCH = {
    # No fallback: validation applies the schema's declared default, so the
    # schema is the one place the default is stated.
    "search": lambda a: tool_search(a["query"], a["limit"]),
    "page": lambda a: tool_page(a["title_or_url"]),
    "sections": lambda a: tool_sections(a["title_or_url"]),
    "section": lambda a: tool_section(a["title_or_url"], a["anchor"]),
    "commands": lambda a: tool_commands(a["title_or_url"], a.get("anchor")),
    "warnings": lambda a: tool_warnings(a["title_or_url"], a.get("anchor")),
    "links": lambda a: tool_links(a["title_or_url"], a.get("anchor")),
}


def handle_tool_call(tool_name: str, arguments: dict) -> dict:
    """
    Validate a tool call against its declared schema, then route it.

    Raises rather than returning an error dict. Returning one made a failure
    indistinguishable from a result to every caller that did not inspect the
    payload -- and the MCP transport did not, so it shipped failures inside
    successful responses. Failure is now something a caller must handle.

    Validation happens here rather than in each handler: the wiki must never be
    asked a question we already know is malformed, and the lambdas below indexed
    arguments straight, so an omitted one became a KeyError the agent was told
    was our bug.
    """
    try:
        handler = _TOOL_DISPATCH[tool_name]
    except KeyError:
        raise UnknownToolError(f"Unknown tool: {tool_name}") from None

    return handler(_validate_arguments(tool_name, arguments))


def _error_payload(exc: Exception) -> dict:
    """
    The one place a failure is given its wire identity.

    Stated twice, the fallback drifted: the transport labelled an unclassified
    exception `internal_error` while the CLI labelled the same one `unknown_tool`.
    Typed errors carry their own code; only a genuinely untyped escape -- a bug
    in this server rather than a fact about the wiki -- falls back.
    """
    return {"error": str(exc), "code": getattr(exc, "code", "internal_error")}


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


if __name__ == "__main__":
    main()
