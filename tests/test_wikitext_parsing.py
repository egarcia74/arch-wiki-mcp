"""
Unit tests for the wikitext primitives.

The recorded corpus happens to contain no {{{triple braces}}}, so the brace
matcher's handling of them is exercised here rather than by a golden test.
"""

import pytest

from src import extractor


def find_end(text):
    return extractor._find_template_end(text, text.index("{{"))


def test_find_template_end_simple():
    assert find_end("{{bc|x}}") == 8


def test_find_template_end_nested():
    text = "{{bc|a{{ic|b}}c}}tail"
    assert text[: find_end(text)] == "{{bc|a{{ic|b}}c}}"


def test_find_template_end_handles_escape_template():
    text = "{{bc|DRI_PRIME{{=}}1}}"
    assert find_end(text) == len(text)


def test_find_template_end_handles_triple_braces():
    """A 2-char scan reads {{{ as '{{' + '{' and miscounts depth."""
    text = "{{bc|{{{1|default}}}}}"
    assert find_end(text) == len(text)


def test_find_template_end_closes_nested_template_at_a_shared_tail():
    """
    '{{App|x|{{Pkg|y}}}}' ends in '}}}}'. Reading the first three as a parameter
    close leaves the template unterminated, and it survives as raw markup.
    """
    text = "{{Pkg|impala}}}}"
    assert text[: find_end(text)] == "{{Pkg|impala}}"


def test_find_template_end_treats_a_literal_brace_as_content():
    """'{{ic|menuentry {opts}}}': the '}}}' here is '}' + '}}', not a parameter."""
    text = '{{ic|menuentry "title" {entry options}}}'
    assert find_end(text) == len(text)


def test_a_literal_brace_body_resolves_whole():
    content, _ = extractor._clean_payload('{{ic|menuentry "title" {entry options}}}')
    assert content == 'menuentry "title" {entry options}'


def test_nested_template_inside_an_unknown_one_still_resolves():
    text, _ = extractor._strip_inline_markup("{{App|impala|A TUI.|https://x|{{Pkg|impala}}}}")
    assert text == "{{App|impala|A TUI.|https://x|impala}}"


def test_find_template_end_handles_a_wikitable_body():
    text = "{{Note|{|class=x\n|a\n|}}}"
    assert find_end(text) == len(text)


def test_find_template_end_unclosed_returns_minus_one():
    assert extractor._find_template_end("{{bc|never closed", 0) == -1


def test_split_respects_max_splits():
    assert extractor._split_template_params("bc|a | b | c", 1) == ["bc", "a | b | c"]
    assert extractor._split_template_params("hc|f|a|b", 2) == ["hc", "f", "a|b"]


def test_split_ignores_pipes_inside_nested_structures():
    assert extractor._split_template_params("hc|{{ic|x}}|body", 2) == ["hc", "{{ic|x}}", "body"]
    assert extractor._split_template_params("hc|[[A|B]]|body", 2) == ["hc", "[[A|B]]", "body"]


def test_strip_param_name_only_strips_known_names():
    assert extractor._strip_param_name("1=body", {"1"}) == "body"
    assert extractor._strip_param_name("output=body", {"2", "output"}) == "body"
    # A body that legitimately opens with an assignment must survive intact.
    assert extractor._strip_param_name("GRUB_ENABLE=y", {"1"}) == "GRUB_ENABLE=y"


def test_clean_payload_marks_placeholders_and_strips_emphasis():
    content, placeholders = extractor._clean_payload("# mount ''device'' '''--verbose'''")
    assert content == "# mount <device> --verbose"
    assert placeholders == ["device"]  # bold is emphasis, not a placeholder


def test_prose_italics_are_emphasis_not_placeholders():
    """The same markup means 'substitute me' in code and nothing in prose."""
    block = extractor.parse_templates("{{Note|Only ''root'' may run ''iwctl''}}")[0]
    assert block.message == "Only root may run iwctl"
    assert "<root>" not in block.message


def test_a_marked_placeholder_is_not_silently_runnable():
    """`<esp>` is shell redirection: a literal paste fails instead of acting wrongly."""
    content, _ = extractor._clean_payload("# grub-install --efi-directory=''esp''")
    assert "<esp>" in content
    assert "=esp" not in content


def test_clean_payload_resolves_escape_and_inline_code():
    content, _ = extractor._clean_payload("{{ic|pacman}} -S x{{=}}y")
    assert content == "pacman -S x=y"


def test_clean_payload_drops_nowiki_wrapper():
    content, _ = extractor._clean_payload("<nowiki>\na | b\n</nowiki>")
    assert content == "a | b"


def test_clean_payload_dedupes_placeholders():
    _, placeholders = extractor._clean_payload("cp ''src'' ''dst'' ''src''")
    assert placeholders == ["src", "dst"]


def test_nowiki_protects_its_payload_from_every_pass():
    """
    <nowiki> is a strip marker: MediaWiki expands nothing inside it. We deleted
    the comments, dropped the tags, and then expanded the templates the tags were
    protecting -- so the wiki's literal text became our rendered text.
    """
    render = extractor.render_section_wikitext

    # The Help:Style case: the wiki displays the literal template call.
    assert render("resort to {{ic|<nowiki>{{ic|text}}</nowiki>}}.") == "resort to {{ic|text}}."
    # A wikilink inside nowiki is text, not a link.
    assert render("see {{ic|<nowiki>[[Foo|bar]]</nowiki>}}.") == "see [[Foo|bar]]."
    # Italics inside nowiki are apostrophes, not emphasis.
    assert render("type {{ic|<nowiki>''x''</nowiki>}}.") == "type ''x''."


