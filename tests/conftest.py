"""
Offline test harness.

The extractor reads fixtures instead of the network when ARCHWIKI_OFFLINE is
set. Nothing set it before, so the suite silently hit the live wiki and the
recorded fixtures were never exercised. Setting it here makes tests/fixtures/
the authoritative source for the whole suite.

ARCHWIKI_FIXTURES must be absolute: extractor._fetch_offline defaults to the
relative "tests/fixtures", which only resolves when pytest runs from the repo
root.
"""

import json
import os
import sys
from functools import lru_cache
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent / "fixtures"

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.extractor import fixture_filename

# Offline mode must be active before any test imports trigger a fetch.
os.environ["ARCHWIKI_OFFLINE"] = "1"
os.environ["ARCHWIKI_FIXTURES"] = str(FIXTURES_DIR)


@lru_cache(maxsize=None)
def load_parse(page: str) -> dict:
    """Load a recorded action=parse response by page title."""
    with open(FIXTURES_DIR / fixture_filename("parse", page)) as handle:
        return json.load(handle)["parse"]


def load_wikitext(page: str) -> str:
    return load_parse(page)["wikitext"]["*"]


# Pinned from the committed fixture rather than transcribed by hand, so
# re-recording GRUB moves this in one place.
GRUB_REVID = load_parse("GRUB")["revid"]
