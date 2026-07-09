"""
Golden tests for warning/note/tip extraction.

The consuming agent is required to surface these to the user before any related
command, so `message` must be readable prose. `message_raw` keeps the verbatim
template body, and `content_hash` covers the raw text so it stays greppable in
the wiki source.
"""

import pytest

from conftest import load_wikitext
from src import extractor

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
