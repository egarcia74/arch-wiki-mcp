# Arch Wiki MCP Server

> **"This is not 'AI that knows Linux.' This is Linux that won't let AI lie about it."**

The Arch Wiki MCP is a **citability engine** that provides constitutional, deterministic extraction of the Arch Linux Wiki as machine-readable data. It acts as a **truth perimeter**, ensuring that AI agents can only provide technical advice that is **cryptographically fingerprinted and revision-attributed** to the wiki: every excerpt carries a SHA-256 fingerprint and a URL pinned to the exact revision it came from, so any claim can be re-fetched from the wiki and independently verified.

## Why this is special: Real Workflows

This MCP turns documentation into a versioned, auditable evidence stream — and is exact about 
how far that reaches:

* **`page`, `section`, `commands`, `warnings`** hand an agent text to quote, and carry both the 
  revision it came from and a fingerprint of the exact bytes. A claim can be checked, not trusted.
* **`links`** is revision-attributed but unhashed. A link is a target, not a quotation.
* **`search`, `sections`** are pointers, not evidence: no revid, no hash. A snippet quoted as fact 
  is the failure this project exists to prevent, so they refuse to look like evidence.

(These tiers are asserted by `test_contract.py`, not merely asserted here.)

### 1. "I need to run this command without bricking my system"

When an assistant shows a command, it’s not advice—it’s a content-addressed excerpt: you can follow the revision link and recompute the hash yourself.

* **Flow**: `search("GRUB")` → `commands("GRUB", "Installation")`
* **Result**: Precise command + revision-pinned URL + Revision ID + Content Hash.
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
* **Value**: The tool refuses rather than guessing, so an agent that invents an answer 
  here has to do it *without* evidence, visibly, instead of dressing a guess as a citation.

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

* **Value**: Every quotable excerpt is traceable to a revision, so unsupported instructions 
  are harder to produce and easier to catch.

---

## Status

✅ **Extractor**: Deterministic wikitext parser with hash stability  
✅ **MCP Server**: Thin wrapper exposing extractor as MCP tools  
✅ **Search**: MediaWiki search API integration complete  
✅ **Tests**: offline suite pinned to recorded wiki fixtures — extraction, protocol, 
packaging, registration and provenance invariants. Every `{{bc}}`/`{{hc}}` block in the 
corpus renders, and every recorded section resolves onto its own heading. (Counts live in 
the tests, where changing one fails something; a count in prose only goes quietly stale.)

## Quick Start

```bash
# Search wiki
arch-wiki-mcp search pacman

# Get full page with hash
arch-wiki-mcp page GRUB

# Get commands with content hashes
arch-wiki-mcp commands GRUB Installation

# Get warnings for safety
arch-wiki-mcp warnings GRUB Installation
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
  "revision_url": "https://wiki.archlinux.org/index.php?oldid=858930#Installation",
  "revision_wikitext_url": "https://wiki.archlinux.org/api.php?action=parse&oldid=858930&prop=wikitext&format=json",
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
  "revision_url": "https://wiki.archlinux.org/index.php?oldid=858613#Boot_the_live_environment",
  "revision_wikitext_url": "https://wiki.archlinux.org/api.php?action=parse&oldid=858613&prop=wikitext&format=json",
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
  "revision_url": "https://wiki.archlinux.org/index.php?oldid=847035#Usage",
  "revision_wikitext_url": "https://wiki.archlinux.org/api.php?action=parse&oldid=847035&prop=wikitext&format=json",
  "revid": 847035,
  "alias": null,
  "alias_target": null,
  "alias_revid": null
}
```

### Where a warning's type came from

`{{Note}}` spells out its own type, so the three `alias` fields above are `null`:
the evidence is in the wikitext that `revid` already covers.

`{{Attention}}` does not. It is a *redirect* to `Template:Warning (Français)`, and
the word `WARNING` appears nowhere in the article. Nothing in the block above
would attest such a type — so a block that gets its type this way carries the
redirect, including the revision of **the redirect page itself**:

```json
{
  "type": "WARNING",
  "message": "Ne formatez la partition système EFI que si vous l'avez créée pendant le partitionnement. S'il y avait déjà une partition système EFI sur le disque précédemment, son formatage peut détruire les chargeurs d'amorçage des autres systèmes d'exploitation installés.",
  "content_hash": "f007b1d054b1b6d2bc8d53a692d8ae530d7824256af4aa5fc5043a8d9e1ddb91",
  "source_url": "https://wiki.archlinux.org/title/Installation_guide_%28Fran%C3%A7ais%29",
  "revision_url": "https://wiki.archlinux.org/index.php?oldid=875238",
  "revision_wikitext_url": "https://wiki.archlinux.org/api.php?action=parse&oldid=875238&prop=wikitext&format=json",
  "revid": 875238,
  "alias": "Attention",
  "alias_target": "Template:Warning (Français)",
  "alias_revid": 675792
}
```

