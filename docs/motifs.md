# Motif Authoring Guide

A motif is a small drawing that the engine places in a cell of a ring: a petal, a leaf, a band, a stem. This guide covers what a motif receives, what it must return, what the engine measures and checks, and how to add one. Motifs live in the `motifs/` package. The composer (`composer.py`) decides where motifs go, the assembler (`assembler.py`) draws and places them, and the resolver (`resolver.py`) settles how neighbouring rings meet. The design spec is `docs/superpowers/specs/2026-10-04-motif-engine-design.md`.

## Cell space and limits

Motifs are authored in normalised cell space, never in pixels. A point is `CellPoint(radial, angular)` from `motifs/geometry.py`. `radial` runs from 0.0 at the ring's inner boundary to 1.0 at its outer boundary. `angular` runs from -1.0 at the left edge of the wedge through 0.0 on the centreline to 1.0 at the right edge. Linework is a list of `SmartVector(points, closed=False)`; a closed vector joins its last point back to its first.

Ring boundaries and division lines are scaffolding. They are never drawn, and an open end that lands on one has landed on nothing. The only thing a line can connect to is other ink.

The `MotifContext` a generator receives carries the cell's geometry (`inner_radius`, `outer_radius`, `wedge_angle`, `center`), the drawing settings (`stroke_width`, `complexity`, `min_white_space`), a seeded `rng` unique to this node, its `position`, and the limits it must respect. Its pixel helpers are `ring_depth`, `half_angle`, `radius_at`, `radial_to_px`, `px_to_radial`, `angular_to_px`, `px_to_angular`, `cell_width_px` and `radial_for_cell_width` (the lowest radial at which the wedge is at least a given number of pixels wide, for motifs that would turn into a needle at the inner edge). `min_white_space` is the request's `min_pattern_size`, and `stroke_width` is `1.0 + 1.5 * (1.0 - complexity * 0.5)`, from 2.5px at complexity 0 down to 1.75px at complexity 1.

A straight segment in cell space is a curve on the page. `MotifContext.polyline` subdivides any segment that sweeps more than `MAX_SEGMENT_ARC_DEGREES` (4 degrees), so a constant-radial edge renders as a true arc rather than a chord that sags inside the ring. Conversion never clamps: a point at radial -0.2 is drawn below the ring, which is how overflow works. `quad_points(start, control, end, steps)` samples a quadratic curve in cell space without clamping, and `mirror_points` reflects a run across the centreline.

Three limits bound every motif:

- `angular_limits` is a half-width in cell units, 1.0 by default. No point may have `abs(angular)` beyond it.
- `radial_limits` is a `(low, high)` pair. No point may have a radial below `low` or above `high`. A base motif starts with `(-max_overflow_inward, 1.0 + max_overflow_outward)` from its registry entry, except in the innermost ring, whose bases get a floor of 0.0. A slot child gets `(0.0, 1.0)`. The resolver narrows the limits toward `(0.0, 1.0)` when overflow has to be pulled back.
- `slot` is `None` for a base motif. For a slot child it is the polygon, in the parent's cell space, that the child must fit inside.

Limits restrict rather than rescale. The engine never moves a point to make it fit; the generator must choose its points so they fit, and `MotifAnalyzer` rejects a motif that does not. The analyzer allows a tolerance of 0.025 cell units on every limit.

## The three-layer parametric model

Nothing about a motif is a fixed drawing. Every author works in three layers.

1. **Ranges the author declares.** Length as a fraction of ring depth (which may exceed 1.0 up to the overflow maximum), width as a fraction of the angular limit, waist position, tip roundness, wave amplitude, and so on. A range may depend on `complexity`: the petal's wave amplitude is drawn from 0.0 to `complexity * 0.06`, and `ring_band` adds a centre spoke only at complexity 0.5 and above.
2. **A draw per instance.** The generator draws its parameters from `context.rng` and builds the outline. Draw every parameter before applying any limit. The resolver regenerates a node from the same seed with narrower limits, and the result must be the same motif cut back, not a different motif: if a limit decided whether a parameter is drawn, every later draw would shift. This is what makes the two generator properties hold, and both are asserted by the test suite and by `qa_patterns.py`: the same stream and limits give identical vectors, and narrower `radial_limits` never give a point further out than wider ones.
3. **A declaration computed from the result.** The footprint, slot, overflow and base point are measured by `build_instance` from the vectors actually generated. A wavy petal yields a slot shaped by that wave, and the child placed in it is fitted to that slot.

