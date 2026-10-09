# Motif Aesthetics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the motif engine's designs look like the coloring-book mandalas in `examples/`: smooth pointed shapes, layered rings, interior detail, a two-weight stroke and a twelve-motif vocabulary, without loosening any structural rule.

**Architecture:** Everything new happens in the motif layer, in cell space. Touch height is a per-ring plan value. Seam ends let ring-wide shapes meet across dividers using a ring-level random stream. Embellishments are applied by generators before measurement. A layered ring's centre node is a composite whose back layer is cut by the front fill. The resolver regenerates all of it with its node and changes only to draw curved stems.

**Tech Stack:** Python 3, Shapely 2.1, svgwrite, Flask, pytest; Windows, run everything with `.venv/Scripts/python`.

**Spec:** `docs/superpowers/specs/2026-10-09-motif-aesthetics-design.md` (builds on `docs/superpowers/specs/2026-10-04-motif-engine-design.md`, section 13). Authoring guide: `docs/motifs.md`.

## Global Constraints

- `BASE_TOUCH_RANGE = (0.08, 0.2)`, `MID_TOUCH_RANGE = (0.35, 0.6)`; touch heights are exactly `"base"` and `"mid"`.
- `DETAIL_WEIGHT_SHARE = 0.6`; weights are exactly `"outline"` (default) and `"detail"`.
- Clearance between two lines is `min_white_space + (stroke_a + stroke_b) / 2`; for two outlines this equals today's `min_white_space + stroke_width`.
- Salts are mixed with `zlib.crc32`, never `hash()`. Salt strings: `"pick"`, `"pick:emb"`, `"pick:back"`, `"emb:<name>"`, `"back"`, `"ring:<motif>:<position>"`.
- Seam ends sit at angular exactly `±1.0`, only at angular budget 1.0, only for motifs declaring `seams: True`, which declare zero overflow both ways and fill their position across the whole ring.
- Embellishment order: `echo`, then at most one of `veins` or `fan`, then `dot`; `beads` only on bands. An entry has an interior fill or a slot child, never both. Count `n = clamp(floor(3 * (complexity - 0.2) / 0.8 + u), 0, 3)`.
- Echo count is 2 at complexity >= 0.6, else 1. A back piece without a seam end shorter than `2 * min_white_space` px is dropped.
- Layered rings: never ring 0, touch height always `base`, one back motif per ring, back radial limits `(0.0, 1.0)`, back paths have role `"back"` and count as base ink.
- Old plan JSON loads: `touch_height="mid"`, `back=None`, `back_dropped=False`, `embellishments=[]`. `find_motif("ring_band")` returns the `band` entry.
- Every seed re-renders after Task 1; re-baseline pinned values in tests rather than preserving them.
- Gates per phase: `.venv/Scripts/python qa_patterns.py --tier full` exits 0, `.venv/Scripts/python qa_report.py --corpus` reports 180/180 PASS, `.venv/Scripts/python -m pytest -q` passes. Then a visual review set goes to the user and work stops until the user's verdict.
- Review sets go under `review/phaseN/` and are never committed (add `review/` to `.gitignore` in Task 8).
- Never hard-wrap prose in Markdown or commit bodies. Commit trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. Seam ends under inexact rotations (7 or 14 divisions, 360/7 degrees): the two halves must still meet, through `snap_to_ink`, with no dangle. Test in Task 5.
2. A layered ring at 24 divisions, where back halves are too thin to survive the cut: the back must be dropped ring-wide and the design must still validate, in pass one and when a pass-two pull-back makes the composite fail. Tests in Task 12.
3. Large `min_pattern_size` (50) at complexity 1.0: every embellishment that cannot fit is dropped and counted, never raised, and the design validates. Test in Task 10.
4. Revision-2 plan JSON still loads (`DesignPlan.from_dict` fills the new fields with defaults), and `/generate` payloads whose `force_motif` names `ring_band` still work. Tests in Tasks 4 and 5.
5. `/regenerate-ring` with a new ring seed on a ring holding a seam motif or a back layer: every cell of that ring must take the new ring stream together, so seams still meet. Test in Task 12.

---

## Phase 1: engine and reshaped motifs

### Task 1: Salted streams and the ring stream

**Files:**
- Modify: `composer.py` (`node_seed`, `node_rng`, picks in `_plan_node`, `_nest`, `_substitute`, `_forced_node`)
- Modify: `motifs/geometry.py` (`MotifContext`)
- Modify: `assembler.py` (`_context`, `_place_node`, `regenerate`)
- Test: `tests/test_composer.py`, `tests/test_geometry.py`, `tests/test_assembler_pass_one.py`; re-baseline pinned values across `tests/`

