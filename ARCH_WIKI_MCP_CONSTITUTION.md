# Arch Wiki MCP: Technical Constitution

**Version:** 1.14  
**Status:** Canonical  
**Last Updated:** 2026-07-10

---

> Amendments and their migration notes are collected in the appendix at the end.

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

Extracted blocks must include a **cryptographic hash** of the quoted wiki fragment,
paired with a **revision-addressed URL** that resolves to the exact revision the
hash was computed over.

The pairing is the point. A hash proves that a fragment matches some text; the
revision URL says *which* text, immutably. A hash beside a canonical page URL —
which follows the page — proves nothing once the page is edited, and the Arch
Wiki is continuously edited.

Be precise about what this buys. The hash is an **unkeyed SHA-256 fingerprint**:
it provides *integrity against a named revision*, not authenticity. It does not
prove an excerpt originated from this server, and it cannot detect a response
forged before it reached the reader, since anyone can hash text they invented. It
is not a signature, and this document does not claim it is one. Overstating the
guarantee would undermine the very thing the guarantee exists to protect.

Be precise about what is pinned, too. The hash covers the revision's **wikitext**,
which is immutable; the *rendered* view of an old revision is not, because it still
transcludes templates at their current versions. `revision_wikitext_url` therefore
returns the wikitext (via the API, so a script can fetch it), and that — not the rendered page — is what an auditor fetches
to recheck a hash. "Pinned", not "frozen", is the honest word for the rest.

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

---

## Appendix — Amendment Migration Notes

The articles above are the constitution as it stands. What follows is the record of
how it got here: one migration note per amendment, newest first. They are history,
not rules -- the rule each one established already lives in the articles.

### Amendment 1.14 — Migration Notes

Per §12 (API Governance): `search()` gains `match`, and `snippet` changes from
MediaWiki's highlight HTML to plain text. `title`, `pageid` and `url` are
unchanged. No hash moves anywhere — `search()` has never carried one.

**Behavioural change:** `search()` now returns results for queries that
previously returned `[]`. Any caller that treated an empty result as "the wiki
has nothing" was being lied to; it will now receive pages.

### Changed in 1.14

- **`search()` no longer manufactures silence.** `srwhat` has no default on this
  wiki, and the API then searches **titles only**. `search("wifi not working")`
  returned `[]` while the wiki held 47 matching pages; `search("iwd wifi")`
  returned `[]` against 33; `search("pacman keyring")` against 111. `[]` is this
  MCP's way of saying the wiki specifies nothing — §5, Fail Closed — so the
  discovery entry point was fabricating the wiki's silence, the same harm the
  rest of this document exists to prevent, one layer earlier than anywhere it had
  been looked for.

  Full-text search alone is not the remedy: it buries exact titles, so
  `search("GRUB")` stops finding `GRUB`. The wiki's own search box asks both
  questions, and so do we — `srwhat=nearmatch` for the exact page, then
  `srwhat=text`. **We do not re-rank.** Each list keeps the order the wiki
  returned it in; the exact match simply precedes the rest, and says so via
  `match`.

- **A search result is a pointer, not evidence.** It is the only tool output with
  no `revid` and no hash, and `snippet` — a truncated fragment of a revision
  nobody named, re-indexed at the wiki's discretion — must never be quoted.
  `SearchResult` is now a dataclass, so §12's contract tests force both AGENTS.md
  and the injected prompt to say what `snippet`, `pageid` and `match` mean.

- **`snippet` is plain text.** It shipped as MediaWiki's highlight HTML wrapped
  around raw wikitext: `[[de:<span class="searchmatch">GRUB</span>]]`. Balanced
  markup is now resolved. A token the wiki truncated (`a:C++|C++]]`) keeps its
  brackets, because inventing the missing half would be interpretation.

- **A test and a report both certified the bug.** `test_search_tool_zero_results`
  asserted `search("wifi not working") == []`, and TEST_STRATEGY.md recorded
  `Expected: Results or empty` → **PASS**. An expectation that accepts either
  answer cannot fail. Both are corrected, and the zero-result case now uses a
  query the wiki genuinely cannot answer.

---

### Amendment 1.13 — Migration Notes

Per §12 (API Governance): no field changes. `message_hash_cleaned` moves for the
three warnings whose body opened at an orphaned list depth — the `{{Tip|#** …}}`
on the English, Spanish and French Installation guides. `content_hash` and
`message_raw` are unchanged everywhere.

