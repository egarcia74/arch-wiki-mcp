import json
import os
import sys
from urllib.request import urlopen, Request
from urllib.parse import urlencode

# Ensure we can run this from repo root
sys.path.insert(0, os.path.abspath("."))

API_ENDPOINT = "https://wiki.archlinux.org/api.php"
USER_AGENT = "ArchWikiMCP/1.0 (Fixture Generator)"

def record_fixture(action, key):
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
    
    safe_key = "".join([c if c.isalnum() else "_" for c in key])
    filename = f"tests/fixtures/{action}_{safe_key}.json"
    
    with open(filename, "w") as f:
        json.dump(data, f, indent=2)
    print(f"Saved to {filename}")

if __name__ == "__main__":
    os.makedirs("tests/fixtures", exist_ok=True)
    record_fixture("parse", "GRUB")
    record_fixture("parse", "Pacman")
    record_fixture("parse", "Iwd")
    record_fixture("parse", "KDE")
    record_fixture("parse", "Systemd")
    record_fixture("parse", "Users and groups")
    record_fixture("query", "GRUB")
    record_fixture("query", "C++")
    record_fixture("query", "Iwd (简体中文)")
    record_fixture("query", "wifi not working")
    record_fixture("parse", "Installation guide")
