# Lean 4：算术内核，而非三维装载证明

环境锁定 `leanprover/lean4:v4.36.0-rc2`，不依赖 Mathlib。

| 声明 | 实际证明内容 | 不能推出 |
|---|---|---|
| `total_le` | 每箱体积和 ≤ C，则总体积 ≤ 箱数 × C | 几何容量假设自动成立 |
| `capacity_bounds_total` | 上述结论的直接引用形式 | 一般三维最优性 |
| `floor_shadow_capacity_insufficient` | `680×245×247 - 30×70×50×207 < 28,735,000` | 当前 C5 下所有铺底布局必然无解 |
| `effective_capacity_not_ruled_out` | `28,735,000 ≤ 680×245×247` | 置顶可行或一车全约束可行 |

## 修正说明

旧名称 `fragile_on_floor_infeasible` 和 `fragile_on_top_feasible` 容易让数值不等式冒充几何证明，本次已替换。比较使用 247 cm 有效高度，而非 250 cm 标称高度。

铺底阴影柱计算为 `41,150,200 - 21,735,000 = 19,415,200 cm³`。该容量上界的几何解释要求：固定 70×50×40 姿态、全部铺底、每件正上方整柱不可用。**整柱留空是额外假设**；当前校验器只禁止直接压在易碎件上，允许由其他货物支撑的无接触跨接。因此 Lean 这里只验证数值，不证明当前 C5 蕴含该容量上界。

旧名称不保留为别名，避免下游继续引用“置顶可行”；历史版本可从 `v0.3-ftl` 取得。

## 复核

从本目录执行：

```bash
export ELAN_HOME="D:/Lean/elan"
export PATH="/d/Lean/elan/bin:$PATH"
lake env lean Boxpack.lean
lake build
```

文件含四个 `#print axioms`，用于查看声明的真实依赖；无 `sorry`/`admit` 和新增公理。以本次实际构建输出为准。

三维几何、支撑、姿态和承重仍由独立 Python 校验器检查，尚未形式化。
