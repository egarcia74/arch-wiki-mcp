"""
MCP tool-surface tests: schema shape, title/URL handling, and error mapping.
"""

import io
import json
import re
from pathlib import Path

import pytest

from conftest import GRUB_REVID
from src import mcp_server

# tomllib is 3.11+, and pyproject declares requires-python = ">=3.10". Reading
# the one line we need keeps the floor honest without a tomli dependency in a
# project whose selling point is having none.
_PROJECT_TABLE = re.compile(r"^\[project\]$(.*?)^\[", re.M | re.S)
_VERSION_LINE = re.compile(r'^version\s*=\s*"([^"]+)"', re.M)

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
    assert len(blocks) == 60  # 17 bc + 8 hc + 35 indented


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


def _drive_server(stdin_text, monkeypatch, capsys):
    """Feed raw lines to the stdio loop; return the parsed responses."""
    monkeypatch.setattr(mcp_server.sys, "stdin", io.StringIO(stdin_text))
    mcp_server.run_mcp_server()
    return [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]


def test_a_parse_error_never_answers_with_a_previous_request_id(monkeypatch, capsys):
    """
    A malformed line must not be blamed on the last request that parsed.

    msg_id used to survive the iteration that bound it, so an unparseable line
    emitted an error carrying the id of an already-answered request -- a client
    keyed on id sees its result overwritten. JSON-RPC 2.0: null when unknown.
    """
    responses = _drive_server(
        '{"jsonrpc":"2.0","id":1,"method":"tools/list"}\nNOT JSON\n', monkeypatch, capsys
    )

    assert len(responses) == 2
    assert responses[0]["id"] == 1 and "result" in responses[0]
    assert responses[1]["id"] is None, "parse error stole the id of request 1"
    assert responses[1]["error"]["code"] == -32603


def test_server_info_version_matches_the_package_version(monkeypatch, capsys):
    """
    The only way a client can tell a reloaded server from a stale process is
    serverInfo.version. Nothing pinned it to pyproject, so it could silently
    lag a release and quietly answer for the previous build.
    """
    pyproject = Path(__file__).parent.parent / "pyproject.toml"
    table = _PROJECT_TABLE.search(pyproject.read_text())
    assert table, "no [project] table in pyproject.toml"
    versions = _VERSION_LINE.findall(table.group(1))
    assert len(versions) == 1, f"expected one version in [project], found {versions}"
    declared = versions[0]

    responses = _drive_server(
        '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}\n', monkeypatch, capsys
    )
    assert responses[0]["result"]["serverInfo"]["version"] == declared


def test_tools_call_without_a_name_is_invalid_params(monkeypatch, capsys):
    responses = _drive_server(
        '{"jsonrpc":"2.0","id":7,"method":"tools/call","params":{"arguments":{}}}\n',
        monkeypatch,
        capsys,
    )

    assert responses[0]["id"] == 7
    assert responses[0]["error"]["code"] == -32602
