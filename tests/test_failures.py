"""
Fail-closed tests.

Constitution section 5 requires an explicit failure, not an empty result.
commands() used to wrap its whole body in `except Exception: return []`, making
a network error, a missing page, and "this page has no commands" indistinguishable
to the calling agent -- which AGENTS.md section 6 then instructs to tell the user
the wiki "does not specify an explicit command block".
"""

from urllib.request import urlopen

import pytest

from src import extractor

MISSING_PAGE = "Nonexistent page xyz"
TRANSCLUDED_PAGE = "Transcluded example"


def test_the_network_guard_actually_bites():
    """A guard nothing exercises is decoration. Prove the suite cannot reach the wiki."""
    with pytest.raises(RuntimeError, match="Network access during tests"):
        urlopen("https://wiki.archlinux.org/api.php", timeout=1)


def test_missing_anchor_raises_rather_than_returning_empty():
    with pytest.raises(ValueError, match="Bogus_anchor"):
        extractor.commands("GRUB", "Bogus_anchor")


def test_missing_anchor_raises_in_section():
    with pytest.raises(ValueError, match="Bogus_anchor"):
        extractor.section("GRUB", "Bogus_anchor")


def test_missing_page_raises_in_commands():
    with pytest.raises(ValueError, match="missingtitle|doesn't exist"):
        extractor.commands(MISSING_PAGE)


def test_missing_page_raises_in_page():
    with pytest.raises(ValueError, match="missingtitle|doesn't exist"):
        extractor.page(MISSING_PAGE)


def test_empty_result_is_still_allowed_when_honest():
    """A section with no code blocks legitimately returns []."""
    blocks = extractor.commands(TRANSCLUDED_PAGE, "Trailing_section")
    assert blocks == []


def test_transcluded_section_fails_closed():
    """byteoffset is null; slicing from 0 would return the wrong section's text."""
    with pytest.raises(ValueError, match="transclu|byte offset"):
        extractor.section(TRANSCLUDED_PAGE, "Transcluded_section")


def test_transcluded_section_fails_closed_in_commands():
    with pytest.raises(ValueError, match="transclu|byte offset"):
        extractor.commands(TRANSCLUDED_PAGE, "Transcluded_section")


def test_unknown_section_keys_are_tolerated():
    """The API adds keys over time; an unknown one must not raise TypeError."""
    result = extractor.sections(TRANSCLUDED_PAGE)
    assert [s["anchor"] for s in result] == [
        "Local_section",
        "Transcluded_section",
        "Trailing_section",
    ]
    assert result[0]["link_anchor"] == "Local_section"


def test_local_section_still_extracts_around_a_transcluded_neighbour():
    """A null byteoffset on the NEXT section must not silently extend the slice."""
    extracted = extractor.section(TRANSCLUDED_PAGE, "Local_section")
    assert "This text lives in this page." in extracted.content
    assert "More local text." not in extracted.content
