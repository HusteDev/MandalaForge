# Architecture

MandalaForge is a Flask app that generates SVG mandala colouring pages. A design is planned by the composer, drawn and placed by the assembler in two passes, and checked by the topology validator. The motif contract and the rules for authoring motifs are in `docs/motifs.md`.

## Runtime Flow

1. The browser sends `POST /generate` from `static/script.js`.
2. `app.py` parses and validates the parameters (`ring_divisions` and `ring_seeds` included) and builds a `DesignGenerator`.
3. `DesignGenerator` in `coloring_generator.py` computes the ring radii.
4. `Composer` in `composer.py` plans every ring into a `DesignPlan`, deterministically from the seed and without drawing anything.
5. `Assembler` in `assembler.py` runs pass one: it draws every motif of every cell in cell space (each generator adds its own embellishments, and a layered ring's centre bases are drawn as composites with the ring's back), places it on the page, and indexes the ink in an `InkIndex` (`placement.py`).
6. `resolver.py` runs pass two, rings innermost first, on one wedge of `360 / B` degrees, mirroring every change to the other wedges: overflow is pulled back and touched, reaches are drawn, and floating cells are replaced through the composer and the ring resolved again. A final touch pass and a design-wide crossing and contact check follow.
7. `DesignGenerator` renders every placed path as an explicit SVG `<path>` in a `ring-<index>` group, with a `data-role` of `base`, `slot`, `reach`, `back` (a layered ring's back outline) or `detail` (embellishment ink, a back's included). There is no `<use>` rotation: the design is `B`-fold symmetric, but every placed path is snapped onto the ink vertices it meets, so a mirrored copy is a rotation only up to float noise, and every touch must be the same vertex in both lines.
8. `TopologyValidator` in `topology_validator.py` analyses the assembled polylines, with the base mask, ring ids and overflow runs, and the summary goes into the response.
9. With `max_region_cap` on (it is off by default and opt-in, through the API's `max_region_cap` and the UI's "Limit large regions (slower)" checkbox, because the ladder makes generation several times slower; `qa_report.py` turns it on for every design), a valid design whose report has faces over the print-size cap climbs the repair ladder in `region_repair.py` before rendering: each oversized face set (host interior, background or open centre) gets its own step (detail inside the host, a background fill, or a rosette in the centre), then a re-roll of its ring, each step edited into a copy of the plan, re-assembled and re-validated from scratch, and kept only when the design stays valid with no more oversized area. The kept trial's plan, assembly and report replace the first ones, and its plan as it stood before assembly is kept as `DesignGenerator.source_plan`. `generate_from_plan` assembles such a saved plan without planning or running the ladder, so a repaired design replays exactly. With the cap on the ladder runs even for `generate(validate=False)`, so the SVG never depends on `validate`. `docs/motifs.md` gives the cap, the ladder and the rosette.
10. The API returns the SVG, the validation summary, the serialised plan and the ring seeds.

`POST /regenerate-ring` follows the same flow with one ring's seed replaced, and returns the whole document.

## Main Files

