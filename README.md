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

* **Flow**: The agent returns `revid: 858930` and `hash: 8b8dfad439...` with a deep link.
* **Value**: The hash covers `content_raw`, the verbatim wikitext, so you can grep the wiki source and check it yourself.

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
✅ **Tests**: 210 offline tests pinned to recorded wiki fixtures; 108/108 `{{bc}}`/`{{hc}}` blocks and 432/432 sections resolve correctly

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
* **`section`**: Single section, rendered for quoting + the verbatim slice + provenance.
* **`commands`**: Extract block-level code (`{{bc}}`, `{{hc}}`, indented) with SHA-256 hashes.
* **`warnings`**: Surface `{{Warning}}`, `{{Note}}`, etc.
* **`links`**: Extract internal wiki links.
* **`search`**: Public MediaWiki search API passthrough.

There is deliberately no tool that infers commands from prose.

### What `commands` returns

```json
{
  "content": "# grub-install --target=x86_64-efi --efi-directory=<esp> --bootloader-id=GRUB",
  "content_raw": "# grub-install --target=x86_64-efi --efi-directory=''esp'' --bootloader-id=GRUB",
  "content_hash": "8b8dfad439a8fb73f328ec9c2da75cf575e7a24ad945d3890ddc626f180b7a44",
  "content_hash_cleaned": "29e88b233ac641da1dec1beeb7500687263991279c8fd0d5762ca45479ffb12e",
  "block_type": "block_code",
  "source_pattern": "template_bc",
  "header": null,
  "placeholders": ["esp"],
  "source_url": "https://wiki.archlinux.org/title/GRUB#Installation",
  "revid": 858930
}
```

* `content` is runnable **once you substitute the placeholders**. Templates and emphasis
  are resolved; italicised placeholders stay marked as `<esp>` so a thoughtless paste fails
  at the shell instead of acting on the wrong path.
* `content_raw` is the verbatim payload, exactly as it appears in the wikitext.
* `content_hash` covers **`content_raw`**, so a human can grep the wiki source to falsify it.
* `content_hash_cleaned` covers **`content`** — the text you actually execute. Both
  fingerprints travel together, so the cleaning step is attested rather than trusted.
* `placeholders` names those tokens. 116 of the 327 code blocks in the fixture corpus have them.
* `header` carries the file path for `{{hc}}` blocks (`/etc/default/grub`).

`commands` fails closed. A missing page or missing anchor raises an error; `[]`
means the wiki specifies no command there, and nothing else.

### What `section` returns

When `commands()` returns `[]`, the contract sends the agent here to quote the wiki's
prose instead. So the same rendered/verbatim split applies:

```json
{
  "section_heading": "Boot the live environment",
  "extraction_method": "wikitext_character_offset",
  "content": "### Boot the live environment\n\n**Note:** Arch Linux installation images do not support Secure Bo ...",
  "content_raw": "=== Boot the live environment ===\n\n{{Note|Arch Linux installation images do not support Secure B ...",
  "content_hash": "b2ec52eef0b639a0fb2a761bdaf3eab9ae6de8ae08091025ad9cf51d022892b7",
  "content_hash_cleaned": "ef24f23bfc84c850417a1cbf5da6270d62f8d78985321dd3995f147685c485d5",
  "url": "https://wiki.archlinux.org/title/Installation_guide#Boot_the_live_environment",
  "revid": 858613
}
```

* `content` is rendered: headings become markdown, `{{bc}}`/`{{hc}}` become fenced
  blocks, `{{Note}}` becomes `**Note:**`, links and inline templates resolve.
* **Outside a fence, a leading `#` is a heading, never a shell prompt.** The wiki writes
  ordered lists as `# step`, which renders as `1. step`. Raw, `# Point the current boot
  device to the one which has the Arch Linux installation medium` is prose that reads
  exactly like a root command — the confusion that got the old `examples` tool deleted.
* A template the renderer does not know (`{{Accuracy|...}}`) is left as raw markup rather
  than dropped. Dropping the wiki's own caveat would be synthesis by omission.
* `content_raw` is the verbatim character slice; `content_hash` covers it, so the citation
  stays falsifiable. `content_hash_cleaned` covers the rendered text you show.

Code you intend to run should still come from `commands()`, which alone carries per-block
hashes and `placeholders`.

### What `warnings` returns

`message` is readable prose, safe to quote to a user. `message_raw` is the verbatim
template body; `content_hash` covers that, and `message_hash_cleaned` covers the
prose you actually show — so nothing an agent quotes goes unattested.

Translated pages do not write `{{Warning}}`. The Spanish Installation guide writes
`{{Note (Español)}}`; the French one writes `{{Attention}}`, a redirect to
`Template:Warning (Français)`. Those names are resolved **against the wiki**, not from
a list in this repo, so `warnings()` returns 13 blocks on the French page exactly as it
does on the English one. If a name cannot be resolved, `warnings()` raises — an
English-only subset would be an `[]` that an agent reads as "the wiki warns of nothing".

```json
{
  "type": "NOTE",
  "message": "Only root and members of the network or the wheel user group are allowed to interact with iwd. In order to use iwctl or other front-ends, you need to add your user to one of those groups.",
  "message_raw": "Only root and members of the {{ic|network}} or the {{ic|wheel}} [[user group]] are allowed to interact with ''iwd''. In order to use ''iwctl'' or other front-ends, you need to [[Users and groups#Group management|add your user to one of those groups]].",
  "content_hash": "9e183a7fb724a74e42120dc6f7e3d9631ca1036fb8758e3a481d1ff2ca22ed3a",
  "message_hash_cleaned": "27693d93de0969fc34ac243581e2f66693c6ae2b0f8cabc3098b86b49a290223",
  "source_url": "https://wiki.archlinux.org/title/Iwd#Usage",
  "revid": 847035
}
```

## Constitutional Guarantees

Every response includes:

* **Source URL**: Direct link to specific revision.
* **Revision ID**: MediaWiki revision number.
* **Content Hash**: SHA-256 fingerprint (NFC-normalized).
* **Extraction Method**: How content was obtained.

## Testing

```bash
pip install -e ".[test]"
pytest
```

Tests run fully offline against recorded API fixtures in `tests/fixtures/`; a wiki
edit can never turn them red. Re-record deliberately:

```bash
python3 tests/record_fixtures.py "GRUB" --force   # then update the golden constants
```

## Governance & Contracts

* `ARCH_WIKI_MCP_CONSTITUTION.md`: Technical and ethical contract.
* `AGENTS.md`: Mandatory behavioral contract for AI agents.
* `TEST_STRATEGY.md`: Validation report and hallucination traps.

## License

MIT License. Documentation (CC BY-SA 4.0).