**Interfaces:**
- Produces: `salted_seed(seed: int, salt: str) -> int` in `motifs/geometry.py` (`seed * 31 + zlib.crc32(salt.encode("utf-8"))`; it lives in the motifs package so motifs can salt without importing `composer`); `node_seed(seed, ring_index, seq_pos, depth, position, salt: str = "") -> int` (today's formula, passed through `salted_seed` when `salt` is non-empty); `node_rng(..., salt: str = "") -> random.Random`; `ring_stream_seed(ring_seed: int, ring_index: int, salt: str) -> int` (defined as `node_seed(ring_seed, ring_index, 0, -2, "centre", salt)`); `MotifContext.ring_stream_seed: int = 0`, `MotifContext.node_seed: int = 0`, `MotifContext.ring_rng: random.Random` (`field(init=False, repr=False, compare=False)`, built in `__post_init__` from `ring_stream_seed`, so `dataclasses.replace` always yields a fresh, identical stream).
- Assembler sets `ring_stream_seed = ring_stream_seed(ring.ring_seed, ring.ring_index, f"ring:{recipe.motif}:{position}")` and `node_seed = rng_seed` on every node context; `_context` gains a `recipe: CellRecipe` parameter.

- [ ] **Step 1: Write the failing tests**

```python
def test_unsalted_node_seed_is_unchanged():
    assert node_seed(42, 1, 2, 0, "centre") == 42 * 1_000_003 + 1 * 10_007 + 2 * 101

def test_salt_changes_the_seed_and_is_stable():
    salted = node_seed(42, 1, 2, 0, "centre", salt="pick")
    assert salted != node_seed(42, 1, 2, 0, "centre")
    assert salted == node_seed(42, 1, 2, 0, "centre", salt="pick")

def test_salt_survives_a_new_process():
    code = "from composer import node_seed; print(node_seed(42, 1, 2, 0, 'centre', salt='pick'))"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout
    assert int(out) == node_seed(42, 1, 2, 0, "centre", salt="pick")

def test_ring_rng_is_fresh_after_replace(cell_kwargs):
    ctx = MotifContext(**cell_kwargs, ring_stream_seed=99)
    first = ctx.ring_rng.random()
    assert replace(ctx).ring_rng.random() == first

def test_cells_of_a_ring_share_one_ring_stream():
    asm = build(manual_plan())            # existing helpers in test_assembler_pass_one.py
    by_motif = {}
    for n in asm.nodes:
        if n.ring_index == 1 and len(n.node_path) == 1:
            by_motif.setdefault((n.recipe.motif, n.position), set()).add(n.context.ring_stream_seed)
    assert by_motif and all(len(seeds) == 1 for seeds in by_motif.values())
```

- [ ] **Step 2: Run them and see them fail**

Run: `.venv/Scripts/python -m pytest tests/test_composer.py tests/test_geometry.py tests/test_assembler_pass_one.py -q`
Expected: FAIL (`salt` is not a parameter; `ring_stream_seed` is not a field)

- [ ] **Step 3: Implement**

Every composer pick (`_pick` calls for bases, slot children and substitutes) uses a stream salted `"pick"`; the generator's own stream stays unsalted.

- [ ] **Step 4: Re-baseline and run the suite**

Run: `.venv/Scripts/python -m pytest -q`
Expected: only tests that pin picked motifs or coordinates fail. Update each pinned value to the new output after checking that the test's intent (determinism, symmetry, a stem present) still holds. Then the whole suite passes.

- [ ] **Step 5: Commit**

```bash
git add composer.py assembler.py motifs/geometry.py tests/
git commit -m "feat(composer): salt the pick stream and add a ring-level stream"
```

### Task 2: Curve and circle helpers

**Files:**
- Modify: `motifs/geometry.py`
- Test: `tests/test_geometry.py`

**Interfaces:**
- Produces: `cubic_points(start: CellPoint, control1: CellPoint, control2: CellPoint, end: CellPoint, steps: int = 8) -> List[CellPoint]` (no clamping, `steps + 1` points, exact ends); `page_arc_points(context: MotifContext, centre: CellPoint, radius_px: float, start_deg: float, end_deg: float, steps: int = 16) -> List[CellPoint]` (angles in the cell's local page frame at `centre`: 0 degrees points outward along the radius, 90 degrees toward increasing angular; offsets mapped with `px_to_radial` and `px_to_angular`); `page_circle_points(context, centre, radius_px, steps: int = 24) -> List[CellPoint]` (closed, no repeated first point); `insert_vertex_on_outline(points: List[CellPoint], closed: bool, point: CellPoint, tolerance: float = 1e-9) -> List[CellPoint]` (inserts `point` into the segment it lies on; returns the input unchanged when it is already a vertex).

- [ ] **Step 1: Write the failing tests**

```python
def test_cubic_points_ends_and_midpoint():
    a, b, c, d = CellPoint(0, 0), CellPoint(0.2, 1), CellPoint(0.8, 1), CellPoint(1, 0)
    pts = cubic_points(a, b, c, d, steps=4)
    assert len(pts) == 5 and pts[0] == a and pts[-1] == d
    assert pts[2].radial == pytest.approx(0.5) and pts[2].angular == pytest.approx(0.75)

def test_page_circle_is_round_on_the_page(cell_kwargs):
    ctx = MotifContext(**cell_kwargs)
    centre = CellPoint(0.5, 0.0)
    cx, cy = ctx.to_cartesian(centre)
    for p in page_circle_points(ctx, centre, 8.0):
        x, y = ctx.to_cartesian(p)
        assert math.hypot(x - cx, y - cy) == pytest.approx(8.0, abs=0.3)

def test_insert_vertex_on_outline():
    square = [CellPoint(0, -1), CellPoint(0, 1), CellPoint(1, 1), CellPoint(1, -1)]
    out = insert_vertex_on_outline(square, True, CellPoint(0.5, 1))
    assert out == [CellPoint(0, -1), CellPoint(0, 1), CellPoint(0.5, 1), CellPoint(1, 1), CellPoint(1, -1)]
    assert insert_vertex_on_outline(out, True, CellPoint(0.5, 1)) == out
```

- [ ] **Step 2: Run them and see them fail**

Run: `.venv/Scripts/python -m pytest tests/test_geometry.py -q`
Expected: FAIL with ImportError

- [ ] **Step 3: Implement the four helpers in `motifs/geometry.py`**

- [ ] **Step 4: Run the tests and see them pass**

Run: `.venv/Scripts/python -m pytest tests/test_geometry.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add motifs/geometry.py tests/test_geometry.py
git commit -m "feat(geometry): cubic curves, page-round arcs and vertex insertion"
```

### Task 3: Line weights, seam contract and curved reach styles

**Files:**
- Modify: `motifs/geometry.py` (`SmartVector`, `MotifContext`)
- Modify: `motifs/contract.py` (`REACH_STYLES`, `Declaration`, `build_instance`, `measure_slot`, `MotifAnalyzer`)
- Modify: `assembler.py` (`_trace_node`, `AssembledDesign.base_mask`)
- Test: `tests/test_contract.py`, `tests/test_assembler_pass_one.py`

**Interfaces:**
- Produces: `SmartVector.weight: str = "outline"`, `SmartVector.layer: str = "front"`; `DETAIL_WEIGHT_SHARE = 0.6` and `WEIGHTS = ("outline", "detail")` in `motifs/geometry.py`; `MotifContext.stroke_for(weight: str) -> float`; `MotifContext.clearance_px(weight_a: str = "outline", weight_b: str = "outline") -> float`; `REACH_STYLES = ("straight", "wavy", "bow", "s")`; `Declaration.seams: bool = False`; `build_instance(..., *, seams: bool = False, slot: Optional[List[CellPoint]] = None)` where `slot` passes an already-measured slot (mutually exclusive with `slot_outline`, `MotifError` if both); `inset_outline(context, outline, inset_px) -> Optional[List[CellPoint]]` (the page-space inset that `measure_slot` used, factored out); `measure_slot(context, outline, outline_weight: str = "outline")` insets by `context.clearance_px(outline_weight, "outline")`.
- Assembler: a path's `stroke_width` is `context.stroke_for(vector.weight)`; its role is `"back"` when `vector.layer == "back"`, else the node's role; `base_mask` is true for roles `"base"` and `"back"`.

- [ ] **Step 1: Write the failing tests**

```python
def test_detail_weight_and_clearance(cell_kwargs):
    ctx = MotifContext(**cell_kwargs)
    assert ctx.stroke_for("detail") == pytest.approx(0.6 * ctx.stroke_width)
    assert ctx.clearance_px("outline", "detail") == pytest.approx(ctx.min_white_space + 0.8 * ctx.stroke_width)
    assert ctx.clearance_px() == pytest.approx(ctx.min_white_space + ctx.stroke_width)

def test_seam_end_is_accounted_for_only_when_declared(cell_kwargs):
    arc = [SmartVector([CellPoint(0.5, -1.0), CellPoint(0.5, 0.0), CellPoint(0.5, 1.0)])]
    ctx = MotifContext(**cell_kwargs)
    assert build_instance(ctx, arc, seams=True).declaration.seams      # no reach end needed
    reach = [ReachEnd(CellPoint(0.5, 0.0), "inward", 10.0)]
    with pytest.raises(MotifError):
        build_instance(MotifContext(**cell_kwargs), arc, reach_ends=reach)
    with pytest.raises(MotifError):
        build_instance(MotifContext(**cell_kwargs, angular_limits=0.6), arc, seams=True)

def test_curved_reach_styles_are_accepted():
    for style in ("bow", "s"):
        assert ReachEnd(CellPoint(0, 0), "inward", 5.0, style).style == style
```

Add `test_detail_vector_is_traced_thinner` to `tests/test_assembler_pass_one.py`: monkeypatch `find_motif("petal")["generator"]` with a wrapper that appends a `detail` copy of the outline inset to radial 0.3 to 0.6, build `manual_plan()`, and assert that path's `stroke_width == 0.6 * asm.stroke_width`.

- [ ] **Step 2: Run them and see them fail**

Run: `.venv/Scripts/python -m pytest tests/test_contract.py tests/test_assembler_pass_one.py -q`
Expected: FAIL

- [ ] **Step 3: Implement**

The seam rule goes in `_end_is_accounted_for`: accepted when the declaration has `seams`, `context.angular_limits == 1.0`, and `abs(abs(endpoint.angular) - 1.0) <= tolerance`. The analyzer reads the flag from the instance's declaration. The rule that an open motif must declare reach ends does not apply to a motif that declares seams: its seams account for its ends.

- [ ] **Step 4: Run the full suite**

Run: `.venv/Scripts/python -m pytest -q`
Expected: PASS (outline-only motifs measure the same slot as before)

- [ ] **Step 5: Commit**

```bash
git add motifs/ assembler.py tests/
git commit -m "feat(contract): line weights, seam ends and curved reach styles"
```

### Task 4: Touch height and seam-aware composition

**Files:**
- Modify: `composer.py` (`RingPlan`, `plan_ring`, `_contact_mode`, `_refresh_contact`, `_side_touch_capable` replaced, `_plan_node`, `_substitute`, `replace_node`, `_position_mode`)
- Modify: `motifs/botanical.py`, `motifs/geometric.py`, `motifs/fallback.py` (registry keys)
- Modify: `assembler.py` (`_context` passes the radial unchanged; nothing else)
- Test: `tests/test_composer.py`, `tests/test_composer_model.py`, `tests/test_motifs.py`

**Interfaces:**
- Produces: `TOUCH_HEIGHTS = ("base", "mid")`, `BASE_TOUCH_RANGE`, `MID_TOUCH_RANGE` in `composer.py` (`SIDE_TOUCH_RADIAL_RANGE` removed); `RingPlan.touch_height: str = "mid"`; `touch_heights_of(entry: Dict) -> Tuple[str, ...]` (all of `TOUCH_HEIGHTS` for a seam motif, else `tuple(entry["side_touch_heights"])`); `common_touch_heights(entries: Sequence[Dict]) -> Tuple[str, ...]` in `TOUCH_HEIGHTS` order.
- Every registry entry gains `side_touch_heights: Tuple[str, ...]`, `seams: bool` and `embellishments: Tuple[str, ...]` (empty until Task 9), and loses `side_touch`. Phase 1 values: petal and leaf `("base", "mid")`; scallop, ring_band and the safe band `("mid",)` (they carry a mid-height side vertex today; Task 5 turns scallop and band into seam motifs with `()`); diamond and stem `()`; `seams` false everywhere until Task 5.
- A ring is `side` when `common_touch_heights` of its bases is non-empty. The height is drawn from that tuple with the ring stream, then the radial from the matching range.
- A seam motif chosen for sequence entry 0 at a position is copied (same recipe, freshly composed) into every entry at that position. Entries after 0 never pick a seam motif. Seam motifs are not candidates in `both` mode. `replace_node` on a seam node replaces it in every entry.

- [ ] **Step 1: Write the failing tests**

```python
def test_registry_declares_touch_heights_and_seams():
    for entry in MOTIFS + [safe_motif("botanical")]:
        assert set(entry["side_touch_heights"]) <= {"base", "mid"} and "side_touch" not in entry
        assert isinstance(entry["seams"], bool) and isinstance(entry["embellishments"], tuple)

def test_touch_radial_matches_height():
    for seed in range(30):
        for ring in plan_for(seed=seed).rings:
            if ring.contact_mode == "side":
                low, high = BASE_TOUCH_RANGE if ring.touch_height == "base" else MID_TOUCH_RANGE
                assert low <= ring.side_touch_radial <= high

def test_disjoint_heights_are_not_side():
    assert common_touch_heights([{"side_touch_heights": ("base",), "seams": False},
                                 {"side_touch_heights": ("mid",), "seams": False}]) == ()

def test_revision_two_plan_loads_as_mid():
    d = plan_for(seed=3).rings[1].to_dict(); d.pop("touch_height")
    assert RingPlan.from_dict(d).touch_height == "mid"
```

- [ ] **Step 2: Run them and see them fail**

Run: `.venv/Scripts/python -m pytest tests/test_composer.py tests/test_composer_model.py tests/test_motifs.py -q`
Expected: FAIL

- [ ] **Step 3: Implement**, including `touch_height` in `RingPlan.to_dict`/`from_dict`.

- [ ] **Step 4: Run the full suite**

Run: `.venv/Scripts/python -m pytest -q`
Expected: PASS after re-baselining pinned picks

- [ ] **Step 5: Commit**

```bash
git add composer.py assembler.py motifs/ tests/
git commit -m "feat(composer): per-ring touch height and seam-aware positions"
```

### Task 5: Band and scallop as seam motifs

**Files:**
- Modify: `motifs/geometric.py` (`generate_ring_band` becomes `generate_band`; entry renamed `band`)
- Modify: `motifs/botanical.py` (`generate_scallop`)
- Modify: `motifs/__init__.py` (`MOTIF_ALIASES = {"ring_band": "band"}` used by `find_motif`)
- Test: `tests/test_motifs.py`, `tests/test_design_generator.py`, `tests/test_app.py`

**Interfaces:**
- Consumes: `context.ring_rng` (Task 1), `page_arc_points` (Task 2), `build_instance(..., seams=True)` (Task 3).
- Produces: `band`: `seams: True`, `spans_cell: True`, positions `["centre", "divider"]`, zero overflow; two open vectors, each a constant-radial arc from `(r, -1.0)` to `(r, 1.0)` with `r1` drawn from `ring_rng` in `[0.25, 0.45]` and `r2` in `[0.55, 0.75]`; no reach ends (seams account for its ends, Task 3). `scallop`: `seams: True`, `spans_cell: True`, positions `["divider"]`, zero overflow, `max_overflow_inward` 0.0; one open vector from `(rb, -1.0)` to `(rb, 1.0)` forming a single circular lobe whose apex is at angular 0, with `rb` and the lobe height drawn from `ring_rng` and a direction `outward` (apex at `rb + h`) or `inward` (apex at `rb - h`), `rb` in `[0.3, 0.5]`, `h` in `[0.25, 0.45]`, clamped by the radial limits; the lobe is a true page-space circular arc through both seam ends and the apex. Both take `side_touch_heights = ()` and `seams = True`.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize("name", ["band", "scallop"])
def test_seam_ends_sit_on_the_cell_edges(name, cell_kwargs):
    inst = find_motif(name)["generator"](make_ctx(cell_kwargs, 4, ring_stream_seed=77))
    ends = [p for v in inst.vectors if not v.closed for p in (v.points[0], v.points[-1])]
    assert ends and all(abs(p.angular) == 1.0 for p in ends)

@pytest.mark.parametrize("name", ["band", "scallop"])
def test_every_cell_draws_the_same_seams(name, cell_kwargs):
    a = find_motif(name)["generator"](make_ctx(cell_kwargs, 1, ring_stream_seed=77))
    b = find_motif(name)["generator"](make_ctx(cell_kwargs, 2, ring_stream_seed=77))
    assert [v.points for v in a.vectors] == [v.points for v in b.vectors]

def test_ring_band_alias():
    assert find_motif("ring_band") is find_motif("band")

@pytest.mark.parametrize("divisions", [[7, 7, 14], [8, 8, 8, 12]])
def test_band_rings_meet_at_their_seams(divisions):
    g = DesignGenerator(seed=5, num_rings=len(divisions), ring_divisions=divisions, categories=["geometric"],
                        force_motif={"name": "band", "role": "base", "position": "centre"})
    g.generate()
    assert g.last_validation_result.is_valid, g.last_validation_result.issues[:5]
    assert g.validation_summary()["dangling_end_count"] == 0
```

In `tests/test_app.py`, add a `/generate` call with `force_motif` naming `ring_band` and assert status 200 and a valid design.

- [ ] **Step 2: Run them and see them fail**

Run: `.venv/Scripts/python -m pytest tests/test_motifs.py tests/test_design_generator.py tests/test_app.py -q`
Expected: FAIL

- [ ] **Step 3: Implement both generators**, drawing every seam-deciding value from `ring_rng` and nothing from `rng`.

- [ ] **Step 4: Run the full suite and a corpus check**

Run: `.venv/Scripts/python -m pytest -q` then `.venv/Scripts/python qa_report.py --corpus`
Expected: PASS; corpus 180/180

- [ ] **Step 5: Commit**

```bash
git add motifs/ tests/
git commit -m "feat(motifs): band and scallop drawn as seam motifs"
```

### Task 6: Lotus petal, leaf and diamond reshaped

**Files:**
- Modify: `motifs/botanical.py` (`_petal_outline`, `generate_petal`, `_leaf_vectors`, `generate_leaf`)
- Modify: `motifs/geometric.py` (`generate_diamond`)
- Modify: `qa_patterns.py` (add `tangent_error_deg` and `max_turn_deg` helpers, used by tests now and by the TANG check in Task 8)
- Test: `tests/test_motifs.py`

**Interfaces:**
- Consumes: `cubic_points` (Task 2), touch heights (Task 4).
- Produces: `qa_patterns.tangent_error_deg(context, points: List[CellPoint], index: int) -> float`, the angle in degrees between the page-space tangent at `points[index]` (from its two neighbours) and the radial direction there; `qa_patterns.max_turn_deg(context, points, closed: bool, skip: Set[int]) -> float`, the largest page-space turning angle at any vertex not in `skip`, measured on the traced polyline.
- Petal: per side, two cubic segments base to belly, belly to tip; belly at a fraction of the length drawn in `[0.3, 0.6]`; tip sharpness and flare drawn per instance; tip vertex at angular 0. With side touch, the touch vertex is the belly and both adjacent controls share its angular, so the tangent there is radial. Length, dip and wave ranges stay as today.
- Leaf: keeps its midrib for now (Task 11 moves it to `veins`); curved pointed apex from cubic segments; side touch as the petal.
- Diamond: a per-instance `concave` draw (probability 0.5); concave edges bow inward by a drawn fraction in `[0.15, 0.35]` of the half-width.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize("name", ["petal", "leaf"])
@pytest.mark.parametrize("radial", [0.12, 0.45])
def test_side_touch_vertex_is_smooth(name, radial, cell_kwargs):
    for seed in range(12):
        ctx = make_ctx(cell_kwargs, seed, side_touch_radial=radial)
        outline = find_motif(name)["generator"](ctx).vectors[0].points
        i = next(k for k, p in enumerate(outline) if p.radial == radial and p.angular == 1.0)
        assert tangent_error_deg(ctx, outline, i) <= 10.0

@pytest.mark.parametrize("name", ["petal", "leaf"])
def test_outline_has_no_corners_but_its_tip_and_base(name, cell_kwargs):
    for seed in range(12):
        ctx = make_ctx(cell_kwargs, seed, side_touch_radial=0.12)
        pts = find_motif(name)["generator"](ctx).vectors[0].points
        tip = max(range(len(pts)), key=lambda k: pts[k].radial)
        base = min(range(len(pts)), key=lambda k: (pts[k].radial, abs(pts[k].angular)))
        assert max_turn_deg(ctx, pts, True, {tip, base}) <= 35.0

def test_base_touch_narrows_above_the_vertex(cell_kwargs):
    ctx = make_ctx(cell_kwargs, 3, side_touch_radial=0.12)
    pts = find_motif("petal")["generator"](ctx).vectors[0].points
    assert all(abs(p.angular) < 1.0 for p in pts if p.radial > 0.12 + 1e-9)

def test_diamond_has_both_variants(cell_kwargs):
    kinds = set()
    for seed in range(20):
        ctx = make_ctx(cell_kwargs, seed); ctx.slot = slot_for(cell_kwargs)
        kinds.add(len(find_motif("diamond")["generator"](ctx).vectors[0].points) > 4)
    assert kinds == {True, False}
```

- [ ] **Step 2: Run them and see them fail**

Run: `.venv/Scripts/python -m pytest tests/test_motifs.py -q`
Expected: FAIL

- [ ] **Step 3: Implement the three generators**, keeping every parameter drawn before any limit is applied (the MONO property).

- [ ] **Step 4: Run the full suite and the smoke tier**

Run: `.venv/Scripts/python -m pytest -q` then `.venv/Scripts/python qa_patterns.py --tier smoke`
Expected: PASS; smoke exit 0

- [ ] **Step 5: Commit**

```bash
git add motifs/ qa_patterns.py tests/
git commit -m "feat(motifs): lotus petal, curved leaf and concave diamond"
```

### Task 7: Curved stems

**Files:**
- Modify: `resolver.py` (`wavy_coords` neighbours, `_draw_reach`, `_wavy_clear_of_ink` renamed `_curve_clear_of_ink`)
- Modify: `motifs/botanical.py` (`generate_stem`)
- Test: `tests/test_assembler_pass_two.py`, `tests/test_motifs.py`

**Interfaces:**
- Produces: `bow_coords(start, end, scale=1.0) -> List[PointTuple]` (half a sine wave, always bowing to the left of start-to-end, so it is the same under rotation); `s_coords(start, end, scale=1.0)` (one full sine wave); `BOW_AMPLITUDE_SHARE = 0.12`, `CURVE_MAX_AMPLITUDE_PX = 8.0`, applied to both; `REACH_SHAPES = {"wavy": wavy_coords, "bow": bow_coords, "s": s_coords}`; `_curve_clear_of_ink(asm, start, end, shape, accept, end_paths)` with the existing `WAVY_FALLBACK_SCALES` ladder. The stem generator draws its style with `rng.choices(["bow", "s", "wavy"], weights=[2, 2, 1])`.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize("shape", [bow_coords, s_coords])
def test_curve_ends_are_exact_and_amplitude_capped(shape):
    start, end = (0.0, 0.0), (0.0, 100.0)
    coords = shape(start, end)
    assert coords[0] == start and coords[-1] == end
    assert max(abs(x) for x, _ in coords) == pytest.approx(min(8.0, 0.12 * 100.0), abs=0.2)

def test_stems_are_never_drawn_straight_by_choice(cell_kwargs):
    stem = find_motif("stem")["generator"]
    styles = {stem(make_ctx(cell_kwargs, s)).declaration.reach_ends[0].style for s in range(40)}
    assert styles == {"bow", "s", "wavy"}
```

- [ ] **Step 2: Run them and see them fail**

Run: `.venv/Scripts/python -m pytest tests/test_assembler_pass_two.py tests/test_motifs.py -q`
Expected: FAIL

- [ ] **Step 3: Implement**, dispatching on `reach_end.style` in `_draw_reach`, with `straight` keeping its current branch.

- [ ] **Step 4: Run the full suite and the corpus**

Run: `.venv/Scripts/python -m pytest -q` then `.venv/Scripts/python qa_report.py --corpus`
Expected: PASS; 180/180

- [ ] **Step 5: Commit**

```bash
git add resolver.py motifs/botanical.py tests/
git commit -m "feat(resolver): bowed and S-curved stems"
```

### Task 8: Phase 1 QA, docs and visual gate

**Files:**
- Modify: `qa_patterns.py` (SEAM and TANG property checks and report columns)
- Modify: `docs/motifs.md`, `docs/architecture.md`, `.gitignore` (adds `review/`)
- Test: `tests/test_qa_patterns.py`

**Interfaces:**
- Produces: `property_checks(entry)` returns keys `deterministic, monotone, angular, slot, seam, tangent`. `seam` is true when the motif declares no seams, or when every open end of its vectors at seed 11 sits at angular exactly `±1.0` and the vectors at seeds 11 and 12 with the same `ring_stream_seed` are identical. `tangent` is true when the motif has no side-touch heights, or when for each of its heights (radial 0.12 for `base`, 0.45 for `mid`) `tangent_error_deg` at the touch vertex is at most 10 for seeds 0 to 5. The table gains `SEAM` and `TANG` columns.

- [ ] **Step 1: Write the failing test**

```python
def test_property_checks_include_seam_and_tangent():
    for entry in MOTIFS:
        outcome = property_checks(entry)
        assert {"seam", "tangent"} <= set(outcome) and all(outcome.values()), (entry["name"], outcome)
```

- [ ] **Step 2: Run it and see it fail**

Run: `.venv/Scripts/python -m pytest tests/test_qa_patterns.py -q`
Expected: FAIL

- [ ] **Step 3: Implement the checks and columns.** Update `docs/motifs.md` (touch heights and smooth touch, seam ends and `ring_rng`, line weights, curved stem styles, band and scallop) and `docs/architecture.md` (salted streams).

- [ ] **Step 4: Run the gates**

Run: `.venv/Scripts/python -m pytest -q`, `.venv/Scripts/python qa_patterns.py --tier full`, `.venv/Scripts/python qa_report.py --corpus`
Expected: all pass; full tier exit 0 with SEAM and TANG all PASS; corpus 180/180

- [ ] **Step 5: Commit**

```bash
git add qa_patterns.py docs/ tests/ .gitignore
git commit -m "test(qa): seam and tangent property checks; document phase 1"
```

- [ ] **Step 6: Visual gate.** Generate twelve designs with overlays into `review/phase1/`: run `.venv/Scripts/python qa_report.py --seeds 11 23 37 41 --vary --categories botanical geometric --complexity C --overlays always --out review/phase1` for C in 0.3, 0.6 and 0.9. Send the design SVGs and overlays to the user with SendUserFile and stop until the user gives a verdict.

## Phase 2: layering and embellishments

### Task 9: Embellishment pipeline with echo

**Files:**
- Create: `motifs/embellish.py`
- Modify: `motifs/contract.py` (`Anatomy`, `Declaration.anatomy`, `MotifInstance.dropped_embellishments`, `build_instance` keywords)
- Modify: `motifs/geometry.py` (`MotifContext.embellishments: Tuple[str, ...] = ()`)
- Modify: `motifs/botanical.py` (petal and leaf call the pipeline)
- Modify: `motifs/geometric.py` (band's `embellishments` entry)
- Modify: `composer.py` (`CellRecipe.embellishments`, selection in `_compose`)
- Modify: `assembler.py` (`_context` passes `tuple(recipe.embellishments)`; `AssembledDesign.dropped_embellishments: int`, summed over the placed instances' `dropped_embellishments`)
- Test: create `tests/test_embellish.py`; `tests/test_composer.py`

**Interfaces:**
- Produces: `Anatomy(base: CellPoint, tip: CellPoint, outline: int)` (frozen dataclass in `motifs/contract.py`); `build_instance(..., *, anatomy: Optional[Anatomy] = None, dropped_embellishments: int = 0, slot_outline_weight: str = "outline")`; `EMBELLISHMENT_ORDER = ("echo", "veins", "fan", "dot", "beads")`, `INTERIOR_FILLS = ("veins", "fan")`; `EmbellishResult(vectors: List[SmartVector], slot_outline: Optional[List[CellPoint]], slot_outline_weight: str, dropped: int)`; `apply_embellishments(context, vectors, anatomy: Optional[Anatomy], slot_outline: Optional[List[CellPoint]]) -> EmbellishResult`, running `context.embellishments` in `EMBELLISHMENT_ORDER`, each drawing from `embellishment_rng(context, name) -> random.Random`, which is `random.Random(salted_seed(context.node_seed, "emb:" + name))`. An interior fill sets `slot_outline` to None. `CellRecipe.embellishments: List[str]` (default empty, serialised). Composer: `pick_embellishments(entry: Dict, complexity: float, rng: random.Random) -> List[str]` with the global count formula, names without replacement from `entry["embellishments"]`, at most one interior fill, returned in `EMBELLISHMENT_ORDER`; `_compose` picks for base nodes with a stream salted `"pick:emb"` and skips slot nesting when an interior fill was picked.
- Echo: each echo is `inset_outline(context, inner, context.clearance_px(inner_weight, "detail"))` drawn as a closed `detail` vector; two at complexity >= 0.6, else one; an echo that does not fit is dropped; the slot becomes the innermost echo with `slot_outline_weight="detail"`.
- Registry `embellishments`: petal `("echo", "veins", "fan", "dot")`, leaf `("echo", "veins")`, band `("beads",)` (beads arrive in Task 11; the composer only picks names the registry lists, and the pipeline ignores an unknown name until then by dropping it).

- [ ] **Step 1: Write the failing tests**

```python
def test_echo_repeats_the_outline_inside(cell_kwargs):
    ctx = make_ctx(cell_kwargs, 4, embellishments=("echo",), complexity=0.3)
    inst = find_motif("petal")["generator"](ctx)
    echoes = [v for v in inst.vectors if v.weight == "detail"]
    assert len(echoes) == 1 and echoes[0].closed
    outer = Polygon(ctx.polyline(inst.vectors[0], 0.0)); inner = Polygon(ctx.polyline(echoes[0], 0.0))
    assert outer.contains(inner)
    assert outer.exterior.distance(inner.exterior) >= ctx.clearance_px("outline", "detail") - 1e-6

def test_two_echoes_at_high_complexity(cell_kwargs):
    ctx = make_ctx(cell_kwargs, 4, embellishments=("echo",), complexity=0.8)
    assert sum(v.weight == "detail" for v in find_motif("petal")["generator"](ctx).vectors) == 2

def test_embellishment_count_follows_complexity():
    entry = find_motif("petal")
    assert pick_embellishments(entry, 0.2, random.Random(1)) == []
    picks = [pick_embellishments(entry, 1.0, random.Random(s)) for s in range(50)]
    assert all(len(p) == 3 and sum(n in INTERIOR_FILLS for n in p) <= 1 for p in picks)

def test_interior_fill_excludes_slot_child():
    for seed in range(40):
        for ring in plan_for(seed=seed, complexity=1.0).rings:
            for e in ring.sequence:
                for node in (e.centre, e.divider):
                    if node and set(node.embellishments) & set(INTERIOR_FILLS):
                        assert node.slot_child is None

def test_oversized_white_space_drops_detail_silently():
    g = DesignGenerator(seed=42, num_rings=4, ring_divisions=[8, 8, 8, 12], complexity=1.0,
                        min_pattern_size=50, categories=["botanical", "geometric"])
    g.generate()
    assert g.last_validation_result.is_valid and g.assembled.dropped_embellishments > 0
```

- [ ] **Step 2: Run them and see them fail**

Run: `.venv/Scripts/python -m pytest tests/test_embellish.py tests/test_composer.py -q`
Expected: FAIL

- [ ] **Step 3: Implement** the pipeline, echo, anatomy (petal: base `(base_radial, 0)`, tip `(tip_radial, 0)`, outline 0), composer picks and assembler plumbing, and refactor `measure_slot` onto `inset_outline`.

- [ ] **Step 4: Run the full suite and the corpus**

Run: `.venv/Scripts/python -m pytest -q` then `.venv/Scripts/python qa_report.py --corpus`
Expected: PASS; 180/180

- [ ] **Step 5: Commit**

```bash
git add motifs/ composer.py assembler.py coloring_generator.py tests/
git commit -m "feat(embellish): embellishment pipeline with echo outlines"
```

### Task 10: Veins, fan and dot

**Files:**
- Modify: `motifs/embellish.py`
- Modify: `motifs/botanical.py` (leaf's midrib removed from `_leaf_vectors`; `_drop_thin_midrib` deleted; leaf supplies anatomy)
- Test: `tests/test_embellish.py`

**Interfaces:**
- Consumes: Task 9's pipeline, `insert_vertex_on_outline` (Task 2), `page_arc_points` and `page_circle_points` (Task 2).
- Produces: `veins`: a midrib from the anatomy base to the tip, clipped to the innermost closed outline, plus side-vein pairs from points on the midrib toward the tip at 35 to 50 degrees from the midrib, each ending on the innermost outline; consecutive vein starts are at least `clearance_px("detail", "detail")` apart along the midrib; every end is inserted as a vertex into the line it lands on; the count is the most that fit, up to 4 pairs, at least 1 or the embellishment is dropped. `fan`: a half-disc hub of radius `clearance_px("detail", "detail")` at the anatomy base, rays from the hub arc to the innermost outline, count the most for which every wedge is at least `clearance_px("detail", "detail")` wide at the hub arc, at least 3 or dropped. `dot`: a `detail` circle of diameter drawn in `[min_white_space, 2 * min_white_space]`, centred on the axis just above the base, kept at least `clearance_px("outline", "detail")` from all ink, dropped otherwise.
- Leaf's veins replace its old midrib, so a leaf without `veins` has no midrib.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize("name", ["veins", "fan", "dot"])
@pytest.mark.parametrize("host", ["petal", "leaf"])
def test_embellishment_is_valid_or_dropped(name, host, cell_kwargs):
    if name not in find_motif(host)["embellishments"]:
        pytest.skip("host does not accept it")
    for seed in range(10):
        inst = find_motif(host)["generator"](make_ctx(cell_kwargs, seed, embellishments=(name,)))
        assert inst.dropped_embellishments in (0, 1)   # build_instance already validated the vectors

def test_vein_ends_are_vertices_of_the_ink_they_touch(cell_kwargs):
    inst = find_motif("leaf")["generator"](make_ctx(cell_kwargs, 2, embellishments=("veins",)))
    closed = [v for v in inst.vectors if v.closed]
    for v in inst.vectors:
        if not v.closed:
            for end in (v.points[0], v.points[-1]):
                assert any(end in c.points for c in closed) or any(end in o.points for o in inst.vectors if o is not v)

def test_fan_wedges_are_colourable(cell_kwargs):
    ctx = make_ctx(cell_kwargs, 5, embellishments=("fan",))
    inst = find_motif("petal")["generator"](ctx)
    rays = [v for v in inst.vectors if v.weight == "detail" and not v.closed]
    assert len(rays) >= 3
```

- [ ] **Step 2: Run them and see them fail**

Run: `.venv/Scripts/python -m pytest tests/test_embellish.py -q`
Expected: FAIL

- [ ] **Step 3: Implement the three embellishments and move the leaf midrib**

- [ ] **Step 4: Run the full suite and the corpus**

Run: `.venv/Scripts/python -m pytest -q` then `.venv/Scripts/python qa_report.py --corpus`
Expected: PASS; 180/180

- [ ] **Step 5: Commit**

```bash
git add motifs/ tests/
git commit -m "feat(embellish): veins, fan and dot"
```

### Task 11: Beads on bands

**Files:**
- Modify: `motifs/embellish.py`, `motifs/geometric.py` (band calls the pipeline)
- Modify: `composer.py` (a seam motif's copied recipe carries entry 0's embellishments to every entry)
- Test: `tests/test_embellish.py`

**Interfaces:**
- Consumes: `context.ring_rng`, which the band has already drawn its radii from; beads continue the same stream, so every cell draws the same beads.
- Produces: `beads`: `k` closed `detail` circles centred at radial `(r1 + r2) / 2` and evenly spaced in angular, `k` drawn from `ring_rng` in `[1, 3]`, diameter drawn from `ring_rng` and capped so each bead keeps `clearance_px("outline", "detail")` from both arcs and `clearance_px("detail", "detail")` from its neighbours and the seam; dropped when even `k = 1` does not fit.

- [ ] **Step 1: Write the failing tests**

```python
def test_beads_are_the_same_in_every_cell(cell_kwargs):
    make = lambda s: find_motif("band")["generator"](make_ctx(cell_kwargs, s, ring_stream_seed=5, embellishments=("beads",)))
    a, b = make(1), make(2)
    assert [v.points for v in a.vectors] == [v.points for v in b.vectors]
    assert any(v.closed and v.weight == "detail" for v in a.vectors)

def test_seam_recipe_copies_carry_embellishments():
    for seed in range(40):
        for ring in plan_for(seed=seed, categories=["geometric"], complexity=1.0).rings:
            for pos in ("centre", "divider"):
                nodes = [getattr(e, pos) for e in ring.sequence]
                if nodes[0] and find_motif(nodes[0].motif)["seams"]:
                    assert all(n.embellishments == nodes[0].embellishments for n in nodes)
```

- [ ] **Step 2: Run them and see them fail**

Run: `.venv/Scripts/python -m pytest tests/test_embellish.py -q`
Expected: FAIL

- [ ] **Step 3: Implement**

- [ ] **Step 4: Run the full suite and the corpus**

Run: `.venv/Scripts/python -m pytest -q` then `.venv/Scripts/python qa_report.py --corpus`
Expected: PASS; 180/180

- [ ] **Step 5: Commit**

```bash
git add motifs/ composer.py tests/
git commit -m "feat(embellish): bead rows on bands"
```

### Task 12: Layered rings

**Files:**
- Create: `motifs/layering.py`
- Modify: `composer.py` (`POSITION_MODES`, `_position_mode`, `plan_ring`, `RingPlan.back`, `RingPlan.back_dropped`, `ComposerSettings.force_position_mode`, `drop_back`)
- Modify: `assembler.py` (`_generate` used by `_place_node` and `regenerate`; `_place_ring` handles `LayeringError`; `LayeredRingFailed`)
- Modify: `coloring_generator.py` (`force_position_mode` parameter; retry on `LayeredRingFailed`)
- Modify: `qa_report.py` (`--force-mode {centre,divider,both,layered}` passed to `DesignGenerator(force_position_mode=...)`)
- Modify: `motifs/botanical.py` (petal and leaf roles gain `"back"`)
- Test: create `tests/test_layering.py`; `tests/test_composer.py`, `tests/test_design_generator.py`

**Interfaces:**
- Produces: `class LayeringError(MotifError)` in `motifs/layering.py`; `compose_layered(front_context: MotifContext, front_entry: Dict, back_context: MotifContext, back_entry: Dict) -> MotifInstance` following spec 5.2 steps 1 to 7, built with `build_instance(..., seams=True, slot=front.declaration.slot, anatomy=front.declaration.anatomy, base_point=front.declaration.base_point, reach_ends=front.declaration.reach_ends)`, back vectors marked `layer="back"`; raises `LayeringError` for any failure that comes from the back or the cut; a front failure raises the front's own `MotifError`.
- Back context: `replace(front_context, rng=random.Random(s), node_seed=s, position="divider", angular_limits=1.0, radial_limits=(0.0, 1.0), slot=None, side_touch_radial=None, embellishments=tuple(ring.back.embellishments))` with `s = ring_stream_seed(ring.ring_seed, ring.ring_index, "back")`.
- Composer: `POSITION_MODES = ("centre", "divider", "both", "layered")`; `layered` is eligible when `ring_index > 0`, some motif with role `"back"` passes its size gates at budget 1.0, and some base candidate has `"base"` in its touch heights. Its centre candidates are those base candidates (non-seam). `RingPlan.back` is picked with a stream salted `"pick:back"` and gets embellishments picked the same way. `touch_height = "base"`. `RingPlan.back: Optional[CellRecipe] = None` and `back_dropped: bool = False` serialise. `Composer.drop_back(ring: RingPlan) -> None` sets `back=None`, `back_dropped=True` and leaves the centre entries. `ComposerSettings.force_position_mode: Optional[str] = None` forces that mode on every ring with index > 0 where it is eligible.
- Assembler: in pass one, a `LayeringError` from a centre node of a layered ring calls `composer.drop_back(ring)`, rewinds and places the ring again without counting a replacement. In pass two, a `LayeringError` raised through `regenerate` surfaces as `LayeredRingFailed(ring_index)`. `DesignGenerator.generate` catches it, calls `drop_back` on that ring of its plan, and assembles again, at most once per ring.

- [ ] **Step 1: Write the failing tests**

```python
def layered_design(**over):
    return DesignGenerator(**{"seed": 42, "num_rings": 4, "ring_divisions": [8, 8, 8, 12],
                              "categories": ["botanical"], "force_position_mode": "layered", **over})

def test_layered_design_validates_and_has_back_ink():
    g = layered_design(); g.generate()
    assert g.last_validation_result.is_valid, g.last_validation_result.issues[:5]
    assert any(r.back is not None for r in g.plan.rings[1:])
    assert any(p.role == "back" for p in g.assembled.paths)

def test_back_never_crosses_the_front_and_cut_points_are_front_vertices(cell_kwargs):
    front, back = find_motif("petal"), find_motif("leaf")
    fctx = make_ctx(cell_kwargs, 3, side_touch_radial=0.12)
    bctx = replace(fctx, rng=random.Random(9), node_seed=9, position="divider", radial_limits=(0.0, 1.0),
                   side_touch_radial=None)
    inst = compose_layered(fctx, front, bctx, back)
    front_outline = inst.vectors[0].points
    fill = Polygon([(p.angular, p.radial) for p in front_outline])
    for v in inst.vectors:
        if v.layer == "back":
            assert not LineString([(p.angular, p.radial) for p in v.points]).crosses(fill.exterior)
            for end in (v.points[0], v.points[-1]):
                assert abs(end.angular) == 1.0 or end in front_outline

def test_dense_layered_ring_drops_its_back_and_still_validates():
    g = layered_design(ring_divisions=[24, 24, 24, 24], complexity=0.9); g.generate()
    assert g.last_validation_result.is_valid
    assert all(r.back is None for r in g.plan.rings if r.back_dropped)

def test_regenerated_ring_keeps_its_seams_meeting():
    g = layered_design(); g.generate()
    frag = g.generate_ring_fragment(2, 999)
    assert g.last_validation_result.is_valid and g.validation_summary()["dangling_end_count"] == 0
```

Add `test_pass_two_layering_failure_drops_the_back(monkeypatch)`: wrap `motifs.layering.compose_layered` so it raises `LayeringError` when `front_context.radial_limits[1] < 1.0 + front_entry["max_overflow_outward"]`, generate `layered_design()`, and assert the design validates and the affected ring has `back_dropped`. Also add `test_layered_is_never_ring_zero` and `test_layered_rings_use_base_touch` to `tests/test_composer.py`.

- [ ] **Step 2: Run them and see them fail**

Run: `.venv/Scripts/python -m pytest tests/test_layering.py tests/test_composer.py tests/test_design_generator.py tests/test_app.py -q`
Expected: FAIL

- [ ] **Step 3: Implement** the composite in cell space with Shapely (x = angular, y = radial): shift with `+1.0` and `-1.0`, intersect with the strip `-1 <= x <= 1`, subtract the front fill polygon, insert cut points with `insert_vertex_on_outline`, drop short unseamed pieces, run the clearance check of spec 5.2 step 6 in page space with a touch disc of `max(min_white_space, 8.0)` px around each cut point.

- [ ] **Step 4: Run the full suite and the corpus**

Run: `.venv/Scripts/python -m pytest -q` then `.venv/Scripts/python qa_report.py --corpus`
Expected: PASS; 180/180

- [ ] **Step 5: Commit**

```bash
git add motifs/ composer.py assembler.py coloring_generator.py qa_report.py tests/
git commit -m "feat(layering): layered rings with hidden-line removal"
```

### Task 13: Phase 2 QA, docs and visual gate

**Files:**
- Modify: `qa_patterns.py` (CUT and EMB checks; matrix runs each motif with each accepted embellishment, and each front with each back in a forced layered ring)
- Modify: `qa_report.py` (corpus forces `layered` on the jobs whose seed is one of the first three `CORPUS_SEEDS`; report columns for layered rings and embellishment counts; a corpus summary line asserting the quotas)
- Modify: `docs/motifs.md`, `docs/architecture.md`
- Test: `tests/test_qa_patterns.py`, `tests/test_qa_report.py`

**Interfaces:**
- Produces: `property_checks(entry)` adds `cut` (true when the motif has no `"back"` role, or when `compose_layered` with a petal front and this back at seeds 0 to 5 yields back ends that are seam ends or front-outline vertices) and `embellished` (DET and MONO hold for the motif with all its accepted embellishments at complexity 0.9). `qa_report` corpus summary prints `layered rings: X/Y botanical+geometric rings (>= 25%)` and `embellishments: name=count ...` and exits non-zero when the layered share is below 25% or any embellishment appears fewer than 10 times.

- [ ] **Step 1: Write the failing tests**

```python
def test_property_checks_include_cut_and_embellished():
    for entry in MOTIFS:
        outcome = property_checks(entry)
        assert {"cut", "embellished"} <= set(outcome) and all(outcome.values()), (entry["name"], outcome)

def test_corpus_quotas_are_checked():
    rows = [{"categories": ["botanical"], "layered_rings": 0, "rings": 4, "embellishments": {}}]
    assert corpus_quota_failures(rows)   # names the layered share and each missing embellishment
```

- [ ] **Step 2: Run them and see them fail**

Run: `.venv/Scripts/python -m pytest tests/test_qa_patterns.py tests/test_qa_report.py -q`
Expected: FAIL

- [ ] **Step 3: Implement**, with `corpus_quota_failures(rows) -> List[str]` in `qa_report.py`. Update `docs/motifs.md` (anatomy, embellishments, layering, back role) and `docs/architecture.md` (the composite and its failure path).

- [ ] **Step 4: Run the gates**

Run: `.venv/Scripts/python -m pytest -q`, `.venv/Scripts/python qa_patterns.py --tier full`, `.venv/Scripts/python qa_report.py --corpus`
Expected: all pass; corpus 180/180 with both quotas met

- [ ] **Step 5: Commit**

```bash
git add qa_patterns.py qa_report.py docs/ tests/
git commit -m "test(qa): layering and embellishment checks; document phase 2"
```

- [ ] **Step 6: Visual gate.** As Task 8 step 6, into `review/phase2/`, plus one run at complexity 0.6 with `--force-mode layered`. Send the files and stop until the user's verdict.

## Phase 3: new motifs

Every new motif is a registry entry with all keys (`name, category, generator, positions, roles, touch, side_touch_heights, seams, spans_cell, min_cell_width_px, min_ring_depth_px, max_overflow_inward, max_overflow_outward, slot_estimate, embellishments`). The parametrised tests in `tests/test_motifs.py` (DET, narrow limits, MONO, slot presence) and `property_checks` cover each new entry automatically once it is registered. Each task adds only shape-specific tests. Size gates: 14px cell width and 18px ring depth unless a task says otherwise. Overflow: 0.0 inward and 0.2 outward for bases, 0.0 for slot-only and back-only use.

### Task 14: Teardrop and rounded petal

**Files:**
- Modify: `motifs/botanical.py`
- Test: `tests/test_motifs.py`

**Interfaces:**
- Produces: `teardrop` (botanical; positions centre and divider; roles base, slot, back; heights base and mid; accepts echo and dot; `slot_estimate (0.45, 0.45)`): the base is a page-space circular arc via `page_arc_points`, the sides are cubic segments to a point at angular 0, with tangents at the arc ends continuous. `rounded_petal` (botanical; same positions, roles and heights; accepts echo, veins, fan and dot; `slot_estimate (0.5, 0.5)`): the lotus profile of Task 6 with the tip replaced by a circular arc tangent to both sides. Both supply anatomy.

- [ ] **Step 1: Write the failing tests**

```python
def test_teardrop_has_a_round_base_and_a_sharp_tip(cell_kwargs):
    ctx = make_ctx(cell_kwargs, 6)
    pts = find_motif("teardrop")["generator"](ctx).vectors[0].points
    tip = max(range(len(pts)), key=lambda k: pts[k].radial)
    assert max_turn_deg(ctx, pts, True, {tip}) <= 35.0 and turn_at(ctx, pts, tip) >= 60.0

def test_rounded_petal_has_no_corner_at_its_tip(cell_kwargs):
    for seed in range(10):
        ctx = make_ctx(cell_kwargs, seed, side_touch_radial=0.12)
        pts = find_motif("rounded_petal")["generator"](ctx).vectors[0].points
        base = min(range(len(pts)), key=lambda k: (pts[k].radial, abs(pts[k].angular)))
        assert max_turn_deg(ctx, pts, True, {base}) <= 35.0
```

`turn_at(context, points, index) -> float` is added to `qa_patterns.py` alongside `max_turn_deg`.

- [ ] **Step 2: Run them and see them fail**

Run: `.venv/Scripts/python -m pytest tests/test_motifs.py -q`
Expected: FAIL

- [ ] **Step 3: Implement both generators and register them**

- [ ] **Step 4: Run the full suite and the smoke tier**

Run: `.venv/Scripts/python -m pytest -q` then `.venv/Scripts/python qa_patterns.py --tier smoke`
Expected: PASS; smoke exit 0

- [ ] **Step 5: Commit**

```bash
git add motifs/ qa_patterns.py tests/
git commit -m "feat(motifs): teardrop and rounded petal"
```

### Task 15: Heart and curl

**Files:**
- Modify: `motifs/botanical.py`
- Test: `tests/test_motifs.py`

**Interfaces:**
- Produces: `heart` (botanical; position centre; roles base and slot; heights mid; accepts echo; `slot_estimate (0.45, 0.4)`): two lobes, each a page-space circular arc, meeting at a cusp on the centreline at the top and running by cubic segments to a point on the centreline at the bottom; with side touch, the lobes' widest vertices are the touch vertices with radial tangents. `curl` (botanical; position centre; roles base and slot; heights mid; accepts nothing; `slot_estimate None`; size gates 28px cell width and 24px ring depth): two mirrored spirals joined at the base, each one open vector whose inner end lands on its own earlier turn, consecutive turns at least `clearance_px()` apart in page space, at most 1.5 turns; with side touch, each spiral's outermost vertex on the cell edge is the touch vertex.

- [ ] **Step 1: Write the failing tests**

```python
def test_heart_has_its_cusp_and_point_on_the_centreline(cell_kwargs):
    pts = find_motif("heart")["generator"](make_ctx(cell_kwargs, 2)).vectors[0].points
    on_axis = [p for p in pts if p.angular == 0.0]
    assert len(on_axis) == 2

def test_curl_inner_end_lands_on_an_earlier_turn(cell_kwargs):
    ctx = make_ctx(cell_kwargs, 8, side_touch_radial=0.45)
    for v in find_motif("curl")["generator"](ctx).vectors:
        earlier = LineString(ctx.polyline(SmartVector(v.points[:-3])))
        assert earlier.distance(Point(ctx.to_cartesian(v.points[-1]))) <= 1e-6
```

Add `test_curl_turns_keep_white_space`: for each spiral, sample it in page space by turning angle about the spiral's centre, and assert the distance between the samples at angle `t` and `t + 360` degrees is at least `ctx.clearance_px()` wherever both exist.

- [ ] **Step 2: Run them and see them fail**

Run: `.venv/Scripts/python -m pytest tests/test_motifs.py -q`
Expected: FAIL

- [ ] **Step 3: Implement both generators and register them**

- [ ] **Step 4: Run the full suite and the smoke tier**

Run: `.venv/Scripts/python -m pytest -q` then `.venv/Scripts/python qa_patterns.py --tier smoke`
Expected: PASS; smoke exit 0

- [ ] **Step 5: Commit**

```bash
git add motifs/ tests/
git commit -m "feat(motifs): heart and curl"
```

### Task 16: Bead and spike

**Files:**
- Modify: `motifs/geometric.py`
- Test: `tests/test_motifs.py` (including `test_registry_lookup`)

**Interfaces:**
- Produces: `bead` (geometric; position divider; roles base and slot; heights base and mid; accepts echo; `slot_estimate None`; size gates 10px and 10px): a `page_circle_points` circle; as a base with side touch, its radius is set so its two horizontal-diameter ends are exactly the vertices `(side_touch_radial, ±angular_limits)`, with radial tangents there by construction; as a slot child, the largest circle `fit_inside_slot` accepts. `spike` (geometric; positions centre and divider; roles base and back; heights base; accepts echo and fan; `slot_estimate (0.4, 0.4)`): a star point with concave cubic sides from the base corners (the touch vertices at `base` height) to a sharp tip at angular 0.
- `test_registry_lookup` expects geometric names `{"diamond", "band", "bead", "spike"}`.

- [ ] **Step 1: Write the failing tests**

```python
def test_bead_diameter_spans_the_touch_vertices(cell_kwargs):
    ctx = make_ctx(cell_kwargs, 1, side_touch_radial=0.45, angular_limits=0.4)
    pts = find_motif("bead")["generator"](ctx).vectors[0].points
    assert CellPoint(0.45, 0.4) in pts and CellPoint(0.45, -0.4) in pts

def test_spike_sides_are_concave(cell_kwargs):
    ctx = make_ctx(cell_kwargs, 4, side_touch_radial=0.12)
    pts = find_motif("spike")["generator"](ctx).vectors[0].points
    tip = max(pts, key=lambda p: p.radial)
    corner = CellPoint(0.12, 1.0)
    right = [p for p in pts if p.angular > 0 and corner.radial < p.radial < tip.radial]
    chord = lambda r: 1.0 - (r - corner.radial) / (tip.radial - corner.radial)
    assert right and all(p.angular < chord(p.radial) for p in right)
```

- [ ] **Step 2: Run them and see them fail**

Run: `.venv/Scripts/python -m pytest tests/test_motifs.py -q`
Expected: FAIL

- [ ] **Step 3: Implement both generators and register them**

- [ ] **Step 4: Run the full suite and the smoke tier**

Run: `.venv/Scripts/python -m pytest -q` then `.venv/Scripts/python qa_patterns.py --tier smoke`
Expected: PASS; smoke exit 0

- [ ] **Step 5: Commit**

```bash
git add motifs/ tests/
git commit -m "feat(motifs): bead and spike"
```

### Task 17: Phase 3 QA, docs and final visual gate

**Files:**
- Modify: `docs/motifs.md` (the twelve motifs, each with its parameters, roles, heights and accepted embellishments), `README.md` (motif list), `qa_report.py` only if a quota fails
- Test: the whole suite

- [ ] **Step 1: Run the gates**

Run: `.venv/Scripts/python -m pytest -q`, `.venv/Scripts/python qa_patterns.py --tier full`, `.venv/Scripts/python qa_report.py --corpus`
Expected: all pass; full tier lists twelve motifs with every property column PASS; corpus 180/180 with both quotas met

- [ ] **Step 2: Update the docs**

- [ ] **Step 3: Commit**

```bash
git add docs/ README.md qa_report.py
git commit -m "docs: the twelve-motif vocabulary"
```

- [ ] **Step 4: Visual gate.** As Task 8 step 6, into `review/phase3/`, with one extra run forcing `layered`. Send the files and stop until the user's verdict.
