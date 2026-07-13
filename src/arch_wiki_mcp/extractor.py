#!/usr/bin/env python3
"""
Arch Wiki Constitutional Extractor
Deterministic, hash-stable extraction of wiki content with full provenance.
"""

import hashlib
import html
import logging
import re
import unicodedata
from dataclasses import dataclass, asdict, fields
from functools import lru_cache
from typing import AbstractSet, Dict, List, Optional, Tuple
from urllib.error import URLError
from urllib.request import urlopen, Request
from urllib.parse import parse_qs, quote, unquote, urlencode, urlparse
import json
import os
from arch_wiki_mcp import REPOSITORY_URL, __version__

# stderr by default, which keeps JSON-RPC on stdout clean.
logger = logging.getLogger(__name__)

# Stated once. The host was written out four times and then reverse-engineered a
# fifth, out of API_ENDPOINT, under a comment claiming the two could not disagree --
# which was true of exactly one of the four.
WIKI_HOST = "wiki.archlinux.org"
WIKI_BASE = f"https://{WIKI_HOST}"
TITLE_PATH = "/title/"

API_ENDPOINT = f"{WIKI_BASE}/api.php"
# The only thing the Arch Wiki's operators ever see of us. It named a version the
# package had left behind releases ago, and pointed at github.com/user/arch-wiki-mcp
# -- a repository that does not exist. Both are derived now, so neither can lag.
USER_AGENT = f"ArchWikiMCP/{__version__} (Constitutional Extractor; +{REPOSITORY_URL})"

# Shared with tests/record_fixtures.py: the recorder must request exactly what
# fetch_siteinfo() requests, or the recorded fixture answers a different question.
SITEINFO_PROPS = "namespaces|namespacealiases|interwikimap"


class ArchWikiError(ValueError):
    """
    Base for every extraction failure. Never raised directly -- raise a subclass,
    so the failure reaches the agent with a category it can act on.

    ValueError, not Exception: callers (and tests) have caught ValueError since
    before these types existed, and a failure that stops being caught is a
    failure that stops fail-closing. The subclasses add a category the MCP layer
    can report; they do not change what is raised to anyone already catching it.

    No `code` of its own: an unclassified extraction failure is one we forgot to
    classify, so it falls through to `internal_error` and is logged as ours,
    rather than reaching an agent under a reassuring name that means nothing.
    """


class PageNotFoundError(ArchWikiError):
    """The wiki has no such page. Distinct from an outage: the answer is 'no page'."""

    code = "page_not_found"


class SectionNotFoundError(ArchWikiError):
    """The page exists; the requested anchor does not."""

    code = "section_not_found"


class EvidenceResolutionError(ArchWikiError):
    """
    The page and section exist, but their text cannot be quoted with provenance
    intact -- a transcluded section whose wikitext lives elsewhere, or an offset
    that did not land on its heading. Quoting anyway would cite the wrong text
    under a valid-looking hash, so this is a refusal, not a miss.
    """

    code = "evidence_unresolvable"


class UpstreamApiError(ArchWikiError):
    """MediaWiki errored or answered in a shape we do not recognise."""

    code = "upstream_api_error"


class MalformedWikiUrlError(ArchWikiError):
    """
    A well-formed string that is not a wiki URL we can resolve to a title.

    Distinct from server.InvalidParamsError, which is a *schema* fault -- a
    missing or wrong-typed argument, where nothing ran. This one ran: the value
    satisfied the schema, the tool tried it, and the URL would not parse. So the
    agent sees it and can self-correct by supplying a plain title.
    """

    code = "malformed_wiki_url"


def _unwrap(data: Dict, root: str, context: str) -> Dict:
    """
    Classify a MediaWiki envelope, or return the payload under `root`.

    Every fetch answers in the same envelope, so every fetch used to repeat this
    check -- and they drifted: two classified their failures and four raised a
    bare ValueError, which the MCP layer could only report as `internal_error`.
    An outage on the admonition-alias path therefore told the agent the server
    was broken rather than that the wiki was unreachable. Classifying here means
    a new fetch cannot forget to, because it never sees an unclassified envelope.
    """
    if "error" in data:
        error = data["error"]
        detail = error.get("info", error)
        # MediaWiki reports "this page does not exist" as an ordinary API error.
        # Undistinguished, a missing page and an outage arrive as one exception,
        # and a caller cannot tell "the wiki says no" from "the wiki did not
        # answer" -- the two conclusions an agent must never conflate.
        if error.get("code") == "missingtitle":
            raise PageNotFoundError(f"{context} API Error: {detail}")
        raise UpstreamApiError(f"{context} API Error: {detail}")

    if root not in data:
        raise UpstreamApiError(f"Unexpected {context} response format: {data}")

    return data[root]


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
    url: str  # Canonical page URL: follows the page, shows what the wiki says now
    revision_url: str  # Pinned to `revid` -- the revision whose wikitext is hashed here
    revision_wikitext_url: str  # That revision's wikitext: the bytes content_hash covers
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
    # Null when the template spelled its own type ({{Warning}}, {{Note (Español)}}).
    # Set when `type` was learned from a redirect, which the article's revid does
    # not cover: see TemplateResolution.
    alias: Optional[str] = None  # Redirect that carried the type, normalized: "Attention"
    alias_target: Optional[str] = None  # Where it points: "Template:Warning (Français)"
    alias_revid: Optional[int] = None  # Revision of the REDIRECT page itself


