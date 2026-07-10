"""
Arch Wiki MCP Server
Thin wrapper around constitutional extractor - exposes wiki as MCP tools.
"""

import sys
import os
import json
from dataclasses import asdict
from typing import Any, Dict, Optional
from urllib.parse import urlparse

# Allow `python3 src/mcp_server.py` to resolve the `src` package. Importing via
# the package (not a bare `import extractor`) keeps a single module identity --
# a bare import loads a second copy under a different sys.modules key.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src import extractor

# Schema documentation constants
TITLE_DESC = "Page title or URL"
ANCHOR_DESC = "Optional section anchor"


def extract_title_from_url(title_or_url: str) -> str:
    """
    Extract page title from URL or return title as-is.
    
    Handles:
    - Plain titles: "GRUB" -> "GRUB"
    - URLs: "https://wiki.archlinux.org/title/GRUB" -> "GRUB"
    - Anchor URLs: "https://wiki.archlinux.org/title/GRUB#Installation" -> "GRUB"
    """
    if title_or_url.startswith("http://") or title_or_url.startswith("https://"):
        parsed = urlparse(title_or_url)
        # Extract title from /title/PageName or /index.php?title=PageName
        if "/title/" in parsed.path:
            return parsed.path.split("/title/")[1].split("#")[0]
        elif "title=" in parsed.query:
            return parsed.query.split("title=")[1].split("&")[0]
        else:
            raise ValueError(f"Cannot extract title from URL: {title_or_url}")
    else:
        # Plain title
        return title_or_url


# MCP Tool: search
def tool_search(query: str, limit: int = 10) -> dict:
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
                                  language, header, placeholders, source_url, revid}]
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
                                  message_hash_cleaned, source_url, revid,
                                  alias, alias_target, alias_revid}]
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
def handle_tool_call(tool_name: str, arguments: dict) -> dict:
    """
    Route tool call to appropriate handler.
    
    Returns result dict or error dict.
    """
    try:
        if tool_name == "search":
            return tool_search(
                arguments["query"],
                arguments.get("limit", 10)
            )
        
        elif tool_name == "page":
            return tool_page(arguments["title_or_url"])
        
        elif tool_name == "sections":
            return tool_sections(arguments["title_or_url"])
        
        elif tool_name == "section":
            return tool_section(
                arguments["title_or_url"],
                arguments["anchor"]
            )
        
        elif tool_name == "commands":
            return tool_commands(
                arguments["title_or_url"],
                arguments.get("anchor")
            )
        
        elif tool_name == "warnings":
            return tool_warnings(
                arguments["title_or_url"],
                arguments.get("anchor")
            )
        
        elif tool_name == "links":
            return tool_links(
                arguments["title_or_url"],
                arguments.get("anchor")
            )
        
        else:
            return {"error": f"Unknown tool: {tool_name}"}
    
    except ValueError as e:
        return {"error": str(e)}
    
    except Exception as e:
        return {"error": f"{type(e).__name__}: {str(e)}"}


def _send_response(response: dict):
    """Send JSON-RPC response to stdout."""
    print(json.dumps(response), flush=True)


def _handle_initialize(msg_id: int) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "result": {
            "protocolVersion": "2024-11-05",
            "serverInfo": {"name": "arch-wiki-mcp", "version": "1.7.0"},
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
   - source_url (with anchor if applicable)
   - revid
   - content_hash
   - extraction_method (if provided)
4) If commands() returns an empty list, you MUST NOT infer a pacman command from prose.
   - Instead: call section() and quote the exact sentence(s) that describe what to do.
5) If a page/section is missing, you must fail closed:
   - return NotFound / empty result
   - do not suggest “closest match”
6) You must surface warnings and notes returned by warnings() before presenting related commands.
7) You must not merge multiple pages into a “unified guide” unless the user explicitly requests multi-page output AND you preserve page-level provenance per fragment.

SEARCH RESULTS ARE POINTERS, NOT EVIDENCE
search() is the one tool whose output carries no revid and no hash. It tells you which
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
"Template:<alias>" at alias_revid -- that pair names one page at one revision -- and say
separately that it redirects to alias_target. Never cite alias_target at alias_revid:
that revision belongs to the redirect, not to its destination, so the pair names no
page that exists. Never present a redirect-derived WARNING as though the article itself
declared it.

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
    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "error": {"code": -32602, "message": f"Unknown prompt: {prompt_name}"}
    }