- `app.py`: Flask routes, parameter parsing and API response shape.
- `coloring_generator.py`: ring radii, orchestration of composer, assembler and validator (including the reassembly when a layered ring fails in pass two, and the repair ladder when the region cap is on), replay of a saved plan (`generate_from_plan`), SVG rendering, validation summary.
- `composer.py`: the plan model (`CellRecipe`, `CellEntry`, `RingPlan`, `DesignPlan`, all JSON-serialisable), seeded per-node streams (`node_seed`, `node_rng`), and `Composer`: base symmetry, division counts, position modes (`layered` included), motif choice, embellishment picks (`pick_embellishments`), slot nesting, a layered ring's back (`drop_back` to remove it), contact modes and routes, and the node fallback chain (`replace_node`).
- `assembler.py`: `Assembler` pass one, `PlacedNode` records that keep each node's recipe, seed, context and parent, the regeneration and commit machinery pass two uses, and the symmetry groups and mirroring methods.
- `resolver.py`: pass two. Overflow pull-back and touches, reach casting and drawing, the per-ring and design-wide contact checks, all on symmetry-group representatives.
- `placement.py`: pure geometry and indexing. `PlacedPath`, `trace` (page coordinates with per-coordinate cell radials), `path_overflow` and `boundary_crossing`, and `InkIndex` over a Shapely `STRtree`.
- `motifs/`: the motif library. `geometry.py` (cell space and `MotifContext`), `contract.py` (`build_instance`, `Declaration`, `MotifAnalyzer`), `slot_fit.py`, `embellish.py` (the embellishment pipeline), `layering.py` (the layered composite), `cache.py` (the per-design memo of generator calls), the category modules `botanical.py` and `geometric.py`, `fallback.py` (safe bands), and the registry in `__init__.py`.
- `region_repair.py`: the region-size repair pass. `classify_faces` and `face_sets` tie each oversized face to the plan entry behind it (host interior, background or centre, symmetric copies grouped), and `RegionRepair` climbs the repair ladder over `Trial`s (a plan, its assembly and its report), through the composer's plan-repair methods (`add_embellishment`, `add_slot_child`, `switch_to_both`, `raise_size_floor`, `reroll_ring`) and `DesignGenerator._trial`.
- `topology_validator.py`: exact planar topology QA, also used by the resolver to judge faces before it draws a reach or keeps a touch. It also holds the print-size cap (`PX_PER_INCH`, `max_region_in2`, `max_region_px2`).
- `templates/index.html`: controls and preview layout.
- `static/script.js`: parameter collection, API calls, preview rendering, ring selector, debug bar, gallery and print controls.

## Generation Model

The app creates circular rings only. `num_rings` sets how many; their radii come from `complexity` (even spacing below 0.1, seeded variable spacing above). Each ring is divided into equal angular cells, and each ring has its own division count, always a multiple of the design's base symmetry `B`.

### Composer

Every choice draws from a stream derived from `(seed, ring_index, sequence_position, tree_depth, position)`, so changing one ring's plan does not reshuffle another's. A design-level style is drawn once per seed: a subset of the enabled categories, which the composer favours 3 to 1 over the others rather than excluding them, and a preferred position mode.

**Base symmetry.** Also once per design, from its own design-level stream, `Composer.symmetry` fixes the base symmetry `B`, stored as `DesignPlan.base_symmetry`. With `vary_divisions` off, `B = num_divisions`. With it on, `B` is drawn from the divisors of `num_divisions` from 3 to 8 (`SYMMETRY_MIN`, `SYMMETRY_MAX`), weighted by their value. When there is none (11, 13, 17, 19, 22, 23), `B` is the largest divisor of `num_divisions` that is at least 3 and smaller than it (11 for 22), or `num_divisions` itself for a prime, so the vary path never gives 1. An explicit `ring_divisions` list gives the greatest common divisor of its counts, which may be 1; such a list is the only way the composer gives `B = 1`.

For each ring, innermost first:

1. **Division count.** `ring_divisions` when supplied; otherwise, with `vary_divisions`, `B * m` for a multiplier `m` drawn around `num_divisions / B`, scaled down toward the centre, with the count kept within 4 to 24; otherwise `num_divisions`.
2. **Sequence length.** A divisor of `divisions / B` from 1 to 4, with length 1 weighted 1 and the others weighted by `complexity`, so the sequence repeats whole in every wedge. Cell `i` uses `sequence[i % len(sequence)]`. With `vary_divisions` off every wedge is one cell, so every ring has a sequence of length 1.
3. **Position mode.** `centre`, `divider` or `both`, weighted toward the style's preference; `both` draws a `centre_share` from 0.45 to 0.75 and needs a 28px cell. Outside ring 0, `layered` joins them with weight 0.2 when a back motif fits the whole cell and a front can touch at `base` height (see Layered composite below); `force_position_mode` forces one mode wherever it is eligible.
4. **Touch height and side-touch radial.** A `touch_height`, `base` or `mid`, chosen from the heights every base in the ring supports, then one `side_touch_radial` from that height's range (0.08 to 0.2 for `base`, 0.35 to 0.6 for `mid`), drawn after the earlier ring-level draws so they are unchanged. A layered ring always touches at `base` height.
5. **Each entry.** A base motif per occupied position from the enabled categories that supports the position and the `base` role and passes the size gates at this cell's budget. Ring 0 uses `spans_cell` bases only. Each base gets its embellishments from its `pick:emb` stream (`pick_embellishments`: `clamp(floor(3 * (complexity - 0.2) / 0.8 + u), 0, 3)` names from those it accepts, at most one interior fill), and a seam motif's later entries copy entry 0's. `force_embellishments` (QA only) adds named embellishments to every accepting base's and back's picks, still keeping at most one interior fill. An enclosing motif with a `slot_estimate` and no interior fill may get a slot child (probability `complexity`, halving per level), nesting at most three deep. A layered ring's centre entries are drawn from the non-seam bases that touch at `base` height, and the ring gets one back motif, `RingPlan.back`, from its `pick:back` stream, with its own embellishments.
6. **Variety.** A ring avoids the base motifs of the canonical ring inside it, the one planned from the design seed, unless nothing else fits. Using the canonical ring means a design rebuilt from its seed plus its `ring_seeds` is exact. A ring beside a seam ring (`band` or `scallop`) never takes a seam motif, even when nothing else fits (the safe band applies then), and a substitute in `Composer.replace_node` follows the same rule against the current bases of the rings on both sides. A regenerated ring also takes no seam motif when the canonical ring outside it has one, so a single regeneration never stacks seam rings; two adjacent regenerated rings can still stack, since each reads only canonical neighbours (see `docs/motifs.md`, changes from user feedback).
7. **Contact mode and routes.** The ring's `contact_mode` is `side` when its bases share a touch height (ring 0 always is, and a seam motif counts at every height), else `overflow` when every base has inward overflow of at least 0.1, else `stem`. A `side` ring meets at shared side vertices and needs only a few inward contacts: overflow where a base has it, else one stem on its first node flagged `once_per_wedge`, which pass one draws once per wedge and at least `MIN_RING_CONTACTS` (3) times in the ring. An `overflow` ring gets no stems. A `stem` ring keeps the revision-1 rule: every base without inward overflow, `spans_cell` or an attachment gets a stem.

When assembly rejects a node, the composer replaces that node only. A floating base in a `side` ring first gets another side-touching base, then a stem; in other rings the stem comes first (available even under `force_motif`, since it changes no motif). Then comes another eligible motif, then the category's safe band. A substitution that leaves a ring unable to keep its mode downgrades it, and a once-per-wedge stem then becomes a per-cell one.

