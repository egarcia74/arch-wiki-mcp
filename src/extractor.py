#!/usr/bin/env python3
"""
Arch Wiki Constitutional Extractor
Deterministic, hash-stable extraction of wiki content with full provenance.
"""

import hashlib
import logging
import re
import unicodedata
from dataclasses import dataclass, asdict, fields
from functools import lru_cache
from typing import AbstractSet, Dict, List, Optional, Tuple
from urllib.error import URLError
from urllib.request import urlopen, Request
from urllib.parse import urlencode, quote
import json
import os

# stderr by default, which keeps JSON-RPC on stdout clean.
logger = logging.getLogger(__name__)

API_ENDPOINT = "https://wiki.archlinux.org/api.php"
USER_AGENT = "ArchWikiMCP/1.0 (Constitutional Extractor; +https://github.com/user/arch-wiki-mcp)"

# Shared with tests/record_fixtures.py: the recorder must request exactly what
# fetch_siteinfo() requests, or the recorded fixture answers a different question.
SITEINFO_PROPS = "namespaces|namespacealiases|interwikimap"


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
    content: str      # Rendered: markup resolved, code fenced, placeholders marked
    content_raw: str  # Verbatim wikitext slice, exactly as the revision stores it
    content_hash: str  # SHA-256 over content_raw, so it stays greppable in the source
    content_hash_cleaned: str  # SHA-256 over content -- the text an agent quotes


@dataclass
class CodeBlock:
    """Extracted code block with metadata."""
    content: str  # Emphasis stripped, {{ic}}/{{=}} resolved -- safe to execute
    content_raw: str  # Verbatim payload as it appeared in wikitext
    content_hash: str  # SHA-256 over content_raw, so it stays greppable in the source
    content_hash_cleaned: str  # SHA-256 over content -- the text an agent actually runs
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
    message: str  # Markup resolved -- readable prose, safe to quote to a user
    message_raw: str  # Verbatim template body as it appeared in wikitext
    content_hash: str  # SHA-256 over message_raw, so it stays greppable in the source
    message_hash_cleaned: str  # SHA-256 over message -- the text the agent must quote
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


def fixture_key(params: Dict) -> str:
    """The identifying parameter of a request: the page, the query, or the metadata kind."""
    return params.get("page") or params.get("srsearch") or params.get("meta") or "unknown"


def _fetch_offline(params: Dict, key: Optional[str] = None) -> Dict:
    """Retrieve API response from local fixtures for offline testing."""
    fixtures_dir = os.environ.get("ARCHWIKI_FIXTURES", "tests/fixtures")
    action = params.get("action", "unknown")

    fixture_path = os.path.join(fixtures_dir, fixture_filename(action, key or fixture_key(params)))
    return json.loads(_read_fixture(fixture_path))


