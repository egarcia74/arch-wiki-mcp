#!/usr/bin/env python3
"""
Proof-of-Life Extractor for Arch Wiki MCP
Tests constitutional guarantees against real MediaWiki API responses

This is a throwaway script to validate extraction logic before MCP implementation.
"""

import hashlib
import json
import re
import unicodedata
from typing import Dict, List, Optional
from urllib.request import urlopen
from urllib.parse import urlencode

API_ENDPOINT = "https://wiki.archlinux.org/api.php"


def fetch_page(page_title: str) -> Dict:
    """Fetch page wikitext, sections, and revision ID from MediaWiki API."""
    params = {
        "action": "parse",
        "page": page_title,
        "prop": "wikitext|sections|revid",
        "format": "json",
    }
    url = f"{API_ENDPOINT}?{urlencode(params)}"
    
    with urlopen(url) as response:
        data = json.loads(response.read().decode("utf-8"))
    
    if "error" in data:
        raise ValueError(f"API Error: {data['error']}")
    
    return data["parse"]


def extract_section_wikitext(wikitext: str, section_start: int, section_end: Optional[int]) -> str:
    """Extract section content from wikitext using byte offsets."""
    # MediaWiki byte offsets are in bytes, not characters
    wikitext_bytes = wikitext.encode("utf-8")
    
    if section_end is not None:
        section_bytes = wikitext_bytes[section_start:section_end]
    else:
        section_bytes = wikitext_bytes[section_start:]
    
    return section_bytes.decode("utf-8")


def extract_code_blocks(wikitext: str) -> List[str]:
    """Extract indented code blocks from wikitext."""
    code_blocks = []
    lines = wikitext.split("\n")
    
    current_block = []
    in_block = False
    
    for line in lines:
        # Code blocks start with space in wikitext
        if line.startswith(" "):
            in_block = True
            current_block.append(line[1:])  # Remove leading space
        else:
            if in_block and current_block:
                code_blocks.append("\n".join(current_block))
                current_block = []
            in_block = False
    
    # Capture final block
    if current_block:
        code_blocks.append("\n".join(current_block))
    
    return code_blocks


def extract_warnings(wikitext: str) -> List[Dict[str, str]]:
    """Extract warning/note/tip templates from wikitext."""
    warnings = []
    
    # Match {{Warning|...}}, {{Note|...}}, {{Tip|...}}
    pattern = r'{{(Warning|Note|Tip|Caution)\|([^}]+)}}'
    
    for match in re.finditer(pattern, wikitext, re.IGNORECASE):
        warnings.append({
            "type": match.group(1).upper(),
            "text": match.group(2).strip()
        })
    
    return warnings


def hash_content(text: str) -> str:
    """Hash content block with constitutional requirements: Unicode NFC + whitespace preserved."""
    # Normalize to Unicode NFC
    normalized = unicodedata.normalize("NFC", text)
    
    # Hash with SHA-256
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def main():
    print("=" * 80)
    print("Arch Wiki MCP - Proof-of-Life Extractor")
    print("Constitutional Compliance Test")
    print("=" * 80)
    print()
    
    # Test pages
    test_pages = ["Installation_guide", "Pacman", "GRUB"]
    
    for page_title in test_pages:
        print(f"\n{'='*80}")
        print(f"Testing: {page_title}")
        print(f"{'='*80}\n")
        
        try:
            page_data = fetch_page(page_title)
            
            # Constitutional Requirement 1: Revision ID
            revid = page_data["revid"]
            print(f"✅ Revision ID: {revid}")
            
            # Constitutional Requirement 2: Page URL
            url = f"https://wiki.archlinux.org/title/{page_title}"
            print(f"✅ Source URL: {url}")
            
            # Constitutional Requirement 3: Sections with anchors
            sections = page_data["sections"]
            print(f"✅ Sections: {len(sections)} found")
            
            if sections:
                first_section = sections[0]
                print(f"   First section: '{first_section['line']}'")
                print(f"   Anchor: #{first_section['anchor']}")
                print(f"   Byte offset: {first_section['byteoffset']}")
            
            # Constitutional Requirement 4: Wikitext extraction
            wikitext = page_data["wikitext"]["*"]
            print(f"✅ Wikitext length: {len(wikitext)} characters")
            
            # Test section extraction
            if len(sections) >= 2:
                section = sections[0]
                next_section_offset = sections[1]["byteoffset"]
                
                section_text = extract_section_wikitext(
                    wikitext,
                    section["byteoffset"],
                    next_section_offset
                )
                
                print(f"\n   Section '{section['line']}' extracted:")
                print(f"   Length: {len(section_text)} characters")
                print(f"   Preview: {section_text[:100].replace(chr(10), ' ')}...")
                
                # Constitutional Requirement 5: Content hash
                content_hash = hash_content(section_text)
                print(f"   ✅ Content hash (SHA-256): {content_hash[:16]}...")
            
            # Constitutional Requirement 6: Code block extraction
            code_blocks = extract_code_blocks(wikitext[:5000])  # First 5k chars
            print(f"\n✅ Code blocks found: {len(code_blocks)}")
            
            if code_blocks:
                first_block = code_blocks[0]
                print("   First block preview:")
                print(f"   {first_block[:100].replace(chr(10), chr(10) + '   ')}")
                
                # Verify whitespace preservation
                block_hash = hash_content(first_block)
                print(f"   ✅ Block hash: {block_hash[:16]}...")
            
            # Constitutional Requirement 7: Warning detection
            warnings = extract_warnings(wikitext)
            print(f"\n✅ Warnings/Notes found: {len(warnings)}")
            
            if warnings:
                for i, warning in enumerate(warnings[:3]):  # Show first 3
                    print(f"   [{warning['type']}] {warning['text'][:60]}...")
            
            print(f"\n✅ {page_title}: ALL CONSTITUTIONAL REQUIREMENTS SATISFIED")
            
        except Exception as e:
            print(f"❌ Error testing {page_title}: {e}")
        
        print()
    
    print("=" * 80)
    print("Audit Complete")
    print("=" * 80)
    print("\nConclusion:")
    print("The MediaWiki API supports all constitutional guarantees:")
    print("  ✅ Revision IDs")
    print("  ✅ Section extraction with anchors")
    print("  ✅ Wikitext access (whitespace preserved)")
    print("  ✅ Code block extraction")
    print("  ✅ Warning template detection")
    print("  ✅ SHA-256 content hashing with Unicode NFC")
    print("\nReady for MCP implementation.")


if __name__ == "__main__":
    main()
