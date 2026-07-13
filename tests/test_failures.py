"""
Fail-closed tests.

Constitution section 5 requires an explicit failure, not an empty result.
commands() used to wrap its whole body in `except Exception: return []`, making
a network error, a missing page, and "this page has no commands" indistinguishable
to the calling agent -- which AGENTS.md section 6 then instructs to tell the user
the wiki "does not specify an explicit command block".
"""

from urllib.error import URLError
from urllib.request import urlopen

import pytest

from conftest import MISSING_PAGE, TRANSCLUDED_PAGE
from arch_wiki_mcp import extractor


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


def _outage(params, timeout=30, key=None):
    """MediaWiki is up enough to answer, and the answer is 'not now'."""
    return {"error": {"code": "maxlag", "info": "Waiting for a database server"}}


def test_an_upstream_outage_is_classified_as_the_wikis_failure_not_ours(monkeypatch):
    """
    Every fetch answers in the same envelope, but only some classified their
    failures -- the rest raised a bare ValueError, which the MCP layer could
    label only `internal_error`. An outage then told the agent that this server
    was broken, when in fact the wiki simply had not answered. Those are the two
    conclusions an agent must never conflate, so the envelope is classified in
    one place and every fetch inherits it.
    """
    monkeypatch.setattr(extractor, "_fetch", _outage)

    with pytest.raises(extractor.UpstreamApiError):
        extractor.fetch_siteinfo()


def test_the_wikis_silence_is_the_wikis_failure_not_ours(monkeypatch):
    """
    UpstreamApiError means "the wiki did not answer" -- yet the paradigm case of
    not answering escaped untyped. _unwrap classified what the wiki *says*; a
    dead socket says nothing, so URLError sailed past it and reached the agent
    as `internal_error`: a bug in us. The remediations are opposites (retry the
    wiki vs. fix this server), which is the whole reason they must not conflate.
    """
    def _dead_socket(request, timeout=30):
        raise URLError("Connection refused")

    monkeypatch.delenv("ARCHWIKI_OFFLINE", raising=False)
    monkeypatch.setattr(extractor, "urlopen", _dead_socket)

    with pytest.raises(extractor.UpstreamApiError):
        extractor.fetch_wiki_parse("GRUB")


def test_an_outage_on_the_alias_path_keeps_its_category(monkeypatch):
    """
    ArchWikiError subclasses ValueError, and _ALIAS_FAILURES lists ValueError --
    so this arm caught the very types the classifier had just raised and
    re-raised them bare, losing the code and re-opening the conflation on
    precisely the path the classifier was written for.
    """
    def _outage_on_alias(names, cache_key, timeout=30):
        raise extractor.UpstreamApiError("Arch Wiki did not answer: [Errno 111] refused")

    monkeypatch.setattr(extractor, "fetch_template_aliases", _outage_on_alias)

    # A name no canonical table knows and no earlier test has cached, so the
    # alias fetch is actually reached rather than short-circuited.
    with pytest.raises(extractor.UpstreamApiError):
        extractor.admonition_types("{{Zzznotreal|mind the gap}}", cache_key="probe")


def test_a_missing_page_is_never_mistaken_for_an_outage(monkeypatch):
    """The converse: 'no such page' is an answer, not a failure to answer."""
    def _missing(params, timeout=30, key=None):
        return {"error": {"code": "missingtitle", "info": "The page you specified doesn't exist."}}

    monkeypatch.setattr(extractor, "_fetch", _missing)

    with pytest.raises(extractor.PageNotFoundError):
        extractor.fetch_wiki_parse("Whatever")

    # ...and an outage on the same call is not mistaken for a missing page.
    monkeypatch.setattr(extractor, "_fetch", _outage)
    with pytest.raises(extractor.UpstreamApiError):
        extractor.fetch_wiki_parse("Whatever")


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
