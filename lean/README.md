# Lean 4 形式化

本目录把报告里引用的两条关键不等式做成了机器可验证的定理。

## 文件

| 文件 | 内容 |
|---|---|
| `Boxpack.lean` | 4 条定理（2,391 B） |
| `lakefile.toml` | 构建配置 |
| `lean-toolchain` | 版本锁定：`leanprover/lean4:v4.36.0-rc2` |

## 4 条定理

| 定理 | 陈述 | 作用 |
|---|---|---|
| `total_le` | 若每个箱子的体积和 ≤ C，则总体积 ≤ 箱数 × C | 「车辆数下界」的算术内核 |
| `capacity_bounds_total` | 同上，报告直接引用的形式 | 指标合法性 |
| `fragile_on_floor_infeasible` | `680×245×250 − 30×70×50×(247−40) < 28,735,000` | **易碎件铺底时一辆车型 2 装不下** |
| `fragile_on_top_feasible` | `28,735,000 ≤ 680×245×250 − 30×70×50×3` | 对照组：置顶可行 |

第三条是核心：`41,650,000 − 105,000 × 207 = 19,915,000 < 28,735,000`。它把「易碎件垂直位置决定可行性」这一实验观察变成了机器验证的不可能性结论。

## 怎么验证

```bash
export ELAN_HOME="D:\Lean\elan"
export PATH="/d/Lean/elan/bin:$PATH"
cd lean
lake build
```

预期输出：`Build completed successfully`。

**不依赖 Mathlib**——纯 `List` / `Nat` / `omega` / `decide`。这意味着验证可在数秒内、无网络环境下完成，也不需要下载 5–15 GB 的 Mathlib。

## 证明要点（给后来者）

- `omega` 不认变量乘变量：证 `(n+1)*C` 前需先 `rw [Nat.add_mul, Nat.one_mul]` 展开成 `n*C + C`
- `one_mul` 必须写 `Nat.one_mul`（无前缀版在 Mathlib 里，核心库没有）
- 具体数值不等式用 `decide` 直接判定，无需手工推导

## 未形式化的部分

**三维几何约束不做形式化。** 理由：Mathlib 无三维装箱基础，从零构造代价远超本项目预算；该部分由 `src/constraints.py` 的几何校验承担。报告中需明确这一边界。