def _handle_tools_list(msg_id: int) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "result": {
            "tools": [
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
                            "query": {"type": "string", "description": "Search query"},
                            "limit": {"type": "number", "description": "Max results (default 10)"}
                        },
                        "required": ["query"]
                    }
                },
                {
                    "name": "page",
                    "description": "Get full page with metadata",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "title_or_url": {"type": "string", "description": TITLE_DESC}
                        },
                        "required": ["title_or_url"]
                    }
                },
                {
                    "name": "sections",
                    "description": "List all sections in page",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "title_or_url": {"type": "string", "description": TITLE_DESC}
                        },
                        "required": ["title_or_url"]
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
                            "title_or_url": {"type": "string", "description": TITLE_DESC},
                            "anchor": {"type": "string", "description": "Section anchor"}
                        },
                        "required": ["title_or_url", "anchor"]
                    }
                },
                {
                    "name": "commands",
                    "description": "Extract code blocks from page or section",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "title_or_url": {"type": "string", "description": TITLE_DESC},
                            "anchor": {"type": "string", "description": ANCHOR_DESC}
                        },
                        "required": ["title_or_url"]
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
                            "title_or_url": {"type": "string", "description": TITLE_DESC},
                            "anchor": {"type": "string", "description": ANCHOR_DESC}
                        },
                        "required": ["title_or_url"]
                    }
                },
                {
                    "name": "links",
                    "description": "Extract internal links from page or section",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "title_or_url": {"type": "string", "description": TITLE_DESC},
                            "anchor": {"type": "string", "description": ANCHOR_DESC}
                        },
                        "required": ["title_or_url"]
                    }
                }
            ]
        }
    }


def _handle_tools_call(msg_id: int, params: dict) -> dict:
    tool_name = params.get("name")
    if not isinstance(tool_name, str):
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {"code": -32602, "message": "Invalid params: 'name' must be a string"}
        }
    arguments = params.get("arguments", {})
    result = handle_tool_call(tool_name, arguments)
    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "result": {
            "content": [{
                "type": "text",
                "text": json.dumps(result, indent=2, ensure_ascii=False)
            }]
        }
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
            message = json.loads(line)
            method = message.get("method")
            params = message.get("params", {})
            msg_id = message.get("id")
            
            if msg_id is None:
                continue
                
            if method == "initialize":
                _send_response(_handle_initialize(msg_id))
            elif method == "prompts/list":
                _send_response(_handle_prompts_list(msg_id))
            elif method == "prompts/get":
                _send_response(_handle_prompts_get(msg_id, params))
            elif method == "tools/list":
                _send_response(_handle_tools_list(msg_id))
            elif method == "tools/call":
                _send_response(_handle_tools_call(msg_id, params))
            else:
                _send_response({
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {"code": -32601, "message": f"Method not found: {method}"}
                })
        except Exception as e:
            _send_response({
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {"code": -32603, "message": f"Internal error: {str(e)}"}
            })


def main():
    """
    Entry point - detect MCP mode vs CLI mode.
    
    MCP mode: Running via stdio (no args)
    CLI mode: Direct invocation with args
    """
    # If no args, assume MCP stdio mode
    if len(sys.argv) == 1 or (len(sys.argv) == 2 and sys.argv[1] == "--stdio"):
        run_mcp_server()
        return
    
    # Otherwise, CLI mode for testing
    if len(sys.argv) < 2:
        print("Usage: python server.py <tool> <args...>")
        print("\nAvailable tools:")
        print("  search <query> [limit]")
        print("  page <title_or_url>")
        print("  sections <title_or_url>")
        print("  section <title_or_url> <anchor>")
        print("  commands <title_or_url> [anchor]")
        print("  warnings <title_or_url> [anchor]")
        print("  links <title_or_url> [anchor]")
        print("\nOr run as MCP server:")
        print("  python server.py --stdio")
        sys.exit(1)
    
    tool = sys.argv[1]
    
    # Build arguments dict
    arguments: Dict[str, Any]
    if tool == "search":
        arguments = {"query": sys.argv[2]}
        if len(sys.argv) > 3:
            arguments["limit"] = int(sys.argv[3])
    elif tool == "page" or tool == "sections":
        arguments = {"title_or_url": sys.argv[2]}
    elif tool == "section":
        arguments = {"title_or_url": sys.argv[2], "anchor": sys.argv[3]}
    elif tool in ["commands", "warnings", "links"]:
        arguments = {"title_or_url": sys.argv[2]}
        if len(sys.argv) > 3:
            arguments["anchor"] = sys.argv[3]
    else:
        print(f"Unknown tool: {tool}")
        sys.exit(1)
    
    # Call tool
    result = handle_tool_call(tool, arguments)
    
    # Print result
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