**Salted streams.** Draws come from streams seeded by CRC-32 mixing rather than from one shared generator. `salted_seed(seed, salt)` (`motifs/geometry.py`, using `zlib.crc32`) folds a salt string into a seed; `node_seed(..., salt)` and `node_rng` give a cell's node stream, and `ring_stream_seed(ring_seed, ring_index, salt)` gives a stream shared by every cell of a ring. The composer's picks use the salt `pick` (`pick:emb` for embellishments, `pick:back` for a layered ring's back), so they never share a stream with a node's drawing and adding a draw in one place leaves the others unchanged. Each embellishment draws from the node seed salted `emb:<name>`, and a layered ring's back from the ring stream salted `back`. The assembler gives each context a `ring_rng` seeded with the salt `ring:{motif}:{position}`, identical in every cell of the ring (seam motifs read their shared edge from it), while a generator's own `rng` stays the unsalted per-node stream.

### Assembler, pass one

Rings innermost to outermost, every cell and occupied position: the base is generated with its position's `MotifContext` (angular budget, radial limits from its overflow maxima, floor 0.0 in the innermost ring, the ring's `side_touch_radial` when the ring is in `side` mode, and the ring stream described under Salted streams), its declared slot is measured, the slot child is generated into that slot, and so on down the tree. A child that does not fit its cell's real slot is dropped from that cell and the child's recipe is marked `dropped`. Attachments draw nothing yet; their reach ends are recorded with their page position. A `once_per_wedge` attachment is recorded only in the cells `_draws_once_per_wedge` picks: the first cell of each wedge that holds the attachment's sequence entry, or, when that would give fewer than `MIN_RING_CONTACTS` (3) in the ring (`B` of 1 or 2), at least `ceil(3 / B)` per wedge, spaced among the wedge's cells that hold the entry. The choice depends only on a cell's place in its wedge, so symmetry groups stay whole; a wedge with fewer such cells than that draws one in each and can still fall short of three (an accepted limitation). Each instance is rotated to its cell, plus half a wedge for the divider position, and every path enters the ink index tagged with ring, cell, position, node and role. Each placed path is then snapped onto other ink (`snap_to_ink`): a vertex within `SAME_VERTEX_PX` (1e-6) of another ink's vertex becomes exactly that vertex, because cells rotated by an inexact angle (360 / 7 degrees) would otherwise meet their neighbours' side vertices only to float noise. A base that fails to generate is replaced through the composer up to three times.