def _fetch(params: Dict, timeout: int = 30, key: Optional[str] = None) -> Dict:
    """
    Single entry point for API access. ARCHWIKI_OFFLINE swaps in fixtures.

    `key` names the fixture when no single parameter identifies the request --
    the template-alias query is keyed by the page whose templates it resolves,
    not by the long `titles` list it sends.
    """
    if os.environ.get("ARCHWIKI_OFFLINE"):
        return _fetch_offline(params, key)

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

    A '}}}' only closes a parameter when one is actually open. Otherwise it is
    ambiguous, and the body decides which two of the three braces close us:

      {{App|x|{{Pkg|y}}}}          '}}' closes Pkg, '}}' closes App
      {{ic|menuentry {options}}}   '}' closes the literal brace, '}}' closes ic

    So a '}' is read as a literal only while an unmatched '{' is open. Getting
    this wrong either leaves the template unterminated -- it then survives into
    output as raw markup -- or ends its span a brace early, which mis-slices the
    body and leaks a stray '}' past the span mask.
    """
    depth = 0
    parameter_depth = 0
    brace_depth = 0  # unmatched literal '{' inside the body
    j = start_idx
    end = len(wikitext)
    while j < end - 1:
        if wikitext.startswith("{{{", j):
            parameter_depth += 1
            j += 3
        elif wikitext.startswith("}}}", j) and parameter_depth > 0:
            parameter_depth -= 1
            j += 3
        elif wikitext.startswith("{{", j):
            depth += 1
            j += 2
        elif wikitext.startswith("}}}", j) and brace_depth > 0:
            brace_depth -= 1
            j += 1
        elif wikitext.startswith("}}", j):
            depth -= 1
            j += 2
            if depth == 0:
                return j
        elif wikitext[j] == "{":
            brace_depth += 1
            j += 1
        elif wikitext[j] == "}" and brace_depth > 0:
            brace_depth -= 1
            j += 1
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


def _strip_param_name(text: str, allowed: AbstractSet[str]) -> str:
    """
    Drop a leading `name=` only when the name is a known parameter of the template.

    Guards bodies that legitimately open with an assignment, e.g. {{bc|GRUB_ENABLE=y}}.
    """
    match = _NAMED_PARAM.match(text)
    if match and match.group(1) in allowed:
        return text[match.end():]
    return text


_NOWIKI_TAG = re.compile(r"</?nowiki>")
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_BOLD = re.compile(r"'''(.*?)'''", re.DOTALL)
_ITALIC = re.compile(r"''(.*?)''", re.DOTALL)
# [[Target|display]] / [[Target]] / [[Target#Anchor]]
# Display text may itself contain brackets -- [[#General options|[options]]] --
# so it is matched lazily up to the first ']]' rather than excluding '[' and ']'.
# Forbidding them left that link unmatched, and it survived into prose as markup.
_WIKILINK = re.compile(r"\[\[([^\[\]|]+)(?:\|(.*?))?\]\]")
_EXTERNAL_LINK = re.compile(r"\[(https?://\S+?)(?:\s+([^\]]*))?\]")

# Templates that wrap a literal value. Each maps its parameters to the text the
# template renders: {{ic|cmd}} -> "cmd", {{man|8|ip-link}} -> "ip-link(8)".
# Keyed by name; the scanning regex is built from the keys.
INLINE_TEMPLATES = {
    "ic": (1, lambda p: _strip_param_name(p[1], {"1"})),
    "pkg": (1, lambda p: _strip_param_name(p[1], {"1"})),
    "aur": (1, lambda p: _strip_param_name(p[1], {"1"})),
    "grp": (1, lambda p: _strip_param_name(p[1], {"1"})),
    "man": (2, lambda p: f"{p[2]}({p[1]})" if len(p) > 2 else p[-1]),
}

_INLINE_TEMPLATE_RE = re.compile(r"\{\{(" + "|".join(INLINE_TEMPLATES) + r")\s*\|", re.IGNORECASE)

# MediaWiki escapes for characters that would otherwise be template syntax.
_TEMPLATE_ESCAPES = {"{{=}}": "=", "{{!}}": "|"}


def _iter_top_level_templates(text: str, pattern: "re.Pattern"):
    """
    Yield (start, end, name) for each non-nested template matching pattern.

    Matches beginning inside an already-yielded span are skipped, and an unclosed
    template is passed over rather than consuming the rest of the document.
    """
    consumed_to = 0
    for match in pattern.finditer(text):
        if match.start() < consumed_to:
            continue
        end = _find_template_end(text, match.start())
        if end == -1:
            continue
        consumed_to = end
        yield match.start(), end, match.group(1).lower()


def _resolve_inline_templates(text: str, _depth: int = 0) -> str:
    """
    Replace inline literal templates with the value they render.

    Uses the brace matcher rather than a regex, because bodies legitimately
    contain pipes -- {{ic|pacman -Ql foo {{!}} grep bin}} -- which a
    `[^{}|]*` pattern can never see through.
    """
    if _depth > 4:  # Malformed input; stop rather than recurse forever
        return text

    out, position = [], 0
    for start, end, name in _iter_top_level_templates(text, _INLINE_TEMPLATE_RE):
        max_splits, render = INLINE_TEMPLATES[name]
        params = _split_template_params(text[start + 2:end - 2], max_splits)
        body = render(params) if len(params) > 1 else ""

        out.append(text[position:start])
        out.append(_resolve_inline_templates(body, _depth + 1))
        position = end

    out.append(text[position:])
    return "".join(out)


def _strip_inline_markup(text: str, mark_placeholders: bool = False) -> Tuple[str, List[str]]:
    """
    Remove wikitext markup that is presentation, not content.

    Returns the cleaned text and the tokens the author marked ''italic''.

    Inside a code block, italics denote a value the reader must substitute
    (''esp'', ''device''); `mark_placeholders` keeps that signal visible as
    <esp>. Inside prose, italics are ordinary emphasis and are simply removed.
    Either way this reads the author's own markup and infers nothing.
    """
    text = _HTML_COMMENT.sub("", text)
    text = _NOWIKI_TAG.sub("", text)
    text = _resolve_inline_templates(text)

    # After template resolution: an escape inside a body would otherwise have
    # broken the parameter split that recovered that body.
    for escape, literal in _TEMPLATE_ESCAPES.items():
        text = text.replace(escape, literal)

    text = _BOLD.sub(r"\1", text)  # Bold before italic: ''' would else split as '' + '

    placeholders = list(dict.fromkeys(t for t in _ITALIC.findall(text) if t))
    text = _ITALIC.sub(r"<\1>" if mark_placeholders else r"\1", text)

    return text, placeholders


def _clean_payload(raw: str) -> Tuple[str, List[str]]:
    """
    Render a code payload down to what a user would run, after substitution.

    Placeholders stay marked. The wiki italicises them precisely because they are
    not literals, and emitting a bare `esp` produces a command that looks runnable
    and silently is not. `<esp>` fails at the shell instead, so a literal paste is
    resisted by structure rather than forbidden by a prompt.
    """
    text, placeholders = _strip_inline_markup(raw, mark_placeholders=True)
    return text.strip("\n"), placeholders


def _resolve_links(text: str) -> str:
    """
    Render wiki and external links as the words a reader sees.

    [[Users and groups#Group management|add your user]] -> "add your user"
    [[Start/enable]]                                    -> "Start/enable"
    [https://example.com/bug a long open bug]           -> "a long open bug (https://example.com/bug)"
    """
    text = _WIKILINK.sub(lambda m: (m.group(2) or m.group(1)).strip(), text)
    text = _EXTERNAL_LINK.sub(
        lambda m: f"{m.group(2).strip()} ({m.group(1)})" if m.group(2) else m.group(1),
        text,
    )
    return text


# The WHOLE leading marker run: "#**", "::*", "##". Matching only the last
# character left the rest in the body -- '##' rendered as '1. # body', putting a
# bare '#' back into prose, which is the very thing this function exists to stop.
# Anchored at column 0: a line starting with a space is preformatted code, and
# its indentation is content.
_LEADING_LIST_MARKUP = re.compile(r"^([*#:;]+)[ \t]*")


def _render_list_markers(line: str) -> str:
    """
    Turn wikitext list markup into plain-text bullets, preserving nesting depth.

    A bare '#' must never survive into agent-facing prose: it is wikitext's
    ordered-list marker, and mistaking it for a root shell prompt is exactly the
    confusion that made the old examples() tool emit prose as bash. An indented
    line is preformatted code and is left untouched.

    '*' and '#' nest a list; ':' and ';' only indent, and carry no meaning once
    the markup is gone. The innermost marker decides the bullet:

        *     -> "- "          #     -> "1. "
        **    -> "  - "        ##    -> "  1. "
        #*    -> "  - "        #**   -> "    - "
    """
    match = _LEADING_LIST_MARKUP.match(line)
    if not match:
        return line

    marker = match.group(1)
    body = line[match.end():]

    depth = sum(1 for char in marker if char in "*#")
    if depth == 0:
        return body  # Bare ':' / ';' indentation carries no meaning in plain text

    if not body.strip():
        return ""  # "#}}" -- a list marker holding only a template's closing brace

    bullet = "- " if marker[-1] == "*" else "1. "
    return f"{'  ' * (depth - 1)}{bullet}{body}"


def _clean_message(raw: str) -> str:
    """
    Render a warning/note body down to prose a user can read.

    The consuming agent is required to quote these to the user, so shipping raw
    {{ic|...}} and [[links]] made the mandated response shape unreadable. The
    verbatim text is preserved alongside as message_raw, and that is what the
    content_hash covers.
    """
    text, _ = _strip_inline_markup(raw)
    text = _resolve_links(text)
    text = "\n".join(_render_list_markers(line) for line in text.split("\n"))
    return text.strip()


def _parse_single_template(
    content: str, types: Dict[str, Optional[str]], revid: Optional[int]
) -> Optional[WarningBlock]:
    """
    Parse the interior content of a template and return a WarningBlock if valid.

    Splits on the first TOP-LEVEL pipe. A naive split("|", 1) truncated any
    message containing a pipe inside a nested {{ic|a|b}} or [[link|text]].

    `types` maps a template name to the admonition it denotes. A translated page
    spells it {{Note (Español)}} or {{Attention}}, so the name alone is not enough.
    """
    parts = _split_template_params(content, 1)
    raw_name = parts[0].strip()

    name = types.get(raw_name.lower()) or canonical_admonition(raw_name)
    if name not in ADMONITION_TYPES:
        return None

    message_raw = _strip_param_name(parts[1], {"1"}).strip() if len(parts) > 1 else ""
    message = _clean_message(message_raw)

    return WarningBlock(
        type=name,
        message=message,
        message_raw=message_raw,
        content_hash=hash_content(message_raw),
        message_hash_cleaned=hash_content(message),
        revid=revid
    )


def parse_templates(
    wikitext: str,
    revid: Optional[int] = None,
    types: Optional[Dict[str, Optional[str]]] = None,
) -> List[WarningBlock]:
    """
    Robustly parse MediaWiki templates for warnings, notes, tips.
    Handles nesting, multi-params, and |1= syntax.

    `types` maps template names to admonition types for a translated page. Without
    it, only names that spell themselves out are recognized -- enough for English,
    and blind to {{Attention}}. warnings() supplies it; see admonition_types().
    """
    warnings = []
    types = types or {}
    
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
        
        block = _parse_single_template(content, types, revid)
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
        content_hash_cleaned=hash_content(content),
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

    for start, end, name in _iter_top_level_templates(wikitext, _CODE_TEMPLATE_RE):
        spec = CODE_TEMPLATES[name]
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


# ---------------------------------------------------------------------------
# Section rendering
#
# AGENTS.md Rule 4 sends the agent here whenever commands() honestly returns []:
# it must quote section() prose instead of inferring a command. Handing back raw
# wikitext made that mandated fallback unsafe -- a numbered list item ("# Point
# the current boot device ...") is indistinguishable from a root shell prompt.
# That is the confusion that got examples() deleted; it survived in the one path
# the constitution requires.
#
# The rendering is deliberately conservative. A template this renderer does not
# know is left VERBATIM, never dropped: markup an agent can see is honest, and
# silently deleting a sentence is synthesis by omission. The renderable set is
# therefore a whitelist, and test_section_render_golden pins the residue.
# ---------------------------------------------------------------------------

_ADMONITIONS = {"note": "Note", "warning": "Warning", "tip": "Tip", "caution": "Caution"}

# Templates that resolve to a literal inside prose, plus the wikitext escapes.
# They are left in place for _strip_inline_markup rather than masked.
_RESOLVED_INLINE = frozenset(INLINE_TEMPLATES) | {"=", "!"}


def _classify_template(name: str) -> str:
    """
    What the renderer may do with a top-level template: render it, resolve it
    inline, or nothing at all.

    "Nothing at all" is a commitment, not a gap. An unknown template is emitted
    byte-for-byte as the wiki wrote it, insides included -- see _mask_templates.
    """
    lowered = name.strip().lower()
    if lowered in CODE_TEMPLATES:
        return "code"
    if canonical_admonition(name):  # {{Note}}, and {{Note (Español)}}
        return "admonition"
    if lowered in _RESOLVED_INLINE:
        return "inline"
    return "verbatim"
_HEADING = re.compile(r"^(={2,6})[ \t]*(.+?)[ \t]*\1[ \t]*$")
_SENTINEL = re.compile("\x00(\\d+)\x00")
_MAX_RENDER_DEPTH = 4


def _render_code_template(name: str, interior: str) -> str:
    """Render {{bc}}/{{hc}} as a fenced block, so prose can never be mistaken for it."""
    spec = CODE_TEMPLATES[name]
    params = _split_template_params(interior, spec.max_splits)

    index = 1
    header = None
    if spec.header_names is not None:
        header_raw = _strip_param_name(params[index], spec.header_names) if len(params) > index else ""
        header, _ = _clean_payload(header_raw)
        index += 1

    raw = _strip_param_name(params[index], spec.body_names) if len(params) > index else ""
    body, _ = _clean_payload(raw)

    fence = f"```\n{body}\n```"
    if not header:
        return fence

    # A {{hc}} header is either a file path (/etc/default/grub) or the command
    # that produced the body (# efibootmgr -u). Emitted bare, the latter starts a
    # line with '#' -- markdown reads that as a heading, and a reader as a root
    # prompt sitting outside any fence. Backticks make it unambiguously a literal.
    return f"`{header}`\n{fence}"


def _render_admonition(name: str, interior: str, depth: int) -> str:
    """Render {{Note|...}} and friends as labelled prose, recursing for nested code."""
    params = _split_template_params(interior, 1)
    raw = _strip_param_name(params[1], {"1"}) if len(params) > 1 else ""

    # "{{Note| The iwd backend ...}}": that leading space sits mid-line in the
    # source, not at column 0, so it does not mark preformatted code. Left on, the
    # whole note renders as code -- links unresolved, and ''bar'' turned into the
    # placeholder <bar>, inventing a value the reader is told to substitute.
    # A body that opens with a newline keeps it; only the first line is affected.
    # strip("\n") not strip(): a nested first item ("#** foo") renders indented,
    # and eating that indent silently promotes it a level above its own siblings.
    body = render_section_wikitext(raw.lstrip(" \t"), depth + 1).strip("\n")

    label = f"**{_ADMONITIONS[canonical_admonition(name).lower()]}:**"
    # A bullet, a fence, or an indented line glued to the label reads as part of it.
    inline = not ("\n" in body or body[:1].isspace() or body.startswith(("- ", "1. ", "```")))
    return f"{label}{' ' if inline else chr(10)}{body}"


def _render_prose_line(line: str) -> str:
    """
    Render one non-template line.

    A space-prefixed line is preformatted code, so it keeps its indentation and
    gets code semantics -- placeholders marked, exactly as commands() marks them.
    Everything else is prose, where ''italics'' are emphasis rather than
    substitution slots.
    """
    if line[:1] in (" ", "\t") and line.strip():
        text, _ = _strip_inline_markup(line, mark_placeholders=True)
        return text

    text, _ = _strip_inline_markup(line)

    heading = _HEADING.match(text)
    if heading:
        return f"{'#' * len(heading.group(1))} {heading.group(2)}"

    return _render_list_markers(_resolve_links(text))


def _render_prose(text: str) -> str:
    return "\n".join(_render_prose_line(line) for line in text.split("\n"))


def _splice_line(line: str, blocks: List[Tuple[str, bool]]) -> str:
    """
    Expand sentinels. A block-level one is lifted onto its own line.

    {{bc}} occurs mid-sentence -- "remount {{ic|...}}. {{bc|# mount ...}} See the
    [[Gentoo:...]]" -- so a fence spliced in place would glue its ``` markers to
    the prose on either side. A verbatim template is not block-level: {{App|...}}
    sits inside a bullet, and lifting it out would invent a line break.
    """
    if not _SENTINEL.search(line):
        return line

    segments: List[str] = []
    current = ""
    position = 0
    for match in _SENTINEL.finditer(line):
        text, is_block = blocks[int(match.group(1))]
        current += line[position:match.start()]
        position = match.end()

        if not is_block:
            current += text
            continue

        if current.rstrip():
            segments.append(current.rstrip())
        segments.append(text)
        current = ""

    current += line[position:]
    if not segments:
        return current

    tail = current.lstrip()
    if tail:
        segments.append(tail)
    return "\n".join(segments)


def render_section_wikitext(wikitext: str, _depth: int = 0) -> str:
    """
    Render a section's wikitext down to text an agent can quote to a user.

    Every template this renderer touches is masked to a newline-free sentinel
    first, so whether a line is preformatted is decided by its position in the
    *original* wikitext. Splitting the text on template spans instead would leave
    the prose trailing a mid-line template starting with a space; it would then
    render as indented code, links unresolved, inside no fence.

    An unknown template is masked too, and restored byte-for-byte. Left in the
    text it would be swept by _strip_inline_markup, which resolves the {{ic|...}}
    and ''italics'' *inside* it -- so {{Accuracy|Use {{ic|sleep 5}}}} came out as
    {{Accuracy|Use sleep 5}}: text that looks raw, is not, and is attested by
    content_hash_cleaned all the same. Masking is what makes "verbatim" true.
    """
    if _depth > _MAX_RENDER_DEPTH:
        return wikitext

    blocks: List[Tuple[str, bool]] = []
    masked: List[str] = []
    position = 0
    for start, end, name in _iter_top_level_templates(wikitext, _ANY_TEMPLATE_RE):
        kind = _classify_template(name)
        if kind == "inline":
            continue  # {{ic|...}}, {{=}}: resolved later, in place

        interior = wikitext[start + 2:end - 2]
        if kind == "code":
            rendered, is_block = _render_code_template(name.strip().lower(), interior), True
        elif kind == "admonition":
            rendered, is_block = _render_admonition(name, interior, _depth), True
        else:
            rendered, is_block = wikitext[start:end], False

        masked.append(wikitext[position:start])
        masked.append(f"\x00{len(blocks)}\x00")
        blocks.append((rendered, is_block))
        position = end

    masked.append(wikitext[position:])

    rendered = _render_prose("".join(masked))
    if blocks:
        rendered = "\n".join(_splice_line(line, blocks) for line in rendered.split("\n"))
    # Newlines only: leading spaces are a nested list item's depth, not padding.
    return rendered.strip("\n")


# Non-content namespaces. [[Category:X]] and [[File:X]] are page metadata, not
# navigable article links.
_NAMESPACE_PREFIXES = frozenset({
    "category", "file", "image", "media", "mediawiki", "module",
    "template", "help", "special", "talk", "user", "project",
})

# Language editions and sister projects. An Arch page links [[de:GRUB]] to bind
# its translation, not to point the reader at a different article.
#
# Used only when siteinfo is unreachable. The wiki's own interwikimap is
# authoritative: a static list rots, and a language Arch adds later would
# otherwise surface as a navigable article link.
_FALLBACK_INTERWIKI_PREFIXES = frozenset({
    "ar", "az", "bg", "bs", "ca", "cs", "da", "de", "el", "en", "es", "fa", "fi",
    "fr", "he", "hr", "hu", "id", "it", "ja", "ko", "lt", "nl", "no", "pl", "pt",
    "ro", "ru", "sk", "sl", "sr", "sv", "th", "tr", "uk", "vi",
    "zh-hans", "zh-hant", "zh-cn", "zh-tw",
    "wikipedia", "w", "wiktionary", "commons", "debian", "gentoo", "ubuntu",
    "freebsd", "kernel", "man", "arxiv", "rfc",
})

_FALLBACK_EXCLUDED_PREFIXES = _NAMESPACE_PREFIXES | _FALLBACK_INTERWIKI_PREFIXES


def fetch_siteinfo(timeout: int = 30) -> Dict:
    """Fetch the wiki's namespace and interwiki tables."""
    params = {
        "action": "query",
        "meta": "siteinfo",
        "siprop": SITEINFO_PROPS,
        "format": "json",
    }

    data = _fetch(params, timeout)

    if "error" in data:
        raise ValueError(f"Siteinfo API Error: {data['error'].get('info', data['error'])}")
    if "query" not in data:
        raise ValueError(f"Unexpected siteinfo response format: {data}")

    return data["query"]


# Errors that mean "the wiki did not answer", as opposed to a bug in this module.
# URLError and HTTPError are OSError subclasses; FileNotFoundError deliberately is
# not caught, so a missing offline fixture stays loud.
_SITEINFO_FAILURES = (URLError, TimeoutError, ConnectionError, json.JSONDecodeError, ValueError)

# Populated only on success. A transient failure must not be memoized: caching the
# fallback would silently reinstate the rotted list for the life of the process.
_derived_prefixes: Optional[frozenset] = None


def reset_prefix_cache() -> None:
    """Drop the memoized siteinfo derivation (used by tests)."""
    global _derived_prefixes
    _derived_prefixes = None


# ---------------------------------------------------------------------------
# Localized admonition templates
#
# A translated page does not write {{Warning}}. The Spanish Installation guide
# writes {{Note (Español)}}; the French one writes {{Attention}}, a redirect to
# Template:Warning (Français). Matching the four English names dropped 11 of 11
# admonitions on the Spanish page and 6 of 13 on the French one -- and warnings()
# returning [] is what AGENTS.md tells the agent means "the wiki says nothing
# here". A dropped {{Attention}} is a suppressed warning, presented as silence.
#
# The mapping is DERIVED, not declared. A ' (Lang)' suffix is stripped locally;
# a redirect alias is resolved by asking MediaWiki, exactly as the interwiki
# prefixes are derived from siteinfo rather than hard-coded (Amendment 1.4).
# ---------------------------------------------------------------------------

ADMONITION_TYPES = frozenset({"NOTE", "WARNING", "TIP", "CAUTION"})

# "Note (Español)" -> "Note". Nested parens do not occur in template titles.
_LANG_SUFFIX = re.compile(r"^(.+?)\s*\([^()]*\)$")

# Any template opening, capturing its name: "{{Note (Español)|" -> "Note (Español)".
_ANY_TEMPLATE_RE = re.compile(r"\{\{\s*([^|{}\n]+?)\s*(?=[|}])")

# Names that are not wiki pages and must never be sent as titles: the escapes
# {{=}} and {{!}}, magic words {{DISPLAYTITLE:...}}, and {{int:savechanges}}.
_NOT_A_TEMPLATE_TITLE = re.compile(r"[:#=|!{}\[\]]")

# MediaWiki accepts at most 50 titles per query.
_TITLES_PER_QUERY = 50

# Populated only on success, and only for names the wiki actually resolved.
# name.lower() -> "WARNING" | None (resolved, and not an admonition)
_template_aliases: Dict[str, Optional[str]] = {}


def reset_template_alias_cache() -> None:
    """Drop the memoized alias derivation (used by tests)."""
    _template_aliases.clear()


def canonical_admonition(name: str) -> Optional[str]:
    """
    The admonition type a template name denotes, by its own spelling alone.

    "Warning" -> "WARNING"; "Note (Español)" -> "NOTE"; "Astuce" -> None (that
    one is a redirect, and only the wiki knows where it points).
    """
    stripped = _LANG_SUFFIX.sub(r"\1", name.strip())
    upper = stripped.upper()
    return upper if upper in ADMONITION_TYPES else None


def fetch_template_aliases(names: List[str], cache_key: str, timeout: int = 30) -> Dict[str, Optional[str]]:
    """
    Ask MediaWiki where each template name redirects, in one batched request.

    Returns name.lower() -> admonition type, or None when the name resolves to
    something that is not an admonition. Raises on an unanswered query: callers
    must fail closed rather than report an English-only subset as complete.
    """
    if not names:
        return {}

    ordered = sorted(names)
    resolved: Dict[str, Optional[str]] = {name.lower(): None for name in ordered}

    batches = [ordered[i:i + _TITLES_PER_QUERY] for i in range(0, len(ordered), _TITLES_PER_QUERY)]
    for index, batch in enumerate(batches):
        suffix = "" if len(batches) == 1 else f"_{index + 1}"
        data = _fetch(
            {
                "action": "query",
                "titles": "|".join(f"Template:{name}" for name in batch),
                "redirects": "1",
                "format": "json",
            },
            timeout,
            key=f"aliases_{cache_key}{suffix}",
        )

        if "error" in data:
            raise ValueError(f"Template alias API Error: {data['error'].get('info', data['error'])}")
        if "query" not in data:
            raise ValueError(f"Unexpected template alias response format: {data}")

        for redirect in data["query"].get("redirects", []):
            source = redirect["from"].split(":", 1)[-1].lower()
            target = redirect["to"].split(":", 1)[-1]
            if source in resolved:
                resolved[source] = canonical_admonition(target)

    return resolved


# A missing offline fixture must be as loud here as a network failure: both mean
# "we do not know whether this page carries a warning."
_ALIAS_FAILURES = (URLError, TimeoutError, ConnectionError, OSError, json.JSONDecodeError, ValueError)


def admonition_types(wikitext: str, cache_key: str) -> Dict[str, Optional[str]]:
    """
    Map every top-level template name in `wikitext` to its admonition type.

    Names that spell themselves out are free. The rest are resolved once, cached
    across pages, and a failure raises: returning the English matches alone would
    be an empty-or-partial result the agent is told to read as the wiki's silence.
    """
    names = {
        name
        for _, _, name in _iter_top_level_templates(wikitext, _ANY_TEMPLATE_RE)
        if name and not _NOT_A_TEMPLATE_TITLE.search(name)
    }

    types: Dict[str, Optional[str]] = {}
    unresolved = []
    for name in names:
        canonical = canonical_admonition(name)
        if canonical:
            types[name] = canonical
        elif name in _template_aliases:
            types[name] = _template_aliases[name]
        else:
            unresolved.append(name)

    if unresolved:
        try:
            resolved = fetch_template_aliases(unresolved, cache_key)
        except _ALIAS_FAILURES as exc:
            raise ValueError(
                f"Cannot resolve template aliases for {cache_key!r}: {exc}. "
                f"Refusing to report an English-only subset of the warnings as complete."
            ) from exc
        _template_aliases.update(resolved)
        types.update(resolved)

    return types


def excluded_link_prefixes() -> frozenset:
    """
    Prefixes that mark a [[link]] as page metadata rather than navigation.

    Derived from the wiki's own tables so the set cannot rot. An explicit list,
    never a "looks like a language code" heuristic: silently dropping a real link
    is synthesis by omission, and silently keeping an interwiki link is synthesis
    by inclusion.

    Falls back to a static snapshot when siteinfo is unreachable. links() is a
    navigation aid, not a command source, so degrading beats failing the call --
    but the fallback is never cached, so the next call retries.
    """
    global _derived_prefixes
    if _derived_prefixes is not None:
        return _derived_prefixes

    try:
        query = fetch_siteinfo()
    except _SITEINFO_FAILURES as exc:
        logger.warning("siteinfo unavailable (%s); using static link-prefix snapshot", exc)
        return _FALLBACK_EXCLUDED_PREFIXES

    prefixes = set()

    # Every namespace except main (id 0), which is where articles live.
    for namespace in query.get("namespaces", {}).values():
        if namespace.get("id", 0) != 0 and namespace.get("*"):
            prefixes.add(namespace["*"].lower())
    for alias in query.get("namespacealiases", []):
        if alias.get("id", 0) != 0 and alias.get("*"):
            prefixes.add(alias["*"].lower())

    for entry in query.get("interwikimap", []):
        if entry.get("prefix"):
            prefixes.add(entry["prefix"].lower())

    # A wiki that returned nothing usable must not silently disable filtering.
    if not prefixes:
        logger.warning("siteinfo returned no prefixes; using static link-prefix snapshot")
        return _FALLBACK_EXCLUDED_PREFIXES

    _derived_prefixes = frozenset(prefixes)
    return _derived_prefixes


def parse_internal_links(
    wikitext: str,
    source_page: str,
    excluded_prefixes: Optional[frozenset] = None,
) -> List[InternalLink]:
    """
    Parse navigable internal wiki links from wikitext.

    Handles [[Target]], [[Target|Display]], [[Target#Anchor|Display]], and the
    same-page [[#Anchor]] form. Namespace and interwiki links are excluded, as
    are multi-parameter media links like [[File:x.png|thumb|caption]].
    """
    if excluded_prefixes is None:
        excluded_prefixes = excluded_link_prefixes()

    links = []

    for match in re.finditer(r"\[\[([^\[\]]+)\]\]", wikitext):
        target_part, separator, display_part = match.group(1).partition("|")

        target = target_part.strip()
        if target.startswith(":"):
            target = target[1:].strip()  # [[:Category:X]] renders as a link, still metadata

        if ":" in target:
            prefix = target.split(":", 1)[0].strip().lower()
            if prefix in excluded_prefixes:
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

    `content` is rendered for quoting; `content_raw` is the verbatim slice that
    `content_hash` attests, so the citation stays falsifiable against the wiki.
    """
    parse_data = fetch_wiki_parse(title)
    target_section, content_raw = _resolve_section(parse_data, anchor)
    content = render_section_wikitext(content_raw)

    return ExtractedBlock(
        title=parse_data["title"],
        url=make_wiki_url(parse_data["title"], anchor),
        revid=parse_data["revid"],
        timestamp=None,
        section_anchor=anchor,
        section_heading=target_section["line"],
        extraction_method="wikitext_character_offset",
        content=content,
        content_raw=content_raw,
        content_hash=hash_content(content_raw),
        content_hash_cleaned=hash_content(content)
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
            "content_hash_cleaned": block.content_hash_cleaned,
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

    Fails closed. A translated page writes {{Note (Español)}} or {{Attention}},
    so template names are resolved against the wiki before parsing. If they cannot
    be resolved this raises rather than returning the English-only subset, which
    the agent is told to read as "the wiki specifies no warnings here".

    Returns list of WarningBlock dicts.
    """
    parse_data = fetch_wiki_parse(title)
    page_wikitext = parse_data["wikitext"]["*"]
    revid = parse_data["revid"]

    # Resolved over the WHOLE page, never the section: the set of names queried
    # must depend only on the page, or an anchored call would ask a different
    # question than the recorded fixture answers.
    types = admonition_types(page_wikitext, title)

    if anchor:
        # The raw slice: this parses wikitext, and section().content is rendered.
        _, wikitext = _resolve_section(parse_data, anchor)
        url_base = make_wiki_url(parse_data["title"], anchor)
    else:
        wikitext = page_wikitext
        url_base = make_wiki_url(parse_data["title"])

    warning_blocks = parse_templates(wikitext, revid, types)
    
    return [
        {
            "type": w.type,
            "message": w.message,
            "message_raw": w.message_raw,
            "content_hash": w.content_hash,
            "message_hash_cleaned": w.message_hash_cleaned,
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
        # The raw slice: these parse wikitext, and .content is now rendered.
        wikitext = extracted.content_raw
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
