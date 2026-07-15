# MCP Setup Guide

## Installation

### Prerequisites

Everything this guide tells you to run, and nothing it does not. (A test enforces
that: a setup document must not ask you for a tool it never told you to get.)

- **Python 3.10+** — provides `python3` and `pip`
- **[pipx](https://pipx.pypa.io)** — the recommended install path below. Arch:
  `pacman -S python-pipx`; elsewhere: `python3 -m pip install --user pipx`
- **git** — only to install an unreleased commit, or to work on the project
- **Internet access** — for the MediaWiki API
- **An MCP client** — the `claude` snippet below assumes Claude Code; other clients
  take the same registration as JSON

### Install

To *use* it, install it into its own environment with pipx:

```bash
pipx install arch-wiki-mcp
```

Or from source, to get a commit that has not been released:

```bash
pipx install git+https://github.com/egarcia74/arch-wiki-mcp.git
```

To *work on* it, clone and install in editable mode:

```bash
git clone https://github.com/egarcia74/arch-wiki-mcp.git
cd arch-wiki-mcp
pip install -e ".[test]"
```

Either way, run `arch-wiki-mcp --check` next: it prints the registration to give your
MCP client.

No runtime dependencies — the standard library only. The install exists to put the
package on the import path and provide the `arch-wiki-mcp` console script; it pulls
in nothing.

---

## MCP Client Configuration

Do not transcribe a path. Ask for one:

```bash
arch-wiki-mcp --check
```

It verifies the package is installed and prints the registration for *this* machine
on stdout, ready to paste:

```json
{
  "mcpServers": {
    "arch-wiki": {
      "command": "/absolute/path/to/arch-wiki-mcp",
      "args": ["--stdio"]
    }
  }
}
```

The path is absolute on purpose. A bare `arch-wiki-mcp` resolves only against the
PATH the client happens to inherit — and a GUI client inherits the desktop
session's, not your shell's, so the config that works in a terminal can fail in the
app. If you use a virtualenv, run `--check` from inside it: the path it prints is the
one that has the package.

If it prints nothing and exits non-zero, it is telling you the package is not
installed for that interpreter. That is the whole point of it — an MCP client
reports a dead path, a missing package and an import error with the same three
words, "Failed to connect".

### Claude Code

Take the `command` that `--check` printed and pass it:

```bash
claude mcp add arch-wiki -- /the/path/--check/printed --stdio
```

Not `$(command -v arch-wiki-mcp)`. That asks your shell's PATH — the mechanism this
whole page exists to stop trusting — and if it finds nothing it expands to *nothing*,
registering a server with no command at all. Which fails, of course, as
"Failed to connect".

### Claude Desktop

**macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`  
**Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

Paste the `--check` output into that file.

### Cline (VS Code Extension)

Paste the `--check` output into Cline's MCP settings.

### Generic MCP Client

Use the `command` and `args` from `--check`, with an empty `env`.

### After an upgrade, a rename, or a moved virtualenv

Re-run `--check` and **re-register with what it prints**, rather than comparing it
against what you have. Replacing is idempotent — if the registration was already
right you rewrite it unchanged, and if it had gone stale you have just fixed it — so
it sidesteps the manual path comparison this page exists to get rid of.

A registration is a path written once into a file nobody opens again, and nothing in
this repository can reach out and correct a stale one. Re-registering is the step that
does.

---

## Available Tools

Once configured, the following MCP tools are available:

### `search(query, limit?)`

Search the Arch Wiki.

**Example**:

```text
Search for "grub installation"
```

**Returns**: List of search results with titles, snippets, URLs

---

### `page(title_or_url)`

Get full page content with metadata.

**Example**:

```text
Get page "GRUB"
```

**Returns**: Title, revision ID, wikitext, hash, sections

---

### `sections(title_or_url)`

List all sections in a page.

**Example**:

```text
List sections of "Installation_guide"
```

**Returns**: Section anchors, byte offsets, hierarchy

---

### `section(title_or_url, anchor)`

Extract specific section with provenance.

**Example**:

```text
Get section "Installation" from "GRUB"
```

**Returns**: Section content, hash, extraction method, URL

---

### `commands(title_or_url, anchor?)`

Extract code blocks from page or section.

**Example**:

```text
Get commands from GRUB § Installation
```

**Returns**: Code blocks with content hashes and source URLs

---

### `warnings(title_or_url, anchor?)`

Extract warning/note/tip templates.

**Example**:

```text
Get warnings from GRUB § Installation
```

**Returns**: Warning templates with hashes and types

---

### `links(title_or_url, anchor?)`

Extract internal wiki links.

**Example**:

```text
Get links from GRUB § Installation
```

**Returns**: Internal links with targets and display text

---

## Verification

After configuration:

1. **Restart your MCP client** (Claude Desktop, VS Code, etc.)
2. **Test search**: Ask "Search the Arch Wiki for pacman"
3. **Test extraction**: Ask "What does the GRUB installation section say?"

You should see responses with:

- ✅ Direct wiki URLs
- ✅ Revision IDs
- ✅ Content hashes
- ✅ Exact command citations

---

## Troubleshooting

### "Failed to connect" / "Command not found"

Those three words are what a client says for a dead path, an uninstalled package, an
import error and a firewall alike. Point the preflight at the config, and it will say
which:

```bash
arch-wiki-mcp --check ~/.claude.json
```

It finds every Arch Wiki registration in the file — wherever your client keeps them —
and **runs** them. It does not compare paths; it starts the command and asks who
answered.

```console
$ arch-wiki-mcp --check ~/.claude.json
~/.claude.json
      python3 /home/you/code/arch-wiki-mcp/src/mcp_server.py --stdio
  XX  projects./home/you/code/arch-wiki-mcp.mcpServers.arch-wiki
      python3: can't open file '/home/you/code/arch-wiki-mcp/src/mcp_server.py': [Errno 2] No such file or directory

1 registration(s) a client cannot start. Replace with:
{ "mcpServers": { "arch-wiki": { "command": "/home/you/.local/bin/arch-wiki-mcp", ... } } }
```

- `OK` — it starts and answers as this server. Nothing to do.
- `??` — it works, but the command is bare, so it resolves from PATH. That is the
  config that passes in a terminal and fails in a GUI client, which inherits the
  desktop session's PATH and not your shell's.
- `XX` — a client cannot start it. The replacement is printed; paste it over.

Other servers in the same file are left alone, and never run.

With no config argument it simply prints the registration that works here:

```bash
arch-wiki-mcp --check
```

- **Exits non-zero**: the package is not installed for that interpreter. `pip install -e .`
- **Prints a registration**: the server is fine. Replace whatever your client has.
- **Your shell cannot find `arch-wiki-mcp` either**: then asking it to check itself
  is no help. Ask the interpreter instead — it does not need PATH:

  ```bash
  python3 -m arch_wiki_mcp.server --check
  ```

  The package can be installed while its script sits somewhere PATH never looks
  (a `pip install --user`, with `~/.local/bin` unset). `--check` handles that: it
  will hand you a registration built on the interpreter rather than the script.

### "Module not found"

The package lives under `src/`, so it is importable only once installed. Run
`pip install -e .` from the repository root. To run without installing:

```bash
PYTHONPATH=src python3 -m arch_wiki_mcp.server --stdio
```

### "Connection timeout"

The wiki API may be slow or unreachable. The server uses 30-second timeouts by default.

### "No tools available"

Check MCP client logs. The server should register 7 tools on startup.

---

## Development Mode

For testing without an MCP client:

```bash
# Test search
arch-wiki-mcp search pacman

# Test page extraction
arch-wiki-mcp page GRUB

# Test section extraction
arch-wiki-mcp section GRUB Installation

# Test commands
arch-wiki-mcp commands GRUB Installation
```

---

## Constitutional Guarantees

Every response includes:

- **Revision URL** (`revision_url`): Link pinned to the exact revision (`?oldid=`).
  Cite this one — it still serves the quoted text after the page moves on.
- **Revision Wikitext URL** (`revision_wikitext_url`): That revision's wikitext, via
  the wiki's API — the bytes `content_hash` is computed over, at a URL a script can
  actually fetch. (The `index.php` raw view answers automation with an anti-bot page.)
- **Source URL** (`source_url` / `url`): The canonical page. It *follows the page*
  and shows the wiki's current state, not the quoted one.
- **Revision ID**: MediaWiki revision number
- **Content Hash**: SHA-256 fingerprint (NFC-normalized) of the verbatim wikitext.
  A fingerprint, not a signature — see [README.md](README.md) for exactly what it proves.
- **Extraction Method**: How content was obtained

This enables:

- **Reproducibility**: Same revid → same hash
- **Integrity checking**: Detect an excerpt that does not match the revision it
  names. This is *not* a signature: it cannot prove an excerpt came from this MCP,
  nor detect one forged before it reached you — anyone can hash text they invented.
- **Traceability**: Follow citations to the exact wiki revision

---

## Security Notes

1. **No authentication required**: Uses public MediaWiki API
2. **Read-only**: Server never modifies wiki content
3. **No caching**: Every request hits live wiki (may change)
4. **No data collection**: No telemetry, logging, or tracking

---

## Performance

- **Latency**: ~200-500ms per request (network dependent)
- **Rate limits**: None enforced by server (wiki may throttle)
- **Concurrency**: Single-threaded (one request at a time)

For production use, consider:

- Caching layer (by `(title, revid)`)
- Rate limiting
- Response compression

---

## License

MIT License. See [ARCH_WIKI_MCP_CONSTITUTION.md](ARCH_WIKI_MCP_CONSTITUTION.md) for full licensing details on documentation (CC BY-SA 4.0) and code.

---

## Support

- **Issues**: [https://github.com/egarcia74/arch-wiki-mcp/issues](https://github.com/egarcia74/arch-wiki-mcp/issues)
- **Governance**: See [ARCH_WIKI_MCP_CONSTITUTION.md](ARCH_WIKI_MCP_CONSTITUTION.md)
- **Agent Contract**: See [AGENTS.md](AGENTS.md)
