# QA Remediation Plan — Topology Defects by Category

**Status: IMPLEMENTED 2026-08-01. Phases 0-4 complete; corpus is 90/90 green.**
See §6 for what shipped, including two root causes not visible at plan time.

Date: 2026-08-01
Source data: `qa_report.py` / topology sweeps — 5 categories × 6 seeds at complexity 0.5,
plus 2 seeds at complexity 0.15 and 0.85 (50 full-design validations total).

## 1. Category review

Active patterns all live in `smart_patterns/` (one wedge-cell per ring, rotated per
division). The legacy `patterns/` + `pattern_registry.py` libraries are **not used**
by the generator (`pattern_generator.py:48`) and are excluded from this review.

| Category  | Patterns | Structure | QA result (all complexities) |
|-----------|----------|-----------|------------------------------|
| geometric | smart_diamond, smart_prism_lattice | Closed polygons anchored to all four cell boundaries; interior struts end on the polygon | **PASS 10/10** |
| celtic    | smart_laced, smart_braid_knot | Side-to-side strands with exactly mirrored left/right ports; optional full-width rails | **PASS 10/10** |
| abstract  | smart_bridge_band, smart_resonance_ladder | Side-to-side waves/rails with matched ports; rungs terminate on rails | **PASS 10/10** |
| art_deco  | smart_fan, smart_stepped_band | Rays inner→outer boundary; stepped bands with matched side ports | **PASS 10/10** ¹ |
| botanical | smart_petal, smart_leaf, smart_vine_band | Petal/leaf shapes with **deliberate radial overruns** past ring boundaries | **FAIL 7/10** |

¹ art_deco initially reported 216 dangles across 6 seeds. All were validator false
positives (micro-gaps of 0.01–0.08px at boundary-arc T-junctions) fixed in
`topology_validator.py` during this review — see §3, Phase 0.

Defect attribution (complexity 0.5, 6 seeds):

| Pattern          | Runs | Dangles | Un-colorable regions | Floating shapes |
|------------------|------|---------|----------------------|-----------------|
| smart_leaf       | 4    | 72      | 12                   | 2 (whole-ring)² |
| smart_petal      | 2    | 24      | 0                    | 0               |
| smart_vine_band  | 6    | 0       | 36 ³                 | 0               |
| all others       | 6 ea | 0       | 0                    | 0               |

² Attributed "unattributed/center" in raw sweep output; confirmed to be the entire
ring-0/ring-1 leaf assemblies (see §2, cause C).
³ Misattributed by radius binning: the pockets sit at ring interfaces (e.g. radius
168.9 against a boundary at 169.6) and are **caused by the neighboring leaf/petal
ring's overrun corners**, not by vine_band. All-vine designs pass (seeds 42, 12345).

## 2. Root cause analysis

Every genuine defect traces to one mechanism with three symptom classes.

**The overrun mechanism.** `smart_petal` and `smart_leaf` intentionally push
endpoints past the cell in the radial direction for an organic look:

- petal: `base = CellPoint(-inner_overrun * …, 0)`, `peak = CellPoint(1.0 + outer_overrun * …, 0)`
  with overruns up to 0.22/0.24 of ring width (→ up to ~16px at typical ring widths)
  (`smart_patterns/botanical.py:67-80`)
- leaf: `lower_port = -inner_overrun * …`, `apex_radial` up to `1.0 + outer_overrun`
  (`smart_patterns/botanical.py:128-135`)

Three contract holes let these through:

**A. The cell analyzer blesses overruns as "boundary contacts."**
`SmartVectorAnalyzer._boundary_side` (`smart_patterns/core.py:160-169`) treats
`radial <= tolerance` as touching the inner boundary — including any *negative*
radial — and `radial >= 1 - tolerance` as touching outer, including radial > 1.
An endpoint 16px past the boundary is validated as "anchored."

**B. Boundary inference can't see overruns, so no ink is guaranteed.**
`_infer_boundary_requirements_from_elements` (`coloring_generator.py:654-663`)
uses `abs(point.radial) <= 0.025` — an endpoint at radial −0.08 matches *neither*
side, so `requires_inner_boundary` stays False and **no boundary circle is drawn**
at the radius the pattern relies on. The endpoint terminates in the neighboring
ring's territory where nothing is guaranteed to exist.

