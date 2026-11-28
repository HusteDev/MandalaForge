# Celtic Interlace Design

**Status:** Draft plan. Open questions answered by the user on 2026-10-12 (section 11); revised against the Celtic references added to `examples/` the same day. Nothing here is built.

**Date:** 2026-10-11, revised 2026-10-12

**Scope:** How a `celtic` category can work in the motif engine: knots, plaits, braids and interlaced bands whose strands pass over and under each other and run from cell to cell and ring to ring. Builds on the motif engine spec (`2026-10-04-motif-engine-design.md`, revision 2) and the motif aesthetics spec (`2026-10-09-motif-aesthetics-design.md`), and reuses their seam ends, ring streams, layering cuts and line weights. Other new motifs are in `2026-10-11-motif-roadmap-design.md`.

## 1. Why Celtic does not fit the current model

Every motif today is drawn in one cell, centred on angular 0, and meets its neighbours at a single shared vertex (side touch), at a seam end, or through overflow and stems. That works because a petal does not care what is in the next cell beyond where they touch.

Interlace is different in four ways:

1. **Strands travel.** A strand in a plait leaves one cell and enters the next, and in knotwork it can leave one ring and enter another. The cell is no longer the unit of a shape; the strand is.
2. **Over and under is a global property.** A Celtic strand alternates strictly: over, under, over, under, all the way round. Whether a crossing in this cell is over or under depends on every crossing before it along the strand, including crossings in other cells and other rings.
3. **Single lines cannot show over and under on a colouring page.** A gap in a line is a dangling end, which the closure rule forbids. Interlace has to be drawn as ribbons (two parallel outlines) so that the under ribbon's outlines can stop exactly on the over ribbon's outline, which is a touch, not a gap. This is why the old engine's `smart_laced`, `knot_simple` and `braid_simple` never read as interlace (`docs/pattern-category-audit.md`): they were single lines crossing with no over and under.
4. **Interlace is not mirror-symmetric.** The geometry of a knot is symmetric about its axis, but mirroring swaps every over for an under. Celtic motifs are rotationally symmetric only. The engine assumes mirror symmetry in several places (back motifs, authoring half an outline).

### 1.1 What the references show

Twelve Celtic references were added to `examples/` on 2026-10-12 (originally `celtic01.png` to `celtic11.png` and `celtic-mandala-knotwork-vector-39422106.avif`; renamed on 2026-11-27 to their visual-library names: `woven-star-shield-8` (celtic01), `stained-knot-lobes-8` (celtic02), `knot-cross-4` (celtic03), `knot-medallion-8` (celtic04), `knot-square-frame-4` (celtic05), `knot-hexagram-6` (celtic06), `knot-triangles-6` (celtic07), `jewel-knot-medallion-8` (celtic08), `vesica-knot-cross-4` (celtic09), `spike-knot-star-8` (celtic10), `knot-bloom-8` (celtic11), and `triskele-spiral-rim`). Four things stand out:

1. **Large woven loops are the commonest structure.** `woven-star-shield-8`, `stained-knot-lobes-8`, `knot-hexagram-6`, `spike-knot-star-8` and `knot-bloom-8` are built mostly from big closed loops (pointed ovals, petals, circles), repeated round the centre, each one weaving over and under its neighbours and spanning two to four rings. Grid knotwork (plaits with breaks) is the second structure, used for bands and panels (`knot-cross-4`, `knot-medallion-8`, `knot-square-frame-4`, `knot-triangles-6`).
2. **Rails are everywhere.** Knot bands sit between thin border circles in `knot-cross-4`, `knot-medallion-8`, `knot-square-frame-4`, `vesica-knot-cross-4` and `spike-knot-star-8`.
3. **Mixing is normal.** `vesica-knot-cross-4` and `spike-knot-star-8` combine knot panels with leaves, petals, bead rows and dots, which matches the decision to allow mixed designs.
4. **Ribbon style varies.** Single ribbons in `woven-star-shield-8`, `stained-knot-lobes-8`, `knot-triangles-6` and `knot-bloom-8`; double-line ribbons in `knot-cross-4`, `knot-medallion-8` and `knot-hexagram-6`. Single is the default; double stays an option.

