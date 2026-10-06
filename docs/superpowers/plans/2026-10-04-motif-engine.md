# Motif Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace MandalaForge's tiling-based pattern layer with a motif engine where cells hold trees of parametric closed motifs, rings have free division counts, and overflow and reaches are resolved against real geometry.

**Architecture:** A new `motifs/` package defines the motif contract and vocabulary. A `Composer` turns seed and settings into a serialisable `DesignPlan`. An `Assembler` runs two passes (draw and place, then resolve overflow, reaches and contact) into page-space polylines. `DesignGenerator` is rewired to plan, assemble, validate with the existing topology validator, and write explicit SVG paths. The old `smart_patterns/` and `pattern_generator.py` stay untouched until the acceptance gate.

**Tech Stack:** Python 3.10+, Shapely 2.1 (`STRtree`, `unary_union`, `LineString`, buffer), svgwrite, Flask, pytest.

**Spec:** `docs/superpowers/specs/2026-10-04-motif-engine-design.md`

## Global Constraints

- Determinism: same seed and parameters produce byte-identical plan JSON and SVG. No use of `hash()` on strings, no set iteration order in any decision, no `random` module globals.
- Cell space is unchanged: radial 0.0 inner boundary, 1.0 outer boundary; angular -1.0 left edge, 0.0 centreline, 1.0 right edge. Limits restrict cell space; they never rescale it.
- Ring and divider lines are never emitted as ink. No boundary inference anywhere.
- Validator thresholds are unchanged: `snap_tolerance=2.5`, `whisker_tolerance=5.0`, `pen_radius=2.0`, `min_region_area=20.0`.
- Stroke width per motif: `1.0 + 1.5 * (1.0 - complexity * 0.5)`.
- Per-ring division count: integer 4 to 24 inclusive. `ring_divisions` length must equal `num_rings`, else HTTP 400.
- Sequence length divides the ring's division count, is at most 4, and is strictly less than the count unless the count is 1.
- Tests run with `.venv/Scripts/python -m pytest -q`. Every commit leaves the suite green.
- Markdown files: no hard-wrapped prose (user rule). Commit messages end with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- `smart_patterns/`, `pattern_generator.py` and `docs/smart-patterns.md` are not edited by any task before Task 16.

## Review Focus

Inputs the spec implies but no task's tests would otherwise exercise. Each one has its test added to the owning task.

1. Narrowest cell the UI allows (7 rings, 24 divisions, complexity 0.9): every ring must still get a motif and validate, because the safe band has zero size gates. Owner: Task 11.
2. `min_pattern_size=50` (slider maximum): slots vanish and nesting is dropped silently, never raised. Owner: Task 11.
3. Odd and co-prime per-ring counts (`[7, 12]`, `[9, 9]`): plan sequences and assembly contact must work with no shared symmetry. Owners: Tasks 7 and 10.
4. Regenerating ring k must change ring k+1's reaches (they land on new ink) while leaving ring k+1's plan identical. Owner: Task 11.
5. Two consecutive regenerations of different rings must both survive, so prior ring seeds must round-trip through the API. Owner: Task 12.

---

### Task 0: Baseline commit and test scaffolding

The repository has no commits. The executor confirms with the user that the whole working tree is the intended baseline, then commits it so every later task has a diff.

**Files:**
- Create: `requirements.txt`
- Create: `tests/__init__.py` (empty)
- Create: `tests/conftest.py`
- Modify: `.gitignore` (add `.pytest_cache/`)

- [ ] **Step 1: Confirm the baseline with the user, then commit the existing tree**

```bash
git add -A
git commit -m "chore: baseline before motif engine"
```

- [ ] **Step 2: Install pytest and write `requirements.txt`**

Run: `.venv/Scripts/python -m pip install pytest`

`requirements.txt` lists: `flask`, `svgwrite`, `shapely>=2.0`, `svgelements`, `pytest`.

- [ ] **Step 3: Write `tests/conftest.py` with the shared cell fixture**

```python
import random
import pytest

@pytest.fixture
def cell_kwargs():
    # ring depth 60px, 30-degree wedge, cell ~68px wide at mid radius
    return dict(inner_radius=100.0, outer_radius=160.0, wedge_angle=30.0,
                center=(306.0, 306.0), stroke_width=1.5, complexity=0.5,
                min_white_space=10.0, rng=random.Random(7))
```

- [ ] **Step 4: Run the empty suite to prove the harness works**

Run: `.venv/Scripts/python -m pytest -q`
Expected: `no tests ran` with exit code 5 and no import errors.

- [ ] **Step 5: Commit**

```bash
git add requirements.txt tests .gitignore
git commit -m "chore: add pytest scaffolding and requirements"
```

---

### Task 1: Geometry module

**Files:**
- Create: `motifs/__init__.py` (empty for now; registry arrives in Task 3)
- Create: `motifs/geometry.py`
- Test: `tests/test_geometry.py`

**Interfaces:**
- Consumes: nothing new. Port `CellPoint`, `SmartVector`, `quad_points`, `mirror_points`, `MAX_SEGMENT_ARC_DEGREES`, and the pixel helpers from `smart_patterns/core.py` by copying, not importing, so the new package is self-contained.
- Produces:
  - `CellPoint(radial: float, angular: float)` frozen dataclass.
  - `SmartVector(points: List[CellPoint], closed: bool = False)`. No overshoot fields.
  - `MotifContext` dataclass with fields `inner_radius, outer_radius, wedge_angle, center, stroke_width, complexity, min_white_space, rng, position: str = "centre", angular_limits: float = 1.0, radial_limits: Tuple[float, float] = (0.0, 1.0), slot: Optional[List[CellPoint]] = None` and methods `ring_depth`, `half_angle`, `radius_at(radial)`, `radial_to_px(span)`, `px_to_radial(px)`, `angular_to_px(span, at_radial)`, `px_to_angular(px, at_radial)`, `cell_width_px(at_radial=0.5)`, `radial_for_cell_width(target_px, limit=0.5)`, `to_cartesian(point, rotation_deg=0.0) -> Tuple[float, float]`, `polyline(vector, rotation_deg=0.0) -> List[Tuple[float, float]]`, `make_path(vector, rotation_deg=0.0) -> Dict[str, Any]`.
  - `cell_rotation_deg(cell_index: int, divisions: int, position: str) -> float`.
  - `quad_points`, `mirror_points`, `MAX_SEGMENT_ARC_DEGREES = 4.0`.

Decisions the port must apply: `to_cartesian` no longer clamps radial or angular (the analyzer enforces limits; overflow is legitimate). `rotation_deg` is added to the angle before conversion. `polyline` performs the same arc subdivision as `make_path` and returns raw coordinates; `make_path` builds the SVG dict from `polyline`. `cell_rotation_deg` returns `cell_index * (360 / divisions)` for `centre` and adds half a wedge for `divider`.

- [ ] **Step 1: Write the failing tests**

```python
import math
from motifs.geometry import CellPoint, SmartVector, MotifContext, cell_rotation_deg

def test_to_cartesian_does_not_clamp_overflow(cell_kwargs):
    ctx = MotifContext(**cell_kwargs)
    x, y = ctx.to_cartesian(CellPoint(1.25, 0.0))
    assert math.isclose(math.hypot(x - 306, y - 306), 175.0, abs_tol=1e-6)

def test_rotation_moves_centreline(cell_kwargs):
    ctx = MotifContext(**cell_kwargs)
    x, y = ctx.to_cartesian(CellPoint(0.5, 0.0), rotation_deg=90.0)
    assert math.isclose(x, 306.0, abs_tol=1e-6) and math.isclose(y, 436.0, abs_tol=1e-6)

def test_polyline_subdivides_arc(cell_kwargs):
    ctx = MotifContext(**cell_kwargs)
    pts = ctx.polyline(SmartVector([CellPoint(0.5, -1.0), CellPoint(0.5, 1.0)]))
    assert len(pts) >= 8
    assert all(math.isclose(math.hypot(x - 306, y - 306), 130.0, abs_tol=0.05) for x, y in pts)

def test_cell_rotation_positions():
    assert cell_rotation_deg(2, 12, "centre") == 60.0
    assert cell_rotation_deg(2, 12, "divider") == 75.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_geometry.py -q`
Expected: FAIL with `ModuleNotFoundError: motifs.geometry`.

- [ ] **Step 3: Implement `motifs/geometry.py`**

Port from `smart_patterns/core.py` lines 403 to 590 and 1019 to 1050, applying the decisions above.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_geometry.py -q`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add motifs tests/test_geometry.py
git commit -m "feat(motifs): geometry module with limits-aware cell context"
```

---

### Task 2: Motif contract and analyzer

**Files:**
- Create: `motifs/contract.py`
- Test: `tests/test_contract.py`

**Interfaces:**
- Consumes: Task 1 geometry.
- Produces:
  - `ReachEnd(point: CellPoint, direction: str, max_length_px: float, style: str = "straight")`. `direction` in `{"inward", "outward"}`, `style` in `{"straight", "wavy"}`.
  - `Declaration(footprint: List[CellPoint], slot: Optional[List[CellPoint]], reach_ends: List[ReachEnd], base_point: CellPoint, overflow_inward: float, overflow_outward: float)`. Overflows are in cell units beyond 0.0 and 1.0, never negative.
  - `MotifInstance(vectors: List[SmartVector], declaration: Declaration, kind: str)`, `kind` in `{"enclosing", "open"}`.
  - `class MotifError(ValueError)`.
  - `measure_footprint(vectors) -> List[CellPoint]`: convex hull of all points via Shapely in cell space.
  - `measure_overflow(vectors) -> Tuple[float, float]`.
  - `measure_slot(context, outline: List[CellPoint]) -> Optional[List[CellPoint]]`: scale the outline to pixels (radial times `ring_depth`, angular times `angular_to_px(1.0, 0.5)`), negative-buffer by `min_white_space + stroke_width`, take the largest polygon if a MultiPolygon, scale back; `None` when empty.
  - `build_instance(context, vectors, reach_ends=(), slot_outline=None, base_point=None) -> MotifInstance`: measures the declaration, sets `kind`, runs the analyzer, raises `MotifError` listing issues. `base_point` defaults to the vertex with the lowest radial, ties broken by `abs(angular)`.
  - `MotifAnalyzer(context, tolerance=0.025).analyze(instance) -> List[str]` implementing spec 3.5. Port `_intersection_makes_tiny_space`, `_segment_intersection`, `_point_touches_segments` and `_physical_distance` from `smart_patterns/core.py`.

