# Motif and Decoration Roadmap

**Status:** Draft plan. Open questions answered by the user on 2026-10-12 (section 9). Nothing here is built.

**Date:** 2026-10-11, revised 2026-10-12

**Scope:** What to add to the motif engine after the motif aesthetics project (`docs/superpowers/specs/2026-10-09-motif-aesthetics-design.md`). That project already covers the reshaped petal, leaf, scallop, band, stem and diamond, the new teardrop, rounded petal, heart, curl, bead and spike, the five embellishments (echo, veins, fan, dot, beads), layered rings, seam ends and two line weights. None of those are re-planned here. Celtic is planned separately in `2026-10-11-celtic-interlace-design.md`, because it needs a different neighbour model.

Every item below is written against the rules the engine already enforces: rings and dividers are never ink, every open end lands on ink, every base joins one structure, base symmetry `B`, contact priority side > overflow > stem, and the validator is the authority. An item that needs an engine change says so.

## 1. What is still missing from the references

After the aesthetics project, comparing the engine's vocabulary with `examples/` and `docs/motif-inventory.md` leaves these gaps, in order of how often they appear:

1. **Small fillers in the V gaps.** Base-height touch leaves a V-shaped gap between neighbouring petal tips. The references fill it with a stamen (a stem with a ball tip), a small drop, a dot, or a short spike (`istockphoto-1441875679`, `hand-drawn-...-tribal-2XTGFGD`, `Coloring-for-kids-mandalas-71763`). The engine leaves it empty or fills it with a stem.
2. **Ring trims other than scallop, band and beads.** Sawtooth rings, cusped (outward-pointing) arcades, vesica chains and dotted borders carry most of the "busy" look of the denser references (`Screenshot 2026-08-21 224327`, `il_1080xN.2078226054`, `istockphoto-1412136230`).
3. **Florets inside larger shapes.** A small complete flower (a dot with four to eight tiny petals) nested inside a big petal or at the centre of a band lens is one of the most common slot fillings in the references. The engine's slot children are diamond and, after phase 3, bead and small petals.
4. **Interior textures beyond veins and fan.** Arcs across the tip of a petal (a cap band), parallel hatching, a dotted inner border, and a scalloped echo.
5. **A real centre.** Ring 0 can only be a seam motif (band or scallop) because it must close off the centre. Every reference has a designed centre: a rosette, a star, a circle with a dot, a small lotus.
6. **Silhouette and weight.** The outer edge of the strongest references is a strong petal or star silhouette at a heavier weight than everything inside it.
7. **Art deco and abstract have no motifs.** Their checkboxes stay disabled.

## 2. Principles for everything in this roadmap

- **Reuse mechanisms before adding them.** Most items are a new generator inside an existing archetype (enclosing outline, seam motif, slot child, attachment) or a new embellishment. Engine work is limited to section 6.
- **Fillers are attachments or slot children, never free-floating bases.** A filler that is not tied to ink is a floating base and fails validation. A V-gap filler hangs off the side-touch vertex or sits on the inward ring's ink.
- **Every new seam motif follows the seam rules exactly.** Its seam radials come from `ring_rng`, it declares zero overflow, it fills its position in every sequence entry, and it never stacks on another seam ring.
- **Each phase ends at a visual review gate**, as the aesthetics project does: automated gates green, then about twelve finished designs and their QA overlays reviewed before the next phase starts.

## 3. New motifs

### 3.1 Fillers (highest value)