When a detail would fall below `min_white_space` at this cell's pixel size, drop the detail rather than raising. The leaf drops its midrib when the halves would be too narrow to colour. Raising `MotifError` is for a motif that cannot be drawn at all: a failing base is replaced through the composer's fallback chain (at most three times per sequence entry and position), a failing slot child is dropped from that cell, and a failing attachment is dropped and counted.

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

## Closure, overflow and reaches

The closure rule: every open end of every motif lands on ink. The ink may be the motif itself, another motif in the cell, or a motif in a neighbouring cell or ring. On the assembled page the topology validator proves it: after noding, any endpoint of degree 1 is a dangling end. Every base motif must also belong to one connected structure, the component holding most of the innermost ring's bases. Slot children may be islands.

The composer gives each base a route to that structure before anything is drawn. A base has contact when it declares `max_overflow_inward` of at least `CONTACT_OVERFLOW` (0.1), or it is `spans_cell` in a ring that has contact elsewhere, or it carries an attachment. When none holds, the composer attaches a stem; a ring with no inward route at all gets one on its first node. When an assembled base still floats, `Composer.replace_node` first adds a stem to it (this repair stays available under `force_motif`, since it changes no motif), then substitutes another eligible motif, then falls back to the category's safe band.

**Overflow** is ink past radial 0.0 or 1.0, declared by `max_overflow_inward` and `max_overflow_outward` as fractions of the ring's depth. Bases in the innermost ring never overflow inward. In pass two the resolver tests each node's overflow against the neighbouring ring's ink. An overflow that crosses neighbour ink, or that comes within `CLEARANCE_PX` (4px, twice the pen radius) of it, is pulled back: a binary search of `SEARCH_STEPS` (10) halvings finds the widest limit that keeps clear, the node and its slot children are regenerated from their stored seeds with that limit, and if the result still conflicts the side's overflow is removed entirely. A side is pulled back at most `MAX_PULL_BACKS` (4) times. Overflow may touch neighbour ink at a shared vertex but never cross it. The clearance applies outside a touch disc of radius `max(min_white_space, 8px)` around the run's extreme vertex (where a touch may be made) and around every vertex of the path shared with other ink (a touch already made, or a reach that landed there). Inside those discs the gap may narrow to a touch.

After every ring is resolved, a final touch pass runs over every overflow side: an extreme vertex within `TOUCH_GAP_PX` (4px) of neighbour ink is moved onto it, with a vertex inserted into the ink it lands on. The move is undone when it would make the two rings cross or crowd each other, judged from both rings, or close off a face too thin or too small to colour. A vertex shared with any other ink is never moved.

**Reaches** are drawn for attachments. A reach end records a page point and a direction. In pass two the reach starts on the node's own ink, at the point of that ink furthest along the reach's line (a stem whose base point lies inside its petal starts where it leaves the petal), and casts along the line until it meets ink. It lands at the first point along the ray within `TOUCH_GAP_PX` of other ink, on that ink's nearest point, so a reach passing within 4px of ink lands on it rather than running beside it. An inward reach that finds nothing within its `max_length_px` recasts all the way to the design centre. A reach shorter than `CLEARANCE_PX` collapses to a touch: the anchor vertex is moved onto the hit and no path is drawn, unless the move would cross or crowd ink or close off a face too thin or too small to colour. A wavy reach is a single sine wave of at most 3px amplitude (and at most 10 percent of its length), reduced through scales 1.0, 0.5, 0.25 and 0.0 until it keeps `CLEARANCE_PX` from all other ink. No reach is drawn when it would close off a face too thin or too small to colour. Both ends of a drawn reach are vertices of the ink they touch.

A touch is always exact: the touching end is a vertex of its own path, and the point it lands on is inserted as a vertex into the path it touches. Nothing relies on a snap tolerance to read as connected.

## Archetypes that satisfy closure

Every motif in the registry is one of four shapes. A new motif should be one of them too, or a combination.

### Enclosing outline

