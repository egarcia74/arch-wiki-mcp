#!/usr/bin/env python3
"""
Arch Wiki Constitutional Extractor
Deterministic, hash-stable extraction of wiki content with full provenance.
"""

import hashlib
import re
import unicodedata
from dataclasses import dataclass, asdict, fields
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
    byteoffset: Optional[int] = 0  # null for transcluded sections
    fromtitle: str = ""
    link_anchor: str = ""

    @classmethod
    def from_api(cls, raw: Dict) -> "WikiSection":
        """Tolerate keys MediaWiki adds over time rather than raising TypeError."""
        allowed = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in raw.items() if k in allowed})


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
    content: str  # Emphasis stripped, {{ic}}/{{=}} resolved -- safe to execute
    content_raw: str  # Verbatim payload as it appeared in wikitext
    content_hash: str  # SHA-256 over content_raw, so it stays greppable in the source
    block_type: str  # "block_code", "file_content", "preformatted"
    source_pattern: str  # "template_bc", "template_hc", "indented_block"
    language: Optional[str] = None
    header: Optional[str] = None  # {{hc}} file path or command; None for {{bc}}
    placeholders: Optional[List[str]] = None  # Tokens the author marked ''italic''
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
    anchor: Optional[str] = None


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
    section_start: Optional[int],
    section_end: Optional[int]
) -> str:
    """
    Extract section content from wikitext using the API's section offsets.

    Despite its name, MediaWiki's `byteoffset` indexes the wikitext by CHARACTER,
    not by UTF-8 byte. Verified across the recorded corpus: all 432 sections land
    exactly on their heading when the offset is used as a character index, while
    byte indexing only works for pages with no multibyte character before the
    heading (121 of 432). Encoding first shifted every section on a page
    containing so much as one accented letter, silently returning a neighbouring
    section's text.

    A null start means the section is transcluded and its text is not on this page
    at all; slicing would return the wrong content, so refuse. A null end means
    "to the end of the page" and is fine.
    """
    if section_start is None:
        raise ValueError(
            "Section has no byte offset (transcluded); its wikitext is not on this page"
        )

    return wikitext[section_start:section_end]


def _resolve_section(parse_data: Dict, anchor: str) -> Tuple[Dict, str]:
    """
    Locate a section by anchor and return it with its wikitext.

    Raises ValueError when the anchor is absent or the section is transcluded,
    rather than returning an empty result the caller cannot distinguish from
    "this section genuinely has no content".
    """
    title = parse_data["title"]
    section_list = parse_data["sections"]

    for i, sect in enumerate(section_list):
        if sect["anchor"] != anchor:
            continue

        if sect["byteoffset"] is None:
            raise ValueError(
                f"Section '{anchor}' in page '{title}' is transcluded "
                f"(null byte offset); its wikitext is not on this page"
            )

        # Skip transcluded neighbours: their null offset is not a boundary.
        next_offset = next(
            (s["byteoffset"] for s in section_list[i + 1:] if s["byteoffset"] is not None),
            None,
        )
        content = extract_section_wikitext(
            parse_data["wikitext"]["*"], sect["byteoffset"], next_offset
        )

        # Fail closed if the slice did not land on a heading. Every section
        # offset must point at its own '==' line; anything else means the API's
        # offset semantics moved under us, and quoting the result would cite the
        # wrong text under a valid-looking hash.
        if not content.startswith("="):
            raise ValueError(
                f"Section '{anchor}' in page '{title}' did not resolve to a heading "
                f"(offset {sect['byteoffset']} landed on {content[:40]!r})"
            )

        return sect, content

    raise ValueError(f"Section with anchor '{anchor}' not found in page '{title}'")


def _find_template_end(wikitext: str, start_idx: int) -> int:
    """
    Find the matching }} for a starting {{ at start_idx.

    Triple braces ({{{parameter}}}) are consumed whole: a 2-char scan would read
    them as {{ + { and miscount the depth.
    """
    depth = 0
    j = start_idx
    end = len(wikitext)
    while j < end - 1:
        if wikitext.startswith("{{{", j) or wikitext.startswith("}}}", j):
            j += 3
        elif wikitext.startswith("{{", j):
            depth += 1
            j += 2
        elif wikitext.startswith("}}", j):
            depth -= 1
            j += 2
            if depth == 0:
                return j
        else:
            j += 1
    return -1