| Motif | Category | Kind | Roles | Positions | Touch heights | Accepts | Notes |
|---|---|---|---|---|---|---|---|
| `stamen` | botanical | open + closed tip | attachment, base (divider) | divider | none | none | A curved stem from a declared anchor ending in a closed circle (the ball). As a divider base in a `base`-height side ring, its stem starts exactly on the shared side-touch vertex and rises into the V gap; the ball floats at the end of the stem, so the stem's free end is closed by the circle it lands on. Variants: one ball, or a trident of three stems with balls. |
| `drop` | botanical | enclosing | attachment, slot | divider, centre | none | echo, dot | A small teardrop hanging point-first from an anchor vertex (a petal tip, a side-touch vertex). Its point is the anchor vertex itself, so it is tied by construction. This is the "drops hanging off tips" item the aesthetics spec put out of scope. |
| `crescent` | botanical | enclosing | slot, base (divider) | centre, divider | base | echo | Two circular arcs sharing their ends. As a divider base it cups the V gap with its horns on the two side-touch vertices. |
| `floret` | botanical | enclosing set | slot | centre | none | none | A dot ringed by 4 to 8 tiny rounded petals that touch the dot, drawn in page space so it looks round. Fits inside a petal's slot, a band lens or a heart. It is an island of its own and joins nothing, as slot children may. |

**Engine need:** `stamen` and `drop` need an *anchor* other than the base point: a declared vertex of the host or of the ring's side-touch vertex. Section 6.1.

### 3.2 Ring trims (seam motifs)

| Motif | Category | Shape | Notes |
|---|---|---|---|
| `sawtooth` | geometric | One tooth per cell: two straight or slightly concave sides from the seam ends `(r_base, ±1.0)` to an apex on the axis; teeth meet at the seams. Optional second, inset tooth line at complexity 0.6 and above. | Direction (outward or inward) from `ring_rng`. Needs a tie to the inward ring, as `band` uses its lens: the tooth apex (inward variant) or a stem from each seam vertex. |
| `arcade` | geometric | Outward-pointing cusped arches: each cell is a pair of circular arcs meeting in a cusp on the axis, ends on the seams. The inverse of `scallop`. A trefoil variant adds a small lobe at each cusp. | `istockphoto-1305138930`, `Coloring-for-kids-mandalas-71763`. |
| `vesica_chain` | geometric | A row of circles that overlap their neighbours by a drawn share, so every overlap is a pointed lens. Each circle is centred on a divider (so it belongs to two cells) and is drawn as two halves meeting on seam ends at angular ±1.0 on its top and bottom. | The overlap lens must hold a pen: the overlap share has a floor computed from `min_white_space`. Reads as "flower of life" (`il_1080xN.2078226054`, `istockphoto-845946480`). |
| `wave` | abstract | A single sine or S-curve running round the ring between two optional arcs, crossing the axis once per cell. | First abstract motif. Must cross or touch ink in every cell, otherwise it forms an encircling face; the plain version is always paired with its arcs. |
| `rope` | geometric | Short diagonal ribs between two arcs, every rib curved, all leaning the same way. | `1000_F_151122547`. Rotationally symmetric but not mirror-symmetric: see the note in 3.6. |

### 3.3 Petal family additions

| Motif | Category | Shape | Roles | Touch heights | Accepts |
|---|---|---|---|---|---|
| `ogee` | botanical | Onion-dome petal: convex shoulders, concave sides, a long sharp tip. The lotus `petal` already has a flare; `ogee` pushes the concave run to more than half the length, with a narrow neck. | base, slot, back | base, mid | echo, veins, fan, dot, cap |
| `tulip` | botanical | Three-lobed cup: a centre lobe and two outer lobes that overlap it, as one outline with interior lines where the outer lobes pass over. | base (centre), slot | mid | echo, dot |
| `paisley` | botanical | An asymmetric boteh (round base, tip curled to one side). Placed as a mirrored pair across the axis so the cell stays symmetric; the pair touch at their bases. | base (centre) | base | echo, dot, beads-on-outline |
| `feather` | botanical | A leaf outline whose interior is a comb of barbs from a central shaft. Built as `leaf` plus a new `barbs` embellishment, so it costs one embellishment rather than one motif. | (as leaf) | | |
| `shell` | art_deco | A half-disc or fan shell with ribs converging on a hinge at its base, sitting on radial 0. The fan embellishment drawn at full size as the motif itself. | base, slot | base | echo, cap |

