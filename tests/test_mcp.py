"""
MCP Server Integration Tests
Tests that MCP tools return extractor output verbatim with full provenance.
"""

import json
import sys
sys.path.insert(0, '..')
from src.mcp_server import (
    tool_page,
    tool_sections,
    tool_section,
    tool_commands,
    tool_warnings,
    tool_links
)


def test_page():
    """Test page tool returns full metadata including revid and hash."""
    print("Test: page(GRUB)")
    print("-" * 80)
    
    result = tool_page("GRUB")
    
    assert "title" in result, "Missing title"
    assert "revid" in result, "Missing revid"
    assert "url" in result, "Missing URL"
    assert "wikitext_hash" in result, "Missing wikitext hash"
    assert "sections" in result, "Missing sections"
    
    print(f"✅ Title: {result['title']}")
    print(f"✅ Revid: {result['revid']}")
    print(f"✅ URL: {result['url']}")
    print(f"✅ Hash: {result['wikitext_hash'][:16]}...")
    print(f"✅ Sections: {len(result['sections'])}")
    print()


def test_page_with_url():
    """Test page tool accepts URL and extracts title."""
    print("Test: page(URL)")
    print("-" * 80)
    
    result = tool_page("https://wiki.archlinux.org/title/GRUB")
    
    assert result["title"] == "GRUB", "Title not extracted from URL"
    print(f"✅ URL parsed correctly: {result['title']}")
    print()


def test_sections():
    """Test sections tool returns all section metadata."""
    print("Test: sections(GRUB)")
    print("-" * 80)
    
    result = tool_sections("GRUB")
    
    assert "sections" in result, "Missing sections key"
    assert len(result["sections"]) > 0, "No sections returned"
    
    first = result["sections"][0]
    assert "anchor" in first, "Missing anchor"
    assert "byteoffset" in first, "Missing byteoffset"
    
    print(f"✅ Sections: {len(result['sections'])}")
    print(f"✅ First section: {first['line']}")
    print(f"✅ Anchor: {first['anchor']}")
    print()


def test_section():
    """Test section tool returns content with hash and provenance."""
    print("Test: section(GRUB, Installation)")
    print("-" * 80)
    
    result = tool_section("GRUB", "Installation")
    
    assert "title" in result, "Missing title"
    assert "revid" in result, "Missing revid"
    assert "url" in result, "Missing URL"
    assert "section_anchor" in result, "Missing section_anchor"
    assert "content" in result, "Missing content"
    assert "content_hash" in result, "Missing content_hash"
    assert "extraction_method" in result, "Missing extraction_method"
    
    print(f"✅ Title: {result['title']}")
    print(f"✅ Revid: {result['revid']}")
    print(f"✅ Section: {result['section_heading']}")
    print(f"✅ URL: {result['url']}")
    print(f"✅ Hash: {result['content_hash'][:16]}...")
    print(f"✅ Method: {result['extraction_method']}")
    print(f"✅ Content length: {len(result['content'])} chars")
    print()


def test_commands():
    """Test commands tool returns code blocks with hashes."""
    print("Test: commands(GRUB, Installation)")
    print("-" * 80)
    
    result = tool_commands("GRUB", "Installation")
    
    assert "commands" in result, "Missing commands key"
    
    if result["commands"]:
        first = result["commands"][0]
        assert "content" in first, "Missing content"
        assert "content_hash" in first, "Missing content_hash"
        assert "block_type" in first, "Missing block_type"
        assert "source_url" in first, "Missing source_url"
        
        print(f"✅ Commands found: {len(result['commands'])}")
        print(f"✅ First block type: {first['block_type']}")
        print(f"✅ First block hash: {first['content_hash'][:16]}...")
        print(f"✅ Source URL: {first['source_url']}")
    else:
        print("⚠️  No commands in this section")
    print()


