# Motif Authoring Guide

A motif is a small drawing that the engine places in a cell of a ring: a petal, a leaf, a band, a stem. This guide covers what a motif receives, what it must return, what the engine measures and checks, and how to add one. Motifs live in the `motifs/` package. The composer (`composer.py`) decides where motifs go, the assembler (`assembler.py`) draws and places them, and the resolver (`resolver.py`) settles how neighbouring rings meet. The design spec is `docs/superpowers/specs/2026-10-04-motif-engine-design.md`.

## Cell space and limits

Motifs are authored in normalised cell space, never in pixels. A point is `CellPoint(radial, angular)` from `motifs/geometry.py`. `radial` runs from 0.0 at the ring's inner boundary to 1.0 at its outer boundary. `angular` runs from -1.0 at the left edge of the wedge through 0.0 on the centreline to 1.0 at the right edge. Linework is a list of `SmartVector(points, closed=False)`; a closed vector joins its last point back to its first.

Ring boundaries and division lines are scaffolding. They are never drawn, and an open end that lands on one has landed on nothing. The only thing a line can connect to is other ink.

The `MotifContext` a generator receives carries the cell's geometry (`inner_radius`, `outer_radius`, `wedge_angle`, `center`), the drawing settings (`stroke_width`, `complexity`, `min_white_space`), a seeded `rng` unique to this node, its `position`, the limits it must respect, and `side_touch_radial` (see [Side touch](#side-touch)). Its pixel helpers are `ring_depth`, `half_angle`, `radius_at`, `radial_to_px`, `px_to_radial`, `angular_to_px`, `px_to_angular`, `cell_width_px` and `radial_for_cell_width` (the lowest radial at which the wedge is at least a given number of pixels wide, for motifs that would turn into a needle at the inner edge). `min_white_space` is the request's `min_pattern_size`, and `stroke_width` is `1.0 + 1.5 * (1.0 - complexity * 0.5)`, from 2.5px at complexity 0 down to 1.75px at complexity 1.

A straight segment in cell space is a curve on the page. `MotifContext.polyline` subdivides any segment that sweeps more than `MAX_SEGMENT_ARC_DEGREES` (4 degrees), so a constant-radial edge renders as a true arc rather than a chord that sags inside the ring. Conversion never clamps: a point at radial -0.2 is drawn below the ring, which is how overflow works. `quad_points(start, control, end, steps)` samples a quadratic curve in cell space without clamping, and `mirror_points` reflects a run across the centreline.

Three limits bound every motif:

- `angular_limits` is a half-width in cell units, 1.0 by default. No point may have `abs(angular)` beyond it.
- `radial_limits` is a `(low, high)` pair. No point may have a radial below `low` or above `high`. A base motif starts with `(-max_overflow_inward, 1.0 + max_overflow_outward)` from its registry entry, except in the innermost ring, whose bases get a floor of 0.0. A slot child gets `(0.0, 1.0)`. The resolver narrows the limits toward `(0.0, 1.0)` when overflow has to be pulled back.
- `slot` is `None` for a base motif. For a slot child it is the polygon, in the parent's cell space, that the child must fit inside.

Limits restrict rather than rescale. The engine never moves a point to make it fit; the generator must choose its points so they fit, and `MotifAnalyzer` rejects a motif that does not. The analyzer allows a tolerance of 0.025 cell units on every limit.

## The three-layer parametric model

Nothing about a motif is a fixed drawing. Every author works in three layers.

1. **Ranges the author declares.** Length as a fraction of ring depth (which may exceed 1.0 up to the overflow maximum), width as a fraction of the angular limit, waist position, tip roundness, wave amplitude, and so on. A range may depend on `complexity`: the petal's wave amplitude is drawn from 0.0 to `complexity * 0.06`, and `band` (formerly `ring_band`, which remains as an alias) adds a centre spoke only at complexity 0.5 and above.

   Base lengths are centred on filling the ring, not stopping short of it, so rings read as nested bands: tips sit on or past the outer boundary and the resolver decides how far they nestle into the next ring, and bases sit at radial 0.0 or dip below it. The petal draws its length from 0.95 to 1.3 of ring depth and a dip from 0.0 to 0.5; the leaf draws its length from 1.0 to 1.2 with its base at 0.0. The overflow maxima that let those tips and dips through are petal 0.5 inward and 0.3 outward, and leaf 0.2 outward.

2. **A draw per instance.** The generator draws its parameters from `context.rng` and builds the outline. Draw every parameter before applying any limit. The resolver regenerates a node from the same seed with narrower limits, and the result must be the same motif cut back, not a different motif: if a limit decided whether a parameter is drawn, every later draw would shift. This is what makes the two generator properties hold, and both are asserted by the test suite and by `qa_patterns.py`: the same stream and limits give identical vectors, and narrower `radial_limits` never give a point further out than wider ones.

3. **A declaration computed from the result.** The footprint, slot, overflow and base point are measured by `build_instance` from the vectors actually generated. A wavy petal yields a slot shaped by that wave, and the child placed in it is fitted to that slot.

When a detail would fall below `min_white_space` at this cell's pixel size, drop the detail rather than raising. Embellishments work this way: `veins` draws no midrib at all when the faces it would make are too narrow to colour, and every embellishment that does not fit is dropped and counted (see [Embellishments](#embellishments)). Raising `MotifError` is for a motif that cannot be drawn at all: a failing base is replaced through the composer's fallback chain (at most three times per sequence entry and position), a failing slot child is dropped from that cell, and a failing attachment is dropped and counted.

## The declaration and what is measured

A generator ends by calling `build_instance(context, vectors, reach_ends=(), slot_outline=None, base_point=None)` from `motifs/contract.py`. It measures a `Declaration`, assembles a `MotifInstance(vectors, declaration, kind)`, runs `MotifAnalyzer`, and raises `MotifError` listing every issue when the motif breaks the contract.

The declaration holds:

- `footprint`: the convex hull of every point, in cell space.
- `slot`: the interior a slot child may occupy, or `None`. Pass the closed outline as `slot_outline` to get one. `measure_slot` traces the outline in page space (arc-subdivided, unrotated), insets it with a mitred buffer of `min_white_space + stroke_width`, keeps the largest piece, discards it when under `MIN_SLOT_AREA_PX` (1 square pixel), and maps it back to cell space. Measuring in page space is what lets the analyzer's pixel clearance check hold exactly.
- `reach_ends`: a list of `ReachEnd(point, direction, max_length_px, style)`, where `direction` is `inward` or `outward` and `style` is `straight` or `wavy`.
- `base_point`: where attachments hang from. By default the point with the lowest radial, ties broken by the smallest `abs(angular)`.
- `overflow_inward` and `overflow_outward`: how far, in cell units, the ink runs past radial 0.0 and 1.0.

`kind` is `enclosing` when any vector is closed and `open` otherwise. An open motif must declare at least one reach end. A motif with no vectors and only reach ends (a stem) is allowed; its footprint and base point come from the reach ends.

The analyzer checks, in cell space with its 0.025 tolerance:

- an open motif declares reach ends;
- every open end of every vector is a declared reach end, touches another vector, or touches a non-adjacent segment of its own vector;
- every vector stays inside `radial_limits` and `angular_limits`;
- where two different vectors cross, the crossing does not leave a space narrower than `min_white_space` (a crossing within `max(2 * stroke_width, 3px)` of a segment end is a touch and is allowed);
- the declared slot is at least `min_white_space` from every segment, measured as page polylines.

Slot children use the helpers in `motifs/slot_fit.py`. `fit_slot_box(context, name)` returns the slot's bounding box inset by one stroke width (the slot already carries the white-space and stroke margin from its parent), and raises when less than `MIN_FIT_PX` (4px) is left across either half-extent. `fit_inside_slot(context, name, builder)` calls `builder(scale)` with scale 1.0 and shrinks it by `SHRINK_FACTOR` (0.92) until the outline is contained in the slot polygon, raising once the scale would drop below `MIN_FIT_SCALE` (0.4). The bounding box alone is not enough: a curved slot edge cuts its corners.

## Positions and angular budget

A cell has two positions. `centre` sits on the cell's centreline. `divider` sits on the cell's clockwise edge: `cell_rotation_deg` turns it half a wedge further. A motif is always authored centred on angular 0; `context.position` says where it will be placed, but authors never draw half-motifs.

The composer picks a position mode per ring: `centre`, `divider` or `both`. The design's style prefers one mode, which is weighted 0.6 against 0.2 for each of the others. `both` needs a cell at least `BOTH_MIN_CELL_WIDTH_PX` (28px) wide at mid-ring; narrower rings fall back to `centre`. In `both` mode the ring draws a `centre_share` from 0.45 to 0.75: centre motifs get `angular_limits = centre_share` and divider motifs get `1.0 - centre_share`, so the two budgets tile the cell edge to edge. Motifs in neighbouring positions may touch where the budgets meet but cannot cross, by construction. When one position is used its motifs get the full 1.0.

A registry entry's `positions` lists where a motif may go, and its size gates are checked against the position's budget: `min_cell_width_px` against the mid-ring cell width times the angular budget, and `min_ring_depth_px` against the ring depth. A motif that fails its gates is never chosen, rather than generated and rejected. The innermost ring is planned from `spans_cell` bases only, so its cells touch each other and close off the centre; it uses `centre` or `divider`, never `both`, and only a position that some enabled `spans_cell` base supports.

## Side touch

