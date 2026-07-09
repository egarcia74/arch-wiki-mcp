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
from dataclasses import fields
from pathlib import Path

import pytest

from src import extractor, mcp_server

REPO_ROOT = Path(__file__).parent.parent
AGENTS_MD = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")

# Every dataclass an agent sees the fields of.
OUTPUT_SCHEMAS = (extractor.CodeBlock, extractor.WarningBlock, extractor.ExtractedBlock)

# Fields an agent can read without being told what they mean.
SELF_EXPLANATORY = {
    "type", "content", "message", "block_type", "source_pattern",
    "language", "header", "revid", "content_hash", "source_url",
    "title", "url", "timestamp", "section_anchor", "section_heading",
    "extraction_method",
}


def declared_fields() -> set:
    return {f.name for schema in OUTPUT_SCHEMAS for f in fields(schema)}


def contract_fields() -> list:
    """Every output field whose meaning an agent cannot guess."""
    return sorted(declared_fields() - SELF_EXPLANATORY)


def usage_prompt() -> str:
    result = mcp_server._handle_prompts_get(1, {"name": "arch-wiki-usage"})
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
        "content_hash_cleaned",
        "content_raw",
        "message_hash_cleaned",
        "message_raw",
        "placeholders",
    ]


def test_no_self_explanatory_field_is_actually_missing_from_the_schema():
    """Guards the exemption list against rotting into a way to skip documentation."""
    stale = SELF_EXPLANATORY - declared_fields() - {"source_url"}  # added at serialization
    assert not stale, f"exempted fields that no longer exist: {stale}"


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
    result = mcp_server.tool_section("GRUB", "Installation")
    declared = {f.name for f in fields(extractor.ExtractedBlock)}
    assert set(result) == declared

    assert result["content_hash"] == extractor.hash_content(result["content_raw"])
    assert result["content_hash_cleaned"] == extractor.hash_content(result["content"])


def test_the_section_tool_returns_rendered_content_over_the_wire():
    """The wire format is where an agent actually meets the '#' ambiguity."""
    result = mcp_server.tool_section("Installation_guide", "Boot_the_live_environment")

    assert result["content"].startswith("### Boot the live environment")
    assert "1. Point the current boot device" in result["content"]
    assert "**Note:**" in result["content"]

    assert result["content_raw"].startswith("=== Boot the live environment ===")
    assert "# Point the current boot device" in result["content_raw"]


def documented_hashes() -> set:
    """Every SHA-256 the README prints as if it were real."""
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    return set(re.findall(r"\b[0-9a-f]{64}\b", readme))


def reproducible_hashes() -> set:
    produced = set()
    block = mcp_server.tool_section("Installation_guide", "Boot_the_live_environment")
    produced |= {block["content_hash"], block["content_hash_cleaned"]}
    for command in extractor.commands("GRUB", "Installation"):
        produced |= {command["content_hash"], command["content_hash_cleaned"]}
    for warning in extractor.warnings("Iwd", "Usage"):
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