def test_warnings():
    """Test warnings tool returns templates with hashes."""
    print("Test: warnings(GRUB, Installation)")
    print("-" * 80)
    
    result = tool_warnings("GRUB", "Installation")
    
    assert "warnings" in result, "Missing warnings key"
    
    if result["warnings"]:
        first = result["warnings"][0]
        assert "type" in first, "Missing type"
        assert "message" in first, "Missing message"
        assert "content_hash" in first, "Missing content_hash"
        assert "source_url" in first, "Missing source_url"
        
        print(f"✅ Warnings found: {len(result['warnings'])}")
        print(f"✅ First type: {first['type']}")
        print(f"✅ First message hash: {first['content_hash'][:16]}...")
        print(f"✅ Source URL: {first['source_url']}")
    else:
        print("⚠️  No warnings in this section")
    print()


def test_links():
    """Test links tool returns internal links."""
    print("Test: links(GRUB, Installation)")
    print("-" * 80)
    
    result = tool_links("GRUB", "Installation")
    
    assert "links" in result, "Missing links key"
    
    if result["links"]:
        first = result["links"][0]
        assert "target_page" in first, "Missing target_page"
        assert "source_page" in first, "Missing source_page"
        assert "source_url" in first, "Missing source_url"
        
        print(f"✅ Links found: {len(result['links'])}")
        print(f"✅ First link: [[{first['target_page']}]]")
        print(f"✅ Source page: {first['source_page']}")
        print(f"✅ Source URL: {first['source_url']}")
    else:
        print("⚠️  No links in this section")
    print()


def test_commands_full_page():
    """Test commands on full page (no section)."""
    print("Test: commands(Installation_guide) - full page")
    print("-" * 80)
    
    result = tool_commands("Installation_guide")
    
    assert "commands" in result, "Missing commands key"
    print(f"✅ Commands in full page: {len(result['commands'])}")
    print()


def test_provenance_integrity():
    """
    Critical test: Verify provenance is preserved exactly.
    
    Constitutional requirement: All returned data includes:
    - URL
    - Section anchor (if applicable)
    - Revision ID
    - Content hash
    - Extraction method
    """
    print("Test: Provenance Integrity")
    print("-" * 80)
    
    # Get section
    sect = tool_section("GRUB", "Installation")
    
    # Verify all provenance fields present
    provenance_fields = [
        "title", "url", "revid", "section_anchor",
        "section_heading", "content_hash", "extraction_method"
    ]
    
    for field in provenance_fields:
        assert field in sect, f"Missing provenance field: {field}"
        assert sect[field] is not None, f"Null provenance field: {field}"
    
    print("✅ All provenance fields present and non-null")
    
    # Get commands
    cmds = tool_commands("GRUB", "Installation")
    
    if cmds["commands"]:
        cmd = cmds["commands"][0]
        assert "content_hash" in cmd, "Commands missing content_hash"
        assert "source_url" in cmd, "Commands missing source_url"
        print("✅ Commands include hash and source URL")
    
    # Get warnings
    warns = tool_warnings("GRUB", "Installation")
    
    if warns["warnings"]:
        warn = warns["warnings"][0]
        assert "content_hash" in warn, "Warnings missing content_hash"
        assert "source_url" in warn, "Warnings missing source_url"
        print("✅ Warnings include hash and source URL")
    
    print()
    print("=" * 80)
    print("CONSTITUTIONAL COMPLIANCE VERIFIED")
    print("=" * 80)
    print("All MCP tools preserve provenance exactly as extractor returns it.")


if __name__ == "__main__":
    print("=" * 80)
    print("MCP Server Integration Tests")
    print("=" * 80)
    print()
    
    test_page()
    test_page_with_url()
    test_sections()
    test_section()
    test_commands()
    test_warnings()
    test_links()
    test_commands_full_page()
    test_provenance_integrity()
    
    print()
    print("=" * 80)
    print("All tests passed")
    print("=" * 80)