### 3.4 Geometric fillers

| Motif | Category | Shape | Notes |
|---|---|---|---|
| `kite` | geometric | A diamond that is a base, not only a slot child, with its side vertices on the side-touch vertices. | Cheap: the diamond generator with side-touch placement. |
| `star` | geometric | A small 4- to 8-point star, page-space round, as a slot child. | Slot island, like `floret`. |
| `lattice` | geometric | A curved checker: two or three arcs crossed by two or three curved (never straight) cross-lines, inside a closed host. | Only as an interior fill on large hosts. Straight radial lines read as scaffolding, so every cross-line is bowed. |

### 3.5 Art deco and abstract starter sets

These turn on two disabled categories with the fewest motifs that can carry a whole design. Each category needs at least one `spans_cell` seam motif (for ring 0) and one side-touching base.

- **art_deco:** `sunburst` (rays from a hub arc to an outer arc, the fan generator at ring scale, seam), `stepped` (a ziggurat silhouette, side-touching base), `shell` (3.3), `chevron` (nested V bands, side-touching base), `keystone` (a tapered arch, base), and `faceted_kite` (a long diamond on the axis with an inset diamond, `examples/deco-rays-diamonds-16.png`). The category follows the definition in 3.7.
- **abstract:** `wave` (3.2), `ripple` (concentric arcs inside a closed host, as an embellishment on a `blob`), `blob` (a smooth closed shape with seeded control points, side-touching), and `orbit` (two offset circles sharing a tangent vertex).

### 3.6 Chirality note

`rope`, `paisley` placed singly, spirals and all interlace are rotationally symmetric but not mirror-symmetric. The engine today assumes every motif is mirror-symmetric about its axis (back motifs must be, and authors mirror half an outline). Chiral motifs need a registry flag, `chiral: True`, which the composer reads to keep them out of the back role and to give every cell of the ring the same handedness. The flag is shared with Celtic.

### 3.7 What art deco means in this engine

Art deco is defined by construction rules, not by a list of shapes, so any motif in the category can be checked against them. `examples/deco-rays-diamonds-16.png` is the reference.