### Changed in 1.13

- **`warnings().message` never opens indented.** The Installation guide writes
  `{{Tip|#** The ISO uses …}}`. That marker's depth is relative to a list living
  *outside* the template, so the extracted tip had no parent and
  `_render_list_markers` faithfully emitted four leading spaces. Markdown reads
  four leading spaces as a **code block** — so a tip rendered as a shell
  transcript, in the one field §6 requires an agent to quote to a user. Prose
  presented as a command is the confusion that got `examples()` deleted; it had
  simply moved to another field.

  Only a *common* indent is removed, so a message with real internal nesting keeps
  every sibling's relative depth. The 1.10 invariant — a nested first item never
  sits shallower than its siblings — is unchanged and still tested; it was pinned
  to the incidental value `"    - a"` rather than to the sibling relationship, and
  now asserts the relationship.

- **A preformatted line takes no part in the dedent.** Its leading space came from
  the wiki, not from us. Counting it measured a common indent of one for
  `"#** see:\n # pacman -Fy"`, and shifting the block by it put a bare `#` at
  column 0 — reintroducing the root-prompt lookalike this rule exists to prevent,
  and wrecking the bullet besides. Such lines neither set the common indent nor
  receive the shift.

  Latent, never live: the four preformatted lines in the recorded corpus (Pacman,
  GRUB, Users and groups) sit beside no list item, so the common indent was zero.
  One wiki edit away. Raised by Codex in review.

- **`make audit` gained `warning_message_opens_indented` and
  `warning_message_root_prompt_lookalike`.** Three of 177 warning messages in the
  recorded corpus violated the first, including on the English Installation guide.
  It was in the fixtures the whole time: the suite checked that no message
  *skipped* a nesting level, never that it *started* at one. The second states for
  `warnings()` what has been checked for `section()` since 1.7 — a bare `#` at
  column 0 is a root prompt to a reader and a heading to markdown. The same
  invariant, on the other code path that renders the same thing.

---

### Amendment 1.12 — Migration Notes

Per §12 (API Governance): no field changes. `content_hash_cleaned` and
`message_hash_cleaned` move for any block whose source uses `<nowiki>` or an HTML
comment — two blocks across the seven recorded pages. **No verbatim hash moves:**
`content_hash`, `content_raw` and `message_raw` are unchanged everywhere, because
the raw payload was always correct. Only the rendered text was wrong.

### Changed in 1.12

- **`<nowiki>` now protects what it wraps, from the scanners and the cleaners
  both.** MediaWiki treats it as a strip marker: nothing inside is expanded, and
  an HTML comment inside it is displayed. We deleted the comments, dropped the
  tags, and then expanded the very templates the tags were protecting.
  `Help:Style` rendered `{{ic|<nowiki>{{ic|text}}</nowiki>}}` as `text` where the
  wiki shows the literal `{{ic|text}}`.

- **A template the wiki merely quotes is not evidence.** Protecting the payload
  during cleaning was too late: extraction runs first. Every scanner —
  `parse_code_blocks`, `parse_templates`, `parse_internal_links`,
  `admonition_types`, and the section renderer's classification pass — now runs
  over a length-preserving mask and slices from the source. Before this,
  `<nowiki>{{bc|echo hi}}</nowiki>` made `commands()` return `echo hi`, and
  `<nowiki>{{Warning|rm -rf /}}</nowiki>` made `warnings()` return a `WARNING` the
  article never issued: a page's documentation of template syntax became a command
  and a safety claim, each carrying a valid hash. A `[[link]]` inside `<nowiki>`
  likewise navigates nowhere and is no longer offered as navigation, and an
  indented line inside one is not a code block, because `<nowiki>` disables
  wikitext interpretation entirely.

  Two layers are therefore load-bearing, and neither is redundant. `mask_nowiki()`
  blinds the scanners. `_hide_nowiki()` protects a payload already handed to a
  cleaner — a code template's body, or the interior of an inline `{{ic|...}}`,
  which is never masked because it resolves in place.

- **An HTML comment inside `<nowiki>` is content, not markup.** `commands("Iwd")`
  returned the dbus config `/etc/dbus-1/system.d/iwd-allow-read.conf` with its two
  comment lines deleted — while `content_hash` went on faithfully attesting
  `content_raw`, which still contained them. The hash was honest and the text the
  user pastes was not: synthesis by omission in the one field this MCP promises is
  runnable. Comments *outside* `<nowiki>` are still removed, as MediaWiki's own
  preprocessor removes them.

  The evidence sat in the committed fixtures the whole time. The guard that should
  have caught it, `test_marking_only_affects_blocks_that_have_placeholders`,
  compared `commands().content` against a reference that deleted the comments too.
  Both sides were wrong in the same direction, so the assertion held.

