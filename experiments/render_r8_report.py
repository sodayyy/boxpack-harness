"""Render a self-contained R8 report only after read-only evidence verification."""
import argparse
import csv
import html
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from experiments.verify_variant_study import verify_bundle


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("preserve existing report; choose a new output")
    result = verify_bundle(args.directory)
    if not result["passed"]:
        raise ValueError(result["errors"])
    summary = json.loads((args.directory / "summary.json").read_text(encoding="utf-8"))
    labels = {"base":"基准", "scale_1_2":"整体规模 ×½", "scale_3_2":"整体规模 ×1.5", "scale_2":"整体规模 ×2",
              "fragile_0":"易碎 0件", "fragile_15":"易碎 15件", "fragile_45":"易碎 45件", "fragile_60":"易碎 60件",
              "oriented_0":"定向 0件", "oriented_1_2":"定向 45件", "oriented_3_2":"定向 135件", "oriented_2":"定向 180件"}
    rows, chart, exports = [], [], []
    for i, (name, s) in enumerate(summary["cases"].items()):
        p1, p2, t = s["P1"], s["P2"], s["totals"]
        y = 40 + i * 34
        x1, x2 = 180 + p2["lower_bound"] / 3, 180 + p2["upper_bound"] / 3
        color = "#0d766e" if p2["proven_optimal"] else "#a55b08"
        chart.append(f'<text x="4" y="{y+5}" fill="#25354a" font-size="13">{labels[name]}</text><line x1="{x1}" y1="{y}" x2="{x2}" y2="{y}" stroke="{color}" stroke-width="5"/><circle cx="{x1}" cy="{y}" r="5" fill="#ffffff" stroke="{color}" stroke-width="2"/><circle cx="{x2}" cy="{y}" r="5" fill="{color}"/><text x="{x2+12}" y="{y+5}" fill="#25354a" font-size="12">{p2["lower_bound"]}–{p2["upper_bound"]}元</text>')
        rows.append(f'<tr><td>{labels[name]}<small>{name}</small></td><td>{t["items"]}</td><td>{t["volume_cm3"]/1e6:.4f}</td><td>{t["weight_kg"]}</td><td>{t["fragile_count"]/t["items"]:.1%}</td><td>{t["oriented_count"]/t["items"]:.1%}</td><td>{s["complete_runs"]}/24</td><td>{p1["lower_bound"]}–{p1["upper_bound"]}</td><td>{p2["lower_bound"]}–{p2["upper_bound"]}</td></tr>')
        exports.append(dict(case=name,items=t["items"],volume_m3=t["volume_cm3"]/1e6,weight_kg=t["weight_kg"],complete_runs=s["complete_runs"],P1_lower=p1["lower_bound"],P1_upper=p1["upper_bound"],P1_witness=p1["witness"],P2_lower=p2["lower_bound"],P2_upper=p2["upper_bound"],P2_witness=p2["witness"]))
    document = '''<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>R8 规模与数量组成研究</title><style>
    *{box-sizing:border-box}body{margin:0;background:#f4f6fa;color:#25354a;font:16px/1.75 "Microsoft YaHei",sans-serif}main{max-width:1160px;margin:auto;padding:42px 28px}h1{font-size:34px;line-height:1.3}h2{font-size:23px;margin-top:32px}p{max-width:1000px}.lead{color:#51617a}.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}.card,section{background:#fff;border:1px solid #dbe3ee;border-radius:12px;padding:22px;margin:16px 0}.card strong{font-size:30px;color:#0d766e;display:block}.note{border-left:4px solid #a55b08;padding-left:18px}table{border-collapse:collapse;width:100%;font-size:14px}th,td{padding:10px;border-bottom:1px solid #dbe3ee;text-align:left}th{background:#edf2f8}small{display:block;color:#64748b}code{font-family:Consolas,monospace;overflow-wrap:anywhere}.scroll{overflow-x:auto}svg{max-width:100%;height:auto}footer{color:#64748b;font-size:13px}@media(max-width:720px){.cards{grid-template-columns:repeat(2,1fr)}main{padding:24px 14px}h1{font-size:27px}}
    </style></head><body><main><p class="lead">MathorCup 2026 D · AI4S研究记录 · 2026-11-11</p><h1>R8：规模与货物数量组成</h1><p>固定12个派生目录、6种同型车队和4个排序，完成288项确定性构造。191项给出完整见证；12个目录均至少有一份完整运输方案。P1与P2分别评价，容量下界允许全部车型及混合组合。</p><div class="cards"><div class="card"><strong>288</strong>固定配置全部完成</div><div class="card"><strong>191</strong>完整、零违规见证</div><div class="card"><strong>9 / 12</strong>最少车辆数已证明</div><div class="card"><strong>6 / 12</strong>最低费用已证明</div></div>
    <section><h2>最低费用的已证区间</h2><p>空心端为全车型容量松弛下界，实心端为完整见证上界。端点重合表示当前操作模型下费用最优性闭合。橙线表示仍有缺口。</p><svg viewBox="0 0 800 458" role="img" aria-label="12场景最低费用上下界">CHART</svg></section>
    <section><h2>两个目标必须分别求解</h2><p>450件场景：两大车给出2辆／1400元，三小车给出3辆／1350元。P1选择两大车，P2选择三小车；若先固定最少车辆再求费用，就会遗漏本轮更便宜的已知方案。该场景的费用下界为1150元，尚未证明1350元最优。</p><p>易碎45件、60件及定向135件场景也出现同样的目标分歧。混合车队未纳入构造搜索，但始终纳入下界；不能把同型候选最优当成全车型最优。</p></section>
    <section><h2>完整结果表</h2><p>区间按下界–上界列出；同值才表示闭合。基准只运行一次，由三条扫描共享。</p><div class="scroll"><table><thead><tr><th>场景</th><th>件数</th><th>体积m³</th><th>重量kg</th><th>易碎占比</th><th>定向占比</th><th>完整配置</th><th>P1辆</th><th>P2元</th></tr></thead><tbody>ROWS</tbody></table></div></section>
    <section><h2>观察、限制与下一步</h2><p>150件、基准、易碎0/15件、定向0/45件共6个目录双目标闭合；450/600件及定向180件只闭合P1；易碎45/60件及定向135件两个目标均留缺口。97项部分装载全部保留，不能据此判断原问题无解。</p><p class="note">数量变化同时改变体积、重量和件数。这里是数量组成开发扫描，无法将差异全部归因于易碎或定向约束；也没有定位一般数量阈值。固定配置不是独立随机重复或等CPU比较。</p><p>下一步优先针对费用缺口登记混合车队构造，再研究基准附近未覆盖区域。AI已参与定义、实现、复核及纠错；人工/AI局部对照仍仅预登记，无节时率结论。</p></section>
    <section><h2>证据与真实核验</h2><p>Ubuntu / Python3.12.3，实际CPU亲和性[0]。保存288次布局与剩余身份、12目录、协议/源码快照、CSV/JSON及全部哈希。191份完整方案另经整数几何与有理数载荷检查。当前核验仍属项目自查。</p><p>读回时曾将JSON尺寸列表直接传给要求元组的裁判，引发姿态误报。当前验证器已在核验完目录JSON后恢复元组；原始数据、布局、哈希和实际运行快照保持原样。已加入缺跑、错目录、重复身份、假费用和协议篡改回归。</p><p>求解CPU合计：CPU秒，仅包含构造器；不包含裁判、读回、开发及测试，不作为AI增效或跨算法速度结论。</p><code>python experiments/verify_variant_study.py experiments/results/quantity_variants_R8_v1</code><p>验证摘要：VERIFY</p></section><footer>当前L4操作模型：chain_area_v1，α=0，p=500kg/m²，顶部余隙3cm。竖向载荷链不等于完整力矩平衡或运输安全认证。</footer></main></body></html>'''
    document = document.replace("CHART", "".join(chart)).replace("ROWS", "".join(rows)).replace("CPU秒", f'{result["cpu_seconds"]:.6f}秒').replace("VERIFY", html.escape(json.dumps(result, ensure_ascii=False)))
    args.output.write_text(document, encoding="utf-8")
    csv_path = args.output.with_suffix(".csv")
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(exports[0]))
        writer.writeheader()
        writer.writerows(exports)
    print(json.dumps(dict(html=str(args.output),csv=str(csv_path),verification=result),ensure_ascii=False))


if __name__ == "__main__":
    main()
