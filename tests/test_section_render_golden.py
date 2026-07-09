"""
Golden tests for section rendering.

AGENTS.md Rule 4 routes the agent to section() precisely when commands() honestly
returns []: it must quote prose rather than infer a command. So section().content
is the one field the constitution *requires* an agent to show a user verbatim, and
it used to be raw wikitext -- where a numbered list item and a root shell prompt
are the same character.
"""

import re

import pytest

from conftest import load_wikitext
from src import extractor

PAGES = ["GRUB", "Installation_guide", "Iwd", "KDE", "Pacman", "Systemd", "Users_and_groups"]

# Every {{bc}} + {{hc}} in the corpus, per test_commands_golden.TEMPLATE_COUNTS.
TOTAL_CODE_TEMPLATES = 108

# Templates this renderer does not know. They survive VERBATIM rather than being
# dropped: markup an agent can see is honest, and deleting a sentence is
# synthesis by omission. This set is pinned so a newly-used template shows up as
# a red test rather than as silently lost content.
EXPECTED_RESIDUAL_TEMPLATES = {
    "app", "bug", "accuracy", "expansion", "merge", "out of date", "style", "dead link",
}

MARKDOWN_HEADING = re.compile(r"^#{2,6} \S")


def rendered_sections():
    for page in PAGES:
        for sect in extractor.sections(page):
            if not sect["anchor"]:
                continue
            yield page, sect["anchor"], extractor.section(page, sect["anchor"])


def outside_fence(content):
    """Yield the lines of `content` that are not inside a ``` fence."""
    in_fence = False
    for line in content.split("\n"):
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence:
            yield line


def test_no_rendered_line_looks_like_a_root_prompt():
    """
    The headline defect. '# Point the current boot device to the one which has
    the Arch Linux installation medium' is a numbered list item, not a command --
    it is the exact string that got examples() deleted, and section() still
    handed it to the agent under Rule 4.

    Outside a fence, a leading '#' may only ever begin a markdown heading.
    """
    offenders = [
        (page, anchor, line)
        for page, anchor, block in rendered_sections()
        for line in outside_fence(block.content)
        if line.startswith("#") and not MARKDOWN_HEADING.match(line)
    ]
    assert offenders == []


def test_wiki_ordered_lists_survive_as_ordered_lists():
    """Rendering must not simply delete the '#'; the steps are still steps."""
    content = extractor.section("Installation_guide", "Boot_the_live_environment").content
    assert "1. Point the current boot device" in content
    assert not extractor.commands("Installation_guide", "Boot_the_live_environment")


def test_every_code_template_becomes_a_balanced_fence():
    fences = 0
    for page, anchor, block in rendered_sections():
        markers = [line for line in block.content.split("\n") if line.startswith("```")]
        assert len(markers) % 2 == 0, f"{page}#{anchor}: unbalanced fence"
        fences += len(markers) // 2
    assert fences == TOTAL_CODE_TEMPLATES


def test_hc_header_is_never_a_bare_hash_line():
    """{{hc|# efibootmgr -u|...}}: the header is a command, and bare it is an H1."""
    content = extractor.section("GRUB", "GRUB_UEFI_not_loaded").content
    assert "`# efibootmgr -u`" in content
    assert "\n# efibootmgr -u" not in content


def test_a_midline_template_does_not_glue_its_fence_to_prose():
    """
    "...enabled. {{bc|# mount ...}} See the [[Gentoo:...]]" -- the trailing prose
    starts with a space. Split on the template span it reads as indented code, so
    its links never resolve and the fence markers land inside prose lines.
    """
    content = extractor.section("GRUB", "Common_installation_errors").content
    assert "\n```\n# mount -o remount,rw,nosuid,nodev,noexec" in content
    assert "\nSee the Gentoo Wiki on installing the boot loader." in content
    assert "[[Gentoo" not in content


def test_admonitions_render_as_labelled_prose():
    content = extractor.section("Iwd", "Usage").content
    assert content.count("**Note:**") == 1
    assert "Only root and members of the network or the wheel user group" in content
    assert "{{Note" not in content


def test_placeholders_are_marked_in_section_code_but_not_in_section_prose():
    """Same markup, two meanings: a substitution slot in code, emphasis in prose."""
    content = extractor.section("GRUB", "Installation").content
    assert "--efi-directory=<esp>" in content          # inside a fence: code
    assert "substitute esp with its mount point" in content  # prose: plain emphasis


def test_no_resolvable_markup_survives_rendering():
    for page, anchor, block in rendered_sections():
        content = block.content
        assert "''" not in content, f"{page}#{anchor}"
        assert "[[" not in content, f"{page}#{anchor}"
        assert "\x00" not in content, f"{page}#{anchor}: sentinel leaked"
        for name in ("ic", "Pkg", "AUR", "Note", "Warning", "Tip", "bc", "hc"):
            assert "{{" + name not in content, f"{page}#{anchor}: {{{{{name}}}}} left raw"


def test_unknown_templates_are_left_verbatim_not_dropped():
    """
    A renderer that silently swallowed {{Accuracy|...}} would be deleting the
    wiki's own caveat. Seeing raw markup is the honest failure.
    """
    seen = set()
    for _, _, block in rendered_sections():
        for match in re.finditer(r"\{\{\s*([A-Za-z0-9_ :-]+?)\s*[|}]", block.content):
            seen.add(match.group(1).strip().lower())
    assert seen == EXPECTED_RESIDUAL_TEMPLATES


def test_content_raw_stays_the_verbatim_slice_the_hash_attests():
    for page, anchor, block in rendered_sections():
        assert block.content_raw.startswith("=")
        assert block.content_raw in load_wikitext(page)
        assert block.content_hash == extractor.hash_content(block.content_raw)
        assert block.content_hash_cleaned == extractor.hash_content(block.content)


def test_rendering_is_deterministic():
    first = extractor.section("GRUB", "Installation")
    second = extractor.section("GRUB", "Installation")
    assert first.content == second.content
    assert first.content_hash_cleaned == second.content_hash_cleaned


@pytest.mark.parametrize(
    "wikitext,expected",
    [
        ("== T ==\n# step one", "## T\n1. step one"),
        ("== T ==\n* bullet", "## T\n- bullet"),
        # A wikilink whose display text contains brackets: ']]]' is ']' + ']]'.
        ("see [[#General options|[options]]]", "see [options]"),
        ("====== Deep ======", "###### Deep"),
        ("{{bc|echo hi}}", "```\necho hi\n```"),
        ("{{hc|/etc/f|body}}", "`/etc/f`\n```\nbody\n```"),
        ("{{Note|be careful}}", "**Note:** be careful"),
        ("{{Warning|''this'' breaks}}", "**Warning:** this breaks"),
        ("{{Tip|use {{ic|pacman}}}}", "**Tip:** use pacman"),
        # A note whose body is a list must not glue the first bullet to the label.
        ("{{Note|\n* one\n* two\n}}", "**Note:**\n- one\n- two"),
        # ...nor one whose body is code.
        ("{{Note|{{bc|echo hi}}}}", "**Note:**\n```\necho hi\n```"),
    ],
)
def test_render_unit_cases(wikitext, expected):
    assert extractor.render_section_wikitext(wikitext) == expected