- **A bodiless `{{bc}}` is no longer a command.** It produced `content: ""` with
  `content_hash` set to the SHA-256 of the empty string — evidence for nothing,
  carrying a hash that verifies against nothing, which §6 obliges an agent to
  present. The wiki specifies no command there, and `[]` is how this MCP says so.
  No page in the audited corpus contains one; the defect was latent.

- **`make audit` gained `nowiki_payload_altered`.** Every `<nowiki>` payload in the
  source must appear verbatim in the rendered output. The audit could not have
  found the rendering defects: it had no notion that some text is literal by
  decree.

  It deliberately does **not** check "nothing quoted becomes evidence." That is a
  claim about the position a block was extracted from, and neither `commands()`
  nor `warnings()` reports position. Both textual proxies are unsound *and* unable
  to fail — `Help:Style` carries a real `{{bc|#!/bin/sh …}}` and quotes that same
  script elsewhere, and a pre-masked comparison goes vacuous exactly when
  `mask_nowiki()` is what regressed. That invariant lives in the unit tests, where
  a synthetic page fixes the positions and each of the six scanners is observed
  going red with its mask removed. A check that cannot fail is not a check.

---

### Amendment 1.11 — Migration Notes

Per §12 (API Governance): `warnings()` gains three additive fields — `alias`,
`alias_target`, `alias_revid`. All are `null` for every warning on an English
page, and for the suffixed localized forms (`{{Note (Español)}}`). No existing
field changes, and no hash moves.

### Changed in 1.11

- **A warning type derived from a template redirect now carries that redirect.**
  The French Installation guide writes `{{Attention}}`, which is a redirect to
  `Template:Warning (Français)`. The type `WARNING` appears nowhere in the
  article's wikitext, the article's `revid` does not cover the redirect page, and
  `content_hash` attests only `message_raw`. Retargeting `Template:Attention`
  flipped a block's `type` with **no change to `revid`, `content_hash`, or
  `message_raw`** — a safety-critical field derived from an unattested source, in
  a project whose product is falsifiable citation.

  `alias_revid` is the revision of the **redirect page itself**. Not the
  article's, and — the trap — not the redirect target's. MediaWiki resolves
  titles before `prop=revisions` runs, so a `redirects=1` query reports the
  destination's revid, which a retarget never touches. Reading the right number
  requires a second query with redirects off.

- **The second query fires only when a name actually redirects to an
  admonition.** English pages resolve `{{ic}}` and `{{Pkg}}` to "not an
  admonition" and pay nothing. Of the nine recorded alias pages, exactly one —
  the French Installation guide — makes the extra request.

- **An unattestable redirect raises.** If the redirect resolves but its revision
  cannot be read, we know the page carries a `WARNING` and cannot say why.
  Returning it unattested would be the claim this amendment forbids; dropping it
  would be a suppressed warning. It fails closed, as an unanswered alias query
  already did.

- **`warnings()` serializes with `asdict`.** It hand-listed its keys, which is
  how `tool_section()` came to attest a hash over text it never returned (1.8).
  A new field now reaches the agent by default rather than by someone
  remembering a second place to add it.

---

### Amendment 1.10 — Migration Notes

Per §12 (API Governance): no field changes. `message_hash_cleaned` moves for any
warning whose body contains a nested list. `content_hash` and `message_raw` are
unchanged.

### Changed in 1.10

- **`warnings().message` keeps a nested first item's indent.** 1.9 fixed this in
  `section()`. `_clean_message` is a separate code path and ended in `.strip()`,
  eating the indent `_render_list_markers` had just generated for the first line.
  The French Installation guide's `{{Astuce}}` rendered its first bullet flush
  left and its second four spaces in, so the two siblings appeared at different
  depths in prose §6 *requires* the agent to quote.

  Found by driving the live server after 1.9 shipped. The offline suite was green,
  and `make audit` was green: the audit checked `section()` for this invariant and
  never checked `warnings()`. Both now do.

- **A leading space in a template body is still insignificant** in
  `warnings().message`, as it is in `section()`: `{{Note| body}}` has that space
  mid-line in the source, where it means nothing.

