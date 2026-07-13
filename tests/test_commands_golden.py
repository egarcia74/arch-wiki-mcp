"""
Golden tests for command extraction.

Arch Wiki code lives in {{bc}} (block code) and {{hc}} (file contents with a
header), not in <pre>/<code> tags. Counts below were measured against the
committed fixtures; they are the contract commands() must satisfy.
"""

import pytest

from conftest import GRUB_REVID, load_wikitext
from arch_wiki_mcp import extractor

# (page, {{bc}} blocks, {{hc}} blocks, indented blocks)
#
# Indented counts exclude space-prefixed lines that sit *inside* a {{bc}}/{{hc}}
# body -- those spans are masked before the indented scan, so a template body is
# never also emitted as a separate preformatted block.
TEMPLATE_COUNTS = [
    ("GRUB", 17, 8, 35),
    ("Installation_guide", 2, 3, 22),
    ("Iwd", 0, 28, 26),
    ("KDE", 6, 19, 28),
    ("Pacman", 0, 1, 61),
    ("Systemd", 1, 18, 16),
    ("Users_and_groups", 0, 5, 31),
]

TOTAL_BC = sum(row[1] for row in TEMPLATE_COUNTS)
TOTAL_HC = sum(row[2] for row in TEMPLATE_COUNTS)


@pytest.mark.parametrize("page,n_bc,n_hc,n_indented", TEMPLATE_COUNTS)
def test_every_template_block_is_extracted(page, n_bc, n_hc, n_indented):
    blocks = extractor.parse_code_blocks(load_wikitext(page))
    by_pattern = {}
    for block in blocks:
        by_pattern.setdefault(block.source_pattern, []).append(block)

    assert len(by_pattern.get("template_bc", [])) == n_bc
    assert len(by_pattern.get("template_hc", [])) == n_hc
    assert len(by_pattern.get("indented_block", [])) == n_indented


def test_corpus_template_totals_are_unchanged():
    """Tripwire on TEMPLATE_COUNTS itself: extraction once recovered 7 of these 108."""
    assert (TOTAL_BC, TOTAL_HC) == (26, 82)


def test_bc_block_is_cleaned_and_traceable():
    """The canonical GRUB EFI install command, verbatim and cleaned."""
    blocks = extractor.commands("GRUB", "Installation")
    match = [b for b in blocks if "--bootloader-id=GRUB" in b["content"] and b["source_pattern"] == "template_bc"]
    assert len(match) == 1
    block = match[0]

    assert block["content"] == (
        "# grub-install --target=x86_64-efi --efi-directory=<esp> --bootloader-id=GRUB"
    )
    assert block["content_raw"] == (
        "# grub-install --target=x86_64-efi --efi-directory=''esp'' --bootloader-id=GRUB"
    )
    assert block["placeholders"] == ["esp"]
    assert block["block_type"] == "block_code"
    assert block["header"] is None
    assert block["revid"] == GRUB_REVID
    assert block["source_url"] == "https://wiki.archlinux.org/title/GRUB#Installation"


def test_content_hash_is_over_raw_not_cleaned():
    """Hashes must stay falsifiable by grepping the wiki source."""
    for block in extractor.commands("GRUB"):
        assert block["content_hash"] == extractor.hash_content(block["content_raw"])


def test_the_executed_text_is_also_fingerprinted():
    """
    An agent runs `content`, not `content_raw`. The cleaning step is the one
    non-verbatim transform in the chain, so it must not be the one step no hash
    attests.
    """
    for block in extractor.commands("GRUB"):
        assert block["content_hash_cleaned"] == extractor.hash_content(block["content"])

    cleaned = [b for b in extractor.commands("GRUB") if b["placeholders"]]
    assert cleaned, "expected at least one block whose cleaning changed the text"
    for block in cleaned:
        assert block["content_hash_cleaned"] != block["content_hash"]


def test_hc_block_exposes_its_header():
    """{{hc|/etc/default/grub|output=...}} — the 'output=' body alias."""
    blocks = extractor.commands("GRUB")
    match = [
        b for b in blocks
        if b["source_pattern"] == "template_hc" and "GRUB_ENABLE_CRYPTODISK=y" in b["content"]
    ]
    assert len(match) == 1
    assert match[0]["header"] == "/etc/default/grub"
    assert match[0]["block_type"] == "file_content"
    assert match[0]["content"].strip() == "GRUB_ENABLE_CRYPTODISK=y"


def test_shell_pipe_in_positional_param_is_not_a_separator():
    """{{bc|DRI_PRIME{{=}}1 glxinfo | grep "OpenGL renderer"}} — the pipe is shell, not wikitext.

    {{=}} is the MediaWiki escape for a literal '=' and must resolve.
    """
    blocks = extractor.parse_code_blocks(load_wikitext("KDE"))
    match = [b for b in blocks if "glxinfo" in b.content]
    assert len(match) == 1
    assert match[0].content == 'DRI_PRIME=1 glxinfo | grep "OpenGL renderer"'


