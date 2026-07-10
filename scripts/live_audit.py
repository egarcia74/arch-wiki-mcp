#!/usr/bin/env python3
"""
Audit the extractor's invariants against the *live* Arch Wiki.

The offline suite pins seven pages. Three of the defects fixed in 1.6-1.8 were
invisible to it and obvious on first contact with real content:

  - nested list markers ('##' -> '1. # body') put a bare '#' back into prose
  - '{{Note| body}}' with a leading space rendered the whole note as code
  - warnings() dropped every admonition on a translated page

None of those needed a new fixture to find. They needed a wider corpus and an
invariant to check it against. That is what this script is: no assertions about
*what* a page says, only that whatever it says comes out obeying the contract.

It talks to the network, so it is deliberately NOT part of the pytest suite --
that suite blocks sockets on purpose. Run it before a release, or after touching
the renderer:

    make audit                  # the default corpus
    make audit PAGES="Btrfs LVM"

Exits non-zero if any invariant is violated.
"""

import argparse
import collections
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import extractor

# Not derived from __doc__: that is None under `python -OO`.
DESCRIPTION = "Audit the extractor's invariants against the live Arch Wiki."


class OfflineModeError(RuntimeError):
    """ARCHWIKI_OFFLINE would make this audit answer from the fixtures."""


def require_live_mode(environ=None):
    """
    Refuse to run against fixtures.

    _fetch() honours ARCHWIKI_OFFLINE, so a shell that still has it exported --
    from a pytest run, or `make test` in the same session -- routes every fetch
    to tests/fixtures. The audit then renders the same seven pinned pages it was
    built to look past, prints "No invariant violations", and exits 0.

    Silently clearing the variable would be worse: this must not *look* like it
    audited the wiki when it did not. That is the failure this repo exists to
    prevent, aimed at itself.
    """
    if (environ if environ is not None else os.environ).get("ARCHWIKI_OFFLINE"):
        raise OfflineModeError(
            "ARCHWIKI_OFFLINE is set: this audit would answer from tests/fixtures "
            "and report a green run without contacting the wiki. Unset it."
        )

# Chosen for coverage of shapes, not popularity: tables, heavy code, prose-only,
# nested lists, multibyte bodies, and the three admonition spellings.
DEFAULT_PAGES = [
    "GRUB", "Installation guide", "Iwd", "KDE", "Pacman", "Systemd", "Users and groups",
    "Xorg", "NetworkManager", "Fstab", "Kernel parameters", "Locale", "Makepkg",
    "Btrfs", "LVM", "Dm-crypt/Encrypting an entire system", "Systemd-boot", "Mkinitcpio",
    "Docker", "QEMU", "Nvidia", "PulseAudio", "PipeWire", "Sudo", "OpenSSH",
    "Arch Linux", "Frequently asked questions", "General recommendations",
    "System maintenance", "Improving performance", "Security",
    "Installation guide (Español)",   # {{Note (Español)}} -- suffixed admonitions
    "Installation guide (Français)",  # {{Astuce}}/{{Attention}} -- redirect aliases
    "Xorg (Русский)",                 # multibyte body, character offsets
    "Help:Style", "ArchWiki:Contributing",
]

MARKDOWN_HEADING = re.compile(r"^#{2,6} \S")
LEAKED_MARKER = re.compile(r"^\s*(?:1\.|-) [*#:;](?=[\s*#:;])", re.MULTILINE)
BULLET = re.compile(r"^(\s*)(?:- |1\. )")
# A real unrendered italic is a PAIR. Bare '' is shell quoting: Docker's
# `--format='{{range ...}}'` leaves it behind once the Go template span is cut.
UNRENDERED_ITALIC = re.compile(r"''.+?''")

# Templates the renderer does not know. They survive verbatim by design; a name
# outside this set is REPORTED, not failed -- it means "decide what this is".
# Note "bc" is deliberately absent: a {{bc}} left unrendered would be a real
# regression, and Help:Style's documented literal is worth seeing every run.
KNOWN_RESIDUAL = {
    "app", "bug", "accuracy", "expansion", "merge", "out of date", "style",
    "dead link", "c", "-", "text art", "yes", "no", "grey", "astuce", "remove",
    "end", "move", "issue", "attention", "да", "нет", "broken package link (русский)",
}

# Never Arch templates: MediaWiki magic words ({{int:savechanges}}, {{fullurl:...}})
# and the Go template fields in Docker's --format='{{range .Networks}}{{.IPAddress}}'.
def is_wiki_template(name):
    return ":" not in name and not name.startswith(".") and not name.startswith("range ")


def unfenced(content):
    """`content` with every ``` fenced block removed."""
    kept, in_fence = [], False
    for line in content.split("\n"):
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence:
            kept.append(line)
    return "\n".join(kept)


def bullet_depths(text):
    return [len(m.group(1)) for m in map(BULLET.match, text.split("\n")) if m]