---

### Amendment 1.9 — Migration Notes

Per §12 (API Governance): no field changes. `content_hash_cleaned` moves for any
section containing an unrendered template or a nested list. `content_hash` and
every verbatim field are unchanged.

### Changed in 1.9

- **"Verbatim" now means verbatim.** 1.6 promised that a template the renderer
  does not know is emitted as the wiki wrote it. Its braces survived; its
  *contents* did not. `{{Accuracy|Use {{ic|sleep 5}} and ''foo''.}}` came out as
  `{{Accuracy|Use sleep 5 and foo.}}` — text that looks raw, is not, and which
  `content_hash_cleaned` attested all the same. An agent instructed to "report it
  as-is" would have relayed an altered caveat.

  Unknown templates are now masked before prose rendering and restored
  byte-for-byte, insides included. The nested `{{ic}}` and `{{Pkg}}` inside an
  `{{App|...}}` are the wiki's bytes, not markup we declined to resolve.

- **A nested list keeps the indent of its first item.** `render_section_wikitext`
  ended in `.strip()`, which ate the leading spaces of the fragment's first line.
  A `{{Tip}}` whose body opens with `#**` rendered item one flush left and item
  two indented, promoting the first above its own siblings.

- **`make audit`.** Three of the defects fixed in 1.6–1.8, and both fixed here,
  were invisible to a green fixture suite and evident on first contact with live
  content. `scripts/live_audit.py` checks the contract's invariants against 36
  live pages and 1834 sections. It is not part of pytest, which blocks sockets on
  purpose. A suite that pins seven pages cannot tell you what the wiki does.

---

### Amendment 1.8 — Migration Notes

Per §12 (API Governance): `warnings()` gains a failure mode. It now raises when
it cannot resolve a page's template names, where it previously returned a subset.
No field changes; no hash of an English page moves.

### Changed in 1.8

- **`warnings()` recognises localized admonitions.** A translated page does not
  write `{{Warning}}`. The Spanish Installation guide writes `{{Note (Español)}}`;
  the French one writes `{{Attention}}`, a redirect to `Template:Warning (Français)`.
  Matching the four English names returned **0 of 11** admonitions on the Spanish
  page and **7 of 13** on the French one.

  §6 orders the agent to surface warnings before any related command, and §5 says
  an empty result is a positive claim that the wiki specifies nothing. A dropped
  `{{Attention}}` was therefore a suppressed *warning*, presented as silence, under
  a tool the agent is told to trust. This is the constitution's central harm, and
  it was reached by translating the page.

  The mapping is **derived, not declared**. A trailing `(Lang)` suffix is stripped locally;
  a redirect alias is resolved by asking MediaWiki, exactly as interwiki prefixes
  are derived from siteinfo (Amendment 1.4) rather than hard-coded. Declaring the
  names would have rotted the moment the wiki added a language.

- **Resolution failure raises.** If the alias query cannot be answered, `warnings()`
  raises rather than returning the English-only matches. We do not know whether the
  page carries a warning, and `[]` would assert that it does not. §5: fail closed.

  *Migration:* `warnings()` may now raise `ValueError` on a page whose templates it
  cannot resolve. Handle it as you already handle a missing anchor. It costs one
  additional API request per page, cached across pages for the process lifetime.

- **`section()` renders the suffixed form** (`{{Note (Español)}}`) but leaves a
  redirect alias (`{{Astuce}}`) as visible markup, because rendering must not
  require a network call. Visible markup is the honest failure; §8 forbids the
  alternative of dropping it.

---

### Amendment 1.7 — Migration Notes

Found by driving the server as an agent against the *live* wiki, not by testing it
from outside. No field is added or removed. `content_hash` and the verbatim fields
are unchanged; `content_hash_cleaned` and `message_hash_cleaned` move for text
containing a nested list.

### Changed in 1.7

- **Nested list markers render with their depth.** `_render_list_markers` read only
  the last character of the marker run and left the rest in the body, so `##` became
  `1. # body` — putting a bare `#` back into agent-facing prose, the precise hazard
  the function exists to remove. 40 lines across the corpus were affected, and
  `warnings().message` shared the defect.

  `*` and `#` now nest (`**` → `"  - "`, `##` → `"  1. "`, `#**` → `"    - "`), while `:`
  and `;` indent only. A marker holding nothing but a template's closing brace
  (`#}}`) no longer emits an empty `1.`.

  The 1.6 test asserted only that no rendered line *begins* with `#`. `1. # body`
  begins with `1`, so it passed. The invariant is now "no list marker survives past
  the bullet it rendered", which is what 1.6 meant to say.

