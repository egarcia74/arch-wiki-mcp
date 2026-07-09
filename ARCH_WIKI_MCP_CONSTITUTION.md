# Arch Wiki MCP: Technical Constitution

**Version:** 1.4  
**Status:** Canonical  
**Last Updated:** 2026-07-09

---

## Amendment 1.4 — Migration Notes

Found by using the server as an agent rather than testing it from outside.

### Corrected in 1.4

- **`extraction_method` reported `wikitext_byte_offset`.** It slices by character.
  A provenance field that misstates the extraction method is not cosmetic in a
  system whose product *is* provenance. Now `wikitext_character_offset`.

### Changed in 1.4

- **`warnings()` returns readable prose.** §5 requires the agent to quote warnings
  to the user, but `message` shipped raw wikitext — `{{ic|network}}`, `[[user
  group]]`, `''iwd''`, leading `::*` — making the mandated response shape
  unreadable. `message` now resolves inline templates, links and emphasis;
  `message_raw` preserves the verbatim body, and `content_hash` covers **that**,
  so falsifiability against the wiki source is unchanged in kind.
  `message_hash_cleaned` covers the prose the agent is obliged to quote, closing
  the same attestation gap that `content_hash_cleaned` closes for code.

  Ordered-list markers render as `1.` rather than `#`. A bare `#` in agent-facing
  prose reads as a root shell prompt — the exact confusion that made the removed
  `examples()` tool emit prose as bash.

  *Migration:* every warning `content_hash` changes, because the body is now split
  on the first **top-level** pipe. The old `split("|", 1)` truncated any message
  containing a pipe inside a nested `{{ic|a{{!}}b}}` or `[[link|text]]`.

- **Code blocks gained `content_hash_cleaned`.** `content_hash` attests
  `content_raw`, but an agent executes `content`. The cleaning step was the only
  non-verbatim transform in the chain and the only one no hash attested. Both
  fingerprints now travel with every block, closing that gap in §7 falsifiability.

- **Link exclusion is derived from the wiki, not hardcoded.** `links()` now reads
  `action=query&meta=siteinfo&siprop=namespaces|namespacealiases|interwikimap`
  (cached per process). The previous static list was missing 32 real interwiki
  prefixes — `fedora`, `doi`, `phab`, `mw`, `meta`, `lv` and others — each of
  which was reported as a navigable article link, and it wrongly excluded `man`
  and `kernel`, which are not interwiki prefixes on this wiki.

  Silently keeping an interwiki link is synthesis by inclusion, exactly as
  silently dropping a real one is synthesis by omission. If siteinfo is
  unreachable the static snapshot is used: `links()` is a navigation aid, not a
  command source, and degrading it beats failing the call. The fallback is logged
  and is never cached, so a transient failure cannot pin the rotted list for the
  life of the process.

---

## Amendment 1.3 — Migration Notes

Per §12 (API Governance), this breaking change to response structure is recorded here.

### Removed in 1.3