def _split_template_params(inner: str, max_splits: int) -> List[str]:
    """
    Split a template interior on top-level '|' only, at most max_splits times.

    A '|' separates parameters only at zero depth. Inside {{...}}, [[...]], or a
    {|...|} table it is content. Capping the split count matters just as much:
    {{bc}} takes one body parameter, so every '|' after the first is the author's
    shell pipe, not a separator.
    """
    openers = ("{{", "[[", "{|")
    closers = ("}}", "]]", "|}")

    parts: List[str] = []
    buf: List[str] = []
    depth = 0
    i = 0
    end = len(inner)

    while i < end:
        pair = inner[i:i + 2]
        if pair in openers:
            depth += 1
        elif pair in closers:
            depth -= 1
        else:
            char = inner[i]
            if char == "|" and depth == 0 and len(parts) < max_splits:
                parts.append("".join(buf))
                buf = []
            else:
                buf.append(char)
            i += 1
            continue

        buf.append(pair)
        i += 2

    parts.append("".join(buf))
    return parts


_NAMED_PARAM = re.compile(r"^\s*([A-Za-z0-9_]+)\s*=")


def _strip_param_name(text: str, allowed: set) -> str:
    """
    Drop a leading `name=` only when the name is a known parameter of the template.

    Guards bodies that legitimately open with an assignment, e.g. {{bc|GRUB_ENABLE=y}}.
    """
    match = _NAMED_PARAM.match(text)
    if match and match.group(1) in allowed:
        return text[match.end():]
    return text


_NOWIKI_TAG = re.compile(r"</?nowiki>")
_INLINE_CODE = re.compile(r"\{\{ic\|(?:1=)?([^{}|]*)\}\}", re.IGNORECASE)
_BOLD = re.compile(r"'''(.*?)'''", re.DOTALL)
_ITALIC = re.compile(r"''(.*?)''", re.DOTALL)


def _clean_payload(raw: str) -> Tuple[str, List[str]]:
    """
    Render a code payload down to what a user would actually run.

    Returns the cleaned text and the tokens the author marked ''italic'', which on
    the Arch Wiki denote values the reader must substitute (''esp'', ''device'').
    Surfacing them is extraction of the author's own markup, not synthesis.
    """
    text = raw.replace("{{=}}", "=")
    text = _NOWIKI_TAG.sub("", text)
    text = _INLINE_CODE.sub(r"\1", text)
    text = _BOLD.sub(r"\1", text)  # Bold before italic: ''' would else split as '' + '

    placeholders = list(dict.fromkeys(t for t in _ITALIC.findall(text) if t))
    text = _ITALIC.sub(r"\1", text)

    return text.strip("\n"), placeholders


def _parse_single_template(content: str, supported: set, revid: Optional[int]) -> Optional[WarningBlock]:
    """
    Parse the interior content of a template and return a WarningBlock if valid.

    TODO: reuse _split_template_params/_strip_param_name here. The naive
    split("|", 1) truncates any message containing a pipe inside a nested
    template or link. Deferred: it would change every warning content_hash.
    """
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


def _make_block(
    raw: str,
    block_type: str,
    source_pattern: str,
    revid: Optional[int],
    header: Optional[str] = None,
) -> CodeBlock:
    content, placeholders = _clean_payload(raw)
    return CodeBlock(
        content=content,
        content_raw=raw,
        content_hash=hash_content(raw),
        block_type=block_type,
        source_pattern=source_pattern,
        language=None,
        header=header or None,
        placeholders=placeholders or None,
        revid=revid,
    )


def _extract_indented_blocks(lines: List[str], revid: Optional[int] = None) -> List[CodeBlock]:
    """Helper to extract leading-space preformatted blocks."""
    blocks, current = [], []
    for line in lines:
        if line.startswith(" ") and not line.strip().startswith("*"):
            current.append(line[1:])
        elif current:
            blocks.append(_make_block("\n".join(current), "preformatted", "indented_block", revid))
            current = []
    if current:
        blocks.append(_make_block("\n".join(current), "preformatted", "indented_block", revid))
    return blocks


