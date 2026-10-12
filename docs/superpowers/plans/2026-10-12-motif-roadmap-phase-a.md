# Motif Roadmap Phase A Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fill the empty V gaps and slots the engine leaves today with six new pieces: `crescent`, `kite`, `stamen`, `floret`, `star`, and the `drop` tip ornament.

**Architecture:** Every piece reuses a mechanism the engine already has, so the composer, assembler and resolver need no new code paths. V-gap fillers are divider bases that side-touch, exactly as `bead` does: in `both` mode the divider position *is* the V gap between two centre petals, and the shared side-touch vertices are the anchors the roadmap asked for. Slot fillers are slot children fitted with `slot_fit`. The drop is an embellishment that hangs from the host's declared `Anatomy.tip`, so a pull-back regenerates and refits it with its host. Section 6.1 of the roadmap ("anchors" as a new declaration plus assembler-placed attachments) is therefore realised through `Anatomy` and side-touch vertices instead; the deviation is recorded in `docs/motifs.md`.

**Tech Stack:** Python 3.10+, Shapely 2, pytest.

**Spec:** `docs/superpowers/specs/2026-10-11-motif-roadmap-design.md` (sections 3.1, 3.4, 6.1, 7 Phase A, 8).

## Global Constraints

- Rings and dividers are never ink; every open end lands on ink; every base joins one structure (motif engine spec).
- A side-touching base puts exact vertices at `CellPoint(side_touch_radial, ±angular_limits)` and no point wider than the budget; the outline runs along the radial through them (tangent within 10 degrees, `tangent_error_deg`).
- Draw every parameter from `context.rng` before applying any limit (determinism and monotone limits).
- Detail it cannot fit is dropped, not raised; `MotifError` only when nothing can be drawn.
- Every closed face a motif makes holds a pen (`holds_pen` / `_faces_hold_pen`).
- Do not edit `README.md`, `qa_report.py`, or the existing test files `tests/test_app.py`, `tests/test_composer.py`, `tests/test_design_generator.py`, `tests/test_layering.py`, `tests/test_motifs.py`, `tests/test_qa_patterns.py`, `tests/test_qa_report.py`: another thread has uncommitted work in them. New tests go in new files. `docs/motifs.md` gets one new section appended at the end only.

## Review Focus

1. **Narrow divider budgets.** In `both` mode the divider budget is `1 - centre_share`, as low as 0.25. A filler must draw or raise cleanly at 0.25 at the smallest cell its size gate admits. Test per filler.
2. **Base-height touch radial near 0.** `BASE_TOUCH_RANGE` starts at 0.08; a crescent or stamen cup must keep its lowest point at or above `radial_limits[0]` (0.0 in ring 0... and in all rings for these fillers, which declare no inward overflow). Test at radial 0.08.
3. **Drop with no room.** A host whose tip already sits at its outward limit must drop the drop and count it, never raise. Test.
4. **Odd floret petal counts and tiny slots.** A floret in a slot below its gate must raise `MotifError` (dropped as a slot child), and every face it makes, petal or centre, holds a pen. Test.
5. **Stamen stems crowding the cup.** Trident side stems must keep `clearance_px` from the centre stem and the cup except at their shared root vertex. Test.

---

### Task 1: crescent

