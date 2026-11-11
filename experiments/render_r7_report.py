"""Render a self-contained R7 report only after read-only evidence validation."""
import argparse
from collections import Counter
from fractions import Fraction
from html import escape
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from experiments.verify_parameter_envelope import verify_bundle


def render(directory):
    directory = Path(directory)
    verified = verify_bundle(directory)
    if not verified["passed"]:
        raise ValueError(verified["errors"])
    summary = json.loads((directory / "summary.json").read_text(encoding="utf-8"))
    rows = json.loads((directory / "grid.json").read_text(encoding="utf-8"))["rows"]
    pressures = ["0", "100", "200", "250", "300", "317", "318", "350", "362", "363", "400", "500"]
    clearances = ["50", "40", "30", "25", "20", "11", "10", "5", "3", "0"]
    # Assert the displayed alpha=1 slice is identical to every other alpha.
    lookup = {(r["alpha"], r["pressure"], r["clearance"]): r for r in rows}
    for r in rows:
        reference = lookup["1", r["pressure"], r["clearance"]]
        for key in ("witness_count", "P1", "P2", "status"):
            if r[key] != reference[key]:
                raise ValueError("alpha slices differ; cannot collapse visualization")
    cells, slice_counts = [], Counter()
    for d in clearances:
        line = ["<tr><th scope='row'>" + d + "</th>"]
        for p in pressures:
            row = lookup["1", p, d]
            if row["status"] == "witness_and_lower_bounds":
                cls, text, title = "optimal", "700", "1辆/700元，双目标最优已证明"
            elif row["status"] == "verified_upper_bounds_not_global_optimum":
                cls, text, title = "upper", "≤900", "2辆/900元仅为可行上界"
            else:
                cls, text, title = "unknown", "—", "现有布局未覆盖，不代表无解"
            slice_counts[cls] += 1
            line.append(f"<td class='{cls}' title='p={p}, δ={d}: {title}'>{text}</td>")
        cells.append("".join(line) + "</tr>")
    if dict(slice_counts) != {"unknown": 99, "optimal": 12, "upper": 9}:
        raise ValueError("unexpected rendered slice counts")
    headers = "".join("<th scope='col'>" + p + "</th>" for p in pressures)
    p_large = Fraction(summary["frontier"]["one_large"][0]["pressure_min"])
    p_small = Fraction(summary["frontier"]["two_small"][0]["pressure_min"])
    if (p_large, p_small) != (Fraction(2540, 7), Fraction(2220, 7)):
        raise ValueError("report formulas require updated verified thresholds")
    # Plot p in [0,500], clearance in [0,15]; color represents saved witnesses.
    x = lambda p: 62 + float(p) / 500 * 576
    y = lambda d: 260 - float(d) / 15 * 210
    green = f"<rect x='{x(p_large):.3f}' y='{y(10):.3f}' width='{638-x(p_large):.3f}' height='{260-y(10):.3f}' fill='#bde4d8' stroke='#176551'/>"
    amber = f"<rect x='{x(p_small):.3f}' y='{y(5):.3f}' width='{x(p_large)-x(p_small):.3f}' height='{260-y(5):.3f}' fill='#f7ddb0' stroke='#956200'/>"
    ticks = "".join(f"<text x='{x(p):.2f}' y='283' text-anchor='middle'>{p}</text>" for p in (0,100,200,300,400,500))
    yticks = "".join(f"<text x='50' y='{y(d)+5:.2f}' text-anchor='end'>{d}</text>" for d in (0,5,10,15))
    template = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>R7 参数区间与证据</title>