## 2. Core idea

Treat Celtic interlace the way Celtic artists construct it: as a **grid of crossings with breaks**, solved for a whole region at once, rather than as motifs picked per cell.

- A region that holds interlace is an **interlace zone**: one ring, or several adjacent rings planned together.
- The zone carries a polar grid of crossing points. With no breaks, strands run diagonally through every crossing and the result is a plait. A **break** on a grid edge replaces a crossing with two turn-backs, which is how plaitwork becomes knotwork (George Bain's method).
- The strand layout, the over and under, the ribbons and the hidden-line cuts are all computed from the zone's grid and break map in one step, so neighbouring cells and rings agree by construction instead of by matching.
- The grid is one of two **centreline sources**. The other is **woven loops** (section 3.6): a set of closed curves placed round the centre with no grid at all. Both feed the same weave pipeline (alternation, ribbons, cuts), so everything after the centrelines is shared.
- Per-cell choice survives as **templates**: named break patterns for a block of the grid (a loop knot, a ring knot, a triquetra block). The composer picks templates per sequence entry, under the rule that every template in a zone has the same boundary signature (section 5.3).

This keeps the engine's existing guarantees: every line ends on ink, the design is exactly `B`-fold symmetric, and the validator stays the authority.

## 3. Strands, ribbons and crossings

### 3.1 The ribbon primitive

A new module, `motifs/interlace.py`, owns strands. A strand is a closed centreline (a strand never ends in Celtic work; a strand that would end at a zone edge turns back instead). It is drawn as a ribbon:

- two outlines, the centreline offset by `+w/2` and `-w/2` in page space, at `outline` weight;
- optionally a third line on the centreline at `detail` weight (the "double-line" ribbon common in Celtic art), cut at the same places as the outlines.

The ribbon's interior is the colourable face. Its width `w` must leave a pen-holding face: `w >= min_white_space + stroke_width`.

Single ribbons are the default; `double` is a per-zone option (decision 2026-10-12).

### 3.2 Crossings and the cut

At a crossing one ribbon is over and one is under. The under ribbon's outlines (and its centre line) are cut away inside the over ribbon's fill, and each cut point is inserted as a vertex into the over ribbon's outline. This is exactly the operation `motifs/layering.py` already performs for a back motif under a front motif (cut against the fill, insert the cut as a vertex, check clearance outside the touch disc), applied per crossing instead of per front. The layering code should be generalised into a shared `occlude(over_fill, under_vectors)` helper rather than duplicated.

After cutting there are no line crossings left at all: every meeting is a T-junction of degree 3, which the topology validator already reads as a touch.

### 3.3 Alternation

Each strand is walked from a fixed start, and its crossings are assigned over, under, over, under in order. Any knot diagram drawn on a plane or an annulus admits a consistent alternating assignment (the faces can be two-coloured like a chessboard), so the walk never contradicts itself; QA asserts it anyway (property ALT).

Alternation also guarantees the colouring rule against encircling faces. An under ribbon's face runs only from one under-crossing to the next, so no ribbon face can run all the way round the centre. The one exception is a strand with no crossings, which the planner never produces in a zone (QA property CLOSED).

### 3.4 The symmetry constraint

Rotating the design by one wedge (`360 / B` degrees) must map every over crossing onto an over crossing. If a wedge holds an odd number of crossing columns, the rotation maps the alternating assignment onto its opposite, and the design is no longer truly `B`-fold symmetric (it is symmetric in shape but every crossing is flipped). So:

- **Rule P1:** the number of crossing columns per wedge is even.
- **Rule P2:** if the number of crossing columns per cell is odd, neighbouring cells have opposite over and under. The cell recipe then carries a `parity` bit and the ring's sequence effectively alternates, which needs an even number of cells per wedge. The composer prefers an even column count per cell, so P2 rarely applies.

These two rules are the "strict interaction with neighbours" in its simplest form: the division count of a Celtic ring is not free.

### 3.5 Chirality

Celtic motifs set the registry flag `chiral: True` (shared with the roadmap, section 3.6 there). A chiral motif is never a back motif, never authored as a mirrored half, and every cell of its ring uses the same handedness. Its centreline may still be authored mirror-symmetric; only the over and under assignment is chiral.

### 3.6 Centreline sources

The weave pipeline takes any set of closed centrelines in page space. It needs only three things from them: every pair of curves crosses transversally (no tangencies), no three curves meet at one point, and every crossing angle is within the XANG range. Two sources produce such sets:

- **Grid knotwork** (section 4): crossings on a conformal polar grid, breaks to make knots. Best for bands and panels.
- **Woven loops:** `n` copies of one closed loop rotated round the centre, `n` a multiple of `B`. The loop shape comes from the existing outline generators drawn as a centreline at full design scale: a pointed oval (vesica), a lotus petal, a circle offset from the centre, a teardrop. Each loop spans the rings between its base radius and its tip radius, so a loop zone is always multi-ring. Crossings are found by curve intersection, not from a grid. Parameters (loop shape, length, width, offset angle, and a second loop set at half a wedge with a different length, as in `woven-star-shield-8`) come from the zone stream.

Woven loops have their own constraints. Loop width must keep neighbouring crossings far enough apart for the ribbon and the gap between ribbons to hold a pen. The number of crossings a loop makes with its neighbours must be even, or alternation flips under rotation (rule P1 restated for loops: the crossings per wedge are even). A circle round the centre (the woven circle in `stained-knot-lobes-8`) can join a loop set, adding two crossings with each loop it cuts.

The **woven layered ring** of section 7.4 is the one-ring special case: front and back petals as two loop sets.

## 4. The grid

### 4.1 Log-polar mapping

A zone's grid is laid out in grid space `(u, v)`, where `u` counts crossing columns round the ring and `v` counts crossing rows outward. It is mapped to the page by a conformal (log-polar) map: angle `theta = u * 2 * pi / C` and radius `r = r_inner * q^v`, with `q = exp(2 * pi / C)` for `C` columns round the full circle.

Conformal means grid squares stay square on the page at every radius, so strands cross at right angles everywhere and ribbon width can scale with radius without distorting. A linear radial map would make inner crossings flatter than outer ones and break the pen and white-space constraints at the inner edge first.

Consequence: a zone's outer-to-inner radius ratio is fixed by the grid, `q^R` for `R` rows. With `C = 24` columns, `q` is about 1.30, so one row of crossings needs a ring whose outer radius is 1.3 times its inner radius; with `C = 48`, about 1.14. The composer either fits ring radii to the grid or picks `C` and `R` to fit the radii, within a tolerance (section 4.3).

### 4.2 Breaks and boundaries

Grid edges join neighbouring crossing points. Each grid edge either lets the strands cross at its midpoint (open) or carries a break (closed), in which case the two strands that would have crossed turn back parallel to the break instead. The zone's inner and outer boundaries are always closed, so strands turn back at the edge of the zone.

A plait is a zone with no internal breaks. A 2-strand twist is a one-row zone. A loop knot is a plait with breaks on every other column edge. Templates (section 5.3) are named break layouts for a block of the grid.

### 4.3 Sizing

With grid pitch `p` (distance between neighbouring crossing points on the page at a given radius) and ribbon width `w`:

- the ribbon holds a pen: `w >= min_white_space + stroke_width`;
- the background gaps between ribbons (squares turned 45 degrees in a plait) hold a pen: `w <= p / sqrt(2) - min_white_space - stroke_width`;
- a turn-back's inner radius keeps `min_white_space` clear.

So `p >= sqrt(2) * 2 * (min_white_space + stroke_width)`, about 34px at `min_white_space` 10 and stroke 2. At a radius of 150px that allows at most about 27 columns round the ring. The composer gates a zone on these numbers the same way size gates stop a motif being chosen today. The aspect tolerance between the grid and the real ring is a crossing angle between 60 and 120 degrees (property XANG).

## 5. Planning

### 5.1 Zones in the plan

`DesignPlan` gains `zones`, a list of `InterlaceZone`:

- `rings`: the first and last ring index it covers;
- `source`: `grid` or `loops` (section 3.6), with the loop parameters when it is `loops`;
- `columns` (`C`) and `rows` (`R`), for a grid zone;
- `ribbon_share` (`w` as a share of pitch) and `ribbon_style` (`single` or `double`);
- `breaks`: the break map for one wedge, repeated `B` times; or, equivalently, the template per sequence entry from which it is built;
- `signature`: the boundary signature every template in the zone shares;
- `frame`: `rails` or `anchors` (section 6);
- `zone_seed`.

A ring inside a zone gets `position_mode = "zone"` and a `zone` index. It has no motif sequence of its own. Serialised plans without `zones` load with none.

### 5.2 Composer rules

- A zone is eligible when the celtic category is enabled, it is not in ring 0, and the grid fits (section 4.3).
- `C` is a multiple of `2B` (rule P1). Rings in the zone take division counts that divide `C` so every cell holds a whole number of columns.
- A zone of more than one ring fits the rings' radii to `q^R`. The ring-width re-pick that landed in `8512118` (neighbours absorb a regenerated ring's width) is the mechanism to extend: the zone takes the depth it needs and the rings outside it absorb the difference.
- Regenerating any ring of a zone re-plans the whole zone from a new zone seed. The UI's ring selector shows the zone as one unit.
- Variety: a ring next to a zone with rails takes no seam base, because rails behave like a band's arcs (the "seam rings never stack" rule).
- Fallback chain for a zone that cannot be drawn at this size: fewer rows, then fewer columns, then a one-row twist, then ordinary rings with the safe band.

