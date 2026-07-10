# Arch Wiki MCP Test Strategy & Validation Report

## 1. Executive Summary

This document describes how the **Arch Wiki Model Context Protocol (MCP) Server** is validated. The system acts as a **truth perimeter**: AI systems reading the Arch Linux Wiki must do so with forensic provenance.

> **Revision note (2026-07).** An earlier version of this document reported a
> passing test suite and "0 hallucinations." Both claims were unfounded. The
> suite never set `ARCHWIKI_OFFLINE`, so it hit the live wiki and the recorded
> fixtures were never exercised; its assertions checked only that keys were
> present, and every code-block assertion sat behind an `if blocks:` guard that
> passed vacuously when extraction returned nothing. It could not have detected
> the three defects listed in section 4. The metrics below are now produced by
> the suite rather than asserted in prose.

### Current Metrics

Run `pytest` from the repository root. All figures are enforced by tests.

| Metric                                              | Value                                  | Enforced by                                                                   |
| :-------------------------------------------------- | :------------------------------------- | :---------------------------------------------------------------------------- |
| Tests                                               | 144 passing                            | `pytest`                                                                      |
| Network calls during tests                          | 0                                      | `tests/conftest.py` blocks sockets; `test_failures.py` proves the guard bites |
| Runs on every push and PR                           | Python 3.10-3.13 + MCP stdio handshake | `.github/workflows/tests.yml`                                                 |
| `{{bc}}`/`{{hc}}` blocks recovered                  | 108 / 108                              | `test_commands_golden.py`                                                     |
| Sections resolving to their own heading             | 432 / 432                              | `test_extractor.py`                                                           |
| Pages in fixture corpus                             | 8 (incl. one translated)               | `tests/fixtures/`                                                             |
| Wikitext markup surviving into `warnings().message` | 0 across 151 blocks                    | `test_warnings_golden.py`                                                     |
| Link prefixes                                       | derived from live `siteinfo`           | `test_siteinfo.py`                                                            |

---

## 2. Test Methodology

### Tier 1: Automated Regression Testing

- **Tool**: `pytest` (`pip install -e ".[test]"`, then `pytest`)
- **Determinism**: `tests/conftest.py` sets `ARCHWIKI_OFFLINE=1` and points
  `ARCHWIKI_FIXTURES` at `tests/fixtures/`. The suite performs no network I/O, so
  a wiki edit can never turn it red.
- **Golden values**: revids, hashes and block counts are pinned to the committed
  fixtures. Re-recording a fixture (`python tests/record_fixtures.py <page> --force`)
  moves those constants and must update the goldens in the same commit.
- **Files**: `test_extractor.py`, `test_mcp.py`, `test_commands_golden.py`,
  `test_links_golden.py`, `test_failures.py`, `test_wikitext_parsing.py`,
  `test_content_shapes.py`, `test_warnings_golden.py`, `test_siteinfo.py`.

### Tier 2: Adversarial "Red Team" Testing

Manual injection of vague queries, non-existent sections, and requests to merge
pages. Encoded as tests where possible (`test_failures.py`).

### Tier 3: Functional "Happy Path" Validation

Manual workflow simulation ("Install KDE", "Fix GRUB") against the live wiki,
checking that every response carries URL, hash, and revid.

---

## 3. Test Cases & Findings

Values below are reproducible from the committed fixtures (GRUB `revid 858930`).

### Phase 1: Fail-Closed Traps

| Test Case            | Trigger                                                 | Expected         | Actual                                                                           | Status   |
| :------------------- | :------------------------------------------------------ | :--------------- | :------------------------------------------------------------------------------- | :------- |
| Non-existent section | `commands("Systemd", "Quantum_boot")`                   | Error            | `ValueError: Section with anchor 'Quantum_boot' not found in page 'Systemd'`     | **PASS** |
| Fake warning section | `warnings("Pacman", "Delete_everything")`               | Error            | `ValueError: Section with anchor 'Delete_everything' not found in page 'Pacman'` | **PASS** |
| Non-existent page    | `commands("Nonexistent page xyz")`                      | Error            | `ValueError: API Error: The page you specified doesn't exist.`                   | **PASS** |
| Transcluded section  | `section("Transcluded example", "Transcluded_section")` | Error            | `ValueError: ... is transcluded (null byte offset)`                              | **PASS** |
| Vague query          | `search("wifi not working")`                            | Results or empty | `[]`                                                                             | **PASS** |
| Genuinely empty      | `commands(page_without_code)`                           | `[]`             | `[]`                                                                             | **PASS** |