<style>
:root{color-scheme:light;--ink:#162b3d;--muted:#526579;--line:#d6e0e8;--bg:#f3f6f8;--card:#fff;--green:#d7efe5;--amber:#ffedcd}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font-family:"Microsoft YaHei","Segoe UI",sans-serif;line-height:1.7}main{max-width:1120px;margin:38px auto;padding:0 24px 48px}h1{font-size:32px;line-height:1.3;margin:10px 0 16px}h2{font-size:22px;margin:0 0 14px}h3{font-size:17px;margin:0 0 10px}.eyebrow{letter-spacing:.12em;color:#176551;font-size:13px;font-weight:700}.intro{max-width:920px;color:var(--muted)}.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:26px 0}.kpi,.panel{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:22px}.kpi strong{display:block;font-size:32px;line-height:1.3}.kpi span{font-size:13px;color:var(--muted)}.panel{margin:18px 0}.twocol{display:grid;grid-template-columns:1fr 1fr;gap:18px}.formula{font-size:19px;font-weight:700;line-height:1.7}.good{border-left:5px solid #26715c}.caution{border-left:5px solid #bd7c17}.note{color:var(--muted);font-size:14px}.warn{background:#fff4df;border:1px solid #e4c78b;border-radius:9px;padding:14px 18px}.legend{display:flex;gap:20px;flex-wrap:wrap;font-size:13px}.legend i{display:inline-block;width:13px;height:13px;border:1px solid #adc1ce;margin-right:7px}.tablewrap{overflow:auto}table{border-collapse:collapse;width:100%;font-size:13px;white-space:nowrap}th,td{border:1px solid var(--line);padding:9px 8px;text-align:center}th{background:#edf2f6}td.optimal{background:var(--green);color:#14533f;font-weight:700}td.upper{background:var(--amber);color:#764b00;font-weight:700}td.unknown{background:#f4f6f8;color:#6d7b87}.plot{max-width:760px;margin:12px auto}svg{width:100%;height:auto}svg text{font-family:inherit;fill:#263d51;font-size:14px}li{margin:6px 0}code,pre{font-family:Consolas,monospace;font-size:13px}pre{background:#eff3f6;border:1px solid var(--line);padding:15px;overflow:auto;line-height:1.7}footer{font-size:13px;color:var(--muted);border-top:1px solid var(--line);padding-top:18px;margin-top:28px}@media(max-width:720px){main{padding:0 14px}.kpis{grid-template-columns:repeat(2,1fr)}.twocol{grid-template-columns:1fr}h1{font-size:26px}.panel{padding:17px}}@media print{body{background:#fff}main{margin:0;max-width:none}.panel,.kpi{break-inside:avoid}table{font-size:10px}}
</style></head><body><main>
<div class="eyebrow">MATHORCUP 2026 D · AI4S RESEARCH / R7</div>
<h1>从一个可行装法，走向可复核的参数区间</h1>
<p class="intro">原始300件货物的一大车700元最优方案已在R6闭合。本轮保持布局不变，研究支撑比例α、允许顶面平均外载p和顶部余隙δ的变化。<b>这里画出的是已有方案能保证的区域，不是原问题全部可行域。</b></p>
<div class="kpis"><div class="kpi"><strong>21</strong><span>44份完整记录去重后的布局</span></div><div class="kpi"><strong>720</strong><span>固定参数点，不是720次求解</span></div><div class="kpi"><strong>84</strong><span>压力与高度边界交叉核验</span></div><div class="kpi"><strong>11,160</strong><span>只读复核的单调关系</span></div></div>
<div class="twocol"><section class="panel good"><h3>一辆大车 · 双目标最优保持</h3><div class="formula">p ≥ 2540/7 ≈ 362.857 kg/m²<br>0 ≤ δ ≤ 10 cm</div><p>α∈[0,1]，12个布局阈值相同。<br><b>P1=1辆，P2=700元</b>，见证与独立下界闭合。</p></section><section class="panel caution"><h3>两辆小车 · 更低压力上限可用</h3><div class="formula">p ≥ 2220/7 ≈ 317.143 kg/m²<br>0 ≤ δ ≤ 5 cm</div><p>α∈[0,1]，9个布局阈值相同。<br>2辆、900元为可行上界，<b>不证明全局必须涨价</b>。</p></section></div>
<section class="panel"><h2>已证可行区域：两种方案提供不同余量</h2><div class="legend"><span><i style="background:#bde4d8"></i>一大车：1辆 / 700元最优</span><span><i style="background:#f7ddb0"></i>仅两小车见证：2辆 / 900元上界</span><span><i style="background:#f0f3f6"></i>未覆盖，不代表无解</span></div>
<div class="plot"><svg viewBox="0 0 680 325" role="img" aria-label="压力上限与顶部余隙的已知可行区域"><rect x="62" y="50" width="576" height="210" fill="#f0f3f6" stroke="#b8c7d4"/>__GREEN____AMBER__<path d="M62 45V260H645" fill="none" stroke="#526579" stroke-width="1.5"/>__XTICKS____YTICKS__<text x="64" y="28">顶部余隙 δ / cm</text><text x="638" y="315" text-anchor="end">允许顶面平均外载 p / kg·m⁻²</text><text x="340" y="112" text-anchor="middle">现有布局池未覆盖</text><text x="590" y="173" text-anchor="middle">700元</text><text x="590" y="196" text-anchor="middle">双目标最优</text><text x="455" y="230" text-anchor="end">仅900元上界 →</text></svg></div>
<p class="note">图示δ为0–15cm；δ&gt;15cm亦未覆盖。绿色区域允许与两小车区域重叠，按较低成本显示；两个精确压力边界均包含等号。所有保存布局100%支撑，六个α切片相同。这不证明支撑比例对其他布局没有影响。</p></section>
<section class="panel"><h2>固定网格：72点最优闭合，54点仅上界，594点未覆盖</h2><p class="note">展示α=1的120点；已逐点验证其与另五个α切片相同。表格各列是离散参数，间距不代表比例。单切片分别为12 / 9 / 99点，乘6得到720点统计。</p><div class="tablewrap"><table aria-label="参数网格成本与证据类型"><thead><tr><th>δ↓ / p→</th>__HEADERS__</tr></thead><tbody>__CELLS__</tbody></table></div><p class="note">700＝双目标最优；≤900＝已有可行成本上界；—＝未找到保存见证。p的单位kg/m²，δ的单位cm。</p></section>
<section class="panel"><h2>这次真正知道了什么</h2><ul><li>每组布局的精确阈值相同：21个布局并未比两个代表方案覆盖更大区域；保留这一负结果。</li><li>固定布局可行当且仅当α≤ρ、p≥p*、δ≤δ*，其余规则另行完整核验。采用整数几何及有理数载荷，不靠四舍五入判边界。</li><li>一大车覆盖区内，非空运输下界1辆、低于700元车队容积不足，使P1/P2分别达到下界。</li><li>900元区域不能排除尚未找到的一大车新布局；灰色区域更不能判成原问题无解。</li></ul><div class="warn"><b>模型边界：</b>面积归一化竖向链不等于完整力矩平衡、摩擦或运输安全认证。当前验证器与分析器共享阈值函数，不能称两套独立数学证明；84项边界另与原约束裁判交叉核验。</div></section>
<section class="panel"><h2>证据与复现</h2><ul><li>63个文件SHA256、44份完整来源布局、计划、实际运行源码/数据快照、阈值、边界、720点JSON/CSV均已读回。</li><li>80项自动发现及12项显式约束触发测试通过；包括重哈希后仍拒绝截断、错参数、假不可行与假阈值。</li><li>分析阶段墙钟13.187891秒，CPU12.625秒；不含实现、前置来源核验和全部测试，不作跨算法速度或全流程节时比较。</li><li>首次测试发现CSV句柄警告，当前验证器已显式关闭；实际运行快照保持原字节。全部数学结论是项目自查，非第三方审查。</li></ul><pre>python experiments/verify_parameter_envelope.py experiments/results/parameter_envelope_R7_v1
python -m unittest discover -s experiments -p "test_*.py" -v
python experiments/test_constraints.py</pre><p class="note">正式说明：docs/11-R7参数区间结果.md。AI局部对照：docs/12-AI局部对照预登记.md，尚未执行。</p></section>
<section class="panel"><h2>后续主线</h2><p>研究更低承重或更大顶部余隙是否需要新的布局结构，再扩展规模/易碎比例/定向比例。AI辅助过程已经有真实实现与纠错记录，但无AI人工对照尚未执行，<b>不报告节时率</b>。方案书、PPT、视频及更广泛化仍未完成。</p></section>
<footer>2026-11-11 · R7固定布局池参数研究 · 自包含HTML，无外部资源。由通过只读核验的证据生成；Git与远端状态见阶段交付说明，不由本图代替核验。</footer>
</main></body></html>"""
    replacements = {"__GREEN__": green, "__AMBER__": amber, "__XTICKS__": ticks,
                    "__YTICKS__": yticks, "__HEADERS__": headers, "__CELLS__": "".join(cells)}
    for key, value in replacements.items():
        template = template.replace(key, value)
    return template


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, default=ROOT / "experiments/results/parameter_envelope_R7_v1")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("preserve previous deliverables; use a new output filename")
    if not args.output.parent.is_dir():
        parser.error("output parent directory does not exist")
    content = render(args.evidence)
    args.output.write_text(content, encoding="utf-8")
    print(json.dumps(dict(output=str(args.output.resolve()), bytes=args.output.stat().st_size,
                          verified=True, plotted_cells=120), ensure_ascii=False))