def test_hc_body_keeps_piped_shell_and_drops_nowiki():
    """A {{hc}} body wrapping <nowiki> with sed pipes must survive intact."""
    blocks = extractor.parse_code_blocks(load_wikitext("KDE"))
    match = [b for b in blocks if b.header == "/usr/local/bin/kde-no-shadow"]
    assert len(match) == 1
    assert "xwininfo -root -tree | sed" in match[0].content
    assert "<nowiki>" not in match[0].content
    assert match[0].content.startswith("#!/bin/bash")


def test_inline_ic_never_becomes_a_command():
    """{{ic}} is inline markup (paths, flags, package names), not a command."""
    blocks = extractor.parse_code_blocks(load_wikitext("Pacman"))
    assert all(b.source_pattern != "template_ic" for b in blocks)
    # Pacman has 180 {{ic}} spans and exactly one {{hc}}; nothing should explode.
    assert len([b for b in blocks if b.source_pattern == "template_hc"]) == 1


def test_every_placeholder_is_marked_in_the_content_it_appears_in():
    """
    116 of the 327 blocks on these seven pages carry placeholders. A bare `esp`
    looks runnable and is not; the marker makes a literal paste fail at the shell
    rather than act on the wrong path.
    """
    marked = 0
    for page, _, _, _ in TEMPLATE_COUNTS:
        for block in extractor.parse_code_blocks(load_wikitext(page)):
            if not block.placeholders:
                continue
            marked += 1
            for token in block.placeholders:
                assert f"<{token}>" in block.content, f"{page}: {token} left bare"
    assert marked == 116


def test_marking_only_affects_blocks_that_have_placeholders():
    """
    A block the wiki never italicised must come out byte-identical to before.

    The reference must protect <nowiki> the same way _clean_payload does. It once
    called _strip_inline_markup on the raw payload directly, so both sides deleted
    the HTML comments inside Iwd's dbus config and the assertion passed while
    commands().content silently dropped two lines the wiki displays.
    """
    for page, _, _, _ in TEMPLATE_COUNTS:
        for block in extractor.parse_code_blocks(load_wikitext(page)):
            if block.placeholders:
                continue
            hidden, protected = extractor._hide_nowiki(block.content_raw)
            unmarked, _ = extractor._strip_inline_markup(hidden)
            assert block.content == extractor._restore_nowiki(unmarked, protected).strip("\n")


def test_no_wikitext_markup_leaks_into_content():
    for page, _, _, _ in TEMPLATE_COUNTS:
        for block in extractor.parse_code_blocks(load_wikitext(page)):
            assert "''" not in block.content
            assert "{{ic" not in block.content


def test_template_bodies_are_not_also_emitted_as_indented_blocks():
    """
    49 space-prefixed lines live inside {{bc}}/{{hc}} bodies across the corpus.
    Without masking the consumed spans, each is re-emitted as a phantom
    indented_block duplicating code already returned by its template.
    """
    blocks = extractor.parse_code_blocks(load_wikitext("KDE"))
    indented = [b.content for b in blocks if b.source_pattern == "indented_block"]

    # This script body sits inside {{hc|/usr/local/bin/kde-no-shadow|<nowiki>...}}
    # and is indented; it must be attributed to the template, never to a bare block.
    assert any("xwininfo" in b.content for b in blocks if b.source_pattern == "template_hc")
    assert not any("xwininfo" in block for block in indented)


def test_extraction_is_deterministic():
    first = extractor.commands("GRUB", "Installation")
    second = extractor.commands("GRUB", "Installation")
    assert [b["content_hash"] for b in first] == [b["content_hash"] for b in second]


EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


@pytest.mark.parametrize("wikitext", ["{{bc}}", "{{bc|}}", "{{bc|1=}}", "{{hc|/etc/f|}}"])
def test_a_bodiless_code_template_is_not_a_command(wikitext):
    """
    An empty block used to come back with content "" and content_hash set to the
    SHA-256 of the empty string -- evidence for nothing, carrying a hash that
    verifies against nothing, which an agent is obliged to present as a command.
    The wiki specifies no command here, and [] is how this MCP says so.
    """
    assert extractor.parse_code_blocks(wikitext, revid=1) == []


def test_the_empty_hash_never_reaches_a_caller():
    """The constant above is real: it is what the old code emitted."""
    assert extractor.hash_content("") == EMPTY_SHA256
    for page, _, _, _ in TEMPLATE_COUNTS:
        for block in extractor.parse_code_blocks(load_wikitext(page)):
            assert block.content_hash != EMPTY_SHA256
            assert block.content.strip()
