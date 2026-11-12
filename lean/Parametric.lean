import Init.Data.Rat.Lemmas

/-
  参数化装箱的有理数阈值内核。
  LayoutProfile 不是三维布局：几何、接触、竖向传力到本摘要的正确性
  仍由纸面论证及 Python 检查承担。本文件不假设三维布局存在。
-/
namespace Boxpack.Parametric

structure Params where
  alpha : Rat
  pressure : Rat
  clearance : Rat

/-- 固定布局经外部几何和载荷核验后提取的三个阈值。 -/
structure LayoutProfile where
  alphaMax : Rat
  pressureMin : Rat
  clearanceMax : Rat

/-- strict 比 loose 更严格；固定其他数据、规则和目标。 -/
def Tightens (strict loose : Params) : Prop :=
  loose.alpha ≤ strict.alpha ∧ strict.pressure ≤ loose.pressure ∧
    loose.clearance ≤ strict.clearance

def InDomain (t : Params) : Prop :=
  0 ≤ t.alpha ∧ t.alpha ≤ 1 ∧ 0 ≤ t.pressure ∧ 0 ≤ t.clearance

/-- 仅为参数部分；base 可包含不依赖三个参数的全部几何/类型条件。 -/
def Admissible (r : LayoutProfile) (t : Params) : Prop :=
  t.alpha ≤ r.alphaMax ∧ r.pressureMin ≤ t.pressure ∧
    t.clearance ≤ r.clearanceMax

def Feasible {L : Type} (base : L → Prop) (profile : L → LayoutProfile)
    (t : Params) (x : L) : Prop :=
  InDomain t ∧ base x ∧ Admissible (profile x) t

theorem tightens_refl (t : Params) : Tightens t t :=
  ⟨Rat.le_refl, Rat.le_refl, Rat.le_refl⟩

theorem tightens_trans {a b c : Params} (hab : Tightens a b)
    (hbc : Tightens b c) : Tightens a c :=
  ⟨Rat.le_trans hbc.1 hab.1, Rat.le_trans hab.2.1 hbc.2.1,
    Rat.le_trans hbc.2.2 hab.2.2⟩

/-- 收紧参数不能让原来不满足阈值的同一布局变成可行。 -/
theorem admissible_mono {r : LayoutProfile} {strict loose : Params}
    (h : Tightens strict loose) (hs : Admissible r strict) :
    Admissible r loose :=
  ⟨Rat.le_trans h.1 hs.1, Rat.le_trans hs.2.1 h.2.1,
    Rat.le_trans h.2.2 hs.2.2⟩

/-- 参数域必须单独保持；不把域外宽松参数当成物理可用输入。 -/
theorem feasible_mono {L : Type} {base : L → Prop}
    {profile : L → LayoutProfile} {strict loose : Params} {x : L}
    (h : Tightens strict loose) (hd : InDomain loose)
    (hs : Feasible base profile strict x) : Feasible base profile loose x :=
  ⟨hd, hs.2.1, admissible_mono h hs.2.2⟩

/-- 对任意布局集合（例如有限保存池），存在见证的区域同样单调。 -/
theorem witness_mono {L : Type} {base : L → Prop}
    {profile : L → LayoutProfile} {strict loose : Params}
    (h : Tightens strict loose) (hd : InDomain loose)
    (hs : ∃ x, Feasible base profile strict x) :
    ∃ x, Feasible base profile loose x := by
  obtain ⟨x, hx⟩ := hs
  exact ⟨x, feasible_mono h hd hx⟩

/-- 最优点定义：存在可行见证且不劣于本域所有可行布局。 -/
def IsMinOn {L : Type} (F : L → Prop) (f : L → Rat) (x : L) : Prop :=
  F x ∧ ∀ y, F y → f x ≤ f y

/-- 任意可行域上，可行见证达到一个有效下界即可闭合最优性。 -/
theorem witness_lower_bound {L : Type} {F : L → Prop} {f : L → Rat}
    {x : L} {b : Rat} (hx : F x) (hlb : ∀ y, F y → b ≤ f y)
    (heq : f x = b) : IsMinOn F f x := by
  refine ⟨hx, ?_⟩
  intro y hy
  rw [heq]
  exact hlb y hy

/-- 两个目标分别在同一域闭合；不要求它们共享最优布局。 -/
theorem separate_objectives {L : Type} {F : L → Prop} {f g : L → Rat}
    {x y : L} {a b : Rat} (hx : F x) (hy : F y)
    (hf : ∀ z, F z → a ≤ f z) (hg : ∀ z, F z → b ≤ g z)
    (hfx : f x = a) (hgy : g y = b) :
    IsMinOn F f x ∧ IsMinOn F g y :=
  ⟨witness_lower_bound hx hf hfx, witness_lower_bound hy hg hgy⟩

/-- 若两域最优点均存在，可行域包含关系推出最优值的反向单调。
    不处理空域的扩展实数 inf，也不假设所有参数下都有最优点。 -/
theorem minimum_mono {L : Type} {Fs Fl : L → Prop} {f : L → Rat}
    {xs xl : L} (hsub : ∀ z, Fs z → Fl z)
    (hs : IsMinOn Fs f xs) (hl : IsMinOn Fl f xl) : f xl ≤ f xs :=
  hl.2 xs (hsub xs hs.1)

end Boxpack.Parametric

#print axioms Boxpack.Parametric.tightens_refl
#print axioms Boxpack.Parametric.tightens_trans
#print axioms Boxpack.Parametric.admissible_mono
#print axioms Boxpack.Parametric.feasible_mono
#print axioms Boxpack.Parametric.witness_mono
#print axioms Boxpack.Parametric.witness_lower_bound
#print axioms Boxpack.Parametric.separate_objectives
#print axioms Boxpack.Parametric.minimum_mono
