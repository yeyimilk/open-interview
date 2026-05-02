from openinterview_core.domain.messengers.plugins.whatsapp.formatter import (
    to_whatsapp,
)


def test_double_asterisk_bold_to_single():
    assert to_whatsapp("Hello **world**") == "Hello *world*"


def test_double_underscore_bold_to_single():
    assert to_whatsapp("Hello __world__") == "Hello *world*"


def test_headings_become_bold():
    out = to_whatsapp("# Title\n\nbody")
    assert out.startswith("*Title*")
    assert "body" in out


def test_multiple_heading_levels():
    out = to_whatsapp("## H2\n### H3 ###")
    assert "*H2*" in out
    assert "*H3*" in out


def test_link_with_label():
    assert to_whatsapp("[docs](https://example.com)") == "docs: https://example.com"


def test_link_label_equals_url():
    assert to_whatsapp("[https://x.io](https://x.io)") == "https://x.io"


def test_image_collapsed_to_url():
    assert to_whatsapp("![alt](https://img.example.com/a.png)") == "https://img.example.com/a.png"


def test_horizontal_rule_removed():
    out = to_whatsapp("a\n\n---\n\nb")
    assert "---" not in out
    assert "a" in out and "b" in out


def test_bullets_converted_to_dot():
    out = to_whatsapp("- one\n- two\n* three")
    assert "• one" in out
    assert "• two" in out
    assert "• three" in out


def test_bullet_does_not_eat_bold_marker():
    out = to_whatsapp("*bold*")
    assert out == "*bold*"


def test_table_flattened():
    md = "| Col A | Col B |\n| --- | --- |\n| 1 | 2 |"
    out = to_whatsapp(md)
    assert "Col A | Col B" in out
    assert "1 | 2" in out
    assert "---" not in out


def test_code_fence_preserved():
    md = "before\n```\ncode **kept**\n```\nafter"
    out = to_whatsapp(md)
    assert "```\ncode **kept**\n```" in out


def test_blockquote_normalised():
    assert to_whatsapp("> hi") == "> hi"


def test_collapses_excess_blank_lines():
    out = to_whatsapp("a\n\n\n\nb")
    assert out == "a\n\nb"


def test_empty_input():
    assert to_whatsapp("") == ""


def test_combined_real_response():
    md = (
        "## Recap\n\n"
        "**Great answer!** Next question:\n\n"
        "- Explain **CAP theorem**\n"
        "- Reference: [wiki](https://en.wikipedia.org/wiki/CAP_theorem)\n\n"
        "---\n\n"
        "Take your time."
    )
    out = to_whatsapp(md)
    assert "*Recap*" in out
    assert "*Great answer!*" in out
    assert "*CAP theorem*" in out
    assert "wiki: https://en.wikipedia.org/wiki/CAP_theorem" in out
    assert "• Explain" in out
    assert "---" not in out
