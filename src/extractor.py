#!/usr/bin/env python3
"""
Arch Wiki Constitutional Extractor
Deterministic, hash-stable extraction of wiki content with full provenance.
"""

import hashlib
import re
import unicodedata
from dataclasses import dataclass, asdict
from functools import lru_cache
from typing import Dict, List, Optional, Tuple
from urllib.request import urlopen, Request
from urllib.parse import urlencode, quote
import json
import os

API_ENDPOINT = "https://wiki.archlinux.org/api.php"
USER_AGENT = "ArchWikiMCP/1.0 (Constitutional Extractor; +https://github.com/user/arch-wiki-mcp)"


@dataclass
class WikiSection:
    """Section metadata from MediaWiki parse response."""
    line: str = ""  # Section heading text
    anchor: str = ""  # URL anchor
    level: str = "1"  # Heading level
    toclevel: int = 1
    number: str = ""
    index: str = ""
    byteoffset: int = 0
    fromtitle: str = ""
    link_anchor: str = ""


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
    block_type: str  # "preformatted", "pre_tag", "code_tag", "shell"
    source_pattern: str  # e.g., "indented_block", "fenced_tag", "shell_heuristic"
    language: Optional[str] = None
    revid: Optional[int] = None


@dataclass
class WarningBlock:
    """Extracted warning/note/tip template."""
    type: str  # WARNING, NOTE, TIP, CAUTION
    message: str
    content_hash: str
    revid: Optional[int] = None


@dataclass
class InternalLink:
    """Extracted internal wiki link."""
    target_page: str
    display_text: Optional[str]
    source_page: str


def make_wiki_url(title: str, anchor: Optional[str] = None) -> str:
    """Safely construct an Arch Wiki URL."""
    encoded_title = quote(title.replace(" ", "_"), safe=":/#")
    url = f"https://wiki.archlinux.org/title/{encoded_title}"
    if anchor:
        url += f"#{quote(anchor, safe=':/#')}"
    return url


