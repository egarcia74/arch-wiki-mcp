"""
The URL a user pastes must resolve to the title they meant, or be refused.

extract_title_from_url() hand-sliced strings: it split on "/title/", took whatever
followed, and never decoded it. So a translated page pasted from a browser --
.../title/Installation_guide_%28Fran%C3%A7ais%29 -- arrived at the wiki as the
literal title "Installation_guide_%28Fran%C3%A7ais%29", which does not exist. The
tool then fail-closed correctly and told the agent the page was missing. It was
not missing; we asked for the wrong one, and reported the wiki's silence as fact.

It also matched "title=" anywhere in the query string and never checked the host,
so https://evil.example/title/GRUB was accepted as an Arch Wiki page.
"""

import pytest

from arch_wiki_mcp import extractor, server

extract = server.extract_title_from_url

WIKI = "https://wiki.archlinux.org"


# (input, expected title)
RESOLVES = [
    pytest.param("GRUB", "GRUB", id="plain-title"),
    pytest.param("Installation guide", "Installation guide", id="plain-title-with-space"),
    pytest.param(f"{WIKI}/title/GRUB", "GRUB", id="canonical"),
    pytest.param(f"{WIKI}/title/GRUB#Installation", "GRUB", id="canonical-with-fragment"),
    pytest.param(f"{WIKI}/title/Installation_guide", "Installation guide", id="underscores"),
    pytest.param(
        f"{WIKI}/title/Installation_guide_%28Fran%C3%A7ais%29",
        "Installation guide (Français)",
        id="percent-encoded-translated-page",
    ),
    pytest.param(
        f"{WIKI}/title/Installation_guide_%28Fran%C3%A7ais%29#Installation",
        "Installation guide (Français)",
        id="percent-encoded-with-fragment",
    ),
    pytest.param(
        f"{WIKI}/index.php?title=Installation_guide_%28Fran%C3%A7ais%29&oldid=123",
        "Installation guide (Français)",
        id="index-php-query-with-oldid",
    ),
    pytest.param(f"{WIKI}/index.php?title=GRUB", "GRUB", id="index-php-query"),
    pytest.param(f"{WIKI}/title/C%2B%2B", "C++", id="percent-encoded-plus"),
    pytest.param(f"{WIKI}/index.php?title=C%2B%2B", "C++", id="query-encoded-plus"),
    # In a query string, "+" means space. In a path it does not.
    pytest.param(f"{WIKI}/index.php?title=Installation+guide", "Installation guide", id="query-plus-is-space"),
    pytest.param(f"{WIKI}/title/Xorg#Configuration", "Xorg", id="fragment-stripped"),
    pytest.param(f"http://{WIKI[8:]}/title/GRUB", "GRUB", id="http-scheme"),
]


@pytest.mark.parametrize("given,expected", RESOLVES)
def test_a_url_resolves_to_the_title_it_names(given, expected):
    assert extract(given) == expected


REFUSED = [
    pytest.param("https://evil.example/title/GRUB", id="foreign-host-with-title-path"),
    pytest.param("https://wiki.archlinux.org.evil.example/title/GRUB", id="suffix-lookalike-host"),
    pytest.param("https://archlinux.org/title/GRUB", id="right-org-wrong-host"),
    pytest.param(f"{WIKI}/", id="no-title-at-all"),
    pytest.param(f"{WIKI}/index.php?oldid=123", id="query-without-a-title"),
    pytest.param(f"{WIKI}/index.php?not_title=GRUB", id="title-only-as-a-substring"),
    pytest.param(f"{WIKI}/title/", id="empty-title-in-path"),
    pytest.param(f"{WIKI}/index.php?title=", id="empty-title-in-query"),
    pytest.param(f"{WIKI}/index.php?title=A&title=B", id="repeated-title-parameter"),
]


@pytest.mark.parametrize("given", REFUSED)
def test_an_unusable_url_is_refused_rather_than_guessed(given):
    """
    Refusing is the whole point. A URL we cannot resolve must not become a title we
    invented -- that is how the wrong page gets quoted with a valid-looking hash.
    """
    with pytest.raises(extractor.MalformedWikiUrlError):
        extract(given)


