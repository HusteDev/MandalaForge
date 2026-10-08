> Note: the smart-pattern layer described here was retired on 2026-10-07 in favour of [docs/motifs.md](motifs.md).

# Motif Inventory (from `examples/`)

Source: visual analysis of 20 reference designs in `examples/` (48 files; the
sample covers every distinct style present — coloring-book line art, henna /
mehndi, Indian folk, art deco, flat-colour vector, and painted mandalas).

Purpose: identify pattern elements worth adding to `smart_patterns/`, and
separate them from the 21 patterns already registered.

Read alongside [smart-patterns.md](smart-patterns.md) for the cell contract and
[pattern-category-audit.md](pattern-category-audit.md) for current coverage.

---

## 1. What the corpus is actually made of

Across all 20 designs, the motif vocabulary is smaller than it looks. Almost
every ring is one of ~20 shape families, and the apparent richness comes from
four things the current engine does not do:

1. **Nesting** — a large silhouette is a *frame* that contains a smaller motif.
2. **Texture fill** — hatch, ribs and bead rows inside an outlined shape.
3. **Line-weight hierarchy** — heavy silhouette, medium sub-shape, hairline fill.
4. **Non-circular ring edges** — the ring's own outer boundary is scalloped or
   pointed, not a circle.

Points 3 and 4 are engine-level, not pattern-level. See §4.

---

## 2. Motifs already covered

These map cleanly onto registered patterns and need no new work:

| Motif in corpus | Covered by |
|---|---|
| Radiating straight spokes / ray burst | `smart_sunburst` |
| Simple pointed petal | `smart_petal` |
| Leaf with midrib | `smart_leaf` |
| Swag / drape hanging from a carrier | `smart_scallop_band` |
| Wavy stem running around the ring | `smart_vine_band` |
| Stacked chevrons | `smart_chevron_stack` |
| Concentric diamond | `smart_diamond` |
| Triangle picket row | `smart_triangle_band` |
| Star point | `smart_star_point` |
| Stepped / ziggurat block | `smart_stepped_band` |
| Half-shell fan | `smart_deco_shell`, `smart_fan` |
| Concentric arc stack | `smart_ripple_stack` |
| Interlacing / plait | `smart_laced`, `smart_braid_knot`, `smart_twist_band` |
| Meander border | `smart_greek_key` |

Notably, **`smart_greek_key` and `smart_braid_knot` appear in none of the 20
references.** Celtic interlace is a category the corpus does not use. That is
worth knowing before investing further there.

---

## 3. Missing motifs, ranked by frequency in the corpus

### Tier 1 — appears in most designs; highest value

#### 3.1 Teardrop / paisley (*boteh*)
Seen in: `istockphoto-1412136230`, `istockphoto-1305138930`,
`Screenshot 2026-08-21 224234`, `1000_F_151122547`, `black-white-...-feminine`.

An asymmetric drop: round at the base, drawn to a tip that curls to one side.
The single most common non-petal motif in the corpus and completely absent from
the registry.

Cell-space sketch: base arc centred on `(radial≈0.25, angular=0)`, two side
curves converging on a tip near `(0.9, ±0.15)` with the tip offset off-axis.
Mirror the pair across the centreline so the cell stays bilaterally symmetric —
individual drops are asymmetric, the cell is not.

Contract note: base sits on the inner boundary, tip crosses the outer boundary
or terminates on a spine vector. No floating.

#### 3.2 Spiral / volute / curl
Seen in: `61vqE83EJGL` ("Southern Lotus" — built almost entirely from volutes),
`istockphoto-1412136230` (paired S-scrolls between every petal),
`1000_F_151122547` (spiral fringe ring), `Screenshot 2026-08-21 224234`.

Nothing in the registry curls. This is the largest single stylistic gap.

Cell-space sketch: Archimedean spiral sampled as a polyline, `r = a + bθ`,
anchored so the *outer* end of the curl lands on a boundary or on a stem
vector, and the inner end terminates in a closed eye. Pair them as
mirror-image S-scrolls either side of the centreline.

Contract note: the free inner end is the problem — terminate it by closing a
small eye loop that touches the spiral's own second turn, so the endpoint is on
real ink.

