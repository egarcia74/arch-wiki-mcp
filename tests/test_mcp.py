"""
MCP tool-surface tests: schema shape, title/URL handling, and error mapping.
"""

import pytest

from conftest import GRUB_REVID
from src import mcp_server

CONTENT_TOOLS = {"search", "page", "sections", "section", "commands", "warnings", "links"}


def test_extract_title_from_url():
    assert mcp_server.extract_title_from_url("GRUB") == "GRUB"
    assert mcp_server.extract_title_from_url("https://wiki.archlinux.org/title/GRUB") == "GRUB"
    assert (
        mcp_server.extract_title_from_url("https://wiki.archlinux.org/title/GRUB#Installation")
        == "GRUB"
    )


def test_extract_title_from_url_rejects_unparseable():
    with pytest.raises(ValueError):
        mcp_server.extract_title_from_url("https://wiki.archlinux.org/")


def test_tools_list_surface_is_exact():
    """examples() was removed; it violated the Exclusive Command Source rule."""
    listed = {t["name"] for t in mcp_server._handle_tools_list(1)["result"]["tools"]}
    assert listed == CONTENT_TOOLS
    assert "examples" not in listed


def test_usage_prompt_does_not_bless_heuristic_inference():
    prompt = mcp_server._handle_prompts_get(1, {"name": "arch-wiki-usage"})
    text = prompt["result"]["messages"][0]["content"]["text"]
    assert "examples()" not in text
    assert "Heuristic inference" not in text
    assert "must not synthesize" in text


def test_page_tool():
    result = mcp_server.tool_page("GRUB")
    assert result["title"] == "GRUB"
    assert result["revid"] == GRUB_REVID
    assert result["url"] == "https://wiki.archlinux.org/title/GRUB"
    assert len(result["sections"]) == 73


def test_page_tool_accepts_url():
    assert mcp_server.tool_page("https://wiki.archlinux.org/title/GRUB")["title"] == "GRUB"


def test_sections_tool():
    sections = mcp_server.tool_sections("GRUB")["sections"]
    assert len(sections) == 73
    assert sections[0]["anchor"]
    assert "byteoffset" in sections[0]


def test_section_tool_provenance():
    result = mcp_server.tool_section("GRUB", "Installation")
    for field in (
        "title",
        "url",
        "revid",
        "section_anchor",
        "section_heading",
        "extraction_method",
        "content",
        "content_hash",
    ):
        assert result[field] is not None, f"{field} must carry provenance"
    assert result["url"] == "https://wiki.archlinux.org/title/GRUB#Installation"


def test_commands_tool_schema():
    blocks = mcp_server.tool_commands("GRUB", "Installation")["commands"]
    assert blocks, "GRUB#Installation contains code blocks"
    for block in blocks:
        for field in (
            "content",
            "content_raw",
            "content_hash",
            "block_type",
            "source_pattern",
            "language",
            "header",
            "placeholders",
            "source_url",
            "revid",
        ):
            assert field in block


def test_commands_tool_full_page():
    blocks = mcp_server.tool_commands("GRUB")["commands"]
    assert len(blocks) == 65  # 17 bc + 8 hc + 40 indented


def test_warnings_tool():
    found = mcp_server.tool_warnings("GRUB", "Installation")["warnings"]
    for warning in found:
        assert warning["source_url"].endswith("#Installation")
        assert warning["content_hash"]


def test_links_tool():
    found = mcp_server.tool_links("GRUB", "Installation")["links"]
    for link in found:
        assert link["source_page"] == "GRUB"
        assert not link["target_page"].startswith(("Category:", "File:"))


def test_missing_anchor_maps_to_error_not_empty_list():
    """The JSON-RPC layer must surface a failure, not a silent []."""
    result = mcp_server.handle_tool_call("commands", {"title_or_url": "GRUB", "anchor": "Bogus"})
    assert "error" in result
    assert "commands" not in result


def test_missing_page_maps_to_error():
    result = mcp_server.handle_tool_call("page", {"title_or_url": "Nonexistent page xyz"})
    assert "error" in result


def test_removed_examples_tool_is_rejected():
    assert "error" in mcp_server.handle_tool_call("examples", {"title_or_url": "GRUB"})


def test_search_tool():
    results = mcp_server.tool_search("GRUB")["results"]
    assert results
    assert results[0]["title"]
    assert results[0]["url"].startswith("https://wiki.archlinux.org/title/")


def test_search_tool_zero_results():
    assert mcp_server.tool_search("wifi not working")["results"] == []
