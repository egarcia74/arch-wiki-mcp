"""
Hash stability and representative-page extraction.

Constitutional requirement: identical revid must yield identical hashes.
"""

import pytest

from conftest import GRUB_REVID, load_parse
from src import extractor

# (page, anchor, revid)
REPRESENTATIVE = [
    ("GRUB", "Installation", GRUB_REVID),
    ("Installation_guide", "Pre-installation", 858613),
    ("Pacman", "Usage", 860643),
]


def test_page_hash_is_deterministic():
    first = extractor.page("GRUB")
    second = extractor.page("GRUB")

    assert first["revid"] == second["revid"] == GRUB_REVID
    assert first["wikitext_hash"] == second["wikitext_hash"]
    assert first["wikitext_hash"] == extractor.hash_content(load_parse("GRUB")["wikitext"]["*"])


def test_section_hash_is_deterministic():
    first = extractor.section("GRUB", "Installation")
    second = extractor.section("GRUB", "Installation")

    assert first.content_hash == second.content_hash
    assert first.content_hash == extractor.hash_content(first.content)
    assert first.section_heading == "Installation"
    assert first.extraction_method == "wikitext_byte_offset"


def test_hash_is_nfc_normalized():
    decomposed = "e\u0301"  # e + combining acute accent
    composed = "\u00e9"  # precomposed e-acute
    assert decomposed != composed
    assert extractor.hash_content(decomposed) == extractor.hash_content(composed)


def test_hash_preserves_whitespace():
    assert extractor.hash_content("a b") != extractor.hash_content("a  b")


@pytest.mark.parametrize("page,anchor,revid", REPRESENTATIVE)
def test_representative_page_extraction(page, anchor, revid):
    extracted = extractor.section(page, anchor)
    assert extracted.revid == revid
    assert extracted.section_anchor == anchor
    assert extracted.content.strip(), "section must not be empty"

    for block in extractor.commands(page, anchor):
        assert block["content_hash"] == extractor.hash_content(block["content_raw"])
        assert block["revid"] == revid
        assert block["source_url"].endswith(f"#{anchor}")

    for warning in extractor.warnings(page, anchor):
        assert warning["type"] in {"WARNING", "NOTE", "TIP", "CAUTION"}
        assert warning["content_hash"]

    for link in extractor.links(page, anchor):
        assert link["source_page"] == page


def test_warnings_are_extracted_with_provenance():
    found = extractor.warnings("GRUB")
    assert found, "GRUB has Warning/Note/Tip templates"
    types = {w["type"] for w in found}
    assert types <= {"WARNING", "NOTE", "TIP", "CAUTION"}
    for warning in found:
        assert warning["revid"] == GRUB_REVID
        assert warning["content_hash"] == extractor.hash_content(warning["message"])


def test_byte_offsets_are_utf8_not_characters():
    """Section slicing must use UTF-8 byte offsets, per the MediaWiki API."""
    wikitext = "== Ä ==\ncontent\n== B ==\n"
    start = len("== Ä ==\ncontent\n".encode("utf-8"))
    assert extractor.extract_section_wikitext(wikitext, start, None) == "== B ==\n"


def test_examples_tool_is_gone():
    """The prose-to-shell heuristic violated Constitution sections 3 and 8."""
    assert not hasattr(extractor, "examples")
    assert not hasattr(extractor, "parse_shell_heuristics")
