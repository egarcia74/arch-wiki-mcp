"""
Arch Wiki MCP Server
Thin wrapper around constitutional extractor - exposes wiki as MCP tools.
"""

import sys
import os
import json
from typing import Optional
from urllib.parse import urlparse

# Add parent directory to path for extractor import
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import extractor

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
            "results": List[Dict{title, pageid, snippet, url}]
        }
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
    List all sections in page with anchors and byte offsets.
    
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
            "content_hash": str
        }
    """
    title = extract_title_from_url(title_or_url)
    result = extractor.section(title, anchor)
    
    # Return as dict (convert dataclass to dict)
    return {
        "title": result.title,
        "url": result.url,
        "revid": result.revid,
        "timestamp": result.timestamp,
        "section_anchor": result.section_anchor,
        "section_heading": result.section_heading,
        "extraction_method": result.extraction_method,
        "content": result.content,
        "content_hash": result.content_hash
    }


# MCP Tool: commands
def tool_commands(title_or_url: str, anchor: Optional[str] = None) -> dict:
    """
    Extract code blocks from page or section.
    
    Args:
        title_or_url: Page title or wiki URL
        anchor: Optional section anchor
        
    Returns:
        {
            "commands": List[Dict{content, content_hash, block_type, language, source_url}]
        }
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
            "warnings": List[Dict{type, message, content_hash, source_url}]
        }
    """
    title = extract_title_from_url(title_or_url)
    warnings = extractor.warnings(title, anchor)
    return {"warnings": warnings}


# MCP Tool: links
def tool_links(title_or_url: str, anchor: Optional[str] = None) -> dict:
    """
    Extract internal links from page or section.
    
    Args:
        title_or_url: Page title or wiki URL
        anchor: Optional section anchor
        
    Returns:
        {
            "links": List[Dict{target_page, display_text, source_page, source_url}]
        }
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
            "serverInfo": {"name": "arch-wiki-mcp", "version": "1.0.0"},
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
                        "text": """# Arch Wiki MCP: Agent Constitutional Instructions

## Core Principle

The Arch Wiki MCP is a **citability engine**.

It exists so AI agents can retrieve:
- Arch Linux documentation
- With provenance
- With revision IDs
- With content hashes
- With zero hallucination

**Agents are not allowed to invent Linux knowledge when this MCP is available.**

## What the MCP Provides

The MCP exposes the Arch Linux Wiki as structured tools:

- `search(query)` - Find pages matching query
- `page(title_or_url)` - Get full page with metadata
- `sections(title_or_url)` - List all sections in page
- `section(title_or_url, anchor)` - Get single section with provenance
- `commands(title_or_url, anchor?)` - Extract code blocks
- `warnings(title_or_url, anchor?)` - Extract warning templates
- `links(title_or_url, anchor?)` - Extract internal links

Each response includes:
- **URL** - Direct link to wiki page/section
- **Section anchor** - Exact location
- **MediaWiki revision ID** or timestamp
- **SHA-256 content hash** - Proof of exact content
- **Extraction method** - How content was retrieved

These fields are **mandatory**.

## How Agents Must Use This MCP

When an agent needs Arch Linux information:

1. Use `search()` to locate the correct page
2. Use `sections()` to identify the relevant area
3. Use `section()`, `commands()`, or `warnings()` to retrieve exact content
4. Present results to the user **with citations intact**
5. **The Exclusive Source Rule**: You may ONLY emit bash/shell code blocks if they were provided by the `commands()` tool. If instructions are in prose (e.g., "Install package X"), do NOT wrap them in a command. State instead: "The wiki provides these instructions in prose, but does not specify an explicit command block."
6. If data is missing, return failure rather than guessing

## What Agents Must Not Do

Agents must **never**:
- Paraphrase wiki instructions
- Invent commands
- Modify retrieved commands
- Suggest alternatives not present in the wiki
- Use training data as a fallback
- Combine pages unless explicitly requested

If the MCP does not return content, the correct response is:
> "The Arch Wiki does not provide this information."

## Proper Usage Example

**User:** "How do I install GRUB?"

**Agent:**
1. Call `search("GRUB")`
2. Call `sections("GRUB")`
3. Call `commands("GRUB", "Installation")`
4. Present:

> According to the Arch Wiki:  
> https://wiki.archlinux.org/title/GRUB#Installation  
> (revision 858930, hash 2cf8a5d99d…)
>
> ```bash
> pacman -S grub
> ```
>
> **Warning:** The wiki states: "It is important to install the GRUB package for the correct architecture."

## Failure Example

**User:** "How do I configure my GPU passthrough?"

If `search()` or `sections()` returns nothing relevant, the agent must say:

> "The Arch Wiki does not provide this information."

**Not:**
- Guesses
- Tutorials
- Generic Linux advice

## Final Rule

**You are not a Linux assistant.**  
**You are an evidence relay.**

If the wiki does not say it, neither do you.

---

This is the **truth perimeter**. Respect it.
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
                    "description": "Search Arch Wiki pages",
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
                    "description": "Get single section with provenance",
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
                    "description": "Extract warning templates from page or section",
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
                "id": msg_id if 'msg_id' in locals() else None,
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