`revid` 875238 is the article. `alias_revid` 675792 is `Template:Attention`. They
are different pages, and only the second one moves if someone repoints the
redirect — which is the whole reason it is pinned. It is deliberately **not** the
revision of `Template:Warning (Français)`: MediaWiki resolves titles before
`prop=revisions` runs, so the obvious one-query lookup returns the destination's
revid, and a retarget never touches that.

If the redirect resolves but its revision cannot be read, `warnings()` raises. We
would know the page carries a `WARNING` and be unable to say why.

## Constitutional Guarantees

Every response includes:

* **Revision URL** (`revision_url`): The revision-addressed link (`?oldid=`). This is the one to
  cite. It resolves to the exact revision the hash was computed over, so it still
  serves the quoted text after the page moves on.
* **Source URL**: The canonical page, with anchor. This one *follows the page*: a
  reader opening it later sees the wiki's current state, not the quoted one. Both
  are returned because they answer different questions.
* **Revision ID**: MediaWiki revision number.
* **Content Hash**: SHA-256 fingerprint (NFC-normalized).
* **Extraction Method**: How content was obtained.

### What the hash proves — and what it does not

`content_hash` is an **unkeyed SHA-256 fingerprint**, not a digital signature. A
project whose product is falsifiable citation cannot afford to overstate its own
guarantees, so this section is exact about which bytes are covered by what.

**How to actually check a citation.** Fetch the revision's wikitext, find the
fragment, NFC-normalise it, SHA-256 it, and compare to `content_hash`:

```bash
# revision_wikitext_url -- the wiki's API, which a script can actually fetch:
curl -s 'https://wiki.archlinux.org/api.php?action=parse&oldid=<revid>&prop=wikitext&format=json' \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["parse"]["wikitext"]["*"])'
```

Every evidence block carries that URL as `revision_wikitext_url`. It is deliberately
*not* `index.php?oldid=N&action=raw`: that is the correct MediaWiki idiom and it works
in a browser, but `wiki.archlinux.org` answers a script there with an anti-bot
interstitial — **HTTP 200, an HTML challenge page, no wikitext**. A checker that hashed
that page would see a mismatch and conclude a good citation was forged. `api.php` is
ungated, and is the route this MCP uses itself.

**What each hash covers — and the one transformation you must apply:**

| Field | Covers | Who can verify it |
| --- | --- | --- |
| `content_hash` | `content_raw` — the fragment's wikitext | **Anyone**, against the wiki, via `revision_wikitext_url`. Contiguous slice of the revision for `section`, `warnings`, and `{{bc}}`/`{{hc}}` command blocks (for those, it is the template's *payload*, not the surrounding template call). |
| `content_hash_cleaned` | `content` — the rendered text an agent quotes | Only against *this MCP's* rendering. The wiki never held this string; we produced it. It attests that the shown text is the text we hashed — not that the wiki wrote it that way. |

⚠️ **`source_pattern: "indented_block"` is the exception, and it matters.** The wiki
marks preformatted text with a single leading space per line, and that space is the
*marker*, not the content — so `content_raw` has it stripped. Locate the fragment in
the raw wikitext and hash it unchanged and **you will get a mismatch**, on roughly
half the indented blocks of a page like GRUB. Strip one leading space from each line
first, then hash. We spell this out rather than describe `content_raw` as "byte-for-byte
what the revision stores", because it is not, and a reader who trusted that phrasing
would conclude a good citation was forged.

**It gives you**: integrity against a named revision. The wikitext of revision
`N` either hashes to `content_hash` or it does not, and anyone can check.

**It does not give you**: authenticity or origin attestation. It does not prove an
excerpt came from this MCP, and it cannot detect a response forged before it
reached you — anyone can compute a valid SHA-256 over text they invented. The hash
fingerprints content; it says nothing about who produced it.

**One caveat, stated because precision is the point.** A rendered `?oldid=` page
still transcludes templates at their *current* versions, so the rendered view of an
old revision is pinned but not frozen. The revision's **wikitext** is immutable, and
that is what the hashes cover — so the guarantee holds, but "pinned" is the honest
word, not "immutable".

A hash beside a URL whose content has since changed proves nothing at all. That is
why the hash and the revision URL travel together.

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
* `MCP_PROTOCOL.md`: The supported MCP subset, the error contract, and why this
  server implements the transport rather than depending on the SDK.
* `TEST_STRATEGY.md`: Validation report and hallucination traps.

## License

MIT License. Documentation (CC BY-SA 4.0).
