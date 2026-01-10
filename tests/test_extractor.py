"""
Hash Stability Regression Test
Tests constitutional requirement: hash determinism for same revid
"""

import json
import sys
sys.path.insert(0, '..')
from src.extractor import page, section, commands, warnings, links, hash_content

def test_hash_stability():
    """
    Regression test: Fetch GRUB twice, verify identical hashes for same revid.
    
    Constitutional requirement: Hash must be stable for identical revid.
    """
    print("=" * 80)
    print("Hash Stability Regression Test")
    print("=" * 80)
    print()
    
    # Test 1: Full page hash stability
    print("Test 1: Full page hash stability")
    print("-" * 80)
    
    page1 = page("GRUB")
    page2 = page("GRUB")
    
    assert page1["revid"] == page2["revid"], "Revids must match for same page"
    assert page1["wikitext_hash"] == page2["wikitext_hash"], "Page hash must be stable"
    
    print(f"✅ Page revid: {page1['revid']}")
    print(f"✅ Page hash: {page1['wikitext_hash'][:16]}...")
    print("✅ Hash stable across two fetches")
    print()
    
    # Test 2: Section hash stability
    print("Test 2: Section hash stability")
    print("-" * 80)
    
    sect1 = section("GRUB", "Installation")
    sect2 = section("GRUB", "Installation")
    
    assert sect1.revid == sect2.revid, "Revids must match"
    assert sect1.content_hash == sect2.content_hash, "Section hash must be stable"
    
    print(f"✅ Section revid: {sect1.revid}")
    print(f"✅ Section: {sect1.section_heading}")
    print(f"✅ Section hash: {sect1.content_hash[:16]}...")
    print("✅ Hash stable across two fetches")
    print()
    
    # Test 3: Code block hash stability
    print("Test 3: Code block hash stability")
    print("-" * 80)
    
    cmds1 = commands("GRUB", "Installation")
    cmds2 = commands("GRUB", "Installation")
    
    assert len(cmds1) == len(cmds2), "Same number of code blocks must be extracted"
    
    if cmds1:
        for i, (c1, c2) in enumerate(zip(cmds1, cmds2)):
            assert c1["content_hash"] == c2["content_hash"], \
                f"Code block {i} hash must be stable"
        
        print(f"✅ Code blocks found: {len(cmds1)}")
        print(f"✅ First block hash: {cmds1[0]['content_hash'][:16]}...")
        print(f"✅ All block hashes stable across two fetches")
    else:
        print("⚠️  No code blocks found in Installation section")
    print()
    
    # Test 4: Warning hash stability
    print("Test 4: Warning hash stability")
    print("-" * 80)
    
    warns1 = warnings("GRUB", "Installation")
    warns2 = warnings("GRUB", "Installation")
    
    assert len(warns1) == len(warns2), "Same number of warnings must be extracted"
    
    if warns1:
        for i, (w1, w2) in enumerate(zip(warns1, warns2)):
            assert w1["content_hash"] == w2["content_hash"], \
                f"Warning {i} hash must be stable"
        
        print(f"✅ Warnings found: {len(warns1)}")
        print(f"✅ First warning type: {warns1[0]['type']}")
        print(f"✅ First warning hash: {warns1[0]['content_hash'][:16]}...")
        print(f"✅ All warning hashes stable across two fetches")
    else:
        print("⚠️  No warnings found in Installation section")
    print()
    
    # Test 5: Link extraction consistency
    print("Test 5: Link extraction consistency")
    print("-" * 80)
    
    links1 = links("GRUB", "Installation")
    links2 = links("GRUB", "Installation")
    
    assert len(links1) == len(links2), "Same number of links must be extracted"
    
    if links1:
        for i, (l1, l2) in enumerate(zip(links1, links2)):
            assert l1["target_page"] == l2["target_page"], \
                f"Link {i} target must be stable"
        
        print(f"✅ Links found: {len(links1)}")
        print(f"✅ First link: [[{links1[0]['target_page']}]]")
        print(f"✅ All links stable across two fetches")
    else:
        print("⚠️  No links found in Installation section")
    print()
    
    print("=" * 80)
    print("VERDICT: Hash stability proven for same revid")
    print("=" * 80)
    print()
    print("Constitutional requirement satisfied:")
    print("  ✅ Page-level hashes are deterministic")
    print("  ✅ Section-level hashes are deterministic")
    print("  ✅ Code block hashes are deterministic")
    print("  ✅ Warning hashes are deterministic")
    print("  ✅ Link extraction is deterministic")
    print()
    print("Forensically sound extraction confirmed.")


def test_representative_pages():
    """
    Test extraction on representative pages: GRUB, Installation Guide, Pacman.
    """
    print("\n" + "=" * 80)
    print("Representative Page Test")
    print("=" * 80)
    print()
    
    test_pages = [
        ("GRUB", "Installation"),
        ("Installation_guide", "Pre-installation"),
        ("Pacman", "Usage")
    ]
    
    for page_title, section_anchor in test_pages:
        print(f"Testing: {page_title} § {section_anchor}")
        print("-" * 80)
        
        try:
            # Extract section
            sect = section(page_title, section_anchor)
            print(f"✅ Section extracted: {sect.section_heading}")
            print(f"   Revid: {sect.revid}")
            print(f"   Hash: {sect.content_hash[:16]}...")
            print(f"   Length: {len(sect.content)} chars")
            
            # Extract commands
            cmds = commands(page_title, section_anchor)
            print(f"✅ Code blocks: {len(cmds)}")
            
            # Extract warnings
            warns = warnings(page_title, section_anchor)
            print(f"✅ Warnings: {len(warns)}")
            
            # Extract links
            lnks = links(page_title, section_anchor)
            print(f"✅ Links: {len(lnks)}")
            
        except Exception as e:
            print(f"❌ Error: {e}")
        
        print()
    
    print("=" * 80)
    print("Representative page extraction complete")
    print("=" * 80)


if __name__ == "__main__":
    test_hash_stability()
    test_representative_pages()
