# Maximum Region Size Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Measure every colourable face against a complexity-scaled print-size cap and, after a valid assembly, climb a repair ladder that adds detail to the plan entry behind each oversized face set, keeping the best valid design and recording every repair in the plan.

**Architecture:** The validator gains the cap and reports oversized faces as a soft issue. A new module, `region_repair.py`, classifies each oversized face (host interior, centre, background), groups the symmetric copies by the plan entry behind them, and runs the ladder. Every ladder step edits a deep copy of the current plan through new `Composer` methods, re-assembles it with a fresh composer and re-validates; a step is kept only when the result is valid and leaves no more oversized area than before. The plan as it stood before its final assembly is kept as `DesignGenerator.source_plan`, so `generate_from_plan` replays a repaired design without the ladder.

**Tech Stack:** Python 3, Shapely 2.1, svgwrite, Flask, pytest; Windows, run everything with `.venv/Scripts/python`.

**Spec:** `docs/superpowers/specs/2026-10-16-max-region-size-design.md`. Authoring guide: `docs/motifs.md`. Style model: `docs/superpowers/plans/2026-10-09-motif-aesthetics.md`.

## Global Constraints

- `PX_PER_INCH = 72.0`; `max_region_in2(complexity) = 1.25 - 0.65 * clamp(complexity, 0, 1)`; `max_region_px2 = max_region_in2 * 72²` (1.0 in² = 5,184 px²). Both live in `topology_validator.py` beside `MIN_REGION_AREA_PX2`.
- The validator stays the authority and no structural rule loosens: an oversized face never changes `is_valid`, and every kept repair passes `analyze` exactly as today. `MIN_REGION_AREA_PX2`, pen and clearance rules are untouched.
- The spec's `ValidationResult` is `TopologyReport` in this codebase (the legacy name, see its docstring); it gains `oversized_regions: List[RegionInfo]`, and its stats gain `num_oversized_regions` and `largest_region_in2`.
- `max_region_cap: bool = True` on `ComposerSettings` and `DesignGenerator`. With it off nothing is measured against the cap or repaired, and the SVG is byte-identical to the pre-cap engine.
- Salts are mixed with `zlib.crc32` via `salted_seed` / `node_seed(..., salt)` / `ring_stream_seed`, never `hash()`. Repair salts: `"repair:1"` (host detail), `"repair:2"` (background), `"repair:3"` (rosette), `"repair:4:<attempt>"` (re-roll seed, attempt 1 to 3).
- Ladder per face kind: host `1 -> 4 -> 5`, background `2 -> 4 -> 5`, centre `3 -> 4 -> 5`. At most `MAX_LADDER_SETS = 8` face sets are handled per design, `MAX_REROLLS = 3` re-roll attempts per set, `REPAIR_SIZE_FLOOR = 0.7`.
- Old plan JSON loads: `CellRecipe.size_floor = 0.0`, `RingPlan.rosette = None`, `DesignPlan.repairs = []`.
- Never hard-wrap prose in Markdown or commit bodies. Commit messages carry no attribution trailer.
- Commit with explicit pathspecs only; other Claude sessions work in this folder concurrently. Never `git add -A`, `git add .` or `git commit -a`, and never touch `.git/index.lock`.
- Gates: `.venv/Scripts/python qa_patterns.py --tier full` exits 0; `.venv/Scripts/python qa_report.py --corpus` reports 180/180 with both existing quotas (layered share, embellishments) and the new oversized ceiling; `.venv/Scripts/python -m pytest -q` passes. The corpus and the full tier take many minutes: run them with output redirected to a log (`> test_output/<name>.log 2>&1`, `test_output/` is git-ignored) and read the log's tail, never stream them.
- The visual review set goes under `review/max-region/` (git-ignored, never committed) and work stops for the user's verdict.

## Review Focus

1. A ring 0 with many divisions or a small free radius, where no rosette fits: the rosette must be refused with `MotifError`, dropped, the step skipped, and the design still valid. Test in Task 6.
2. QA-forced designs (`force_motif`, `force_position_mode="layered"` as the corpus uses): step 2 must never switch a forced ring's position mode, and a re-roll must keep the forced mode, so the corpus layered quota holds. Tests in Tasks 4 and 7.
3. `generate_ring_fragment` (the `/regenerate-ring` API) on a design the ladder repaired: rebuilding from the seed plus `ring_seeds` must reproduce the same repaired SVG. Test in Task 7.
4. `generate(validate=False)` with the cap on: the ladder runs anyway, so the SVG equals `generate(validate=True)`; only `last_validation_result` differs. Test in Task 3.
5. Plans saved before this work, and plans after a repair, round-trip through `DesignPlan.to_json` / `from_json` and replay. Tests in Tasks 3, 4, 6 and 7.

---

### Task 1: The cap and oversized-face reporting

**Files:**
- Modify: `topology_validator.py` (constants beside `MIN_REGION_AREA_PX2`, `TopologyReport`, `TopologyValidator.__init__`, `analyze`)
- Modify: `composer.py` (`ComposerSettings`)
- Modify: `coloring_generator.py` (`DesignGenerator.__init__`, `generate`, `_validate`)
- Test: `tests/test_region_cap.py` (new)

