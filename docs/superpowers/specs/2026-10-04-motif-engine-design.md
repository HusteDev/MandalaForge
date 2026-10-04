# Motif Engine Design

**Status:** Approved in conversation, awaiting written review

**Date:** 2026-10-04

**Scope:** Replaces the pattern layer of MandalaForge (`pattern_generator.py`, `smart_patterns/`, and the generation core of `coloring_generator.py`) with a motif-based engine. The topology validator, SVG assembly, QA harnesses, Flask routes and UI survive with targeted changes.

## 1. Why

The current engine treats a cell as a tiling unit. One pattern per ring is generated for a single wedge and rotated into every division. Its linework must connect edge to edge: side ports must match across cells, every open end must land on a drawn ring boundary or on another vector inside the same cell, and the pattern must cross the ring's full radial depth. Colourability is proven by proving connection.

The target look, taken from the reference sketch that motivated this design, works differently. Rings and dividers are construction lines that are never drawn. A cell holds a small stack of motifs: a big petal with a smaller petal nested inside it, a diamond inside a petal, a stem that runs down into the ring below and ends on that ring's ink. Motifs overflow their ring slightly. Some are centred on a divider rather than on a cell. Rings have different division counts. Colourability comes from every motif being closed, where closed means every open end lands on ink somewhere in the design.

These are not tweaks to the existing contract. They are a different drawing model, so the pattern layer is rebuilt rather than migrated.

## 2. Decisions

These were settled in design conversation and are not open.

1. Ring boundaries and division lines are scaffolding. They are never emitted as ink, never inferred, and never count as something an endpoint can land on.
2. Each ring has its own division count, chosen freely. Overall symmetry is whatever falls out.
3. A cell has two positions, its centre and the divider on its clockwise side. Each position may hold a tree of motifs: one base motif, optional slot contents nested inside enclosing motifs, and optional attached open motifs (reachers) that extend toward a neighbouring ring. At least one position per cell is occupied. Motifs from neighbouring positions in the same ring may touch but never cross; the composer gives each position an angular budget so this holds by construction.
4. Closure rule: every open end of every motif must land on ink. The ink may be the motif itself, another motif in the same cell, or a motif in a neighbouring cell or ring. A motif that encloses its own area with no contacts is permitted when it is a slot child. Nothing dangles.
5. Overflow is declared per motif and is clipped to open space. An overflowing motif may touch the neighbouring ring's ink but may not cross it. If it would cross, it is shortened to touch; if no shortening above its own ring boundary avoids a crossing, it stays within its ring.
6. Reaches extend from a declared open end in a declared direction until they touch ink in the target ring, up to a maximum length. Reaches and overflows are resolved per cell instance in a second pass against the real assembled geometry.
7. Structural connectivity: every base motif in every cell of every ring belongs to one connected component of the ink graph. In practice each cell is held in place by its neighbour cell, by the ring inward of it, or by a reach. The innermost ring's cells touch each other so the centre becomes its own enclosed region. Slot children may be islands.
8. New motif vocabulary. The existing 21 patterns and `PatternGenerator` stay in the repo untouched until the new engine passes the acceptance gate in section 9, then are retired.
9. Motifs are parametric. Length, width, waviness, tip shape and similar properties are drawn per instance from seeded randomness within author-declared ranges. Nothing about a motif is a fixed design.
10. A ring's cells need not be identical. A ring uses a repeating sequence of cell recipes whose length divides the ring's division count, so a 9-cell ring may cycle through 3 different motif trees and a 6-cell ring may alternate between 2.

## 3. Motif contract

A motif is a Python function in a category module under a new package, plus a registry entry. It receives a `MotifContext` and returns a `MotifInstance`.

### 3.1 Input: `MotifContext`

Cell geometry in pixels and in normalised cell space. Cell space is unchanged from today: `CellPoint(radial, angular)` with radial 0.0 at the ring's inner boundary and 1.0 at its outer boundary, angular -1.0 at the left cell edge, 0.0 on the centreline and 1.0 at the right edge. The context carries:

- inner and outer radius, wedge angle, page centre, and the pixel helpers that exist on `SmartCellContext` today (`cell_width_px`, `radial_to_px`, `px_to_angular`, `radial_for_cell_width`);
- `complexity`, `stroke_width`, `min_white_space`;
- `rng`, a seeded stream unique to this motif node;
- `position`, either `centre` or `divider`. In divider mode the motif is still authored centred on angular 0; the composer shifts it by half a cell at placement. Authors never write two half-motifs;
- `angular_limits`, a half-width in cell units, 1.0 by default. The motif must produce no point with `abs(angular)` beyond it. When a ring occupies both positions, the composer splits the cell between them (section 4.2) so neighbouring motifs cannot cross;
- `radial_limits`, a `(low, high)` pair in cell units, defaulting to the motif's declared overflow range such as `(-0.25, 1.25)`. The motif must produce no point with radial outside it. The overflow resolver (section 5) narrows it toward `(0.0, 1.0)`;
- `slot`, optional. When the motif is being generated as a slot child, the slot polygon it must fit inside, in the parent's cell space, with the required margin already subtracted.

### 3.2 Output: `MotifInstance`

- `vectors`: the linework as a list of `SmartVector`, in cell space. Radial values may run below 0.0 or above 1.0 within `radial_limits`. Angular values stay within `angular_limits`. Paths are made from them exactly as `make_path` does today, including the arc subdivision that keeps a constant-radial segment a true arc.
- `declaration`, measured from the vectors after generation, not written as constants:
  - `footprint`: a polygon enclosing the motif's ink;
  - `slot`: optional polygon inside the footprint that is clear of the motif's own ink by at least `min_white_space`;
  - `reach_ends`: a list of `(point, direction, max_length_px, style)`. `direction` is `inward` or `outward`. `style` is `straight` or `wavy` and tells the engine how to draw the reach segment;
  - `overflow_inward_px` and `overflow_outward_px`: how far the generated ink extends beyond radial 0.0 and 1.0.
- `kind`: `enclosing` if the vectors form at least one closed loop, `open` otherwise. An open motif must declare at least one reach end.

### 3.3 Registry entry

```python
{
    "name": "petal",
    "category": "botanical",
    "generator": generate_petal,
    "positions": ("centre", "divider"),
    "roles": ("base", "slot"),
    "touch": True,                 # may be relied on for ring-to-ring contact
    "spans_cell": False,           # True when the ink reaches both angular limits by construction
    "min_cell_width_px": 14.0,
    "min_ring_depth_px": 18.0,
    "max_overflow_inward": 0.25,   # fraction of own ring depth
    "max_overflow_outward": 0.25,
}
```

Size gates work as today: they stop the composer choosing a motif that cannot fit, instead of generating it and rejecting it.

### 3.4 Three-layer parametric model

Every motif author works in three layers.

1. **Ranges the author declares.** Length as a fraction of ring depth, which may exceed 1.0 up to the overflow maximum. Width as a fraction of the cell. Tip sharpness, waist position, edge mode, wave amplitude, rib count. Each range may depend on `complexity`.
2. **A draw per instance.** The motif draws its parameters from `rng`, builds the outline, and clamps anything that would drop below `min_white_space` at this cell's pixel size. Drop a detail rather than raising; raising forces a node fallback.
3. **A declaration computed from the result.** Footprint, slot and reach ends are measured from the generated outline. A wavy petal yields a slot shaped by that petal, and a slot child is fitted to that slot.

Two properties follow and are asserted by QA (section 9): the same `rng` state and the same limits must produce identical vectors, and narrower `radial_limits` must never produce a point further out than wider ones.

### 3.5 Motif-level validation

A `MotifAnalyzer` replaces `SmartVectorAnalyzer`. It checks, in cell space:

- every open endpoint is either a declared reach end or touches the motif's own ink;
- the declared slot, if any, really is clear of the motif's ink by `min_white_space` (Shapely buffer test against the generated outline);
- intersections among the motif's own vectors do not create spaces smaller than `min_white_space`;
- radial extent stays within `radial_limits`;
- angular extent stays within `angular_limits`.

