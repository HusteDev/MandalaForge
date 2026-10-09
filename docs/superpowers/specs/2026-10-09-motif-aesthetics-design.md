# Motif Aesthetics Design

**Status:** Approved in conversation, awaiting written review

**Date:** 2026-10-09

**Scope:** Makes the motif engine's output look like the coloring-book mandalas in `examples/`. Reshapes the existing motifs, adds six new ones, and adds three engine mechanisms (touch height, seam ends, layered rings) plus a shared embellishment layer and a two-weight stroke. Builds on the motif engine (`docs/superpowers/specs/2026-10-04-motif-engine-design.md`, revision 2 in its section 13) and keeps every rule that spec settled: base symmetry B, contact priority side > overflow > stem, rings filled, every open end on ink, the validator as the authority.

## 1. Why

Revision 2 of the motif engine passes every structural rule, and the user confirmed its symmetry and design requirements are correct, but the designs are not attractive. Comparing its output with the 48 reference images in `examples/` gives four causes:

1. Straight lines read as scaffolding. `ring_band` draws a concentric band whose side edges sit on the dividers, plus a centre spoke, and stems run straight down the centreline. Both look like the ring and division lines that are never meant to be drawn, so designs read as dartboards.
2. Shapes are blobby. Side touch makes every base bulge to the full cell width at a radial between 0.35 and 0.6 and meet its neighbour at a corner, so petals become lobes.
3. Cells have no interior detail. The references get most of their richness from echo lines, veins, fan rays, dots and bead rows. The engine draws one outline and an occasional diamond.
4. The vocabulary is six motifs, two of which are a stem and a band.

The references share a small set of techniques: pointed lotus petals with S-curved sides that touch their neighbours near the base and leave the tips free; a second petal ring behind the first, offset by half a wedge, peeking out between the front petals; one or two echo outlines inside a shape; fan rays, veins and dots inside shapes; round scallops and bead chains as edge trims; curls, hearts and star points as accents; bold outlines with finer detail lines; smooth curves everywhere, with corners only at intentional tips.

## 2. Decisions

These were settled in design conversation and are not open.

1. One project covering all four causes, delivered in three phases, each ending at a visual review gate (section 10).
2. Side touch height is chosen per ring by the composer, `base` or `mid`, among the heights every base in the ring supports.
3. Layering is an engine feature: a ring can carry a back layer whose hidden lines are removed by the front motifs.
4. Interior detail comes from a shared embellishment layer that motifs opt into, not from per-motif code. Motif-specific detail may still live in a generator. Slot children stay.
5. The vocabulary is the twelve motifs of section 7: six reshaped, six new.
6. Two line weights: motif outlines at today's stroke, embellishments at 0.6 of it.
7. Layering and embellishments happen inside the motif layer, in cell space, so the resolver regenerates them with their node and needs no occlusion logic. Seam ends are added so ring-wide shapes can be drawn without side edges.

## 3. Touch height

### 3.1 Plan and registry

`RingPlan` gains `touch_height`, `"base"` or `"mid"`. The composer draws `side_touch_radial` from `BASE_TOUCH_RANGE = (0.08, 0.2)` for `base` and from `MID_TOUCH_RANGE = (0.35, 0.6)` for `mid`. A plan without the field loads as `mid`.

The registry key `side_touch: bool` becomes `side_touch_heights: Tuple[str, ...]`, the heights at which the motif can place the side-touch vertex. An empty tuple means the motif cannot side-touch. Seam motifs (section 4) connect their ring through their seams and count as side-capable at every height.

### 3.2 Choosing the height

After a ring's bases are planned, the composer intersects the `side_touch_heights` of every base in the ring. When the intersection is empty, the ring is not side-capable and its contact mode is chosen as revision 2 does today (overflow, then stem). Otherwise the composer draws the height uniformly from the intersection with the ring-level stream. Layered rings (section 5) always use `base`, so only front motifs whose `side_touch_heights` include `base` are eligible in them.

### 3.3 Smooth touch

Every side-touching outline places the side-touch vertex as revision 2 requires (exactly `CellPoint(side_touch_radial, ±angular_limits)`, no point wider than the budget) and additionally makes the outline's tangent at that vertex parallel to the divider: the curve control points on each side of the vertex sit at the same angular as the vertex. Neighbours then meet smoothly instead of at a corner. Two such outlines are mirror images across the divider and each stays inside its own cell, so they cannot cross.

With `base` height the touch vertex is the outline's widest point and the outline narrows above it, which leaves V-shaped gaps between neighbouring tips.