Analyzer rules, exactly: every open endpoint equals a `reach_end.point` within tolerance or lies within tolerance of a segment of another vector or a non-adjacent segment of its own vector; the slot polygon, if present, is at least `min_white_space` from every segment measured in pixels; crossings between vectors create no space under `min_white_space`; every point has `radial_limits[0] - tolerance <= radial <= radial_limits[1] + tolerance` and `abs(angular) <= angular_limits + tolerance`; an `open` instance with no reach ends is an issue.

- [ ] **Step 1: Write the failing tests**

```python
import pytest
from motifs.geometry import CellPoint, SmartVector, MotifContext
from motifs.contract import build_instance, MotifError, ReachEnd, measure_slot

def closed_box(lo, hi, w):
    return SmartVector([CellPoint(lo, -w), CellPoint(lo, w), CellPoint(hi, w), CellPoint(hi, -w)], closed=True)

def test_closed_box_is_enclosing(cell_kwargs):
    inst = build_instance(MotifContext(**cell_kwargs), [closed_box(0.1, 0.9, 0.6)])
    assert inst.kind == "enclosing"
    assert inst.declaration.base_point == CellPoint(0.1, -0.6) or inst.declaration.base_point == CellPoint(0.1, 0.6)

def test_open_end_without_reach_is_rejected(cell_kwargs):
    with pytest.raises(MotifError, match="open end"):
        build_instance(MotifContext(**cell_kwargs), [SmartVector([CellPoint(0.2, 0.0), CellPoint(0.8, 0.0)])])

def test_open_end_declared_as_reach_is_accepted(cell_kwargs):
    reach = ReachEnd(CellPoint(0.0, 0.0), "inward", 40.0)
    inst = build_instance(MotifContext(**cell_kwargs),
                          [closed_box(0.0, 0.9, 0.6)], reach_ends=[reach])
    assert inst.declaration.reach_ends == [reach]

def test_radial_limit_violation_is_rejected(cell_kwargs):
    ctx = MotifContext(**cell_kwargs, radial_limits=(0.0, 1.0))
    with pytest.raises(MotifError, match="radial"):
        build_instance(ctx, [closed_box(0.1, 1.2, 0.6)])

def test_angular_limit_violation_is_rejected(cell_kwargs):
    ctx = MotifContext(**cell_kwargs, angular_limits=0.5)
    with pytest.raises(MotifError, match="angular"):
        build_instance(ctx, [closed_box(0.1, 0.9, 0.8)])

def test_slot_is_inset_and_clear(cell_kwargs):
    ctx = MotifContext(**cell_kwargs)
    outline = closed_box(0.0, 1.0, 1.0).points
    slot = measure_slot(ctx, outline)
    assert slot is not None
    assert all(0.15 < p.radial < 0.85 for p in slot)

def test_slot_vanishes_when_margin_exceeds_shape(cell_kwargs):
    ctx = MotifContext(**{**cell_kwargs, "min_white_space": 50.0})
    assert measure_slot(ctx, closed_box(0.0, 1.0, 1.0).points) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_contract.py -q`
Expected: FAIL with `ModuleNotFoundError: motifs.contract`.

- [ ] **Step 3: Implement `motifs/contract.py`**

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_contract.py -q`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add motifs/contract.py tests/test_contract.py
git commit -m "feat(motifs): motif contract, measured declaration, analyzer"
```

---

### Task 3: Registry, petal, diamond, safe band

**Files:**
- Modify: `motifs/__init__.py`
- Create: `motifs/botanical.py`
- Create: `motifs/geometric.py`
- Create: `motifs/fallback.py`
- Test: `tests/test_motifs.py`

**Interfaces:**
- Consumes: Tasks 1 and 2.
- Produces:
  - Generator signature for every motif: `def generate_<name>(context: MotifContext) -> MotifInstance`.
  - Registry entry keys: `name, category, generator, positions, roles, touch, spans_cell, min_cell_width_px, min_ring_depth_px, max_overflow_inward, max_overflow_outward, slot_estimate` where `slot_estimate` is `(width_fraction, depth_fraction)` of the cell a slot child can expect, or `None`.
  - `motifs.MOTIFS: List[Dict]`, `motifs.motifs_for_categories(categories: List[str]) -> List[Dict]`, `motifs.find_motif(name: str) -> Optional[Dict]`, `motifs.safe_motif(category: str) -> Dict` returning an entry named `f"{category}_safe_band"` with `is_safe_fallback=True`.

Motif definitions. All parameters are drawn from `context.rng`; all pixel sizes respect `min_white_space`.

`petal` (botanical; positions centre and divider; roles base and slot; touch True; min cell 14px, min depth 18px; overflow in 0.25, out 0.25; slot_estimate (0.5, 0.5)). Draw `length` in `[0.75, 1.25]`, `dip` in `[0.0, 0.25]`, `half_width = angular_limits * uniform(0.55, 0.95)`, `waist` in `[0.35, 0.6]`, `wave` in `[0.0, complexity * 0.06]`. Base at `(max(radial_limits[0], -dip), 0.0)`, tip at `(min(radial_limits[1], length), 0.0)`. Outline: `quad_points(base, control, widest)` then `quad_points(widest, control2, tip)` on the right side, where widest is `(base.radial + (tip.radial - base.radial) * waist, half_width)`, mirrored for the left side, closed. When `wave > 0` add `wave * sin(3 * pi * t)` to the angular of interior samples. When the context has a `slot`, scale so the footprint fits inside the slot's bounding box in cell space with a margin of `px_to_radial(min_white_space)` radially and the equivalent angular margin at the slot's mid radial. Slot outline is the petal outline. Reach ends: none.

`diamond` (geometric; centre; slot only; touch False; min cell 10px, min depth 10px; no overflow; slot_estimate None). Four points at the slot's bounding box inset by the margin above; aspect drawn in `[0.6, 1.0]` of the available height. Requires `context.slot`; raises `MotifError` without one.

`safe_band` (per category via `safe_motif`; positions centre and divider; base; touch True; spans_cell True; zero gates; no overflow). Closed quadrilateral `(0.4, -L), (0.4, L), (0.6, L), (0.6, -L)` with `L = angular_limits`. No randomness.

- [ ] **Step 1: Write the failing tests, including the property tests that every later motif inherits**

```python
import random
import pytest
from motifs import MOTIFS, find_motif, safe_motif, motifs_for_categories
from motifs.geometry import MotifContext, CellPoint
from motifs.contract import MotifInstance, MotifError

def make_ctx(cell_kwargs, seed=7, **over):
    kw = {**cell_kwargs, "rng": random.Random(seed), **over}
    return MotifContext(**kw)

def slot_for(cell_kwargs):
    return [CellPoint(0.2, -0.4), CellPoint(0.2, 0.4), CellPoint(0.8, 0.4), CellPoint(0.8, -0.4)]

def all_entries():
    return MOTIFS + [safe_motif("botanical")]

def generate(entry, ctx, cell_kwargs):
    if "base" not in entry["roles"]:
        ctx.slot = slot_for(cell_kwargs)
    return entry["generator"](ctx)

@pytest.mark.parametrize("entry", all_entries(), ids=lambda e: e["name"])
def test_motif_is_deterministic(entry, cell_kwargs):
    a = generate(entry, make_ctx(cell_kwargs, 11), cell_kwargs)
    b = generate(entry, make_ctx(cell_kwargs, 11), cell_kwargs)
    assert [v.points for v in a.vectors] == [v.points for v in b.vectors]

@pytest.mark.parametrize("entry", all_entries(), ids=lambda e: e["name"])
def test_motif_respects_narrow_limits(entry, cell_kwargs):
    ctx = make_ctx(cell_kwargs, 3, radial_limits=(0.0, 1.0), angular_limits=0.5)
    inst = generate(entry, ctx, cell_kwargs)
    assert all(-0.03 <= p.radial <= 1.03 and abs(p.angular) <= 0.53 for v in inst.vectors for p in v.points)

@pytest.mark.parametrize("entry", all_entries(), ids=lambda e: e["name"])
def test_narrower_radial_limits_never_reach_further(entry, cell_kwargs):
    wide = generate(entry, make_ctx(cell_kwargs, 5, radial_limits=(-0.25, 1.25)), cell_kwargs)
    narrow = generate(entry, make_ctx(cell_kwargs, 5, radial_limits=(-0.1, 1.1)), cell_kwargs)
    hi = lambda inst: max(p.radial for v in inst.vectors for p in v.points) if inst.vectors else 0
    lo = lambda inst: min(p.radial for v in inst.vectors for p in v.points) if inst.vectors else 0
    assert hi(narrow) <= hi(wide) + 1e-9 and lo(narrow) >= lo(wide) - 1e-9

@pytest.mark.parametrize("entry", [e for e in all_entries() if e["slot_estimate"]], ids=lambda e: e["name"])
def test_declared_slot_is_present_at_default_size(entry, cell_kwargs):
    inst = generate(entry, make_ctx(cell_kwargs, 9), cell_kwargs)
    assert inst.declaration.slot is not None

def test_registry_lookup():
    assert find_motif("petal")["category"] == "botanical"
    assert find_motif("nope") is None
    assert {e["name"] for e in motifs_for_categories(["geometric"])} == {"diamond"}
    assert safe_motif("celtic")["name"] == "celtic_safe_band"

def test_diamond_requires_slot(cell_kwargs):
    with pytest.raises(MotifError):
        find_motif("diamond")["generator"](make_ctx(cell_kwargs))

def test_safe_band_spans_angular_limits(cell_kwargs):
    inst = safe_motif("botanical")["generator"](make_ctx(cell_kwargs, angular_limits=0.7))
    angs = {round(p.angular, 6) for p in inst.vectors[0].points}
    assert angs == {-0.7, 0.7}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_motifs.py -q`
