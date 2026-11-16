"""Render the editable research manuscript and appendices as one reading page.

Requires markdown-it-py and latex2mathml==3.78.1. Outputs native offline
MathML. Does not generate or modify research data.
"""
import argparse
import html
from pathlib import Path
import re
from urllib.parse import quote

# Historical manuscript renderer; current research entry is README.md.
from markdown_it import MarkdownIt
from latex2mathml.converter import convert

ROOT = Path(__file__).resolve().parents[1]
DOCS = [
    ("paper", "历史论文正文", "archive/20-论文主稿.md"),
    ("model", "附录A · 完整公式", "19-统一参数化模型.md"),
    ("audit", "历史核验台账", "archive/21-科研核心核验与结论台账.md"),
]


def render(text):
    blocks = []

    def math(match):
        key = len(blocks)
        source = match.group(1)
        tags = re.findall(r"\\tag\{([^}]+)\}", source)
        source = re.sub(r"\\tag\{[^}]+\}", "", source)
        number = '<span class="eqno">(' + html.escape(tags[0]) + ')</span>' if tags else ""
        blocks.append('<div class="equation">' + convert(source, display="block") + number + '</div>')
        return "\n\nMATHBLOCK" + str(key) + "END\n\n"

    text = re.sub(r"\\\[([\s\S]*?)\\\]", math, text)
    # Protect the whole inline expression, including escaped braces and symbols.
    inline = []

    def inline_math(match):
        key = len(inline)
        inline.append(convert(match.group(1)))
        return "INLINEMATH" + str(key) + "END"

    text = re.sub(r"\\\(([\s\S]*?)\\\)", inline_math, text)
    page = MarkdownIt("commonmark", {"html": False}).enable("table").render(text)
    for i, expression in enumerate(inline):
        page = page.replace("INLINEMATH" + str(i) + "END", expression)
    for i, block in enumerate(blocks):
        page = page.replace("<p>MATHBLOCK" + str(i) + "END</p>", block)
    for ident, _, filename in DOCS:
        page = page.replace('href="' + filename + '"', 'href="#' + ident + '"')
        page = page.replace('href="' + quote(filename) + '"', 'href="#' + ident + '"')
    diagram = (ROOT / "docs" / "archive" / "22-参数区域示意.svg").read_text(encoding="utf-8")
    page = re.sub(r'<img src="22-[^\"]+\.svg"[^>]*>', diagram, page)
    return page


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    if not args.output.parent.is_dir():
        p.error("output parent must exist")
    sections = "\n".join('<section id="' + ident + '">' + render((ROOT / "docs" / f).read_text(encoding="utf-8")) + '</section>' for ident, _, f in DOCS)
    nav = " · ".join('<a href="#' + ident + '">' + label + '</a>' for ident, label, _ in DOCS)
    style = """
:root { color-scheme: light; --ink:#203043; --accent:#23666c; }
* { box-sizing:border-box; } html { scroll-behavior:smooth; }
body { margin:0; background:#f3f5f7; color:var(--ink); font:16px/1.85 'Microsoft YaHei',sans-serif; }
header { background:#e8f1f2; padding:38px max(24px,calc((100vw - 1050px)/2)); border-bottom:1px solid #cbdcde; }
header h1 { font-size:27px; margin:0 0 10px; } header p { margin:6px 0; }
nav { position:sticky; top:0; background:#ffffffed; padding:12px 24px; text-align:center; border-bottom:1px solid #d5dde2; z-index:5; }
a { color:var(--accent); text-decoration:none; } a:hover { text-decoration:underline; }
main { max-width:1100px; margin:28px auto; padding:0 18px; }
section { background:white; padding:40px 52px; margin-bottom:28px; border:1px solid #dce3e7; border-radius:8px; scroll-margin-top:65px; }
h1,h2,h3 { line-height:1.5; color:#163c48; } section h1 { font-size:29px; } h2 { font-size:23px; border-bottom:1px solid #dce6e8; padding-bottom:10px; margin-top:38px; } h3 { font-size:19px; }
p { margin:15px 0; } blockquote { margin:15px 0; padding:9px 18px; background:#f2f7f7; border-left:4px solid #6e9fa2; }
table { border-collapse:collapse; width:100%; font-size:14px; display:block; overflow-x:auto; }
th,td { border:1px solid #d4dfe3; padding:10px 12px; vertical-align:top; } th { background:#edf4f5; text-align:left; }
pre { background:#f3f5f7; border:1px solid #dce3e7; padding:16px; overflow:auto; font-size:13px; line-height:1.65; }
code { font-family:Consolas,monospace; overflow-wrap:anywhere; } p code,td code { font-size:.9em; background:#f0f4f5; padding:2px 4px; }
section svg { max-width:100%; height:auto; } .equation { overflow-x:auto; padding:16px 4px; text-align:center; font-family:Cambria,serif; } math { font-family:'Cambria Math','STIX Two Math',serif; } .eqno { float:right; padding-left:10px; }
footer { text-align:center; color:#5e7180; padding:25px; font-size:13px; }
@media(max-width:700px) { section { padding:22px 19px; } section h1 { font-size:24px; } body { font-size:15px; } }
@media print { body { background:white; } nav,header { position:static; } section { border:0; padding:0; page-break-before:always; } main { max-width:none; } }
"""
    page = '<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>三维装箱研究 · 论文与完整公式</title><style>' + style + '</style>'
    page += '</head><body>'
    page += '<header><h1>多车型三维装箱：模型、证书与可核验结果</h1><p>历史归档：2026-11-13论文工作稿；非最新研究入口</p><p>先给问题与依据，再谈工具。当前模型原实例最优1辆/700元；一般完整相图、动力学和AI节时仍未完成。</p><p style="font-size:13px">公式采用浏览器原生MathML，离线可读，无需联网公式库。可编辑Markdown源稿与Lean/Python文件另行交付。</p></header><nav>' + nav + '</nav><main>' + sections + '</main><footer>研究自查，不是同行评审或第三方安全认证。未覆盖区域不等于无解。</footer></body></html>'
    args.output.write_text(page, encoding="utf-8")
    print(dict(output=str(args.output), sections=len(DOCS), equations=page.count('class="equation"'), chars=len(page)))


if __name__ == "__main__":
    main()