## 4. Seam ends

### 4.1 The rule

A registry entry may declare `seams: True`. Such a motif may end an open vector exactly on the cell edge, at angular `±1.0`. The neighbouring cell draws the mirrored end at the same page point, so the two ends meet at a shared vertex. Seam ends are allowed only when the motif's angular budget is the full 1.0 (a single-position ring, or the back layer of a layered ring), never in `both` mode.

### 4.2 Ring stream

`MotifContext` gains `ring_rng`, a `random.Random` seeded by `ring_stream_seed(ring_seed, ring_index, motif_name, position)`, identical in every cell of the ring. Every parameter that decides where a seam end sits must be drawn from `ring_rng`, never from `rng`. Salts are mixed with `zlib.crc32` of the salt string, never with Python's `hash()`, which is randomised per process.

### 4.3 Guarantees

- The composer gives a seam motif its whole position across the ring: every sequence entry uses that motif there, so a seam end never faces a different motif.
- Seam motifs declare zero overflow on both sides, so the resolver never pulls one back and never regenerates one with different limits.
- `MotifAnalyzer` accepts a seam end as accounted for when the motif declares seams and the end's angular is exactly `±1.0` within its tolerance.
- `Assembler.snap_to_ink` already merges ends that meet to float noise under inexact rotations. A seam that does not meet shows as a dangle and fails validation.

## 5. Layered rings

### 5.1 Plan

`POSITION_MODES` gains `"layered"`. In a layered ring the front motifs occupy the centre position with angular budget 1.0, and sequence entries vary as usual. `RingPlan` gains `back: Optional[CellRecipe]`, one back motif for the whole ring, placed on every divider, and `back_dropped: bool`. A layered ring is eligible only outside ring 0 and only when at least one motif with role `"back"` passes its size gates at budget 1.0. The style's preferred mode keeps weight 0.6 and every other eligible mode gets 0.2.

### 5.2 Generation

`motifs/layering.py` exposes `compose_layered(front_context, front_entry, back_context, back_entry) -> MotifInstance`. The assembler calls it for each centre node of a layered ring instead of calling the front generator directly.

1. Generate the front with `front_context`, embellishments included (section 6), as an ordinary base.
2. Generate the back once with `back_context`: position `divider`, angular limits 1.0, radial limits `(0.0, 1.0)`, its `rng` replaced by the ring stream for the back motif, so every cell draws the same back motif. Back embellishments draw from the same ring stream.
3. Shift the back's vectors by `+1.0` and by `-1.0` angular units, which places them on the cell's two dividers exactly (one angular unit is half a wedge and cell space is linear in angle). Keep the parts with `abs(angular) <= 1.0`. Back motifs are mirror-symmetric, so the trim falls on their centreline vertices (tip and base), which become seam ends.
4. Cut away every part of every back vector that lies inside the front's fill, the union of the front's closed outlines. Each cut point is inserted as a vertex into the front outline it lies on, so the touch is exact. Containment is computed in cell space, which is exact because tracing maps straight cell-space segments to the drawn curves.
5. Drop a visible back piece shorter than `2 * min_white_space` (in pixels) when it has no seam end. A piece that keeps a seam end is never dropped.
6. Check that every visible back piece stays at least `min_white_space` plus half of each stroke from the front outline, except within the touch disc of its own cut ends. Raise `MotifError` otherwise.
7. Return front and back vectors as one `MotifInstance`. The declaration's slot is measured from the front outline only. Back vectors keep their own roles for output (section 5.3).

A front motif's tip may overflow outward as usual. A resolver pull-back regenerates the whole composite with narrower front limits; the back is regenerated identically, because it depends only on the ring stream and fixed limits, and is cut again against the new front. The front never covers a point on the divider except at its side-touch vertex, so the seam ends of the two back halves always agree.

### 5.3 Output and validation

Back paths are placed with role `"back"`. `AssembledDesign.base_mask` treats `"back"` as base ink for structural connectivity. The analyzer's existing open-end rule already accounts for cut ends (they touch another vector) and, with section 4, for seam ends.

### 5.4 Failure

When `compose_layered` raises for any sequence entry of a layered ring, the back layer is dropped for the whole ring: the composer sets `back = None`, `back_dropped = True` and the position mode to `centre`, and the assembler places the ring again. Dropping it in one cell only would leave the neighbouring half's seam dangling.

## 6. Embellishments

### 6.1 Anatomy