def hash_content(text: str) -> str:
    """
    Hash content with constitutional requirements:
    - Unicode NFC normalization
    - Whitespace preserved
    - SHA-256
    """
    normalized = unicodedata.normalize("NFC", text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def fixture_filename(action: str, key: str) -> str:
    """
    Filesystem name for a recorded API response.

    The fixture recorder, the offline fetcher, and the tests must agree on this
    mapping exactly, or recorded fixtures become unfindable. One definition.
    """
    safe_key = "".join(c if c.isalnum() else "_" for c in key)
    return f"{action}_{safe_key}.json"


@lru_cache(maxsize=None)
def _read_fixture(fixture_path: str) -> str:
    """Fixtures are immutable within a run; read each one once."""
    if not os.path.exists(fixture_path):
        raise FileNotFoundError(f"Offline mode enabled but fixture missing: {fixture_path}")
    with open(fixture_path, "r") as f:
        return f.read()


def _fetch_offline(params: Dict) -> Dict:
    """Retrieve API response from local fixtures for offline testing."""
    fixtures_dir = os.environ.get("ARCHWIKI_FIXTURES", "tests/fixtures")
    action = params.get("action", "unknown")
    key = params.get("page", "unknown") if action == "parse" else params.get("srsearch", "unknown")

    fixture_path = os.path.join(fixtures_dir, fixture_filename(action, key))
    return json.loads(_read_fixture(fixture_path))


def _fetch(params: Dict, timeout: int = 30) -> Dict:
    """Single entry point for API access. ARCHWIKI_OFFLINE swaps in fixtures."""
    if os.environ.get("ARCHWIKI_OFFLINE"):
        return _fetch_offline(params)

    url = f"{API_ENDPOINT}?{urlencode(params)}"
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_wiki_parse(page_title: str, timeout: int = 30) -> Dict:
    """
    Fetch page wikitext, sections, and revision ID from MediaWiki API.
    Supports ARCHWIKI_OFFLINE environment variable for deterministic testing.
    """
    params = {
        "action": "parse",
        "page": page_title,
        "prop": "wikitext|sections|revid",
        "format": "json",
    }

    data = _fetch(params, timeout)

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


def _find_template_end(wikitext: str, start_idx: int) -> int:
    """Find the matching }} for a starting {{ at start_idx."""
    depth = 0
    for j in range(start_idx, len(wikitext) - 1):
        if wikitext[j:j+2] == "{{":
            depth += 1
        elif wikitext[j:j+2] == "}}":
            depth -= 1
            if depth == 0:
                return j + 2
    return -1


def _parse_single_template(content: str, supported: set, revid: Optional[int]) -> Optional[WarningBlock]:
    """Parse the interior content of a template and return a WarningBlock if valid."""
    parts = content.split("|", 1)
    name = parts[0].strip().upper()
    
    if name in supported:
        message = parts[1].strip() if len(parts) > 1 else ""
        if message.startswith("1="):
            message = message[2:].strip()
            
        return WarningBlock(
            type=name,
            message=message,
            content_hash=hash_content(message),
            revid=revid
        )
    return None


def parse_templates(wikitext: str, revid: Optional[int] = None) -> List[WarningBlock]:
    """
    Robustly parse MediaWiki templates for warnings, notes, tips.
    Handles nesting, multi-params, and |1= syntax.
    """
    warnings = []
    supported = {"WARNING", "NOTE", "TIP", "CAUTION"}
    
    i = 0
    while i < len(wikitext):
        start_idx = wikitext.find("{{", i)
        if start_idx == -1:
            break
            
        end_idx = _find_template_end(wikitext, start_idx)
        if end_idx == -1:
            i = start_idx + 2
            continue
            
        content = wikitext[start_idx+2:end_idx-2]
        i = end_idx
        
        block = _parse_single_template(content, supported, revid)
        if block:
            warnings.append(block)
            
    return warnings


def _extract_indented_blocks(lines: List[str], revid: Optional[int] = None) -> List[CodeBlock]:
    """Helper to extract leading-space preformatted blocks."""
    blocks, current = [], []
    for line in lines:
        if line.startswith(" ") and not line.strip().startswith("*"):
            current.append(line[1:])
        elif current:
            c = "\n".join(current)
            blocks.append(CodeBlock(c, hash_content(c), "preformatted", "indented_block", None, revid))
            current = []
    if current:
        c = "\n".join(current)
        blocks.append(CodeBlock(c, hash_content(c), "preformatted", "indented_block", None, revid))
    return blocks

def _extract_shell_blocks(lines: List[str], revid: Optional[int] = None) -> List[CodeBlock]:
    """Helper to extract shell prompt blocks (# or $)."""
    blocks, current = [], []
    for line in lines:
        s = line.strip()
        # Accept # or $ at start of line
        if s.startswith("#") or s.startswith("$"):
            current.append(s)
        elif current:
            # Ensure the block looks like shell (starts with prompt)
            c = "\n".join(current)
            # Only emit if it looks like a real block (more than one line or has space after prompt)
            is_valid = len(current) > 1 or " " in current[0]
            if is_valid:
                blocks.append(CodeBlock(c, hash_content(c), "shell", "shell_heuristic", "bash", revid))
            current = []
    if current:
        c = "\n".join(current)
        if len(current) > 1 or " " in current[0]:
            blocks.append(CodeBlock(c, hash_content(c), "shell", "shell_heuristic", "bash", revid))
    return blocks

def parse_code_blocks(wikitext: str, revid: Optional[int] = None) -> List[CodeBlock]:
    """
    STRICT EXTRACTION: Only returns formal wiki code constructs.
    - Indented blocks (space-prefixed)
    - <pre> and <code> tags
    """
    lines = wikitext.split("\n")
    code_blocks = []
    
    # Pattern 1: Indented blocks
    code_blocks.extend(_extract_indented_blocks(lines, revid))
    
    # Pattern 2: <pre>...</pre> blocks
    pre_pattern = r'<pre>(.*?)</pre>'
    for match in re.finditer(pre_pattern, wikitext, re.DOTALL):
        content = match.group(1).strip()
        code_blocks.append(CodeBlock(content, hash_content(content), "pre_tag", "fenced_tag", None, revid))
    
    # Pattern 3: <code>...</code> blocks (only if multi-line)
    code_pattern = r'<code>(.*?)</code>'
    for match in re.finditer(code_pattern, wikitext, re.DOTALL):
        content = match.group(1).strip()
        if "\n" in content:
            code_blocks.append(CodeBlock(content, hash_content(content), "code_tag", "fenced_tag", None, revid))
    
    return code_blocks


def parse_shell_heuristics(wikitext: str, revid: Optional[int] = None) -> List[CodeBlock]:
    """
    HEURISTIC EXTRACTION: Attempts to find shell prompts in prose.
    Returns blocks that LOOK like commands but aren't formally fenced.
    """
    lines = wikitext.split("\n")
    return _extract_shell_blocks(lines, revid)


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

    data = _fetch(params, timeout)

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
            "url": make_wiki_url(item["title"])
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
        "url": make_wiki_url(parse_data["title"]),
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
        url=make_wiki_url(parse_data["title"], anchor),
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
    MCP Tool: Extract formal code blocks from page or section.
    These are structural elements (indented or tagged).
    """
    try:
        parse_data = fetch_wiki_parse(title)
        full_wikitext = parse_data["wikitext"]["*"]
        url_base = make_wiki_url(title)
        revid = parse_data.get("revid")
        
        if anchor:
            # Find section by anchor
            target_section = None
            next_section_offset = None
            section_list = parse_data["sections"]
            for i, sect in enumerate(section_list):
                if sect["anchor"] == anchor:
                    target_section = sect
                    if i + 1 < len(section_list):
                        next_section_offset = section_list[i + 1]["byteoffset"]
                    break
            
            if target_section is None:
                return [] # Section not found, return empty list
            
            wikitext_to_parse = extract_section_wikitext(
                full_wikitext,
                target_section["byteoffset"],
                next_section_offset
            )
            url_base = f"{url_base}#{anchor}"
        else:
            wikitext_to_parse = full_wikitext
            
        code_blocks = parse_code_blocks(wikitext_to_parse, revid)
        
        return [
            {
                "content": block.content,
                "content_hash": block.content_hash,
                "block_type": block.block_type,
                "source_pattern": block.source_pattern,
                "language": block.language,
                "source_url": url_base,
                "revid": block.revid
            }
            for block in code_blocks
        ]
    except Exception:
        return []


def examples(title: str, anchor: Optional[str] = None) -> List[Dict]:
    """
    MCP Tool: Extract heuristic shell examples from prose.
    Less reliable than commands(), used for snippets that LOOK like commands.
    """
    try:
        parse_data = fetch_wiki_parse(title)
        full_wikitext = parse_data["wikitext"]["*"]
        url_base = make_wiki_url(title)
        revid = parse_data.get("revid")
        
        if anchor:
            # Find section by anchor
            target_section = None
            next_section_offset = None
            section_list = parse_data["sections"]
            for i, sect in enumerate(section_list):
                if sect["anchor"] == anchor:
                    target_section = sect
                    if i + 1 < len(section_list):
                        next_section_offset = section_list[i + 1]["byteoffset"]
                    break
            
            if target_section is None:
                return [] # Section not found, return empty list
            
            wikitext_to_parse = extract_section_wikitext(
                full_wikitext,
                target_section["byteoffset"],
                next_section_offset
            )
            url_base = f"{url_base}#{anchor}"
        else:
            wikitext_to_parse = full_wikitext
            
        blocks = parse_shell_heuristics(wikitext_to_parse, revid)
        
        return [
            {
                "content": block.content,
                "content_hash": block.content_hash,
                "block_type": block.block_type,
                "source_pattern": block.source_pattern,
                "language": block.language,
                "source_url": url_base,
                "revid": block.revid
            }
            for block in blocks
        ]
    except Exception:
        return []


def warnings(title: str, anchor: Optional[str] = None) -> List[Dict]:
    """
    MCP Tool: Extract warning templates from page or section.
    
    Returns list of WarningBlock dicts.
    """
    if anchor:
        extracted = section(title, anchor)
        wikitext = extracted.content
        url_base = extracted.url
        revid = extracted.revid
    else:
        page_data = page(title)
        wikitext = page_data["wikitext"]
        url_base = page_data["url"]
        revid = page_data["revid"]
    
    warning_blocks = parse_templates(wikitext, revid)
    
    return [
        {
            "type": w.type,
            "message": w.message,
            "content_hash": w.content_hash,
            "source_url": url_base,
            "revid": w.revid
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