def skips_a_nesting_level(text):
    """A list may nest one level at a time. A jump means an item lost its indent."""
    depths = bullet_depths(text)
    return any(second - first > 2 for first, second in zip(depths, depths[1:]))


def strip_template_spans(content):
    """`content` minus every {{...}} the renderer left verbatim."""
    kept, position = [], 0
    for start, end, _ in extractor._iter_top_level_templates(content, extractor._ANY_TEMPLATE_RE):
        kept.append(content[position:start])
        position = end
    kept.append(content[position:])
    return "".join(kept)


def nowiki_payloads(raw):
    """Each <nowiki> payload in the source, as the wiki means it to be displayed."""
    return [m.group(1) for m in extractor._NOWIKI_SPAN.finditer(raw)]


def strip_nowiki_payloads(content, raw):
    """
    `content` minus the text <nowiki> protected.

    That text is the wiki's literal output: a nowiki'd [[Foo]] is not a wikilink
    we failed to resolve, and a nowiki'd ''x'' is two apostrophes, not emphasis.
    The rendered content carries no tags to tell them apart, so the source must.
    """
    for payload in nowiki_payloads(raw):
        needle = payload.strip("\n")
        if needle:
            content = content.replace(needle, "", 1)
    return content


def prose_lines(content):
    """
    The rendered lines that are prose, and must therefore carry no markup.

    A fenced block is code the wiki wrote. A space-prefixed line is preformatted
    code, where '[[' is bash's test operator and '' is a shell quote. A surviving
    {{...}} is a template we could not render, reproduced byte-for-byte -- its
    insides are the wiki's text, not markup we failed to resolve. All three are
    content; only what remains is ours to get right.
    """
    in_fence = False
    for line in strip_template_spans(content).split("\n"):
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or line[:1] in (" ", "\t"):
            continue
        yield line


def audit_section(page, anchor, raw, page_wikitext, report):
    def fail(kind, detail):
        report[kind].append(f"{page}#{anchor}: {detail}")

    content = extractor.render_section_wikitext(raw)

    if raw not in page_wikitext:
        fail("raw_not_a_slice_of_the_page", "content_raw is not a substring of the page")
    if "\x00" in content:
        fail("sentinel_leaked", "a block sentinel escaped into output")
    if content.count("```") % 2:
        fail("unbalanced_fence", "odd number of fence markers")

    # <nowiki> is a strip marker: MediaWiki expands nothing inside it, so whatever
    # it wraps must reach the reader unchanged. We used to delete the HTML comments
    # inside it and then expand the very templates it was protecting.
    for payload in nowiki_payloads(raw):
        needle = payload.strip("\n")
        if needle and needle not in content:
            fail("nowiki_payload_altered", repr(needle[:70]))

    for line in prose_lines(strip_nowiki_payloads(content, raw)):
        if line.startswith("#") and not MARKDOWN_HEADING.match(line):
            fail("root_prompt_lookalike", repr(line[:70]))
        if LEAKED_MARKER.match(line):
            fail("leaked_list_marker", repr(line[:70]))
        if UNRENDERED_ITALIC.search(line):
            fail("italics_survived", repr(line[:70]))
        if "[[" in line:
            fail("wikilink_survived", repr(line[:70]))

    # A template we could not render must appear EXACTLY as the wiki wrote it.
    # Rendering its insides while keeping its braces produces text that looks
    # raw, is not, and is attested by content_hash_cleaned all the same.
    for span in unrendered_template_spans(content):
        if span not in raw:
            fail("unrendered_template_was_altered", repr(span[:70]))

    # A list may nest one level at a time. Skipping a level means an item lost the
    # indent its siblings kept -- a trailing .strip() on the fragment ate it.
    if skips_a_nesting_level(content):
        fail("nested_list_skipped_a_level", f"bullet indents {bullet_depths(content)[:6]}")

    return content


def unrendered_template_spans(content):
    """The full text of each top-level {{...}} left in the rendered output."""
    for start, end, _ in extractor._iter_top_level_templates(content, extractor._ANY_TEMPLATE_RE):
        yield content[start:end]