**C. Cross-ring connectivity is never verified at generation time.**
Candidate validation checks one ring in isolation and exempts dangles within 3px
of ring-boundary radii (`_validate_design` in `coloring_generator.py`). Small
random overruns slip under the exemption; the full-design check then finds the
real dangles — but by then the design is already assembled.

Symptom classes by overrun size (all observed in sweeps):

| Overrun size | Symptom |
|---|---|
| < ~2.5px | Endpoint bridged/pruned by validator tolerance, but crossing pockets remain → **un-colorable ~3×3px regions** at ring interfaces (complexity 0.15 runs: u=12–18) |
| ~2.5–5px | Mixed: pockets + occasional dangles |
| > 5px | **Dangling line ends** (seed 777: 44; seed 984322 @0.85: 36); when the pattern also has *no* boundary requirements at all, the entire ring's linework is a disconnected open component → **"floating shape"** (seed 984322: both leaf rings) |

## 3. Plan

### Phase 0 — Validator correctness (DONE during this review)
- Force-close near-closed rings (float noise made GEOS discard whole rings as dangles).
- Snap-round the post-bridge re-union and make gap-bridges overshoot their target
  line by 0.05px so T-junctions genuinely node (GEOS exact predicates refuse
  epsilon-off junctions; this was the art_deco false-positive source).
- Result: false-positive rate on the 30-run corpus dropped from 12 failing runs to 4,
  all 4 confirmed genuine.

### Phase 1 — Harden the smart-cell contract (`smart_patterns/core.py`)
1. `_boundary_side`: inner requires `-tol <= radial <= tol`, outer requires
   `1-tol <= radial <= 1+tol`. Endpoints outside `[-tol, 1+tol]` are **contract
   violations** — the analyzer rejects the vector ("endpoint overruns cell").
2. Add an explicit, capped overshoot channel instead of today's silent overruns:
   `SmartVector(overshoot_px=N)` with N ≤ 3px (under the 5px whisker tolerance),
   legal **only** when the pattern also declares `force_inner/outer_boundary`
   so ink is guaranteed at the crossing. Overshoot is applied in `to_cartesian`
   as an absolute px offset, not a fraction of ring width — this preserves the
   hand-drawn bleed look at every ring size.
3. Unify the two `_boundary_side` implementations (core.py analyzer vs
   coloring_generator inference) into one shared function so they can never
   disagree again (hole B was exactly such a disagreement).

### Phase 2 — Fix botanical patterns (`smart_patterns/botanical.py`)
1. **smart_petal**: clamp `base` to radial 0.0 and `peak` to 1.0; express the
   organic bleed via the new capped overshoot; set `force_inner_boundary` and
   `force_outer_boundary` in the pattern descriptor.
2. **smart_leaf**: same for `lower_port` (clamp to 0.0) and apex (cap at 1.0);
   force inner boundary; force outer boundary only when the apex actually
   reaches radial 1.0 (apex may legitimately stop inside the cell, where it is
   anchored by the leaf edges meeting it).
3. **smart_vine_band**: no geometry change expected (its failures were neighbor
   pockets); re-verify after 1–2 land.
4. Re-run the full corpus; expected: botanical 10/10.

### Phase 3 — Close the candidate-gate gap (`coloring_generator.py`)
1. With Phase 1/2 landed, every boundary an endpoint relies on is force-declared,
   so its arcs are already included in candidate validation. Shrink the dangle
   exemption from 3px to ~1px (float slack only), or remove it entirely.
2. Add the *previous* ring's accepted linework to each candidate validation
   (rings generate inner→outer), so ring-interface pockets are caught at
   candidate time instead of full-design time.
3. Keep the strict full-design validation as the final gate (no exemptions).

### Phase 4 — Regression harness
1. Pin a QA corpus: 5 categories × 6 seeds × complexity {0.15, 0.5, 0.85}
   (90 designs) run via `qa_report.py`; store pass/fail + defect counts;
   fail the run on any regression. Wire as a single command
   (`python qa_report.py --corpus`).
2. Per-pattern harness: validate each pattern in isolation across
   complexity × divisions {8, 12, 16, 24} × ring widths {16, 30, 60} — the sweep
   showed several code paths are complexity-gated (petal port-splitting ≥0.7,
   wavy modes ≥0.82, stepped second band ≥0.55) and `smart_resonance_ladder`
   was selected in only 3 of 30 runs (its `min_ring_width: 24` excludes most
   rings — worth revisiting, see Phase 5).
3. Emit the pastel overlay (`qa_overlay_<seed>.svg`) automatically for any
   failing corpus entry.