**The motif memo.** Every generator call of an assembly (bases, slot children, attachments, a layered composite's front and back, and every pass-two regeneration) goes through `Assembler._call`, which answers it from the design's `MotifCache` (`motifs/cache.py`) when it has one; `compose_layered` gets front and back entries whose generators answer through the memo (`MotifCache.wrap`). `DesignGenerator.generate` and `generate_from_plan` each make a fresh memo, shared by the design's repair trials and dropped when the design is done; it is never module-global. A node's seed has no cell index, so every cell holding one sequence entry draws the same motif from the same context, and a repair trial draws its unchanged rings again: those repeats are answered from the memo. The key is the generator, the motif name, every other context field (pickled) and the exact states of `rng` and `ring_rng`; a hit returns a deep copy of the instance (or raises the stored error again) and leaves both streams as the real call left them, so the design is byte-identical with the memo on or off (`DesignGenerator.use_motif_cache`). It relies on generators being pure functions of their context (`docs/motifs.md`, Adding a motif).

**Where embellishments run.** Inside the generator, not the assembler: the context carries the recipe's `embellishments`, and the generator calls `apply_embellishments` after drawing its outline and before `build_instance`. Every regeneration (a pull-back, a commit) therefore redraws them from the host, and a dropped embellishment is counted in the instance and summed into `AssembledDesign.dropped_embellishments`. Detail-weight ink is placed with role `detail`.

### Layered composite

A layered ring's centre bases are composites (`motifs/layering.py`, spec 5). For each, `Assembler._generate` builds the back's context from the front's, with the whole cell on a divider, radial limits (0.0, 1.0) and the ring's `back` stream for its `rng`, node seed and ring stream, and calls `compose_layered`. It draws the front, draws the back once, shifts it onto both dividers, cuts away what the front's fill hides, makes every cut a vertex of the front outline, drops pieces too short to colour or in the notch below the side touch, checks the clearance to the front outside the touch discs of the cuts, and returns front and back as one instance whose back seam ends meet the neighbouring cell's halves exactly. Back outlines are placed with role `back`, which `resolver.STRUCTURAL_ROLES` (`base`, `back`) counts as structure; back detail ink is `detail`. A pull-back regenerates the whole composite, and the back, which depends only on the ring stream and fixed limits, is cut again against the narrower front. `docs/motifs.md` gives the steps and the rules a back motif follows.

**Failure path.** Any failure of the back or of the cut raises `LayeringError` (a `MotifError`). In pass one, `_place_ring` catches it, calls `Composer.drop_back(ring)` (which sets `back = None`, `back_dropped = True` and the ring's mode to `centre`, keeping the centre entries) and places the ring again without counting a replacement. In pass two only some cells of the ring are redrawn and the rest would keep the back, so a composite failure there, or a replacement that falls back to a safe band (which drops the back too), raises `LayeredRingFailed`. `DesignGenerator._assemble` catches it, drops that ring's back and assembles the whole design again, at most once per ring; a second failure of the same ring propagates. The back is always dropped for the whole ring, never one cell, since a neighbour's half would dangle.

### Resolver, pass two

Rings innermost to outermost. For each ring the inner ring's outward overflow is checked again against this ring's ink, then this ring's inward overflow, then its outward overflow, then its pending reaches, then the contact check. Floating bases are replaced, once per floating group's sequence entry, and the ring resolved again, up to three rounds; when a round replaces cells, the neighbour rings' facing sides get a fresh pull-back budget. When every ring is resolved, a final touch pass runs over every base's extreme vertex on each side that has a neighbour ring, then the design-wide checks run: no adjacent rings may still cross or crowd each other, and no base may float. Either failure raises `AssemblyError`, which the API returns as a 400.

**Symmetry groups.** Pass two resolves one wedge of `360 / B` degrees and mirrors every operation to the other wedges by rotation. `Assembler.symmetry_groups` puts cell `i` of a ring of `N` cells with cells `i + k * N / B`, same position and node path; the member in the first wedge is the group's representative (`is_representative`). Only representatives are resolved, and every predicate (crossing, crowding, landing, uncolourable faces) is judged on the representative, with every member's ink in the index. Pull-back counters live on the representative. Every change to ink is mirrored: `commit_group` commits a regenerated representative and a turned copy for each member, `mirror_insert` and `mirror_move` repeat a vertex insertion or move at the turned point, a resolved reach is copied to each member, and `snapshot` and `restore` undo a refused touch in the whole group. A turned copy differs by about 1e-14 from ink traced in its own cell, so `snap_to_ink` sets each mirrored vertex within `SAME_VERTEX_PX` of another ink's vertex exactly to it, as it does for every placed and committed path. The design-wide crossing check judges the representatives' ink only. With `B = 1` every node is its own group and pass two is the per-cell resolution of revision 1. `Assembler.symmetry` falls back to 1 for a hand-made plan whose rings do not repeat whole in every wedge.

## Positions, Overflow, Reaches and Contact

Ring boundaries and division lines are scaffolding. They are never drawn and nothing can land on them; the debug options `draw_rings` and `draw_divisions` show them as dashed grey guides only.

**Positions.** A cell has a `centre` position on its centreline and a `divider` position on its clockwise edge. Motifs are always authored centred on angular 0 and rotated by half a wedge for the divider. When a ring uses both, centre motifs get an angular half-width of `centre_share` and divider motifs get `1.0 - centre_share`, so they tile the cell and may touch but never cross.

**Contact modes.** A ring connects to the structure by side touch, by overflow or by stems, in that order of preference (its `contact_mode`). In a `side` ring every base draws to its full angular budget with exact vertices at `(side_touch_radial, ±angular_limits)`, which sits at the ring's touch height and leaves the outline tangent to the radial direction, so neighbouring motifs, from different sequence entries or in the centre and divider positions, meet at shared vertices and the ring is one connected band. `docs/motifs.md` gives the author's side of the rule.

**Overflow.** A motif may run past its ring's edges by its declared maxima, as a fraction of ring depth. The innermost ring never overflows inward. Overflow may touch neighbour ink at a shared vertex but never cross it, and it keeps `CLEARANCE_PX` (4px, twice the pen radius) from neighbour ink outside a touch disc of radius `max(min_white_space, 8px)` around its extreme vertex and around any vertex its path shares with other ink. The clearance applies to overflow geometry only (`path_overflow`, which ignores runs less than `OVERFLOW_EPSILON`, 1e-9, past the boundary); ink inside its own ring may lie close to a neighbour's overflow. A side that conflicts is pulled back by binary search over its radial limit, regenerating the node and its slot children from their stored seeds, at most four times; if nothing works the side keeps no overflow. Blame decides which side starts a pull-back (a crossing within `BOUNDARY_MARGIN_PX`, 0.5px, of a ring's boundary or past it is that ring's overflow), but a limit is only clear when the node crosses the neighbour ring's ink nowhere at all: the two rings' margins overlap, so a shape that merely moved a crossing out of its own margin would hand it to the neighbour, and two tips nestled into each other's rings would trade it until both sides ran out of pull-backs. The final touch pass moves an extreme vertex within 4px of neighbour ink onto it, whether or not it overflows, so a tip on the ring boundary meets the next ring, unless that would make the two rings cross or crowd each other, judged from both rings, or close a face too thin or small to colour. Shared vertices are never moved: a guarded tip is touched from the other side, by inserting its projection into the neighbour's ink and moving that vertex onto the tip.

**Reaches.** A reach starts on its node's own ink and casts in its direction. It lands at the first point within 4px of other ink, so it never runs beside ink in a gap no pen fits. A stem is bounded to the neighbour ring: an inward reach casts exactly to the inward neighbour ring's inner boundary, whatever its declared length, and never recasts toward the centre; a miss draws nothing and leaves the cell to the contact check. An outward reach casts its declared length. A reach shorter than a pen width collapses to a touch. A stem draws as a bow, an S-curve or a wavy line, and its amplitude is reduced until it keeps 4px from all other ink, down to a straight line; an inward stem never lands on ink of a ring further out. A reach that would close off an uncolourable face is not drawn.

**Contact.** A touch is an endpoint placed exactly on another path, with a vertex inserted into that path, so the validator sees a node of degree three. Every base in every cell must be connected to the structure: the component holding most of the innermost ring's bases. Slot children may be islands.

## Validation

There are two validation layers:

- `MotifAnalyzer` in `motifs/contract.py` checks each motif instance in cell space as it is built: open ends accounted for, limits respected, no crossing that leaves a sub-white-space gap, and a declared slot that really is clear of the motif's ink.
- `TopologyValidator` checks the assembled page: dangling ends, un-colourable faces (under 20px² or too thin for a 2px pen tip), floating open shapes, floating base motifs, overflow crossings into another ring, and lanes or regions that run the whole way around the centre. Snap-rounded linework can polygonize into a self-intersecting face; the validator repairs an invalid face with `make_valid` before measuring it, keeping every polygon part, so no face is lost.

With the region cap on (`max_region_px2(complexity)` passed to the validator), every face inside the mandala larger than `max_region_in2(complexity) = 1.25 - 0.65 * complexity` square inches at 72 px per inch is reported in `TopologyReport.oversized_regions`, a soft issue that never changes `is_valid`. The stats gain `num_oversized_regions` (0 with the cap off) and `largest_region_in2`, the largest face in square inches, measured either way. The repair ladder reads these faces; `qa_report.py --corpus` prints how many corpus designs keep one and the largest face, and fails when more designs keep one than its pinned ceiling.

The resolver judges candidate reaches and touches with the validator's own face rules, so pass two does not create the faces the validator would reject.

## API Response

`POST /generate` returns the following. This response is real (seed 1, two rings, eight divisions, complexity 0.7, botanical and geometric), abridged only in that the SVG is cut short. With `vary_divisions` off, `base_symmetry` equals the division count and each ring's `sequence` has one entry.

```json
{
  "params_string": "Seed: 1\nRings: 2\nDivisions: 8\nRing divisions: 8, 8\nComplexity: 0.7\nCategories: botanical, geometric",
  "plan": {
    "base_symmetry": 8,
    "rings": [
      {
        "centre_share": 1.0,
        "contact_mode": "side",
        "divisions": 8,
        "ring_index": 0,
        "ring_seed": 1,
        "sequence": [
          {
            "centre": null,
            "divider": {
              "attachments": [],
              "category": "botanical",
              "dropped": false,
              "is_fallback": false,
              "motif": "scallop",
              "once_per_wedge": false,
              "provides_contact": true,
              "slot_child": null
            }
          }
        ],
        "side_touch_radial": 0.48738757947622124
      },
      {
        "centre_share": 1.0,
        "contact_mode": "side",
        "divisions": 8,
        "ring_index": 1,
        "ring_seed": 1,
        "sequence": [
          {
            "centre": {
              "attachments": [
                {
                  "attachments": [],
                  "category": "botanical",
                  "dropped": false,
                  "is_fallback": false,
                  "motif": "stem",
                  "once_per_wedge": true,
                  "provides_contact": true,
                  "slot_child": null
                }
              ],
              "category": "botanical",
              "dropped": false,
              "is_fallback": false,
              "motif": "leaf",
              "once_per_wedge": false,
              "provides_contact": true,
              "slot_child": null
            },
            "divider": null
          }
        ],
        "side_touch_radial": 0.3923170845034385
      }
    ],
    "seed": 1,
    "style": {
      "categories": ["botanical"],
      "positions": "divider"
    }
  },
  "ring_seeds": {},
  "svg": "<svg baseProfile=\"full\" height=\"612\" ...",
  "used_seed": 1,
  "validation": {
    "dangling_end_count": 0,
    "floating_base_count": 0,
    "is_valid": true,
    "issue_count": 0,
    "issues": [],
    "overflow_crossing_count": 0,
    "tiny_region_count": 0
  }
}
```

The plan is `DesignPlan.to_dict()`. At the top it carries the `seed`, the `style` and the design's `base_symmetry`, which every ring's division count is a multiple of. Each ring carries its `divisions`, its `centre_share` (1.0 when only one position is used), its `contact_mode` (`side`, `overflow` or `stem`), its `touch_height` (`base` or `mid`), its `side_touch_radial` (the radial of the shared side vertices, used only in a `side` ring), its `ring_seed` (the design seed unless the ring was regenerated through `/regenerate-ring`, or re-rolled by the region-cap repair ladder, whose step 4 salts the ring's seed `"repair:4:<k>"` for attempt `k`), its `position_mode` (`centre`, `divider`, `both` or `layered`), its `back` (a layered ring's back recipe, or null), `back_dropped` (true when the ring was planned layered and lost its back) and its `sequence`. Each `CellEntry` holds a `centre` and a `divider` recipe, either of which may be null. A `CellRecipe` names its `motif` and `category`, its `slot_child` and `attachments`, and four flags: `is_fallback` for a safe band, `provides_contact` for a node that routes its cell to the structure, `once_per_wedge` on an attachment drawn once per wedge rather than in every cell (at least `MIN_RING_CONTACTS` times in the ring), and `dropped` on a slot-child recipe that could not be placed in at least one cell, and its `embellishments`, the names picked for it. The region-cap repairs add three fields: each `CellRecipe` carries its `size_floor` (0.0 unless step 2 raised it), each ring its `rosette` (null except on the innermost ring once step 3 kept one), and the plan its `repairs`, the kept repairs in order as `{"step", "kind", "ring", "change"}` (see `docs/motifs.md`). The validation summary does not report oversized faces. A plan serialised before these fields existed still loads, with `base_symmetry` 1, `contact_mode` `stem`, `touch_height` `mid`, `side_touch_radial` 0.5, `once_per_wedge` false, no `back`, `back_dropped` false, empty `embellishments`, a `position_mode` derived from the ring's entries, `size_floor` 0.0, no `rosette` and empty `repairs`. `validation` is null when validation did not run, and `issues` holds at most 20 messages.

`POST /regenerate-ring` takes the `/generate` keys plus `ring_index` and an optional `ring_seed` (random when omitted), and returns `ring_index`, `ring_seed`, the whole `svg`, the full `plan`, the merged `ring_seeds` and `validation`. JSON object keys are strings, so `ring_seeds` comes back as `{"2": 81234}`; the API accepts the same shape back. The client replaces the whole SVG document, since neighbouring rings' overflow and reaches land on the regenerated ring's new ink.
