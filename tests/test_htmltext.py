"""HTML タグの除去."""

from __future__ import annotations

from selfocr.htmltext import strip_html_tags

TABLE = """<table>
<tr><th>Name</th><th>Qty</th></tr>
<tr><td>Apple</td><td>3</td></tr>
</table>"""


def test_strip_table():
    assert strip_html_tags(TABLE) == "Name Qty\nApple 3"


def test_strip_keeps_surrounding_text():
    text = "前の段落\n\n" + TABLE + "\n\n次の段落"
    assert strip_html_tags(text) == "前の段落\n\nName Qty\nApple 3\n\n次の段落"


def test_strip_keeps_plain_text():
    text = "# 見出し\n\n普通の文章です. a < b, 100 < 200"
    assert strip_html_tags(text) == text


def test_strip_decodes_entities():
    assert strip_html_tags("<td>A &amp; B</td>") == "A & B"


def test_strip_keeps_unknown_tags():
    assert strip_html_tags("x <y> z") == "x <y> z"


def test_strip_breaks():
    assert strip_html_tags("a<br>b") == "a\nb"


def test_strip_empty():
    assert strip_html_tags("") == ""