#### 3.3 Bead / dot rows (pearl string)
Seen in: `leaf-flower-petal-...-228503117` (full bead ring),
`Coloring-for-kids-mandalas-71763` (ball terminals),
`Screenshot 2026-08-21 224234` (dotted outlines), `istockphoto-1412136230`,
`1000_F_151122547` (circle-in-circle ring).

The engine currently emits only line vectors — it has no punctuation element at
all. Bead rows are the cheapest possible density and rhythm, and every hand-drawn
reference uses them.

Cell-space sketch: N small circles spaced along a carrier polyline. Two
variants worth having: *bead ring* (beads along an arc at constant radial) and
*bead-and-reel* (bead alternating with a short bar).

Contract note: beads must be tangent to (or centred on) the carrier so they
touch ink. A row of free-floating circles violates the contract — the carrier
must be drawn.

#### 3.4 Radial hatch / rib fill
Seen in: `istockphoto-1441875679` (rib fans inside every petal),
`il_1080xN.2078226054` (dense arc hatch in shells),
`a-black-color-...-2T06C84`, `istockphoto-1305138930` (leaf veining).

A set of short parallel lines filling an outlined shape, converging on a point
or following the shape's spine. This is what makes the references read as
"detailed" without adding new outlines.

Cell-space sketch: given a host outline, emit `k` lines from a focus point to
sample points along the outline. `k` scales with `complexity`.

Contract note: every hatch line has both ends on real ink (focus + outline), so
this is contract-friendly — but it needs the host outline to exist. Best
implemented as a **modifier** (§5), not a standalone pattern.

#### 3.5 Nested outline / echo offset
Seen in: nearly every reference. `coloring-mandala-difficult-3` (nested
diamonds and triangles), `il_1080xN.2078226054`, `mandala-pattern_1308-34434`,
`ornate-mandala-...-warm-tones`.

An inset repeat of the host shape's own silhouette, 1–3 times.

Also best implemented as a modifier. It is the highest ratio of visual payoff
to implementation cost in this whole document.

### Tier 2 — common; clear individual value

#### 3.6 Ogee / lotus arch (onion-dome petal)
Seen in: `hand-drawn-...-tribal-2XTGFGD`, `indian-mandala-line-art`,
`7119lCmJcrL`, `ornate-mandala-...-warm-tones`, `istockphoto-1412136230`.

Distinct from `smart_petal`: the sides carry an S-curve (concave near the tip,
convex at the shoulder) meeting in a sharp cusp. This is the characteristic
Indian/Islamic petal and the corpus uses it far more than the plain lens petal.

Cell-space sketch: two cubic-ish polylines from `(0, ±0.5)` bulging outward to
`(0.55, ±0.75)` then turning concave to meet at `(1.0, 0)`.

#### 3.7 Vesica / interlocking circle lattice
Seen in: `il_1080xN.2078226054` (outer band of overlapping circles),
`istockphoto-845946480` (entirely overlapping vesica petals).

Overlapping circles whose intersections form pointed-oval lenses. Reads as
"flower of life" and is a whole visual language the registry lacks.

Contract note: intersections are the point of this motif, so it needs
`min_white_space` tuning — the lens slivers near the crossings are small by
design and will trip the current rejection rule.

#### 3.8 Cusped / foliated arch (multifoil)
Seen in: `Coloring-for-kids-mandalas-71763` (outer silhouette),
`61vqE83EJGL`, `black-white-...-feminine`.

A run of arcs meeting in outward-pointing cusps. Related to
`smart_scallop_band` but the opposite orientation: a scallop *swags downward*,
a foliated arch *bulges outward* with sharp cusps between lobes.

#### 3.9 Sawtooth / zigzag ring
Seen in: `Screenshot 2026-08-21 224327` (several sawtooth rings),
`1-23-10-7-4-15-50m`, `7119lCmJcrL`.

`smart_chevron_stack` is close but stacks chevrons radially. What the corpus
uses is a continuous zigzag *around* the ring — one tooth per cell, meeting the
neighbouring cell's tooth at the side boundary.