### 5.3 Templates and signatures

A template is a break layout over a block of `a` columns by `b` rows, plus a boundary signature: which grid edges on the block's four sides are open. Two templates may sit next to each other only when the edges they share agree. Rather than solve a tiling problem, each zone draws one signature from its zone stream and the composer only offers templates with that signature, so every pair of neighbours agrees by construction. This is a Wang-tile idea reduced to a single label per zone.

Signatures worth starting with:

- `open`: every block side is open. Strands pass freely between blocks; the zone reads as continuous knotwork.
- `closed_sides`: block sides round the ring are closed, radial sides open. Each cell becomes its own knot stacked across the zone's rows.
- `closed`: every block side closed. Each block is a separate knot that touches its neighbours only where the planner adds a shared vertex (used by the cell-local knots of section 7.1).

### 5.4 Seeding

The break map, signature and template picks come from `ring_stream_seed(zone_seed, first_ring, "zone")` so they are identical in every wedge; per-cell variation inside a zone is not allowed, because every strand crosses cells.

## 6. Connecting a zone to its neighbours

A zone must join the design's one structure, and the space between its outer turn-backs and the next ring must not become a face that runs round the centre.

### 6.1 Rails (default)

The zone draws an inner and an outer rail: arcs near its boundaries, drawn as seams like `band`'s arcs. Every boundary turn-back's apex is placed exactly on its rail as a shared vertex, computed from the same grid values as the rail (the exact-vertex rule of side touch). The rails then do the job the band's arcs do: neighbour rings reach them through overflow, the final touch pass, or stems. The zone declares zero overflow, like every seam motif, so the resolver never pulls it back.

