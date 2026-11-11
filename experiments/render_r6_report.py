"""Render a self-contained HTML research result from verified R6 evidence."""
import html
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parent
sys.path.insert(0, str(ROOT))
from experiments.verify_block_search import verify_bundle
from experiments.verify_witness_exact import verify


def main():
    directory = ROOT / "experiments/results/block_search_L4_v1"
    if not verify_bundle(directory)["passed"]:
        raise ValueError("evidence rejected")
    if not verify(ROOT / "experiments/results/r6_block_witnesses_v1/one_large.json")["passed"]:
        raise ValueError("exact self-check rejected")
    summary = json.loads((ROOT / "experiments/results/r6_block_witnesses_v1/summary.json").read_text(encoding="utf-8"))
    row = json.loads((directory / "blocks_L4_024.json").read_text(encoding="utf-8"))
    placements = row["search"]["placements"]
    by_serial = {b["serial"]: b for tr in row["fleet"] for b in tr["boxes"]}
    colors = {"G1": ("#dbeafe", "#1d4ed8"), "G2": ("#ccfbf1", "#0f766e"),
              "G3": ("#fef3c7", "#92400e"), "G4": ("#ede9fe", "#6d28d9"), "G5": ("#ffe4e6", "#be123c")}
    rects, table_rows = [], []
    for index, placement in enumerate(placements, 1):
        boxes = [by_serial[s] for s in placement["serials"]]
        names = sorted({b["name"] for b in boxes})
        base = next((name for name in names if name != "G3"), "G3")
        fill, stroke = colors[base]
        x, y, l, w = (placement[k] for k in ("x", "y", "l", "w"))
        label = "+".join(names)
        title = f"块{index}: {label}，{len(boxes)}件；地面({x},{y})，底面{l}×{w}cm；高{max(b['z']+b['h'] for b in boxes)}cm"
        rects.append(f'<g><title>{html.escape(title)}</title><rect x="{x}" y="{y}" width="{l}" height="{w}" rx="2" fill="{fill}" stroke="{stroke}" stroke-width="1.2"/><text x="{x+l/2}" y="{y+w/2-2}" text-anchor="middle" fill="{stroke}" font-size="9" font-weight="700">{index}</text><text x="{x+l/2}" y="{y+w/2+10}" text-anchor="middle" fill="{stroke}" font-size="7">{label}</text></g>')
        counts = ", ".join(f"{name}×{sum(b['name']==name for b in boxes)}" for name in names)
        table_rows.append(f"<tr><td>{index}</td><td>{counts}</td><td>({x}, {y})</td><td>{l}×{w}</td><td>{max(b['z']+b['h'] for b in boxes)}</td></tr>")
    groups = "".join(f"<tr><td>{'一辆大车' if g['combination']==[0,1] else '两辆小车'}</td><td>{'标准平台＋易碎帽' if g['capped'] else '无易碎帽'}</td><td>{g['complete_runs']} / {g['runs']}</td><td>{g['placed']}</td></tr>" for g in summary["groups"])
    document = '''<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>R6｜300件装入一辆大车</title>
<style>
:root{color-scheme:light;--ink:#17253a;--muted:#58677a;--line:#dce4ed;--blue:#1d4ed8;--bg:#f5f8fc}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.7 "Segoe UI","Microsoft YaHei",sans-serif}main{max-width:1080px;margin:auto;padding:38px 28px 60px}header{border-top:5px solid var(--blue);padding-top:24px}small,.muted{color:var(--muted)}.eyebrow{font-size:12px;letter-spacing:2px;font-weight:700;color:var(--blue)}h1{font-size:36px;line-height:1.25;letter-spacing:-1px;margin:12px 0}h2{font-size:21px;margin:0 0 14px}h3{font-size:17px;margin:0 0 8px}p{margin:8px 0 12px}.cards{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin:24px 0}.card,section{background:white;border:1px solid var(--line);border-radius:12px;padding:22px}.card strong{display:block;font-size:31px;color:var(--blue)}.card span{color:var(--muted);font-size:13px}section{margin:18px 0}.two{display:grid;grid-template-columns:1fr 1fr;gap:22px}.tag{font-size:12px;background:#e8f4ec;color:#166534;border-radius:18px;padding:5px 10px;display:inline-block}.proof{border-left:3px solid #2563eb;padding:0 16px}.caution{border-left:3px solid #d97706;background:#fffbeb;padding:12px 16px;margin-top:16px}svg{width:100%;height:auto;background:#fff}table{width:100%;border-collapse:collapse;font-size:14px}th,td{text-align:left;padding:10px;border-bottom:1px solid var(--line)}th{background:#f1f5f9;font-weight:600}.legend{display:flex;flex-wrap:wrap;gap:15px;font-size:12px;margin:10px 0}.dot{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:5px}code{font:12px Consolas,monospace;background:#eef2f7;border-radius:4px;padding:3px 5px;overflow-wrap:anywhere}ul{padding-left:21px}details{margin-top:18px}summary{cursor:pointer;color:var(--blue)}footer{font-size:12px;color:var(--muted);margin-top:24px}@media(max-width:650px){main{padding:24px 14px}.cards,.two{grid-template-columns:1fr}h1{font-size:29px}.card{padding:16px}}@media print{body{background:#fff}main{padding:10px}.card,section{break-inside:avoid}details{display:none}}
</style></head><body><main>
<header><div class="eyebrow">三维装箱 × AI辅助科研 · R6 · 2026-11-11</div><h1>300件货物，一辆大车装完</h1><p class="muted">从逐件贪心的失败，走到整体平台构造；用可编辑布局和独立下界，闭合原始实例的两个运输目标。</p><span class="tag">完整布局核验通过 · 原始实例 / 当前操作模型</span></header>
<div class="cards"><div class="card"><span>P1 最少车辆数</span><strong>1 辆</strong><span>下界 1 ＝ 已验证上界 1</span></div><div class="card"><span>P2 最低运输成本</span><strong>700 元</strong><span>独立费用下界 ＝ 已验证上界</span></div><div class="card"><span>完整运输</span><strong>300 / 300</strong><span>28.735 m³ · 4,110 kg · 零违规</span></div></div>
<section><h2>01 / 这次改变了什么</h2><div class="two"><div><h3>原来：一件一件放</h3><p>标准件先占位后，不容易给易碎件留出完整、同高的支撑平台。R5最好完整方案是一小一大两车，1150元。</p></div><div><h3>现在：把平台和顶层一起设计</h3><p>先构造“标准件底座＋易碎件顶层”或定向件立柱，再把这些整体块排到地面。没有放松原先的姿态、支撑或承重规则。</p></div></div><p><b>结果：</b>得到一大车700元，也找到两小车900元。相对此前1150元可行方案少450元（39.13%），这不是AI节时率或一般算法提升率。</p></section>
<section><h2>02 / 一大车方案：地面块布局</h2><p class="muted">俯视图，尺寸单位cm。编号对应下表；色块表示整柱/平台的地面占用，不是把所有货物平铺。悬停查看块内容。</p>
<svg viewBox="0 0 740 305" role="img" aria-label="一辆680乘245厘米大车的完整块地面布局"><text x="370" y="18" text-anchor="middle" font-size="12" fill="#58677a">内长 680 cm</text><g transform="translate(30,32)"><rect x="0" y="0" width="680" height="245" fill="#f8fafc" stroke="#64748b" stroke-width="2"/>__RECTS__</g><text x="30" y="297" font-size="10" fill="#58677a">内部坐标：左前下原点；导出CSV/JSON使用右后下原点，并已验证双轴往返。</text></svg>
<div class="legend">__LEGEND__</div><p>最高 <b>240cm</b>，低于扣除余隙后的247cm；最大顶面平均外载 <b>362.857kg/m²</b>，低于500；所有正高度货物 <b>100%支撑</b>。标称空间率68.9916%，有效空间率69.8296%。</p>
<details><summary>展开完整块清单（逐件坐标另见JSON/CSV）</summary><table><thead><tr><th>块</th><th>货物组成</th><th>地面起点</th><th>底面</th><th>高度</th></tr></thead><tbody>__BLOCK_ROWS__</tbody></table></details></section>
<section><h2>03 / 为什么能说原始实例最优</h2><div class="two"><div class="proof"><h3>P1：至少要一辆，实际用一辆</h3><p>货物非空，所以零辆车不可能完成运输。已有一辆大车的完整合法布局，故最少车辆数恰为1。</p></div><div class="proof"><h3>P2：比700元更便宜的都装不下</h3><p>车型仅450元小车、700元大车。低于700元只可能零辆或一辆小车；小车有效容积19.1394m³，小于28.735m³。因此最低费用至少700元，而新方案正好达到。</p></div></div><div class="caution">最优性来自“可行见证＋独立下界”，不是块算法穷举了全部布局。P1/P2各自证明，没有把最低成本限制在最少车辆方案中。</div></section>
<section><h2>04 / 固定96配置开发结果</h2><table><thead><tr><th>车队</th><th>构造</th><th>完整方案 / 配置</th><th>最好件数*</th></tr></thead><tbody>__GROUPS__</tbody></table><small>* 先按已装体积选优，再报告该方案件数。已知原始实例开发，不是盲测；配置可能重复同一布局，不代表独立随机成功概率。有帽/无帽同时改变平台与堆叠，不能作单因素因果结论。</small></section>
<section><h2>05 / 证据与边界</h2><ul><li>96次全部运行、44份完整方案；109个证据文件哈希、矩阵完整性、逐件规则与指标独立读回通过。</li><li>另写不导入求解器/原裁判的整数几何＋有理数载荷检查；两方案均通过。属于另一实现自查，不称第三方审查。</li><li>69项自动发现＋12项约束触发，共81项回归通过；旧结果、失败构造与历史版本保留。</li><li>没有完整力矩、摩擦、动态运输或局部峰值压力认证；易碎件六姿态是本项目主情景约定。</li></ul></section>
<section><h2>06 / AI做了什么，以及下一步</h2><p>本轮留下了“失败诊断 → 构造假设 → 实现 → 测试 → 固定预算实验 → 读回 → 数学论证”的真实链条。没有无AI人工耗时对照，因此不报告AI全流程提效百分比。</p><p><b>下一阶段：</b>转向参数区间、适用范围与AI局部增效对照；不再把原始实例继续降成本作为待完成主线。方案书、PPT和视频仍待制作。</p><p class="muted">正式证据：<code>experiments/results/r6_block_witnesses_v1/</code><br>完整说明：<code>docs/09-R6块构造结果与最优证据.md</code></p></section>
<footer>由实际证据生成 · R6开发节点 · 研究对象、模型约定与结论范围必须对应；不将布局可行等同工程安全。</footer></main></body></html>'''
    legend = "".join(f'<span><i class="dot" style="background:{fill};border:1px solid {stroke}"></i>{name}</span>' for name, (fill, stroke) in colors.items())
    document = document.replace("__RECTS__", "".join(rects)).replace("__LEGEND__", legend).replace("__BLOCK_ROWS__", "".join(table_rows)).replace("__GROUPS__", groups)
    target = WORKSPACE / "R6-一车方案与最优证据.html"
    target.write_text(document, encoding="utf-8")
    print(json.dumps(dict(file=str(target), blocks=len(placements), bytes=target.stat().st_size), ensure_ascii=False))


if __name__ == "__main__":
    main()
