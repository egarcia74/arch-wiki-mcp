# Arch Wiki MCP Server

**Constitutional, deterministic extraction of Arch Linux Wiki as machine-readable data.**

## Status

✅ **Extractor**: Deterministic wikitext parser with hash stability  
✅ **MCP Server**: Thin wrapper exposing extractor as MCP tools  
✅ **Search**: MediaWiki search API integration complete

## Quick Start

```bash
# Search wiki
python3 src/mcp_server.py search pacman

# Get full page with revid and hash
python3 src/mcp_server.py page GRUB

# Get section with provenance
python3 src/mcp_server.py section GRUB Installation

# Get commands with content hashes
python3 src/mcp_server.py commands GRUB Installation

# Get warnings with content hashes
python3 src/mcp_server.py warnings GRUB Installation

# Get internal links
python3 src/mcp_server.py links GRUB Installation
```

## MCP Tools

All tools accept `title_or_url` (e.g., `"GRUB"` or `"https://wiki.archlinux.org/title/GRUB"`).

### `page(title_or_url)`

Returns full page with metadata:

```json
{
  "title": "GRUB",
  "pageid": 5984,
  "revid": 858930,
  "url": "https://wiki.archlinux.org/title/GRUB",
  "wikitext": "...",
  "wikitext_hash": "58498a1a18f290df...",
  "sections": [...]
}
```

### `sections(title_or_url)`

Returns section list with anchors and byte offsets:

```json
{
  "sections": [
    {
      "line": "Installation",
      "anchor": "Installation",
      "byteoffset": 2652,
      "level": "3",
      ...
    }
  ]
}
```

### `section(title_or_url, anchor)`

Returns single section with full provenance:

```json
{
  "title": "GRUB",
  "url": "https://wiki.archlinux.org/title/GRUB#Installation",
  "revid": 858930,
  "section_anchor": "Installation",
  "section_heading": "Installation",
  "extraction_method": "wikitext_byte_offset",
  "content": "...",
  "content_hash": "720f6d4b7fb711a9..."
}
```

### `commands(title_or_url, [anchor])`

Returns code blocks with hashes:

```json
{
  "commands": [
    {
      "content": "# pacman -S grub",
      "content_hash": "2cf8a5d99d271b33...",
      "block_type": "shell",
      "language": "bash",
      "source_url": "https://wiki.archlinux.org/title/GRUB#Installation"
    }
  ]
}
```

### `warnings(title_or_url, [anchor])`

Returns warning templates with hashes:

```json
{
  "warnings": [
    {
      "type": "WARNING",
      "message": "...",
      "content_hash": "e937a8302be0f9b2...",
      "source_url": "https://wiki.archlinux.org/title/GRUB#Installation"
    }
  ]
}
```

### `links(title_or_url, [anchor])`

Returns internal wiki links:

```json
{
  "links": [
    {
      "target_page": "EFI system partition",
      "display_text": "Mount the partition",
      "source_page": "GRUB",
      "source_url": "https://wiki.archlinux.org/title/GRUB#Installation"
    }
  ]
}
```

### `search(query, [limit])`

Search the Arch Wiki using MediaWiki search API:

```json
{
  "results": [
    {
      "title": "Pacman",
      "pageid": 9454,
      "snippet": "...<span class=\"searchmatch\">pacman</span>...",
      "url": "https://wiki.archlinux.org/title/Pacman"
    }
  ]
}
```

## Constitutional Guarantees

Every response includes:

✅ **Source URL** - Direct link to wiki page/section  
✅ **Revision ID** - MediaWiki revision number  
✅ **Content Hash** - SHA-256 of extracted text (NFC-normalized, whitespace preserved)  
✅ **Extraction Method** - How content was extracted (e.g., `wikitext_byte_offset`)

This enables:
- **Reproducibility**: Same revid → same hash
- **Forensic soundness**: Prove exactly what was extracted
- **Blame assignment**: Trace advice to exact wiki version
- **Auditability**: Verify AI didn't fabricate content

## Testing

```bash
# Hash stability regression test
python3 tests/test_extractor.py

# MCP server integration test
python3 tests/test_mcp.py
```

## Architecture

```
User → MCP Server → Extractor → MediaWiki API → Arch Linux Wiki
       (src/mcp_server.py)   (src/extractor.py)
          ↓                      ↓
    Thin wrapper            Truth engine
    No parsing              Wikitext parser
    Passthrough             Hash generator
```

**MCP Server** (`src/mcp_server.py`):
- Thin wrappers around extractor
- URL → title parsing
- JSON serialization
- No wiki parsing

**Extractor** (`src/extractor.py`):
- Single source of truth
- Wikitext parsing (not HTML)
- Template detection ({{Warning}}, etc.)
- Code block extraction (4 patterns)
- Link extraction ([[Target]])
- SHA-256 hashing with NFC normalization

## Governance

See:
- `ARCH_WIKI_MCP_CONSTITUTION.md` - Technical contract
- `AGENTS.md` - AI agent behavioral contract
- `MEDIAWIKI_API_AUDIT.md` - API capability findings

## Implementation Notes

1. **Hash stability requires revid pinning**  
   Hashes are stable for same revid, not across time.

2. **Code blocks use multiple patterns**  
   - Leading-space preformatted
   - Shell prompts (`#`, `$`)
   - `<pre>` and `<code>` tags

3. **Warnings use template syntax**  
   `{{Warning|text}}`, `{{Note|text}}`, `{{Tip|text}}`

4. **MCP tools are passthrough**  
   No reformatting, no synthesis, no "helpfulness"

## License

MIT License. See `ARCH_WIKI_MCP_CONSTITUTION.md` for full licensing details on documentation (CC BY-SA 4.0) and code.

## Project Status

- [x] MediaWiki API audit
- [x] Constitutional specification
- [x] Deterministic extractor
- [x] Hash stability proof
- [x] MCP server thin wrappers
- [x] Integration tests
- [x] Search implementation
- [x] MCP setup documentation
- [x] MCP protocol integration
- [x] Client testing (Claude, Cline, etc.)
- [ ] Deployment configuration (final phase)

**All 7 MCP tools operational. Ready for high-fidelity evidence relay.**