**Files:**
- Create: `motifs/fillers.py` (all Phase A motifs live here, registered as `FILLER_MOTIFS` and appended to `MOTIFS` in `motifs/__init__.py`, so the other thread's edits to `botanical.py` and `geometric.py` are not touched)
- Test: `tests/test_motifs_fillers.py` (create)

**Interfaces:**
- Produces: `generate_crescent(context: MotifContext) -> MotifInstance`; registry entry `"crescent"`: category `botanical`, positions `["divider"]`, roles `["base", "slot"]`, `side_touch_heights ("base", "mid")`, embellishments `("echo",)`, `spans_cell False`, `min_cell_width_px 10.0`, `min_ring_depth_px 12.0`, overflow 0.0 / 0.0, `slot_estimate None`.
- Consumes: `page_arc_points`, `side_touch_radial_within` from `motifs/geometry.py`; `fit_slot_box`, `fit_inside_slot`; `holds_pen`, `apply_embellishments`.

As built: a cup of cubics. The widest vertices `(touch, ±half_width)` are on the outer side of the horns, where the outline runs along the radial, so they are the side-touch vertices; each horn rises above them to a sharp tip and turns down into the inner curve (see `motifs/fillers.py`). Original sketch: two circular arcs sharing the two horn vertices. Horns at `(h, ±w)`; the outer arc dips to `h - depth`, the inner arc to `h - depth * CRESCENT_INNER_SHARE`. With side touch: `h = side_touch_radial`, `w = angular_limits`, and the horns are the side-touch vertices. Without: `h` from `CRESCENT_HORN_RANGE = (0.45, 0.75)`, `w = angular_limits * CRESCENT_WIDTH_RANGE` drawn from `(0.7, 0.95)`. `depth` share from `CRESCENT_DEPTH_RANGE = (0.5, 0.9)` of the room down to `max(radial_limits[0], 0.0)`; `CRESCENT_INNER_SHARE` from `(0.35, 0.6)`. Horns end tangent to the radial (control the arcs so the outline runs along the divider at the horns). Slot child: fit the same shape into `fit_slot_box` with `fit_inside_slot`.

- [ ] **Step 1: Write failing tests** in `tests/test_motifs_fillers.py` (reuse the `make_ctx` helper pattern from `tests/test_motifs_geometric_new.py` and the `cell_kwargs` fixture):
  - `test_crescent_horns_are_the_side_touch_vertices`: for radial in (0.08, 0.35, 0.6) and limit in (1.0, 0.25): `CellPoint(radial, ±limit)` in `vectors[0].points`, and `max(abs(p.angular)) <= limit + 1e-9`.
  - `test_crescent_stays_above_the_ring_floor`: radial 0.08 → `min(p.radial) >= 0.0`.
  - `test_crescent_touch_is_smooth`: `tangent_error_deg` at each horn ≤ 10.
  - `test_crescent_face_holds_pen` over 40 seeds × limits (1.0, 0.5, 0.25) at a 10px-wide cell (scale `cell_kwargs` so the gate is met): every instance either raises `MotifError` or `holds_pen(ctx, points)`.
  - `test_crescent_slot_child_inside_slot`: generated with a petal's slot fits inside it (reuse the slot-containment pattern from `tests/test_motifs.py::test_slot_child_is_contained_in_the_slot_polygon`).
- [ ] **Step 2:** `pytest tests/test_motifs_fillers.py -k crescent -v` → FAIL (`find_motif("crescent")` is None).
- [ ] **Step 3:** Implement `generate_crescent` and add the registry entry after `heart`.
- [ ] **Step 4:** `pytest tests/test_motifs_fillers.py tests/test_motifs.py -q` → PASS (the generic determinism, monotone-limit and side-touch tests in `test_motifs.py` now include crescent).
- [ ] **Step 5:** Commit `feat(motifs): crescent`.

### Task 2: kite

**Files:**
- Modify: `motifs/fillers.py`
- Test: `tests/test_motifs_fillers.py`

**Interfaces:**
- Produces: `generate_kite(context) -> MotifInstance`; registry `"kite"`: geometric, positions `["centre", "divider"]`, roles `["base"]`, `side_touch_heights ("base", "mid")`, embellishments `("echo", "dot")`, `min_cell_width_px 12.0`, `min_ring_depth_px 16.0`, overflow inward 0.0, outward 0.2, `slot_estimate (0.35, 0.35)`.
- Consumes: `_diamond`-style construction from `geometric.py`; `Anatomy`.

Shape: four vertices, bottom tip `(b, 0)`, side vertices `(s, ±w)`, top tip `(t, 0)`; each edge a quadratic bowed slightly inward by `KITE_BOW_RANGE = (0.0, 0.2)` of the half-width, with the side vertices' neighbouring controls at the side vertex's angular so the outline runs radially there. With side touch `s = side_touch_radial`, `w = angular_limits`. `b` from `KITE_BASE_RANGE = (0.0, 0.05)` but never above `s - 0.05`; `t` from `KITE_LENGTH_RANGE = (0.9, 1.15)` clamped to `radial_limits[1]`. Without side touch `s` from `(0.3, 0.5)` and `w = 0.85 * angular_limits`. Anatomy: base = bottom tip, tip = top tip, outline 0.

- [ ] **Step 1: Write failing tests:** `test_kite_side_vertices_are_the_touch_vertices` (radials 0.08, 0.35, 0.6; limits 1.0, 0.5), `test_kite_top_is_within_limits` (narrow `radial_limits=(0.0, 1.0)` → `max radial <= 1.0`), `test_kite_tips_are_sharp` (turn at top tip ≥ 60 degrees with `turn_at`).
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3:** Implement and register after `bead`.
- [ ] **Step 4:** `pytest tests/test_motifs_fillers.py tests/test_motifs.py tests/test_motifs_geometric_new.py -q` → PASS.
- [ ] **Step 5:** Commit `feat(motifs): kite`.

### Task 3: stamen

**Files:**
- Modify: `motifs/fillers.py`
- Test: `tests/test_motifs_fillers.py`

**Interfaces:**
- Consumes: Task 1's crescent outline builder, refactored into `_crescent_outline(context, horn_radial, half_width, depth, inner_share) -> List[CellPoint]` so the stamen's cup is the same shape.
- Produces: `generate_stamen(context) -> MotifInstance`; registry `"stamen"`: botanical, positions `["divider"]`, roles `["base"]`, `side_touch_heights ("base",)` (as built: a cup at mid height leaves no room for the ball above it, so base only), embellishments `()`, `min_cell_width_px 12.0`, `min_ring_depth_px 36.0` (as built: below that the ball cannot keep a clearance from the cup), overflow 0.0 / 0.2, `slot_estimate None`.

Shape: a cup (a crescent at `STAMEN_CUP_DEPTH_RANGE = (0.25, 0.45)` of the room) whose horns are the side-touch vertices (or, without side touch, sit at `STAMEN_CUP_RANGE = (0.1, 0.3)`); a stem from the cup's inner-arc axis vertex up the axis, gently bowed by `STAMEN_BOW_RANGE = (0.0, 0.08)` of the half-width; a ball, a page-space circle of diameter `max(min_white_space * 1.5, ...)` up to `STAMEN_BALL_SHARE = 0.6` of the budget's width at its radial, whose bottom vertex is the stem's end. Stem top (ball centre) at `STAMEN_LENGTH_RANGE = (0.75, 1.1)` clamped so the ball stays within `radial_limits[1]`. At complexity ≥ 0.5, when they fit, two side stems from the same root vertex bow outward to balls at 0.7 of the centre ball's size, mirrored; each keeps `clearance_px()` from the centre stem, the cup and the other balls outside the touch disc of the root (else they are dropped, not raised). Raise `MotifError` only when the centre ball cannot hold a pen.

- [ ] **Step 1: Write failing tests:** `test_stamen_cup_horns_are_touch_vertices`, `test_stamen_stem_ends_on_cup_and_ball` (stem's first point is a vertex of the cup vector, last point a vertex of the ball vector), `test_stamen_ball_is_round_on_the_page` (ball samples within 2% of a circle in page space via `ctx.to_cartesian`), `test_stamen_trident_keeps_clearance` (complexity 0.9, 40 seeds: side stems either absent or every point outside the root disc ≥ `ctx.clearance_px()` from other ink), `test_stamen_draws_in_a_quarter_budget` (limit 0.25 at the gate size: draws or raises `MotifError`, never another exception).
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3:** Implement; register after `crescent`.
- [ ] **Step 4:** run Task 1–3 tests and `tests/test_motifs.py` → PASS.
- [ ] **Step 5:** Commit `feat(motifs): stamen`.

### Task 4: floret and star (slot sets)

**Files:**
- Modify: `motifs/fillers.py` (floret, star)
- Test: `tests/test_motifs_fillers.py`

**Interfaces:**
- Produces: `generate_floret`, `generate_star`; registry `"floret"`: botanical, positions `["centre"]`, roles `["slot"]`, `min_cell_width_px 16.0`, `min_ring_depth_px 16.0`, everything else as `diamond`. `"star"`: geometric, same gates as `diamond`.

Floret: a page-space flower outline around the slot box's centre, `r(θ) = R * (1 - a + a * |cos(kθ/2)|)` sampled with a vertex at every lobe tip and notch, `k` from `FLORET_PETALS = (5, 8)` inclusive, `a` from `(0.25, 0.4)`; a centre circle of radius `FLORET_CENTRE_SHARE (0.25, 0.35) * R`; `k` straight detail-weight dividers from the centre circle to each notch vertex, inserted as vertices on the circle. Fit with `fit_inside_slot` by scaling `R`. If the petals cannot hold a pen with dividers, drop the dividers; if the centre circle cannot, drop it; raise only when the outline itself cannot.
Star: `k` from `(5, 8)`, inner radius share `(0.4, 0.6)`, edges straight or concave (bow `(0.0, 0.2)`), page-space round, fitted the same way.

- [ ] **Step 1: Write failing tests:** `test_floret_every_face_holds_pen` (40 seeds in a petal's slot: `_faces_hold_pen(ctx, vectors)`), `test_floret_dividers_end_on_ink` (every divider endpoint is a vertex of the circle or of the outline), `test_floret_is_contained_in_slot`, `test_star_has_k_tips`, `test_star_is_contained_in_slot`, `test_slot_sets_raise_below_gate` (slot 4px wide → `MotifError`).
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3:** Implement and register (`floret` after `stamen`, `star` after `kite`).
- [ ] **Step 4:** run new tests and `tests/test_motifs.py` → PASS.
- [ ] **Step 5:** Commit `feat(motifs): floret and star slot sets`.

### Task 5: drop tip ornament

**Files:**
- Modify: `motifs/embellish.py`; registry `embellishments` tuples of `petal`, `teardrop`, `spike`, `kite`
- Test: `tests/test_embellish_drop.py` (create)

**Interfaces:**
- Consumes: `Anatomy.tip`, `embellishment_rng`, `page_circle_points`.
- Produces: embellishment name `"drop"`; `EMBELLISHMENT_ORDER = ("echo", "veins", "fan", "dot", "drop", "beads")`; `_drop(context, state, anatomy, rng) -> int`.

Shape: a closed teardrop at `outline` weight whose point is exactly the host tip vertex `anatomy.tip`, pointing back at the host along the axis, its bulb outward: point-to-bulb length from `DROP_LENGTH_RANGE = (2.0, 3.5)` × `min_white_space` px, bulb diameter `DROP_BULB_RANGE = (1.2, 2.0)` × `min_white_space`, shrunk (both by the same factor, floor 1.0 × `min_white_space` for the bulb) until the drop stays inside `radial_limits[1]` and `angular_limits`, else dropped (return 1). The point's two sides leave the tip at ±`DROP_POINT_ANGLE = 20` degrees from the axis. It is not an interior fill and does not touch the slot.

- [ ] **Step 1: Write failing tests:** `test_drop_point_is_the_host_tip` (petal with `embellishments=["drop"]`, `radial_limits=(-0.5, 1.6)`: the drop vector contains `anatomy.tip` as a vertex and every other drop point has radial > tip radial), `test_drop_is_outline_weight`, `test_drop_is_dropped_without_room` (host limits `(0.0, 1.0)` with the tip at the ceiling → no extra vector, `dropped_embellishments == 1`, no raise), `test_drop_is_deterministic_and_monotone` (same stream → same vectors; narrower high limit never reaches further).
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3:** Implement `_drop`, add it to the dispatch table and `EMBELLISHMENT_ORDER`, and add `"drop"` to the four hosts' tuples.
- [ ] **Step 4:** `pytest tests/test_embellish_drop.py tests/test_embellish.py tests/test_motifs.py -q` → PASS.
- [ ] **Step 5:** Commit `feat(embellish): drop tip ornament`.

### Task 6: integration, QA and docs

**Files:**
- Modify: `docs/motifs.md` (append one section), `qa_patterns.py` only if a new motif needs a harness hook
- Test: full suite

- [ ] **Step 1:** `pytest -q -n 4` → all pass.
- [ ] **Step 2:** `python qa_patterns.py --tier full` for each new motif (`--motif crescent` etc.) → exit 0. Fix generator issues it finds in the owning task's code.
- [ ] **Step 3:** `python qa_report.py --corpus` → 180/180 valid. Count placements of each new motif and of `drop` across the corpus from the plans; each must appear at least 10 times. If one falls short, raise its pick weight in the composer for `both`-mode divider positions (record the change in the docs section).
- [ ] **Step 4:** Append `## Fillers and tip ornaments (roadmap Phase A)` to `docs/motifs.md`: what each motif is, the V-gap mechanism (divider bases in `both` mode), and the deviation from roadmap 6.1 (anchors realised through side-touch vertices and `Anatomy.tip`, no new declaration field or assembler path).
- [ ] **Step 5:** Render a review set: 12 designs (botanical and botanical+geometric, complexity 0.3/0.6/0.9, both division modes) plus their QA overlays into `test_output/phase_a/`.
- [ ] **Step 6:** Commit `docs(motifs): roadmap Phase A fillers`.
