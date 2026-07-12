"""
Records live MediaWiki API responses into tests/fixtures/.

These fixtures back the golden tests, which pin exact revids, hashes, and block
counts. Re-recording is a deliberate act: it will move those constants and the
golden assertions must be updated in the same commit.
"""

import json
import os
import sys
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.parse import urlencode

# Ensure we can run this from repo root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from arch_wiki_mcp import extractor
from arch_wiki_mcp.extractor import SITEINFO_PROPS, fixture_filename

API_ENDPOINT = "https://wiki.archlinux.org/api.php"
USER_AGENT = "ArchWikiMCP/1.0 (Fixture Generator)"

# Pages whose template names warnings() must resolve. A translated page writes
# {{Note (Español)}} or {{Attention}}; only the wiki knows where those point.
ALIAS_PAGES = [
    "GRUB", "Pacman", "Iwd", "KDE", "Systemd", "Users and groups",
    "Installation guide",
    "Installation guide (Español)",
    "Installation guide (Français)",
]

CORPUS = [
    ("parse", "GRUB"),
    ("parse", "Pacman"),
    ("parse", "Iwd"),
    ("parse", "KDE"),
    ("parse", "Systemd"),
    ("parse", "Users and groups"),
    ("parse", "Installation guide"),
    ("parse", "Installation guide (Español)"),  # Non-English body: NFC + character offsets
    ("parse", "Installation guide (Français)"),  # {{Astuce}}/{{Attention}} redirect aliases
    ("query", "GRUB"),
    ("query", "C++"),
    ("query", "Iwd (简体中文)"),
    ("query", "wifi not working"),  # Multi-word question: title-only search returned []
    ("query", "zzzqqxnotathing"),  # Genuinely nothing: the only honest empty result
    ("query", "siteinfo"),  # Authoritative namespace + interwiki tables for links()
]

# Hand-authored, not recordable: no live page yields a null byteoffset in this
# corpus, and the API-error shape is easier to pin by hand.
HAND_AUTHORED = {"parse_Transcluded_example.json", "parse_Nonexistent_page_xyz.json"}


def _save(filename, params, force):
    if os.path.exists(filename) and not force:
        print(f"Skipping {filename} (exists; pass --force to re-record)")
        return

    request = Request(f"{API_ENDPOINT}?{urlencode(params)}", headers={"User-Agent": USER_AGENT})
    with urlopen(request) as response:
        data = json.loads(response.read().decode("utf-8"))

    with open(filename, "w") as f:
        json.dump(data, f, indent=2)
    print(f"Saved to {filename}")


def record_fixture(action, key, force=False):
    fixture = lambda k: os.path.join("tests/fixtures", fixture_filename(action, k))  # noqa: E731

    if action == "parse":
        _save(fixture(key), {
            "action": action, "format": "json",
            "page": key, "prop": "wikitext|sections|revid",
        }, force)
        return

    if key == "siteinfo":
        _save(fixture(key), {
            "action": action, "format": "json",
            "meta": "siteinfo", "siprop": SITEINFO_PROPS,
        }, force)
        return

    # search() asks the wiki two questions, so two fixtures. Recording only the
    # full-text one would leave the exact-title lookup unbacked, and the offline
    # suite would fail closed on a missing fixture rather than answer wrongly.
    _save(fixture(key), {
        "action": action, "format": "json",
        "list": "search", "srsearch": key, "srlimit": 5, "srwhat": "text",
    }, force)
    _save(fixture(f"nearmatch_{key}"), {
        "action": action, "format": "json",
        "list": "search", "srsearch": key, "srlimit": 1, "srwhat": "nearmatch",
    }, force)


