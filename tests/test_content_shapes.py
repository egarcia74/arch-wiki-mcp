"""
Content shapes beyond the English mainspace happy path.

Covers a translated page body (multibyte wikitext, where MediaWiki's byte
offsets and Python's character indices diverge) and wikitables, which have no
extractor path and must not leak into commands() or links().
"""

import json

import pytest

from conftest import FIXTURES_DIR, load_parse, load_wikitext
from arch_wiki_mcp import extractor

SPANISH = "Installation guide (Español)"

# Pages in the corpus containing {| ... |} wikitables.
TABLE_PAGES = ["Users_and_groups", "Systemd", "Installation_guide", "Iwd"]

# The whole recorded corpus, in the shape the offset question is asked of it.
# Pinned like TOTAL_CODE_TEMPLATES: a number belongs where changing it breaks
# something. These lived in prose across three documents -- README, TEST_STRATEGY,
# MEDIAWIKI_API_AUDIT -- as "432/432 sections, 121/432 by byte", measured once by
# hand during the investigation. Fixtures were added afterwards and the sentences
# could not notice: the true figures were 461 and 124 before this was written. The
# claim stayed true and its evidence went stale, silently, in the one paragraph
# justifying how the parser slices every section it ever returns.
CORPUS_SECTIONS = 461


def _offsets_resolving_onto_a_heading():
    """Every section in the corpus, sliced both ways. Returns (total, by_char, by_byte)."""
    total = by_char = by_byte = 0

    for path in sorted(FIXTURES_DIR.glob("parse_*.json")):
        parse = json.loads(path.read_text(encoding="utf-8")).get("parse", {})
        if "wikitext" not in parse:
            continue

        wikitext = parse["wikitext"]["*"]
        as_bytes = wikitext.encode("utf-8")

        for section in parse.get("sections", []):
            offset = section["byteoffset"]
            if offset is None:      # transcluded: its text is not on this page at all
                continue
            total += 1

            # Through the code under test, not around it. This first re-sliced the
            # wikitext itself -- wikitext[offset:] -- which measures MediaWiki's data
            # and says nothing whatever about our parser. Reverting the extractor to
            # byte slicing left it passing: a census wearing a guard's name, in the
            # change about numbers nothing keeps true.
            sliced = extractor.extract_section_wikitext(wikitext, offset, None)
            if sliced.split("\n", 1)[0].startswith("="):
                by_char += 1

            # The converse stays independently derived, because it is the thing the
            # extractor must NOT do. Both arms coming from the code under test would
            # let a single bug agree with itself.
            if as_bytes[offset:].decode("utf-8", "replace").split("\n", 1)[0].startswith("="):
                by_byte += 1

    return total, by_char, by_byte


def test_every_section_in_the_corpus_resolves_as_a_character_offset():
    """
    The claim the parser is built on, asserted over the whole corpus rather than
    asserted in prose.

    test_multibyte_section_slicing_uses_character_offsets() below proves the rule on
    one Spanish page. The *general* claim -- that this holds for every section we
    have ever recorded -- was written into three documents as a hand-counted ratio
    and checked by nothing. It is the justification for how section() slices, so it
    is worth a test rather than a sentence.
    """
    total, by_char, by_byte = _offsets_resolving_onto_a_heading()

    assert total == CORPUS_SECTIONS, (
        f"the corpus moved ({total} sections, was {CORPUS_SECTIONS}); re-check the "
        "offset invariant and update the pin deliberately"
    )
    assert by_char == total, f"{total - by_char} sections did not land on their heading"

    # And the converse, which is why the rule exists at all: reading the same field
    # as a byte offset -- as its name invites, and as the deleted proof_of_life.py
    # did -- lands most sections in the middle of the previous one's prose.
    assert by_byte < total, "byte indexing worked everywhere; the premise has changed"


def test_spanish_page_has_a_real_body_not_a_redirect():
    wikitext = load_wikitext(SPANISH)
    assert not wikitext.lstrip().upper().startswith("#REDIRECT")
    assert any(ord(c) > 127 for c in wikitext), "expected multibyte content"


def test_multibyte_section_slicing_uses_character_offsets():
    """
    Despite its name, MediaWiki's `byteoffset` indexes the wikitext by CHARACTER.
    Slicing the Python string as if the offset counted UTF-8 bytes would drift by
    one position per multibyte character seen so far.
    """
    parse = load_parse(SPANISH)
    wikitext = parse["wikitext"]["*"]
    assert len(wikitext.encode("utf-8")) > len(wikitext), "fixture must be multibyte"

    for sect in parse["sections"]:
        extracted = extractor.section(SPANISH, sect["anchor"])
        # content_raw is the verbatim slice; content has been rendered for quoting.
        first_line = extracted.content_raw.split("\n", 1)[0]
        # The slice must begin exactly at this section's own heading. Treating the
        # offset as a byte index drifts by one position per multibyte character
        # seen so far, landing in the previous section's prose.
        assert first_line.startswith("="), f"{sect['anchor']}: began at {first_line!r}"
        assert sect["line"] in first_line, f"{sect['anchor']}: began at {first_line!r}"


def test_multibyte_page_hash_is_nfc_stable():
    first = extractor.page(SPANISH)
    second = extractor.page(SPANISH)
    assert first["wikitext_hash"] == second["wikitext_hash"]
    assert first["revid"] == second["revid"]


def test_commands_extract_from_translated_page():
    blocks = extractor.commands(SPANISH)
    patterns = [b["source_pattern"] for b in blocks]
    assert patterns.count("template_bc") == 2
    assert patterns.count("template_hc") == 3
    for block in blocks:
        assert block["content_hash"] == extractor.hash_content(block["content_raw"])


@pytest.mark.parametrize("page", TABLE_PAGES)
def test_wikitables_are_present_but_never_become_commands(page):
    wikitext = load_wikitext(page)
    assert "{|" in wikitext, f"{page} should contain a wikitable"

    for block in extractor.parse_code_blocks(wikitext):
        assert "{|" not in block.content
        assert not block.content.lstrip().startswith("|-")
        assert not block.content.lstrip().startswith("!")


@pytest.mark.parametrize("page", TABLE_PAGES)
def test_wikitable_rows_never_become_links(page):
    for link in extractor.parse_internal_links(load_wikitext(page), page):
        assert not link.target_page.startswith(("|", "!", "{"))
        assert link.target_page.strip() == link.target_page