A motif that fails is rejected and the composer substitutes a node (section 4.4).

### 3.6 Removed from the old contract

Side-port matching, `port_rng`, the full-radial-span rule, the 3px overshoot cap, `overshoot_start_px` / `overshoot_end_px`, boundary inference, the `force_*_boundary` flags, and the rule that a vector must touch a cell boundary. Boundaries are not ink, so none of these mean anything.

### 3.7 Kept

`CellPoint`, `SmartVector`, `make_path`, `MAX_SEGMENT_ARC_DEGREES`, `quad_points`, `mirror_points`, the pixel-sizing helpers, and the authoring discipline of putting a vertex wherever two vectors cross.

## 4. Cell recipes and the composer

The composer replaces `PatternGenerator`. It decides what every ring contains, deterministically from the seed, before anything is drawn.

### 4.1 Data model

- `CellRecipe`: a tree node with `motif` (registry name), optional `slot_child` (another `CellRecipe`), and `attachments` (a list of `CellRecipe` for open motifs hung off this node's base point on the ring boundary). Nodes carry `is_fallback` and `provides_contact` flags once assembly has run.
- `CellEntry`: `centre` and `divider`, each a `CellRecipe` or `None`, at least one present. `divider` is the position on the cell's clockwise side.
- `RingPlan`: `ring_index`, `divisions`, `centre_share` (the angular half-width given to centre motifs when both positions are used, see 4.2), and `sequence`, a list of `CellEntry` whose length divides `divisions`. Cell `i` uses `sequence[i % len(sequence)]`.
- `DesignPlan`: ring radii, a `RingPlan` per ring, and the design-level style (4.3). Serialisable to JSON; this is what the API returns and what `/regenerate-ring` edits.

### 4.2 Building a plan

Rings are planned innermost to outermost. For each ring:

1. **Division count.** If the request supplies `ring_divisions`, use it. Else if `vary_divisions` is true, draw a count from the seeded stream within the UI range, centred on `num_divisions`, biased lower for rings with smaller circumference. Else use `num_divisions`.
2. **Sequence length.** Pick from the divisors of the count, weighted by `complexity`. Complexity 0.0 always gives length 1.
3. **Positions.** Decide, once per ring and weighted by the design style and complexity, whether the ring uses centre positions only, divider positions only, or both. When both, draw `centre_share` from 0.45 to 0.75. Centre motifs then receive `angular_limits = centre_share` and divider motifs receive `1.0 - centre_share`, so the two tile the cell edge to edge and can touch but never cross. When only one position is used its motifs receive the full 1.0.
4. **Each sequence entry.** For each occupied position, pick a base motif from the enabled categories that supports that position, supports the `base` role, and passes the size gates for the position's angular budget at this cell's pixel size. If the motif is enclosing and complexity allows, pick a slot filler that passes the gates for the slot's estimated size and recurse. Nesting depth is capped at 3.
5. **Contact, per base motif.** Every base motif in every entry needs a route to the structure: it declares inward overflow at or above a minimum useful amount, or it is `spans_cell` and so touches its neighbours in the ring, or it receives an inward reach attachment. The composer adds the reach when neither of the first two holds. For the innermost ring there is no inward neighbour, so the ring must be made of `spans_cell` motifs so its cells touch each other; the composer may also add a small centre motif that touches the ring.
6. **Variety.** Avoid repeating the inward ring's base motif unless nothing else fits, matching today's variety filter.

### 4.3 Seeding and coherence

Every choice uses a stream derived from `(seed, ring_index, sequence_position, tree_depth)`, so changing one ring's plan does not reshuffle another's. A design-level style is drawn once per seed: a weighting toward a subset of the enabled categories and a preferred position mode (centre, divider or both). It biases every later pick so a design reads as one language without making rings identical.

### 4.4 Node fallback

The composer never draws and never measures real geometry. When assembly rejects a node, it asks the composer for a replacement for that node only. The chain is: another eligible motif of the same role and category set, then an open reach attachment with a longer maximum when the failure was a missing contact, then the category's safe motif. The safe motif is a plain `spans_cell` closed band between radial 0.4 and 0.6, which touches its neighbour cells by construction and provides contact when given an inward reach.

## 5. Two-pass assembly

Replaces the generation core of `DesignGenerator` and the ring-level fallback in `PatternGenerator`. Input is a `DesignPlan`; output is page-space linework.

### 5.1 Pass one: draw and place

Rings innermost to outermost. For each cell and each occupied position: generate the base motif with the position's `MotifContext`, measure its slot, generate the slot child into that slot, and recurse. Attachments are not drawn; their reach ends are recorded with their page-space position and direction. Each instance is placed by rotating cell space to the cell's angle, plus half a cell for the divider position. Every placed vector enters a spatial index (Shapely `STRtree`) tagged with ring, cell, node and whether the segment is *home* (within radial 0.0 to 1.0 of its own ring) or *overflow*. At the end of pass one, home ink for every ring is final.

### 5.2 Pass two: resolve

Rings innermost to outermost. For each ring, in this order:

1. **Inward overflow.** For each instance whose overflow enters the inward ring, test the overflow segments against that ring's final ink. No crossing: keep. Crossing: find by binary search the lowest `radial_limits` floor at which the motif's innermost point touches the first ink it would have crossed, re-generate with that floor, and insert a vertex on the touched segment. If no floor below 0.0 avoids a crossing, set the floor to 0.0. The innermost ring has no inward neighbour, so its inward overflow is always kept.
2. **Outward overflow.** Same test against the outward ring's home ink, narrowing the `radial_limits` ceiling instead. The outward ring resolves its own inward overflow on its turn against this ring's now-final geometry, so overflows meeting in the gap always resolve in a fixed order. The outermost ring has no outward neighbour, so its outward overflow is always kept; this is how a petal passes the outer edge of the design.
3. **Reaches.** For each recorded reach end, cast from the endpoint in its direction through the index until it meets ink in the target ring or exhausts `max_length_px`. On a hit, snap the end onto the hit segment, insert a vertex there, and emit the reach path in the declared style at that length. On a miss the reach fails. The composer never creates an outward reach on the outermost ring or an inward reach on the innermost.
4. **Contact check, per cell.** Confirm each cell's base motif is connected to the structure: it touches a neighbour cell in its ring, or touches the inward ring, or has a successful reach. A floating cell triggers node fallback (4.4) for that cell's sequence entry, which by symmetry fixes every cell using that entry, and the ring is re-resolved.

### 5.3 Touching

A touch is an endpoint placed exactly on another vector's segment, with a vertex inserted into that segment. The topology validator then sees a node of degree three. No contact may rely on snap tolerance.

### 5.4 Symmetry and output

Nothing in pass two assumes repetition; each cell resolves on its own. Solving one wedge and copying it when all counts share a factor is a later optimisation, not a rule. SVG output emits every cell as explicit paths; `<use>` rotation is removed because cells in one ring are no longer guaranteed identical after resolution.

### 5.5 Determinism

A given seed and parameters produce the same plan, the same draws and the same pass-two decisions. Index queries run over deterministic geometry in a fixed order.

## 6. Validation

`topology_validator.py` remains the page-level authority.

**Unchanged:** dangling ends (any degree-1 endpoint fails; this is the closure rule proven on the assembled page) and tiny/thin regions with thresholds from `min_pattern_size`.

**Removed:** the dangle exemption at ring radii, boundary inference, and the boundary element builder in `coloring_generator.py`.

**New, structural connectivity:** every base motif, in both the centre and divider positions of every cell, belongs to the same connected component of the ink graph. Slot children may be islands. Any other island is a failure, reported as `floating_base_count`.

**New, overflow discipline:** no overflow segment intersects ink from another ring except at its own endpoint. Reported as `overflow_crossing_count`.

**Summary shape:** `is_valid`, `issue_count`, `tiny_region_count`, `issues`, plus `dangling_end_count`, `floating_base_count`, `overflow_crossing_count`.

## 7. API

`POST /generate` request: all existing keys keep their meaning. `num_divisions` becomes the default per-ring count. New optional keys: `vary_divisions` (boolean, default false) and `ring_divisions` (list of integers, one per ring, overrides both). A per-ring count may be any integer from 4 to 24 inclusive, odd counts included; the slider keeps its even steps. `ring_divisions` must have exactly `num_rings` entries or the request is rejected with 400.

`POST /generate` response: `svg`, `params_string`, `used_seed`, `validation` (section 6 shape), and `plan`, the serialised `DesignPlan`. `pattern_usage` and all `force_*_boundary` / `requires_*_boundary` fields are removed.

`POST /regenerate-ring`: same request keys plus an optional `ring_seeds` map of earlier per-ring overrides. Re-plans one ring with a new ring seed, keeps the other rings' plans, re-runs both assembly passes, and returns the full new `svg`, the full `plan`, and the merged `ring_seeds`. The whole document is returned because neighbouring rings' reaches and overflows land on the regenerated ring's new ink, so a single ring group can no longer be swapped in isolation.

## 8. UI

- A "Vary divisions per ring" checkbox under the Divisions slider, bound to `vary_divisions`. The randomise button may set it.
- Ring selector buttons show each ring's division count alongside its base motif name, read from `plan`.
- The debug bar prints per-ring counts and the base motif of each sequence entry.

## 9. QA

**`qa_patterns.py` becomes a per-motif harness.** It pins one motif, disables fallback, and drives the real pipeline over a matrix that adds position (centre, divider, and both with a fixed `centre_share`) and role (base of every cell; slot filler inside a known-good petal; sole contact provider over a known-good band). Division axes become per-ring lists and include the sketch's 8/8/8/12 fixture and a no-common-factor pair such as 7 over 12. The forced-motif switch still bypasses size gates.

Per-motif property checks: determinism (same stream and limits, identical vectors), monotone limits (narrower `radial_limits` never reach further), angular containment (ink stays inside `angular_limits` for every budget the composer can issue), slot honesty (declared slot verified clear with Shapely).

**`qa_report.py`** keeps the pinned corpus and adds `vary_divisions` as an axis so half the corpus runs uniform grids and half runs free counts. The overlay marks floating base motifs with dashed boxes and draws reaches as thin coloured traces.

**`qa_check.py`** is untouched.

**Acceptance gate** before retiring the old pattern layer: full per-motif tier passes for every registered motif; corpus passes at 100 percent; a visual review of corpus overlays confirms ring contacts look drawn rather than mechanical. The last item is a judgement call.

## 10. Initial motif vocabulary

Drawn from the reference sketch and `docs/motif-inventory.md`. Enough to reproduce the sketch and exercise every mechanism; the catalog grows afterwards.

| Motif | Kind | Roles | Positions | Mechanisms exercised |
|---|---|---|---|---|
| `petal` | enclosing | base, slot | centre, divider | slot, overflow both ways, both positions in one ring |
| `leaf` | enclosing | base, slot | centre | midrib as self-touch, no slot of its own |
| `diamond` | enclosing | slot | centre | pure island |
| `ring_band` | enclosing | base | centre, divider | `spans_cell`, cell-to-cell contact, innermost ring |
| `stem` | open | attachment | centre, divider | inward reach, wavy style |
| `scallop` | enclosing | base | divider | overflow inward, `spans_cell` |
| `safe_band` | enclosing | base (fallback) | centre, divider | fixed closed band at radial 0.4 to 0.6, `spans_cell`, contact by construction |

## 11. Documentation

`docs/smart-patterns.md` is replaced by a motif authoring guide: cell space, the three-layer model, the declaration, archetypes that satisfy closure, and traps as they are found. `README.md` and `docs/architecture.md` describe the two-pass assembly and the new API.

## 12. Out of scope

Migrating the existing 21 patterns. Non-circular ring edges. Line-weight hierarchy. Texture fills. The wedge-solve optimisation. Per-ring division controls in the main UI beyond the checkbox.
