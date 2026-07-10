"""
Localized admonition templates.

A translated page does not write {{Warning}}. The Spanish Installation guide
writes {{Note (Español)}}; the French one writes {{Attention}}, a redirect to
Template:Warning (Français). Matching only the four English names dropped every
admonition on the Spanish page and 6 of 13 on the French one.

warnings() returning [] is what AGENTS.md tells the agent means "the wiki
specifies no warning here". A dropped {{Attention}} is therefore a suppressed
warning presented as silence -- the exact harm the constitution exists to
prevent, and precisely the class of bug the fail-closed rules were written for.

The mapping is derived from the wiki, not declared here.
"""

import pytest

from src import extractor

ENGLISH = "Installation guide"
SPANISH = "Installation guide (Español)"
FRENCH = "Installation guide (Français)"


@pytest.fixture(autouse=True)
def _clean_alias_cache():
    extractor.reset_template_alias_cache()
    yield
    extractor.reset_template_alias_cache()


@pytest.mark.parametrize(
    "name,expected",
    [
        ("Warning", "WARNING"),
        ("note", "NOTE"),
        ("Note (Español)", "NOTE"),
        ("Tip (正體中文)", "TIP"),
        ("Caution", "CAUTION"),
        # A redirect alias spells out nothing; only the wiki knows where it points.
        ("Astuce", None),
        ("Attention", None),
        ("ic", None),
        ("Pkg", None),
    ],
)
def test_a_name_that_spells_itself_out_needs_no_lookup(name, expected):
    assert extractor.canonical_admonition(name) == expected


def test_the_spanish_page_carried_eleven_admonitions_and_returned_none():
    """{{Note (Español)}} -- the suffixed form, resolvable without the network."""
    found = extractor.warnings(SPANISH)
    counts = {}
    for warning in found:
        counts[warning["type"]] = counts.get(warning["type"], 0) + 1

    assert counts == {"NOTE": 7, "TIP": 4, "WARNING": 1}
    assert len(found) == 12


def test_the_french_page_hid_a_warning_behind_a_redirect():
    """{{Attention}} -> Template:Warning (Français). Only the wiki can say so."""
    found = extractor.warnings(FRENCH)
    warnings_only = [w for w in found if w["type"] == "WARNING"]

    assert len(warnings_only) == 1
    assert "partition système EFI" in warnings_only[0]["message"]
    assert len([w for w in found if w["type"] == "TIP"]) == 5  # {{Astuce}}


def test_english_pages_are_unchanged():
    found = extractor.warnings(ENGLISH)
    assert [w["type"] for w in found].count("WARNING") == 1
    assert len(found) == 12


def test_hashes_still_attest_the_verbatim_template_body():
    for page in (ENGLISH, SPANISH, FRENCH):
        for warning in extractor.warnings(page):
            assert warning["content_hash"] == extractor.hash_content(warning["message_raw"])
            assert warning["message_hash_cleaned"] == extractor.hash_content(warning["message"])


def test_alias_resolution_failure_raises_rather_than_returning_a_subset():
    """
    The whole point. If we cannot ask the wiki what {{Attention}} means, we do not
    know whether this page carries a warning, and [] would be a lie. No alias
    fixture exists for this page, so the offline fetch fails.
    """
    with pytest.raises(ValueError, match="Cannot resolve template aliases"):
        extractor.warnings("Transcluded example")


def test_escapes_and_magic_words_are_never_sent_as_titles():
    """{{=}}, {{!}}, {{DISPLAYTITLE:x}} and {{int:y}} are not wiki pages."""
    wikitext = "{{=}} {{!}} {{DISPLAYTITLE:x}} {{int:savechanges}} {{Note|hi}}"
    types = extractor.admonition_types(wikitext, "unused-no-fixture-needed")
    assert types == {"note": extractor.TemplateResolution(type="NOTE")}


def test_resolved_aliases_are_cached_across_pages():
    extractor.warnings(FRENCH)
    assert extractor._template_aliases["astuce"].type == "TIP"
    assert extractor._template_aliases["attention"].type == "WARNING"
    # Resolved, and not an admonition. A real answer, and cached as one.
    assert extractor._template_aliases["ic"].type is None