def test_a_foreign_host_is_never_reachable_through_a_tool(monkeypatch):
    """The refusal must hold at the tool boundary, not just in the helper."""
    def _no_fetch(*args, **kwargs):
        raise AssertionError("a foreign host reached the wiki fetcher")

    monkeypatch.setattr(extractor, "_fetch", _no_fetch)

    with pytest.raises(extractor.MalformedWikiUrlError):
        server.handle_tool_call("page", {"title_or_url": "https://evil.example/title/GRUB"})


def test_a_plain_title_is_passed_through_untouched():
    """
    Only URLs are parsed. A title is whatever the caller typed -- we must not
    "helpfully" decode a page whose name genuinely contains a percent sign.
    """
    assert extract("100%_CPU") == "100%_CPU"
    assert extract("C++") == "C++"


@pytest.mark.parametrize("given", [
    pytest.param(f" {WIKI}/title/GRUB", id="leading-space"),
    pytest.param(f"{WIKI}/title/GRUB\n", id="trailing-newline"),
    pytest.param(f"HTTPS://{WIKI[8:]}/title/GRUB", id="uppercase-scheme"),
    pytest.param(f"Https://{WIKI[8:]}/title/GRUB", id="mixed-case-scheme"),
])
def test_a_url_is_still_a_url_after_a_sloppy_paste(given):
    """
    startswith(("http://", "https://")) failed on a leading space and on an
    uppercase scheme -- both ordinary paste artifacts. The URL then skipped the URL
    branch entirely and was handed to the wiki *as a title*, which finds nothing.
    The wiki's silence, reported as fact, through the whitespace door.
    """
    assert extract(given) == "GRUB"


@pytest.mark.parametrize("given", [
    pytest.param(f" https://evil.example/title/GRUB", id="leading-space-foreign-host"),
    pytest.param(f"HTTPS://evil.example/title/GRUB", id="uppercase-scheme-foreign-host"),
])
def test_a_sloppy_paste_does_not_smuggle_a_foreign_host_past_the_check(given):
    with pytest.raises(extractor.MalformedWikiUrlError):
        extract(given)


REAL_TITLES = [
    "GRUB",
    "Installation guide",
    "Installation guide (Français)",
    "C++",
    "100% CPU",
    "DeveloperWiki:Something",
    "Xorg/Guide",
]


@pytest.mark.parametrize("title", REAL_TITLES)
def test_the_parser_is_the_inverse_of_the_builder(title):
    """
    make_wiki_url() and extract_title_from_url() are each other's inverse, and now
    live beside each other so they stay that way. A URL this server hands out must
    be one this server can read back.
    """
    assert extract(extractor.make_wiki_url(title)) == title


@pytest.mark.parametrize("title", REAL_TITLES)
def test_the_round_trip_survives_an_anchor(title):
    assert extract(extractor.make_wiki_url(title, "Installation")) == title


def test_a_revision_url_is_refused_with_advice_rather_than_a_shrug():
    """
    The URL an agent is most likely to paste back is the one we told it to cite.
    A revision URL names a revid, not a title -- refusing is right, but the message
    should say what to pass instead.
    """
    revision_url = extractor.make_revision_url(858930)

    with pytest.raises(extractor.MalformedWikiUrlError, match="revision URL"):
        extract(revision_url)


def test_the_decoded_title_actually_reaches_the_wiki(monkeypatch):
    """
    A page-keyed fixture answers the same JSON however wrong the query, so asserting
    the response proves nothing. Assert the request.
    """
    asked = []
    monkeypatch.setattr(extractor, "fetch_wiki_parse", lambda t, *a, **k: asked.append(t) or {
        "title": t, "pageid": 1, "revid": 1, "wikitext": {"*": ""}, "sections": []
    })

    server.tool_page(f"{WIKI}/title/Installation_guide_%28Fran%C3%A7ais%29")

    assert asked == ["Installation guide (Français)"], (
        "the wiki was asked for a title nobody pasted"
    )
