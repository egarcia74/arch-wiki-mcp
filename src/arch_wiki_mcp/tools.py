"""
The wiki tools and the schema that validates every call to them.

Each `tool_*` is a thin turn of an extractor result into the dict a client
receives. Around them sits the one thing that must not drift: `_TOOLS` is the
schema the server advertises, and `_validate_arguments` enforces exactly that
schema at the boundary -- a rule stated to a client and a rule imposed on it,
read from the same declaration so they cannot disagree. protocol.py serves these
over JSON-RPC; cli.py serves the same ones over argv.
"""

import re
from dataclasses import asdict
from typing import Any, Optional

from arch_wiki_mcp import extractor

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
