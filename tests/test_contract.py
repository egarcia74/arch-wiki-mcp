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

from dataclasses import fields
from pathlib import Path

import pytest

from src import extractor, mcp_server

REPO_ROOT = Path(__file__).parent.parent
AGENTS_MD = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")

# Fields an agent can read without being told what they mean.
SELF_EXPLANATORY = {
    "type", "content", "message", "block_type", "source_pattern",
    "language", "header", "revid", "content_hash", "source_url",
}


def contract_fields() -> list:
    """Every output field whose meaning an agent cannot guess."""
    declared = set()
    for dataclass in (extractor.CodeBlock, extractor.WarningBlock):
        declared |= {f.name for f in fields(dataclass)}
    return sorted(declared - SELF_EXPLANATORY)


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
    declared = set()
    for dataclass in (extractor.CodeBlock, extractor.WarningBlock):
        declared |= {f.name for f in fields(dataclass)}
    stale = SELF_EXPLANATORY - declared - {"source_url"}  # source_url is added at serialization
    assert not stale, f"exempted fields that no longer exist: {stale}"


def test_the_contract_no_longer_claims_all_output_is_verbatim():
    """
    commands().content and warnings().message are deliberately NOT verbatim.
    The old §4 told agents otherwise, in exactly these words.
    """
    assert "Content returned by this MCP is **verbatim evidence**" not in AGENTS_MD


def test_both_documents_tell_the_agent_section_is_unrendered():
    """The one tool with no rendered field. An agent must not silently render it."""
    assert "raw wikitext" in AGENTS_MD
    assert "raw wikitext" in usage_prompt()
