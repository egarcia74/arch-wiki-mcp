# MCP Setup Guide

## Installation

### Prerequisites

- Python 3.8+
- Internet access (for MediaWiki API calls)

### Clone Repository

```bash
git clone https://github.com/egarcia74/arch-wiki-mcp.git
cd arch-wiki-mcp
```

No dependencies required - uses Python standard library only.

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
      "command": "python3",
      "args": [
        "/absolute/path/to/arch-wiki-mcp/src/mcp_server.py"
      ]
    }
  }
}
```

Replace `/absolute/path/to` with your actual installation path.

### Cline (VS Code Extension)

Add to Cline's MCP settings:

```json
{
  "mcpServers": {
    "arch-wiki": {
      "command": "python3",
      "args": [
        "/absolute/path/to/arch-wiki-mcp/src/mcp_server.py"
      ]
    }
  }
}
```

### Generic MCP Client

For any MCP-compatible client, use:

```json
{
  "name": "arch-wiki",
  "command": "python3",
  "args": ["/absolute/path/to/arch-wiki-mcp/src/mcp_server.py"],
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

### "Command not found" or "Permission denied"

Ensure `mcp_server.py` is executable:

```bash
chmod +x src/mcp_server.py
```

Verify Python path:

```bash
which python3
# Use this full path in config if needed
```

### "Module not found"

Ensure you're using absolute paths in the config, not relative paths.

### "Connection timeout"

The wiki API may be slow or unreachable. The server uses 30-second timeouts by default.

### "No tools available"

Check MCP client logs. The server should register 7 tools on startup.

---

## Development Mode

For testing without an MCP client:

```bash
# Test search
python3 src/mcp_server.py search pacman

# Test page extraction
python3 src/mcp_server.py page GRUB

# Test section extraction
python3 src/mcp_server.py section GRUB Installation

# Test commands
python3 src/mcp_server.py commands GRUB Installation
```

---

## Constitutional Guarantees

Every response includes:

- **Source URL**: Direct link to wiki revision
- **Revision ID**: MediaWiki revision number
- **Content Hash**: SHA-256 fingerprint (NFC-normalized)
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