**Interfaces:**
- Produces: `PX_PER_INCH = 72.0`; `max_region_in2(complexity: float) -> float`; `max_region_px2(complexity: float) -> float`; `TopologyReport.oversized_regions: List[RegionInfo] = field(default_factory=list)`; `TopologyValidator(..., max_region_px2: Optional[float] = None)`; stats `num_oversized_regions: int` (0 when the cap is None) and `largest_region_in2: float` (largest region area / 72², rounded to 3 places, 0.0 with no regions, always computed); `ComposerSettings.max_region_cap: bool = True`; `DesignGenerator(..., max_region_cap: bool = True)` stored as `self.max_region_cap` and passed into the settings; `DesignGenerator._validation_report(assembled: AssembledDesign) -> Tuple[TopologyReport, List[List[PointTuple]]]` (today's `_validate` body without the printing, passing `max_region_px2(self.complexity)` when the cap is on, else None).

- [ ] **Step 1: Write the failing tests**

```python
def square(side, at=(100.0, 100.0)):
    x, y = at
    return [(x, y), (x + side, y), (x + side, y + side), (x, y + side), (x, y)]

def test_cap_values():
    assert max_region_in2(0.0) == pytest.approx(1.25)
    assert max_region_in2(0.6) == pytest.approx(0.86)
    assert max_region_in2(1.0) == pytest.approx(0.6)
    assert max_region_in2(-1.0) == pytest.approx(1.25) and max_region_in2(2.0) == pytest.approx(0.6)
    assert max_region_px2(0.6) == pytest.approx(0.86 * 5184.0) and PX_PER_INCH == 72.0

def test_oversized_face_is_reported_not_failed():
    cap = max_region_px2(0.5)                       # 4795.2 px2
    report = TopologyValidator(max_region_px2=cap).analyze([square(100.0)])
    plain = TopologyValidator().analyze([square(100.0)])
    assert len(report.oversized_regions) == 1 and report.stats["num_oversized_regions"] == 1
    assert report.stats["largest_region_in2"] == pytest.approx(round(10000.0 / 5184.0, 3))
    assert report.is_valid == plain.is_valid and report.issues == plain.issues
    assert plain.oversized_regions == [] and plain.stats["num_oversized_regions"] == 0

def test_face_under_the_cap_is_not_oversized():
    report = TopologyValidator(max_region_px2=max_region_px2(0.5)).analyze([square(60.0)])
    assert report.oversized_regions == []

def test_generator_reports_largest_region():
    g = DesignGenerator(seed=42, num_rings=4, ring_divisions=[8, 8, 8, 12], max_region_cap=False)
    g.generate()
    assert g.last_validation_result.stats["num_oversized_regions"] == 0
    assert g.last_validation_result.stats["largest_region_in2"] > 0.0

@pytest.mark.parametrize("case", sorted(PRE_CAP_SVG_SHA))
def test_cap_off_reproduces_the_pre_cap_engine(case):
    seed, complexity, category = case
    svg = DesignGenerator(seed=seed, complexity=complexity, categories=[category], max_region_cap=False).generate()
    assert hashlib.sha256(svg.encode("utf-8")).hexdigest() == PRE_CAP_SVG_SHA[case]
```

Before writing any code, fill `PRE_CAP_SVG_SHA` (a dict keyed by `(seed, complexity, category)`) with the sha256 of `DesignGenerator(seed=seed, complexity=complexity, categories=[category]).generate()` on the unmodified engine, for seeds 42, 777 and 12345, complexities 0.5 and 0.85, categories botanical and geometric (12 cases). This test guards every later task.

- [ ] **Step 2: Run them and see them fail**

Run: `.venv/Scripts/python -m pytest tests/test_region_cap.py -q`
Expected: FAIL with ImportError on `max_region_in2`

- [ ] **Step 3: Implement**

`analyze` appends nothing to `issues` for an oversized face; `oversized_regions` lists every region with `area > max_region_px2`, in region order. `generate` is unchanged in this task apart from `_validate` now calling `_validation_report`.

- [ ] **Step 4: Run the full suite**

Run: `.venv/Scripts/python -m pytest -q`
Expected: PASS (nothing repairs yet, so no output changes)

- [ ] **Step 5: Commit**

```bash
git add topology_validator.py composer.py coloring_generator.py tests/test_region_cap.py
git commit -m "feat(validator): print-scale region cap reported as a soft issue"
```

### Task 2: Face classification and owner matching

**Files:**
- Create: `region_repair.py`
- Modify: `composer.py` (new module-level `recipe_at`)
- Test: `tests/test_region_cap.py`

**Interfaces:**
- Consumes: `RegionInfo`, `PlacedPath` (`ring_index`, `cell_index`, `position`, `node_path`, `role`, `coords`, `closed`, `stroke_width`).
- Produces in `region_repair.py`: `FACE_KINDS = ("host", "background", "centre")`; `HOST_ROLES = ("base", "back", "slot", "detail")`; `NodeKey = Tuple[int, int, str, Tuple[int, ...]]`; `@dataclass OversizedFace(region: RegionInfo, kind: str, ring_index: int, position: Optional[str] = None, node_path: Optional[Tuple[int, ...]] = None, on_back: bool = False, bordering: Tuple[NodeKey, ...] = ())` with property `key -> Tuple` (`("host", ring, position, node_path[0], node_path[1:], on_back)`, `("background", ring)`, `("centre", 0)`); `@dataclass FaceSet(key: Tuple, kind: str, ring_index: int, faces: List[OversizedFace])` with properties `area -> float` and `first -> OversizedFace`; `classify_faces(regions: Sequence[RegionInfo], paths: Sequence[PlacedPath], rings: Sequence[Dict[str, float]], center: PointTuple) -> List[OversizedFace]`; `face_sets(faces: Sequence[OversizedFace]) -> List[FaceSet]` sorted by `(ring_index, FACE_KINDS.index(kind), key)`.
- Produces in `composer.py`: `recipe_at(ring: RingPlan, position: str, node_path: Tuple[int, ...], on_back: bool = False) -> Optional[CellRecipe]` (`ring.back` when `on_back`; else the sequence entry `node_path[0]` at `position`, then `slot_child` once per further element; None where the chain ends).

Classification, in this order:
1. **Centre:** `region.polygon.covers(Point(center))`; ring 0.
2. **Host:** among closed paths whose role is in `HOST_ROLES`, those whose `Polygon(coords).buffer(stroke_width).covers(region.polygon)`; the one with the smallest polygon area is the host. A detail outline (an echo) maps to its own node, so `on_back` is true only for role `"back"`.
3. **Background:** otherwise. The owner is the ring whose annulus (`inner_radius` to `outer_radius` about `center`) holds the largest share of the face's area, ties broken by the ring holding the label point; `bordering` is the sorted, de-duplicated `NodeKey`s of paths whose distance to the face's exterior is at most their `stroke_width`.

- [ ] **Step 1: Write the failing tests**

Hand-built on `center = (306, 306)`, `rings = [{"inner_radius": 20, "outer_radius": 100}, {"inner_radius": 100, "outer_radius": 200}]`: a closed circle of radius 100 (ring 0, cell 0, `"centre"`, `(0,)`, role `"base"`), a closed circle of radius 200 (ring 1, cell 0, `"centre"`, `(0,)`, `"base"`) and a closed square petal 40 px a side centred at radius 150 (ring 1, cell 3, `"divider"`, `(1,)`, `"base"`). Faces come from `TopologyValidator().faces(polylines)`.

```python
def test_centre_face_is_owned_by_ring_zero(design):
    centre = [f for f in classify_faces(*design) if f.kind == "centre"]
    assert len(centre) == 1 and centre[0].ring_index == 0 and centre[0].key == ("centre", 0)

def test_host_face_maps_to_its_node(design):
    host = [f for f in classify_faces(*design) if f.kind == "host"]
    assert len(host) == 1
    assert (host[0].ring_index, host[0].position, host[0].node_path) == (1, "divider", (1,))
    assert host[0].key == ("host", 1, "divider", 1, (), False)

def test_background_face_is_owned_by_the_ring_holding_most_of_it(design):
    back = [f for f in classify_faces(*design) if f.kind == "background"]
    assert len(back) == 1 and back[0].ring_index == 1
    assert (1, 3, "divider", (1,)) in back[0].bordering and (0, 0, "centre", (0,)) in back[0].bordering

def test_symmetric_copies_form_one_set(design_four_petals):    # four copies of the petal, cells 0, 3, 6, 9
    sets = face_sets([f for f in classify_faces(*design_four_petals) if f.kind == "host"])
    assert len(sets) == 1 and len(sets[0].faces) == 4

def test_recipe_at_walks_slot_children_and_back():
    child = CellRecipe("diamond", "geometric")
    ring = RingPlan(1, 8, 1.0, [CellEntry(CellRecipe("petal", "botanical", slot_child=child), None)], 0,
                    back=CellRecipe("leaf", "botanical"))
    assert recipe_at(ring, "centre", (0,)) is ring.sequence[0].centre
    assert recipe_at(ring, "centre", (0, 0, 0)) is None
    assert recipe_at(ring, "centre", (0, 0)) is ring.sequence[0].centre.slot_child
    assert recipe_at(ring, "divider", (0,), on_back=True) is ring.back
```

- [ ] **Step 2: Run them and see them fail**

Run: `.venv/Scripts/python -m pytest tests/test_region_cap.py -q`
Expected: FAIL with ImportError on `region_repair`

- [ ] **Step 3: Implement `classify_faces`, `face_sets` and `recipe_at`**

- [ ] **Step 4: Run them and see them pass**

Run: `.venv/Scripts/python -m pytest tests/test_region_cap.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add region_repair.py composer.py tests/test_region_cap.py
git commit -m "feat(repair): classify oversized faces and match them to plan entries"
```

### Task 3: Ladder engine, replay and step 1 (detail inside the host)

**Files:**
- Modify: `region_repair.py` (`Trial`, `RegionRepair`)
- Modify: `coloring_generator.py` (`generate`, `_assemble`, new `_new_composer`, `_trial`, `generate_from_plan`, `source_plan`)
- Modify: `composer.py` (`DesignPlan.repairs`, `Composer.adopt`, `Composer.add_embellishment`, `Composer.add_slot_child`)
- Test: `tests/test_region_repair.py` (new)

**Interfaces:**
- Consumes: Task 1 `_validation_report`, `max_region_px2`; Task 2 `classify_faces`, `face_sets`, `FaceSet`, `recipe_at`.
- Produces in `composer.py`: `DesignPlan.repairs: List[Dict[str, Any]] = field(default_factory=list)` (in `to_dict` as `"repairs"`, `from_dict` defaults to `[]`), each record `{"step": int, "kind": str, "ring": int, "change": str}` with `change` one of `"embellishment:<name>"`, `"slot_child:<motif>"`, `"position_mode:both"`, `"size_floor"`, `"rosette"`, `"ring_seed:<int>"`; `Composer.adopt(plan: DesignPlan) -> None` (sets the live rings a substitute reads from); `Composer.add_embellishment(ring: RingPlan, position: str, node_path: Tuple[int, ...], on_back: bool, name: str) -> bool` (False unless the host's registry entry accepts `name`, the host lacks it, and adding it keeps one interior fill and no fill beside a slot child; a seam host gets it in every entry at that position; the list stays in `EMBELLISHMENT_ORDER`); `Composer.add_slot_child(ring: RingPlan, position: str, node_path: Tuple[int, ...], rng: random.Random) -> bool` (False when the host has a slot child or an interior fill, or no slot-role motif passes the gates at the host's `slot_estimate`; otherwise picks one with `_pick` and `rng`).
- Produces in `region_repair.py`: `MAX_LADDER_SETS = 8`; `@dataclass Trial(source_plan: DesignPlan, plan: DesignPlan, assembled: AssembledDesign, report: TopologyReport, polylines: List, sets: List[FaceSet])` with property `oversized_area -> float` (sum of `FaceSet.area`); `class RegionRepair(generator: DesignGenerator)` with `run(first: Trial) -> Trial` and `step_host(trial: Trial, face_set: FaceSet) -> Trial`. Every step returns the trial to continue from: the new one when it is valid and its `oversized_area` is at most the current one's, else the current one.
- Produces in `coloring_generator.py`: `self.source_plan: DesignPlan | None`; `_new_composer() -> Composer`; `_assemble(plan: DesignPlan | None = None, composer: Composer | None = None) -> AssembledDesign` (defaults to `self.plan`, `self.composer`); `_trial(plan: DesignPlan) -> Trial | None` (deep-copies `plan` as `source_plan`, assembles the copy with a fresh, adopted composer, validates, classifies; None on `AssemblyError`); `generate_from_plan(plan: DesignPlan, validate: bool = True) -> str` (assembles a deep copy of `plan` with a fresh adopted composer, never runs the ladder).

`generate` becomes: plan, `source_plan = deepcopy(plan)`, assemble; when `max_region_cap` is on, build the first `Trial` from that assembly (whatever `validate` says) and, when it is valid and has face sets, take `RegionRepair(self).run(first)` and adopt its `source_plan`, `plan`, `assembled` and report; render; set `last_validation_result` only when `validate`.

`run` loop: repeatedly take the first set of the current trial's `face_sets` whose key it has not handled, until none is left or `MAX_LADDER_SETS` sets were handled; for a host set call `step_host` (Tasks 4, 6 and 7 add the other kinds and the re-roll).

`step_host`: the candidates, in order, are `echo`, the interior fill (`veins` or `fan`; when the host accepts both, chosen with `node_rng(ring.ring_seed, ring_index, node_path[0], len(node_path) - 1, position, "repair:1")`), a slot child (only when the placed host's `instance.declaration.slot` is non-empty), then `dot`. Each candidate is applied to a deep copy of the current trial's `plan` and recorded in its `repairs`, then tried with `_trial`; the step stops as soon as the set's key is absent from the current trial's sets.

- [ ] **Step 1: Find the seeds**

Run `.venv/Scripts/python -c` over seeds 0 to 199 at complexity 0.5 and 0.85, botanical and geometric, `ring_divisions` unset, building `DesignGenerator(..., max_region_cap=False)` and printing the seeds whose `classify_faces` over `oversized_regions` gives a host set, a background set in a `centre`-mode ring, a background set in a `both` ring, and a centre set. Pin one seed per case as `HOST_SEED`, `BACKGROUND_CENTRE_MODE_SEED`, `BACKGROUND_BOTH_SEED`, `CENTRE_SEED` (with their complexity and categories) at the top of `tests/test_region_repair.py`.

- [ ] **Step 2: Write the failing tests**

```python
def test_host_step_shrinks_the_set_and_records_it():
    off = gen(HOST_SEED, max_region_cap=False); off.generate()
    key = next(s.key for s in sets_of(off) if s.kind == "host")
    g = gen(HOST_SEED); g.generate()
    assert g.last_validation_result.is_valid
    assert any(r["step"] == 1 and r["change"].startswith(("embellishment:", "slot_child:")) for r in g.plan.repairs)
    assert area_of(g, key) < area_of(off, key)           # 0.0 once the set is under the cap

def test_step_one_respects_the_interior_fill_rule():
    ring = RingPlan(1, 8, 1.0, [CellEntry(CellRecipe("petal", "botanical", embellishments=["veins"]), None)], 0)
    c = composer_for(seed=3)
    assert not c.add_embellishment(ring, "centre", (0,), False, "fan")
    assert c.add_embellishment(ring, "centre", (0,), False, "echo")
    assert ring.sequence[0].centre.embellishments == ["echo", "veins"]
    assert not c.add_embellishment(ring, "centre", (0,), False, "beads")   # petal does not accept beads

def test_a_step_that_fails_validation_is_undone(monkeypatch):
    real = DesignGenerator._trial
    def failing(self, plan):
        trial = real(self, plan)
        if trial is not None and plan.repairs:
            trial.report.is_valid = False
        return trial
    monkeypatch.setattr(DesignGenerator, "_trial", failing)
    assert gen(HOST_SEED).generate() == gen(HOST_SEED, max_region_cap=False).generate()

def test_ladder_runs_without_validation():
    assert gen(HOST_SEED).generate(validate=False) == gen(HOST_SEED).generate()

def test_repaired_plan_replays_without_the_ladder():
    g = gen(HOST_SEED); svg = g.generate()
    plan = DesignPlan.from_json(g.source_plan.to_json())
    assert gen(HOST_SEED).generate_from_plan(plan) == svg

def test_old_plan_json_loads_without_repairs():
    d = plan_for(seed=3).to_dict(); d.pop("repairs")
    assert DesignPlan.from_dict(d).repairs == []
```

Test helpers at the top of `tests/test_region_repair.py`, each added by the task that first uses it: `gen(case, **over)` builds the pinned case's `DesignGenerator` with `over` applied; `composer_for(seed, **settings)` builds a `Composer` on that generator's rings; `sets_of(g)` is `face_sets(classify_faces(...))` over `g.last_validation_result.oversized_regions`; `area_of(g, key)` is that set's area, 0.0 when absent; `set_keys(g)` the set of keys; `background_area(g, ring)` the area of `("background", ring)`; `has_seam_base(ring)` whether any base is a seam motif; `rosette_paths(g)` the paths with `node_path == (ROSETTE_NODE,)`.

- [ ] **Step 3: Run them and see them fail**

Run: `.venv/Scripts/python -m pytest tests/test_region_repair.py -q`
Expected: FAIL

- [ ] **Step 4: Implement**

- [ ] **Step 5: Run the full suite**

Run: `.venv/Scripts/python -m pytest -q`
Expected: PASS once pinned values in tests that reach a repaired design are handled: where a test's intent is pre-cap behaviour (a pinned structure, reach count or plan), pass `max_region_cap=False`; otherwise re-baseline the pinned value after checking the intent still holds.

- [ ] **Step 6: Commit**

```bash
git add region_repair.py coloring_generator.py composer.py tests/
git commit -m "feat(repair): ladder engine, plan replay and detail inside the host"
```

### Task 4: Step 2, fill the background

**Files:**
- Modify: `motifs/geometry.py` (`MotifContext.size_floor`, `size_draw`)
- Modify: `motifs/botanical.py`, `motifs/geometric.py` (size draws)
- Modify: `composer.py` (`CellRecipe.size_floor`, `REPAIR_SIZE_FLOOR`, `Composer.switch_to_both`, `Composer.raise_size_floor`)
- Modify: `assembler.py` (`_context` passes `size_floor=recipe.size_floor`)
- Modify: `region_repair.py` (`step_background`)
- Test: `tests/test_geometry.py`, `tests/test_composer.py`, `tests/test_region_repair.py`

**Interfaces:**
- Consumes: Task 3 `Trial`, `RegionRepair`, `DesignPlan.repairs`.
- Produces: `MotifContext.size_floor: float = 0.0`; `size_draw(context: MotifContext, rng: random.Random, low: float, high: float) -> float` in `motifs/geometry.py`, equal to `low + (high - low) * (context.size_floor + (1.0 - context.size_floor) * rng.random())`, which is exactly `rng.uniform(low, high)` at floor 0.0; `CellRecipe.size_floor: float = 0.0` (in `to_dict`, `from_dict` default 0.0); `REPAIR_SIZE_FLOOR = 0.7`; `Composer.switch_to_both(ring: RingPlan, rng: random.Random) -> bool`; `Composer.raise_size_floor(ring: RingPlan) -> bool`; `RegionRepair.step_background(trial: Trial, face_set: FaceSet) -> Trial`.
- Size draws that switch to `size_draw` (every other draw stays on `rng`): petal, leaf, teardrop and rounded_petal `length` and `half_width`; spike `length` and `width`; bead `size`; heart `width_share`; diamond `aspect`.

`switch_to_both` returns False (changing nothing) when the ring is not in `centre` mode, has a seam base, `force_motif` or `force_position_mode` is set, or `_mode_eligible("both", ...)` fails, or a centre base no longer passes its gates at the new centre width. Otherwise: `position_mode = "both"`, `centre_share = rng.uniform(0.45, 0.75)`, a divider node per entry from `_plan_node(..., "divider", width, depth, avoid, None, allow_seams=False)` with the divider budget, then `_refresh_contact(ring)`. `raise_size_floor` sets every base node's `size_floor` to `REPAIR_SIZE_FLOOR`; False when all already have it.

`step_background`: skip (return the trial) when the owning ring is layered (`position_mode == "layered"`) or has a seam base. A `centre` ring tries `switch_to_both` with `random.Random(ring_stream_seed(ring.ring_seed, ring_index, "repair:2"))`; a `both` or `divider` ring, or a `centre` ring whose switch returned False, tries `raise_size_floor`. Record `"position_mode:both"` or `"size_floor"`.

- [ ] **Step 1: Write the failing tests**

```python
def test_size_draw_matches_uniform_at_floor_zero(cell_kwargs):
    ctx = MotifContext(**cell_kwargs)
    assert size_draw(ctx, random.Random(5), 0.4, 0.9) == random.Random(5).uniform(0.4, 0.9)

def test_size_floor_draws_from_the_upper_end(cell_kwargs):
    ctx = MotifContext(**cell_kwargs, size_floor=0.7)
    assert all(size_draw(ctx, random.Random(s), 0.0, 1.0) >= 0.7 for s in range(50))

def test_switch_to_both_refuses_forced_and_seam_rings():
    c = composer_for(seed=3, force_position_mode="centre")
    ring = next(r for r in c.plan().rings if r.ring_index > 0)
    assert not c.switch_to_both(ring, random.Random(1)) and ring.position_mode == "centre"

def test_old_recipe_json_loads_with_floor_zero():
    d = plan_for(seed=3).rings[1].sequence[0].centre.to_dict(); d.pop("size_floor")
    assert CellRecipe.from_dict(d).size_floor == 0.0

@pytest.mark.parametrize("case", [BACKGROUND_CENTRE_MODE_SEED, BACKGROUND_BOTH_SEED])
def test_background_step(case):
    g = gen(case); g.generate()
    assert g.last_validation_result.is_valid
    step2 = [r for r in g.plan.repairs if r["step"] == 2]
    assert step2 and step2[0]["change"] in ("position_mode:both", "size_floor")
    assert background_area(g, step2[0]["ring"]) < background_area(gen(case, max_region_cap=False), step2[0]["ring"])

def test_background_step_skips_layered_and_seam_rings():
    g = gen(BACKGROUND_CENTRE_MODE_SEED, force_position_mode="layered"); g.generate()
    for r in g.plan.repairs:
        ring = g.plan.rings[r["ring"]]
        assert r["step"] != 2 or (ring.position_mode != "layered" and not has_seam_base(ring))
```

- [ ] **Step 2: Run them and see them fail**

Run: `.venv/Scripts/python -m pytest tests/test_geometry.py tests/test_composer.py tests/test_region_repair.py -q`
Expected: FAIL

- [ ] **Step 3: Implement**

- [ ] **Step 4: Run the full suite and the motif gate**

Run: `.venv/Scripts/python -m pytest -q` then `.venv/Scripts/python qa_patterns.py --tier smoke > test_output/smoke.log 2>&1`
Expected: PASS; the smoke log ends with every motif passing (floor 0.0 changes no draw)

- [ ] **Step 5: Commit**

```bash
git add motifs/geometry.py motifs/botanical.py motifs/geometric.py composer.py assembler.py region_repair.py tests/test_geometry.py tests/test_composer.py tests/test_region_repair.py
git commit -m "feat(repair): fill oversized background with divider motifs or larger bases"
```

### Task 5: The rosette motif

**Files:**
- Modify: `motifs/geometric.py` (`generate_rosette`, registry entry)
- Test: `tests/test_motifs_geometric_new.py`

**Interfaces:**
- Consumes: `cubic_points`, `insert_vertex_on_outline`, `holds_pen` (`motifs/embellish.py`), `build_instance(..., seams=True)`.
- Produces: `generate_rosette(context: MotifContext) -> MotifInstance` and the entry `{"name": "rosette", "category": "geometric", "positions": ["centre"], "roles": ["centre"], "touch": True, "side_touch_heights": (), "seams": True, "embellishments": (), "spans_cell": True, "min_cell_width_px": 0.0, "min_ring_depth_px": 0.0, "max_overflow_inward": 0.0, "max_overflow_outward": 0.0, "slot_estimate": None}`. The `"centre"` role is new and no composer filter asks for it, so the rosette is never picked as a base, slot child, back or attachment. Constants: `ROSETTE_DOT_RANGE = (0.18, 0.28)`, `ROSETTE_LOBE_WIDTH_RANGE = (0.45, 0.75)`, `ROSETTE_BELLY_RANGE = (0.45, 0.7)`, `ROSETTE_MIN_FREE_CLEARANCES = 4.0`.

Drawing, in the cell of one lobe (Task 6 gives it `inner_radius = 0.0` and `outer_radius` = the free radius): every parameter is drawn from `context.ring_rng` before any limit applies, in the order dot radial `d`, lobe half-width `w`, belly radial share `b`. Vector 1 is the dot arc, an open detail-weight vector at constant radial `d` from `(d, -1.0)` to `(d, 1.0)`, a seam arc like the band's. Vector 2 is the lobe, an open detail-weight curve, mirror-symmetric about angular 0, from `(d, -w)` through its widest point at radial `d + b * (tip - d)` to the tip `(tip, 0.0)` and back to `(d, w)`, built from `cubic_points` halves and `mirror_points`, with `tip = min(1.0, radial_limits[1])`. The lobe ends are inserted as vertices of the dot arc. The generator raises `MotifError` when `radial_to_px(1.0) < ROSETTE_MIN_FREE_CLEARANCES * clearance_px("detail", "detail")`, when the gap between neighbouring lobes on the dot arc, `angular_to_px(2 * (1 - w), d)`, is under `clearance_px("detail", "detail")`, or when the lobe interior or the dot's cell piece fails `holds_pen`.

- [ ] **Step 1: Write the failing tests**

```python
def rosette_ctx(cell_kwargs, seed=7, **over):
    return make_ctx(cell_kwargs, seed, **{"inner_radius": 0.0, "outer_radius": 60.0, "ring_stream_seed": 31, **over})

def test_rosette_is_never_picked_by_the_composer():
    entry = find_motif("rosette")
    assert not {"base", "slot", "back", "attachment"} & set(entry["roles"])

def test_rosette_cells_draw_the_same_ink(cell_kwargs):
    a = find_motif("rosette")["generator"](rosette_ctx(cell_kwargs, 1))
    b = find_motif("rosette")["generator"](rosette_ctx(cell_kwargs, 2))
    assert [v.points for v in a.vectors] == [v.points for v in b.vectors]

def test_rosette_tip_reaches_the_outer_edge_and_lobe_rests_on_the_dot(cell_kwargs):
    dot, lobe = find_motif("rosette")["generator"](rosette_ctx(cell_kwargs)).vectors
    assert all(v.weight == "detail" for v in (dot, lobe))
    assert abs(dot.points[0].angular) == 1.0 and abs(dot.points[-1].angular) == 1.0
    assert CellPoint(1.0, 0.0) in lobe.points
    assert lobe.points[0] in dot.points and lobe.points[-1] in dot.points

def test_rosette_refuses_a_small_free_radius(cell_kwargs):
    with pytest.raises(MotifError):
        find_motif("rosette")["generator"](rosette_ctx(cell_kwargs, outer_radius=12.0))

def test_rosette_refuses_crowded_lobes(cell_kwargs):
    with pytest.raises(MotifError):
        find_motif("rosette")["generator"](rosette_ctx(cell_kwargs, wedge_angle=15.0, outer_radius=25.0))
```

- [ ] **Step 2: Run them and see them fail**

Run: `.venv/Scripts/python -m pytest tests/test_motifs_geometric_new.py -q`
Expected: FAIL (`find_motif("rosette")` is None)

- [ ] **Step 3: Implement `generate_rosette` and the entry**

- [ ] **Step 4: Run the tests, the registry tests and the motif's property checks**

Run: `.venv/Scripts/python -m pytest tests/test_motifs_geometric_new.py tests/test_motifs.py tests/test_contract.py -q` then `.venv/Scripts/python qa_patterns.py --motif rosette --tier smoke > test_output/rosette.log 2>&1`
Expected: PASS; the log shows rosette with every case SKIP (no base, slot or contact role), no FAIL, and `ok` in every property column; exit 0

- [ ] **Step 5: Commit**

```bash
git add motifs/geometric.py tests/test_motifs_geometric_new.py
git commit -m "feat(motifs): rosette, a repair-only centre motif"
```

### Task 6: Step 3, fill the centre

**Files:**
- Modify: `composer.py` (`RingPlan.rosette`)
- Modify: `assembler.py` (`ROSETTE_NODE`, `place_rosette`, `assemble`)
- Modify: `region_repair.py` (`step_centre`)
- Test: `tests/test_region_repair.py`, `tests/test_composer.py`

**Interfaces:**
- Consumes: Task 5 `generate_rosette`; `resolver.insert_vertex(path, point)`; `Assembler.snap_to_ink`.
- Produces: `RingPlan.rosette: Optional[CellRecipe] = None` (ring 0 only; `to_dict` key `"rosette"`, `from_dict` default None); `ROSETTE_NODE = -1` in `assembler.py`; `Assembler.place_rosette() -> bool` called at the end of `assemble`, after pass two, when the innermost ring's `rosette` is set (False and nothing placed when the generator raises `MotifError`); `AssembledDesign.rosette_dropped: bool = False`; `RegionRepair.step_centre(trial: Trial, face_set: FaceSet) -> Trial`.

`place_rosette`, for each cell `i` of the innermost ring (`N = ring.divisions`): cast a ray from `center` at `cell_rotation_deg(i, N, "centre")` and take its nearest hit on any placed path (through `self.index`); build `MotifContext(inner_radius=0.0, outer_radius=<hit distance>, wedge_angle=360/N, center, stroke_width, complexity, min_white_space, rng=random.Random(seed), position="centre", ring_stream_seed=seed, node_seed=seed)` with `seed = ring_stream_seed(ring.ring_seed, ring.ring_index, "repair:3")`; generate, trace with that cell's rotation into `PlacedPath(ring.ring_index, i, "centre", (ROSETTE_NODE,), "detail", ...)`; then `insert_vertex` the traced tip into the hit path, add every rosette path to `paths` and the index and `snap_to_ink` them. Any rosette path other than the tip's own segment ends lying closer than `clearance_px("detail", "outline")` to other ink, outside a disc of that radius about the tip, refuses the rosette like a `MotifError`. The lobe tips touching ring 0 split the open centre into one face per lobe gap, so no face encircles the centre.

`step_centre`: set `rings[0].rosette = CellRecipe("rosette", "geometric")` on a copy, record `"rosette"`, try it; a trial whose assembly reports `rosette_dropped` is not kept.

- [ ] **Step 1: Write the failing tests**

```python
def test_centre_step_adds_a_rosette():
    g = gen(CENTRE_SEED); g.generate()
    report = g.last_validation_result
    assert report.is_valid and not report.encircling_regions
    assert g.plan.rings[0].rosette is not None and any(r["change"] == "rosette" for r in g.plan.repairs)
    assert ("centre", 0) not in set_keys(g) or g.plan.repairs[-1]["step"] == 4
    rosette = [p for p in g.assembled.paths if p.node_path == (ROSETTE_NODE,)]
    assert rosette and all(p.role == "detail" and p.ring_index == 0 for p in rosette)
    assert g.last_validation_result.stats["num_floating_base"] == 0

def test_rosette_that_does_not_fit_is_dropped_and_the_design_stays_valid():
    g = gen(CENTRE_SEED, complexity=1.0, min_pattern_size=25, max_region_cap=False); g.generate()
    plan = copy.deepcopy(g.source_plan); plan.rings[0].rosette = CellRecipe("rosette", "geometric")
    h = gen(CENTRE_SEED, complexity=1.0, min_pattern_size=25, max_region_cap=False)
    h.generate_from_plan(plan)
    assert h.assembled.rosette_dropped and rosette_paths(h) == []
    assert h.last_validation_result.is_valid

def test_a_kept_design_never_has_a_dropped_rosette():
    g = gen(CENTRE_SEED, ring_divisions=[24, 24, 24, 24]); g.generate()
    assert g.last_validation_result.is_valid and not g.assembled.rosette_dropped

def test_rosette_round_trips():
    plan = plan_for(seed=3); plan.rings[0].rosette = CellRecipe("rosette", "geometric")
    assert DesignPlan.from_json(plan.to_json()) == plan
    d = plan.rings[0].to_dict(); d.pop("rosette")
    assert RingPlan.from_dict(d).rosette is None
```

- [ ] **Step 2: Run them and see them fail**

Run: `.venv/Scripts/python -m pytest tests/test_region_repair.py tests/test_composer.py -q`
Expected: FAIL

- [ ] **Step 3: Implement**

- [ ] **Step 4: Run the full suite**

Run: `.venv/Scripts/python -m pytest -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add composer.py assembler.py region_repair.py tests/test_region_repair.py tests/test_composer.py
git commit -m "feat(repair): fill an oversized open centre with a rosette"
```

### Task 7: Step 4 re-roll, step 5 give-up, determinism

**Files:**
- Modify: `composer.py` (`Composer.reroll_ring`)
- Modify: `region_repair.py` (`MAX_REROLLS`, `step_reroll`, `run`)
- Test: `tests/test_region_repair.py`

**Interfaces:**
- Consumes: Tasks 3, 4 and 6 (`step_host`, `step_background`, `step_centre`), `salted_seed`.
- Produces: `Composer.reroll_ring(plan: DesignPlan, ring_index: int, ring_seed: int) -> RingPlan` (plans the ring with `plan_ring(ring_index, ring_seed)`, puts it in `plan.rings` and the live rings; `self.rings` widths and `ring_seeds` are untouched, so ring geometry stays fixed); `MAX_REROLLS = 3`; `RegionRepair.step_reroll(trial: Trial, face_set: FaceSet) -> Trial`.

`step_reroll`, used for every kind once its own step leaves the set's key present: attempts `k = 1..3` each re-roll the owning ring of a copy of the current plan with `salted_seed(ring.ring_seed, f"repair:4:{k}")`, record `"ring_seed:<seed>"`, and are tried with `_trial`; the valid attempt with the smallest `oversized_area` is kept when it is strictly smaller than the current trial's. Step 5 is `run` itself: whatever trial it holds when the sets run out is the result, its remaining faces stay in `oversized_regions`, and the design is never rejected for them.

- [ ] **Step 1: Write the failing tests**

```python
def test_reroll_keeps_ring_geometry_and_forced_mode():
    c = composer_for(seed=3, force_position_mode="layered"); plan = c.plan()
    old = plan.rings[2]
    new = c.reroll_ring(plan, 2, salted_seed(old.ring_seed, "repair:4:1"))
    assert plan.rings[2] is new and new.ring_seed != old.ring_seed
    assert new.position_mode == old.position_mode == "layered"

def test_give_up_keeps_the_best_valid_design(monkeypatch):
    monkeypatch.setattr(RegionRepair, "step_host", lambda self, trial, face_set: trial)
    monkeypatch.setattr(RegionRepair, "step_reroll", lambda self, trial, face_set: trial)
    g = gen(HOST_SEED); g.generate()
    assert g.last_validation_result.is_valid and g.last_validation_result.oversized_regions

@pytest.mark.parametrize("case", [HOST_SEED, BACKGROUND_BOTH_SEED, CENTRE_SEED])
def test_repaired_design_is_deterministic(case):
    a, b = gen(case), gen(case)
    assert a.generate() == b.generate() and a.plan.to_json() == b.plan.to_json()
    assert gen(case).generate_from_plan(DesignPlan.from_json(a.source_plan.to_json())) == a.generate()

@pytest.mark.parametrize("case", [HOST_SEED, CENTRE_SEED])
def test_cap_off_repairs_nothing(case):
    off = gen(case, max_region_cap=False); off.generate()
    assert off.plan.repairs == [] and off.source_plan.rings[0].rosette is None

def test_regenerated_repaired_design_replays_from_ring_seeds():
    g = gen(CENTRE_SEED); g.generate()
    frag = g.generate_ring_fragment(1, 4242)
    replay = gen(CENTRE_SEED, ring_seeds=frag["ring_seeds"])
    assert replay.generate() == frag["svg"] and replay.plan.repairs == g.plan.repairs
```

Byte-identity with the cap off is pinned by Task 1's `test_cap_off_reproduces_the_pre_cap_engine`, which must still pass.

- [ ] **Step 2: Run them and see them fail**

Run: `.venv/Scripts/python -m pytest tests/test_region_repair.py -q`
Expected: FAIL

- [ ] **Step 3: Implement**

- [ ] **Step 4: Run the full suite and a corpus check**

Run: `.venv/Scripts/python -m pytest -q` then `.venv/Scripts/python qa_report.py --corpus > test_output/corpus.log 2>&1`
Expected: PASS; the log's tail shows 180/180 and no `QUOTA MISSED`

- [ ] **Step 5: Commit**

```bash
git add composer.py region_repair.py tests/test_region_repair.py
git commit -m "feat(repair): re-roll a ring and keep the best valid design"
```

### Task 8: Corpus line, ceiling, documentation and the visual gate

**Files:**
- Modify: `qa_report.py` (`run_one`, `main`, `corpus_quota_failures`, `OVERSIZED_DESIGN_CEILING`)
- Modify: `docs/motifs.md`, `docs/architecture.md`
- Test: `tests/test_qa_report.py`

**Interfaces:**
- Consumes: report stats `num_oversized_regions`, `largest_region_in2`.
- Produces: `run_one` rows gain `'oversized': int` (the stat) and `'largest_in2': float` (0 on errors); `OVERSIZED_DESIGN_CEILING: int`; `corpus_quota_failures` adds `f"oversized regions in {count} designs (> {OVERSIZED_DESIGN_CEILING})"` when more than the ceiling of rows have `row.get('oversized', 0) > 0`; `main` prints, in the corpus block, `f"oversized regions: {count} of {len(results)} designs; largest region {largest:.2f} in²"`.

- [ ] **Step 1: Write the failing tests**

```python
def test_run_one_reports_oversized_regions(tmp_path):
    row = run_one((42, 4, 12, 0.5, ["botanical"], False, str(tmp_path), "never"))
    assert row["oversized"] >= 0 and row["largest_in2"] > 0.0

def test_oversized_ceiling_is_a_quota():
    from qa_report import corpus_quota_failures, OVERSIZED_DESIGN_CEILING
    counts = {name: 10 for name in ("echo", "veins", "fan", "dot", "beads")}
    rows = [{"categories": ["celtic"], "layered_rings": 0, "rings": 4, "embellishments": counts, "oversized": 1}
            for _ in range(OVERSIZED_DESIGN_CEILING + 1)]
    assert corpus_quota_failures(rows) == [
        f"oversized regions in {OVERSIZED_DESIGN_CEILING + 1} designs (> {OVERSIZED_DESIGN_CEILING})"]
```

- [ ] **Step 2: Run them and see them fail**

Run: `.venv/Scripts/python -m pytest tests/test_qa_report.py -q`
Expected: FAIL

- [ ] **Step 3: Implement with a provisional ceiling of 180, then measure**

Run: `.venv/Scripts/python qa_report.py --corpus > test_output/corpus.log 2>&1`
Read the `oversized regions:` line and set `OVERSIZED_DESIGN_CEILING` to the measured count (the pinned guard against regression).

- [ ] **Step 4: Document**

`docs/motifs.md`: a section "Region size cap and repair" (the cap formula and values, the three face kinds, the ladder per kind, salts, what is recorded in the plan, `max_region_cap`, `size_floor` and which draws honour it), and "The rosette (repair only)" after "The twelve motifs" (role `centre`, never picked, drawn in a centre cell of inner radius 0 out to the free radius, lobe tips touching ring 0 so no face encircles the centre, every parameter from the ring stream, its refusals). `docs/architecture.md`: Runtime Flow gains the ladder after validation and `generate_from_plan`; Main Files gains `region_repair.py`; Validation gains the soft oversized report and its stats.

- [ ] **Step 5: Run the gates**

Run, each with output to a log and the tail read:
- `.venv/Scripts/python -m pytest -q`
- `.venv/Scripts/python qa_patterns.py --tier full > test_output/full.log 2>&1` (exit 0)
- `.venv/Scripts/python qa_report.py --corpus > test_output/corpus.log 2>&1` (180/180 PASS, no `QUOTA MISSED`)

- [ ] **Step 6: Commit**

```bash
git add qa_report.py docs/motifs.md docs/architecture.md tests/test_qa_report.py
git commit -m "feat(qa): report oversized regions over the corpus; document the region cap"
```

- [ ] **Step 7: Build the visual review set**

Write `review/max-region/<label>_before.svg` (`max_region_cap=False`) and `<label>_after.svg` for the eight corpus designs with the largest pre-cap `largest_region_in2`, at least one per face kind and one per complexity tier, plus `review/max-region/<label>_overlay.svg` from `debug_overlay_svg` for each "after". List them for the user with each design's repairs (`plan.repairs`) and its before/after `largest_region_in2`, and stop until the user's verdict. Nothing under `review/` is committed.
