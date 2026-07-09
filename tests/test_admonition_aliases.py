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
    assert types == {"note": "NOTE"}


def test_resolved_aliases_are_cached_across_pages():
    extractor.warnings(FRENCH)
    assert extractor._template_aliases["astuce"] == "TIP"
    assert extractor._template_aliases["attention"] == "WARNING"
    assert extractor._template_aliases["ic"] is None  # resolved, and not an admonition


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