1. **Line vocabulary.** Outlines are built from straight segments and true circular arcs only. No cubic S-curves, no spirals, no free-form curves. This is the opposite of the botanical rule (curves everywhere, corners only at tips).
2. **Corners are deliberate.** Every corner is a sharp vertex, with a turn of at least 30 degrees. A near-straight kink reads as a drawing error.
3. **Parallel line groups.** Lines come in groups of two or three at a fixed, tight spacing (the clearance between two detail lines). A new embellishment, `lines`, draws them: offset copies of one edge of the host, not an echo of the whole outline.
4. **Stepping.** A form may repeat as smaller copies stacked along its axis (ziggurat, stepped arch, nested chevrons), each step at a fixed ratio of the one before, drawn once per instance.
5. **Radiation from a local hub.** Rays converge on a hub inside the motif (a fan, a shell, a sunburst's hub arc), never on the mandala centre across a whole ring.
6. **The scaffolding rule.** No line may lie along a divider or the cell centreline for more than half the ring's depth, and no arc may lie at radial 0 or 1 across the whole cell. Straight radial lines inside a host and arcs that are not on the ring edges are allowed. This keeps the category from reading as the ring and division lines the engine never draws.
7. **Symmetry.** Every deco motif is mirror-symmetric about its axis, and the category prefers the `both` position mode, so centre and divider motifs alternate the way deco borders alternate large and small units.
8. **Ornament.** Embellishments allowed are `lines`, `cap`, `dot` and the inset copy (an echo whose corners stay sharp). `veins`, `fan` with curved rays, `eye` and scalloped echoes are not offered to deco hosts.

QA adds a DECO check for the category: no cubic segments, every corner at least 30 degrees, and rule 6 measured on the placed ink.

## 4. New embellishments

All follow the embellishment rules: own salted stream, dropped and counted when they do not fit, recomputed on every regeneration, ends inserted as vertices.

| Name | What it draws | Hosts | Kind |
|---|---|---|---|
| `cap` | One to three arcs across the host near its tip, each ending on the outline, parallel to the outer ring edge. Makes the "banded tip" in `istockphoto-1441875679`. | petal, ogee, rounded_petal, teardrop, shell | interior band; compatible with `veins` (veins stop at the lowest cap arc) |
| `hatch` | Parallel lines across the host perpendicular to its axis, spaced by `clearance_px("detail", "detail")`, ends on the outline. | leaf, teardrop, spike, kite | interior fill |
| `dotted_echo` | A row of floating detail circles along the inside of the outline instead of a continuous echo line. Spacing and diameter from the host's stream. | petal, teardrop, scallop lobe, arcade lobe | border |
| `scalloped_echo` | An echo whose line is a chain of small arcs, each pair meeting at a vertex. | petal, rounded_petal, heart | border |
| `barbs` | A shaft along the axis plus dense short side lines at a fixed angle. Turns a leaf into a feather. | leaf | interior fill |
| `lines` | Two or three offset copies of one edge of the host at the detail clearance, ends on the host outline. The art deco parallel-line group (3.7). | stepped, keystone, faceted_kite, chevron, shell | border |
| `eye` | A small spiral at the host's base whose inner end closes on its own earlier turn, as `curl` does. | teardrop, paisley, heart | point accent |

`EMBELLISHMENT_ORDER` grows to: `echo` or `dotted_echo` or `scalloped_echo` (at most one border), then `cap` or `lines`, then at most one interior fill (`veins`, `fan`, `hatch`, `barbs`), then `dot` or `eye`, then `beads`.

## 5. Ring and design level decorations

These are not motifs. They change how rings are composed.

1. **Designed centre (ring 0).** A new role, `centre`, for motifs drawn once in the middle of the design rather than once per cell: `rosette` (a floret at ring scale with `B` petals), `star_centre` (a `B`-point star), `lotus_centre` (one ring of side-touching petals around a circle), and `eye_centre` (concentric circles and a dot). This is one option alongside today's seam-ring centre, not a replacement: the composer picks between them per design. When a centre motif is picked, the innermost ring no longer has to be a seam ring: the centre motif supplies the closure and the connection that the seam band supplies today. Needs: a ring-0 mode in the composer, and the validator's structure root moves from "the component holding most of ring 0's bases" to "the component holding the centre motif".
2. **Three weights for any line.** Every line can be drawn at one of three weights: `heavy` (1.5 times the outline stroke), `outline`, and `detail` (0.6). A motif draws its lines with semantic weights as today (outline for its shape, detail for embellishments). The composer then applies a per-ring **emphasis** that can move any line up or down one step:
   - `silhouette`: the outer half of every base outline in the outermost ring goes `heavy`, giving the design a bold edge;
   - `ring`: every base outline in the ring goes `heavy`, used on one or two rings per design to make them read as structure (bands, rails, a Celtic zone's ribbons);
   - `fine`: every base outline goes `detail` and its embellishments stay `detail`, for a delicate ring between two heavy ones;
   - `none`: the semantic weights as drawn.
   Emphasis is drawn per ring from the style, at most one `silhouette` ring and at most two `ring` rings per design. A motif may also pin a line's weight (a `heavy` stamen ball, a `detail` rope rib) so emphasis never changes it. Clearances already take both lines' weights (`clearance_px`), so a heavy line automatically pushes neighbouring ink further away; the validator's pen test is unchanged and sees thicker lines only as smaller faces, so `RIB`- and `SLOT`-style checks are measured with real widths.
3. **Density ramp.** Complexity applied per ring instead of per design: `complexity_ring = complexity * ramp(ring_index)`, with the ramp shape (flat, rising to the rim, falling to the rim) drawn from the style. Affects embellishment counts, slot depth, and sequence length. `Screenshot 2026-08-21 224327` and `1-23-10-7-4-15-50m` both ramp.
4. **Fronts on dividers with the back in the centre.** The reverse layered ring the aesthetics spec put out of scope. The layering code already shifts a back onto dividers; this needs the mirrored case and the matching seam rule.
5. **Triple layering.** Three tiers of petals in one ring (front, middle on dividers, back in the centre again at a longer length). `istockphoto-1412136230` does this. Built on 4 plus the existing cut-and-insert code applied twice.
6. **Ring-pair motifs.** One motif drawn across two adjacent rings with the same division count (a long petal whose base is in ring k and tip in ring k+1, with the inner part acting as ring k's motif). Lower priority; Celtic zones (see the Celtic plan) need the same "rings planned together" mechanism, so build it there first and reuse it here.

## 6. Engine changes this roadmap needs

1. **Anchors.** A declaration gains `anchors`: named exact vertices (`tip`, `side_left`, `side_right`, `base`) that attachments can hang from. A ring in `side` mode also exposes the shared side-touch vertex as a ring anchor. `stamen` and `drop` hang from anchors; the assembler places the attachment so its first point is exactly the anchor vertex (no reach cast), which keeps the touch exact.
2. **Floating slot sets.** `floret` and `star` are islands made of several closed vectors. The analyzer already allows islands for slot children; QA needs a property that every part of a set holds a pen.
3. **The `chiral` registry flag** (3.6), shared with Celtic.
4. **Centre role and ring-0 planning** (5.1), including the validator's structure root.
5. **Three weights and emphasis** (5.2): `SmartVector.weight` gains `heavy` and a `pinned` flag; `RingPlan` gains `emphasis`; the assembler applies emphasis when placing paths, before clearances are checked; `clearance_px` already takes two weights.
6. **Per-ring complexity** (5.3): `MotifContext.complexity` becomes the ring's value; the plan stores the ramp.

## 7. Phasing

Each phase ends with the full `qa_patterns.py` tier, `qa_report.py --corpus` at 180/180, pytest green, and a visual review of about twelve designs.

1. **Phase A, fillers and anchors:** anchors (6.1), `stamen`, `drop`, `crescent`, `floret`, `kite`, `star`. This fills the V gaps and slots, the largest visible gap after the aesthetics project.
2. **Phase B, trims:** `sawtooth`, `arcade`, `vesica_chain`, plus embellishments `cap`, `dotted_echo`, `hatch`.
3. **Phase C, centre and weights:** the centre role and four centre motifs, the three weights with per-ring emphasis, the density ramp.
4. **Phase D, petal family and textures:** `ogee`, `tulip`, `paisley` (with `chiral`), `feather` via `barbs`, `scalloped_echo`, `eye`, reverse and triple layering.
5. **Phase E, new categories:** the art deco and abstract starter sets, then enable their checkboxes.

Celtic runs on its own track (see its plan) and shares only the `chiral` flag and the "rings planned together" mechanism with this roadmap.

## 8. QA additions

- `qa_patterns.py` covers every new motif in every position and role it declares, and every new embellishment on every host that accepts it, with the existing DET, MONO, ANG, SLOT, SEAM, TANG, CUT and EMB checks.
- **ANCHOR:** every anchored attachment's first point is exactly the anchor vertex, to 1e-9.
- **SET:** every closed part of a floating slot set holds a pen and keeps `min_white_space` from its siblings.
- **CHIRAL:** every cell of a ring with a chiral motif has the same handedness.
- The corpus gains art deco and abstract designs once Phase E lands, and every new motif and embellishment is placed at least ten times across the corpus.

## 9. Decisions (2026-10-12)

1. The designed centre is one option alongside the seam-ring centre (5.1).
2. Three weights are available for any line, not only the outer silhouette; per-ring emphasis decides where they go (5.2).
3. Art deco follows the formal definition in 3.7, with `examples/deco-rays-diamonds-16.png` as its reference.
4. Phases run in the order of section 7, fillers first.