Every ring has a `contact_mode`, chosen by the composer and stored in its `RingPlan`: `side`, `overflow` or `stem`, in that order of preference. A ring is `side` when its bases share a touch height (`common_touch_heights`), and the innermost ring always is. Each registry entry lists the heights it supports in `side_touch_heights`, drawn from `base` and `mid`; a seam motif (see [Seams and the ring stream](#seams-and-the-ring-stream)) connects through its seams and counts at every height. The composer draws one height per ring into `RingPlan.touch_height` and one `side_touch_radial` from that height's range, `base` from `BASE_TOUCH_RANGE` (0.08 to 0.2) and `mid` from `MID_TOUCH_RANGE` (0.35 to 0.6), from the ring-level stream. A base-height touch sits low on the cell edge, which reads as petals rising from a shared root; a mid-height touch reads as petals meeting at the belly. The assembler passes the radial in `MotifContext.side_touch_radial` to every base motif of a `side` ring; slot children and attachments always get `None`, as does every base of an `overflow` or `stem` ring.

What it means for an author: when `context.side_touch_radial` is set and `context.slot` is `None`, the motif must draw to its full angular budget and put a vertex exactly at `CellPoint(side_touch_radial, angular_limits)` and exactly at `CellPoint(side_touch_radial, -angular_limits)`, with no point wider than the budget. Every base in the ring places the same two vertices: neighbours from different sequence entries, and a centre motif and the divider motif that shares its edge in `both` mode (the centre budget ends at `centre_share`, where the divider's begins), land on the same page point, so they meet at a shared vertex. The ring becomes one connected band, which needs only a few inward contacts: one per wedge, and at least `MIN_RING_CONTACTS` (3) in the ring.

The exact-vertex rule: the shared point must be a vertex of the outline itself, not a point the outline passes through between two samples, and it must be the radial and angular given, not an approximation (the tests check both coordinates to 1e-9). A curve that merely bulges out to the budget near that radial meets its neighbour tangentially, which float arithmetic turns into a near miss or a crossing; two outlines that carry the same vertex meet at one point by construction. Two helpers in `motifs/geometry.py` do the bookkeeping:

**Smooth touch.** The shared vertex is also where two neighbouring outlines meet, so the outline must run along the divider there rather than arrive at a corner. `petal` and `leaf` leave the touch vertex with a tangent within 10 degrees of the radial direction, and apart from their tip and base they have no corner (a turn of at most 35 degrees between traced segments). `qa_patterns.py` measures this with `tangent_error_deg`, the angle between the radial direction and the chord between the touch vertex's two neighbours; the chord only approximates the drawn tangent, so read the 10 degree limit as a bound on that approximation. `max_turn_deg` is the matching corner measure.

- `side_touch_radial_within(context, low, high)` returns the side-touch radial when it applies (a base motif, a radial is set) and lies strictly inside `(low, high)`, otherwise `None`. Use it to decide whether to draw the side-touch shape.
- `side_edge_containing_touch(context, low, high)` widens a band's side edge so the side-touch radial lies strictly inside it, at least `SIDE_EDGE_MARGIN` (0.05) from each end, clamped to the radial limits; it returns the edge unchanged when side touch does not apply. Bands drawn from different sequence entries then all carry the shared vertex.

How the registered motifs do it:

- `petal` has a lotus profile: two cubic runs per side, with the belly drawn from 0.3 to 0.6 of its length, so the outline swells to the full budget at the belly and closes to the tip. It pins a vertex at `(side_touch_radial, ±angular_limits)` and approaches it tangent to the radial direction. No sample is wider than the vertex.
- `leaf` puts its base corners at `(0.0, ±LEAF_SIDE_TOUCH_BASE * angular_limits)` (0.6 of the budget), and each edge runs corner, side vertex `(side_touch_radial, ±angular_limits)`, apex, as two curves whose controls are no wider than the budget. The apex is curved to one side. The leaf draws no midrib of its own: its midrib is the `veins` embellishment (see [Embellishments](#embellishments)), so a leaf without `veins` has none.
- `band`, `scallop` and the safe band span the budget along their side edges. The safe band widens its side edge with `side_edge_containing_touch` and inserts the vertex `(side_touch_radial, ±angular_limits)` on both side edges; `band` and `scallop` are seam motifs and need no touch vertex.

When the radial falls outside the motif's own radial run (only possible when the radial limits are much narrower than 0.35 to 0.6), `petal` and `leaf` draw their plain shapes and a band edge's nearest end serves as the vertex. List a height in `side_touch_heights` only when the generator honours the rule at that height; `stem` and `diamond` list none. A motif that supports no common height puts any ring it is a base of into `overflow` mode (when every base there has at least `CONTACT_OVERFLOW` of inward overflow) or `stem` mode.

## Seams and the ring stream

A seam motif draws the edge it shares with the cell beside it, so the ring needs no side-touch vertex. Its registry entry sets `seams: True` and its declaration carries `seams=True`, which tells the analyzer to accept open ends at angular exactly ±1.0 (and only at the full budget of 1.0). A seam motif is never placed in `both` mode, where the budget is below 1.0, and it fills its position in every entry of the ring's sequence; forcing one into `both` raises `ValueError`. A seam ring also gets a stem in every cell, so that a ring of scallops meets the faces-per-cell floor.

Neighbouring cells must draw the same seam, so its parameters come from `MotifContext.ring_rng`, a stream seeded with `ring_stream_seed` that is identical in every cell of a ring using the same motif and position. The assembler seeds it as `ring_stream_seed(ring_seed, ring_index, f"ring:{motif}:{position}")`. A generator's own `rng` stays the per-node, unsalted stream and is the place for variation between cells; use `ring_rng` only for what must agree across the ring. `dataclasses.replace` rebuilds `ring_rng`, so a copy of a context yields a fresh, identical stream.

- `band` draws two seam arcs at radials `r1` in [0.25, 0.45] and `r2` in [0.55, 0.75] from `ring_rng`; a band whose recipe carries `beads` draws the same values from the wider ranges `r1` in [0.12, 0.25] and `r2` in [0.75, 0.88], so the bead row has room. Arcs alone would leave the band's base floating and form an annulus round the centre that validation rejects, so each cell also draws one mirror-symmetric curved lens at angular 0 whose tips meet both arcs. `ring_band` is kept as an alias for the name.
- `scallop` draws one page-space circular lobe per cell through the seam ends `(rb, ±1.0)` and an apex. The apex shrinks toward `rb` in steps of 0.9 until the lobe stays within ±1.

Three choices made during implementation depart from the aesthetics spec. The band's lens tie: the spec drew two arcs only, but untied arcs leave a floating base and an annulus round the centre that validation rejects, so each cell adds a lens that meets both arcs. The stem in every cell of a seam ring: the spec left seam rings to connect through their seams, but a ring of scallops then fell below the faces-per-cell floor, so every cell carries a stem. The scallop apex shrink: the lobe's apex is pulled toward the seam radial in 0.9 steps because a fixed apex could cross the ±1 edge and break the shared seam.

`MotifContext.to_cell` is the inverse of `to_cartesian`, for generators that build a shape in page space (a circle, an arc) and map it back into cell space. `motifs/geometry.py` also offers `cubic_points`, `page_arc_points`, `page_circle_points` and `insert_vertex_on_outline`.

## Line weights

Each `SmartVector` has a `weight`, `outline` or `detail`, and a `layer`. An `outline` vector strokes at the full `stroke_width`; a `detail` vector strokes at `DETAIL_WEIGHT_SHARE` (0.6) of it. `MotifContext.stroke_for(weight)` returns the width in pixels and `clearance_px(weight_a, weight_b)` returns the centreline gap that leaves `min_white_space` between the edges of two lines, so a generator can space a detail line against an outline without assuming one pen width. `inset_outline(context, outline, inset_px)` (in `motifs/contract.py`) insets a closed outline in true page space for nested detail.

Every vector at `detail` weight is placed with path role `"detail"`, whichever node drew it, a back layer's included: detail ink floats inside its host the way a slot child may, so it is never counted as base structure. The `veins` midrib is the one embellishment line that is not always `detail`: it takes the weight of the ring of ink it crosses, so it strokes at `outline` weight on a host with no echo and at `detail` weight inside an echo (see [Phase 2 deviations](#phase-2-deviations-from-the-aesthetics-spec)).

## Anatomy

A host that accepts embellishments names its parts with `Anatomy(base, tip, outline)` from `motifs/contract.py`: `base` and `tip` are cell points of the host (for a pointed host, its base vertex and its tip vertex on the axis), and `outline` is the index of its closed outline vector in the list it passes on. The generator builds it from the outline it actually drew and passes it both to `apply_embellishments` and to `build_instance(..., anatomy=anatomy)`, which stores it in `Declaration.anatomy`. `petal` and `leaf` use `_pointed_anatomy(points)`: base `points[0]`, tip `points[2 * CURVE_STEPS]`, outline 0. `band` names its lens: base `(r1, 0)` on the inner arc, tip `(r2, 0)` on the outer arc, outline 2 (after its two arcs). A motif that accepts `veins`, `fan` or `dot` must supply an anatomy; without one, every embellishment it is asked for is dropped and counted.

## Embellishments

Embellishments are detail ink a host adds inside itself, from `motifs/embellish.py`. A registry entry's `embellishments` tuple lists the names it accepts: `petal` takes `echo`, `veins`, `fan` and `dot`, `leaf` takes `echo` and `veins`, `band` takes `beads`, and the rest take none.

**Selection.** The composer picks a base node's embellishments per sequence entry, so every cell that repeats the entry draws the same ones, and stores them in `CellRecipe.embellishments`. `pick_embellishments(entry, complexity, rng)` draws `u` uniform in [0, 1) and takes `n = clamp(floor(3 * (complexity - 0.2) / 0.8 + u), 0, 3)` names without replacement from the accepted list, keeping at most one interior fill (`INTERIOR_FILLS`, `veins` and `fan`), and returns them in `EMBELLISHMENT_ORDER`. Its stream is the node's pick stream salted `"pick:emb"`, so adding a pick never shifts the motif choice. A node with an interior fill gets no slot child, and only a node without one is offered a slot chain. A seam motif's copies in later sequence entries carry entry 0's embellishments, so every cell draws the same seam ink. A layered ring's back picks its own from the divider's `"pick:emb"` stream. For QA, `ComposerSettings.force_embellishments` (and `DesignGenerator(force_embellishments=...)`) adds the named embellishments to the picks of every base and back that accepts them (`force_embellishment_picks`): a forced interior fill displaces a picked one, so a node still has at most one, and a node with an interior fill still gets no slot child. It draws nothing, so every unforced pick is unchanged. The composer raises `ValueError` for an unknown name, a repeated name, or more than one forced interior fill.

**Application.** A generator draws its outline and then calls `apply_embellishments(context, vectors, anatomy, slot_outline)` before `build_instance`. It runs the names in `context.embellishments` in `EMBELLISHMENT_ORDER` (`echo`, `veins`, `fan`, `dot`, `beads`), each from its own stream: `embellishment_rng(context, name)`, the node seed salted `"emb:" + name`, except `beads`, which continues `context.ring_rng` so every cell of the band draws it alike. Adding or dropping one never shifts another's draws. It returns an `EmbellishResult`: the vectors, the slot outline the host should declare (with its weight), and the number dropped. An embellishment that does not fit at this cell's pixel size is dropped and counted, and the pipeline never raises; the host passes the count as `build_instance(..., dropped_embellishments=...)`, and the assembler sums it into `AssembledDesign.dropped_embellishments`. Drops count per embellishment: an echo that drew one of its two lines counts no drop. Embellishments are recomputed from the host on every regeneration, so a pull-back shrinks the host and everything inside it, and determinism and monotone limits hold for embellished output. Every end that lands on the host outline or an echo is inserted there as a vertex.

- **echo**: one inner outline, or two at complexity `ECHO_TWO_AT` (0.6) and above. Each is the innermost ink inset in page space by `clearance_px(its weight, "detail")`, drawn closed at `detail` weight, and kept only when its face holds a pen and has `min_white_space` of white across it somewhere. The second is skipped when the first does not fit. The host's slot moves inside the innermost echo and is measured at `detail` weight, and interior fills nest inside it too.
- **veins**: a midrib along the axis across the innermost ring of ink, from its base crossing to its tip crossing, plus mirrored pairs of side veins at `detail` weight from the midrib toward the tip, at one drawn angle of 35 to 50 degrees from it (`VEIN_ANGLE_RANGE`), each ending on that ring. The lowest start sits at a drawn share of 0.15 to 0.3 of the midrib's length (`VEIN_FIRST_RANGE`), the highest at 0.7 (`VEIN_LAST_SHARE`), the rest evenly between. It draws the most pairs that fit, up to `MAX_VEIN_PAIRS` (4): consecutive starts at least `clearance_px("detail", "detail")` apart, and every face the veins make holding a pen with `min_white_space` across it. When not even one pair fits, the whole embellishment, midrib included, is dropped.
- **fan**: a half-disc hub of radius `clearance_px("detail", "detail")`, centred on the axis where the innermost ring is exactly that far from it, so the hub arc's ends land on the ring, and rays from the hub arc straight out from its centre to the ring. The ray count is the most for which every wedge between rays is at least that clearance wide along the hub arc. Because the hub radius equals the required wedge width, that is always exactly `MIN_FAN_RAYS` (3) rays; fewer drop the fan.
- **dot**: a closed `detail` circle, round on the page, of drawn diameter between `min_white_space` and twice that, centred on the axis at the lowest point of the lower half of the innermost ring (searched in `DOT_SEARCH_STEP_PX`, 0.5px, steps) where it keeps `clearance_px("outline", "detail")` from all ink. It floats. When the host still offers a slot, the slot outline is cut along the radial at the dot's top, so a slot child keeps clear of it.
- **beads**: on a `band` only. `k` beads in each half of the cell, `k` drawn from `BEADS_PER_HALF_RANGE` (1 to 3) on the ring stream, mirrored about the axis (the lens tie sits there), centred halfway between the two arcs and evenly spaced from the lens to the seam with a full pitch between beads and half a pitch at either end, so the row runs on evenly through the neighbouring cell's beads. The diameter is drawn between 1 and 2 times `min_white_space` (`BEAD_DIAMETER_RANGE`) and capped so each bead keeps an outline-to-detail clearance from the arcs and the lens and a detail clearance from every other bead, the neighbouring cell's included. Fewer beads are tried when the drawn number does not fit, and a row whose diameter would fall below `min_white_space` is dropped.

## Layered rings and the back role

A layered ring draws a second ring of motifs behind its front ones and removes the hidden lines (`motifs/layering.py`). `POSITION_MODES` gains `"layered"`. A ring past the innermost is eligible when a motif with role `"back"` in the enabled categories passes its size gates at the whole cell and some non-seam base can touch at `base` height. The style never prefers it, so an eligible ring takes it with weight 0.2 against the preferred mode's 0.6. `ComposerSettings.force_position_mode` (and `DesignGenerator(force_position_mode=...)`, and `qa_report.py --force-mode`) forces a mode on every ring past the innermost where it is eligible; it cannot be combined with `force_motif` (`ValueError`).

**Plan.** The fronts fill the centre position with the whole angular budget and vary by sequence entry as usual; they are non-seam bases that touch at `base` height, and a layered ring always touches at `base` height, with its radial from `BASE_TOUCH_RANGE`. `RingPlan.back` is one `CellRecipe` for the whole ring, picked from the `"pick:back"` stream among the back candidates, with its own embellishments. `RingPlan.back_dropped` records a dropped back, and `RingPlan.position_mode` the ring's mode (plans saved before it existed derive it from their entries).

**Role.** A registry entry lists `"back"` in `roles` when it may be drawn behind a front: `petal` and `leaf` today. A back motif must be mirror-symmetric about its axis, so that its trim on the dividers falls on its centreline vertices (its tip and base), which become seam ends that the neighbouring cell's half meets exactly.

**The composite.** The assembler draws each centre base of a layered ring with `compose_layered(front_context, front_entry, back_context, back_entry)` instead of the front generator alone. The back context is the front's with the whole cell on a divider: position `divider`, angular limits 1.0, radial limits (0.0, 1.0), no slot and no side touch, and its `rng`, node seed and ring stream all seeded with `ring_stream_seed(ring_seed, ring_index, "back")`, so every cell draws the same back. The steps:

1. Draw the front, embellishments included; a front failure raises the front's own `MotifError`. Draw the back; a back failure raises `LayeringError`.
2. Shift the back's vectors by +1.0 and -1.0 angular units onto the cell's two dividers and keep the parts with `abs(angular) <= 1.0`; ends trimmed on a divider sit at angular exactly ±1.0 and become seam ends. A segment that runs along a divider is dropped, so a back midrib there is never drawn twice.
3. Cut away every part inside the front's fill (the union of its closed outlines), by exact segment intersection in cell space, which is exact because tracing maps straight cell-space segments to the drawn curves.
4. Drop a visible piece shorter than `2 * min_white_space` pixels that has no seam end, and every piece with a seam end in the notch at or below the side-touch vertex (up to one touch disc above it); a piece joining a notch seam to a seam above it raises `LayeringError`.
5. Raise `LayeringError` for an outline piece with no cut end: nothing ties it to the structure.
6. Insert every cut point into the front outline it lies on as a vertex, and end the piece exactly there.
7. Check in page space that every piece keeps `clearance_px(piece weight, front weight)` from the front outline, except inside the touch disc of its own cut ends, of radius `touch_disc_px` = `clearance_px() + max(min_white_space, 8)`; each seam end is checked on its own. A piece too close raises `LayeringError`.
8. Return front and back as one `MotifInstance` with `seams=True` (the back's seam ends are accounted for), the front's slot, anatomy, base point and reach ends, and the drops of both.

Back outline vectors carry `layer="back"` and are placed with path role `"back"`; back detail ink is `"detail"`. `resolver.STRUCTURAL_ROLES` is `("base", "back")`, so `AssembledDesign.base_mask` counts back outlines as base ink for connectivity. A pull-back regenerates the whole composite with narrower front limits; the back depends only on the ring stream and fixed limits, so it is drawn identically and cut again.

**Failure.** When a composite raises `LayeringError` in pass one, the composer's `drop_back(ring)` sets `back = None`, `back_dropped = True` and the mode to `centre`, keeping the centre entries, and the ring is placed again without counting a replacement. In pass two only some cells are redrawn, and the others would keep the back, so a composite failure there (or a replacement that falls back to a safe band, which also drops the back) raises `LayeredRingFailed`; `DesignGenerator` then drops that ring's back and assembles the whole design again, at most once per ring. The back is dropped for the whole ring, never in one cell, because a neighbouring half's seam would dangle.

## Phase 2 deviations from the aesthetics spec

These choices made while building layering and embellishments depart from the letter of the aesthetics spec (`docs/superpowers/specs/2026-10-09-motif-aesthetics-design.md`) or settle what it leaves open. Each was ruled on during the work.

- **The veins midrib takes the weight of the ring it crosses.** The spec says embellishments draw `detail`; the midrib strokes at `outline` weight on a host with no echo and at `detail` inside an echo. Reason: without an echo it replaces the leaf's old outline-weight midrib and ends on outline ink at the host's tip; inside an echo it is interior detail ending on a detail line.
- **The dot cuts the slot's top.** The spec only says the dot floats. Reason: a slot child measured in the full slot could sit on the dot; cutting the slot along the dot's top radial keeps the child clear of it.
- **Slot-fitted petals and leaves must hold a pen.** The spec gives a slot child no such rule. Reason: the dot's slot cut left slots so shallow that a fitted leaf could not be coloured (a full-tier design failed validation); a child that fails is dropped, as an unfitting child already is.
- **The fan always has exactly 3 rays.** Not a change to the rule but a consequence of it, kept on purpose: the spec's hub radius equals the required wedge width, so the count is floor(pi), 3. Reason: the spec is binding and the hub size is an aesthetic decision for the user.
- **Beads come in mirrored rows on either side of the lens.** The spec draws one evenly spaced row across the band. Reason: the band's lens tie (a Phase 1 deviation) occupies the axis, so `k` beads per half-cell, mirrored, keep the band mirror-symmetric.
- **A beaded band draws its arcs from wider ranges.** `r1` in [0.12, 0.25] and `r2` in [0.75, 0.88] instead of [0.25, 0.45] and [0.55, 0.75], with the same draws from the ring stream and unchanged clearances. Reason: between the plain ranges a bead row with full clearances almost never fitted, so beads never drew.
- **Seam copies carry entry 0's embellishments.** The spec picks embellishments per sequence entry. Reason: a seam motif's ink must be identical in every cell, and beads change a band's arcs.
- **The resolver moves a node's own lines with a shared tip.** The spec names curved stems as the resolver's only change. When only a node's own lines share its tip vertex, a touch moves the tip and those lines together. Reason: a veined petal's guarded base was left 0.004px from the ring inside, leaving a region round the centre (seed 955789).
- **The layering touch disc is `clearance + max(min_white_space, 8)` px.** Reason: a disc of `max(min_white_space, 8)` px is smaller than the clearance itself, so a piece leaving its cut was always too close at the disc's edge and every back was dropped.
- **Back pieces with a seam end in the notch below the side touch are dropped.** Spec 5.2 step 5 never drops a piece with a seam end. Reason: back ink in the notch between two fronts always closed a face no pen fits (41 of 72 forced-layered designs were invalid). Both cells of a divider decide alike, from the back and the ring's touch radial only.
- **Seam ends get their own clearance check, and a cut-free back outline piece raises.** Reason: a short seamed piece inside a cut's touch disc made slivers against the front, and an outline piece with no cut would float.
- **Back detail ink has role `"detail"`, not `"back"`.** Reason: a back's echo or dot floats like front detail; as `"back"` it would count as floating base ink.
- **A pass-two layering failure reassembles the design.** Spec 5.4 has the assembler place the ring again. Reason: pass two redraws only some cells, and the rest would keep the back, so the generator drops the back and assembles again (`LayeredRingFailed`).

## Changes from user feedback on band rings

The user found rings of `band` joined to their neighbours by long straight radial spokes extremely mechanical. These changes came from that feedback (the investigation and the controller's ruling are in the motif-aesthetics ledger).

- **Resolver fix: a curved reach is exempt from the clearance check near every path at its junction.** A correctness fix, not a design change. `_curve_clear_of_ink` exempted only the anchor and target paths inside the touch disc at the reach's ends, so a stem starting or ending on a vertex that another path also passes through (a band's inner arc through its lens tip, a petal's tip, a leaf's midrib end) found that path at distance 0 from every curve and fell back to straight: every band stem, and most leaf and petal stems, were drawn straight whatever style they picked. Every indexed path within `ON_INK_PX` of the start or end is now exempted within the touch disc around that point only, so a curve that comes too close to such a path away from the junction still falls down the ladder.

## Closure, overflow and reaches

The closure rule: every open end of every motif lands on ink. The ink may be the motif itself, another motif in the cell, or a motif in a neighbouring cell or ring. On the assembled page the topology validator proves it: after noding, any endpoint of degree 1 is a dangling end. Every base motif must also belong to one connected structure, the component holding most of the innermost ring's bases. Slot children may be islands.

The composer gives each base a route to that structure before anything is drawn, according to the ring's contact mode:

- **`side`**: the ring is one band through its side vertices, so a few inward contacts are enough. When some base declares `max_overflow_inward` of at least `CONTACT_OVERFLOW` (0.1), overflow provides it and no stem is added. Otherwise the first node gets a single stem with `once_per_wedge=True`. The assembler draws it in the first cell of each wedge of `360 / B` degrees that holds the stem's sequence entry, but never fewer than `MIN_RING_CONTACTS` (3) times in the ring: when the base symmetry is 1 or 2, one per wedge would join the ring to the one inside it at one or two points and leave the band between as one face running round the centre, so each wedge draws at least `ceil(3 / B)`, spaced among the wedge's cells that hold the entry (`Assembler._draws_once_per_wedge`). The rule depends only on a cell's place in its wedge, so symmetry groups stay whole. A wedge with fewer such cells draws the stem in each of them and can still fall short of three; that limitation is accepted.
- **`overflow`**: every base has inward overflow and nestles into the ring below; no stems are added.
- **`stem`**: the last resort, as in revision 1. A base has contact when it has inward overflow, or is `spans_cell` in a ring that has contact elsewhere, or carries an attachment; the composer attaches a stem to every base where none holds.

When an assembled base still floats, `Composer.replace_node` repairs its sequence entry. In a `side` ring it first substitutes another side-touching base, then adds a stem; in other rings the stem comes first (this repair stays available under `force_motif`, since it changes no motif). After that it substitutes any other eligible motif, then falls back to the category's safe band. A substitution that puts a base without side touch into a `side` ring downgrades the ring's mode and turns its once-per-wedge stem back into a per-cell one.

**Overflow** is ink past radial 0.0 or 1.0, declared by `max_overflow_inward` and `max_overflow_outward` as fractions of the ring's depth. Bases in the innermost ring never overflow inward. In pass two the resolver tests each node's overflow against the neighbouring ring's ink. An overflow that crosses neighbour ink, or that comes within `CLEARANCE_PX` (4px, twice the pen radius) of it, is pulled back: a binary search of `SEARCH_STEPS` (10) halvings finds the widest limit that keeps clear, the node and its slot children are regenerated from their stored seeds with that limit, and if the result still conflicts the side's overflow is removed entirely. A side is pulled back at most `MAX_PULL_BACKS` (4) times. Overflow may touch neighbour ink at a shared vertex but never cross it. The clearance applies to overflow geometry only, the runs `placement.path_overflow` finds past radial 0.0 or 1.0: a motif's ink inside its own ring may come as close as it likes to a neighbour's overflow, which is that neighbour's to keep clear. A run that goes less than `OVERFLOW_EPSILON` (1e-9) past the boundary is float noise on a vertex that lies on it, and is not overflow. The clearance applies outside a touch disc of radius `max(min_white_space, 8px)` around the run's extreme vertex (where a touch may be made) and around every vertex of the path shared with other ink (a touch already made, or a reach that landed there). Inside those discs the gap may narrow to a touch.

After every ring is resolved, a final touch pass runs over each base's extreme vertex on every side that has a neighbour ring, whether or not it overflows, so a tip that stops on the ring boundary still meets the next ring: an extreme vertex within `TOUCH_GAP_PX` (4px) of neighbour ink is moved onto it, with a vertex inserted into the ink it lands on. The move is undone when it would make the two rings cross or crowd each other, judged from both rings, or close off a face too thin or too small to colour. A vertex shared with any other ink is never moved: the neighbour's ink comes to it instead (see the traps).

**Reaches** are drawn for attachments. A reach end records a page point and a direction. In pass two the reach starts on the node's own ink, at the point of that ink furthest along the reach's line (a stem whose base point lies inside its petal starts where it leaves the petal), and casts along the line until it meets ink. It lands at the first point along the ray within `TOUCH_GAP_PX` of other ink, on that ink's nearest point, so a reach passing within 4px of ink lands on it rather than running beside it. An inward reach (a stem) casts exactly to the inward neighbour ring's inner boundary, whatever its declared `max_length_px`, so it reaches all of that ring and never past it; an outward reach casts its declared length. A reach that finds no ink draws nothing and leaves the cell to the contact check and the fallback chain; no longer stem is ever cast. A reach shorter than `CLEARANCE_PX` collapses to a touch: the anchor vertex is moved onto the hit and no path is drawn, unless the move would cross or crowd ink or close off a face too thin or too small to colour. A reach is drawn in one of three curved styles chosen per stem, `bow` (a single arc), `s` (an S-curve) or `wavy` (a sine wave), with weights 2, 2 and 1 (`REACH_SHAPES` in `resolver.py`). The amplitude is at most `min(8px, 0.12 x length)`. Every style goes through the same fallback ladder, `_curve_clear_of_ink`: the amplitude is reduced through scales 1.0, 0.5, 0.25 and 0.0 until the curve keeps `CLEARANCE_PX` from all other ink, and scale 0.0 is a straight line. Ink that meets the reach's start or end point (the anchor and target, and any other path through that point: a band's arc through its lens tip, a midrib ending on a tip) is held clear only outside the touch disc around that point, so a curve may leave a junction but may not sweep back onto the junction's ink further along. An inward stem also never lands on ink of a ring further out than its neighbour. No reach is drawn when it would close off a face too thin or too small to colour. Both ends of a drawn reach are vertices of the ink they touch.

A touch is always exact: the touching end is a vertex of its own path, and the point it lands on is inserted as a vertex into the path it touches. Nothing relies on a snap tolerance to read as connected.

## Archetypes that satisfy closure

Every motif in the registry is one of four shapes. A new motif should be one of them too, or a combination.

### Enclosing outline

One closed vector. It has no open ends, so it satisfies closure on its own, and its interior can declare a slot. `petal` is the model: a mirror-symmetric outline built from two cubic runs per side in a lotus profile, passing `slot_outline=outline` so a child can nest inside. Every slot-fitted outline must be a face the validator accepts: `petal` and `leaf` raise `MotifError` (so the child is dropped) when the outline fitted into a slot fails `holds_pen` (area of at least `MIN_REGION_AREA_PX2`, non-empty when eroded by `PEN_RADIUS_PX`), as the diamond does. A slot cut shallow, by a dot for one, could otherwise fit a child too thin to colour. In a `side` ring its widest vertex is the side-touch vertex. `diamond` is the slot-only version, a pure island inside its parent. Half the time (`DIAMOND_CONCAVE_CHANCE`) its four edges bow inward by 0.15 to 0.35 of the half-width, which keeps the tip a point; a bowed diamond in a small slot can be too thin to colour, so `_holds_pen` applies the validator's own rule (area of at least `MIN_REGION_AREA_PX2` and non-empty when eroded by `PEN_RADIUS_PX`), falls back to the straight diamond in the same slot when the bowed one fails it, and raises `MotifError` (the child is dropped) when neither passes. An enclosing base still needs contact with the structure, which comes from inward overflow, from `spans_cell`, or from a stem.

### Outline with midrib

A closed outline plus open vectors whose two ends are vertices of the outline. Since Phase 2 the midrib is not part of any motif's own drawing: it is the `veins` embellishment, which a `leaf` or `petal` gets when the composer picks it. The midrib runs along the axis from the outline's base crossing to its tip crossing (on a host outline these are the anatomy's base and tip vertices), and the side veins run from the midrib to the outline; every end is inserted into the line it lands on as a vertex. Each is a self-touch, so it needs no reach end. Veins split the host, so a host with veins (or a fan) declares no slot, and veins are drawn only when every face they make holds a pen with `min_white_space` across it somewhere.

### Spans-cell band

A closed shape that reaches both angular limits by construction (`spans_cell: True`), so it meets the same motif in the neighbouring cells along a shared radial edge. The safe bands (`<category>_safe_band`, from `motifs/fallback.py`) are the plainest case: a band from radial 0.4 to 0.6 across the full angular limit, valid in any cell. In a `side` ring the safe band widens its side edges to contain the side-touch radial and carries its vertex. `band` and `scallop` are the seam motifs, described in [Seams and the ring stream](#seams-and-the-ring-stream). Spans-cell bases are the only bases the innermost ring uses.

### Pure reach

No vectors at all, only a reach end. `stem` declares one inward `ReachEnd` at `CellPoint(0.0, 0.0)` with a declared maximum of 0.9 ring depths (the resolver casts inward reaches to the neighbour ring's inner boundary instead). Its line is drawn in one of three curved styles chosen by the resolver (`bow`, `s` or `wavy`, weights 2, 2 and 1; see Closure, overflow and reaches). It has the `attachment` role: it is never a base, and the composer hangs it off a base that needs contact. The assembler generates attachments only to record their reach ends; the resolver draws the line.

## Traps

These were found the hard way while building the engine. Each now has a test or a guard; the lesson is what to look for in a new motif or engine change.

- **A slack constant hiding a metric mismatch.** The slot was first measured one way and checked another, and a slack constant in the check made the two agree. The fix was to measure the slot in page space with the same polylines the analyzer checks, and make the check strict. A slack constant in a geometric check usually means two measurements disagree.
- **Bounding-box slot fit.** A child fitted to the slot's bounding box poked through the curved slot edge and breached the parent's white-space clearance. Children are now contained in the slot polygon itself (`fit_inside_slot`), inset a stroke width from its edge.
- **Midribs splitting narrow leaves.** A slot-fitted leaf at a small size kept its midrib and produced halves too thin to colour. A detail that divides a shape must check the parts it creates, not just the whole.
- **Overflow run ends off the drawn chord.** Overflow runs were first ended where the cell-space segment crosses the boundary circle, which is not on the page segment actually drawn between two traced coordinates, so crossing tests against those runs could miss ink. `boundary_crossing` now puts the end on the drawn segment and on the circle.
- **The validator's precision grid collapsing thin faces.** Faces are noded on a 0.001px grid, and GEOS could collapse a negative buffer of gridded input to empty where a pen fits easily, so legitimate faces were reported too thin. The pen test now erodes each face in floating precision.
- **A reach bridging a sub-pen slit.** A short reach drawn across a narrow slit between two lines that meet behind it closed the slit off as an uncolourable face. Reaches are now judged by the faces they would close, with the validator's own thresholds, and a reach shorter than a pen width becomes a touch instead.
- **One-sided touch judgement.** The final touch pass judged a moved tip only from the touching node's side. The moved tip is also the neighbour ring's neighbour ink, and it could come within clearance of the neighbour's own overflow. Touches are now judged from both rings, with the same rule as the final check.
- **Shared vertices moved by a touch.** Moving a vertex that other ink also ends on (a midrib's end, a reach's start, an earlier touch) detached that ink. No touch moves a shared vertex, and the clearance rule exempts a disc around every shared vertex rather than only around the run's tip.
- **Guarded tips that never touch.** With ring-filling lengths a leaf's apex sits on the ring boundary, within a pen's width of the next ring's ink, but the apex is guarded because the midrib ends on it. The touch pass could not move it, and the design failed the final check that no two rings crowd each other. A guarded tip is now touched from the other side: the tip's projection onto the neighbour's ink is inserted as a vertex and moved onto the tip, bending that ink by at most `TOUCH_GAP_PX`; when that vertex is guarded too, the near miss is accepted. Treat any vertex your motif shares between two vectors as one the engine will not move.
- **Float noise on exact geometry.** Three failures came from points that are equal on paper and differ by about 1e-14 in floats. A turned copy of a representative's ink differs from ink traced in its own cell, and the validator only reads a touch when the shared vertex is the same point in both lines, so mirrored ink is snapped onto the vertex it meets (`Assembler.snap_to_ink`, within `SAME_VERTEX_PX`; see the next trap for why every placed path now is). A touch restored after a redraw reused a vertex 5e-14 away, which left a float-noise overflow run (radial about -1e-17) lying along the other ink, and the validator read it as a crossing; the other ink's vertex is now moved onto the reused one. Mirrored members failed pass two's final crowding check on their own noise, so that check judges only the representatives' ink, and `path_overflow` ignores runs that go less than `OVERFLOW_EPSILON` past the boundary. When two motifs must meet, compute the shared point from the same cell-space values in both, and never test page coordinates for equality with a tolerance of your own.
- **Side vertices apart by rotation noise.** Neighbouring cells compute their shared side vertex from the same cell point, but each is rotated to its own cell, and a rotation by an inexact angle (360 / 7 degrees) leaves the two vertices about 1e-14 apart. A third line touching one of them then overlapped the other along a sub-micron segment, which the validator read as an overflow crossing. Every path the assembler places, commits or mirrors is now snapped with `snap_to_ink`, so each vertex within `SAME_VERTEX_PX` (1e-6) of another ink's vertex becomes exactly that vertex, and neighbouring cells share their side vertices bitwise.
- **Self-intersecting faces.** Snap-rounded linework can still polygonize into a face that is not a valid polygon, and the validator's face measurement raised a GEOS "side location conflict" on it instead of measuring it. `TopologyValidator` now repairs an invalid face with `make_valid` before measuring it, keeping every polygon part, largest first, so no face is lost; valid faces pass through unchanged. A validator exception on a design is a validator bug to fix, not a design to reject.

## Adding a motif

1. Write a generator `generate_<name>(context: MotifContext) -> MotifInstance` in the category module (`motifs/botanical.py`, `motifs/geometric.py`, or a new module whose list is added to `MOTIFS` in `motifs/__init__.py`). Draw every parameter first, respect the three limits, and end with `build_instance`.
2. Add a registry entry to the module's list.
3. Run the three commands below until all of them pass, and run the test suite.

A worked example, a teardrop-shaped `drop` that can be a base or a slot child (it uses the imports `botanical.py` already has):

```python
def _drop_outline(base: float, tip: float, half_width: float, belly: float) -> List[CellPoint]:
    """A closed, mirror-symmetric drop: right side base to tip, then the left side back."""
    control = CellPoint(base + (tip - base) * belly, 2.0 * half_width)
    right = quad_points(CellPoint(base, 0.0), control, CellPoint(tip, 0.0), 8)
    return right + mirror_points(right)[1:-1][::-1]


def generate_drop(context: MotifContext) -> MotifInstance:
    rng = context.rng
    # Layer 2: draw every parameter before any limit is applied.
    length = rng.uniform(0.7, 1.1)
    half_width = context.angular_limits * rng.uniform(0.5, 0.8)
    belly = rng.uniform(0.25, 0.45)

    low, high = context.radial_limits
    if context.slot:
        box = fit_slot_box(context, "drop")
        centre = box.radial_mid
        width = min(half_width, box.half_width)

        def build(scale: float) -> List[CellPoint]:
            return _drop_outline(
                centre + (box.radial_min - centre) * scale,
                centre + (box.radial_max - centre) * scale,
                width * scale,
                belly,
            )

        outline = fit_inside_slot(context, "drop", build)
    else:
        outline = _drop_outline(max(low, 0.0), min(high, length), half_width, belly)
    # Layer 3: the slot is measured from the outline actually drawn.
    return build_instance(context, [SmartVector(outline, closed=True)], slot_outline=outline)
```

Its registry entry:

```python
{
    "name": "drop",
    "category": "botanical",
    "generator": generate_drop,
    "positions": ["centre", "divider"],
    "roles": ["base", "slot"],
    "touch": True,
    "side_touch_heights": (),
    "seams": False,
    "embellishments": (),
    "spans_cell": False,
    "min_cell_width_px": 14.0,
    "min_ring_depth_px": 18.0,
    "max_overflow_inward": 0.0,
    "max_overflow_outward": 0.1,
    "slot_estimate": (0.5, 0.5),
}
```

What each key does:

- `name` is unique across the registry and is what the plan records. `category` is the UI category that enables it.
- `positions` is any of `centre` and `divider`. `roles` is any of `base`, `slot`, `attachment` and `back` (drawn behind the fronts of a layered ring; see [Layered rings and the back role](#layered-rings-and-the-back-role)). The drop can stand as a base or nest in a slot.
- `touch` declares that the motif's ink may be relied on for ring-to-ring contact. The engine does not read it yet.
- `side_touch_heights` lists the touch heights (`base`, `mid`) at which the generator honours the side-touch rule: given `side_touch_radial` in that height's range, it draws to its full angular budget with exact vertices at `(side_touch_radial, ±angular_limits)`. The drop does not place those vertices, so it lists none, and a ring with a drop base is never a `side` ring. To support side touch, draw the drop at the full budget and pin its widest vertex with `side_touch_radial_within`, as `generate_petal` does.
- `seams` is true for a motif that draws its own shared edges (see [Seams and the ring stream](#seams-and-the-ring-stream)). It implies `spans_cell`, and the composer never uses it in `both` mode.
- `embellishments` lists the embellishment names the motif accepts (see [Embellishments](#embellishments)). A motif that lists `veins`, `fan` or `dot` must pass an `Anatomy` to `apply_embellishments`, and a generator that lists any must call it. The drop lists none.
- `spans_cell` is true only when the ink reaches both angular limits by construction. It makes the motif eligible for the innermost ring and counts as contact with the cells beside it.
- `min_cell_width_px` and `min_ring_depth_px` are the size gates. Set them from measurement: `qa_patterns.py --probe` ignores them so you can see where the motif really breaks.
- `max_overflow_inward` and `max_overflow_outward` set the base's starting radial limits, as fractions of ring depth. The drop never goes below radial 0.0 and runs at most 0.1 past the outer boundary. With less than 0.1 of inward overflow, no `spans_cell` and no side-touch height, a ring with a drop base is a `stem` ring, and the composer gives every drop base a stem for contact.
- `slot_estimate` is the `(width, depth)` fraction of the cell that the motif's slot is expected to offer, which the composer uses to gate slot children without drawing anything; `None` means the motif declares no slot. It is only an estimate: the assembler fits each child to the slot the parent really declares in that cell, and drops the child where it does not fit. A known limitation follows: the petal's (0.5, 0.5) is optimistic at high division counts, where real slots are much smaller, so designs there drop many slot children and come out valid but sparser.

The three commands, run from the repository root:

```bash
.venv/Scripts/python qa_patterns.py --motif drop    # one motif, smoke tier: every position, role and ring fixture
.venv/Scripts/python qa_patterns.py --tier full     # every motif over the full matrix (about ten minutes with --jobs 6)
.venv/Scripts/python qa_report.py --corpus          # 180 pinned designs: 5 categories x 3 complexities x 6 seeds x 2 division modes
```

`qa_patterns.py` forces the motif in each position (`centre`, `divider` and `both`) and role (`base` of every forced cell, `slot` inside a petal, `contact` as a petal's attachment), over the ring fixtures 8/8/8/12, 7/12, 6/6 and 24/24/24, with fallback disabled so a rejection fails visibly. Each fixture's base symmetry is the gcd of its counts (4, 1, 6 and 24), and a case's label carries it, as in `div8-8-8-12_B4_c0.5_mws10_both_slot`. It never forces ring 0. A case is skipped when the declared gates exclude it. The gates read the fixture's plan, made by a `Composer` with the generator's own settings: a node's budget is its ring's planned `centre_share`, and a slot child is gated on the slot the petal frame really declares in each forced ring, drawn with that ring's `side_touch_radial` when the ring is in `side` mode. A seam motif is skipped in `both` mode. A slot job is also skipped when it places nothing and the slot every frame really ended with, after pull-backs, is below the child's gate; if any final slot admits the child, a missing child still fails. A case fails when the design does not validate, when the forced motif is never placed, or when the design has fewer regions than three quarters of a region per forced cell; slot children dropped where they did not fit are counted in the DROP column, not failed.

The matrix also runs pairing jobs over the same fixtures, complexities and white spaces. For each embellishment a motif accepts, in each single position it supports, the motif is forced as a base and the plan is edited so every forced node carries exactly that embellishment (an interior fill also clears the node's slot child); the label ends in `_emb-<name>`. For each layered front (`layered_fronts()`: a non-seam base that touches at `base` height) and each back motif (`layered_pairs()`), the design is generated with the `layered` mode forced, and the plan is edited so every layered ring where both pass the composer's size gates draws that front, composed as the composer composes it, in front of that back; the label ends in `_layered_base_back-<name>`. The edited plan is assembled and validated exactly as `generate()` does it, so a failing composite drops its back. A pairing job fails as a forced job does; an embellishment that does not fit, or a back that is dropped, in one case is counted in DROP and passes, but a pairing that is never drawn in any case of the matrix (`uncovered_pairings`) fails its motif. The run ends with every pairing's drawn and dropped totals.

The harness also runs eight property checks, each with a column in the table: determinism, monotone limits, angular containment, slot honesty, `SEAM`, `TANG`, `CUT` and `EMB`. `SEAM` holds when the motif declares no seams, or when every open end of its vectors at seed 11 sits at angular exactly ±1.0 and the vectors at seeds 11 and 12 with the same `ring_stream_seed` are identical. `TANG` holds when the motif lists no touch heights, or when at each of its heights (radial 0.12 for `base`, 0.45 for `mid`) the touch vertex has a `tangent_error_deg` of at most 10 for seeds 0 to 5. `CUT` holds when the motif has no `back` role, or when `compose_layered` with a `petal` front touching at radial 0.12 and this back, at seeds 0 to 5 on the standard cell, leaves every open back end either a seam end (angular exactly ±1.0) or exactly a vertex of a front outline; a seed whose composite raises `LayeringError` is a legitimate drop, but at least one must compose. `EMB` holds when determinism and monotone limits hold at complexity 0.9 with each of the motif's largest accepted sets (`embellishment_sets`: all it accepts, one interior fill at a time) and with each embellishment alone, and each embellishment alone is drawn on the standard cell at a white space of 10px or, failing that, 5px (a band's beads need more room between its arcs than 10px of white leaves there), so the check is never vacuous. `tests/test_qa_patterns.py` runs all eight for every registry entry, and `tests/test_motifs.py` runs its own determinism, narrow-limit and slot checks for every entry as well. The harness exits non-zero on any failure.

`qa_report.py --corpus` runs the 180 pinned designs and exits non-zero unless every design passes and both corpus quotas hold (`corpus_quota_failures`). The jobs whose seed is one of the first five `CORPUS_SEEDS` (`CORPUS_LAYERED_SEEDS`) force the `layered` mode wherever it is eligible, since layered rings are rare unforced. The jobs in `CORPUS_EMBELLISHMENT_JOBS` (three botanical jobs at complexity 0.15: `dot` on seed 42 in both division modes, and `fan` and `dot` on seed 777 with uniform divisions) force embellishments, since unforced picks draw too few fans (only petals accept one) and dots (at complexity 0.6 and above two echoes leave a dot no room); they are the fewest jobs found that meet the quota. The summary prints `layered rings: X/Y botanical+geometric rings (>= 25%)`, counting a ring as layered only when it kept its back, and `embellishments: name=count ...`, counting for each embellishment the rings it was drawn in (a node's names are credited when none dropped; otherwise each is checked by regenerating the node with the names up to it, `drawn_names`), each of which must be at least 10. Each design's row shows its layered rings (LAYR), dropped backs (BDRP) and embellishment counts. `--force-mode` replaces the corpus's own forcing on every job. Add `--overlays always` to write an overlay for every design into `test_output/`, and `--jobs N` to run in parallel. Finish with the suite: `.venv/Scripts/python -m pytest -q`.