- **A `#` from a resolved anchor link is not a leak.** `[[#Icon themes]]` renders as
  `#Icon themes`, which is also how MediaWiki labels it. Faithfulness outranks
  tidiness.

---

### Amendment 1.6 — Migration Notes

Per §12 (API Governance): `section()` gains `content_raw` and
`content_hash_cleaned`, and its `content` changes from raw wikitext to rendered
text. `content_hash` still attests the verbatim slice and does **not** move.

### Changed in 1.6

- **`section().content` is rendered.** §6 (Exclusive Command Source) directs the
  agent to `section()` whenever `commands()` honestly returns `[]`: quote the
  wiki's prose rather than infer a command. That prose was raw wikitext, in which
  a numbered list item is written `# Point the current boot device ...` — the
  same character a root shell prompt uses. Five sections in the corpus reachable
  by that route begin lines this way.

  This is the defect that got `examples()` removed in 1.3 for emitting prose as
  bash. Deleting the tool did not delete the ambiguity; it relocated it into the
  one path this constitution *requires* an agent to take.

  Wiki headings now render as markdown headings, `{{bc}}`/`{{hc}}` as fenced
  blocks, and `{{Note}}`/`{{Warning}}`/`{{Tip}}` as labelled prose. Outside a
  fence a leading `#` is a heading; the wiki's ordered lists render as `1.`.

  *Migration:* show `content`, cite `content_raw` and `content_hash`. Code an
  agent intends to run must still come from `commands()`, which alone carries
  per-block hashes and `placeholders`.

- **Unknown templates survive verbatim.** The renderer resolves a whitelist. A
  template it does not know (`{{Accuracy|...}}`, `{{App|...}}`) is left as raw
  markup rather than dropped. §8 forbids synthesis; silently deleting the wiki's
  own caveat is synthesis by omission, and markup an agent can see is the honest
  failure. The residual set is pinned by test, so a newly used template becomes a
  red test rather than lost content.

- **`warnings()` and `links()` read `content_raw`.** Both parse wikitext and were
  built on `section().content`. Left unchanged they would have returned `[]` for
  every anchored call — which §6 tells the agent means "the wiki specifies
  nothing here." A rendering change became a fail-closed lie one call away.

---

### Amendment 1.5 — Migration Notes

Per §12 (API Governance): `content` changes for every code block containing a
placeholder, and `content_hash_cleaned` moves with it. `content_raw` and
`content_hash` are unchanged.

### Changed in 1.5

- **Placeholders stay marked in `content`.** Where the wiki italicises a token
  inside a command, it names a value the reader must substitute. Cleaning used to
  strip the italics and emit a bare `esp`, producing a string that *looks* runnable
  and is not — a hash-attested command that acts on the wrong path. `content` now
  renders it `<esp>`, which fails at the shell.

  This is the constitution's own principle applied to its own output: §5 says fail
  closed, and §7 asks that a claim be falsifiable. A structure that resists the
  mistake outranks a prompt that forbids it. AGENTS.md §7 becomes the backstop, not
  the primary defence.

  Many code blocks across the corpus carry placeholders; blocks without them are
  byte-identical to 1.4.

  *Migration:* substitute `<token>` for each entry in `placeholders` before running
  a command, or read `content_raw` and substitute deliberately. Agents must not
  strip the markers: doing so converts a loud failure into a silent one.

  Italics in **prose** (`warnings().message`) remain ordinary emphasis and are still
  removed. The same markup means different things in code and in prose.

- **`content` is no longer documented as "safe to run".** It is runnable once its
  placeholders are substituted. The previous wording was false for 35% of blocks.

---

### Amendment 1.4 — Migration Notes

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

- **The agent contract was rewritten to match.** §12 governs interfaces, and the
  injected `arch-wiki-usage` prompt is one. AGENTS.md §4 said "Content returned by
  this MCP is verbatim evidence", which stopped being true when `content` and
  `message` became rendered fields. §4 now carries a table mapping each tool to its
  rendered field, its verbatim field, and the hash attesting each; new §7 forbids
  presenting a `placeholders` token as a literal. The injected prompt says the same.
  `tests/test_contract.py` fails when either document drifts from the schema.

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

### Amendment 1.3 — Migration Notes

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
