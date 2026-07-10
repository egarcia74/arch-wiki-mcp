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
    # content_hash attests the verbatim slice, so it stays greppable in the source.
    assert first.content_hash == extractor.hash_content(first.content_raw)
    # ...and the rendered text an agent actually quotes is fingerprinted too.
    assert first.content_hash_cleaned == extractor.hash_content(first.content)
    assert first.section_heading == "Installation"
    # The name is the claim: we slice by character, not by byte.
    assert first.extraction_method == "wikitext_character_offset"


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
        # The hash covers the verbatim body, so it stays greppable in the source.
        assert warning["content_hash"] == extractor.hash_content(warning["message_raw"])


def test_section_offsets_are_character_indices_not_bytes():
    """
    MediaWiki's `byteoffset` indexes characters, not UTF-8 bytes, despite the name.
    Encoding first shifts every section on a page containing an accented letter.
    """
    wikitext = "== Ä ==\ncontent\n== B ==\n"
    character_start = wikitext.index("== B ==")
    byte_start = len("== Ä ==\ncontent\n".encode("utf-8"))
    assert character_start != byte_start, "test string must be multibyte"

    assert extractor.extract_section_wikitext(wikitext, character_start, None) == "== B ==\n"


def test_section_extraction_refuses_an_offset_that_misses_the_heading():
    """A slice landing in prose means the API's offset semantics changed."""
    with pytest.raises(ValueError, match="did not resolve to a heading"):
        extractor._resolve_section(
            {
                "title": "T",
                "wikitext": {"*": "lead prose\n== A ==\nbody\n"},
                "sections": [{"anchor": "A", "line": "A", "byteoffset": 3}],
            },
            "A",
        )


def test_every_section_in_the_corpus_resolves_to_its_own_heading():
    """The invariant that catches an offset-semantics regression on any page."""
    for page in ("GRUB", "Installation_guide", "Iwd", "KDE", "Pacman", "Systemd"):
        for sect in extractor.sections(page):
            extracted = extractor.section(page, sect["anchor"])
            assert extracted.content_raw.startswith("="), f"{page}#{sect['anchor']}"
            # The rendered slice must start at the same heading, as markdown.
            assert extracted.content.startswith("#"), f"{page}#{sect['anchor']}"


def test_examples_tool_is_gone():
    """The prose-to-shell heuristic violated Constitution sections 3 and 8."""
    assert not hasattr(extractor, "examples")
    assert not hasattr(extractor, "parse_shell_heuristics")


# ---------------------------------------------------------------------------
# search(): a discovery aid, never evidence.
# ---------------------------------------------------------------------------

def test_clean_snippet_resolves_balanced_markup():
    assert extractor.clean_snippet(
        '[[de:<span class="searchmatch">GRUB</span>]]'
    ) == "de:GRUB"
    assert extractor.clean_snippet("{{ic|pacman}} and ''iwd''") == "pacman and iwd"
    assert extractor.clean_snippet("&lt;pre&gt;code&lt;/pre&gt;") == "<pre>code</pre>"
    assert extractor.clean_snippet("one\ntwo\n") == "one two"


def test_clean_snippet_leaves_a_severed_token_alone():
    """
    A snippet is a truncated fragment. "a:C++|C++]]" has no opening '[[' to
    match, and inventing one would be interpretation. It stays as the wiki sent
    it -- which is why a snippet may never be quoted.
    """
    assert extractor.clean_snippet("a:C++|C++]]. Zosta") == "a:C++|C++]]. Zosta"


def test_no_snippet_in_the_corpus_carries_html():
    for query in ["GRUB", "C++", "wifi not working", "Iwd (简体中文)"]:
        for result in extractor.search(query):
            assert "<span" not in result["snippet"]
            assert "&lt;" not in result["snippet"] and "&amp;" not in result["snippet"]
            assert "\n" not in result["snippet"]


def test_a_search_result_declares_how_it_matched():
    for result in extractor.search("GRUB"):
        assert result["match"] in {"title", "text"}
