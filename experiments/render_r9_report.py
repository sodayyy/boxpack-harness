"""Render R9 only from a verified bundle; refuse to overwrite deliverables."""
import argparse
import csv
import html
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from experiments.verify_mixed_study import verify_bundle


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("directory",type=Path)
    p.add_argument("--output",type=Path,required=True)
    args = p.parse_args()
    if args.output.exists() or args.output.with_suffix(".csv").exists():
        p.error("choose a new output; preserve reports")
    check = verify_bundle(args.directory)
    if not check["passed"]:
        raise ValueError(check["errors"])
    summary = json.loads((args.directory/"summary.json").read_text(encoding="utf-8"))
    old = json.loads((args.directory/"source/summary.json").read_text(encoding="utf-8"))["cases"]
    labels = {"scale_3_2":"450件", "scale_2":"600件", "fragile_45":"易碎45件", "fragile_60":"易碎60件", "oriented_3_2":"定向135件", "oriented_2":"定向180件"}
    table, chart, rows = [], [], []
    improved = sum(s["P2"]["upper_bound"]<old[n]["P2"]["upper_bound"] for n,s in summary["cases"].items())
    for i,(name,s) in enumerate(summary["cases"].items()):
        a,b = s["P1"],s["P2"]
        prior = old[name]["P2"]["upper_bound"]
        table.append(f'<tr><td>{labels[name]}<small>{name}</small></td><td>{s["r9_complete_runs"]}/48</td><td>{prior}</td><td>{a["lower_bound"]}–{a["upper_bound"]}</td><td>{b["lower_bound"]}–{b["upper_bound"]}</td><td>{b["source"]}: {b["witness"]}</td></tr>')
        y = 40+i*65
        x1,x2,x3 = [170+x/3 for x in (b["lower_bound"],b["upper_bound"],prior)]
        color = "#0b766d" if b["proven_optimal"] else "#a35a08"
        chart.append(f'<text x="8" y="{y+4}" fill="#25354a" font-size="14">{labels[name]}</text><line x1="{x1}" y1="{y}" x2="{x2}" y2="{y}" stroke="{color}" stroke-width="5"/><circle cx="{x1}" cy="{y}" r="5" fill="#fff" stroke="{color}" stroke-width="2"/><circle cx="{x2}" cy="{y}" r="5" fill="{color}"/><circle cx="{x3}" cy="{y-13}" r="4" fill="#8492a6"/><text x="170" y="{y+25}" fill="#51617a" font-size="12">R8上界 {prior} → 合并后 [{b["lower_bound"]}, {b["upper_bound"]}] 元</text>')
        rows.append(dict(case=name,r9_complete=s["r9_complete_runs"],r8_cost_upper=prior,P1_lower=a["lower_bound"],P1_upper=a["upper_bound"],P1_source=a["source"],P1_witness=a["witness"],P2_lower=b["lower_bound"],P2_upper=b["upper_bound"],P2_source=b["source"],P2_witness=b["witness"]))
    document = '''<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>R9 混合车队费用缺口</title><style>*{box-sizing:border-box}body{background:#f4f6fa;color:#25354a;margin:0;font:16px/1.8 "Microsoft YaHei",sans-serif}main{max-width:1080px;margin:auto;padding:36px 24px}h1{font-size:34px;line-height:1.4}h2{font-size:23px}section,.card{background:#fff;border:1px solid #dbe3ee;border-radius:12px;padding:22px;margin:16px 0}.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}.card strong{display:block;font-size:30px;color:#0b766d}.muted,small{color:#64748b}small{display:block}table{width:100%;border-collapse:collapse;font-size:14px}td,th{padding:11px;border-bottom:1px solid #dbe3ee;text-align:left}th{background:#edf2f8}.scroll{overflow:auto}svg{max-width:100%;height:auto}code{overflow-wrap:anywhere}.note{border-left:4px solid #a35a08;padding-left:16px}@media(max-width:700px){.cards{grid-template-columns:repeat(2,1fr)}main{padding:20px 12px}h1{font-size:26px}}</style></head><body><main><p class="muted">MathorCup 2026 D · AI4S研究流程 · 2026-11-11</p><h1>R9：从容量下界到混合车队见证</h1><p>针对R8六个费用未闭合目录，冻结一小一大、两种车序、四种排序、两种坐标优先及三种块姿态序，共288项确定性配置。新增路线逐车重组剩余货物，不改变已装车辆或旧R8证据。</p><div class="cards"><div class="card"><strong>288</strong>全部配置已执行</div><div class="card"><strong>COMPLETE</strong>完整零违规见证</div><div class="card"><strong>IMPROVED / 6</strong>目录费用上界下降</div><div class="card"><strong>PROVEN / 6</strong>目录费用最优已证</div></div><section><h2>合并R8/R9后的费用区间</h2><p>空心圆为全车型容量下界，实心圆为完整见证上界，上方灰点为R8旧费用上界。绿线端点重合才表示当前操作模型的费用最优证明。</p><svg viewBox="0 0 760 430" role="img" aria-label="六目录费用上下界及旧上界">CHART</svg></section><section><h2>完整结果与见证索引</h2><p>每目录48配置。P1与P2从R8、R9所有完整零违规见证中分别选优；未使用车辆不收费。</p><div class="scroll"><table><thead><tr><th>目录</th><th>R9完整</th><th>R8费用上界</th><th>合并P1辆</th><th>合并P2元</th><th>P2见证</th></tr></thead><tbody>ROWS</tbody></table></div></section><section><h2>方法及有效结论</h2><p>旧构造器只接受等高车队。本轮不放松该接口，而是逐车调用单车构造：按本车有效高度组块，装不下的货物在下一辆车重新组块。每次按逐件裁判检查几何、姿态、支撑与竖向链载荷；完整方案另作整数几何/有理数自查。</p><p>费用上界下降说明新增构造路线提供了更便宜的合法见证；达到独立容量下界才证明对应目标最优。未闭合区间仍然未定；混合车队失败不等于原问题无解，也不推翻已有R8见证。</p><p class="note">六目录来自已知R8缺口，是开发研究，不是盲测、等CPU算法比较或车队类型的单因素因果实验。新增车序、重组策略与车高共同变化，不把收益归为某一个组件。</p></section><section><h2>复核、局限与AI流程</h2><p>保存全部完整/部分布局、阶段输入输出身份、原块统计、源R8绑定、源码与协议快照、CSV/JSON及哈希。验证器不导入求解器；与原裁判及R7精确方法共享部分代码，仍属项目自查，不是第三方审查。</p><p>求解CPU合计 CPU_SECONDS 秒，仅包含构造器，不含来源核验、裁判、开发与测试。实际平台与亲和性见environment.json；不报告AI节时率。</p><p>AI参与了协议、构造建议、实现、运行、反例测试和解释；真实人工/AI对照仍未执行。当前竖向载荷链不等于完整力矩平衡、摩擦或运输安全认证。</p><code>python experiments/verify_mixed_study.py experiments/results/mixed_blocks_R9_v1</code><p class="muted">VERIFY</p></section></main></body></html>'''
    for key,value in {"COMPLETE":str(summary["complete_runs"]),"IMPROVED":str(improved),"PROVEN":str(check["objective_proven_counts"]["P2"]),"CHART":"".join(chart),"ROWS":"".join(table),"CPU_SECONDS":f'{check["cpu_seconds"]:.6f}',"VERIFY":html.escape(json.dumps(check,ensure_ascii=False))}.items():
        document = document.replace(key,value)
    args.output.write_text(document,encoding="utf-8")
    with args.output.with_suffix(".csv").open("w",encoding="utf-8-sig",newline="") as f:
        w = csv.DictWriter(f,fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(json.dumps(dict(html=str(args.output),verification=check),ensure_ascii=False))


if __name__ == "__main__":
    main()
