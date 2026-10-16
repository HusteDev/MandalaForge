# Maximum Region Size Design

**Status:** Approved in conversation, awaiting written review

**Date:** 2026-10-16

**Scope:** Adds a print-scale maximum to the size of a colourable region and a repair pass that adds detail to designs whose regions exceed it. Builds on the motif engine and the motif-aesthetics work (`docs/superpowers/specs/2026-10-09-motif-aesthetics-design.md`) and keeps every structural rule they settled: the validator stays the authority, every repaired design must still pass it exactly as today.

## 1. Why

Designs are printed on 8.5×11 paper and coloured by hand. Some regions are too large to be pleasant to fill with one colour. In the reviewed designs the largest region (usually the open centre, or the background between ring-1 shapes, repeated once per wedge) measured 0.6 to 1.5 in², median about 1.1 in²; the user flagged a 1.5 in² centre region as too large. The engine already enforces a minimum region size (`MIN_REGION_AREA_PX2 = 20` in `topology_validator.py`); this adds the matching maximum.

## 2. Decisions

Settled in design conversation and not open:

1. An oversized region is fixed by adding detail inside it, not by rejecting or merely reporting the design.
2. The cap scales with complexity.
3. Repair happens after assembly, on measured faces, not by estimating empty space at plan time.
4. A design is never rejected for an oversized region; if the repair ladder cannot fix it, the best valid attempt is kept and the leftover is recorded.

## 3. The cap

`max_region_in2(complexity) = 1.25 - 0.65 * complexity`, clamped to complexity in `[0, 1]`: 1.25 in² at 0, about 0.86 in² at 0.6, 0.6 in² at 1.0. It converts to pixels at the page scale of 72 px per inch (the 612 px page is 8.5 in wide): `max_region_px2 = max_region_in2 * 72²` (1.0 in² is 5,184 px²). The function and the `PX_PER_INCH = 72.0` constant live in `topology_validator.py` beside `MIN_REGION_AREA_PX2`.

## 4. Detection

### 4.1 Which faces

The faces are the `RegionInfo` faces the validator already computes. The cap applies to every face inside the mandala's outer edge: host interiors, the open centre, and the background between shapes. The unbounded page outside the mandala is not a face and is never measured. Nothing else in validation changes.

### 4.2 Reporting

An oversized face is a soft issue. `ValidationResult` gains `oversized_regions: List[RegionInfo]` and the stats gain `num_oversized_regions` and `largest_region_in2`. `is_valid` does not depend on them.

### 4.3 Tying a face to the plan

Each oversized face is classified and matched to plan entries using the ring, cell, position and node path that every `PlacedPath` already records:

- **Host interior:** the face lies inside one closed base outline; the owner is that node.
- **Centre:** the face contains the design centre; the owner is ring 0.
- **Background:** otherwise; the owner is the ring holding most of the face's area (by the radial of its label point and its area split across ring bounds), and the bordering nodes are the nodes whose paths form the face's boundary.

Faces come in symmetric sets, one per wedge of the base symmetry. The repair acts on the plan entry behind a face (a `CellRecipe` in a sequence entry, or a ring's position mode), so one change fixes every copy at once.

## 5. The repair ladder

`DesignGenerator.generate` runs the ladder after a valid assembly when the cap is enabled. Each oversized face set climbs the steps below, cheapest first. After each step only the affected ring is re-assembled (through the existing regeneration path) and the design is validated and measured again; the next step runs only if the face set is still over the cap. A step whose result fails validation is undone and the ladder moves on.

1. **Detail inside the host** (host-interior faces): add an embellishment the host accepts and lacks, in order echo, then the interior fill it accepts (veins or fan), then dot, honouring the existing rules (one interior fill; an interior fill excludes a slot child). If the host declares a slot and has no slot child or interior fill, adding a slot child is tried before the dot.
2. **Fill the background** (background faces): if the owning ring is in `centre` mode, switch it to `both` so each gap gets a divider motif; if it is already `both` (or a divider ring), redraw its bases from the upper end of their size ranges. Seam and layered rings are left alone at this step (their geometry is ring-wide by construction).
3. **Fill the centre** (centre faces): add a `rosette` to the open middle. `rosette` is a new geometric motif: a small mirror-symmetric ring of lobes around a dot, sized to the free radius left inside ring 0, every parameter drawn from a ring-level stream so all wedges match, with the same clearance and colourability rules as every motif (`clearance_px`, `holds_pen`). It is placed as ink owned by ring 0 with role `detail`, so it never counts as floating base ink.
4. **Re-roll the ring** with a new ring seed, up to 3 attempts, keeping the attempt with the smallest total oversized area.
5. **Give up gracefully:** keep the best valid design found and leave its remaining oversized faces in `oversized_regions`.

### 5.1 Determinism

Repairs draw from their own stream, `node_seed` / ring seed salted with `"repair:<step>"` via `zlib.crc32` like every other salt. A design is fully reproducible from its seed and settings; repairs are recorded in the plan (the added embellishments, changed position modes, rosette and new ring seeds) so a saved plan replays without re-running the ladder.

### 5.2 Settings

`ComposerSettings` / `DesignGenerator` gain `max_region_cap: bool = True`. With it off, nothing is measured or repaired and output matches the pre-cap engine. The API and UI may expose it later; this spec does not require that.

## 6. Out of scope

Changing the minimum region size; any structural rule; rejecting designs for size; UI controls for the cap value; per-category caps.

## 7. Testing

- Unit tests for `max_region_in2` at complexity 0, 0.6, 1.0 and clamping, and for the px conversion.
- Unit tests for face classification (host interior, centre, background) and owner matching on hand-built designs.
- One test per ladder step on a seed known to produce the face type it targets, asserting the face set drops under the cap (or the step is skipped for seam/layered rings), the design still validates, and the plan records the repair.
- Determinism: same seed and settings give the same SVG and plan; a saved repaired plan replays identically.
- `max_region_cap=False` reproduces current output exactly.
- `qa_report.py --corpus` prints `oversized regions: X of 180 designs` and the largest region in in²; the corpus keeps 180/180 valid and both existing quotas. A pinned ceiling on X guards against regression once measured.

## 8. Documentation

`docs/motifs.md` gains the cap, the ladder and the `rosette` motif; `docs/architecture.md` describes where the repair pass runs.