Expected: FAIL with `ImportError: cannot import name 'MOTIFS'`.

- [ ] **Step 3: Implement the registry in `motifs/__init__.py` and the three motifs**

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_motifs.py -q`
Expected: all passed (15 parametrised cases plus 3).

- [ ] **Step 5: Commit**

```bash
git add motifs tests/test_motifs.py
git commit -m "feat(motifs): registry with petal, diamond and safe band"
```

---

### Task 4: Leaf, ring band, scallop, stem

**Files:**
- Modify: `motifs/botanical.py` (leaf, scallop, stem)
- Modify: `motifs/geometric.py` (ring_band)
- Modify: `motifs/__init__.py` (register)
- Test: `tests/test_motifs.py` (the parametrised tests pick the new entries up; add the three targeted tests below)

**Interfaces:**
- Consumes: Task 3 registry conventions.
- Produces: four more registry entries. Downstream tasks reference `ring_band` as the known-good `spans_cell` base and `stem` as the known-good reach attachment.

`leaf` (botanical; centre; base and slot; touch True; min cell 14px, depth 20px; overflow out 0.15, in 0.0; slot_estimate None). Closed outline: corners `(0.0, ±half_width)`, apex `(min(radial_limits[1], length), 0.0)` with `length` in `[0.85, 1.15]`, edges via `quad_points` with roundness in `[0.25, 1.1]`. Midrib: open vector from `(0.0, 0.0)` to the apex; both ends lie on outline vertices, so the analyzer accepts it. The midrib runs through the interior, so the leaf declares no slot.

`ring_band` (geometric; centre and divider; base; touch True; spans_cell True; zero gates; no overflow; slot_estimate None). Closed quadrilateral with `r1` in `[0.30, 0.45]`, `r2` in `[0.55, 0.70]`, spanning `±angular_limits`. Any two draws overlap radially within `[0.45, 0.55]`, which is what makes neighbouring cells touch along a shared radial edge. Optional rung from `(r1, 0)` to `(r2, 0)` when `complexity >= 0.5`.

`scallop` (botanical; divider; base; touch True; spans_cell True; min cell 12px, depth 16px; overflow in 0.3, out 0.0; slot_estimate None). Closed: top edge at `r_top` in `[0.5, 0.6]` spanning `±angular_limits`, side edges down to `r_top - 0.2`, bottom edge a `quad_points` arc dipping to `max(radial_limits[0], -dip)` at angular 0 with `dip` in `[0.1, 0.3]`.

`stem` (botanical; centre and divider; role `attachment`; touch True; zero gates; no overflow; slot_estimate None). Emits no vectors. Declares one `ReachEnd(point=CellPoint(0.0, 0.0), direction="inward", max_length_px=context.ring_depth * 0.9, style="wavy" if complexity >= 0.6 else "straight")`. `kind` is `open`. `build_instance` must accept an instance with no vectors when it has a reach end; its footprint is the single point.

- [ ] **Step 1: Write the three targeted tests**

```python
def test_leaf_midrib_touches_outline(cell_kwargs):
    inst = find_motif("leaf")["generator"](make_ctx(cell_kwargs))
    assert inst.kind == "enclosing" and len(inst.vectors) == 2

def test_ring_band_draws_overlap_in_shared_range(cell_kwargs):
    gen = find_motif("ring_band")["generator"]
    for seed in range(20):
        pts = gen(make_ctx(cell_kwargs, seed)).vectors[0].points
        rs = sorted({p.radial for p in pts})
        assert rs[0] <= 0.45 and rs[-1] >= 0.55

