#!/usr/bin/env python3
"""
Arch Wiki Constitutional Extractor
Deterministic, hash-stable extraction of wiki content with full provenance.
"""

import hashlib
import re
import unicodedata
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Tuple
from urllib.request import urlopen, Request
from urllib.parse import urlencode
import json

API_ENDPOINT = "https://wiki.archlinux.org/api.php"
USER_AGENT = "ArchWikiMCP/1.0 (Constitutional Extractor; +https://github.com/user/arch-wiki-mcp)"


@dataclass
class WikiSection:
    """Section metadata from MediaWiki parse response."""
    line: str  # Section heading text
    anchor: str  # URL anchor
    level: str  # Heading level (2, 3, 4...)
    toclevel: int  # Table of contents level
    number: str  # Section number (e.g., "2.1")
    index: str  # Section index
    byteoffset: int  # Byte offset in wikitext
    fromtitle: str  # Source page title
    link_anchor: str  # Link anchor (may differ from anchor)


@dataclass
class ExtractedBlock:
    """Constitutional artifact: extracted content with full provenance."""
    title: str
    url: str
    revid: int
    timestamp: Optional[str]  # Fallback if revid unavailable
    section_anchor: Optional[str]
    section_heading: Optional[str]
    extraction_method: str
    content: str
    content_hash: str  # SHA-256 of NFC-normalized content, whitespace preserved


@dataclass
class CodeBlock:
    """Extracted code block with metadata."""
    content: str
    content_hash: str
    block_type: str  # "preformatted", "pre_tag", "code_tag"
    language: Optional[str]  # Language hint if detectable


@dataclass
class WarningBlock:
    """Extracted warning/note/tip template."""
    type: str  # WARNING, NOTE, TIP, CAUTION
    message: str
    content_hash: str


@dataclass
class InternalLink:
    """Extracted internal wiki link."""
    target_page: str
    display_text: Optional[str]
    source_page: str