Rails are the standard frame for Celtic panels (five of the twelve references), they decouple the zone from whatever is next to it, and they need no new resolver logic. They are the default (decision 2026-10-12).

A woven-loop zone has no turn-backs: its loops are closed. Its outer loop tips and inner loop bases touch the rails at exact shared vertices instead, or, with no rails, are left as anchors (6.2) or reached by the neighbour ring's overflow and stems like any petal tip.

### 6.2 Anchors (second option, stricter coupling)

No rails. The outer turn-back apexes are exposed as anchors, and the outward neighbour ring is planned to meet them: its division count equals the number of apexes (or a divisor of it), its position (`centre` or `divider`) is chosen so its motifs line up with the apexes, and its bases are planned with inward overflow so each one touches an apex. A petal rising from each loop of the knot below is the intended look.

This is a cross-ring constraint the composer does not have today: a ring's division count and position mode are dictated by the ring inside it. It needs the same anchor mechanism as the roadmap's fillers (roadmap section 6.1), plus a composer rule that plans the ring outside a zone with `anchors` against the zone's apex positions. It should come after rails work.

### 6.3 The centre

A zone never covers ring 0. The centre of a Celtic design is a **rose knot**: `B` loops round the centre, each interlaced with its two neighbours, drawn by the same ribbon code with its own small grid. It closes off the centre as the seam band does today and is a candidate for the roadmap's `centre` role.

