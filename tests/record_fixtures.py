"""
Records live MediaWiki API responses into tests/fixtures/.

These fixtures back the golden tests, which pin exact revids, hashes, and block
counts. Re-recording is a deliberate act: it will move those constants and the
golden assertions must be updated in the same commit.
"""

import json
import os
import sys
from urllib.request import urlopen, Request
from urllib.parse import urlencode

# Ensure we can run this from repo root
sys.path.insert(0, os.path.abspath("."))

from src import extractor
from src.extractor import SITEINFO_PROPS, fixture_filename

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
    ("query", "wifi not working"),
    ("query", "siteinfo"),  # Authoritative namespace + interwiki tables for links()
]

# Hand-authored, not recordable: no live page yields a null byteoffset in this
# corpus, and the API-error shape is easier to pin by hand.
HAND_AUTHORED = {"parse_Transcluded_example.json", "parse_Nonexistent_page_xyz.json"}


def record_fixture(action, key, force=False):
    filename = os.path.join("tests/fixtures", fixture_filename(action, key))

    if os.path.exists(filename) and not force:
        print(f"Skipping {filename} (exists; pass --force to re-record)")
        return

    params = {
        "action": action,
        "format": "json"
    }
    if action == "parse":
        params["page"] = key
        params["prop"] = "wikitext|sections|revid"
    elif key == "siteinfo":
        params["meta"] = "siteinfo"
        params["siprop"] = SITEINFO_PROPS
    else:
        params["list"] = "search"
        params["srsearch"] = key
        params["srlimit"] = 5

    url = f"{API_ENDPOINT}?{urlencode(params)}"
    print(f"Recording {action} for {key}...")

    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request) as response:
        data = json.loads(response.read().decode("utf-8"))

    with open(filename, "w") as f:
        json.dump(data, f, indent=2)
    print(f"Saved to {filename}")


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
        for _, _, name in extractor._iter_top_level_templates(wikitext, extractor._ANY_TEMPLATE_RE)
        if name and not extractor._NOT_A_TEMPLATE_TITLE.search(name)
    }
    return sorted(n for n in names if not extractor.canonical_admonition(n))


def record_aliases(page_title, force=False):
    """Record the redirect resolution for one page's template names."""
    names = unresolved_template_names(page_title)
    batch_size = extractor._TITLES_PER_QUERY
    batches = [names[i:i + batch_size] for i in range(0, len(names), batch_size)] or [[]]

    for index, batch in enumerate(batches):
        suffix = "" if len(batches) == 1 else f"_{index + 1}"
        filename = os.path.join(
            "tests/fixtures", fixture_filename("query", f"aliases_{page_title}{suffix}")
        )
        if os.path.exists(filename) and not force:
            print(f"Skipping {filename} (exists; pass --force to re-record)")
            continue

        params = {
            "action": "query",
            "titles": "|".join(f"Template:{name}" for name in batch),
            "redirects": "1",
            "format": "json",
        }
        print(f"Recording template aliases for {page_title} ({len(batch)} names)...")
        request = Request(f"{API_ENDPOINT}?{urlencode(params)}", headers={"User-Agent": USER_AGENT})
        with urlopen(request) as response:
            data = json.loads(response.read().decode("utf-8"))

        with open(filename, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)
        print(f"Saved to {filename}")


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