@dataclass(frozen=True)
class _CodeTemplate:
    """How to pull a payload out of one Arch Wiki code template."""
    max_splits: int
    header_names: Optional[frozenset]  # None when the template has no header param
    body_names: frozenset
    block_type: str
    source_pattern: str


# Arch-specific conventions (Template:Bc, Template:Hc). MediaWiki exposes no way
# to discover "which templates are code", so the set is declared, not derived --
# but its shape lives in data, so adding one is an entry, not a new branch.
CODE_TEMPLATES = {
    "bc": _CodeTemplate(1, None, frozenset({"1"}), "block_code", "template_bc"),
    "hc": _CodeTemplate(2, frozenset({"1"}), frozenset({"2", "output"}), "file_content", "template_hc"),
}

_CODE_TEMPLATE_RE = re.compile(r"\{\{(" + "|".join(CODE_TEMPLATES) + r")\b", re.IGNORECASE)
_NON_NEWLINE = re.compile(r"[^\n]")


def _extract_code_templates(
    wikitext: str, revid: Optional[int]
) -> Tuple[List[CodeBlock], List[Tuple[int, int]]]:
    """
    Extract {{bc}} (block code) and {{hc}} (file contents with a header).

    These carry essentially all real Arch Wiki code. Returns the blocks and the
    spans they consumed, so the indented scanner can skip them.
    """
    blocks: List[CodeBlock] = []
    spans: List[Tuple[int, int]] = []
    consumed_to = 0

    for match in _CODE_TEMPLATE_RE.finditer(wikitext):
        start = match.start()
        if start < consumed_to:
            continue  # Nested inside a block we already took
        end = _find_template_end(wikitext, start)
        if end == -1:
            continue
        consumed_to = end

        spec = CODE_TEMPLATES[match.group(1).lower()]
        params = _split_template_params(wikitext[start + 2:end - 2], spec.max_splits)

        index = 1
        header = None
        if spec.header_names is not None:
            header_raw = _strip_param_name(params[index], spec.header_names) if len(params) > index else ""
            header, _ = _clean_payload(header_raw)
            index += 1

        raw = _strip_param_name(params[index], spec.body_names) if len(params) > index else ""

        blocks.append(_make_block(raw, spec.block_type, spec.source_pattern, revid, header=header))
        spans.append((start, end))

    return blocks, spans


def _mask_spans(wikitext: str, spans: List[Tuple[int, int]]) -> str:
    """
    Blank out consumed spans, preserving newlines so line structure survives.

    Space-prefixed lines inside a {{bc}}/{{hc}} body would otherwise be scanned a
    second time and re-emitted as phantom indented blocks.
    """
    if not spans:
        return wikitext

    out, previous = [], 0
    for start, end in spans:
        out.append(wikitext[previous:start])
        out.append(_NON_NEWLINE.sub("\x00", wikitext[start:end]))
        previous = end
    out.append(wikitext[previous:])

    return "".join(out)


def parse_code_blocks(wikitext: str, revid: Optional[int] = None) -> List[CodeBlock]:
    """
    STRICT EXTRACTION: only formal, block-level wiki code constructs.

    - {{bc}} / {{hc}} templates
    - Indented blocks (space-prefixed)

    Inline {{ic}} is deliberately excluded: it marks paths, flags and package
    names, not runnable commands.
    """
    blocks, spans = _extract_code_templates(wikitext, revid)
    blocks.extend(_extract_indented_blocks(_mask_spans(wikitext, spans).split("\n"), revid))
    return blocks


# Non-content namespaces. [[Category:X]] and [[File:X]] are page metadata, not
# navigable article links.
_NAMESPACE_PREFIXES = frozenset({
    "category", "file", "image", "media", "mediawiki", "module",
    "template", "help", "special", "talk", "user", "project",
})

