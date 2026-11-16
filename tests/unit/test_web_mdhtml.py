"""Web 层 Markdown 渲染器的安全与语法覆盖测试。"""

from __future__ import annotations

from aipulse.web.mdhtml import render_md


def test_headings_lists_tables_and_blockquotes():
    md = "# 标题\n\n> ### 引用标题\n>\n> 1. **一**\n\n- 项目\n\n| A | B |\n|---|---|\n| 1 | 2 |\n"
    html = render_md(md)
    assert "<h1>标题</h1>" in html
    assert "<blockquote>" in html and "<h3>引用标题</h3>" in html
    assert "<ol><li><strong>一</strong></li></ol>" in html
    assert "<ul><li>项目</li></ul>" in html
    assert "<table>" in html and "<th>A</th>" in html and "<td>2</td>" in html


def test_raw_html_is_escaped_except_whitelist():
    md = "<script>alert(1)</script>\n\n<details>\n<summary>展开</summary>\n\n- 内容\n</details>\n"
    html = render_md(md)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "<details>" in html and "<summary>展开</summary>" in html
    assert "<li>内容</li>" in html


def test_dangerous_links_are_downgraded_to_text():
    md = "[x](javascript:alert(1)) [y](data:text/html;base64,xx) [ok](https://example.com)\n"
    html = render_md(md)
    assert "javascript" not in html
    assert "data:text" not in html
    assert 'href="https://example.com"' in html


def test_truncates_large_input():
    html = render_md("a" * 100, max_bytes=10)
    assert len(html) < 100
    assert html.startswith("<p>")