def audit_page(page, report, residual, stats):
    try:
        parse = extractor.fetch_wiki_parse(page)
    except Exception as exc:  # noqa: BLE001 -- an unreachable page is a finding
        report["page_fetch_failed"].append(f"{page}: {exc!r}")
        return

    stats["pages"] += 1
    page_wikitext = parse["wikitext"]["*"]

    # warnings() must never raise on a reachable page: [] is a claim, and an
    # unresolvable alias must surface as an error rather than as silence.
    try:
        found = extractor.warnings(page)
        stats["warnings"] += len(found)
    except Exception as exc:  # noqa: BLE001
        report["warnings_raised"].append(f"{page}: {exc!r}")
        found = []

    # "Nothing the wiki merely QUOTES becomes evidence" is NOT checked here, on
    # purpose. It is a claim about the POSITION a block was extracted from, and
    # neither commands() nor warnings() reports position. Every textual proxy is
    # both unsound and unable to fail:
    #
    #   - "content_raw appears inside some <nowiki> payload" flags a legitimate
    #     block, because Help:Style carries a real {{bc|#!/bin/sh ...}} and quotes
    #     that same script elsewhere.
    #   - "extraction from a pre-masked page agrees" is false for an honest block
    #     whose body legitimately contains <nowiki>, and goes vacuous the moment
    #     mask_nowiki() is the thing that regressed.
    #
    # The invariant is enforced in tests/test_wikitext_parsing.py instead, where a
    # synthetic page fixes the positions, and each of the six scanners is observed
    # going red with its mask removed. A check that cannot fail is not a check.

    # warnings().message is prose an agent is REQUIRED to quote. It renders lists
    # through the same helper as section(), but strips whitespace separately -- so
    # the nesting invariant has to be checked here too, not inferred from sections.
    for warning in found:
        if skips_a_nesting_level(warning["message"]):
            report["warning_message_skipped_a_level"].append(f"{page}: {warning['type']}")
        if LEAKED_MARKER.search(warning["message"]):
            report["warning_message_leaked_a_marker"].append(f"{page}: {warning['type']}")

        # A type learned from a redirect must say so, completely. Half-provenance
        # is worse than none: it looks attested and pins nothing.
        alias_fields = (warning["alias"], warning["alias_target"], warning["alias_revid"])
        if any(alias_fields) and not all(alias_fields):
            report["alias_provenance_incomplete"].append(f"{page}: {warning['type']} {alias_fields}")

        # And a template that spells its own type must claim no redirect: an alias
        # on {{Warning}} would attest a lookup that never happened.
        if warning["alias"] and extractor.canonical_admonition(warning["alias"]):
            report["alias_claimed_for_a_self_spelling_name"].append(
                f"{page}: {warning['alias']}"
            )

        # The redirect page is never the article. If they coincide we have pinned
        # the wrong page, which is the failure this provenance exists to detect.
        if warning["alias_revid"] is not None and warning["alias_revid"] == warning["revid"]:
            report["alias_revid_equals_article_revid"].append(f"{page}: {warning['alias']}")

    audited_public_api = False
    for section in parse["sections"]:
        anchor = section.get("anchor")
        if not anchor:
            continue
        try:
            # section() would refetch the page per call; we already hold the parse.
            _, raw = extractor._resolve_section(parse, anchor)
        except ValueError:
            stats["unresolvable"] += 1  # transcluded section: fails closed, by design
            continue

        stats["sections"] += 1
        content = audit_section(page, anchor, raw, page_wikitext, report)
        # Outside fences only: Help:Style *documents* {{bc}} inside a code block,
        # and that literal is content, not a template we declined to render. The
        # same is true of anything the wiki wrapped in <nowiki> -- Help:Style spells
        # {{ic}} and {{pkg}} that way in prose, and they are text, not markup.
        for _, _, name in extractor._iter_top_level_templates(
            unfenced(strip_nowiki_payloads(content, raw)), extractor._ANY_TEMPLATE_RE
        ):
            if is_wiki_template(name.strip().lower()):
                residual[name.strip().lower()] += 1

        # Once per page, go through the tool an agent actually calls, and check
        # that each hash attests the field it claims to.
        if not audited_public_api:
            audited_public_api = True
            block = extractor.section(page, anchor)
            if block.content_hash != extractor.hash_content(block.content_raw):
                report["hash_does_not_attest_raw"].append(f"{page}#{anchor}")
            if block.content_hash_cleaned != extractor.hash_content(block.content):
                report["cleaned_hash_does_not_attest_content"].append(f"{page}#{anchor}")
            if block.content != content:
                report["public_api_renders_differently"].append(f"{page}#{anchor}")


def main():
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    parser.add_argument("pages", nargs="*", default=[], help="pages to audit")
    args = parser.parse_args()

    try:
        require_live_mode()
    except OfflineModeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    pages = args.pages or DEFAULT_PAGES
    report = collections.defaultdict(list)
    residual = collections.Counter()
    stats = collections.Counter()

    for page in pages:
        audit_page(page, report, residual, stats)

    print(f"pages {stats['pages']}  sections {stats['sections']}  "
          f"warnings {stats['warnings']}  transcluded(skipped) {stats['unresolvable']}")

    unknown = {name for name in residual if name not in KNOWN_RESIDUAL}
    if unknown:
        print("\nunrecognised templates left verbatim (decide what these are):")
        for name in sorted(unknown):
            print(f"  {residual[name]:5d}  {{{{{name}}}}}")

    if not report:
        print("\nNo invariant violations.")
        return 0

    print("\nVIOLATIONS")
    for kind, items in sorted(report.items()):
        print(f"\n  {kind}: {len(items)}")
        for item in items[:8]:
            print(f"     {item}")
        if len(items) > 8:
            print(f"     ... and {len(items) - 8} more")
    return 1


if __name__ == "__main__":
    sys.exit(main())