### Phase 5 — Cleanup and follow-ons (non-blocking)
1. Decide the fate of the unused `patterns/` + `pattern_registry.py` libraries:
   archive them, or port select designs through the hardened smart-cell contract.
   Also remove the now-unused `PatternValidator` class (keep `ShapeExtractor`).
2. Rebalance selection: resonance_ladder and braid_knot rarely appear;
   review `min_ring_width` values against actual ring-width distribution.
3. Optional safety net: an assembly-time repair pass that trims overshoot stubs
   at the boundary circle — only worth it if Phase 2 leaves residual cases.

## 4. Acceptance criteria
- 90/90 corpus designs pass full-design topology validation (0 dangles,
  0 floating open shapes, 0 un-colorable regions).
- No increase in safe-fallback usage (currently 0 across all sweeps — pattern
  rejection storms would show up here first).
- Spot-check overlays for each category at each complexity tier.

## 5. Risks
- Clamping overruns changes botanical aesthetics slightly; the capped-overshoot
  channel (Phase 1.2) is the mitigation — verify visually before/after.
- Validator tolerances (snap 2.5px, whisker 5px, pen 2px, min area 20px²) assume
  the 612px canvas; parametrize against canvas scale if larger exports are added.

## 6. Implementation record

Phases 0–4 landed. Final results: **corpus 90/90**, geometry sweep (divisions
{6,8,16,24} × rings {2,6} × 5 categories) **40/40**, unseen-seed sweep **24/24**,
validator unit cases **9/9**, safe-fallback cells used **0**.

### Shipped as planned
- `smart_patterns/core.py`: symmetric `boundary_side()` + `cell_overrun()` as
  shared module functions; contract pass in `SmartVectorAnalyzer.analyze` that
  rejects any geometry outside the cell before connectivity is considered;
  capped absolute-px overshoot channel on `SmartVector`.
- `smart_patterns/botanical.py`: petal base/peak and leaf corners/apex clamped
  into the cell; organic bleed re-expressed through the overshoot channel.
- `coloring_generator.py`: `_smart_boundary_side` now delegates to the shared
  function (the two implementations used to disagree — that was hole B); dangle
  exemption narrowed from "any validated ring boundary ±3px" to "the two unknown
  radial frontiers ±1px"; candidate validation now includes the previously
  accepted ring.
- `qa_report.py`: `--corpus` regression mode (5 categories × 6 seeds ×
  complexity {0.15, 0.5, 0.85}), parallel workers, overlays on failure,
  non-zero exit for CI.

### Two additional root causes found during implementation
Both were pre-existing, both invisible to the old QA, and both surfaced only
once the stricter gates were in place.

1. **Side ports drawn from per-variation RNG.** `smart_petal` picked its side
   port radius from the variation RNG, so variation A's right port and
   variation B's left port landed at different radii and adjacent cells could
   not meet (12 dangles per affected ring). Fixed by adding a ring-stable
   `port_rng` to the pattern call contract — anything positional on a side
   boundary must draw from it, never from the per-variation stream.

2. **Fallback was per-variation, breaking ring atomicity.** When one variation's
   pattern was rejected, only that variation fell back, producing rings whose
   cells came from different patterns (e.g. `smart_petal` + `smart_leaf`) with
   irreconcilable port radii. Fallback is now a ring-level decision:
   `PatternGenerator.generate_ring_variations` generates every variation from a
   single pattern and moves the whole ring to the next candidate on failure.
   Relatedly, candidate validation used to check one variation replicated to all
   divisions; it now validates all variations interleaved exactly as placed,
   which is what makes port mismatches visible at generation time.

### Refinement to the overshoot rule
The first cut let any boundary endpoint bleed, which fanned tiny triangles: when
several lines share an endpoint pushed outside the ring, the boundary arc slices
un-colorable slivers (~4–7px²) off the fan. The contract now permits bleed only
where a *lone* line crosses — the endpoint must sit on a radial boundary, must
not sit on a side boundary (the neighboring cell shares it), and must not
coincide with another vector in the cell. Petal bleeds only at its outer tip,
leaf only at its stem root.

### Not done (Phase 5, non-blocking)
Retiring the unused `patterns/` + `pattern_registry.py` libraries and the unused
`PatternValidator` class, and rebalancing `min_ring_width` so rarely-selected
patterns (`smart_resonance_ladder`, `smart_braid_knot`) appear more often.