`build_instance` gains `anatomy: Optional[Anatomy]`, where `Anatomy(base: CellPoint, tip: CellPoint, outline: int)` names the host's base point, its tip, and the index of its closed outline vector. A motif that accepts `veins`, `fan` or `dot` must supply it.

### 6.2 Application

`motifs/embellish.py` holds the embellishment registry and `apply_embellishments(context, vectors, anatomy, names) -> List[SmartVector]`. A generator calls it after drawing its outline and before `build_instance`. Embellishments run in a fixed order: `echo`, then at most one interior fill (`veins` or `fan`), then `dot`; `beads` applies only to bands. Each embellishment draws from its own stream, seeded by `node_seed` salted with `"emb:" + name`, so adding or dropping one never shifts another's draws. An embellishment that does not fit at this cell's pixel size is dropped and counted in the assembler's statistics; it never raises. Every embellishment end that lands on the host outline or an echo is inserted there as a vertex.

Embellishments are recomputed from the host on every regeneration, so a narrower radial limit shrinks the host and everything inside it, and the generator properties (determinism, narrower limits never reach further out) hold for embellished output.

### 6.3 The five embellishments

- **echo:** one inner outline, or two at complexity 0.6 and above, repeating the host's shape. Each echo is the host outline (or the previous echo) inset in page space by `min_white_space` plus half of each stroke, measured the way `measure_slot` measures a slot, and drawn as a closed `detail` vector; each echo shrinks the slot, and slot children and interior fills nest inside the innermost echo.
- **veins:** a midrib along the axis from base to tip, ending on the innermost echo or the outline, plus pairs of side veins from the midrib toward the tip, ending on the same ink. Vein starts are spaced along the midrib by at least `min_white_space` plus one detail stroke.
- **fan:** a half-disc hub at the base and rays from the hub's arc to the innermost echo or the outline. The ray count is the largest for which every wedge between rays is at least `min_white_space` plus one detail stroke wide at the hub.
- **dot:** a small closed circle near the base inside the innermost echo or the outline, floating, as slot children may. Its diameter is drawn between `min_white_space` and twice that, and it keeps `min_white_space` clear of all ink.
- **beads:** a row of floating closed circles centred between a band's two arcs, evenly spaced, with the count per cell and the diameter drawn from the ring stream so the ring stays symmetric. Each bead keeps `min_white_space` clear of both arcs and of its neighbours.

### 6.4 Selection

Each registry entry gains `embellishments: Tuple[str, ...]`, the names it accepts. The composer picks them per sequence entry, so ring symmetry holds, and stores them in `CellRecipe.embellishments` (default empty). The count is `n = clamp(floor(3 * (complexity - 0.2) / 0.8 + u), 0, 3)` with `u` uniform in `[0, 1)` from the entry's pick stream; names are drawn without replacement from the accepted list, keeping at most one interior fill. An entry with an interior fill gets no slot child, and an entry with a slot child gets no interior fill.

## 7. Vocabulary

### 7.1 Shared geometry

`motifs/geometry.py` gains `cubic_points(start, control1, control2, end, steps)`, sampling a cubic curve in cell space without clamping. Every curved outline is built from cubic and circular-arc segments. A circle meant to look round on the page is built in pixels and mapped into cell space with `px_to_radial` and `px_to_angular`.

### 7.2 Reshaped motifs

| Motif | Shape | Roles | Touch heights | Accepts |
|---|---|---|---|---|
| petal | Lotus profile: two cubic segments per side, narrow base, belly between 0.3 and 0.6 of the length, concave flare to a sharp tip; draws tip sharpness and flare. | base, slot, back | base, mid | echo, veins, fan, dot |
| leaf | Narrow base, curved pointed apex. The midrib moves to `veins`. | base, slot, back | base, mid | echo, veins |
| scallop | Seam motif: a ring of true circular lobes edge to edge; lobe height and direction (outward or inward) from the ring stream; zero overflow; spans the cell. | base | seams | none |
| band | Was `ring_band` (`find_motif` keeps the old name as an alias). Seam motif: two concentric arcs at radii from the ring stream, no side edges, no spoke; spans the cell and still closes the centre in ring 0. | base | seams | beads |
| stem | Reach styles `bow` (a single arc) and `s` (an S-curve) join `wavy`; the composer stops choosing `straight`. | attachment | none | none |
| diamond | Straight-sided or concave-sided, drawn per instance. | slot | none | none |

The stem's curved styles are generated by the resolver's reach drawing, with the same clearance check and the same amplitude fallback ladder as `wavy` (1.0, 0.5, 0.25, then straight). This is the resolver's only change in this project.