def unresolved_template_names(page_title):
    """
    Exactly the names warnings() will ask the wiki about for this page.

    Derived from the recorded parse fixture with the extractor's own helpers, so
    the fixture answers the question the runtime actually asks. A name that spells
    itself out ("Note", "Note (Español)") is never queried.
    """
    path = os.path.join("tests/fixtures", fixture_filename("parse", page_title))
    with open(path, encoding="utf-8") as handle:
        wikitext = json.load(handle)["parse"]["wikitext"]["*"]

    names = {
        name
        for _, _, name in extractor._iter_top_level_templates(
            extractor.mask_nowiki(wikitext), extractor._ANY_TEMPLATE_RE
        )
        if name and not extractor._NOT_A_TEMPLATE_TITLE.search(name)
    }
    return sorted(n for n in names if not extractor.canonical_admonition(n))


def _record_query(filename, params, label, force):
    """Fetch and save one API response, or load the recorded one. Returns the data."""
    if os.path.exists(filename) and not force:
        print(f"Skipping {filename} (exists; pass --force to re-record)")
        with open(filename, encoding="utf-8") as handle:
            return json.load(handle)

    print(f"Recording {label}...")
    request = Request(f"{API_ENDPOINT}?{urlencode(params)}", headers={"User-Agent": USER_AGENT})
    with urlopen(request) as response:
        data = json.loads(response.read().decode("utf-8"))

    with open(filename, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
    print(f"Saved to {filename}")
    return data


def record_aliases(page_title, force=False):
    """
    Record the redirect resolution for one page's template names.

    Two fixtures, mirroring the two queries warnings() makes. The second is
    recorded only when a name actually redirects to an admonition, because that
    is the only case the runtime fetches it -- a fixture nothing reads would rot
    unnoticed, and its absence is what proves the second query was skipped.
    """
    names = unresolved_template_names(page_title)
    batch_size = extractor._TITLES_PER_QUERY
    batches = [names[i:i + batch_size] for i in range(0, len(names), batch_size)] or [[]]

    redirect_titles = []
    for index, batch in enumerate(batches):
        suffix = "" if len(batches) == 1 else f"_{index + 1}"
        data = _record_query(
            os.path.join("tests/fixtures", fixture_filename("query", f"aliases_{page_title}{suffix}")),
            {
                "action": "query",
                "titles": "|".join(f"Template:{name}" for name in batch),
                "redirects": "1",
                "format": "json",
            },
            f"template aliases for {page_title} ({len(batch)} names)",
            force,
        )
        for redirect in data.get("query", {}).get("redirects", []):
            if extractor.canonical_admonition(redirect["to"].split(":", 1)[-1]):
                redirect_titles.append(redirect["from"])

    if not redirect_titles:
        return

    # The revision of each REDIRECT page. No redirects=1: with it, MediaWiki
    # resolves the title and returns the destination's revid instead.
    ordered = sorted(redirect_titles)
    revid_batches = [ordered[i:i + batch_size] for i in range(0, len(ordered), batch_size)]
    for index, batch in enumerate(revid_batches):
        suffix = "" if len(ordered) <= batch_size else f"_{index + 1}"
        _record_query(
            os.path.join("tests/fixtures", fixture_filename("query", f"aliasrevs_{page_title}{suffix}")),
            {
                "action": "query",
                "titles": "|".join(batch),
                "prop": "revisions",
                "rvprop": "ids",
                "format": "json",
            },
            f"redirect revisions for {page_title} ({len(batch)} redirects)",
            force,
        )


if __name__ == "__main__":
    # Existing fixtures are never silently overwritten: re-recording moves the
    # revids and hashes the golden tests pin, and must be a deliberate act.
    force = "--force" in sys.argv
    wanted = [a for a in sys.argv[1:] if a != "--force"]

    os.makedirs("tests/fixtures", exist_ok=True)
    for action, key in CORPUS:
        if not wanted or key in wanted:
            record_fixture(action, key, force=force)

    # After the parse fixtures exist: the alias query is derived from them.
    for page_title in ALIAS_PAGES:
        if not wanted or page_title in wanted:
            record_aliases(page_title, force=force)
