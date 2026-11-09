/-
  MathorCup 2026 D 题（三维装箱）的可验证引理
  全部只用 Lean 4 核心库，不依赖 Mathlib。

  目的：为论文中的"车辆数下界"指标提供机器验证的依据。
-/

namespace Boxpack

/-! ## 一、下界的算术内核 -/

/-- 若每个箱子的体积和不超过容量 `C`，则所有箱子的体积和不超过 `箱子数 × C`。

    这就是"车辆数不可能少于 ⌈总体积 / 单车容积⌉"的算术本质：
    反过来说，`boxes.length * C ≥ 总体积`，即 `boxes.length ≥ 总体积 / C`。 -/
theorem total_le (C : Nat) :
    ∀ (boxes : List (List Nat)),
      (∀ b ∈ boxes, b.sum ≤ C) → (boxes.map List.sum).sum ≤ boxes.length * C
  | [], _ => by simp
  | b :: bs, h => by
    have hb : b.sum ≤ C := h b (by simp)
    have hs : (bs.map List.sum).sum ≤ bs.length * C :=
      total_le C bs (fun x hx => h x (by simp [hx]))
    simp only [List.map_cons, List.sum_cons, List.length_cons]
    rw [Nat.add_mul, Nat.one_mul]
    omega

/-- 论文直接引用的形式：容量 × 箱子数 不小于 已装总体积。 -/
theorem capacity_bounds_total (C : Nat) (boxes : List (List Nat))
    (hcap : ∀ b ∈ boxes, b.sum ≤ C) :
    (boxes.map List.sum).sum ≤ boxes.length * C :=
  total_le C boxes hcap

/-! ## 二、易碎件置底的不可能性证明 -/

/-- 车型 2 的具体算例（单位 cm³）：

    - 车厢容积 = 680 × 245 × 250 = 41,650,000
    - 易碎件底面积 = 30 件 × 70 × 50 = 105,000
    - 可用高度 = 247 − 40 = 207（易碎件高 40，其上不可放货）
    - 因此易碎件置底时可用容积 = 41,650,000 − 105,000 × 207 = 19,915,000
    - 而货物总体积 = 28,735,000

    结论：19,915,000 < 28,735,000，故一辆车型 2 在"易碎件置底"前提下必然装不下。 -/
theorem fragile_on_floor_infeasible :
    (680 * 245 * 250 : Nat) - (30 * 70 * 50) * (247 - 40) < 28735000 := by
  decide

/-- 同一算例下，若易碎件置于顶层，死空间只剩顶部 3 cm 余隙：
    41,650,000 − 105,000 × 3 = 41,335,000 ≥ 28,735,000，故不构成结构性障碍。 -/
theorem fragile_on_top_feasible :
    (28735000 : Nat) ≤ (680 * 245 * 250) - (30 * 70 * 50) * 3 := by
  decide

end Boxpack

#check @Boxpack.total_le
#check @Boxpack.capacity_bounds_total
#check @Boxpack.fragile_on_floor_infeasible
#check @Boxpack.fragile_on_top_feasible
