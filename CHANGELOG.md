# Changelog

## 2.1.0

A minor release. One new capability, and a large internal reorganization that no
consumer can observe.

### Added

- **`arch-wiki-mcp --check <config-file>`.** `2.0.0` gave `--check` the power to
  *print* a registration that works on this machine; it could not tell you the one
  already in your config is dead — which is the failure this project actually
  shipped. Now, given a config file, it finds every registration in it that names
  this server and *runs* them, because "Failed to connect" names a dead path, a
  missing package and an import error identically, and the only way to tell which
  is to start the command and ask who answered. Each is reported `healthy`,
  `fragile` (works, but resolved from a `PATH` a GUI client may not share), `dead`,
  or `foreign` (answers as a different server), and a correct registration is
  printed to replace any that fail.

  It executes commands drawn from the file you name, so it identifies a Python
  command's execution target the way CPython itself does — walking the argument
  list, honouring attached and clustered short options — so a data argument that
  merely *names* this project is never mistaken for the script to run. No released
  version ever shipped without this; the guarantee holds from the feature's first
  release.

### Internal

No behavioural change; the surface `2.0.0` documented is unchanged.

- The `--check` machinery moved into its own `registration.py`, and the MCP server
  was split from one ~1300-line `server.py` into `tools.py` (the seven wiki tools
  and their schema validation), `protocol.py` (JSON-RPC over stdio), and `cli.py`
  (argv parsing and the mode flags). `arch_wiki_mcp.server` remains the entry
  point every client spawns.
- Documentation: install instructions moved to the top of the README, the
  constitution reads core-first with amendments in an appendix, cross-document
  references are links, and every doc lints clean under a committed
  `.markdownlint.jsonc`.

## 2.0.0

The first release with a number that means anything. There were no tags before this
one: `1.7.0` was a version the code reported and no artifact ever carried.

It is a major bump because a consumer of `1.7.0` breaks in four ways.

### Breaking

- **The package moved.** `src.extractor` is now `arch_wiki_mcp.extractor`, and the
  server is `arch_wiki_mcp.server`. The old `src/` layout let the same file load
  twice under two names.
- **The entry point moved.** `python3 src/mcp_server.py --stdio` is gone. Install the
  package and run `arch-wiki-mcp --stdio`. **Any MCP client registered against the old
  path stops working** — the client will say only "Failed to connect". Run
  `arch-wiki-mcp --check` and re-register with what it prints.
- **`revision_raw_url` is now `revision_wikitext_url`,** and points at `api.php`
  rather than `index.php?action=raw`. The old URL answered a script with an anti-bot
  HTML page — carrying HTTP 200 — so an auditor who fetched it hashed a challenge
  page, got a mismatch, and would have concluded that a good citation was forged.
- **Errors are typed.** A tool that cannot answer returns an MCP `isError` result
  carrying a code (`page_not_found`, `section_not_found`, `evidence_unresolvable`,
  `upstream_api_error`, `malformed_wiki_url`). A malformed *call* returns a JSON-RPC
  error instead (`-32700`, `-32600`, `-32601`, `-32602`, `-32603`). Previously both
  arrived as prose, and a client's mistake was frequently reported as ours.

### Added

- `arch-wiki-mcp --check`: verifies the install and prints an MCP registration for
  this machine on stdout, ready to redirect into a client config. The path is
  resolved from the running interpreter and the installer's own entry-point metadata,
  because a bare command name resolves only against whatever `PATH` the client
  inherits — and a GUI client inherits the desktop session's, not your shell's.
- `revision_url` on every evidentiary response: a URL pinned to the revision the text
  was actually taken from. `source_url` remains the canonical page, which *follows*
  the page and may no longer contain the quoted text at all.
- Alias provenance: a warning whose type comes from a template redirect now carries
  `alias`, `alias_target`, `alias_revid` and `alias_revision_url`. The French guide
  writes `{{Astuce}}`; the word "TIP" appears nowhere in the article's own wikitext,
  so the article's revision cannot attest it and the redirect's must.
- `pipx install` support (no runtime dependencies, one console script).

### Fixed

- Percent-encoded and translated wiki URLs resolve to the page they name, instead of
  being handed to the wiki as a literal title that finds nothing.
- Foreign and look-alike hosts are refused rather than fetched.
- Section slicing uses MediaWiki's `byteoffset` as a **character** index, which is
  what it actually is despite its name. Byte indexing silently returned a
  neighbouring section's text on any page containing one accented letter.
- Every request to the wiki is bounded by a timeout and identifies itself with the
  version actually running.
