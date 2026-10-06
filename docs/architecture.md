# Architecture

MandalaForge is a Flask app that generates SVG mandala colouring pages. A design is planned by the composer, drawn and placed by the assembler in two passes, and checked by the topology validator. The motif contract and the rules for authoring motifs are in `docs/motifs.md`.

## Runtime Flow

1. The browser sends `POST /generate` from `static/script.js`.
2. `app.py` parses and validates the parameters (`ring_divisions` and `ring_seeds` included) and builds a `DesignGenerator`.
3. `DesignGenerator` in `coloring_generator.py` computes the ring radii.
4. `Composer` in `composer.py` plans every ring into a `DesignPlan`, deterministically from the seed and without drawing anything.
5. `Assembler` in `assembler.py` runs pass one: it draws every motif of every cell in cell space, places it on the page, and indexes the ink in an `InkIndex` (`placement.py`).
6. `resolver.py` runs pass two, rings innermost first: overflow is pulled back and touched, reaches are drawn, and floating cells are replaced through the composer and the ring resolved again. A final touch pass and a design-wide crossing and contact check follow.
7. `DesignGenerator` renders every placed path as an explicit SVG `<path>` in a `ring-<index>` group, with a `data-role` of `base`, `slot` or `reach`. There is no `<use>` rotation: cells in one ring are not identical after resolution.
8. `TopologyValidator` in `topology_validator.py` analyses the assembled polylines, with the base mask, ring ids and overflow runs, and the summary goes into the response.
9. The API returns the SVG, the validation summary, the serialised plan and the ring seeds.

`POST /regenerate-ring` follows the same flow with one ring's seed replaced, and returns the whole document.

## Main Files

- `app.py`: Flask routes, parameter parsing and API response shape.
- `coloring_generator.py`: ring radii, orchestration of composer, assembler and validator, SVG rendering, validation summary.
- `composer.py`: the plan model (`CellRecipe`, `CellEntry`, `RingPlan`, `DesignPlan`, all JSON-serialisable), seeded per-node streams (`node_seed`, `node_rng`), and `Composer`: division counts, position modes, motif choice, slot nesting, contact routes and the node fallback chain (`replace_node`).
- `assembler.py`: `Assembler` pass one, `PlacedNode` records that keep each node's recipe, seed, context and parent, and the regeneration and commit machinery pass two uses.
- `resolver.py`: pass two. Overflow pull-back and touches, reach casting and drawing, the per-ring and design-wide contact checks.
- `placement.py`: pure geometry and indexing. `PlacedPath`, `trace` (page coordinates with per-coordinate cell radials), `path_overflow` and `boundary_crossing`, and `InkIndex` over a Shapely `STRtree`.
- `motifs/`: the motif library. `geometry.py` (cell space and `MotifContext`), `contract.py` (`build_instance`, `Declaration`, `MotifAnalyzer`), `slot_fit.py`, the category modules `botanical.py` and `geometric.py`, `fallback.py` (safe bands), and the registry in `__init__.py`.
- `topology_validator.py`: exact planar topology QA, also used by the resolver to judge faces before it draws a reach or keeps a touch.
- `templates/index.html`: controls and preview layout.
- `static/script.js`: parameter collection, API calls, preview rendering, ring selector, debug bar, gallery and print controls.

## Generation Model

The app creates circular rings only. `num_rings` sets how many; their radii come from `complexity` (even spacing below 0.1, seeded variable spacing above). Each ring is divided into equal angular cells, and each ring has its own division count.

### Composer

Every choice draws from a stream derived from `(seed, ring_index, sequence_position, tree_depth, position)`, so changing one ring's plan does not reshuffle another's. A design-level style is drawn once per seed: a subset of the enabled categories, which the composer favours 3 to 1 over the others rather than excluding them, and a preferred position mode. For each ring, innermost first:

1. **Division count.** `ring_divisions` when supplied; otherwise, with `vary_divisions`, a count drawn around `num_divisions`, scaled down toward the centre and clamped to 4 to 24; otherwise `num_divisions`.
2. **Sequence length.** A divisor of the count from 1 to 4, with length 1 weighted 1 and the others weighted by `complexity`. Cell `i` uses `sequence[i % len(sequence)]`.
3. **Position mode.** `centre`, `divider` or `both`, weighted toward the style's preference; `both` draws a `centre_share` from 0.45 to 0.75 and needs a 28px cell.
4. **Each entry.** A base motif per occupied position from the enabled categories that supports the position and the `base` role and passes the size gates at this cell's budget. Ring 0 uses `spans_cell` bases only. An enclosing motif with a `slot_estimate` may get a slot child (probability `complexity`, halving per level), nesting at most three deep.
5. **Variety.** A ring avoids the base motifs of the canonical ring inside it, the one planned from the design seed, unless nothing else fits. Using the canonical ring means a design rebuilt from its seed plus its `ring_seeds` is exact.
6. **Contact.** Every base gets a route to the structure: inward overflow of at least 0.1, `spans_cell` in a ring that has contact, or a stem attachment, which the composer adds where neither holds.

When assembly rejects a node, the composer replaces that node only. A floating base first gets a stem (available even under `force_motif`, since it changes no motif), then another eligible motif, then the category's safe band.

### Assembler, pass one