One closed vector. It has no open ends, so it satisfies closure on its own, and its interior can declare a slot. `petal` is the model: a mirror-symmetric outline built from two quadratic runs per side, optionally wavy, passing `slot_outline=outline` so a child can nest inside. `diamond` is the slot-only version, a pure island inside its parent. An enclosing base still needs contact with the structure, which comes from inward overflow, from `spans_cell`, or from a stem.

### Outline with midrib

A closed outline plus an open vector whose two ends are vertices of the outline. `leaf` puts a vertex in the middle of its straight base edge so the midrib's lower end lands on outline ink, and its upper end is the apex. The midrib is a self-touch, so it needs no reach end. It splits the leaf in two, so the leaf declares no slot of its own, and it draws the midrib only when each half, at the leaf's widest point, is at least `min_white_space` wide.

### Spans-cell band

A closed shape that reaches both angular limits by construction (`spans_cell: True`), so it meets the same motif in the neighbouring cells along a shared radial edge. `ring_band` draws its inner and outer edges from overlapping ranges, so any two neighbouring draws share some radial span. `scallop` is a divider-position band whose lower edge dips into the ring below. The safe bands (`<category>_safe_band`, from `motifs/fallback.py`) are the plainest case: a band from radial 0.4 to 0.6 across the full angular limit, valid in any cell. Spans-cell bases are the only bases the innermost ring uses.

### Pure reach

No vectors at all, only a reach end. `stem` declares one inward `ReachEnd` at `CellPoint(0.0, 0.0)` with a maximum of 0.9 ring depths, wavy at complexity 0.6 and above. It has the `attachment` role: it is never a base, and the composer hangs it off a base that needs contact. The assembler generates attachments only to record their reach ends; the resolver draws the line.

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
- `positions` is any of `centre` and `divider`. `roles` is any of `base`, `slot` and `attachment`. The drop can stand as a base or nest in a slot.
- `touch` declares that the motif's ink may be relied on for ring-to-ring contact. The engine does not read it yet.
- `spans_cell` is true only when the ink reaches both angular limits by construction. It makes the motif eligible for the innermost ring and counts as contact with the cells beside it.
- `min_cell_width_px` and `min_ring_depth_px` are the size gates. Set them from measurement: `qa_patterns.py --probe` ignores them so you can see where the motif really breaks.
- `max_overflow_inward` and `max_overflow_outward` set the base's starting radial limits, as fractions of ring depth. The drop never goes below radial 0.0 and runs at most 0.1 past the outer boundary. With less than 0.1 of inward overflow and no `spans_cell`, the composer gives every drop base a stem for contact.
- `slot_estimate` is the `(width, depth)` fraction of the cell that the motif's slot is expected to offer, which the composer uses to gate slot children without drawing anything; `None` means the motif declares no slot. It is only an estimate: the assembler fits each child to the slot the parent really declares in that cell, and drops the child where it does not fit. A known limitation follows: the petal's (0.5, 0.5) is optimistic at high division counts, where real slots are much smaller, so designs there drop many slot children and come out valid but sparser.

The three commands, run from the repository root:

```bash
.venv/Scripts/python qa_patterns.py --motif drop    # one motif, smoke tier: every position, role and ring fixture
.venv/Scripts/python qa_patterns.py --tier full     # every motif over the full matrix (about ten minutes with --jobs 6)
.venv/Scripts/python qa_report.py --corpus          # 180 pinned designs: 5 categories x 3 complexities x 6 seeds x 2 division modes
```

`qa_patterns.py` forces the motif in each position (`centre`, `divider`, and `both` with a fixed share) and role (`base` of every forced cell, `slot` inside a petal, `contact` as a petal's attachment), over the ring fixtures 8/8/8/12, 7/12, 6/6 and 24/24/24, with fallback disabled so a rejection fails visibly. It never forces ring 0. A case is skipped when the declared gates exclude it. A case fails when the design does not validate, when the forced motif is never placed, or when the design has fewer regions than three quarters of a region per forced cell; slot children dropped where they did not fit are counted in the DROP column, not failed. The harness also runs four property checks (determinism, monotone limits, angular containment, slot honesty), which `tests/test_motifs.py` runs for every registry entry as well. It exits non-zero on any failure. `qa_report.py --corpus` exits non-zero unless every design passes; add `--overlays always` to write an overlay for every design into `test_output/`, and `--jobs N` to run in parallel. Finish with the suite: `.venv/Scripts/python -m pytest -q`.