@dataclass(frozen=True)
class TemplateResolution:
    """
    What a template name denotes, and -- if we had to ask the wiki -- how we know.

    `type` is None for a name that resolved to something that is not an
    admonition ({{ic}}, {{Pkg}}); that is a real answer, and it is cached.

    A name like {{Attention}} spells out nothing: its type comes from
    Template:Attention being a redirect to Template:Warning (Français). Nothing in
    the article attests that. Retarget the redirect and the block's `type` flips
    with no change to the article's revid, message_raw, or content_hash.

    So we pin the redirect. `alias_revid` is the revision of the REDIRECT page --
    the page a retarget edits -- and not of its destination. MediaWiki resolves
    titles before prop=revisions runs, so `redirects=1` reports the destination's
    revid, which a retarget leaves untouched. It is the wrong number to trust,
    and it must be fetched in a separate query with redirects off.
    """
    type: Optional[str] = None
    alias: Optional[str] = None
    alias_target: Optional[str] = None
    alias_revid: Optional[int] = None


@dataclass
class InternalLink:
    """Extracted internal wiki link."""
    target_page: str
    display_text: Optional[str]
    source_page: str
    anchor: Optional[str] = None


@dataclass
class SearchResult:
    """
    One page the wiki's own search returned. A pointer, never evidence.

    `snippet` carries no revid and no hash, and the wiki may re-index it at any
    time. It exists to help choose which page to open; nothing in it may be
    quoted to a user. To cite anything, call section(), commands() or warnings()
    on `title`.
    """
    title: str
    pageid: int
    snippet: str  # Plain text: the wiki's match context, markup resolved
    url: str
    match: str  # "title" (exact page) or "text" (full-text hit)


def make_wiki_url(title: str, anchor: Optional[str] = None) -> str:
    """
    The canonical page URL. Follows the page: what it serves is whatever the wiki
    says *now*, which is what a reader usually wants and what an auditor must not
    rely on. For the latter, see make_revision_url().
    """
    encoded_title = quote(title.replace(" ", "_"), safe=":/#")
    url = f"{WIKI_BASE}{TITLE_PATH}{encoded_title}"
    if anchor:
        url += f"#{quote(anchor, safe=':/#')}"
    return url


def make_revision_url(revid: int, anchor: Optional[str] = None) -> str:
    """
    The URL for one revision, via MediaWiki's oldid.

    Evidence used to carry the canonical URL and the revid side by side, and the
    README called that "a direct link to the specific revision". It was not: the
    URL followed the page. Quote a warning today, follow the link a month later,
    and the wiki serves whatever the page says then -- possibly no warning at all.
    The revid was in the payload the whole time and the URL simply did not use it,
    which left a citation falsifiable in principle and unfalsifiable in practice.

    oldid alone identifies the revision -- no title needed, so a page renamed
    after extraction still resolves, which is exactly when pinning matters most.

    Precisely what is pinned: the revision's *wikitext*, which is what our hashes
    cover. The page this renders still transcludes templates at their current
    versions, so the rendered view is not frozen. To check a hash, fetch the
    wikitext (see make_revision_wikitext_url) rather than this page -- and say "pinned",
    not "immutable", because only one of the two is true.
    """
    url = f"{WIKI_BASE}/index.php?oldid={revid}"
    if anchor:
        url += f"#{quote(anchor, safe=':/#')}"
    return url


def extract_title_from_url(title_or_url: str) -> str:
    """
    Resolve a title from an Arch Wiki URL, or pass a plain title through.
    The exact inverse of make_wiki_url(), and lives beside it for that reason.

    Parsed structurally rather than sliced. The old version split on "/title/",
    took what followed, and never decoded it -- so a translated page pasted from a
    browser (.../title/Installation_guide_%28Fran%C3%A7ais%29) reached the wiki as
    the literal title "Installation_guide_%28Fran%C3%A7ais%29", which does not
    exist. The tool then fail-closed and reported the page as missing. It was not
    missing: we asked the wrong question and relayed the wiki's silence as fact,
    which is the one failure this project exists to prevent.

    It also matched "title=" anywhere in the query and never checked the host, so
    https://evil.example/title/GRUB passed as an Arch Wiki page.

    Refusal, never a guess: a URL we cannot resolve must not become a title we
    invented, or the wrong page gets quoted under a valid-looking hash.
    """
    # Stripped and scheme-parsed rather than startswith("http"): a pasted URL that
    # arrived with a leading space, or spelled HTTPS://, failed that test, skipped
    # the URL branch, and was handed to the wiki *as a title* -- reopening the very
    # bug above through the whitespace door.
    title_or_url = title_or_url.strip()
    parsed = urlparse(title_or_url)

    if parsed.scheme not in ("http", "https"):
        # A plain title is whatever the caller typed. Decoding it would corrupt a
        # page whose name genuinely contains a percent sign ("100%_CPU").
        return title_or_url

    # hostname, not netloc: lowercased, port stripped, and an exact match -- so
    # "wiki.archlinux.org.evil.example" does not pass for the wiki.
    if parsed.hostname != WIKI_HOST:
        raise MalformedWikiUrlError(
            f"Not an Arch Wiki URL (host {parsed.hostname!r}, expected {WIKI_HOST!r}): "
            f"{title_or_url}"
        )

    if parsed.path.startswith(TITLE_PATH):
        # A path: percent-decoded, but "+" is a literal plus, not a space.
        title = unquote(parsed.path[len(TITLE_PATH):])
    else:
        # A query: parse_qs percent-decodes *and* reads "+" as a space, which is
        # what a query string means by it. Splitting on "title=" by hand did
        # neither, and matched "not_title=" too.
        candidates = parse_qs(parsed.query, keep_blank_values=True).get("title", [])
        if len(candidates) != 1:
            # The URL most likely to be pasted back is one we handed out: a
            # revision URL names a revid, not a title. Say so, rather than leaving
            # an agent to wonder what it got wrong.
            if "oldid" in parse_qs(parsed.query):
                raise MalformedWikiUrlError(
                    f"That is a revision URL, which names a revid and not a title. "
                    f"Pass the page title instead: {title_or_url}"
                )
            raise MalformedWikiUrlError(
                f"URL names {len(candidates)} titles, need exactly one: {title_or_url}"
            )
        title = candidates[0]

    # MediaWiki treats an underscore and a space as the same character in a title.
    title = title.replace("_", " ").strip()
    if not title:
        raise MalformedWikiUrlError(f"URL names no title: {title_or_url}")

    return title


