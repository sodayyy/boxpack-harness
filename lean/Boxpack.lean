import Parametric

/-
  三维装箱研究中的算术引理；只使用 Lean 4 核心库。
  注意：本文件不定义三维排布、接触、支撑或力学平衡。
  具体数值不等式不是完整装载存在性/不可行性的形式化证明。
-/
namespace Boxpack

/-- 每箱体积和不超过容量，则总体积不超过箱数乘容量。 -/
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

/-- 车辆容量下界的算术内核；容量假设由外部模型提供。 -/
theorem capacity_bounds_total (C : Nat) (boxes : List (List Nat))
    (hcap : ∀ b ∈ boxes, b.sum ≤ C) :
    (boxes.map List.sum).sum ≤ boxes.length * C :=
  total_le C boxes hcap

/-- 固定姿态、全部铺底且上方整柱留空情景的容量不等式。
    247 cm 为有效高度。几何到阴影柱容量的推导未在 Lean 中形式化；
    当前 C5 仅禁止直接承压，不自动蕴含整柱留空。 -/
theorem floor_shadow_capacity_insufficient :
    (680 * 245 * 247 : Nat) - (30 * 70 * 50) * (247 - 40) < 28735000 := by
  decide

/-- 仅比较总体积与有效车厢容量；正余量不证明三维装载存在。 -/
theorem effective_capacity_not_ruled_out :
    (28735000 : Nat) ≤ (680 * 245 * 247) := by
  decide

/-- 原300件：标称容量松弛已排除所有低于700元车队。
    具体三维布局满足体积容量的桥接仍由外部核验承担。 -/
theorem original_fleet_cost_lower (small large : Nat)
    (h : 28735000 ≤ 19404000 * small + 41650000 * large) :
    700 ≤ 450 * small + 700 * large := by
  omega

/-- 原300件非空运输至少使用一辆车。 -/
theorem original_fleet_count_lower (small large : Nat)
    (h : 28735000 ≤ 19404000 * small + 41650000 * large) :
    1 ≤ small + large := by
  omega

/-- 600件在3cm余隙下的两个独立容量下界。 -/
theorem doubled_fleet_lower (small large : Nat)
    (h : 57470000 ≤ 19139400 * small + 41150200 * large) :
    2 ≤ small + large ∧ 1150 ≤ 450 * small + 700 * large := by
  constructor
  · omega
  · by_cases hz : large = 0
    · subst large
      have hs : 3 ≤ small := by omega
      omega
    · by_cases ho : large = 1
      · subst large
        have hs : 1 ≤ small := by omega
        omega
      · have hl : 2 ≤ large := by omega
        omega

/-- 600件不能用三小车：仅为有效容量排除，不是一般几何判定。 -/
theorem doubled_three_small_excluded :
    (3 * 19139400 : Nat) < 57470000 := by decide

end Boxpack

#print axioms Boxpack.original_fleet_cost_lower
#print axioms Boxpack.original_fleet_count_lower
#print axioms Boxpack.doubled_fleet_lower
#print axioms Boxpack.doubled_three_small_excluded

#check @Boxpack.total_le
#check @Boxpack.capacity_bounds_total
#check @Boxpack.floor_shadow_capacity_insufficient
#check @Boxpack.effective_capacity_not_ruled_out
#print axioms Boxpack.total_le
#print axioms Boxpack.capacity_bounds_total
#print axioms Boxpack.floor_shadow_capacity_insufficient
#print axioms Boxpack.effective_capacity_not_ruled_out