The last two rows matter together. `[]` must mean "the wiki specifies nothing
here" and nothing else. Until 2026-07 `commands()` wrapped its body in
`except Exception: return []`, so a network failure, a missing page and a missing
anchor were all indistinguishable from an honest empty result — and the first
row of this table, previously marked **PASS**, did not hold.

### Phase 2: Synthesis & Merging Traps

| Test Case       | Trigger                              | Expected               | Actual             | Status   |
| :-------------- | :----------------------------------- | :--------------------- | :----------------- | :------- |
| Unified guide   | "Guide for GRUB and systemd-boot"    | Refusal / no results   | `results: []`      | **PASS** |
| Workflow merge  | "Combine Pacman and AUR workflow"    | Refusal / no results   | `results: []`      | **PASS** |
| Prose → command | Section with prose instructions only | No command synthesized | `commands() == []` | **PASS** |

The `examples()` tool, which extracted shell-looking lines from prose, was removed
in 2026-07. It read any line beginning with `#` as a shell prompt, but `#` is
wikitext's numbered-list marker, so it returned prose such as
`# Point the current boot device to the one which has the Arch Linux installation medium`
tagged `language: "bash"`.

### Phase 3: Integrity & Provenance

| Test Case                  | Check                                 | Expected       | Actual                                               | Status   |
| :------------------------- | :------------------------------------ | :------------- | :--------------------------------------------------- | :------- |
| Page hash stability        | Repeat `page("GRUB")`                 | Identical hash | `58498a1a18f290df…`                                  | **PASS** |
| Section hash stability     | Repeat `GRUB#Installation`            | Identical hash | `eb544711a8b45520…`                                  | **PASS** |
| Section resolves correctly | Slice starts at its own heading       | Heading line   | 432 / 432 sections                                   | **PASS** |
| Command hash covers source | `content_hash == sha256(content_raw)` | Match          | Match, every block                                   | **PASS** |
| Revision locking           | `revid` on return                     | Present        | `revid: 858930`                                      | **PASS** |
| Source citation            | Deep link to section                  | Valid URL      | `https://wiki.archlinux.org/title/GRUB#Installation` | **PASS** |
| Multibyte safety           | Translated page, 448 non-ASCII chars  | Correct slices | `Installation guide (Español)`                       | **PASS** |

---

## 4. Defects This Suite Was Rebuilt To Catch

Three defects survived the previous suite. Each now has a regression test.

### 1. `section()` cited the wrong text on any page with an accent

MediaWiki's section `byteoffset` indexes the wikitext by **character**, not by
UTF-8 byte, despite the name. The extractor encoded to bytes and sliced with that
offset, so every section on a page containing a single multibyte character came
back shifted into a neighbouring section's prose:

```python
section("Installation_guide", "Pre-installation").content
# -> "connection is available."    text from the previous section
```

It carried a correct revid, a correct `source_url`, and a `content_hash` that
faithfully hashed the wrong text. Verified across the corpus: character indexing
resolves 432/432 sections onto their heading; byte indexing resolves 121/432.
Seven of eight corpus pages were affected. The old suite missed it because it
compared two fetches against each other and read the heading from API metadata
rather than from the extracted text.

### 2. `commands()` missed almost every real code block

Extraction recognised space-indented lines, `<pre>` and `<code>`. The corpus
contains **zero** `<pre>`, `<code>` or `<syntaxhighlight>`. Real code lives in
templates: 1271 `{{ic}}`, 82 `{{hc}}`, 26 `{{bc}}`. `commands()` recovered 7 of
108 `{{bc}}`/`{{hc}}` blocks, and those 7 were coincidences where the same command
also appeared indented elsewhere.

This is worse than ordinary under-extraction. `AGENTS.md` §6 instructs the calling
agent that an empty `commands()` means the wiki "does not specify an explicit
command block" — so a miss was laundered into a confident false statement about
the wiki. **False silence, not false speech.**

### 3. `links()` returned page metadata as article links

`[[Category:…]]` and interwiki language links (`ar:`, `de:`, …) were returned as
navigable links: 76 of 161 results on `Installation guide`.

---

## 5. Deployment Recommendation

The extraction paths above are now covered by tests pinned to real recorded wiki
content, and the suite fails when they regress. The previous document's
"Production Ready" certification rested on a suite that could not observe the
behavior it certified; treat that claim as withdrawn and this one as scoped to
what the tests actually assert.

### Defects found by using the server, not testing it

The three items below were opened as known gaps and closed after the server was
registered as a live MCP and driven as an agent would drive it. None were visible
from unit tests or from the wire protocol; all three appeared the moment a model
had to _consume_ the output.