def test_a_type_learned_from_a_redirect_carries_that_redirect():
    """
    The gap this closes. {{Attention}} is a WARNING only because the wiki says
    Template:Attention redirects to Template:Warning (Français). The article's
    revid does not cover that page, and content_hash covers only message_raw --
    so retargeting the redirect flipped `type` with nothing in the block moving.
    """
    warning = next(w for w in extractor.warnings(FRENCH) if w["type"] == "WARNING")

    assert warning["alias"] == "Attention"
    assert warning["alias_target"] == "Template:Warning (Français)"
    assert warning["alias_revid"] == 675792

    # The revid of the REDIRECT page, never the article's, and never its target's.
    assert warning["alias_revid"] != warning["revid"]


def test_a_type_the_template_spells_out_claims_no_redirect():
    """
    {{Warning}} and {{Note (Español)}} are self-attesting: the spelling sits in
    the wikitext the article's revid already covers. Inventing an alias for them
    would attest a lookup that never happened.
    """
    for page in (ENGLISH, SPANISH):
        for warning in extractor.warnings(page):
            assert warning["alias"] is None, page
            assert warning["alias_target"] is None, page
            assert warning["alias_revid"] is None, page


def test_the_redirect_revid_is_the_redirect_page_not_its_destination():
    resolved = extractor.fetch_template_aliases(["Attention"], FRENCH)
    assert resolved["attention"] == extractor.TemplateResolution(
        type="WARNING",
        alias="Attention",
        alias_target="Template:Warning (Français)",
        alias_revid=675792,
    )


def test_the_revid_query_asks_the_redirect_pages_with_redirects_off(monkeypatch):
    """
    Asserts the REQUEST, not the response, and that is the whole point.

    An offline fixture is keyed by page, so _fetch hands back the same JSON
    whichever titles we ask for. Querying the redirect's *destination* instead of
    the redirect itself therefore passes every response-level assertion -- I
    reverted the code to do exactly that and all 224 tests stayed green.

    Two things must hold, and only the outgoing params can show them:
      - we ask for Template:Attention, the page a retarget edits, not
        Template:Warning (Français), which such an edit never touches;
      - redirects=1 is absent, because with it MediaWiki resolves the title
        before prop=revisions runs and answers about the destination anyway.
    """
    sent = []
    original = extractor._fetch

    def _spy(params, timeout=30, key=None):
        sent.append(params)
        return original(params, timeout, key)

    monkeypatch.setattr(extractor, "_fetch", _spy)
    extractor.fetch_template_aliases(["Attention", "Astuce"], FRENCH)

    revid_queries = [p for p in sent if p.get("prop") == "revisions"]
    assert len(revid_queries) == 1, "expected exactly one revid query"
    params = revid_queries[0]

    titles = params["titles"].split("|")
    assert titles == ["Template:Astuce", "Template:Attention"]
    assert "redirects" not in params, "redirects=1 would answer about the destination"
    assert params["rvprop"] == "ids"


def test_an_unattestable_redirect_fails_closed_rather_than_guessing(monkeypatch):
    """
    We know the page carries a WARNING and cannot say why. Returning it unattested
    would be the very claim this change exists to forbid; dropping it would be a
    suppressed warning. Raise.
    """
    monkeypatch.setattr(extractor, "fetch_redirect_revids", lambda *a, **k: {})

    with pytest.raises(ValueError, match="cannot attest"):
        extractor.fetch_template_aliases(["Attention"], FRENCH)


def test_english_pages_pay_nothing_for_attestation(monkeypatch):
    """
    The second query fires only for a name that redirects to an admonition. No
    English page has one, and none may pay a request for that.
    """
    def _refuse(*args, **kwargs):
        raise AssertionError("fetch_redirect_revids called for a page with no alias")

    monkeypatch.setattr(extractor, "fetch_redirect_revids", _refuse)
    assert len(extractor.warnings(ENGLISH)) == 12


def test_the_renderer_handles_the_suffixed_form():
    rendered = extractor.render_section_wikitext("{{Note (Español)|Cuidado.}}")
    assert rendered == "**Note:** Cuidado."


def test_the_renderer_leaves_a_redirect_alias_verbatim():
    """
    section() renders without a network call, so {{Astuce}} stays raw. Visible
    markup is the honest failure; warnings() is where resolving it matters.
    """
    rendered = extractor.render_section_wikitext("{{Astuce|Un conseil.}}")
    assert rendered == "{{Astuce|Un conseil.}}"