def hash_content(text: str) -> str:
    """
    Hash content with constitutional requirements:
    - Unicode NFC normalization
    - Whitespace preserved
    - SHA-256
    """
    normalized = unicodedata.normalize("NFC", text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def fetch_wiki_parse(page_title: str, timeout: int = 30) -> Dict:
    """
    Fetch page wikitext, sections, and revision ID from MediaWiki API.
    
    Args:
        page_title: Wiki page title (e.g., "GRUB" or "Installation_guide")
        timeout: Request timeout in seconds
        
    Returns:
        MediaWiki parse API response dict
        
    Raises:
        ValueError: If page not found or API error
    """
    params = {
        "action": "parse",
        "page": page_title,
        "prop": "wikitext|sections|revid",
        "format": "json",
    }
    url = f"{API_ENDPOINT}?{urlencode(params)}"
    
    request = Request(url, headers={"User-Agent": USER_AGENT})
    
    with urlopen(request, timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8"))
    
    if "error" in data:
        raise ValueError(f"API Error: {data['error'].get('info', data['error'])}")
    
    if "parse" not in data:
        raise ValueError(f"Unexpected API response format: {data}")
    
    parse_data = data["parse"]
    # Normalize keys for constitutional code style
    if "sections" in parse_data:
        for section in parse_data["sections"]:
            if "linkAnchor" in section:
                section["link_anchor"] = section.pop("linkAnchor")
    
    return parse_data


def extract_section_wikitext(
    wikitext: str,
    section_start: int,
    section_end: Optional[int]
) -> str:
    """
    Extract section content from wikitext using byte offsets.
    
    MediaWiki byte offsets are in UTF-8 bytes, not characters.
    """
    wikitext_bytes = wikitext.encode("utf-8")
    
    if section_end is not None:
        section_bytes = wikitext_bytes[section_start:section_end]
    else:
        section_bytes = wikitext_bytes[section_start:]
    
    return section_bytes.decode("utf-8")


def parse_templates(wikitext: str) -> List[WarningBlock]:
    """
    Parse MediaWiki templates for warnings, notes, tips.
    
    Supports:
    - {{Warning|message}}
    - {{Note|message}}
    - {{Tip|message}}
    - {{Caution|message}}
    
    Multi-line templates are supported.
    """
    warnings = []
    
    # Match {{TemplateName|content}} including multi-line
    pattern = r'\{\{(Warning|Note|Tip|Caution)\s*\|\s*([^}]+)\}\}'
    
    for match in re.finditer(pattern, wikitext, re.IGNORECASE | re.DOTALL):
        template_type = match.group(1).upper()
        message = match.group(2).strip()
        
        warnings.append(WarningBlock(
            type=template_type,
            message=message,
            content_hash=hash_content(message)
        ))
    
    return warnings


def _extract_indented_blocks(lines: List[str]) -> List[CodeBlock]:
    """Helper to extract leading-space preformatted blocks."""
    blocks, current = [], []
    for line in lines:
        if line.startswith(" ") and not line.strip().startswith("*"):
            current.append(line[1:])
        elif current:
            blocks.append(CodeBlock("\n".join(current), hash_content("\n".join(current)), "preformatted", None))
            current = []
    if current:
        blocks.append(CodeBlock("\n".join(current), hash_content("\n".join(current)), "preformatted", None))
    return blocks

def _extract_shell_blocks(lines: List[str]) -> List[CodeBlock]:
    """Helper to extract shell prompt blocks (# or $)."""
    blocks, current = [], []
    for line in lines:
        s = line.strip()
        if s.startswith("#") or s.startswith("$"):
            current.append(s)
        elif current:
            if current[0].startswith("# ") or current[0].startswith("$ "):
                c = "\n".join(current)
                blocks.append(CodeBlock(c, hash_content(c), "shell", "bash"))
            current = []
    if current and (current[0].startswith("# ") or current[0].startswith("$ ")):
        c = "\n".join(current)
        blocks.append(CodeBlock(c, hash_content(c), "shell", "bash"))
    return blocks

def parse_code_blocks(wikitext: str) -> List[CodeBlock]:
    """
    Parse code blocks from wikitext using multiple patterns.
    
    Patterns:
    1. Leading-space preformatted blocks (baseline)
    2. Shell prompt blocks (lines starting with # or $)
    3. <pre>...</pre> blocks
    4. <code>...</code> inline (if multi-line)
    
    Returns list of code blocks with hashes.
    """
    lines = wikitext.split("\n")
    code_blocks = _extract_indented_blocks(lines)
    code_blocks.extend(_extract_shell_blocks(lines))
    
    # Pattern 3: <pre>...</pre> blocks
    pre_pattern = r'<pre>(.*?)</pre>'
    for match in re.finditer(pre_pattern, wikitext, re.DOTALL):
        content = match.group(1).strip()
        code_blocks.append(CodeBlock(content, hash_content(content), "pre_tag", None))
    
    # Pattern 4: <code>...</code> blocks (only if multi-line)
    code_pattern = r'<code>(.*?)</code>'
    for match in re.finditer(code_pattern, wikitext, re.DOTALL):
        content = match.group(1).strip()
        if "\n" in content:
            code_blocks.append(CodeBlock(content, hash_content(content), "code_tag", None))
    
    return code_blocks


def parse_internal_links(wikitext: str, source_page: str) -> List[InternalLink]:
    """
    Parse internal wiki links from wikitext.
    
    Patterns:
    - [[Target]]
    - [[Target|Display Text]]
    
    Returns list of internal links with source/target/display.
    """
    links = []
    
    # Match [[Target]] or [[Target|Display]]
    pattern = r'\[\[([^\]|]+)(?:\|([^\]]+))?\]\]'
    
    for match in re.finditer(pattern, wikitext):
        target = match.group(1).strip()
        display = match.group(2).strip() if match.group(2) else None
        
        links.append(InternalLink(
            target_page=target,
            display_text=display,
            source_page=source_page
        ))
    
    return links


def search(query: str, limit: int = 10, timeout: int = 30) -> List[Dict]:
    """
    MCP Tool: Search Arch Wiki using MediaWiki search API.
    
    Args:
        query: Search query string
        limit: Maximum number of results (default 10)
        timeout: Request timeout in seconds
        
    Returns:
        List of search results:
        [{
            "title": str,
            "pageid": int,
            "snippet": str,  # HTML snippet with highlights
            "url": str
        }]
    
    No ranking, no interpretation. Just wiki's search results as-is.
    """
    params = {
        "action": "query",
        "list": "search",
        "srsearch": query,
        "srlimit": limit,
        "format": "json",
    }
    url = f"{API_ENDPOINT}?{urlencode(params)}"
    
    request = Request(url, headers={"User-Agent": USER_AGENT})
    
    with urlopen(request, timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8"))
    
    if "error" in data:
        raise ValueError(f"Search API Error: {data['error'].get('info', data['error'])}")
    
    if "query" not in data or "search" not in data["query"]:
        raise ValueError(f"Unexpected search API response: {data}")
    
    results = []
    for item in data["query"]["search"]:
        results.append({
            "title": item["title"],
            "pageid": item["pageid"],
            "snippet": item.get("snippet", ""),
            "url": f"https://wiki.archlinux.org/title/{item['title'].replace(' ', '_')}"
        })
    
    return results


def page(title: str) -> Dict:
    """
    MCP Tool: Fetch full page with metadata.
    
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
    parse_data = fetch_wiki_parse(title)
    wikitext = parse_data["wikitext"]["*"]
    
    return {
        "title": parse_data["title"],
        "pageid": parse_data["pageid"],
        "revid": parse_data["revid"],
        "url": f"https://wiki.archlinux.org/title/{title}",
        "wikitext": wikitext,
        "wikitext_hash": hash_content(wikitext),
        "sections": [asdict(WikiSection(**s)) for s in parse_data["sections"]]
    }


def sections(title: str) -> List[Dict]:
    """
    MCP Tool: Return section list with anchors and byte offsets.
    
    Returns list of sections with metadata.
    """
    parse_data = fetch_wiki_parse(title)
    return [asdict(WikiSection(**s)) for s in parse_data["sections"]]


def section(title: str, anchor: str) -> ExtractedBlock:
    """
    MCP Tool: Extract single section by anchor with full provenance.
    
    Returns ExtractedBlock with section content and hash.
    """
    parse_data = fetch_wiki_parse(title)
    wikitext = parse_data["wikitext"]["*"]
    section_list = parse_data["sections"]
    
    # Find section by anchor
    target_section = None
    next_section_offset = None
    
    for i, sect in enumerate(section_list):
        if sect["anchor"] == anchor:
            target_section = sect
            if i + 1 < len(section_list):
                next_section_offset = section_list[i + 1]["byteoffset"]
            break
    
    if target_section is None:
        raise ValueError(f"Section with anchor '{anchor}' not found in page '{title}'")
    
    # Extract section wikitext
    content = extract_section_wikitext(
        wikitext,
        target_section["byteoffset"],
        next_section_offset
    )
    
    return ExtractedBlock(
        title=parse_data["title"],
        url=f"https://wiki.archlinux.org/title/{title}#{anchor}",
        revid=parse_data["revid"],
        timestamp=None,
        section_anchor=anchor,
        section_heading=target_section["line"],
        extraction_method="wikitext_byte_offset",
        content=content,
        content_hash=hash_content(content)
    )


def commands(title: str, anchor: Optional[str] = None) -> List[Dict]:
    """
    MCP Tool: Extract code blocks from page or section.
    
    Returns list of CodeBlock dicts with content and hashes.
    """
    if anchor:
        extracted = section(title, anchor)
        wikitext = extracted.content
        url_base = extracted.url
    else:
        page_data = page(title)
        wikitext = page_data["wikitext"]
        url_base = page_data["url"]
    
    blocks = parse_code_blocks(wikitext)
    
    return [
        {
            "content": block.content,
            "content_hash": block.content_hash,
            "block_type": block.block_type,
            "language": block.language,
            "source_url": url_base
        }
        for block in blocks
    ]


def warnings(title: str, anchor: Optional[str] = None) -> List[Dict]:
    """
    MCP Tool: Extract warning templates from page or section.
    
    Returns list of WarningBlock dicts.
    """
    if anchor:
        extracted = section(title, anchor)
        wikitext = extracted.content
        url_base = extracted.url
    else:
        page_data = page(title)
        wikitext = page_data["wikitext"]
        url_base = page_data["url"]
    
    warning_blocks = parse_templates(wikitext)
    
    return [
        {
            "type": w.type,
            "message": w.message,
            "content_hash": w.content_hash,
            "source_url": url_base
        }
        for w in warning_blocks
    ]


def links(title: str, anchor: Optional[str] = None) -> List[Dict]:
    """
    MCP Tool: Extract internal links from page or section.
    
    Returns list of InternalLink dicts.
    """
    if anchor:
        extracted = section(title, anchor)
        wikitext = extracted.content
        url_base = extracted.url
    else:
        page_data = page(title)
        wikitext = page_data["wikitext"]
        url_base = page_data["url"]
    
    link_list = parse_internal_links(wikitext, title)
    
    return [
        {
            "target_page": link.target_page,
            "display_text": link.display_text,
            "source_page": link.source_page,
            "source_url": url_base
        }
        for link in link_list
    ]


if __name__ == "__main__":
    # Simple CLI test
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python extractor.py <page_title> [section_anchor]")
        sys.exit(1)
    
    title = sys.argv[1]
    anchor = sys.argv[2] if len(sys.argv) > 2 else None
    
    print(f"Fetching: {title}" + (f" § {anchor}" if anchor else ""))
    print("=" * 80)
    
    if anchor:
        result = section(title, anchor)
        print(f"Title: {result.title}")
        print(f"URL: {result.url}")
        print(f"Revision: {result.revid}")
        print(f"Section: {result.section_heading}")
        print(f"Hash: {result.content_hash}")
        print(f"\nContent ({len(result.content)} chars):")
        print(result.content[:500])
    else:
        result = page(title)
        print(f"Title: {result['title']}")
        print(f"URL: {result['url']}")
        print(f"Revision: {result['revid']}")
        print(f"Sections: {len(result['sections'])}")
        print(f"Wikitext hash: {result['wikitext_hash']}")
