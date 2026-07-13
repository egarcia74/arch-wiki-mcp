"""
The URL an agent follows must resolve to the revision it was handed.

Evidence carried a canonical page URL plus a separate revid, and the README
promised "a direct link to the specific revision". Those are different things.
A canonical URL follows the page: quote a warning today, follow the link a month
later, and MediaWiki serves whatever the page says then -- which may not contain
the warning at all. The revid was right there in the payload and the URL simply
did not use it, so the citation was falsifiable in principle and unfalsifiable in
practice, which is the only kind of provenance that matters.

`revision_url` pins the text. `source_url` stays as the canonical page, because a
reader usually wants the live page and the two answer different questions.
"""

from dataclasses import asdict
from urllib.parse import parse_qs, unquote, urlparse

import pytest

from conftest import GRUB_REVID
from arch_wiki_mcp import extractor

ANCHOR = "Installation"


def _query(url):
    return parse_qs(urlparse(url).query)


def _fragment(url):
    return unquote(urlparse(url).fragment)


# Every evidentiary tool: the ones that hand an agent text it may quote.
EVIDENCE = [
    pytest.param(lambda: extractor.page("GRUB"), id="page"),
    pytest.param(lambda: asdict(extractor.section("GRUB", ANCHOR)), id="section"),
    pytest.param(lambda: extractor.commands("GRUB", ANCHOR)[0], id="commands"),
    pytest.param(lambda: extractor.warnings("GRUB")[0], id="warnings"),
    pytest.param(lambda: extractor.links("GRUB", ANCHOR)[0], id="links"),
]


@pytest.mark.parametrize("extract", EVIDENCE)
def test_every_evidentiary_response_carries_a_revision_url(extract):
    block = extract()

    assert block.get("revision_url"), "evidence with no revision-addressed URL"


@pytest.mark.parametrize("extract", EVIDENCE)
def test_the_revision_url_resolves_to_the_revid_it_was_handed(extract):
    """
    The whole claim. A URL that names a different revision than the payload -- or
    names none -- is a citation of nothing in particular.
    """
    block = extract()

    oldid = _query(block["revision_url"]).get("oldid")
    assert oldid == [str(block["revid"])], (
        f"revision_url points at {oldid}, payload says revid={block['revid']}"
    )


@pytest.mark.parametrize("extract", EVIDENCE)
def test_the_canonical_url_is_still_there(extract):
    """
    revision_url is added, not substituted. A reader following a citation usually
    wants the live page; an auditor wants the text as quoted. Both, or neither is
    honest.
    """
    block = extract()

    assert block.get("source_url") or block.get("url"), "canonical page URL was dropped"


def test_a_section_anchor_survives_on_the_revision_url():
    """An anchorless revision URL drops the reader at the top of a long page."""
    block = asdict(extractor.section("GRUB", ANCHOR))

    assert _fragment(block["revision_url"]) == ANCHOR


def test_the_revision_url_is_pinned_to_the_recorded_revision():
    """
    Not recomputed from the code under test: GRUB_REVID comes from the committed
    fixture, so a bug that fed the wrong revid into both the payload and the URL
    would agree with itself and still fail here.
    """
    block = asdict(extractor.section("GRUB", ANCHOR))

    assert _query(block["revision_url"])["oldid"] == [str(GRUB_REVID)]


@pytest.mark.parametrize("extract", EVIDENCE)
def test_the_wikitext_url_is_one_a_script_can_actually_fetch(extract):
    """
    The field exists so an auditor can re-fetch the bytes content_hash covers. It
    pointed at index.php?action=raw, which wiki.archlinux.org answers with an
    anti-bot interstitial -- HTTP *200*, an HTML challenge page, no wikitext. A
    script would have hashed the challenge, seen a mismatch, and concluded a good
    citation was forged: the worst error this project can make, shipped in the one
    field whose whole job is to prevent it. api.php is not gated, and is the route
    the extractor itself uses.
    """
    url = extract()["revision_wikitext_url"]

    assert "/api.php" in url, "the audit URL must be the machine-fetchable route"
    assert "index.php" not in url, "index.php answers a script with a bot challenge"
    assert "action=parse" in url and "prop=wikitext" in url