## 7. The Celtic vocabulary

### 7.1 Level 0: knots inside one cell

Self-contained knots, each its own small grid with the `closed` signature, used as bases or slot children. They need ribbons and alternation but no cross-cell agreement, so they are the first thing to build.

| Motif | Shape | Roles | Contact |
|---|---|---|---|
| `triquetra` | Three pointed loops interlaced round a centre, optionally with a circle woven through them | base, slot | As a base, its two outer loop tips sit on the side-touch vertices. |
| `solomon` | Two closed loops interlinked, four crossings | base, slot | Side touch at `mid`. |
| `quaternary` | Four loops round a square centre (shield knot) | base, slot | Side touch at `mid`. |
| `heart_knot` | A single strand forming a heart with a loop crossing at its base | base, slot | Side touch at `mid`. |
| `triskele` | Three spirals from a centre, each ending on its own earlier turn (the `curl` closure rule) | slot | Island. Not interlace, but chiral and Celtic. |

### 7.2 Level 1: single-ring bands

One-ring zones. Strands cross cell edges as paired seam ends (the two outlines of a ribbon), so the seam rule extends from one end per side to a set of **ports** per side: radial, tangent, ribbon width and the parity bit. The zone planner computes them, so neighbouring cells always agree.

| Motif | Shape |
|---|---|
| `twist` | Two strands crossing once per column: the simplest plait. |
| `plait` | Three or four strands, every crossing open. |
| `running_loop` | A plait with alternate breaks, giving a chain of loops interlaced with a running strand. |
| `chain` | Interlinked rings, each circle linked with its two neighbours. |
| `arcade` | Interlaced arches: each arch spans two cells and passes over one neighbour arch and under the other. |
| `double_spiral` | S-spirals linked end to end (non-interlace, chiral). |
| `key` | Celtic key pattern: diagonal fret corridors. Straight lines are allowed only because none is radial or concentric (the roadmap's art deco rule). |

### 7.3 Level 2: knotwork across rings

Multi-ring zones with templates and signatures (section 5). This is where knots span two or three rings and strands travel between them. Rings inside the zone stop being independent; the zone is planned, drawn and regenerated as one.

### 7.4 Level 3: weaving with other categories

Mixed designs are allowed (decision 2026-10-12): a zone can sit among botanical and geometric rings, and the composer treats its rails like a band's arcs for the variety and seam-stacking rules.

- **Woven layered ring.** A layered ring (aesthetics spec section 5) where the back petals weave with the front petals instead of always lying behind them. Front and back petals with an `echo` already form ribbons (outline plus echo); at each place a back ribbon crosses a front ribbon, the over and under alternates instead of the front always winning. This reuses the layered ring almost entirely: the cut is applied per crossing with the alternating assignment. It is the cheapest way to show interlace inside a botanical design, and works whether or not the celtic category is enabled.
- **Anchored neighbours** (section 6.2): botanical rings planned to rise from a knot's loops.

## 8. Assembly and validation

### 8.1 Pass one

A zone is drawn as one unit when the assembler reaches its first ring: break map, strand walk, alternation, centrelines (cubic segments in grid space with fixed tangents: plus or minus 45 degrees at crossings, parallel to the break at turn-backs), conformal map, ribbons, cuts, rails. Its paths are placed with role `base` for ribbon outlines and rails, and `detail` for double-line centre lines. Geometry is computed for the whole zone (strands cross wedge borders); QA asserts the result is `B`-fold symmetric, and `snap_to_ink` merges float noise at wedge borders as it does for every placed path.

### 8.2 Pass two

Zones declare zero overflow and are never regenerated by the resolver. Neighbouring rings resolve against the zone's ink as final, exactly as they do against a seam ring. A floating zone (rails not reached) is repaired on the neighbour's side through the existing fallback chain.

### 8.3 Analyzer and validator

- The analyzer accepts a zone instance as a seam instance (ports at the zone's cell edges are seam ends).
- After cutting there are no crossings, so the analyzer's crossing rule applies unchanged.
- The validator needs no change: T-junctions are touches, ribbons are faces, and alternation prevents encircling faces.

### 8.4 New QA properties

| Name | Check |
|---|---|
| ALT | Every strand alternates over and under along its whole length. |
| PAR | Rotating by one wedge maps every over crossing to an over crossing (rule P1). |
| CLOSED | Every strand is a closed loop with at least one crossing. |
| RIB | Every ribbon face and every background gap holds a pen and has `min_white_space` across it. |
| XANG | Every crossing angle on the page is between 60 and 120 degrees. |
| RAIL | Every boundary turn-back apex is an exact vertex of its rail (to 1e-9). |
| CUT | Every cut point is a vertex of the over ribbon's outline (already a layering check). |

The corpus gains celtic-only and celtic-plus-botanical designs, with at least a quarter of the eligible rings forced into zones.

## 9. Phasing

Each phase ends with the automated gates and a visual review against the Celtic references, as the aesthetics project does. The order follows the references: woven loops come before grid knotwork because they are the commoner structure and need no grid.

1. **Phase C1, the weave pipeline and cell knots:** `motifs/interlace.py` (strands, alternation, ribbons), the shared `occlude` helper extracted from `layering.py`, the `chiral` flag, and the Level 0 knots. The celtic checkbox turns on with these plus the safe band, with ring 0 still a band.
2. **Phase C2, woven loops:** loop zones spanning several rings (section 3.6), rails, the rose-knot centre, and the woven layered ring (7.4), which reuses the same pipeline inside botanical designs. Needs the composer to plan a zone across rings, so the zone plan, radius handling and whole-zone regeneration of section 5 land here, without the grid.
3. **Phase C3, grid bands:** one-ring grid zones, ports and parity, the conformal grid, the Level 1 bands.
4. **Phase C4, grid knotwork across rings:** multi-ring grid zones, templates and signatures.
5. **Phase C5, anchored neighbours** (6.2).

## 10. Risks

- **Loop zones are large.** A woven-loop zone spans several rings and is regenerated as one, so it removes those rings from per-ring regeneration. The UI must show this clearly.
- **Ring sizes.** The conformal grid ties ring depth to radius. Small designs or many thin rings may leave no ring that fits a zone, so celtic designs may need fewer, deeper rings than other categories.
- **Division counts.** Rules P1 and P2 and the grid fit restrict division counts. With `vary_divisions` off, a `num_divisions` whose per-wedge column count is odd forces two columns per cell or no zone.
- **Exactness at cuts.** The layering work hit float-noise failures at shared vertices (`docs/motifs.md`, traps). Ribbons multiply the number of cut points, so the shared `occlude` helper must use the same exact-vertex insertion.
- **Colouring appeal.** Long ribbon faces are tedious to colour. The double-line style and the `ribbon_share` range are the levers; the visual review decides.

## 11. Decisions (2026-10-12)

1. Rails are the default zone frame; anchors come later (Phase C5).
2. Single ribbons are the default; double-line is an option.
3. Celtic may share a design with other categories. This can be revisited.
4. Order: the weave pipeline and cell knots first, then woven loops together with the woven layered ring, then grid knotwork. Reason: five of the twelve Celtic references are built mainly from woven loops, and the woven layered ring brings interlace into botanical designs for almost no extra work once the pipeline exists.
5. Celtic references are in `examples/` (section 1.1).
