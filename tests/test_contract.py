"""
The agent contract must describe the tools that exist.

AGENTS.md and the injected `arch-wiki-usage` prompt are the only things telling a
consuming model how to read this MCP's output. When commands() and warnings()
gained cleaned/verbatim field pairs, both documents still said every field was
"verbatim evidence" -- so an agent following the contract would have presented
`--efi-directory=esp` as wiki text, when the wiki says ''esp'' and means "the
user's EFI partition". These tests fail when the contract drifts from the schema.

The field list is derived from the dataclasses, not hand-maintained: a new output
field cannot be added without documenting it in both places.
"""

import re
from dataclasses import asdict, fields
from pathlib import Path

import pytest

from arch_wiki_mcp import extractor, server

REPO_ROOT = Path(__file__).parent.parent
AGENTS_MD = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")

# Every dataclass an agent sees the fields of.
OUTPUT_SCHEMAS = (
    extractor.CodeBlock,
    extractor.WarningBlock,
    extractor.ExtractedBlock,
    extractor.SearchResult,
)

# Fields an agent can read without being told what they mean.
SELF_EXPLANATORY = {
    "type", "content", "message", "block_type", "source_pattern",
    "language", "header", "revid", "content_hash", "source_url",
    "title", "url", "timestamp", "section_anchor", "section_heading",
    "extraction_method", "wikitext", "pageid",
    # links(): the name says the thing. A link has a target, the words it was
    # written as, and the page it was found on.
    "target_page", "display_text", "anchor", "source_page",
    # page(): the section list, in the shape sections() returns.
    "sections",
}


def declared_fields() -> set:
    return {f.name for schema in OUTPUT_SCHEMAS for f in fields(schema)}


def contract_fields() -> list:
    """Every output field whose meaning an agent cannot guess."""
    return sorted(declared_fields() - SELF_EXPLANATORY)


def usage_prompt() -> str:
    result = server._handle_prompts_get(1, {"name": "arch-wiki-usage"})
    return result["result"]["messages"][0]["content"]["text"]


@pytest.mark.parametrize("field", contract_fields())
def test_agents_md_names_every_ambiguous_field(field):
    assert field in AGENTS_MD, f"the binding contract never mentions {field}"


@pytest.mark.parametrize("field", contract_fields())
def test_the_injected_prompt_names_every_ambiguous_field(field):
    assert field in usage_prompt(), f"agents are never told what {field} means"


def test_the_derived_field_set_is_the_one_we_expect():
    """Tripwire: a field leaving this set means the schema shrank silently."""
    assert contract_fields() == [
        "alias",
        "alias_revid",
        "alias_target",
        "content_hash_cleaned",
        "content_raw",
        "match",
        "message_hash_cleaned",
        "message_raw",
        "placeholders",
        "revision_url",
        "revision_wikitext_url",
        "snippet",
    ]


def test_no_self_explanatory_field_is_actually_missing_from_the_schema():
    """Guards the exemption list against rotting into a way to skip documentation."""
    stale = SELF_EXPLANATORY - declared_fields() - serialized_fields()
    assert not stale, f"exempted fields that no longer exist: {stale}"


def serialized_fields() -> set:
    """
    Every key an agent actually receives -- taken from real tool output, not from
    the dataclasses.

    The dataclasses are not the whole schema: warnings() and commands() add keys
    at serialization (`source_url`, `alias_revision_url`), and those slipped past
    a guard that only read `fields()`. A field an agent must interpret is one an
    agent receives, whichever line of code put it there.
    """
    keys = set(extractor.page("GRUB"))
    keys |= set(asdict(extractor.section("GRUB", "Installation")))
    keys |= set(extractor.commands("GRUB", "Installation")[0])
    keys |= set(extractor.links("GRUB", "Installation")[0])
    for warning in extractor.warnings("Installation guide (Français)"):
        keys |= set(warning)
    for hit in extractor.search("GRUB"):
        keys |= set(hit)
    return keys


def test_every_field_an_agent_receives_is_documented():
    """
    The guard's own stated rule -- "a new output field cannot be added without
    documenting it in both places" -- was true only of dataclass fields. Keys added
    at serialization reached agents undocumented, which is the same hole in the
    same wall.
    """
    undocumented = {
        field
        for field in serialized_fields() - SELF_EXPLANATORY
        if field not in AGENTS_MD or field not in usage_prompt()
    }
    assert not undocumented, (
        f"agents receive fields no contract explains: {sorted(undocumented)}"
    )


def test_the_contract_no_longer_claims_all_output_is_verbatim():
    """
    commands().content and warnings().message are deliberately NOT verbatim.
    The old §4 told agents otherwise, in exactly these words.
    """
    assert "Content returned by this MCP is **verbatim evidence**" not in AGENTS_MD


def test_no_document_still_calls_section_output_raw_wikitext():
    """
    section().content used to be the one unrendered field, and both documents told
    the agent to quote it as-is. It is rendered now; an agent quoting `content_raw`
    on that advice would paste {{ic|...}} and '#'-prefixed prose at a user.
    """
    assert "returns raw wikitext only" not in AGENTS_MD
    assert "returns raw wikitext only" not in usage_prompt()


def test_both_documents_tell_the_agent_which_section_field_to_show():
    for document in (AGENTS_MD, usage_prompt()):
        assert "section()" in document
        assert "content_raw" in document


def test_the_section_tool_surfaces_every_field_of_its_dataclass():
    """
    tool_section() once hand-listed its response keys and omitted content_raw and
    content_hash_cleaned. An agent then received rendered `content` beside a
    `content_hash` attesting a verbatim slice it was never shown -- a citation it
    could not check, which is the one thing this MCP exists to prevent.
    """
    result = server.tool_section("GRUB", "Installation")
    declared = {f.name for f in fields(extractor.ExtractedBlock)}
    assert set(result) == declared

    assert result["content_hash"] == extractor.hash_content(result["content_raw"])
    assert result["content_hash_cleaned"] == extractor.hash_content(result["content"])