Rings innermost to outermost, every cell and occupied position: the base is generated with its position's `MotifContext` (angular budget, radial limits from its overflow maxima, floor 0.0 in the innermost ring), its declared slot is measured, the slot child is generated into that slot, and so on down the tree. A child that does not fit its cell's real slot is dropped from that cell and the child's recipe is marked `dropped`. Attachments draw nothing yet; their reach ends are recorded with their page position. Each instance is rotated to its cell, plus half a wedge for the divider position, and every path enters the ink index tagged with ring, cell, position, node and role. A base that fails to generate is replaced through the composer up to three times.

### Resolver, pass two

Rings innermost to outermost. For each ring the inner ring's outward overflow is checked again against this ring's ink, then this ring's inward overflow, then its outward overflow, then its pending reaches, then the contact check. Floating bases are replaced and the ring resolved again, up to three rounds. When every ring is resolved, a final touch pass runs over every overflow side, then the design-wide checks run: no adjacent rings may still cross or crowd each other, and no base may float. Either failure raises `AssemblyError`, which the API returns as a 400.

## Positions, Overflow, Reaches and Contact

Ring boundaries and division lines are scaffolding. They are never drawn and nothing can land on them; the debug options `draw_rings` and `draw_divisions` show them as dashed grey guides only.

**Positions.** A cell has a `centre` position on its centreline and a `divider` position on its clockwise edge. Motifs are always authored centred on angular 0 and rotated by half a wedge for the divider. When a ring uses both, centre motifs get an angular half-width of `centre_share` and divider motifs get `1.0 - centre_share`, so they tile the cell and may touch but never cross.

**Overflow.** A motif may run past its ring's edges by its declared maxima, as a fraction of ring depth. The innermost ring never overflows inward. Overflow may touch neighbour ink at a shared vertex but never cross it, and it keeps `CLEARANCE_PX` (4px, twice the pen radius) from neighbour ink outside a touch disc of radius `max(min_white_space, 8px)` around its extreme vertex and around any vertex its path shares with other ink. A side that conflicts is pulled back by binary search over its radial limit, regenerating the node and its slot children from their stored seeds, at most four times; if nothing works the side keeps no overflow. The final touch pass moves an extreme vertex within 4px of neighbour ink onto it, unless that would make the two rings cross or crowd each other, judged from both rings, or close a face too thin or small to colour. Shared vertices are never moved.

**Reaches.** A reach starts on its node's own ink and casts in its direction. It lands at the first point within 4px of other ink, so it never runs beside ink in a gap no pen fits. An inward reach that misses within its declared length recasts to the design centre. A reach shorter than a pen width collapses to a touch. A wavy reach reduces its amplitude until it keeps 4px from all other ink. A reach that would close off an uncolourable face is not drawn.

**Contact.** A touch is an endpoint placed exactly on another path, with a vertex inserted into that path, so the validator sees a node of degree three. Every base in every cell must be connected to the structure: the component holding most of the innermost ring's bases. Slot children may be islands.

## Validation

There are two validation layers:

- `MotifAnalyzer` in `motifs/contract.py` checks each motif instance in cell space as it is built: open ends accounted for, limits respected, no crossing that leaves a sub-white-space gap, and a declared slot that really is clear of the motif's ink.
- `TopologyValidator` checks the assembled page: dangling ends, un-colourable faces (under 20px² or too thin for a 2px pen tip), floating open shapes, floating base motifs, overflow crossings into another ring, and lanes or regions that run the whole way around the centre.

The resolver judges candidate reaches and touches with the validator's own face rules, so pass two does not create the faces the validator would reject.

## API Response

`POST /generate` returns the following. This response is real (seed 1, two rings, eight divisions, complexity 0.7, botanical and geometric), abridged: the SVG is cut short and each ring's `sequence` shows one of its four entries.

```json
{
  "params_string": "Seed: 1\nRings: 2\nDivisions: 8\nRing divisions: 8, 8\nComplexity: 0.7\nCategories: botanical, geometric",
  "plan": {
    "rings": [
      {
        "centre_share": 1.0,
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
              "provides_contact": true,
              "slot_child": null
            }
          }
        ]
      },
      {
        "centre_share": 1.0,
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
                  "provides_contact": true,
                  "slot_child": null
                }
              ],
              "category": "botanical",
              "dropped": false,
              "is_fallback": false,
              "motif": "petal",
              "provides_contact": true,
              "slot_child": {
                "attachments": [],
                "category": "geometric",
                "dropped": false,
                "is_fallback": false,
                "motif": "diamond",
                "provides_contact": false,
                "slot_child": null
              }
            },
            "divider": null
          }
        ]
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

The plan is `DesignPlan.to_dict()`. Each ring carries its `divisions`, its `centre_share` (1.0 when only one position is used), its `ring_seed` (the design seed unless the ring was regenerated) and its `sequence`. Each `CellEntry` holds a `centre` and a `divider` recipe, either of which may be null. A `CellRecipe` names its `motif` and `category`, its `slot_child` and `attachments`, and three flags: `is_fallback` for a safe band, `provides_contact` for a node that routes its cell to the structure, and `dropped` on a slot-child recipe that could not be placed in at least one cell. `validation` is null when validation did not run, and `issues` holds at most 20 messages.

`POST /regenerate-ring` takes the `/generate` keys plus `ring_index` and an optional `ring_seed` (random when omitted), and returns `ring_index`, `ring_seed`, the whole `svg`, the full `plan`, the merged `ring_seeds` and `validation`. JSON object keys are strings, so `ring_seeds` comes back as `{"2": 81234}`; the API accepts the same shape back. The client replaces the whole SVG document, since neighbouring rings' overflow and reaches land on the regenerated ring's new ink.
