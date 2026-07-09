"""
Link-prefix exclusion derived from the wiki's own namespace and interwiki tables.

A hardcoded list rots. When this project's static snapshot was compared against
the live siteinfo, it was missing 32 real interwiki prefixes (fedora, doi, phab,
mw, meta, lv, ...) -- each of which links() reported as a navigable article link
-- and wrongly excluded `man` and `kernel`, which are not interwiki here at all.
"""

from urllib.error import URLError

import pytest

from conftest import load_wikitext
from src import extractor


@pytest.fixture(autouse=True)
def clear_prefix_cache():
    extractor.reset_prefix_cache()
    yield
    extractor.reset_prefix_cache()


def test_prefixes_come_from_siteinfo():
    prefixes = extractor.excluded_link_prefixes()

    # Namespaces the wiki declares.
    for namespace in ("category", "file", "help", "template", "archwiki", "developerwiki"):
        assert namespace in prefixes

    # Interwiki prefixes the wiki declares, including ones absent from the old
    # static list.
    for interwiki in ("de", "zh-hans", "fedora", "doi", "phab", "mw", "meta"):
        assert interwiki in prefixes


def test_prefixes_absent_from_the_wiki_are_not_excluded():
    """`man` and `kernel` are templates here, not interwiki prefixes."""
    prefixes = extractor.excluded_link_prefixes()
    assert "man" not in prefixes
    assert "kernel" not in prefixes


def test_main_namespace_is_never_excluded():
    """Articles live in namespace 0; excluding it would drop every real link."""
    assert "" not in extractor.excluded_link_prefixes()


def test_falls_back_to_the_static_snapshot_when_siteinfo_is_unreachable(monkeypatch):
    """links() is navigation, not a command source: degrade rather than fail the call."""
    def boom(*_args, **_kwargs):
        raise URLError("network down")

    monkeypatch.setattr(extractor, "fetch_siteinfo", boom)
    prefixes = extractor.excluded_link_prefixes()

    assert prefixes is extractor._FALLBACK_EXCLUDED_PREFIXES
    assert "category" in prefixes
    assert "de" in prefixes


def test_the_fallback_is_never_memoized(monkeypatch):
    """
    A blip on the first call must not pin the rotted list for the process lifetime.
    That list is missing 32 real interwiki prefixes -- caching it would silently
    reinstate the exact defect siteinfo derivation exists to remove.
    """
    monkeypatch.setattr(extractor, "fetch_siteinfo", lambda *a, **k: (_ for _ in ()).throw(URLError("blip")))
    assert extractor.excluded_link_prefixes() is extractor._FALLBACK_EXCLUDED_PREFIXES

    monkeypatch.undo()  # Network recovers
    recovered = extractor.excluded_link_prefixes()

    assert recovered is not extractor._FALLBACK_EXCLUDED_PREFIXES
    assert "fedora" in recovered


def test_a_successful_derivation_is_memoized(monkeypatch):
    calls = []
    real = extractor.fetch_siteinfo

    def counted(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(extractor, "fetch_siteinfo", counted)
    first = extractor.excluded_link_prefixes()
    second = extractor.excluded_link_prefixes()

    assert first is second
    assert len(calls) == 1


def test_empty_siteinfo_does_not_silently_disable_filtering(monkeypatch):
    monkeypatch.setattr(extractor, "fetch_siteinfo", lambda *a, **k: {})
    assert extractor.excluded_link_prefixes() is extractor._FALLBACK_EXCLUDED_PREFIXES


def test_a_bug_in_this_module_is_not_swallowed_as_a_network_failure(monkeypatch):
    """A missing offline fixture must stay loud, not degrade silently."""
    def missing(*_args, **_kwargs):
        raise FileNotFoundError("fixture missing")

    monkeypatch.setattr(extractor, "fetch_siteinfo", missing)
    with pytest.raises(FileNotFoundError):
        extractor.excluded_link_prefixes()


def test_links_uses_the_derived_prefixes():
    links = extractor.parse_internal_links(load_wikitext("Installation_guide"), "Installation guide")
    targets = [link.target_page for link in links]

    assert not any(t.lower().startswith(("category:", "file:", "de:", "fedora:")) for t in targets)
    assert "network interface" in targets
    assert "pacman" in targets


def test_explicit_prefixes_override_the_lookup():
    """The parser stays pure: callers may inject the exclusion set."""
    links = extractor.parse_internal_links(
        "[[Pacman]] and [[Zebra:Thing]]", "Test", excluded_prefixes=frozenset({"zebra"})
    )
    assert [link.target_page for link in links] == ["Pacman"]
