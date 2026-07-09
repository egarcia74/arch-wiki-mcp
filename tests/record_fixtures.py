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

from src.extractor import fixture_filename

API_ENDPOINT = "https://wiki.archlinux.org/api.php"
USER_AGENT = "ArchWikiMCP/1.0 (Fixture Generator)"

CORPUS = [
    ("parse", "GRUB"),
    ("parse", "Pacman"),
    ("parse", "Iwd"),
    ("parse", "KDE"),
    ("parse", "Systemd"),
    ("parse", "Users and groups"),
    ("parse", "Installation guide"),
    ("parse", "Installation guide (Español)"),  # Non-English body: NFC + UTF-8 offsets
    ("query", "GRUB"),
    ("query", "C++"),
    ("query", "Iwd (简体中文)"),
    ("query", "wifi not working"),
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


if __name__ == "__main__":
    # Existing fixtures are never silently overwritten: re-recording moves the
    # revids and hashes the golden tests pin, and must be a deliberate act.
    force = "--force" in sys.argv
    wanted = [a for a in sys.argv[1:] if a != "--force"]

    os.makedirs("tests/fixtures", exist_ok=True)
    for action, key in CORPUS:
        if not wanted or key in wanted:
            record_fixture(action, key, force=force)