def test_the_section_tool_returns_rendered_content_over_the_wire():
    """The wire format is where an agent actually meets the '#' ambiguity."""
    result = server.tool_section("Installation_guide", "Boot_the_live_environment")

    assert result["content"].startswith("### Boot the live environment")
    assert "1. Point the current boot device" in result["content"]
    assert "**Note:**" in result["content"]

    assert result["content_raw"].startswith("=== Boot the live environment ===")
    assert "# Point the current boot device" in result["content_raw"]


def _plain(text: str) -> str:
    """Strip markdown/quoting noise so both documents can be matched the same way."""
    return re.sub(r"\s+", " ", re.sub(r"[`*\"]", "", text))


@pytest.mark.parametrize("source", ["AGENTS.md", "usage_prompt"])
def test_the_contract_cites_the_redirect_page_not_its_destination(source):
    """
    alias_revid is a revision of Template:<alias>. Pairing it with alias_target
    names a title and a revision belonging to two different pages -- a citation
    that resolves to nothing, in the one field added to make the type falsifiable.

    Both documents shipped exactly that instruction ("cite alias_target at
    alias_revid"). The tool output was right and the manual was wrong, which is
    the failure this whole test module exists to catch.
    """
    text = _plain(AGENTS_MD if source == "AGENTS.md" else usage_prompt())
    assert "cite Template:<alias> at alias_revid" in text


def documented_hashes() -> set:
    """Every SHA-256 the README prints as if it were real."""
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    return set(re.findall(r"\b[0-9a-f]{64}\b", readme))


def reproducible_hashes() -> set:
    produced = set()
    block = server.tool_section("Installation_guide", "Boot_the_live_environment")
    produced |= {block["content_hash"], block["content_hash_cleaned"]}
    for command in extractor.commands("GRUB", "Installation"):
        produced |= {command["content_hash"], command["content_hash_cleaned"]}
    for warning in extractor.warnings("Iwd", "Usage"):
        produced |= {warning["content_hash"], warning["message_hash_cleaned"]}
    # The README's alias-provenance example is a real block off a real page.
    for warning in extractor.warnings("Installation guide (Français)"):
        produced |= {warning["content_hash"], warning["message_hash_cleaned"]}
    return produced


def test_every_hash_in_the_readme_reproduces_from_the_fixtures():
    """
    A rendering change moves content_hash_cleaned, and a hash pasted into prose
    does not move with it. The README shipped a stale one for exactly that reason.
    In a repo whose product is falsifiable citation, a hash nothing produces is
    the worst kind of documentation error.
    """
    unverified = documented_hashes() - reproducible_hashes()
    assert not unverified, f"README prints hashes nothing produces: {unverified}"


# What the README promises about provenance, tool by tool. Three tiers, not two.
#
# The first draft of that paragraph said "every excerpt an agent receives carries the
# revision it came from and a fingerprint of the exact bytes". search() carries neither
# -- it is a pointer, and its own tool description says so -- and links() carries a
# revid but no hash. So the sentence written to *replace* an overclaim was itself an
# overclaim, in the change whose entire subject was claims outrunning what backs them.
# CodeRabbit caught it. This is the guard that should have.
HASHED_EVIDENCE = {
    "page": "wikitext_hash",       # the page's own wikitext
    "section": "content_hash",
    "commands": "content_hash",
    "warnings": "content_hash",
}
ATTRIBUTED_ONLY = ["links"]        # a link is a target, not a quotation
POINTERS = ["search", "sections"]  # no revid, no hash, and they must not pretend


def _first(tool: str) -> dict:
    call = {
        "page": lambda: extractor.page("GRUB"),
        "section": lambda: asdict(extractor.section("GRUB", "Installation")),
        "commands": lambda: extractor.commands("GRUB", "Installation")[0],
        "warnings": lambda: extractor.warnings("Iwd", "Usage")[0],
        "links": lambda: extractor.links("GRUB", "Installation")[0],
        "search": lambda: extractor.search("GRUB")[0],
        "sections": lambda: server.tool_sections("GRUB")["sections"][0],
    }[tool]
    return call()


@pytest.mark.parametrize("tool,hash_field", sorted(HASHED_EVIDENCE.items()))
def test_quotable_output_carries_a_revision_and_a_fingerprint(tool, hash_field):
    payload = _first(tool)

    assert payload.get("revid"), f"{tool}() hands over text with no revision"
    assert payload.get(hash_field), f"{tool}() hands over text with no fingerprint"
    assert payload.get("revision_url"), f"{tool}() cites no revision-addressed URL"


@pytest.mark.parametrize("tool", ATTRIBUTED_ONLY)
def test_a_link_is_attributed_but_not_fingerprinted(tool):
    """Pinning the middle tier, so the README cannot quietly promote or demote it."""
    payload = _first(tool)

    assert payload.get("revid"), f"{tool}() is unattributed"
    assert "content_hash" not in payload, (
        f"{tool}() now carries a hash; the README says it does not"
    )


@pytest.mark.parametrize("tool", POINTERS)
def test_a_pointer_never_looks_like_evidence(tool):
    """
    The dangerous direction. A pointer that grew a revid would invite an agent to
    quote a `snippet` -- ellipsised, HTML-marked search-result text -- as if it were
    attested wiki content. Absence here is the feature.
    """
    payload = _first(tool)

    assert "revid" not in payload, f"{tool}() is a pointer but carries a revid"
    assert "content_hash" not in payload, f"{tool}() is a pointer but carries a hash"
