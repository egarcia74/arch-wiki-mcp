# Arch Wiki MCP Server

> **"This is not 'AI that knows Linux.' This is Linux that won't let AI lie about it."**

The Arch Wiki MCP is a **citability engine** that provides constitutional, deterministic extraction of the Arch Linux Wiki as machine-readable data. It acts as a **truth perimeter**, ensuring that AI agents can only provide technical advice that is cryptographically traceable to the wiki.

## Why this is special: Real Workflows

This MCP does what no other tool can: it turns documentation into a versioned, auditable evidence stream.

### 1. "I need to run this command without bricking my system"

When an assistant shows a command, it’s not advice—it’s a signed excerpt.

* **Flow**: `search("GRUB")` → `commands("GRUB", "Installation")`
* **Result**: Precise command + URL + Revision ID + Content Hash.
* **Value**: You run what the wiki says, not what an LLM hallucinated.

### 2. "I don’t trust AI, prove it"

Skeptical sysadmins can audit exactly what the AI says against the wiki's current state.

* **Flow**: The agent returns `revid: 858930` and `hash: 2cf8a5d99d...` with a deep link.
* **Value**: Cryptographic proof that the AI didn't make it up.

### 3. "The wiki changed, did the advice change?"

Detect when documentation updates invalidate previous instructions.

* **Flow**: Compare `hash A` (old) vs `hash B` (current).
* **Value**: Documentation as a versioned data stream, not "vibes."

### 4. "Stop guessing what I meant"

Forces the AI to fail closed instead of guessing when a query is ambiguous.

* **Flow**: `search("wifi")` → many results → Agent refuses to guess.
* **Value**: Every other assistant will hallucinate here. Yours won't.

### 5. "I want raw data, not a tutorial"

A structured API for automation engineers to build tools on top of Arch knowledge.

* **Flow**: Call `links()`, `sections()`, and `commands()` programmatically.
* **Value**: It’s not a chat bot. It’s a documentation API.

### 6. "Don’t hide the warnings"

Suppresses the AI's tendency to sound confident by surfacing every warning template.

* **Flow**: `warnings("GRUB", "Installation")`
* **Value**: Returns all 5 warning blocks with hashes. No skipping the dangerous parts.

### 7. "Build on top of Arch knowledge safely"

A reliable backend for IDEs, scripts, and agents.

* **Value**: Safe embedding of Arch knowledge without the risk of hallucination.

---

## Status

✅ **Extractor**: Deterministic wikitext parser with hash stability  
✅ **MCP Server**: Thin wrapper exposing extractor as MCP tools  
✅ **Search**: MediaWiki search API integration complete  
✅ **Audit**: 100% provenance integrity verified

## Quick Start

```bash
# Search wiki
python3 src/mcp_server.py search pacman

# Get full page with hash
python3 src/mcp_server.py page GRUB

# Get commands with content hashes
python3 src/mcp_server.py commands GRUB Installation

# Get warnings for safety
python3 src/mcp_server.py warnings GRUB Installation
```

## MCP Tools

All tools accept `title_or_url` (e.g., `"GRUB"` or `https://wiki.archlinux.org/title/GRUB`).

* **`page`**: Full page metadata + wikitext + hash.
* **`sections`**: List anchors and hierarchy.
* **`section`**: Single section content + provenance.
* **`commands`**: Extract code blocks with SHA-256 hashes.
* **`warnings`**: Surface {{Warning}}, {{Note}}, etc.
* **`links`**: Extract internal wiki links.
* **`search`**: Public MediaWiki search API passthrough.

## Constitutional Guarantees

Every response includes:

* **Source URL**: Direct link to specific revision.
* **Revision ID**: MediaWiki revision number.
* **Content Hash**: SHA-256 fingerprint (NFC-normalized).
* **Extraction Method**: How content was obtained.

## Testing

```bash
# Verify hash stability and provenance integrity
python3 tests/test_extractor.py
python3 tests/test_mcp.py
```

## Governance & Contracts

* `ARCH_WIKI_MCP_CONSTITUTION.md`: Technical and ethical contract.
* `AGENTS.md`: Mandatory behavioral contract for AI agents.
* `TEST_STRATEGY.md`: Validation report and hallucination traps.

## License

MIT License. Documentation (CC BY-SA 4.0).