- **The `examples` tool**, and the prose-to-shell heuristic behind it. It read any
  line beginning with `#` as a shell prompt, but `#` is wikitext's numbered-list
  marker, so it returned prose tagged as `bash`. It contradicted §3 ("not a
  command generator"), §8 ("generate synthetic examples" — prohibited), and
  AGENTS.md §6 (Exclusive Command Source). The `arch-wiki-usage` prompt no longer
  offers "heuristic inference" as an allowed response shape.

  *Migration:* there is no replacement. When `commands()` returns `[]`, quote the
  prose via `section()` and let the user decide, as §5 requires.

### Changed in 1.3

- **`commands()` fails closed.** It previously wrapped its body in
  `except Exception: return []`, so a network error, a missing page, and a missing
  anchor were indistinguishable from an honest empty result. A missing page or
  anchor now raises. `[]` means the wiki specifies no command there — nothing else.
- **`commands()` extracts `{{bc}}` and `{{hc}}`**, the templates that carry
  essentially all real Arch Wiki code. It previously matched only indented lines,
  `<pre>` and `<code>`; the latter two occur nowhere in the sampled corpus.
  Inline `{{ic}}` remains excluded: it marks paths, flags and package names.
- **`section()` slices by character offset.** MediaWiki's `byteoffset` indexes
  characters despite its name; encoding first returned a neighbouring section's
  text on any page containing a multibyte character, under a valid-looking hash.
  A slice that does not land on a heading now raises.
- **Code blocks gained `content_raw`, `header`, and `placeholders`.**
  `content_hash` covers `content_raw` (the verbatim payload), preserving §7
  falsifiability: a human can grep the wiki source. `content` is the same payload
  with wikitext emphasis stripped and `{{ic}}`/`{{=}}` resolved.
- **`links()` excludes namespace and interwiki links** and splits `Target#Anchor`
  into `target_page` + `anchor`.

---

## 1. Mission

This MCP server exists to provide AI systems with **live, authoritative, non-hallucinated access to the Arch Linux Wiki**.

No more. No less.

It is infrastructure for correctness. Not assistance. Not troubleshooting. Not helpfulness.

If an AI agent needs verified Arch Linux documentation, this server retrieves it. If the information doesn't exist in the wiki, the server fails closed. It does not synthesize. It does not guess. It does not help.

---

## 2. The Problem

### Why This Exists

**LLMs hallucinate.**  
They fabricate `pacman` flags, invent configuration paths, and confidently suggest commands that brick systems.

**Web search is polluted.**  
Random blog posts, outdated Stack Overflow answers, and ChatGPT-generated "tutorials" dominate results. None cite sources. Most are wrong.

**Generic Linux tooling doesn't understand Arch.**  
Ubuntu scripts break on Arch. RHEL advice is irrelevant. Systemd behaviors differ. The AUR exists.

**Arch users need ground truth.**  
The Arch Wiki is that ground truth. It is maintained, versioned, and authoritative. But it's HTML designed for humans.

This MCP server makes it machine-readable without compromising fidelity.

---

## 3. Scope

### What This MCP Server Does

- **Retrieves wiki pages** by exact title or URL
- **Extracts page sections** by heading
- **Returns command examples** as quoted, traceable text
- **Surfaces warnings and notes** explicitly marked in wiki content
- **Searches for pages** by keyword or topic
- **Reports package information** as documented in wiki articles

All outputs are **traceable to specific wiki pages and sections**. All data is **extracted, not synthesized**.

### What This MCP Server Does Not Do

This is **not**:

- A Linux assistant
- A package manager wrapper
- A troubleshooting chatbot
- A command generator
- A configuration validator
- A system administration tool
- An AI that "understands" Linux

It does not:

- Interpret commands
- Suggest alternatives
- Recommend packages
- Diagnose problems
- Generate scripts
- Paraphrase wiki content
- Aggregate external sources

**If it's not in the wiki, it's out of scope.**

---

## 4. Data Contract

### Single Source of Truth

The **Arch Linux Wiki** is the only authoritative source.

- URL: `https://wiki.archlinux.org/`
- License: GNU Free Documentation License 1.3 or later
- Maintenance: Arch Linux community

### No Synthetic Knowledge

This server does not:

- Paraphrase wiki content into "simpler" language
- Combine information from multiple pages unless explicitly requested by the API caller with page-level granularity
- Infer meaning from context
- Fill gaps with "reasonable" assumptions
- Use training data as a fallback

### Extraction, Not Interpretation

All returned content must be:

- **Quoted directly** from wiki source, or
- **Extracted as structured metadata** (headings, links, code blocks), or
- **Returned as failure** if unavailable

There is no "close enough." There is no "probably this." There is success or failure.

---

## 5. API Philosophy

### Structured Artifacts, Not Natural Language

This MCP exposes the wiki as **machine-readable primitives**:

- **Pages**: Title, URL, last modified timestamp, full content
- **Sections**: Heading hierarchy, section content, anchor links
- **Commands**: Code blocks tagged with language, context, and source section
- **Warnings**: Explicit note/warning/tip blocks with severity
- **Packages**: Names, categories, and wiki references
- **Links**: Internal wiki links extracted with source and target page
- **Search Results**: Ranked page titles with match context

Responses are JSON-structured, version-tagged, and citation-linked.

### Traceability Over Brevity

Every response includes:

- Source wiki URL
- Section anchor (if applicable)
- MediaWiki revision ID or last-modified timestamp when revision ID is unavailable
- Extraction method (direct quote, code block, heading structure)
- **Content hash** (SHA-256) of extracted text block

If an agent cannot cite its source, it should not have used this server.

### Provenance Persistence

Extracted blocks must include a **cryptographic hash** of the quoted wiki fragment.

The Arch Wiki is continuously edited. A timestamp alone cannot prove what version was served if a page has been modified multiple times in the same day.

Content hashing ensures:

- **Bug Reports**: Users can prove exactly what text justified a command
- **Reproducibility**: Researchers can verify historical responses
- **Auditability**: System owners can trace bad advice to exact wiki versions
- **Blame**: Maintainers can determine if wiki or MCP introduced error

Implementation requirements:

- Use **SHA-256** for content fingerprinting
- Hash the **exact extracted text** before any formatting
- Text must be normalized to **Unicode NFC** and whitespace preserved before hashing
- Include hash in all JSON responses as `content_hash` field
- Log hashes with timestamps for forensic retrieval

This turns citation from "well-sourced" into **forensically sound**.

### Fail Closed

When in doubt, return an error. Do not approximate. Do not fallback. Do not "try to help."

Examples of correct failure modes:

- `Page not found: "acrhlinux"` (typo, do not suggest "archlinux")
- `Section "GPU passthrough" not found in page "Xorg"` (do not return "closest match")
- `No command blocks in section "See Also"` (do not synthesize examples)

---

## 6. Non-Goals

### Explicitly Out of Bounds

This project will **never** become:

❌ **A Linux Assistant**  
No conversational AI. No "what do you want to do?" No task inference.

❌ **A Package Manager**  
No `pacman` wrappers. No AUR helpers. No installation automation.

❌ **A Troubleshooting Bot**  
No log analysis. No error diagnosis. No "try this" suggestions.

❌ **A Blog Aggregator**  
No Reddit scraping. No forum crawling. No "community wisdom."

❌ **A Command Generator**  
No "AI-suggested scripts." No "smart defaults." No execution.

❌ **A Configuration Manager**  
No dotfile generation. No systemd unit creation. No validation.

### Why These Are Non-Goals

Each of these requires **interpretation, inference, or synthesis**. This violates the core contract: **wiki extraction only**.

If a feature cannot be implemented by retrieving and structuring wiki content, it does not belong in this project.

---

## 7. Quality Bar

### Definition of "Correct"

A response is correct if and only if:

1. **Traceable**: Response includes wiki URL and section
2. **Verbatim or Structured**: Content is quoted directly or extracted as metadata
3. **Version-Aware**: Timestamp or revision ID included
4. **Content-Hashed**: SHA-256 fingerprint of extracted text included
5. **Falsifiable**: A human can verify the response against the wiki

A response is **incorrect** if:

- Content is paraphrased without citation
- Commands are modified or "improved"
- Information is inferred from context
- Fallback data is used when wiki content is unavailable

### Testing Standards

All functionality must include:

- **Unit tests** for parsers and extractors
- **Integration tests** against live wiki pages
- **Regression tests** for critical pages (installation guide, pacman, systemd)
- **Failure tests** confirming correct error handling

Tests must fail if:

- Content deviates from wiki source
- Citations are missing or incorrect
- Extraction logic hallucinates structure

---

## 8. Contributor Rules

### Core Principle

**Anyone who adds logic that synthesizes, guesses, or fabricates Linux instructions violates this project's constitution.**

### Prohibited Changes

Contributors may **not**:

- Add LLM calls for "summarization" or "clarification"
- Implement "smart" fallbacks when wiki content is missing
- Paraphrase wiki text for "readability"
- Infer commands from partial matches
- Scrape external sources (Reddit, forums, blogs)
- Generate synthetic examples
- Implement "helpful" error messages that suggest fixes

### Required Changes

Contributors **must**:

- Cite wiki pages in all responses
- Preserve exact wiki content in quotes
- Fail explicitly when content is unavailable
- Document extraction methods
- Include version/timestamp metadata
- Write tests that verify against live wiki

### Code Review Standards

Pull requests must:

- Include before/after wiki citations
- Demonstrate no content synthesis
- Pass all extraction tests
- Document failure modes

Reviewers must reject PRs that:

- Introduce inference logic
- Remove citation tracking
- Add "smart" approximations
- Implement workarounds for missing content

---

## 9. Agent Contract

### Rules for AI Agents Using This MCP

AI systems using this server **must**:

1. **Cite Pages**: Include wiki URLs in user-facing responses
2. **Respect Warnings**: Surface all `[!WARNING]` and `[!CAUTION]` blocks from wiki
3. **Fail Transparently**: Tell users when information is unavailable
4. **Prefer Failure Over Invention**: Do not supplement with training data
5. **Preserve Context**: Do not strip section headings or source metadata
6. **Verify Commands**: Encourage users to check wiki before executing

AI systems using this server **must not**:

- Claim wiki content as their own knowledge
- Modify commands without explicit citation of changes
- Fill gaps with "general Linux knowledge"
- Suggest alternatives not documented in wiki
- Execute retrieved commands without user confirmation

### Example: Correct Usage

**User**: "How do I install GRUB?"

**Agent**: According to the [GRUB wiki page](https://wiki.archlinux.org/title/GRUB#Installation):

```bash
# pacman -S grub
```

> [!WARNING]  
> The wiki states: "It is important to install the GRUB package for the correct architecture."

**Agent**: "Would you like me to retrieve the full installation section?"

### Example: Incorrect Usage

**User**: "How do I install GRUB?"

**Agent**: "You can install GRUB with `pacman -S grub`. Then run `grub-install` to set it up."

❌ **Violation**: Added `grub-install` command without wiki citation  
❌ **Violation**: Did not link to source page  
❌ **Violation**: Did not surface warnings from wiki

---

## 10. Governance

### Decision Authority

Technical decisions are resolved by:

1. **Does it violate the data contract?** → Reject
2. **Does it require synthesis?** → Reject
3. **Can it be implemented via wiki extraction?** → Evaluate
4. **Does it improve traceability?** → Approve

### Amendment Process

This constitution can be amended only by:

1. Demonstrating that the amendment **strengthens** the data contract
2. Proving that the amendment **reduces** hallucination risk
3. Showing that the amendment **improves** citation fidelity

Amendments that weaken correctness guarantees are **unconstitutional**.

---

## 11. License and Attribution

### Project License

This MCP server is licensed under **MIT** for code, **CC BY-SA 4.0** for documentation.

### Wiki License

All Arch Wiki content is licensed under the **GNU Free Documentation License 1.3 or later**.

Retrieved content must:

- Preserve original licensing
- Attribute to "Arch Linux Wiki contributors"
- Link to source pages

---

## 12. Enforcement

### Violations

Code that violates this constitution must be:

- Reverted immediately
- Documented in a post-mortem
- Used to strengthen tests

### Examples of Violations

- Adding a "suggest alternative packages" feature
- Implementing LLM-based summarization
- Scraping Stack Overflow for additional context
- Generating commands not found in wiki
- Removing citation metadata for "cleaner" output

### Consequences

Repeated violations result in:

- Contributor access revocation
- Reversion to last constitutional state
- Public documentation of breach

### API Governance

Breaking changes to API semantics require:

- Constitution version bump
- Migration notes documenting changes
- Backward compatibility period when feasible

Quietly changing response structure, field names, or extraction behavior violates this constitution even if implementation details remain "correct."

Governance applies to interfaces, not just code.

---

## Final Statement

This is not a product. This is infrastructure.

It exists so that AI agents can retrieve Arch Linux documentation without lying.

Everything else is out of scope.

If you want helpfulness, synthesis, or interpretation, you are in the wrong repository.

This is a citability layer for the Arch Wiki. Nothing more.

**End of Constitution.**