def test_an_html_comment_inside_nowiki_is_displayed_not_deleted():
    """
    Iwd's dbus config carries two comment lines. The wiki renders them; we
    deleted them from commands().content while content_hash went on attesting
    content_raw, which still had them. The user pasted a file the wiki never
    showed -- synthesis by omission in the one field meant to be runnable.
    """
    content, _ = extractor._clean_payload("<nowiki><!-- keep me -->\nbody\n</nowiki>")
    assert content == "<!-- keep me -->\nbody"


def test_an_html_comment_outside_nowiki_is_still_removed():
    """MediaWiki's preprocessor strips these before anything sees them."""
    assert extractor.render_section_wikitext("Text <!-- hidden --> more.") == "Text  more."


def test_italics_inside_nowiki_are_not_placeholders():
    """
    A placeholder is a value the reader substitutes. ''x'' inside nowiki is two
    apostrophes the wiki prints, and promoting it to <x> would invent a slot.
    """
    content, placeholders = extractor._clean_payload("run <nowiki>''x''</nowiki> ''real''")
    assert placeholders == ["real"]
    assert "''x''" in content and "<real>" in content


def test_a_stray_unpaired_nowiki_tag_is_still_dropped():
    content, _ = extractor._clean_payload("a </nowiki> b")
    assert content == "a  b"


# ---------------------------------------------------------------------------
# <nowiki> must be invisible to every SCANNER, not merely to the cleaners.
#
# Protecting the payload after extraction is too late: by then the scanner has
# already found a {{bc}} in a page that was documenting template syntax, and
# handed it back as a command carrying a hash. Raised by Codex on PR #11.
# ---------------------------------------------------------------------------

def test_a_quoted_code_template_is_not_a_command():
    """Help:Style quotes {{bc|...}} to teach syntax. It is prose, not a command."""
    assert extractor.parse_code_blocks("Before <nowiki>{{bc|echo hi}}</nowiki> after", revid=1) == []


def test_a_quoted_admonition_is_not_a_warning():
    """
    The most dangerous version. A page documenting {{Warning|...}} would have
    produced a WARNING the article never issued -- a fabricated safety claim,
    attested by a hash, on a page that merely quotes the template.
    """
    assert extractor.parse_templates("Docs: <nowiki>{{Warning|rm -rf /}}</nowiki>", revid=1) == []


def test_a_quoted_wikilink_is_not_a_link():
    links = extractor.parse_internal_links("See <nowiki>[[Foo|bar]]</nowiki>", "X", frozenset())
    assert links == []


def test_a_quoted_template_renders_as_the_literal_text_the_wiki_shows():
    rendered = extractor.render_section_wikitext("Before <nowiki>{{bc|echo hi}}</nowiki> after")
    assert rendered == "Before {{bc|echo hi}} after"
    assert "```" not in rendered, "a quoted template must not become a fenced block"


def test_an_indented_line_inside_nowiki_is_not_a_code_block():
    """<nowiki> disables wikitext interpretation, preformatted lines included."""
    assert extractor.parse_code_blocks("<nowiki>\n echo hi\n</nowiki>", revid=1) == []


def test_a_quoted_template_name_is_never_sent_to_the_wiki_as_a_title():
    """admonition_types() would have queried Template:Attention for a page quoting it."""
    types = extractor.admonition_types(
        "<nowiki>{{Attention|x}}</nowiki> {{Note|real}}", "unused-no-fixture-needed"
    )
    assert types == {"note": extractor.TemplateResolution(type="NOTE")}


def test_real_templates_still_extract_alongside_quoted_ones():
    """The mask must not swallow the page's actual content."""
    wikitext = "{{bc|real}} and <nowiki>{{bc|quoted}}</nowiki>"
    blocks = extractor.parse_code_blocks(wikitext, revid=1)
    assert [b.content for b in blocks] == ["real"]

    warnings = extractor.parse_templates("{{Warning|real}} <nowiki>{{Warning|quoted}}</nowiki>", revid=1)
    assert [w.message for w in warnings] == ["real"]


def test_a_nowiki_inside_a_template_body_is_still_the_bodys_business():
    """Masking is top-level only; _clean_payload protects what is nested."""
    blocks = extractor.parse_code_blocks("{{bc|<nowiki>{{ic|x}}</nowiki>}}", revid=1)
    assert [b.content for b in blocks] == ["{{ic|x}}"]


@pytest.mark.parametrize(
    "wikitext,expected_type,expected_header",
    [
        ("{{bc|echo hi}}", "block_code", None),
        ("{{bc|1=echo hi}}", "block_code", None),
        ("{{hc|/etc/f|body}}", "file_content", "/etc/f"),
        ("{{hc|/etc/f|2=body}}", "file_content", "/etc/f"),
        ("{{hc|1=$ cmd|2=body}}", "file_content", "$ cmd"),
        ("{{hc|/etc/f|output=body}}", "file_content", "/etc/f"),
    ],
)
def test_all_six_parameter_forms(wikitext, expected_type, expected_header):
    blocks = extractor.parse_code_blocks(wikitext)
    assert len(blocks) == 1
    assert blocks[0].block_type == expected_type
    assert blocks[0].header == expected_header
    assert blocks[0].content in ("echo hi", "body")
