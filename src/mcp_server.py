"""
Arch Wiki MCP Server
Thin wrapper around constitutional extractor - exposes wiki as MCP tools.
"""

import sys
import json
from typing import Optional
from urllib.parse import urlparse
from . import extractor


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


def main():
    """
    Simple CLI for testing MCP tools.
    
    Usage:
        python server.py page GRUB
        python server.py sections Installation_guide
        python server.py section GRUB Installation
        python server.py commands GRUB Installation
    """
    if len(sys.argv) < 2:
        print("Usage: python server.py <tool> <args...>")
        print("\nAvailable tools:")
        print("  page <title_or_url>")
        print("  sections <title_or_url>")
        print("  section <title_or_url> <anchor>")
        print("  commands <title_or_url> [anchor]")
        print("  warnings <title_or_url> [anchor]")
        print("  links <title_or_url> [anchor]")
        sys.exit(1)
    
    tool = sys.argv[1]
    
    # Build arguments dict
    if tool == "page" or tool == "sections":
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