# Language editions and sister projects. An Arch page links [[de:GRUB]] to bind
# its translation, not to point the reader at a different article.
#
# TODO: derive from action=query&meta=siteinfo&siprop=interwikimap|namespaces
# instead. A static list rots: a language Arch adds later would surface as a
# navigable article link.
_INTERWIKI_PREFIXES = frozenset({
    "ar", "az", "bg", "bs", "ca", "cs", "da", "de", "el", "en", "es", "fa", "fi",
    "fr", "he", "hr", "hu", "id", "it", "ja", "ko", "lt", "nl", "no", "pl", "pt",
    "ro", "ru", "sk", "sl", "sr", "sv", "th", "tr", "uk", "vi",
    "zh-hans", "zh-hant", "zh-cn", "zh-tw",
    "wikipedia", "w", "wiktionary", "commons", "debian", "gentoo", "ubuntu",
    "freebsd", "kernel", "man", "arxiv", "rfc",
})

# An explicit exclusion list, never a "looks like a language code" heuristic:
# silently dropping a real link is synthesis by omission.
_EXCLUDED_PREFIXES = _NAMESPACE_PREFIXES | _INTERWIKI_PREFIXES


def parse_internal_links(wikitext: str, source_page: str) -> List[InternalLink]:
    """
    Parse navigable internal wiki links from wikitext.

    Handles [[Target]], [[Target|Display]], [[Target#Anchor|Display]], and the
    same-page [[#Anchor]] form. Namespace and interwiki links are excluded, as
    are multi-parameter media links like [[File:x.png|thumb|caption]].
    """
    links = []

    for match in re.finditer(r"\[\[([^\[\]]+)\]\]", wikitext):
        target_part, separator, display_part = match.group(1).partition("|")

        target = target_part.strip()
        if target.startswith(":"):
            target = target[1:].strip()  # [[:Category:X]] renders as a link, still metadata

        if ":" in target:
            prefix = target.split(":", 1)[0].strip().lower()
            if prefix in _EXCLUDED_PREFIXES:
                continue

        page_part, _, anchor_part = target.partition("#")
        page_name = page_part.strip() or source_page  # [[#Anchor]] targets this page
        anchor = anchor_part.strip() or None

        # Only the first parameter is display text; the rest are media options.
        display = display_part.split("|")[0].strip() if separator else None

        links.append(InternalLink(
            target_page=page_name,
            display_text=display or None,
            source_page=source_page,
            anchor=anchor,
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
        "sections": [asdict(WikiSection.from_api(s)) for s in parse_data["sections"]]
    }


def sections(title: str) -> List[Dict]:
    """
    MCP Tool: Return section list with anchors and byte offsets.
    
    Returns list of sections with metadata.
    """
    parse_data = fetch_wiki_parse(title)
    return [asdict(WikiSection.from_api(s)) for s in parse_data["sections"]]


def section(title: str, anchor: str) -> ExtractedBlock:
    """
    MCP Tool: Extract single section by anchor with full provenance.

    Returns ExtractedBlock with section content and hash.
    """
    parse_data = fetch_wiki_parse(title)
    target_section, content = _resolve_section(parse_data, anchor)

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
    MCP Tool: Extract formal, block-level code blocks from a page or section.

    Fails closed. A missing page or a missing anchor raises; only a page that
    genuinely contains no code blocks returns []. Callers are told to treat []
    as "the wiki specifies no command here", so it must never stand in for an
    error.
    """
    parse_data = fetch_wiki_parse(title)
    revid = parse_data.get("revid")
    url_base = make_wiki_url(title)

    if anchor:
        _, wikitext_to_parse = _resolve_section(parse_data, anchor)
        url_base = f"{url_base}#{anchor}"
    else:
        wikitext_to_parse = parse_data["wikitext"]["*"]

    return [
        {
            "content": block.content,
            "content_raw": block.content_raw,
            "content_hash": block.content_hash,
            "block_type": block.block_type,
            "source_pattern": block.source_pattern,
            "language": block.language,
            "header": block.header,
            "placeholders": block.placeholders,
            "source_url": url_base,
            "revid": block.revid
        }
        for block in parse_code_blocks(wikitext_to_parse, revid)
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
            "anchor": link.anchor,
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
