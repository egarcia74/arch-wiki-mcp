"""
Golden tests for internal link extraction.

links() used to return [[Category:...]] and interwiki language links as if they
were article links -- 76 of 161 results on Installation guide.
"""

from conftest import load_wikitext
from arch_wiki_mcp import extractor

EXCLUDED_PREFIXES = ("Category:", "File:", "Image:", "Media:", "Template:", "Help:", "Special:")
INTERWIKI_SAMPLE = ("ar:", "bg:", "ca:", "cs:", "de:", "el:", "es:", "ja:", "zh:")


def test_namespace_and_interwiki_links_are_excluded():
    links = extractor.parse_internal_links(load_wikitext("Installation_guide"), "Installation guide")
    targets = [link.target_page for link in links]

    for target in targets:
        assert not target.startswith(EXCLUDED_PREFIXES), f"namespace link leaked: {target}"
        assert not target.startswith(INTERWIKI_SAMPLE), f"interwiki link leaked: {target}"


def test_content_links_are_not_over_filtered():
    """Guard against an over-broad exclusion silently dropping real links."""
    links = extractor.parse_internal_links(load_wikitext("Installation_guide"), "Installation guide")
    targets = {link.target_page for link in links}

    for expected in ("network interface", "EFI system partition", "pacman"):
        assert expected in targets, f"real content link was dropped: {expected}"


def test_anchor_is_split_from_target():
    links = extractor.parse_internal_links(
        "See [[EFI system partition#Typical mount points|Other mount points]].", "Test"
    )
    assert len(links) == 1
    assert links[0].target_page == "EFI system partition"
    assert links[0].anchor == "Typical mount points"
    assert links[0].display_text == "Other mount points"


def test_local_anchor_targets_source_page():
    links = extractor.parse_internal_links("Back to [[#Installation]].", "GRUB")
    assert len(links) == 1
    assert links[0].target_page == "GRUB"
    assert links[0].anchor == "Installation"


def test_multipipe_file_link_is_dropped_not_mangled():
    links = extractor.parse_internal_links("[[File:x.png|thumb|300px|A caption]]", "Test")
    assert links == []


def test_display_text_survives_when_present():
    links = extractor.parse_internal_links("[[Pacman|the package manager]]", "Test")
    assert links[0].target_page == "Pacman"
    assert links[0].display_text == "the package manager"
    assert links[0].anchor is None


def test_links_serialization_includes_anchor():
    for link in extractor.links("GRUB", "Installation"):
        assert "anchor" in link
        assert "target_page" in link
        assert "source_url" in link
