"""
Content shapes beyond the English mainspace happy path.

Covers a translated page body (multibyte wikitext, where MediaWiki's byte
offsets and Python's character indices diverge) and wikitables, which have no
extractor path and must not leak into commands() or links().
"""

import pytest

from conftest import load_parse, load_wikitext
from src import extractor

SPANISH = "Installation guide (Español)"

# Pages in the corpus containing {| ... |} wikitables.
TABLE_PAGES = ["Users_and_groups", "Systemd", "Installation_guide", "Iwd"]


def test_spanish_page_has_a_real_body_not_a_redirect():
    wikitext = load_wikitext(SPANISH)
    assert not wikitext.lstrip().upper().startswith("#REDIRECT")
    assert any(ord(c) > 127 for c in wikitext), "expected multibyte content"


def test_multibyte_section_slicing_uses_byte_offsets():
    """
    MediaWiki byteoffset counts UTF-8 bytes. Slicing the Python string by those
    numbers would drift by one position per multibyte character seen so far.
    """
    parse = load_parse(SPANISH)
    wikitext = parse["wikitext"]["*"]
    assert len(wikitext.encode("utf-8")) > len(wikitext), "fixture must be multibyte"

    for sect in parse["sections"]:
        extracted = extractor.section(SPANISH, sect["anchor"])
        first_line = extracted.content.split("\n", 1)[0]
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
