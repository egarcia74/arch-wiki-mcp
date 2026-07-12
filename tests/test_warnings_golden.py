"""
Golden tests for warning/note/tip extraction.

The consuming agent is required to surface these to the user before any related
command, so `message` must be readable prose. `message_raw` keeps the verbatim
template body, and `content_hash` covers the raw text so it stays greppable in
the wiki source.
"""

import re

import pytest

from conftest import load_wikitext
from arch_wiki_mcp import extractor

CORPUS = [
    "GRUB", "Installation_guide", "Iwd", "KDE",
    "Pacman", "Systemd", "Users_and_groups",
]


def all_warnings():
    for page in CORPUS:
        for block in extractor.parse_templates(load_wikitext(page)):
            yield page, block


def test_message_is_readable_prose():
    """The Iwd usage note, as an agent must quote it to a user."""
    warning = extractor.warnings("Iwd", "Usage")[0]

    assert warning["message"] == (
        "Only root and members of the network or the wheel user group are allowed "
        "to interact with iwd. In order to use iwctl or other front-ends, you need "
        "to add your user to one of those groups."
    )
    assert "{{ic|" in warning["message_raw"]
    assert "[[Users and groups#Group management|" in warning["message_raw"]


def test_hash_covers_the_verbatim_body():
    for warning in extractor.warnings("GRUB"):
        assert warning["content_hash"] == extractor.hash_content(warning["message_raw"])


def test_the_quoted_text_is_also_fingerprinted():
    """
    The agent is required to quote `message` to the user. It is a non-verbatim
    transform, so it must not be the one thing no hash attests -- the same
    argument that gives code blocks their content_hash_cleaned.
    """
    found = extractor.warnings("Iwd", "Usage")
    assert found
    for warning in found:
        assert warning["message_hash_cleaned"] == extractor.hash_content(warning["message"])
        assert warning["message_hash_cleaned"] != warning["content_hash"]


def test_no_wikitext_markup_survives_into_message():
    for page, block in all_warnings():
        for token in ("{{ic", "{{Pkg", "{{!}}", "{{=}}", "[[", "<nowiki", "<!--", "'''"):
            assert token not in block.message, f"{page}: {token} leaked into message"


def test_ordered_list_markers_never_look_like_a_root_prompt():
    """'#' starts an ordered list in wikitext. A bare '#' line reads as a shell prompt."""
    for page, block in all_warnings():
        for line in block.message.split("\n"):
            assert not line.startswith("#"), f"{page}: bare '#' line {line[:40]!r}"


def test_indented_code_inside_a_note_keeps_its_indentation():
    block = next(b for _, b in all_warnings() if "pacman -Fy" in b.message_raw)
    assert block.message.endswith(" # pacman -Fy")


def test_bullets_are_rendered():
    block = extractor.parse_templates("{{Note|* first\n* second}}")[0]
    assert block.message == "- first\n- second"


def test_ordered_lists_are_rendered():
    block = extractor.parse_templates("{{Note|# first\n# second}}")[0]
    assert block.message == "1. first\n1. second"


def test_indent_colons_are_dropped():
    block = extractor.parse_templates("{{Note|::* nested item}}")[0]
    assert block.message == "- nested item"


def test_pipe_inside_a_nested_template_does_not_truncate():
    """The naive split('|', 1) cut the message at the first pipe."""
    block = extractor.parse_templates("{{Warning|Run {{ic|pacman -Ql x {{!}} grep bin}} first}}")[0]
    assert block.message == "Run pacman -Ql x | grep bin first"
    assert block.type == "WARNING"


def test_pipe_inside_a_wikilink_does_not_truncate():
    block = extractor.parse_templates("{{Note|See [[Users and groups|the group page]] for more}}")[0]
    assert block.message == "See the group page for more"


def test_man_template_renders_as_page_and_section():
    block = extractor.parse_templates("{{Note|Consult {{man|8|ip-link}} for details}}")[0]
    assert block.message == "Consult ip-link(8) for details"


def test_external_link_keeps_its_url():
    block = extractor.parse_templates("{{Note|This is a [https://bugs.example/1 long open bug]}}")[0]
    assert block.message == "This is a long open bug (https://bugs.example/1)"


def test_named_parameter_body_is_unwrapped():
    block = extractor.parse_templates("{{Warning|1=Do not run rm -rf /}}")[0]
    assert block.message == "Do not run rm -rf /"


def test_a_body_that_opens_with_an_assignment_survives():
    block = extractor.parse_templates("{{Note|GRUB_ENABLE=y is required}}")[0]
    assert block.message == "GRUB_ENABLE=y is required"


def test_unsupported_templates_are_ignored():
    assert extractor.parse_templates("{{Merge|Other page}}{{Expansion}}") == []


@pytest.mark.parametrize("name", ["Warning", "Note", "Tip", "Caution", "WARNING", "note"])
def test_supported_types_are_case_insensitive(name):
    block = extractor.parse_templates("{{%s|body}}" % name)[0]
    assert block.type == name.upper()