def make_revision_wikitext_url(revid: int) -> str:
    """
    The revision's wikitext -- the bytes content_hash is computed over -- at a URL a
    script can actually fetch.

    This is the URL that makes a citation checkable, so it has to work unattended.
    It used to be index.php?action=raw, which is the correct MediaWiki idiom and
    which a browser resolves fine -- but wiki.archlinux.org answers a script there
    with an anti-bot interstitial: HTTP *200*, an HTML challenge page, no wikitext.
    An auditor's script would have hashed the challenge, seen a mismatch, and
    concluded a good citation was forged. That is the worst error this project can
    make, and it was sitting in the one field whose entire job is to prevent it.

    api.php is not gated, and is the route the extractor itself uses -- so the URL we
    hand an auditor is the URL we trust ourselves. It answers JSON; the wikitext is
    at .parse.wikitext["*"], which is why this is not called a "raw" URL. No anchor:
    a source document has no fragments to jump to.
    """
    return f"{API_ENDPOINT}?action=parse&oldid={revid}&prop=wikitext&format=json"


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
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        # _unwrap classifies what the wiki *says*; this classifies its *silence*.
        # Left raw, the paradigm "the wiki did not answer" -- an outage, a dead
        # socket, a truncated body -- escaped untyped and the MCP layer could
        # only call it `internal_error`: a bug in us. It is the opposite. The
        # remediation differs too (retry the wiki vs. fix this server), which is
        # the whole reason the two must not arrive as one exception.
        raise UpstreamApiError(f"Arch Wiki did not answer: {exc}") from exc
    # FileNotFoundError from _fetch_offline is deliberately not caught: a missing
    # fixture is our bug, and must stay loud rather than pose as an outage.


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

    parse_data = _unwrap(data, "parse", "parse")
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
        raise EvidenceResolutionError(
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
            raise EvidenceResolutionError(
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
            raise EvidenceResolutionError(
                f"Section '{anchor}' in page '{title}' did not resolve to a heading "
                f"(offset {sect['byteoffset']} landed on {content[:40]!r})"
            )

        return sect, content

    raise SectionNotFoundError(f"Section with anchor '{anchor}' not found in page '{title}'")


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

# MediaWiki treats <nowiki> as a strip marker: nothing inside it is expanded, and
# an HTML comment inside it is displayed rather than removed. We used to delete
# comments, drop the tags, and then expand the templates the tags were protecting
# -- so {{ic|<nowiki>{{ic|text}}</nowiki>}} rendered as "text" where the wiki shows
# the literal "{{ic|text}}", and the Iwd dbus config lost the comment lines the
# wiki displays. The payload is lifted out before any of that runs and put back
# after, byte for byte.
_NOWIKI_SPAN = re.compile(r"<nowiki>(.*?)</nowiki>", re.DOTALL | re.IGNORECASE)
# 'nowiki' keeps this distinct from render_section_wikitext's \x00<digits>\x00
# template sentinels, which share the delimiter but never the payload.
_NOWIKI_SENTINEL = re.compile("\x00nowiki(\\d+)\x00")


def _hide_nowiki(text: str) -> Tuple[str, List[str]]:
    """
    Lift <nowiki> payloads out of `text`, leaving inert sentinels behind.

    The second of two layers, and both are load-bearing. mask_nowiki() stops the
    *scanners* finding structure inside a nowiki span -- a quoted {{bc}} is not a
    command. This stops the *cleaners* rewriting a payload handed to them: a code
    template's body, or the interior of an inline {{ic|...}}, which is never
    masked because it resolves in place. Removing this one turns
    {{ic|<nowiki>{{ic|text}}</nowiki>}} back into "text".
    """
    protected: List[str] = []

    def _stash(match: "re.Match") -> str:
        protected.append(match.group(1))
        return f"\x00nowiki{len(protected) - 1}\x00"

    return _NOWIKI_SPAN.sub(_stash, text), protected


def _restore_nowiki(text: str, protected: List[str]) -> str:
    """
    Put each payload back exactly as the wiki wrote it.

    Must run after link resolution and list rendering, not just after markup
    stripping: a sentinel carries no [[ or ]], so those passes leave it alone,
    and restoring early would expose the payload to them.
    """
    if not protected:
        return text
    return _NOWIKI_SENTINEL.sub(lambda m: protected[int(m.group(1))], text)
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

    Expects <nowiki> payloads to have been lifted out by _hide_nowiki already:
    a comment or a template inside one is the wiki's own literal text, and
    nothing here may touch it. The caller restores them once every pass has run.
    """
    text = _HTML_COMMENT.sub("", text)
    text = _NOWIKI_TAG.sub("", text)  # a stray, unpaired tag; the spans are gone
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
    hidden, protected = _hide_nowiki(raw)
    text, placeholders = _strip_inline_markup(hidden, mark_placeholders=True)

    # Pacman writes ''<nowiki>http://...</nowiki>'': the italics wrap the span, so
    # the placeholder token IS the sentinel. Restore it, or the declared
    # placeholder is an internal marker the reader cannot find in the command.
    placeholders = [_restore_nowiki(token, protected) for token in placeholders]

    # Restore before trimming: "{{bc|<nowiki>\ncode\n</nowiki>}}" wraps its payload
    # in newlines that the fence supplies, and they are not part of the code.
    return _restore_nowiki(text, protected).strip("\n"), placeholders


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


def _is_preformatted(source_line: str) -> bool:
    """A space-prefixed source line is preformatted code; its indent is content."""
    return source_line[:1] in (" ", "\t") and bool(source_line.strip())


def _dedent_orphan_indent(rendered: List[Tuple[str, str]]) -> List[str]:
    """
    Remove an indent that _render_list_markers invented, and only that.

    The Installation guide writes "{{Tip|#** The ISO uses ...}}": the marker's
    depth is relative to a list that lives OUTSIDE the template. Extracted on its
    own, the tip has no parent, and the four spaces generated for it are read by
    markdown as a code block -- in the one field §6 requires an agent to quote to
    a user. Prose rendered as a shell transcript is what got examples() deleted.

    A preformatted line takes no part. Its leading space came from the wiki, not
    from us: "#** see:\\n # pacman -Fy" measured a common indent of one, and
    shifting the block by it put a bare '#' at column 0 -- reintroducing the
    root-prompt lookalike this whole rule exists to prevent. Such lines neither
    set the common indent nor receive the shift.

    Only a *common* indent goes, so a line that is genuinely shallower keeps every
    sibling's relative depth and real nesting inside a message survives untouched.
    """
    movable = [
        line for source, line in rendered
        if line.strip() and not _is_preformatted(source)
    ]
    if not movable:
        return [line for _, line in rendered]

    common = min(len(line) - len(line.lstrip(" ")) for line in movable)
    if not common:
        return [line for _, line in rendered]

    return [
        line if _is_preformatted(source) or not line.strip() else line[common:]
        for source, line in rendered
    ]


def _clean_message(raw: str) -> str:
    """
    Render a warning/note body down to prose a user can read.

    The consuming agent is required to quote these to the user, so shipping raw
    {{ic|...}} and [[links]] made the mandated response shape unreadable. The
    verbatim text is preserved alongside as message_raw, and that is what the
    content_hash covers.

    Whitespace is handled at both ends for the same reason it is in
    _render_admonition: a leading space in "{{Note| body}}" sits mid-line in the
    source and means nothing, while the leading spaces _render_list_markers emits
    are a nested item's depth. Stripping both promoted a nested first item a level
    above its own siblings.
    """
    hidden, protected = _hide_nowiki(raw.lstrip(" \t"))
    text, _ = _strip_inline_markup(hidden)
    text = _resolve_links(text)

    # Each source line is carried alongside what it rendered to: only the source
    # can say whether a leading space is a list depth we generated or preformatted
    # code the wiki wrote.
    rendered = [(line, _render_list_markers(line)) for line in text.split("\n")]
    text = "\n".join(_dedent_orphan_indent(rendered))

    return _restore_nowiki(text.strip("\n").rstrip(), protected)


def _parse_single_template(
    content: str, types: Dict[str, TemplateResolution], revid: Optional[int]
) -> Optional[WarningBlock]:
    """
    Parse the interior content of a template and return a WarningBlock if valid.

    Splits on the first TOP-LEVEL pipe. A naive split("|", 1) truncated any
    message containing a pipe inside a nested {{ic|a|b}} or [[link|text]].

    `types` maps a template name to what it denotes, and to the redirect that
    said so. A translated page spells it {{Note (Español)}} or {{Attention}}, so
    the name alone is not enough -- and when a redirect supplied the type, the
    block carries that redirect so a client can check it.
    """
    parts = _split_template_params(content, 1)
    raw_name = parts[0].strip()

    resolution = types.get(raw_name.lower())
    if resolution is None:
        resolution = TemplateResolution(type=canonical_admonition(raw_name))
    if resolution.type not in ADMONITION_TYPES:
        return None

    message_raw = _strip_param_name(parts[1], {"1"}).strip() if len(parts) > 1 else ""
    message = _clean_message(message_raw)

    return WarningBlock(
        type=resolution.type,
        message=message,
        message_raw=message_raw,
        content_hash=hash_content(message_raw),
        message_hash_cleaned=hash_content(message),
        revid=revid,
        alias=resolution.alias,
        alias_target=resolution.alias_target,
        alias_revid=resolution.alias_revid,
    )


def parse_templates(
    wikitext: str,
    revid: Optional[int] = None,
    types: Optional[Dict[str, TemplateResolution]] = None,
) -> List[WarningBlock]:
    """
    Robustly parse MediaWiki templates for warnings, notes, tips.
    Handles nesting, multi-params, and |1= syntax.

    `types` maps template names to what they denote on a translated page. Without
    it, only names that spell themselves out are recognized -- enough for English,
    and blind to {{Attention}}. warnings() supplies it; see admonition_types().
    """
    warnings = []
    types = types or {}

    # Scan the mask, slice the source. "<nowiki>{{Warning|rm -rf /}}</nowiki>" is a
    # page documenting template syntax, not a warning the article issues -- and a
    # fabricated WARNING is the most dangerous thing this tool can return.
    scan = mask_nowiki(wikitext)

    i = 0
    while i < len(scan):
        start_idx = scan.find("{{", i)
        if start_idx == -1:
            break

        end_idx = _find_template_end(scan, start_idx)
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
    scan: str, wikitext: str, revid: Optional[int]
) -> Tuple[List[CodeBlock], List[Tuple[int, int]]]:
    """
    Extract {{bc}} (block code) and {{hc}} (file contents with a header).

    These carry essentially all real Arch Wiki code. Returns the blocks and the
    spans they consumed, so the indented scanner can skip them.

    `scan` is `wikitext` with <nowiki> blanked, and is what the search runs on;
    every payload is sliced from `wikitext`, which the mask keeps offset-aligned.
    A {{bc}} the wiki merely quotes must never become a command.
    """
    blocks: List[CodeBlock] = []
    spans: List[Tuple[int, int]] = []

    for start, end, name in _iter_top_level_templates(scan, _CODE_TEMPLATE_RE):
        spec = CODE_TEMPLATES[name]
        params = _split_template_params(wikitext[start + 2:end - 2], spec.max_splits)

        index = 1
        header = None
        if spec.header_names is not None:
            header_raw = _strip_param_name(params[index], spec.header_names) if len(params) > index else ""
            header, _ = _clean_payload(header_raw)
            index += 1

        raw = _strip_param_name(params[index], spec.body_names) if len(params) > index else ""

        block = _make_block(raw, spec.block_type, spec.source_pattern, revid, header=header)

        # A bodiless {{bc}} yields content "" attested by the SHA-256 of the empty
        # string -- an empty command block an agent would present as evidence, and
        # a hash that verifies against nothing. The wiki specifies no command here,
        # and [] is how this MCP says that. The span is still consumed so the
        # indented scanner does not rescan it.
        if block.content.strip():
            blocks.append(block)
        spans.append((start, end))

    return blocks, spans


def _mask_spans(wikitext: str, spans: List[Tuple[int, int]]) -> str:
    """
    Blank out consumed spans, preserving newlines so line structure survives.

    Space-prefixed lines inside a {{bc}}/{{hc}} body would otherwise be scanned a
    second time and re-emitted as phantom indented blocks.

    Length-preserving: offsets into the result index the original text, so a
    scanner may run on the mask and slice from the source.
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


def _union_spans(spans: List[Tuple[int, int]]) -> List[Tuple[int, int]]:
    """Sorted, non-overlapping. A template body may contain a whole <nowiki> span."""
    merged: List[Tuple[int, int]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def nowiki_spans(wikitext: str) -> List[Tuple[int, int]]:
    """Where each <nowiki>...</nowiki> sits, tags included."""
    return [(m.start(), m.end()) for m in _NOWIKI_SPAN.finditer(wikitext)]


def mask_nowiki(wikitext: str) -> str:
    """
    `wikitext` with every <nowiki> span blanked, same length, newlines kept.

    Every scanner must run on this rather than on the source. <nowiki> means "do
    not interpret", so a {{bc}} inside it is not a code block, a {{Warning}}
    inside it is not a warning, and a [[link]] inside it is not a link -- they
    are characters the wiki prints. Cleaning the payload afterwards is too late:
    by then the scanner has already found a command in a page's documentation of
    template syntax, and handed it over carrying a hash.
    """
    return _mask_spans(wikitext, nowiki_spans(wikitext))


def parse_code_blocks(wikitext: str, revid: Optional[int] = None) -> List[CodeBlock]:
    """
    STRICT EXTRACTION: only formal, block-level wiki code constructs.

    - {{bc}} / {{hc}} templates
    - Indented blocks (space-prefixed)

    Inline {{ic}} is deliberately excluded: it marks paths, flags and package
    names, not runnable commands.

    <nowiki> disables wikitext interpretation entirely, so a span of it yields no
    command -- neither a quoted {{bc}} nor an indented line inside it.
    """
    hidden = nowiki_spans(wikitext)
    blocks, spans = _extract_code_templates(mask_nowiki(wikitext), wikitext, revid)
    consumed = _union_spans(spans + hidden)
    blocks.extend(_extract_indented_blocks(_mask_spans(wikitext, consumed).split("\n"), revid))
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

    # _classify_template only routes here when this resolves, but that guard sits
    # in another function: re-check rather than trust it at a distance. Not an
    # assert -- those compile out under -O, and this must never label silently.
    canonical = canonical_admonition(name)
    if canonical is None:
        raise ValueError(f"not an admonition template: {name!r}")

    label = f"**{_ADMONITIONS[canonical.lower()]}:**"
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
    hidden, protected = _hide_nowiki(line)

    if line[:1] in (" ", "\t") and line.strip():
        text, _ = _strip_inline_markup(hidden, mark_placeholders=True)
        return _restore_nowiki(text, protected)

    text, _ = _strip_inline_markup(hidden)

    heading = _HEADING.match(text)
    if heading:
        return _restore_nowiki(f"{'#' * len(heading.group(1))} {heading.group(2)}", protected)

    return _restore_nowiki(_render_list_markers(_resolve_links(text)), protected)


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

    # Classify on the mask. A {{bc}} the wiki quotes inside <nowiki> is prose that
    # happens to look like a template: rendering it as a fence turns a page's
    # documentation of syntax into a command block an agent may hand to a user.
    scan = mask_nowiki(wikitext)

    templates = [(start, end, name) for start, end, name in _iter_top_level_templates(scan, _ANY_TEMPLATE_RE)]

    # Only top-level <nowiki>: one inside a template body is that body's business,
    # and _clean_payload protects it there. `payload` is carried, never re-sliced,
    # because the tags match case-insensitively and are not a fixed width.
    items: List[Tuple[int, int, Optional[str], Optional[str]]] = [
        (start, end, name, None) for start, end, name in templates
    ]
    items += [
        (m.start(), m.end(), None, m.group(1))
        for m in _NOWIKI_SPAN.finditer(wikitext)
        if not any(s < m.start() < e for s, e, _ in templates)
    ]
    items.sort(key=lambda item: item[0])

    blocks: List[Tuple[str, bool]] = []
    masked: List[str] = []
    position = 0
    for start, end, name, payload in items:
        if name is None:  # a <nowiki> span: its payload is literal, verbatim
            rendered, is_block = payload or "", False
        else:
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

    return _unwrap(data, "query", "siteinfo")


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
# name.lower() -> TemplateResolution. A resolution whose .type is None means
# "resolved, and not an admonition" ({{ic}}, {{Pkg}}) -- a real answer, cached.
_template_aliases: Dict[str, TemplateResolution] = {}


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


def _batched(titles: List[str]) -> List[List[str]]:
    return [titles[i:i + _TITLES_PER_QUERY] for i in range(0, len(titles), _TITLES_PER_QUERY)]


def fetch_redirect_revids(titles: List[str], cache_key: str, timeout: int = 30) -> Dict[str, int]:
    """
    The current revision of each redirect page, keyed by its full title.

    Deliberately queried WITHOUT redirects=1. With it, MediaWiki resolves the
    title first and hands back the destination's revid -- a page a retarget never
    touches. The revision that moves when someone repoints {{Attention}} is the
    revision of Template:Attention, and this is the only way to read it.
    """
    revids: Dict[str, int] = {}
    for index, batch in enumerate(_batched(sorted(titles))):
        suffix = "" if len(titles) <= _TITLES_PER_QUERY else f"_{index + 1}"
        data = _fetch(
            {
                "action": "query",
                "titles": "|".join(batch),
                "prop": "revisions",
                "rvprop": "ids",
                "format": "json",
            },
            timeout,
            key=f"aliasrevs_{cache_key}{suffix}",
        )

        query = _unwrap(data, "query", "redirect revision")

        for page in query.get("pages", {}).values():
            revisions = page.get("revisions")
            if revisions:
                revids[page["title"]] = revisions[0]["revid"]

    return revids


def fetch_template_aliases(names: List[str], cache_key: str, timeout: int = 30) -> Dict[str, TemplateResolution]:
    """
    Ask MediaWiki what each template name denotes, and pin how we learned it.

    Returns name.lower() -> TemplateResolution. Raises on an unanswered query:
    callers must fail closed rather than report an English-only subset as
    complete.

    Two queries, not one, and the second only when a name actually redirects to
    an admonition. An English page resolves {{ic}} and {{Pkg}} to "not an
    admonition" and stops there, paying nothing. Only a page that leans on a
    redirect for a safety-critical type pays for attesting it.
    """
    if not names:
        return {}

    ordered = sorted(names)
    resolved: Dict[str, TemplateResolution] = {name.lower(): TemplateResolution() for name in ordered}
    aliases: Dict[str, Tuple[str, str, str]] = {}  # lowered source -> (source title, target title, type)

    batches = _batched(ordered)
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

        query = _unwrap(data, "query", "template alias")

        for redirect in query.get("redirects", []):
            source = redirect["from"].split(":", 1)[-1].lower()
            target = redirect["to"].split(":", 1)[-1]
            admonition = canonical_admonition(target)
            if source in resolved and admonition:
                aliases[source] = (redirect["from"], redirect["to"], admonition)

    if aliases:
        revids = fetch_redirect_revids([source for source, _, _ in aliases.values()], cache_key, timeout)
        for source, (source_title, target_title, admonition) in aliases.items():
            revid = revids.get(source_title)
            if revid is None:
                # We know this page carries a WARNING and cannot say why. Silence
                # would be worse: fail closed, exactly as an unanswered query does.
                # The page and alias both exist -- what cannot be produced is the
                # provenance -- so this is EvidenceResolutionError, not an outage.
                raise EvidenceResolutionError(
                    f"No revision for redirect {source_title!r}: cannot attest that it "
                    f"denotes {admonition}."
                )
            resolved[source] = TemplateResolution(
                type=admonition,
                alias=source_title.split(":", 1)[-1],
                alias_target=target_title,
                alias_revid=revid,
            )

    return resolved


# A missing offline fixture must be as loud here as a network failure: both mean
# "we do not know whether this page carries a warning."
_ALIAS_FAILURES = (URLError, TimeoutError, ConnectionError, OSError, json.JSONDecodeError, ValueError)


def admonition_types(wikitext: str, cache_key: str) -> Dict[str, TemplateResolution]:
    """
    Map every top-level template name in `wikitext` to what it denotes.

    Names that spell themselves out are free, and self-attesting: the spelling is
    in the wikitext the article's revid already covers. The rest are resolved once
    against the wiki, cached across pages, and carry the redirect they came from.
    A failure raises: returning the English matches alone would be an
    empty-or-partial result the agent is told to read as the wiki's silence.
    """
    names = {
        name
        for _, _, name in _iter_top_level_templates(mask_nowiki(wikitext), _ANY_TEMPLATE_RE)
        if name and not _NOT_A_TEMPLATE_TITLE.search(name)
    }

    types: Dict[str, TemplateResolution] = {}
    unresolved = []
    for name in names:
        canonical = canonical_admonition(name)
        if canonical:
            types[name] = TemplateResolution(type=canonical)
        elif name in _template_aliases:
            types[name] = _template_aliases[name]
        else:
            unresolved.append(name)

    if unresolved:
        try:
            resolved = fetch_template_aliases(unresolved, cache_key)
        except _ALIAS_FAILURES as exc:
            # Re-raise as the *same* category, not a bare ValueError. ArchWikiError
            # subclasses ValueError -- which _ALIAS_FAILURES lists -- so this arm
            # caught the very types _unwrap had just raised and flattened them,
            # losing the code and re-opening the conflation on precisely the path
            # the classifier was written for. An outage here means "retry the
            # wiki"; an unresolvable alias means "do not". They must stay apart.
            category = type(exc) if isinstance(exc, ArchWikiError) else UpstreamApiError
            raise category(
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

    A [[link]] the wiki wrapped in <nowiki> is the characters of a link, printed.
    It navigates nowhere, and offering it as navigation invents a citation.
    """
    if excluded_prefixes is None:
        excluded_prefixes = excluded_link_prefixes()

    links = []

    for match in re.finditer(r"\[\[([^\[\]]+)\]\]", mask_nowiki(wikitext)):
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


# MediaWiki's own highlight markup, and the only unescaped HTML it injects into a
# snippet. Everything else there arrives entity-escaped.
_SEARCHMATCH_SPAN = re.compile(r"</?span[^>]*>")


def clean_snippet(raw: str) -> str:
    """
    Render a search snippet down to plain text on one line.

    It arrived as MediaWiki's highlight HTML wrapped around raw wikitext:
    '[[de:<span class="searchmatch">GRUB</span>]]'. Handed to an agent, that is
    markup to quote or a link to follow, and it is neither -- a snippet carries
    no revid and no hash. Rendering it is not attesting it; see SearchResult.

    A snippet is a TRUNCATED fragment, so its markup may be cut mid-token:
    "a:C++|C++]]. Zosta" has no opening '[[' to match and keeps its brackets.
    Balanced markup resolves; a severed token stays as the wiki sent it. That is
    the honest outcome, and the reason a snippet may never be quoted.
    """
    text = _SEARCHMATCH_SPAN.sub("", raw)
    text = html.unescape(text)

    hidden, protected = _hide_nowiki(text)
    text, _ = _strip_inline_markup(hidden)
    text = _resolve_links(text)
    text = _restore_nowiki(text, protected)

    # One line: a snippet is a fragment, and its newlines were never structure.
    return " ".join(text.split())


def _search_hits(query: str, limit: int, what: str, timeout: int, key: Optional[str] = None) -> List[Dict]:
    """One list=search request. Raises rather than reporting a partial answer."""
    data = _fetch(
        {
            "action": "query",
            "list": "search",
            "srsearch": query,
            "srlimit": limit,
            "srwhat": what,
            "format": "json",
        },
        timeout,
        key=key,
    )

    query = _unwrap(data, "query", "search")
    return _unwrap(query, "search", "search results")


def search(query: str, limit: int = 10, timeout: int = 30) -> List[Dict]:
    """
    MCP Tool: Search Arch Wiki using MediaWiki search API.

    Two requests, mirroring what the wiki's own search box does: the exact-title
    match first if there is one, then the full-text hits in the wiki's order.

    srwhat has no default on this wiki, and the API then searches TITLES ONLY.
    search("wifi not working") returned [] while the wiki held 47 matching pages
    -- and [] is this MCP's way of saying the wiki specifies nothing. The
    discovery entry point was manufacturing silence, the same harm the rest of
    the contract exists to prevent, one layer earlier.

    Full text alone is not the fix either: it buries exact titles, so
    search("GRUB") no longer finds GRUB. Asking both questions is what the wiki
    does. We do not re-rank: each list keeps the order the wiki returned it in,
    and the exact match simply precedes the rest.

    Returns list of SearchResult dicts.
    """
    exact = _search_hits(query, 1, "nearmatch", timeout, key=f"nearmatch_{query}")
    full_text = _search_hits(query, limit, "text", timeout)

    seen = {hit["pageid"] for hit in exact}
    ordered = [(hit, "title") for hit in exact]
    ordered += [(hit, "text") for hit in full_text if hit["pageid"] not in seen]

    return [
        asdict(SearchResult(
            title=hit["title"],
            pageid=hit["pageid"],
            snippet=clean_snippet(hit.get("snippet", "")),
            url=make_wiki_url(hit["title"]),
            match=match,
        ))
        for hit, match in ordered[:limit]
    ]


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
        # `url` here, `source_url` in commands/warnings/links: an inconsistency
        # this predates and does not fix. Adding a third spelling as an alias
        # would unify nothing and back-compat nothing, so it does not.
        "url": make_wiki_url(parse_data["title"]),
        "revision_url": make_revision_url(parse_data["revid"]),
        "revision_wikitext_url": make_revision_wikitext_url(parse_data["revid"]),
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
        revision_url=make_revision_url(parse_data["revid"], anchor),
        revision_wikitext_url=make_revision_wikitext_url(parse_data["revid"]),
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
    # Subscript, not .get(): a revid we do not have is a citation we cannot make.
    # Tolerated as None, it reached the agent as "?oldid=None" -- a URL that looks
    # attested and pins nothing, which is worse than no URL at all.
    revid = parse_data["revid"]

    # Built once: the revision is a property of the page and anchor, not of each
    # block, and every block on the page shares it.
    #
    # parse_data["title"], not the caller's `title`: MediaWiki normalises and follows
    # redirects, so asking for "Grub" is answered about "GRUB". Built from the raw
    # argument, source_url named the page the caller asked for while revid and
    # revision_url named the page the wiki served -- one block citing two pages.
    url_base = make_wiki_url(parse_data["title"], anchor)
    revision_url = make_revision_url(revid, anchor)
    revision_wikitext_url = make_revision_wikitext_url(revid)

    if anchor:
        _, wikitext_to_parse = _resolve_section(parse_data, anchor)
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
            "revision_url": revision_url,
            "revision_wikitext_url": revision_wikitext_url,
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
    else:
        wikitext = page_wikitext

    warning_blocks = parse_templates(wikitext, revid, types)

    # Built once: the provenance is a property of the page and anchor, not of each
    # block, and every block on the page shares it. (anchor is None in the whole-page
    # case, which every one of these already handles.)
    url_base = make_wiki_url(parse_data["title"], anchor)
    revision_url = make_revision_url(revid, anchor)
    revision_wikitext_url = make_revision_wikitext_url(revid)

    # asdict, not a hand-listed literal: the literal is how tool_section() came to
    # attest a hash over text it never returned. A new field must reach the agent
    # by default, not by someone remembering to add it in a second place.
    return [
        {
            **asdict(w),
            "source_url": url_base,
            "revision_url": revision_url,
            "revision_wikitext_url": revision_wikitext_url,
            # alias_revid pins the redirect page, never its target. A type learned
            # from a redirect is not attested by the article's revision, so the
            # redirect gets a revision URL of its own -- otherwise the provenance
            # stops one link short of the fact it is attesting. Null exactly when
            # alias_revid is: the template spelled its own type, and the article's
            # revision already covers it.
            "alias_revision_url": (
                make_revision_url(w.alias_revid) if w.alias_revid else None
            ),
        }
        for w in warning_blocks
    ]


def links(title: str, anchor: Optional[str] = None) -> List[Dict]:
    """
    MCP Tool: Extract internal links from page or section.
    
    Returns list of InternalLink dicts.
    """
    # links() carried no revid at all, so its source_url was unpinnable even in
    # principle: an agent could not have said which revision of the page listed
    # the link, only that some revision once did. Both branches already produce
    # the provenance -- take it from them rather than rebuilding it.
    if anchor:
        extracted = section(title, anchor)
        # The raw slice: these parse wikitext, and .content is now rendered.
        wikitext = extracted.content_raw
        url_base = extracted.url
        revid = extracted.revid
        revision_url = extracted.revision_url
        revision_wikitext_url = extracted.revision_wikitext_url
    else:
        page_data = page(title)
        wikitext = page_data["wikitext"]
        url_base = page_data["url"]
        revid = page_data["revid"]
        revision_url = page_data["revision_url"]
        revision_wikitext_url = page_data["revision_wikitext_url"]

    link_list = parse_internal_links(wikitext, title)

    return [
        {
            "target_page": link.target_page,
            "display_text": link.display_text,
            "anchor": link.anchor,
            "source_page": link.source_page,
            "source_url": url_base,
            "revision_url": revision_url,
            "revision_wikitext_url": revision_wikitext_url,
            "revid": revid
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