### 7.3 New motifs

| Motif | Category | Shape | Roles | Touch heights | Accepts |
|---|---|---|---|---|---|
| teardrop | botanical | Circular-arc base, cubic sides to a point | base, slot, back | base, mid | echo, dot |
| rounded_petal | botanical | Lotus profile with a circular-arc tip | base, slot, back | base, mid | echo, veins, fan, dot |
| heart | botanical | Two lobes and a point, widest near the top | base (centre), slot | mid | echo |
| curl | botanical | A mirrored pair of spirals joined at the base, each ending on its own earlier turn; turns spaced at least `min_white_space` plus one stroke apart | base (centre), slot | mid | none |
| bead | geometric | A true circle; as a divider base in `both` mode its horizontal diameter ends on the shared side-touch vertices | base (divider), slot | base, mid | echo |
| spike | geometric | Concave-sided star point, widest at its base | base, back | base | echo, fan |

Celtic, art deco and abstract still have no motifs and stay disabled in the UI.

## 8. Line weight

`SmartVector` gains `weight: str = "outline"`, either `"outline"` or `"detail"`. Embellishments draw `detail`. `PlacedPath.stroke_width` is the assembler's stroke for `outline` and `DETAIL_WEIGHT_SHARE * stroke` with `DETAIL_WEIGHT_SHARE = 0.6` for `detail`; the SVG writer already emits each path's own width. Clearances become width-aware: wherever slot measurement or the analyzer adds one full stroke today, it adds half the stroke of each of the two lines involved. `TopologyValidator` works on centrelines with a fixed pen radius and is unchanged; thinner detail lines only make faces roomier than it assumes.

## 9. Composer and plans

### 9.1 Streams

Today the motif pick and the motif's own parameter draws share one seed, which biases parameters such as petal length. `node_seed` gains a `salt: str = ""` argument mixed with `zlib.crc32`, and each consumer gets its own salt: `"pick"` for motif and embellishment selection, `"emb:<name>"` for each embellishment, `"back"` for the back motif's ring stream, and `"ring:<motif>:<position>"` for seam motifs' ring streams. The generator's own stream stays unsalted.

### 9.2 Plan fields

New fields, all with defaults so revision-2 plans still load: `RingPlan.touch_height = "mid"`, `RingPlan.back = None`, `RingPlan.back_dropped = False`, `CellRecipe.embellishments = []`. Every seed renders differently after this project, gallery items included; pinned tests are re-baselined. The API and UI carry the richer plan unchanged.

## 10. Delivery and acceptance

The work lands in three phases. Each phase ends with the automated gates (full tier of `qa_patterns.py` exit 0, `qa_report.py --corpus` 180/180, pytest green) and a review set of about twelve finished designs plus QA overlays sent to the user. Work stops at each gate until the user gives a visual verdict; the visual review is the acceptance gate.

1. **Phase 1, engine and reshaped motifs:** touch height, seam ends, band and scallop as seam motifs, smooth touch tangents, `cubic_points`, reshaped petal, leaf and diamond, curved stems, stream salting, two-weight plumbing.
2. **Phase 2, layering and embellishments:** layered rings, the five embellishments, the anatomy contract, selection in the composer.
3. **Phase 3, new motifs:** teardrop, rounded_petal, heart, curl, bead, spike.

## 11. QA

`qa_patterns.py` covers every motif, every motif with each embellishment it accepts, and layered composites for every front and back pairing. New property checks join DET, MONO, ANG and SLOT:

- **SEAM:** every seam end lies at angular `±1.0` and coincides with the mirrored end of the same motif in the neighbouring cell.
- **TANG:** at every side-touch vertex, the outline's page-space tangent is within 10 degrees of the divider's direction.
- **CUT:** every occlusion cut point is a vertex of the front outline.
- **EMB:** DET and MONO hold for embellished output.

`qa_report.py --corpus` keeps 180 designs, with at least a quarter of the rings of its botanical and geometric designs layered (the other three categories have no motifs to layer) (the corpus runner forces the `layered` position mode on chosen rings when the natural rate is lower) and every embellishment exercised at least ten times.

## 12. Documentation

`docs/motifs.md` gains seam ends and the ring stream, touch heights and smooth touch, the anatomy contract, line weights, embellishments, and layering. `docs/architecture.md` describes the layered composite and where embellishments run.

## 13. Out of scope

A three-weight hierarchy with a heavy outer silhouette; motifs for celtic, art deco and abstract; drops hanging off tips; layering in ring 0; front motifs on the dividers with the back layer in the centre.
