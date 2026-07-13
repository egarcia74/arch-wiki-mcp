# MCP Setup Guide

## Installation

### Prerequisites

- Python 3.10+
- Internet access (for MediaWiki API calls)

### Clone Repository

```bash
git clone https://github.com/egarcia74/arch-wiki-mcp.git
cd arch-wiki-mcp
pip install -e .
```

No runtime dependencies — the standard library only. The install exists to put the
package on the import path and provide the `arch-wiki-mcp` console script; it pulls
in nothing.

---

## MCP Client Configuration

### Claude Desktop

Add to your Claude Desktop config file:

**macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`  
**Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "arch-wiki": {
      "command": "arch-wiki-mcp",
      "args": ["--stdio"]
    }
  }
}
```

### Cline (VS Code Extension)

Add to Cline's MCP settings:

```json
{
  "mcpServers": {
    "arch-wiki": {
      "command": "arch-wiki-mcp",
      "args": ["--stdio"]
    }
  }
}
```

### Generic MCP Client

For any MCP-compatible client, use:

```json
{
  "name": "arch-wiki",
  "command": "arch-wiki-mcp",
  "args": ["--stdio"],
  "env": {}
}
```

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

### "Command not found"

The console script is installed by `pip install -e .`. Check it is on your PATH:

```bash
which arch-wiki-mcp
```

If your MCP client does not inherit your shell's PATH (common for GUI apps), give
the absolute path that command prints.

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
  A fingerprint, not a signature — see `README.md` for exactly what it proves.
- **Extraction Method**: How content was obtained

This enables:

- **Reproducibility**: Same revid → same hash
- **Auditability**: Verify AI didn't fabricate
- **Traceability**: Follow citations to exact wiki version

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

MIT License. See `ARCH_WIKI_MCP_CONSTITUTION.md` for full licensing details on documentation (CC BY-SA 4.0) and code.

---

## Support

- **Issues**: [https://github.com/egarcia74/arch-wiki-mcp/issues](https://github.com/egarcia74/arch-wiki-mcp/issues)
- **Governance**: See `ARCH_WIKI_MCP_CONSTITUTION.md`
- **Agent Contract**: See `AGENTS.md`