def test_stem_is_a_pure_reach(cell_kwargs):
    inst = find_motif("stem")["generator"](make_ctx(cell_kwargs))
    assert inst.vectors == [] and inst.kind == "open"
    assert inst.declaration.reach_ends[0].direction == "inward"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_motifs.py -q`
Expected: the three new tests FAIL with `TypeError: 'NoneType'` from `find_motif`.

- [ ] **Step 3: Implement the four motifs and register them**

- [ ] **Step 4: Run the full motif suite**

Run: `.venv/Scripts/python -m pytest tests/test_motifs.py -q`
Expected: all passed, parametrised cases now cover 8 entries.

- [ ] **Step 5: Commit**

```bash
git add motifs tests/test_motifs.py
git commit -m "feat(motifs): leaf, ring band, scallop and stem"
```

---

### Task 5: Topology validator additions

**Files:**
- Modify: `topology_validator.py:149-160` (analyze signature) and the issues block around line 230
- Test: `tests/test_topology_additions.py`

**Interfaces:**
- Consumes: existing `TopologyValidator`.
- Produces:
  - `structural_components(polylines: Sequence[Sequence[Coord]], touch_tolerance: float = 0.01) -> List[int]`: union-find over input polylines, joining two when their LineStrings are within `touch_tolerance` (STRtree query with `dwithin`). Returns a component id per polyline, ids assigned in first-seen order.
  - `TopologyValidator.analyze(polylines, exempt_dangle_fn=None, center=None, divisions=None, base_mask: Optional[Sequence[bool]] = None, overflow_parts: Optional[Sequence[Tuple[int, LineString]]] = None, ring_ids: Optional[Sequence[int]] = None) -> TopologyReport`.
  - New stats keys: `num_floating_base`, `num_overflow_crossings`. New issue strings start with `Floating base motif near (` and `Overflow crosses ring `.

Rules: with `base_mask`, the base polylines must all share one component id from `structural_components`; every base polyline outside the largest base component is a floating base. With `overflow_parts` and `ring_ids`, each overflow LineString tagged with ring `r` is tested against the polylines whose `ring_ids` differ from `r`; an intersection whose geometry is not exactly one of the overflow line's two endpoints counts as a crossing.

- [ ] **Step 1: Write the failing tests**

```python
from shapely.geometry import LineString
from topology_validator import TopologyValidator, structural_components

SQ = lambda x: [(x, 0), (x + 10, 0), (x + 10, 10), (x, 10), (x, 0)]

def test_structural_components_groups_touching_lines():
    ids = structural_components([SQ(0), SQ(10), SQ(50)])
    assert ids[0] == ids[1] != ids[2]

def test_floating_base_reported():
    report = TopologyValidator().analyze([SQ(0), SQ(10), SQ(50)], base_mask=[True, True, True])
    assert report.stats["num_floating_base"] == 1
    assert any(i.startswith("Floating base motif") for i in report.issues)

def test_slot_island_is_not_floating_base():
    report = TopologyValidator().analyze([SQ(0), SQ(10), SQ(50)], base_mask=[True, True, False])
    assert report.stats["num_floating_base"] == 0

def test_overflow_crossing_detected():
    lines = [SQ(0), [(5, -20), (5, 20)]]
    report = TopologyValidator().analyze(
        lines, ring_ids=[0, 1], overflow_parts=[(1, LineString([(5, -20), (5, 20)]))])
    assert report.stats["num_overflow_crossings"] == 1

def test_overflow_touch_at_endpoint_is_allowed():
    lines = [SQ(0), [(5, -20), (5, 0)]]
    report = TopologyValidator().analyze(
        lines, ring_ids=[0, 1], overflow_parts=[(1, LineString([(5, -20), (5, 0)]))])
    assert report.stats["num_overflow_crossings"] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_topology_additions.py -q`
Expected: FAIL with `ImportError: structural_components`.

- [ ] **Step 3: Implement the additions**

- [ ] **Step 4: Run the new tests and the existing QA script on one old design to prove nothing regressed**

Run: `.venv/Scripts/python -m pytest tests/test_topology_additions.py -q`
Expected: 5 passed.

Run: `.venv/Scripts/python qa_report.py --seeds 42 --overlays never`
Expected: `1/1 designs passed` (the old engine still drives this script until Task 14).

- [ ] **Step 5: Commit**

```bash
git add topology_validator.py tests/test_topology_additions.py
git commit -m "feat(validator): structural connectivity and overflow discipline checks"
```

---

### Task 6: Composer data model and serialisation

**Files:**
- Create: `composer.py`
- Test: `tests/test_composer_model.py`

**Interfaces:**
- Consumes: Task 3 registry (`find_motif`, `safe_motif`).
- Produces:
  - `CellRecipe(motif: str, category: str, slot_child: Optional[CellRecipe] = None, attachments: List[CellRecipe] = [], is_fallback: bool = False, provides_contact: bool = False, dropped: bool = False)` with `to_dict()` and `CellRecipe.from_dict(d)`.
  - `CellEntry(centre: Optional[CellRecipe], divider: Optional[CellRecipe])` with the same pair of methods.
  - `RingPlan(ring_index: int, divisions: int, centre_share: float, sequence: List[CellEntry], ring_seed: int)` with `to_dict` and `from_dict`.
  - `DesignPlan(seed: int, style: Dict[str, Any], rings: List[RingPlan])` with `to_dict`, `from_dict`, `to_json() -> str` (sorted keys) and `DesignPlan.from_json(text)`. All four are plain dataclasses, so `==` compares structurally.
  - `node_rng(seed: int, ring_index: int, seq_pos: int, depth: int, position: str) -> random.Random` seeded with `seed * 1_000_003 + ring_index * 10_007 + seq_pos * 101 + depth * 11 + (0 if position == "centre" else 1)`.

- [ ] **Step 1: Write the failing tests**

```python
import random
from composer import CellRecipe, CellEntry, RingPlan, DesignPlan, node_rng

def test_plan_round_trips_through_json():
    leaf = CellRecipe("petal", "botanical", slot_child=CellRecipe("diamond", "geometric"),
                      attachments=[CellRecipe("stem", "botanical", provides_contact=True)])
    plan = DesignPlan(5, {"categories": ["botanical"], "positions": "both"},
                      [RingPlan(0, 8, 0.6, [CellEntry(leaf, None)], 5)])
    assert DesignPlan.from_json(plan.to_json()) == plan

def test_node_rng_is_stable_and_distinct():
    assert node_rng(1, 0, 0, 0, "centre").random() == node_rng(1, 0, 0, 0, "centre").random()
    assert node_rng(1, 0, 0, 0, "centre").random() != node_rng(1, 0, 0, 0, "divider").random()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_composer_model.py -q`
Expected: FAIL with `ModuleNotFoundError: composer`.

- [ ] **Step 3: Implement the dataclasses and `node_rng` in `composer.py`**

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_composer_model.py -q`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add composer.py tests/test_composer_model.py
git commit -m "feat(composer): plan data model and seeded node streams"
```

---

### Task 7: Composer planning

**Files:**
- Modify: `composer.py`
- Test: `tests/test_composer.py`

**Interfaces:**
- Consumes: Task 6 model, Task 3 registry.
- Produces:
  - `ComposerSettings(num_divisions: int = 12, vary_divisions: bool = False, ring_divisions: Optional[List[int]] = None, complexity: float = 0.5, min_pattern_size: float = 10.0, categories: List[str] = ["botanical"], force_motif: Optional[Dict[str, str]] = None)`. `force_motif` keys: `name`, `position` (`centre`/`divider`/`both`), `role` (`base`/`slot`/`contact`).
  - `Composer(seed: int, ring_geometry: List[Dict[str, float]], settings: ComposerSettings)` where each geometry dict has `inner_radius` and `outer_radius`.
  - `Composer.plan() -> DesignPlan`.
  - `Composer.plan_ring(ring_index: int, ring_seed: int) -> RingPlan`.
  - `Composer.replace_node(ring: RingPlan, seq_pos: int, position: str, reason: str) -> bool`: applies the fallback chain of spec 4.4 in place; returns `False` when exhausted.
  - `Composer.divisor_candidates(count: int) -> List[int]`.

Pinned rules, in `plan_ring` order:

1. Division count: `ring_divisions[i]` if given; else if `vary_divisions`, `clamp(round(num_divisions * scale * rng.triangular(0.7, 1.3, 1.0)), 4, 24)` with `scale = 0.5 + 0.5 * (mid_radius / outermost_mid_radius)`; else `num_divisions`. Every draw in `plan_ring` uses streams from `node_rng(ring_seed, ring_index, seq_pos, depth, position)`; `plan()` calls `plan_ring(i, seed)` for each ring, so `ring_seed == seed` unless a ring was regenerated.
2. Sequence length: candidates are divisors `d` of the count with `d <= 4` and `d < count`; `1` is always present. Weight `1` for `d == 1`, `complexity` for others. Complexity `0.0` always yields `1`.
3. Position mode: style's preferred mode gets weight `0.6`, the other two `0.2` each. `both` is only eligible when `cell_width_px(0.5) >= 2 * 14.0`; otherwise fall back to `centre`. When `both`, `centre_share = rng.uniform(0.45, 0.75)`; else `centre_share = 1.0`.
4. Per entry and position: candidate base motifs are registry entries in the enabled categories with `"base" in roles` and the position in `positions`, whose gates pass for the position's budget: `min_cell_width_px <= cell_width_px(0.5) * budget` where budget is `centre_share` or `1 - centre_share`, and `min_ring_depth_px <= ring_depth`. Pick with `rng.choice` after applying the variety filter (drop the inward ring's base names when alternatives remain). If none pass, use `safe_motif(category)` for the first enabled category with `is_fallback=True`.
5. Nesting: if the chosen motif has a `slot_estimate` and `rng.random() < complexity * (0.5 ** depth)` for `depth` starting at 0, pick a slot child from entries with `"slot" in roles` whose gates pass for `(cell_width_px * budget * width_fraction, ring_depth * depth_fraction)`. Recurse to a total depth of 3 nodes.
6. Contact per base motif: `provides_contact` is set when the motif's `max_overflow_inward >= 0.1`, or `spans_cell` is true and some other entry in the ring already provides inward contact, or an attachment is added: `CellRecipe("stem", "botanical", provides_contact=True)` from the enabled categories' first `attachment`-role motif. Rings other than the innermost must end with at least one entry whose base has inward overflow or a reach. The innermost ring uses only `spans_cell` candidates for its bases; when none is enabled, `safe_motif`.
7. Style, drawn once in `plan()` with `node_rng(seed, -1, 0, 0, "centre")`: `{"categories": <non-empty subset of enabled>, "positions": <one of centre|divider|both>}`.
8. `force_motif` applies to every ring except the innermost, which is always planned normally so the structure has an anchor. It replaces step 4's pick with the named motif in the named position(s); when `role == "slot"` it places the motif as the slot child of a `petal` base; when `role == "contact"` it replaces the attachment and the base is `petal` with no inward overflow. Size gates are skipped for the forced motif. `replace_node` returns `False` immediately when `force_motif` is set, so a rejection surfaces.

- [ ] **Step 1: Write the failing tests**

```python
import pytest
from composer import Composer, ComposerSettings

GEOM = [dict(inner_radius=20 + 60 * i, outer_radius=80 + 60 * i) for i in range(4)]

def plan_for(**over):
    settings = ComposerSettings(**{"categories": ["botanical", "geometric"], **over})
    return Composer(123, GEOM, settings).plan()

def test_plan_is_deterministic():
    assert plan_for().to_json() == plan_for().to_json()

def test_uniform_divisions_by_default():
    assert [r.divisions for r in plan_for(num_divisions=10).rings] == [10, 10, 10, 10]

def test_ring_divisions_override():
    assert [r.divisions for r in plan_for(ring_divisions=[8, 8, 8, 12]).rings] == [8, 8, 8, 12]

def test_vary_divisions_stays_in_range_and_varies_somewhere():
    seen = set()
    for seed in range(10):
        p = Composer(seed, GEOM, ComposerSettings(vary_divisions=True, categories=["botanical"])).plan()
        for r in p.rings:
            assert 4 <= r.divisions <= 24
            seen.add(r.divisions)
    assert len(seen) > 1

def test_sequence_length_divides_count_and_is_bounded():
    for seed in range(10):
        p = Composer(seed, GEOM, ComposerSettings(complexity=1.0, ring_divisions=[9, 7, 12, 6],
                                                   categories=["botanical", "geometric"])).plan()
        for r in p.rings:
            n = len(r.sequence)
            assert r.divisions % n == 0 and n <= 4 and n < r.divisions

def test_complexity_zero_gives_single_entry_and_no_nesting():
    p = plan_for(complexity=0.0)
    for r in p.rings:
        assert len(r.sequence) == 1
        for e in r.sequence:
            for node in (e.centre, e.divider):
                assert node is None or node.slot_child is None

def test_every_base_has_a_contact_route():
    p = plan_for(complexity=0.8)
    for r in p.rings:
        for e in r.sequence:
            for node in (e.centre, e.divider):
                if node is not None:
                    assert node.provides_contact or any(a.provides_contact for a in node.attachments)

def test_innermost_ring_uses_spans_cell_bases():
    from motifs import find_motif, safe_motif
    p = plan_for()
    for e in p.rings[0].sequence:
        for node in (e.centre, e.divider):
            if node is not None:
                entry = find_motif(node.motif) or safe_motif(node.category)
                assert entry["spans_cell"]

def test_plan_ring_with_new_seed_leaves_other_rings_equal():
    c = Composer(123, GEOM, ComposerSettings(categories=["botanical"]))
    base = c.plan()
    again = c.plan()
    again.rings[2] = c.plan_ring(2, 999)
    assert again.rings[:2] == base.rings[:2]
    assert again.rings[3] == base.rings[3]
    assert again.rings[2] != base.rings[2]

def test_force_motif_as_slot_child():
    p = plan_for(force_motif={"name": "diamond", "position": "centre", "role": "slot"})
    assert p.rings[1].sequence[0].centre.slot_child.motif == "diamond"

def test_force_motif_disables_fallback():
    c = Composer(1, GEOM, ComposerSettings(force_motif={"name": "petal", "position": "centre", "role": "base"}))
    ring = c.plan().rings[1]
    assert c.replace_node(ring, 0, "centre", "test") is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_composer.py -q`
Expected: FAIL with `ImportError: Composer`.

- [ ] **Step 3: Implement `ComposerSettings`, `Composer.plan`, `plan_ring`, `replace_node`, `divisor_candidates`**

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_composer.py -q`
Expected: 11 passed.

- [ ] **Step 5: Commit**

```bash
git add composer.py tests/test_composer.py
git commit -m "feat(composer): deterministic ring planning with contact routes"
```

---

### Task 8: Assembler pass one

**Files:**
- Create: `assembler.py`
- Test: `tests/test_assembler_pass_one.py`

**Interfaces:**
- Consumes: Tasks 1 to 4, 6, 7.
- Produces:
  - `PlacedPath(ring_index: int, cell_index: int, position: str, node_path: Tuple[int, ...], role: str, coords: List[Tuple[float, float]], radials: List[float], closed: bool, stroke_width: float)`. `role` in `{"base", "slot", "reach"}`. `radials` is the cell-space radial of each coordinate (interpolated through subdivision), so overflow portions can be derived.
  - `PlacedNode(ring_index, cell_index, position, node_path, recipe: CellRecipe, rng_seed: int, instance: MotifInstance, paths: List[PlacedPath], context: MotifContext, parent: Optional[PlacedNode])`.
  - `InkIndex` with `add(path: PlacedPath)`, `remove(path)`, `rebuild()`, `candidates(geom) -> List[PlacedPath]`, `first_hit(ray: LineString, exclude: Callable[[PlacedPath], bool]) -> Optional[Tuple[PlacedPath, Tuple[float, float], float]]` returning the nearest intersection point along the ray and its distance.
  - `AssembledDesign(plan: DesignPlan, paths: List[PlacedPath], nodes: List[PlacedNode], reaches: List[PlacedPath], dropped_children: int)` with `polylines()`, `base_mask()`, `ring_ids()`, `overflow_parts() -> List[Tuple[int, LineString]]`.
  - `Assembler(plan: DesignPlan, ring_geometry: List[Dict[str, float]], center: Tuple[float, float], complexity: float, min_white_space: float, composer: Composer)` with `pass_one() -> None`, `assemble() -> AssembledDesign` (pass one then pass two; pass two arrives in Task 9).
  - `stroke_width_for(complexity: float) -> float` returning `1.0 + 1.5 * (1.0 - complexity * 0.5)`.
  - `class AssemblyError(ValueError)`.

Pass one rules: iterate rings innermost to outermost, cells in index order, positions centre then divider. Build the position's `MotifContext` with `position`, `angular_limits` from `centre_share`, `radial_limits = (-max_overflow_inward, 1 + max_overflow_outward)` from the registry entry, `rng = node_rng(ring.ring_seed, ring_index, seq_pos, depth, position)`, `stroke_width = stroke_width_for(complexity)`. Rotation is `cell_rotation_deg(cell_index, divisions, position)`. For a slot child, pass `slot = parent.instance.declaration.slot`; when the parent has no slot, or the child's generator raises `MotifError`, mark the child recipe `dropped=True`, increment `dropped_children`, and continue. When a base generator raises `MotifError`, call `composer.replace_node(...)` and retry up to 3 times, then raise `AssemblyError`. Attachments are not generated in pass one; their reach ends are recorded on the parent node as `(ReachEnd, page_point, rotation_deg)` by calling the attachment generator with the parent's context and keeping only the declaration.

- [ ] **Step 1: Write the failing tests**

```python
import math
from assembler import Assembler, stroke_width_for
from composer import Composer, ComposerSettings, CellRecipe, CellEntry, RingPlan, DesignPlan

GEOM = [dict(inner_radius=40, outer_radius=100), dict(inner_radius=100, outer_radius=170)]
CENTER = (306.0, 306.0)

def manual_plan(divs=(8, 12)):
    inner = RingPlan(0, divs[0], 1.0, [CellEntry(CellRecipe("ring_band", "geometric", provides_contact=True), None)], 1)
    outer = RingPlan(1, divs[1], 1.0, [CellEntry(CellRecipe("petal", "botanical",
                     slot_child=CellRecipe("diamond", "geometric"),
                     attachments=[CellRecipe("stem", "botanical", provides_contact=True)]), None)], 1)
    return DesignPlan(1, {"categories": ["botanical", "geometric"], "positions": "centre"}, [inner, outer])

def build(plan):
    composer = Composer(1, GEOM, ComposerSettings(categories=["botanical", "geometric"]))
    a = Assembler(plan, GEOM, CENTER, 0.5, 10.0, composer)
    a.pass_one()
    return a

def test_stroke_width_formula():
    assert stroke_width_for(0.0) == 2.5 and stroke_width_for(1.0) == 1.75

def test_pass_one_places_every_cell():
    a = build(manual_plan())
    bases = {(n.ring_index, n.cell_index) for n in a.nodes if len(n.node_path) == 1}
    assert len([c for c in bases if c[0] == 0]) == 8 and len([c for c in bases if c[0] == 1]) == 12

def test_cells_are_rotated_to_their_angle():
    a = build(manual_plan())
    node = next(n for n in a.nodes if n.ring_index == 1 and n.cell_index == 3 and len(n.node_path) == 1)
    xs = [x for x, y in node.paths[0].coords]; ys = [y for x, y in node.paths[0].coords]
    cx, cy = sum(xs) / len(xs) - CENTER[0], sum(ys) / len(ys) - CENTER[1]
    assert math.isclose(math.degrees(math.atan2(cy, cx)) % 360, 90.0, abs_tol=3.0)

def test_slot_child_is_placed_inside_parent_slot():
    a = build(manual_plan())
    child = next(n for n in a.nodes if n.recipe.motif == "diamond")
    assert child.parent.recipe.motif == "petal" and not child.recipe.dropped

def test_slot_child_dropped_when_margin_too_large():
    composer = Composer(1, GEOM, ComposerSettings(categories=["botanical", "geometric"]))
    a = Assembler(manual_plan(), GEOM, CENTER, 0.5, 50.0, composer)
    a.pass_one()
    assert a.dropped_children == 12

def test_reach_ends_recorded_but_not_drawn():
    a = build(manual_plan())
    assert not any(p.role == "reach" for p in a.paths)
    assert len(a.pending_reaches) == 12

def test_radials_track_overflow():
    a = build(manual_plan())
    petal = next(n for n in a.nodes if n.recipe.motif == "petal")
    assert max(petal.paths[0].radials) == max(p.radial for v in petal.instance.vectors for p in v.points)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_assembler_pass_one.py -q`
Expected: FAIL with `ModuleNotFoundError: assembler`.

- [ ] **Step 3: Implement pass one in `assembler.py`**

Expose `nodes`, `paths`, `pending_reaches` and `dropped_children` as attributes on `Assembler` after `pass_one`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_assembler_pass_one.py -q`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add assembler.py tests/test_assembler_pass_one.py
git commit -m "feat(assembler): pass one draws, places and indexes motifs"
```

---

### Task 9: Assembler pass two

**Files:**
- Modify: `assembler.py`
- Test: `tests/test_assembler_pass_two.py`

**Interfaces:**
- Consumes: Task 8, Task 5 `structural_components`.
- Produces: `Assembler.pass_two() -> None`, `Assembler.assemble() -> AssembledDesign`, and three helpers used by tests: `resolve_overflow(node: PlacedNode, side: str) -> None` (`side` in `inward`/`outward`), `resolve_reach(node, reach_end, page_point, rotation_deg) -> Optional[PlacedPath]`, `floating_base_cells() -> List[Tuple[int, int, str]]`.

Algorithms the signatures do not determine:

**Overflow resolution** for a node whose `radials` leave `[0, 1]` on `side`:
1. Build the overflow LineStrings from the node's paths (sub-runs where radial is below 0 for inward, above 1 for outward, split at the exact crossing by interpolation).
2. Neighbour ink is every `PlacedPath` of ring `r - 1` (inward) or `r + 1` (outward). Innermost inward and outermost outward return immediately with no change.
3. If no overflow LineString intersects neighbour ink, return.
4. Otherwise binary search the limit: `clear = 0.0` (or `1.0`), `cross = current limit`; for up to 10 iterations set `mid = (clear + cross) / 2`, regenerate the node's whole subtree with `radial_limits` floor (or ceiling) at `mid` using the stored `rng_seed`, and move `clear` or `cross` depending on whether the regenerated overflow intersects neighbour ink.
5. Regenerate at `clear`. Find the extreme vertex (lowest or highest radial). Project it onto the nearest neighbour segment; if that distance is at most `2.0` px, move the vertex onto the projection and insert the projected point as a vertex into the neighbour path's `coords` (and a radial interpolated between its neighbours). If the gap is larger, leave the motif at `clear` with no touch; the contact check decides whether a reach is needed. Replace the node's paths in the index.

**Reach resolution**:
1. Unit direction is toward the page centre for `inward`, away for `outward`. Ray is `LineString([page_point, page_point + dir * max_length_px])`.
2. `first_hit` excludes paths of the same node and its subtree. If no hit, return `None`.
3. Insert the hit point as a vertex into the hit path. Build the reach coords: `straight` is `[page_point, hit]`; `wavy` is 9 points along the segment with perpendicular offset `amp * sin(2 * pi * t)` where `amp = min(3.0, 0.1 * length)`, endpoints exact. Return a `PlacedPath` with `role="reach"`, `radials` set to the parent's base radial at the start and the hit path's interpolated radial at the end, and add it to the index.

**Pass two order**: for each ring innermost to outermost: resolve inward overflow for every node of that ring, then outward overflow, then every pending reach of that ring, then `floating_base_cells()` for that ring. A cell is floating when any of its base paths is not in the same `structural_components` component as ring 0's base paths, computed over all current polylines; ring 0 itself is floating only if its own bases split into more than one component. For each floating cell, call `composer.replace_node(ring_plan, seq_pos, position, "floating")`, regenerate every cell using that entry (pass one for those cells only) and repeat the ring's pass two; give up with `AssemblyError` after 3 rounds.

- [ ] **Step 1: Write the failing tests**

```python
import math
from shapely.geometry import LineString
from assembler import Assembler, AssemblyError
from composer import Composer, ComposerSettings, CellRecipe, CellEntry, RingPlan, DesignPlan
from topology_validator import TopologyValidator, structural_components
from tests.test_assembler_pass_one import GEOM, CENTER, manual_plan

def assemble(plan, mws=10.0):
    composer = Composer(1, GEOM, ComposerSettings(categories=["botanical", "geometric"]))
    return Assembler(plan, GEOM, CENTER, 0.5, mws, composer).assemble()

def validate(design):
    return TopologyValidator(snap_tolerance=2.5, whisker_tolerance=5.0, pen_radius=2.0, min_region_area=20.0).analyze(
        design.polylines(), center=CENTER, base_mask=design.base_mask(),
        ring_ids=design.ring_ids(), overflow_parts=design.overflow_parts())

def test_stems_land_on_inner_ring_ink():
    design = assemble(manual_plan())
    assert len(design.reaches) == 12
    for reach in design.reaches:
        end = reach.coords[-1]
        assert math.hypot(end[0] - CENTER[0], end[1] - CENTER[1]) < 100.0

def test_overflow_never_crosses_neighbour_ink():
    design = assemble(manual_plan())
    report = validate(design)
    assert report.stats["num_overflow_crossings"] == 0

def test_all_bases_share_one_component():
    design = assemble(manual_plan())
    report = validate(design)
    assert report.stats["num_floating_base"] == 0

def test_coprime_counts_still_assemble_and_validate():
    design = assemble(manual_plan(divs=(7, 12)))
    report = validate(design)
    assert report.stats["num_dangles"] == 0 and report.stats["num_floating_base"] == 0

def test_touch_inserts_vertex_into_target_path():
    design = assemble(manual_plan())
    reach = design.reaches[0]
    hit = reach.coords[-1]
    assert any(any(math.isclose(x, hit[0], abs_tol=1e-6) and math.isclose(y, hit[1], abs_tol=1e-6)
                   for x, y in p.coords) for p in design.paths if p.role != "reach")

def test_wavy_reach_has_interior_points():
    plan = manual_plan()
    composer = Composer(1, GEOM, ComposerSettings(categories=["botanical", "geometric"]))
    design = Assembler(plan, GEOM, CENTER, 0.9, 10.0, composer).assemble()
    assert all(len(r.coords) == 9 for r in design.reaches)

def test_assembly_is_deterministic():
    a = assemble(manual_plan()); b = assemble(manual_plan())
    assert [p.coords for p in a.paths] == [p.coords for p in b.paths]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_assembler_pass_two.py -q`
Expected: FAIL with `AttributeError: 'Assembler' object has no attribute 'assemble'` or reaches empty.

- [ ] **Step 3: Implement pass two**

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_assembler_pass_two.py -q`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add assembler.py tests/test_assembler_pass_two.py
git commit -m "feat(assembler): resolve overflow, reaches and per-cell contact"
```

---

### Task 10: Petal overflow and both-positions assembly fixtures

This task has no new production code of its own; it exists to pin the two sketch behaviours end to end before the generator is rewired, and to fix whatever they reveal in Tasks 3, 4 or 9.

**Files:**
- Test: `tests/test_assembler_fixtures.py`
- Modify (if the tests reveal defects): `motifs/botanical.py`, `assembler.py`

- [ ] **Step 1: Write the tests**

```python
from composer import CellRecipe, CellEntry, RingPlan, DesignPlan
from tests.test_assembler_pass_two import assemble, validate

def petal_over_band_plan():
    inner = RingPlan(0, 8, 1.0, [CellEntry(CellRecipe("ring_band", "geometric", provides_contact=True), None)], 1)
    outer = RingPlan(1, 8, 1.0, [CellEntry(CellRecipe("petal", "botanical", provides_contact=True), None)], 3)
    return DesignPlan(3, {"categories": ["botanical", "geometric"], "positions": "centre"}, [inner, outer])

def both_positions_plan():
    inner = RingPlan(0, 8, 1.0, [CellEntry(CellRecipe("ring_band", "geometric", provides_contact=True), None)], 1)
    entry = CellEntry(CellRecipe("petal", "botanical", attachments=[CellRecipe("stem", "botanical", provides_contact=True)]),
                      CellRecipe("petal", "botanical", attachments=[CellRecipe("stem", "botanical", provides_contact=True)]))
    outer = RingPlan(1, 8, 0.6, [entry], 5)
    return DesignPlan(5, {"categories": ["botanical"], "positions": "both"}, [inner, outer])

def test_petal_inward_overflow_stops_at_band():
    report = validate(assemble(petal_over_band_plan()))
    assert report.stats["num_overflow_crossings"] == 0 and report.stats["num_dangles"] == 0

def test_centre_and_divider_petals_coexist_without_crossing():
    design = assemble(both_positions_plan())
    report = validate(design)
    assert report.stats["num_floating_base"] == 0
    assert report.stats["num_uncolorable_regions"] == 0
```

- [ ] **Step 2: Run the tests**

Run: `.venv/Scripts/python -m pytest tests/test_assembler_fixtures.py -q`
Expected: either 2 passed, or failures that name a specific defect in a motif or the resolver. Fix the defect in its owning module, keeping the earlier tasks' tests green.

- [ ] **Step 3: Run the whole suite**

Run: `.venv/Scripts/python -m pytest -q`
Expected: all passed.

- [ ] **Step 4: Commit**

```bash
git add tests/test_assembler_fixtures.py motifs assembler.py
git commit -m "test(assembler): sketch fixtures for overflow and both positions"
```

---

### Task 11: Rewire `DesignGenerator`

**Files:**
- Modify: `coloring_generator.py` (replace everything from `generate` through `_draw_ring_boundaries`; keep `__init__`, `_calculate_rings`, `_polar_to_cartesian`, `_dict_to_svg_element`, the debug overlay helpers, `get_params_as_string`)
- Test: `tests/test_design_generator.py`

**Interfaces:**
- Consumes: Tasks 7, 8, 9, 5.
- Produces:
  - `DesignGenerator(seed=None, canvas_size=(612, 612), num_divisions=12, num_rings=4, complexity=0.5, min_pattern_size=8, categories=None, vary_divisions=False, ring_divisions=None, ring_seeds=None, force_motif=None, draw_rings=False, draw_divisions=False)`. `ring_seeds` is `Optional[Dict[int, int]]` of per-ring seed overrides applied in `plan`.
  - Attributes after `generate()`: `plan: DesignPlan`, `assembled: AssembledDesign`, `last_validation_result: TopologyReport`, `last_validation_polylines`.
  - `generate(validate=True) -> str`.
  - `generate_ring_fragment(ring_index: int, ring_seed: int, validate=True) -> Dict` returning `{"ring_index", "ring_seed", "svg", "plan", "ring_seeds"}` where `svg` is the full re-assembled document and `ring_seeds` is the merged override map. The whole document is returned because neighbouring rings' reaches and overflows change when a ring changes.
  - `validation_summary() -> Optional[Dict]` with keys `is_valid, issue_count, tiny_region_count, dangling_end_count, floating_base_count, overflow_crossing_count, issues` (first 20).
  - `get_params_as_string()` gains a line `Ring divisions: 8, 8, 8, 12`.

SVG layout: `<g id="mandala">` containing one `<g id="ring-N">` per ring, each containing one `<path>` per `PlacedPath` with `fill="none" stroke="black" stroke-linecap="butt" stroke-linejoin="round"`, `stroke-width` from the path, and a `data-role` attribute. No `<defs>`, no `<use>`, no boundary group. Debug ring and division overlays stay available behind their flags and are drawn in grey dashes as before.

Validation: `TopologyValidator(snap_tolerance=2.5, whisker_tolerance=5.0, pen_radius=2.0, min_region_area=20.0).analyze(assembled.polylines(), center=self.center, base_mask=assembled.base_mask(), ring_ids=assembled.ring_ids(), overflow_parts=assembled.overflow_parts())`. No `exempt_dangle_fn`, no `divisions`.

- [ ] **Step 1: Write the failing tests**

```python
import re
from coloring_generator import DesignGenerator

def gen(**over):
    return DesignGenerator(**{"seed": 42, "num_rings": 4, "ring_divisions": [8, 8, 8, 12],
                              "categories": ["botanical", "geometric"], **over})

def test_sketch_fixture_generates_and_validates():
    g = gen(); svg = g.generate()
    assert g.last_validation_result.is_valid, g.last_validation_result.issues[:5]
    assert "<use" not in svg and "<defs" not in svg
    assert len(re.findall(r'<g id="ring-\d+"', svg)) == 4

def test_svg_is_deterministic():
    assert gen().generate() == gen().generate()

def test_narrowest_cells_still_generate():
    g = DesignGenerator(seed=7, num_rings=7, num_divisions=24, complexity=0.9, categories=["botanical"])
    g.generate()
    assert g.last_validation_result.is_valid

def test_max_min_pattern_size_drops_nesting_silently():
    g = gen(min_pattern_size=50, complexity=1.0); g.generate()
    assert all(node.recipe.slot_child is None or node.recipe.slot_child.dropped
               for node in g.assembled.nodes if len(node.node_path) == 1)
    assert g.last_validation_result.is_valid

def test_regenerate_ring_changes_neighbour_reaches_not_plan():
    g = gen(); g.generate()
    before_plan = g.plan.rings[3]
    before_reaches = [r.coords for r in g.assembled.reaches if r.ring_index == 3]
    frag = g.generate_ring_fragment(2, 999)
    assert g.plan.rings[3] == before_plan
    assert [r.coords for r in g.assembled.reaches if r.ring_index == 3] != before_reaches
    assert frag["ring_seeds"] == {2: 999}
    assert "<svg" in frag["svg"] and '<g id="ring-0"' in frag["svg"]

def test_validation_summary_shape():
    g = gen(); g.generate()
    assert set(g.validation_summary()) == {"is_valid", "issue_count", "tiny_region_count", "dangling_end_count",
                                           "floating_base_count", "overflow_crossing_count", "issues"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_design_generator.py -q`
Expected: FAIL with `TypeError: unexpected keyword argument 'ring_divisions'`.

- [ ] **Step 3: Rewire `coloring_generator.py`**

Delete `_generate_ring_assets`, `_validate_design`'s extractor loop, all `_merge_*`/`_infer_*`/`_smart_*` boundary helpers, `_get_boundary_element_dicts`, `_ring_boundary_arc_elements`, `_draw_ring_boundaries`, `_calculate_num_variations`, `_generate_variation_extensions`, and the `pattern_usage` attribute. Replace the CLI block's debug flags accordingly.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_design_generator.py -q`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add coloring_generator.py tests/test_design_generator.py
git commit -m "feat(generator): plan, assemble, validate and emit explicit paths"
```

---

### Task 12: Flask API

**Files:**
- Modify: `app.py`
- Test: `tests/test_app.py`

**Interfaces:**
- Consumes: Task 11.
- Produces:
  - `POST /generate` accepts `vary_divisions: bool`, `ring_divisions: List[int] | None`, `ring_seeds: Dict[str, int] | None` in addition to the existing keys. Responds with `svg, params_string, used_seed, validation, plan, ring_seeds`. `ring_divisions` of the wrong length, or any count outside 4 to 24, returns 400 with `{"error": ...}`.
  - `POST /regenerate-ring` accepts the same keys plus `ring_index` and optional `ring_seed`; applies prior `ring_seeds` then the new one; responds with `ring_index, ring_seed, svg, plan, ring_seeds, validation`.
  - `validation_to_summary` is replaced by `generator.validation_summary()`.

- [ ] **Step 1: Write the failing tests**

```python
import json
import pytest
from app import app

@pytest.fixture
def client():
    app.testing = True
    return app.test_client()

BASE = {"seed": 42, "num_rings": 3, "num_divisions": 8, "complexity": 0.5,
        "min_pattern_size": 10, "categories": ["botanical", "geometric"]}

def test_generate_returns_plan_and_summary(client):
    data = client.post("/generate", json=BASE).get_json()
    assert data["plan"]["rings"][0]["divisions"] == 8
    assert "floating_base_count" in data["validation"]
    assert "pattern_usage" not in data

def test_ring_divisions_wrong_length_is_400(client):
    r = client.post("/generate", json={**BASE, "ring_divisions": [8, 8]})
    assert r.status_code == 400 and "ring_divisions" in r.get_json()["error"]

def test_ring_divisions_out_of_range_is_400(client):
    r = client.post("/generate", json={**BASE, "ring_divisions": [8, 8, 30]})
    assert r.status_code == 400

def test_regenerate_ring_round_trips_prior_seeds(client):
    first = client.post("/regenerate-ring", json={**BASE, "ring_index": 1, "ring_seed": 5}).get_json()
    second = client.post("/regenerate-ring", json={**BASE, "ring_index": 2, "ring_seed": 9,
                                                   "ring_seeds": first["ring_seeds"]}).get_json()
    assert second["ring_seeds"] == {"1": 5, "2": 9}
    assert second["plan"]["rings"][1] == first["plan"]["rings"][1]

def test_regenerate_ring_index_out_of_range_is_400(client):
    r = client.post("/regenerate-ring", json={**BASE, "ring_index": 7})
    assert r.status_code == 400
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_app.py -q`
Expected: FAIL on `data["plan"]` with `KeyError`.

- [ ] **Step 3: Update `app.py`**

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_app.py -q`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add app.py tests/test_app.py
git commit -m "feat(api): per-ring divisions, plan in response, ring seed round-trip"
```

---

### Task 13: UI

**Files:**
- Modify: `templates/index.html:71-75` (add checkbox under the Divisions slider)
- Modify: `static/script.js` (`buildGenerationPayload`, `renderDebugBar`, `renderRingSelector`, the regenerate handler around lines 470 to 530, and the `currentPatternUsage` state)

**Interfaces:**
- Consumes: Task 12 response shapes.
- Produces: no new API; the client keeps `currentPlan` and `currentRingSeeds` instead of `currentPatternUsage`.

Changes:
- Checkbox `<input type="checkbox" id="vary-divisions">` labelled `Vary divisions per ring`, included in the payload as `vary_divisions`. The randomise button sets it with probability 0.5.
- `renderRingSelector` reads `currentPlan.rings[i]` and renders `Ring N · 12` with the base motif name of the first sequence entry (centre, else divider) as the tag.
- `renderDebugBar` emits `R1=8:ring_band R2=8:petal+diamond R3=12:petal/scallop` where `+` joins a slot child and `/` joins sequence entries.
- Regenerate handler sends `ring_seeds: currentRingSeeds`, then replaces the whole `svg` from the response, stores `currentRingSeeds = data.ring_seeds`, `currentPlan = data.plan`, re-renders the ring selector and re-selects the ring. The `defs` manipulation is deleted.

- [ ] **Step 1: Make the template and script changes**

- [ ] **Step 2: Start the preview and verify in the browser**

Use `preview_start` with name `mandalaforge`. Generate with the checkbox on, confirm via `read_page` that the ring selector buttons show differing counts and that the debug bar shows per-ring entries. Select ring 2, click Regenerate Ring twice, confirm via `read_console_messages` there are no errors and via `read_page` that both regenerated rings' tags changed and persisted.

- [ ] **Step 3: Take a screenshot of the generated design with the checkbox on**

- [ ] **Step 4: Commit**

```bash
git add templates/index.html static/script.js
git commit -m "feat(ui): vary divisions toggle, plan-driven ring selector and debug bar"
```

---

### Task 14: Per-motif QA harness

**Files:**
- Rewrite: `qa_patterns.py`
- Test: `tests/test_qa_patterns.py`

**Interfaces:**
- Consumes: Task 11 `DesignGenerator(force_motif=...)`, Task 3 registry.
- Produces: `run_case(job) -> Dict` with keys `name, label, status, detail`, `status` in `PASS, SKIP, FAIL, CONTRACT, ERROR`; `MATRIX_SMOKE` and `MATRIX_FULL` dicts; `property_checks(entry) -> Dict[str, bool]` with keys `deterministic, monotone, angular, slot`.

Matrix axes: `ring_divisions` fixtures `[(8, 8, 8, 12), (7, 12), (6, 6), (24, 24, 24)]` (ring count follows the tuple length), `complexity` `(0.15, 0.5, 0.9)` smoke and `(0.15, 0.35, 0.5, 0.7, 0.9)` full, `min_white` `(10,)` smoke and `(5, 10, 25)` full, `position` `("centre", "divider", "both")`, `role` `("base", "slot", "contact")` filtered to the roles the entry supports. A job is skipped when the entry does not support the position or role, or when the declared gates exclude the fixture and `--probe` is not set. CLI keeps `--motif`, `--tier`, `--list`, `--jobs`, `--seed`, `--probe`. The report table columns become `MOTIF PASS SKIP FAIL CONTR ERR DET MONO ANG SLOT`.

- [ ] **Step 1: Write the failing tests**

```python
from qa_patterns import run_case, property_checks, MATRIX_SMOKE
from motifs import find_motif

def test_property_checks_pass_for_petal():
    assert all(property_checks(find_motif("petal")).values())

def test_run_case_passes_for_ring_band_base():
    job = ("ring_band", "geometric", (8, 8), 0.5, 10, "centre", "base", 1, False)
    assert run_case(job)["status"] == "PASS"

def test_run_case_skips_unsupported_role():
    job = ("diamond", "geometric", (8, 8), 0.5, 10, "centre", "base", 1, False)
    assert run_case(job)["status"] == "SKIP"

def test_smoke_matrix_contains_sketch_fixture():
    assert (8, 8, 8, 12) in MATRIX_SMOKE["ring_divisions"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_qa_patterns.py -q`
Expected: FAIL with `ImportError: property_checks`.

- [ ] **Step 3: Rewrite `qa_patterns.py`**

- [ ] **Step 4: Run the tests, then the smoke tier**

Run: `.venv/Scripts/python -m pytest tests/test_qa_patterns.py -q`
Expected: 4 passed.

Run: `.venv/Scripts/python qa_patterns.py --tier smoke`
Expected: exit code 0 with every motif row showing zero FAIL, CONTR and ERR. Any failure is a motif or resolver defect; fix it in its owning module before committing.

- [ ] **Step 5: Commit**

```bash
git add qa_patterns.py tests/test_qa_patterns.py motifs assembler.py
git commit -m "feat(qa): per-motif harness over positions, roles and ring fixtures"
```

---

### Task 15: Corpus harness and overlays

**Files:**
- Modify: `qa_report.py`
- Modify: `topology_validator.py:694-769` (`debug_overlay_svg` gains `reach_lines` and `floating_base_boxes` parameters)
- Test: `tests/test_qa_report.py`

**Interfaces:**
- Consumes: Task 11.
- Produces: `run_one(job)` where `job = (seed, num_rings, num_divisions, complexity, categories, vary_divisions, out_dir, overlay_mode)`; corpus jobs are the existing categories, seeds and complexities crossed with `vary_divisions in (False, True)`. Result dict gains `vary` and `reaches` (count). `debug_overlay_svg(report, polylines, size, reach_lines=(), floating_base_boxes=())` draws reaches as 1px `#0a7` traces and floating bases as dashed red boxes.

- [ ] **Step 1: Write the failing tests**

```python
from qa_report import run_one, corpus_jobs

def test_corpus_has_both_division_modes():
    jobs = corpus_jobs(out_dir="test_output", overlay_mode="never")
    assert {j[5] for j in jobs} == {False, True} and len(jobs) == 180

def test_run_one_reports_reaches(tmp_path):
    result = run_one((42, 3, 8, 0.5, ["botanical"], True, str(tmp_path), "always"))
    assert result["status"] == "PASS" and result["reaches"] >= 0
    assert any(p.name.startswith("qa_overlay_") for p in tmp_path.iterdir())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_qa_report.py -q`
Expected: FAIL with `ImportError: corpus_jobs`.

- [ ] **Step 3: Update `qa_report.py` and the overlay function**

- [ ] **Step 4: Run the tests, then the corpus**

Run: `.venv/Scripts/python -m pytest tests/test_qa_report.py -q`
Expected: 2 passed.

Run: `.venv/Scripts/python qa_report.py --corpus`
Expected: `180/180 designs passed`. Failures are defects to fix in their owning module.

- [ ] **Step 5: Commit**

```bash
git add qa_report.py topology_validator.py tests/test_qa_report.py
git commit -m "feat(qa): corpus runs both division modes and overlays reaches"
```

---

### Task 16: Documentation and retirement gate

**Files:**
- Create: `docs/motifs.md`
- Modify: `README.md`, `docs/architecture.md`
- Delete, only after the gate below passes and the user confirms: `smart_patterns/`, `pattern_generator.py`, `docs/smart-patterns.md`, `shape_extractor.py` (no remaining importer besides the deleted code; `qa_check.py` uses svgelements, not the extractor)

`docs/motifs.md` sections, each written in unwrapped prose: Cell space and limits; The three-layer parametric model; The declaration and what is measured; Positions and angular budget; Closure, overflow and reaches; Archetypes that satisfy closure (enclosing outline, outline with midrib, spans-cell band, pure reach); Traps, seeded from the failures found in Tasks 10, 14 and 15; Adding a motif, with the registry entry and the three commands `qa_patterns.py --motif <name>`, `qa_patterns.py --tier full`, `qa_report.py --corpus`.

`README.md`: replace "How a design is built" with the plan, two-pass assembly and validation summary; replace the pattern catalog table with the motif table from spec section 10; update the parameters table with `vary_divisions` and `ring_divisions`; update the API response description. `docs/architecture.md`: runtime flow and generation model rewritten for composer and assembler; boundaries section replaced by positions and contact; API response example updated.

- [ ] **Step 1: Write `docs/motifs.md`, update `README.md` and `docs/architecture.md`**

- [ ] **Step 2: Commit the documentation**

```bash
git add docs/motifs.md README.md docs/architecture.md
git commit -m "docs: motif authoring guide and updated architecture"
```

- [ ] **Step 3: Run the acceptance gate**

Run: `.venv/Scripts/python qa_patterns.py --tier full`
Expected: exit 0.

Run: `.venv/Scripts/python qa_report.py --corpus --overlays always`
Expected: `180/180 designs passed`.

Then open `test_output/` overlays for the six corpus seeds at complexity 0.5 with `vary_divisions` on and send them to the user with `SendUserFile` for the visual review of ring contacts. Stop here until the user confirms the gate.

- [ ] **Step 4: After confirmation, retire the old layer**

```bash
git rm -r smart_patterns pattern_generator.py docs/smart-patterns.md shape_extractor.py
.venv/Scripts/python -m pytest -q
git commit -m "chore: retire the tiling pattern layer"
```

Expected: suite green with no import of the removed modules anywhere (`grep -rn "smart_patterns\|pattern_generator\|shape_extractor" --include=*.py .` returns nothing).

---

## Revision 2 tasks (spec section 13)

The visual gate failed after Task 16. These tasks implement spec section 13 on top of the completed branch. Task 16 step 4 (retirement) remains gated on the user's visual review after Task 20.

### Task 17: Composer: base symmetry, contact mode, side-touch radial

**Files:**
- Modify: `composer.py`
- Test: `tests/test_composer.py`

**Interfaces:**
- Consumes: the Task 7 composer.
- Produces:
  - `DesignPlan.base_symmetry: int`, `RingPlan.contact_mode: str` in `{"side", "overflow", "stem"}`, `RingPlan.side_touch_radial: float`, all serialised and round-tripped.
  - `Composer.base_symmetry(num_divisions, vary_divisions, ring_divisions, rng) -> int`: `num_divisions` when vary is off and no explicit list; the gcd of an explicit list; otherwise a divisor of `num_divisions` in 3..8 drawn with weights proportional to the divisor.
  - Division count with vary on: `B * m` with `m = clamp(round(num_divisions * scale * triangular(0.7, 1.3, 1.0) / B), 1, 24 // B)` using the existing `scale`, count clamped to 4..24.
  - Sequence length divides `divisions // B`.
  - `contact_mode`: `"side"` when every base in the ring has registry `side_touch` True (ring 0 always side); else `"overflow"` when every base has `max_overflow_inward >= 0.1`; else `"stem"`. In `side` mode the ring gets exactly one inward contact per wedge: when no base has inward overflow, one stem attachment on the first entry's first occupied position. In `overflow` mode no stems are added. In `stem` mode stems are added to bases lacking inward contact, as today.
  - `side_touch_radial = rng.uniform(0.35, 0.6)` from the ring-level stream.
  - `replace_node` for reason "floating" in a `side` ring: first another `side_touch` base, then a stem.

- [ ] Write failing tests: vary on gives counts that are all multiples of `base_symmetry`; `ring_divisions=[8, 8, 8, 12]` gives `base_symmetry == 4`; sequence length divides `divisions // B`; botanical+geometric rings have `contact_mode == "side"` and at most `B` stems per ring; `side_touch_radial` is identical across a ring's entries and within 0.35..0.6; plan JSON round-trips the new fields.
- [ ] Implement, run `tests/test_composer.py` and the full suite, commit `feat(composer): base symmetry, contact modes and side-touch radial`.

### Task 18: Motifs: side touch and ring fill

**Files:**
- Modify: `motifs/geometry.py` (`MotifContext.side_touch_radial: Optional[float] = None`), `motifs/botanical.py`, `motifs/geometric.py`, `motifs/fallback.py`, `motifs/__init__.py`
- Test: `tests/test_motifs.py`

**Interfaces:**
- Registry key `side_touch: bool` on every entry: petal, leaf, scallop, ring_band and the safe band True; stem and diamond False.
- When `context.side_touch_radial` is set and the motif is a base (no slot), the outline's widest vertex is exactly `CellPoint(side_touch_radial, ±angular_limits)`; otherwise the revision-1 shape. Petal `length` in 0.95..1.3, leaf 1.0..1.2; petal `max_overflow_inward` 0.5, scallop 0.4.

- [ ] Write failing tests: a petal and a leaf generated with `side_touch_radial=0.5` have a vertex at `(0.5, ±angular_limits)` within 1e-9; two petals from different seeds share that vertex; a centre petal with `angular_limits=0.6` and a divider petal with `0.4` in adjacent positions meet at the same page point (via `cell_rotation_deg` and `to_cartesian`); petal tips reach radial at least 0.95 with default limits; the property tests still pass.
- [ ] Implement, run `tests/test_motifs.py` and the full suite, commit `feat(motifs): side touch vertices and ring-filling lengths`.

### Task 19: Resolver: symmetry groups and bounded stems

**Files:**
- Modify: `resolver.py`, `assembler.py`
- Test: `tests/test_assembler_pass_two.py`, `tests/test_design_generator.py`

**Interfaces:**
- `Assembler.symmetry_groups(ring_index) -> List[List[PlacedNode]]`: groups of `B` nodes related by rotation `360 / B`, members ordered by cell index, the first member in the first wedge.
- Pass two operates on group representatives; every commit, touch, reach and undo is mirrored to the members by rotating coordinates about the centre by `k * 360 / B` and applying to the member's corresponding paths (same node_path, same path index) and to the rotated counterpart of any neighbour path touched (the neighbour cell at index `+ k * N_neighbour / B`).
- Stems cast only to the inward neighbour ring's inner boundary; no recast to the centre.
- The contact check and floating fallback keep their rules; in a `side` ring a floating cell is handled per group.

- [ ] Write failing tests: a 12/12/12/12 design is exactly 12-fold symmetric (every path's coordinates rotated by 30 degrees match some path's coordinates within 1e-6); an 8/8/8/12 design is 4-fold symmetric; a stem never ends inside a ring other than its inward neighbour; the sketch fixture and the review seeds still validate; determinism.
- [ ] Implement, run the pass-two tests and the full suite, commit `feat(resolver): symmetry groups mirror resolution; stems stay in the neighbour ring`.

### Task 20: QA, docs, review set

**Files:**
- Modify: `qa_patterns.py` (fixtures gain `B`; slot gate uses the plan's `centre_share`), `qa_report.py` (table shows `B`), `docs/motifs.md`, `docs/architecture.md`, `README.md`, `static/script.js` (debug bar shows `B=`)
- Test: existing harness tests updated

- [ ] Run `qa_patterns.py --tier smoke --jobs 6` and `qa_report.py --corpus --overlays always --jobs 6`; expect exit 0 and 180/180; fix harness breakage; report engine failures.
- [ ] Update the docs for section 13.
- [ ] Generate the review set: six corpus overlays (botanical c0.5 v1), six finished designs with vary on and six with vary off, seeds 42, 777, 12345, 254302, 955789, 984322, complexity 0.5, botanical+geometric; the controller sends them to the user.
- [ ] Commit `feat(qa,docs): revision 2 harness fixtures, docs and review set`.