def test_the_wikitext_url_names_the_revision_it_belongs_to():
    block = asdict(extractor.section("GRUB", ANCHOR))

    assert _query(block["revision_wikitext_url"])["oldid"] == [str(block["revid"])]


def test_a_redirected_page_does_not_cite_two_different_pages_at_once(monkeypatch):
    """
    commands() built source_url from the title the *caller* passed, while revid and
    revision_url came from the page MediaWiki actually served. Ask for a redirect
    and one block claimed both pages at once -- a citation disagreeing with itself.
    Every other tool resolved the title first.
    """
    served = dict(extractor.fetch_wiki_parse("GRUB"))
    monkeypatch.setattr(extractor, "fetch_wiki_parse", lambda *a, **k: served)

    # "Grub" would redirect; MediaWiki answers about "GRUB".
    block = extractor.commands("Grub", ANCHOR)[0]

    assert "/title/GRUB#" in block["source_url"], (
        f"source_url cites the title asked for, not the page served: {block['source_url']}"
    )


def test_links_does_not_cite_the_page_the_caller_asked_for_either(monkeypatch):
    """
    The sibling of the commands() bug, missed when that one was fixed. links() passed
    the caller's raw title to parse_internal_links, so `source_page` -- and the target
    of a bare [[#Anchor]] link -- named the page asked for, while the revision named
    the page served. One block, two pages, again.
    """
    served = dict(extractor.fetch_wiki_parse("GRUB"))
    monkeypatch.setattr(extractor, "fetch_wiki_parse", lambda *a, **k: served)

    for link in extractor.links("Grub", ANCHOR):
        assert link["source_page"] == "GRUB", (
            f"source_page cites the title asked for, not the page served: {link['source_page']}"
        )


def test_a_reader_following_the_readme_can_actually_reproduce_a_hash():
    """
    The claim, executed. `content_hash` covers `content_raw`, and the README tells a
    reader to find that fragment in the revision's wikitext and hash it -- so it had
    better be findable there.

    It was not, for one block type. The wiki marks preformatted text with a leading
    space per line, and the parser strips it (it is the marker, not the content), so
    an indented block's content_raw is not a substring of the revision at all. A
    reader doing exactly what the README said would have got a mismatch and concluded
    a good citation was forged -- which, in a repo whose product is falsifiable
    citation, is the worst error available. The README now states the transformation;
    this asserts the README is telling the truth.
    """
    wikitext = extractor.fetch_wiki_parse("GRUB")["wikitext"]["*"]

    checked = {"indented_block": 0, "contiguous": 0}
    for block in extractor.commands("GRUB"):
        raw = block["content_raw"]

        if block["source_pattern"] == "indented_block":
            # The README's documented step: put the marker space back.
            restored = "\n".join(" " + line for line in raw.split("\n"))
            assert restored in wikitext, "the documented transformation does not locate it"
            checked["indented_block"] += 1
        else:
            assert raw in wikitext, f"{block['source_pattern']} is not a wikitext slice"
            checked["contiguous"] += 1

        assert extractor.hash_content(raw) == block["content_hash"]

    assert checked["indented_block"], "the exception the README documents was never exercised"
    assert checked["contiguous"], "the ordinary case was never exercised"


def test_an_alias_keeps_its_own_revision_url():
    """
    alias_revid pins the redirect page, never its target. A warning whose type was
    learned from a redirect must let an auditor read *that redirect* as it stood,
    or the provenance stops one link short of the fact it is attesting.

    The French installation guide writes {{Astuce}}, a redirect -- so the type
    appears nowhere in the article's own wikitext and the article's revid does not
    attest it. This is the page where the distinction is real.
    """
    aliased = [
        w for w in extractor.warnings("Installation guide (Français)")
        if w.get("alias_revid")
    ]
    assert aliased, "the fixture that exercises alias provenance stopped doing so"

    for warning in aliased:
        oldid = _query(warning["alias_revision_url"])["oldid"]
        assert oldid == [str(warning["alias_revid"])], (
            "the redirect's URL must name the redirect's own revision"
        )
        # And must NOT be the article's revision: that pair names no page.
        assert oldid != [str(warning["revid"])]