- **`extraction_method` claimed `wikitext_byte_offset`.** It slices by character.
  A provenance field that misstates the method, in a system whose product is
  provenance.
- **`warnings().message` shipped raw wikitext.** The constitution requires the
  agent to quote warnings to the user, so the mandated response shape rendered as
  `Only root and members of the {{ic|network}} or the {{ic|wheel}} [[user group]]…`.
  Cleaning it also fixed a truncation bug: the naive `split("|", 1)` cut every
  message at the first pipe inside a nested template or link.
- **`content` was executed but unhashed.** `content_hash` attested `content_raw`;
  the cleaning transform — the only non-verbatim step in the chain — was attested
  by nothing. Now covered by `content_hash_cleaned`.
- **`AGENTS.md` §4 told agents every field was verbatim.** It is the binding
  contract, and after `content`/`message` became rendered fields it was wrong: an
  agent obeying it would present `--efi-directory=esp` as wiki text, when the wiki
  says `''esp''` and means "substitute your EFI partition". `test_contract.py` now
  fails when the contract drifts from the tool schema.
- **Interwiki prefixes were a static list**, missing 32 real prefixes (`fedora`,
  `doi`, `phab`, `mw`, `meta`, `lv`, …), each reported as a navigable article
  link, and wrongly excluding `man` and `kernel`. Now read from the wiki's own
  `siteinfo` tables.

### The live audit

`make audit` renders every section of 36 live pages (1834 sections) and checks the
contract's invariants against them: no root-prompt lookalike outside a fence, no
list marker leaking past its bullet, no list skipping a nesting level, balanced
fences, `content_hash` attesting `content_raw`, and every unrendered template
appearing byte-for-byte as the wiki wrote it.

It asserts nothing about _what_ a page says — only that whatever it says comes out
obeying the contract. It is deliberately outside pytest, which blocks sockets.

This is not redundant with the fixture suite. Five defects reached `master` past a
green suite and were caught on first contact with live content:

| defect                                        | fixture corpus said                             |
| :-------------------------------------------- | :---------------------------------------------- | ------------------------------------------ | ----- |
| `##` → `1. # body` (bare `#` back in prose)   | green; 40 affected lines were _in_ the fixtures |
| `{{Note                                       | body}}` rendered as code                        | green; no fixture has a leading-space body |
| `warnings()` dropped every Spanish admonition | green; corpus is English                        |
| `{{Accuracy                                   | {{ic                                            | x}}}}` altered inside "verbatim"           | green |
| nested list lost its first indent             | green                                           |

The first two were _present in the recorded fixtures_ and invisible because the
assertions looked one character to the left. Re-recording would not have helped.

### Remaining gaps

- **The section renderer resolves a whitelist.** `{{bc}}`, `{{hc}}`, `{{Note}}`,
  `{{Warning}}`, `{{Tip}}`, `{{Caution}}`, the inline templates, links, headings and
  list markers. Anything else — `{{App}}`, `{{Accuracy}}`, `{{Bug}}` — survives as
  raw markup rather than being dropped, and `test_section_render_golden` pins that
  residual set so a newly used template goes red instead of vanishing silently.
  Rendering it away would be synthesis by omission; leaving it visible is the
  honest failure.
- **`{{bc}}`/`{{hc}}` are Arch template conventions**, declared in code rather than
  discovered. MediaWiki exposes no way to ask which templates are code. If the
  wiki renames them, extraction silently returns fewer blocks — the one failure
  mode the corpus tests would catch only if a fixture were re-recorded.
- **No caching of `fetch_wiki_parse` in the live path.** An agent calling
  `section()`, `commands()` and `warnings()` on one page issues three identical
  HTTP requests. Pure latency, and the hardest thing here to test offline. It is
  no longer merely theoretical: a live audit of 1834 sections spent its whole
  budget re-fetching the same 37 pages, because `section()` refetches per call.
- **`warnings()` costs one extra request per page**, to resolve template names it
  has not seen before (`{{Astuce}}` → `Template:Warning (Français)`). Resolutions
  are cached across pages for the process lifetime; a failure raises rather than
  degrading to the English-only subset.
- **Template aliases are pinned per page.** `tests/fixtures/query_aliases_*.json`
  records exactly the names `warnings()` will ask about, derived from the parse
  fixture by the recorder. A page whose templates change needs its alias fixture
  re-recorded, or the offline test fails loudly rather than silently resolving
  nothing.
- **`search().snippet` passes MediaWiki's `<span class="searchmatch">` HTML
  through** unrendered.
