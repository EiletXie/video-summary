import re

CSS = """
body {
    font-family: "PingFang SC", "Microsoft YaHei", "Helvetica Neue", sans-serif;
    max-width: 800px;
    margin: 40px auto;
    padding: 0 20px;
    line-height: 1.8;
    color: #1a1a1a;
    background: #fff;
}
.meta {
    color: #888;
    font-size: 14px;
    margin-bottom: 24px;
    padding-bottom: 16px;
    border-bottom: 1px solid #eee;
}
.meta span { margin-right: 20px; }
h1 { font-size: 24px; font-weight: 600; margin-bottom: 8px; }
h2 { font-size: 18px; font-weight: 600; margin-top: 32px; color: #2563EB; }
h3 { font-size: 16px; font-weight: 600; margin-top: 24px; }
p { margin: 12px 0; }
ul, ol { margin: 12px 0; padding-left: 24px; }
li { margin: 4px 0; }
strong { color: #1a1a1a; }
blockquote {
    border-left: 3px solid #2563EB;
    padding: 8px 16px;
    margin: 16px 0;
    color: #555;
    background: #f8f9fa;
}
.content { white-space: pre-wrap; word-break: break-word; }
.badge {
    display: inline-block;
    padding: 2px 10px;
    border-radius: 12px;
    font-size: 12px;
    background: #e8f0fe;
    color: #2563EB;
}
"""


def render_original(title: str, platform: str, url: str, text: str) -> str:
    html_text = _markdown_to_html(text)
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{_esc(title)} - 原文</title>
<style>{CSS}</style>
</head>
<body>
<h1>{_esc(title)}（原文）</h1>
<div class="meta">
    <span class="badge">{platform}</span>
    <span>原文 · LLM 排版</span>
</div>
{html_text}
</body>
</html>"""


def render_summary(title: str, platform: str, url: str, text: str,
                   granularity: str, llm_source: str) -> str:
    g_labels = {"brief": "简洁", "standard": "标准", "detailed": "详细"}
    l_labels = {"local": "本地 Ollama", "api": "DeepSeek API"}
    g_label = g_labels.get(granularity, granularity)
    l_label = l_labels.get(llm_source, llm_source)

    html_text = _markdown_to_html(text)

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{_esc(title)} - 总结</title>
<style>{CSS}</style>
</head>
<body>
<h1>{_esc(title)}</h1>
<div class="meta">
    <span class="badge">{platform}</span>
    <span>总结 · {g_label}</span>
    <span>模型：{l_label}</span>
</div>
{html_text}
</body>
</html>"""


def _markdown_to_html(text: str) -> str:
    """Convert basic markdown to HTML."""
    # Escape HTML first
    text = _esc(text)

    lines = text.split("\n")
    result = []
    in_list = False
    list_tag = None

    for line in lines:
        # Heading: ### ...
        if line.startswith("### "):
            if in_list:
                result.append(f"</{list_tag}>")
                in_list = False
            result.append(f"<h3>{line[4:]}</h3>")
            continue
        if line.startswith("## "):
            if in_list:
                result.append(f"</{list_tag}>")
                in_list = False
            result.append(f"<h2>{line[3:]}</h2>")
            continue
        if line.startswith("# "):
            if in_list:
                result.append(f"</{list_tag}>")
                in_list = False
            result.append(f"<h2>{line[2:]}</h2>")
            continue

        # Unordered list
        list_match = re.match(r"^[-*]\s+(.+)$", line)
        if list_match:
            if not in_list or list_tag != "ul":
                if in_list:
                    result.append(f"</{list_tag}>")
                result.append("<ul>")
                in_list = True
                list_tag = "ul"
            result.append(f"<li>{list_match.group(1)}</li>")
            continue

        # Ordered list
        num_match = re.match(r"^\d+[\.\)]\s+(.+)$", line)
        if num_match:
            if not in_list or list_tag != "ol":
                if in_list:
                    result.append(f"</{list_tag}>")
                result.append("<ol>")
                in_list = True
                list_tag = "ol"
            result.append(f"<li>{num_match.group(1)}</li>")
            continue

        # Close list if we're leaving it
        if in_list and line.strip():
            result.append(f"</{list_tag}>")
            in_list = False
            list_tag = None

        # Empty line → paragraph break
        if not line.strip():
            if in_list:
                result.append(f"</{list_tag}>")
                in_list = False
                list_tag = None
            continue

        # Regular paragraph
        result.append(f"<p>{line}</p>")

    if in_list:
        result.append(f"</{list_tag}>")

    html = "\n".join(result)

    # Inline formatting (after block-level conversion)
    html = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html)
    html = re.sub(r"__(.+?)__", r"<strong>\1</strong>", html)
    html = re.sub(r"\*(.+?)\*", r"<em>\1</em>", html)
    html = re.sub(r"_(.+?)_", r"<em>\1</em>", html)
    html = re.sub(r"`(.+?)`", r"<code>\1</code>", html)

    return html


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