def test_anchored_tools_parse_the_raw_slice_not_the_rendered_one():
    """
    warnings() and links() build on section(), and section().content is rendered:
    its {{Note|...}} templates and [[links]] are already resolved away. Feeding
    that back to a wikitext parser silently yields [] -- which this project's
    fail-closed contract tells the agent means "the wiki says nothing here".
    """
    anchored = extractor.warnings("Iwd", "Usage")
    assert len(anchored) == 1
    assert anchored[0]["type"] == "NOTE"

    assert extractor.links("GRUB", "Installation")


def skips_a_nesting_level(text):
    """A list may nest one level at a time; a jump means an item lost its indent."""
    bullet = re.compile(r"^(\s*)(?:- |1\. )")
    depths = [len(m.group(1)) for m in map(bullet.match, text.split("\n")) if m]
    return any(second - first > 2 for first, second in zip(depths, depths[1:]))


def test_a_nested_first_item_keeps_the_indent_its_siblings_have():
    """
    _clean_message ended in .strip(), eating the indent _render_list_markers had
    just generated for the first line. section() was fixed in 1.9; warnings()
    shares neither the code path nor, until now, the test. Found by driving the
    live server: the French Installation guide's {{Astuce}} rendered its first
    bullet flush left and its second four spaces in.

    The invariant is that siblings share a depth -- not that the depth is four
    spaces. This pinned "    - a", which is the orphan indent 1.13 removes.
    """
    assert extractor._clean_message("#** a\n#** b") == "- a\n- b"
    # The 1.10 regression itself: the first item must never sit shallower.
    assert extractor._clean_message("#** a\n#*** b") == "- a\n  - b"


def test_a_message_never_opens_indented():
    """
    Four leading spaces are a markdown code block. {{Tip|#** ...}} on the
    Installation guide takes its depth from a list outside the template, so the
    extracted tip had no parent and opened as a shell transcript -- in the field
    the contract requires an agent to quote. It sat in the fixtures all along.
    """
    for page in CORPUS + ["Installation guide (Français)"]:
        for warning in extractor.warnings(page):
            first = warning["message"].split("\n")[0]
            assert first == first.lstrip(" "), f"{page}: {warning['type']} opens indented"


def test_dedenting_never_flattens_real_nesting():
    """Only a *common* indent is removed, so relative depth survives."""
    assert extractor._clean_message("* top\n** nested") == "- top\n  - nested"
    assert extractor._clean_message("#** a\n#*** b\n#** c") == "- a\n  - b\n- c"
    assert extractor._clean_message("plain prose") == "plain prose"


def test_dedenting_never_touches_a_preformatted_line():
    """
    A space-prefixed line is preformatted code; its indent is the wiki's, not
    ours. Counting it toward the common indent measured 1 for
    "#** see:\\n # pacman -Fy", and shifting the block by it put a bare '#' at
    column 0 -- the root-prompt lookalike the whole rule exists to prevent, and
    a wrecked bullet besides. Raised by Codex on PR #12.

    Latent, not live: the corpus's preformatted warning lines (Pacman, GRUB,
    Users and groups) sit beside no list item, so the common indent was 0.
    """
    assert extractor._clean_message("#** see:\n # pacman -Fy") == "- see:\n # pacman -Fy"

    # The preformatted line neither sets the common indent nor receives the shift.
    assert extractor._clean_message("#** a\n # code\n#** b") == "- a\n # code\n- b"


def leading_whitespace(line):
    return line[: len(line) - len(line.lstrip(" \t"))]


def test_every_preformatted_line_in_the_corpus_keeps_its_indent():
    """
    Markup inside such a line is still resolved (''x'' -> x); only its
    indentation is content, and only that must survive byte-for-byte.
    """
    checked = 0
    for page in CORPUS + ["Installation guide (Français)"]:
        for warning in extractor.warnings(page):
            for source, rendered in zip(
                warning["message_raw"].split("\n"), warning["message"].split("\n")
            ):
                if extractor._is_preformatted(source):
                    checked += 1
                    assert leading_whitespace(rendered) == leading_whitespace(source), (
                        f"{page}: {source!r} -> {rendered!r}"
                    )
    assert checked >= 4, f"corpus should exercise preformatted lines, saw {checked}"


def test_a_leading_space_in_the_body_is_still_insignificant():
    """In {{Note| body}}, that leading space sits mid-line in the source and means nothing."""
    assert extractor._clean_message(" The iwd backend refuses.") == "The iwd backend refuses."


def test_no_warning_message_in_the_corpus_skips_a_nesting_level():
    for page in CORPUS + ["Installation guide (Français)"]:
        for warning in extractor.warnings(page):
            assert not skips_a_nesting_level(warning["message"]), f"{page}: {warning['type']}"