Contract note: this is a natural side-port pattern — left port and right port
at the same radial, apex on the centreline.

#### 3.10 Stamen / ball-tipped antenna
Seen in: `istockphoto-1441875679` (stamens with circle tips),
`hand-drawn-...-tribal-2XTGFGD` (ball-tipped spokes),
`Coloring-for-kids-mandalas-71763` (ball terminals on outer points),
`istockphoto-1305138930`.

A thin stem ending in a small filled or outlined circle. Used to fill the
awkward wedge between larger motifs — exactly the gap the current generator
tends to leave empty.

### Tier 3 — present, lower frequency

| Motif | Seen in | Note |
|---|---|---|
| Crescent / lune | `61vqE83EJGL`, `mandala-pattern_1308`, `pngtree-simple` | Trivial to build; pairs well as a filler |
| Heart | `colorful-geometric-...-heart-motifs`, `TheKaleidoscope` | Niche but explicitly requested by one whole style |
| Trefoil (three-lobed cusp) | `Coloring-for-kids`, `ornate-...-warm-tones` | Special case of 3.8 |
| Feather / plume | `istockphoto-1305138930`, `black-white-...-feminine` | Spine + barb comb; combine 3.4 with a leaf |
| Curved checker grid | `coloring-mandala-difficult-3` | Partly covered by `smart_prism_lattice` |
| Rope / bead-and-reel twist | `1000_F_151122547` | Variant of `smart_twist_band` + 3.3 |

---

## 4. Engine-level observations

These are not new patterns. They are structural differences between the corpus
and the current generator, and they limit how much any new motif can help.

### 4.1 Rings are circular; the corpus's often are not
`coloring_generator.py:19` states plainly: *"All rings are circular (no polygon
support)"*. But in `coloring-mandala-difficult-3`, `istockphoto-1441875679` and
`TheKaleidoscope`, the ring's outer edge is itself a star or petal silhouette,
and the motifs inside are clipped to that shape. This is the single biggest
reason generated output reads as "generated" rather than drawn.

### 4.2 Uniform stroke weight
`coloring_generator.py:186` computes one `base_stroke` for the entire design
from `num_divisions`. Every strong reference uses at least two weights and the
best use three: heavy silhouette outline, medium interior shape, hairline
texture. Adding a per-element weight tier would improve perceived quality more
than any single new motif.

### 4.3 One division count for all rings
`num_divisions` is global. The references routinely change count between rings
(e.g. 8 petals outside, 16 beads inside) and, just as often, offset adjacent
rings by half a cell so motifs interlock. `istockphoto-1441875679` and
`coloring-mandala-difficult-3` both do this.

### 4.4 No overlap between rings
The corpus layers rings like shingles — petals from an outer ring pass *over*
the ring boundary and sit on top of the inner ring. The current
`MAX_OVERSHOOT_PX` bleed is a hand-drawn overshoot, not deliberate layering.

### 4.5 Density ramps
`Screenshot 2026-08-21 224327` and `1-23-10-7-4-15-50m` both ramp detail
density from fine at the centre to bold at the rim. Complexity is currently a
flat per-pattern parameter.

---

## 5. Recommended shape: modifiers, not just patterns

Four of the highest-value items above (3.3 bead rows, 3.4 hatch fill, 3.5
nested outline, and arguably 3.10 stamens) are not standalone cell patterns —
they decorate a host shape. Adding them as 4 more entries in
`SMART_PATTERNS` would undersell them badly.

A `decorate(context, vectors, style)` step applied to an existing generator's
output would multiply the existing 21 patterns rather than add to them, and
every generated line already terminates on real ink, so the cell contract holds
by construction.

Suggested order of work:

1. Nested outline modifier (§3.5) — cheapest, applies to all 21 existing patterns.
2. Radial hatch modifier (§3.4).
3. Bead row modifier + standalone bead ring (§3.3).
4. Teardrop / paisley (§3.1) and ogee arch (§3.6) — botanical.
5. Spiral / volute (§3.2) — new sub-family; the largest stylistic gap.
6. Stroke-weight tiers (§4.2) — engine change, high payoff.
