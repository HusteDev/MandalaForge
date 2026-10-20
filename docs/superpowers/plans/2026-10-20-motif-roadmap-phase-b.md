# Motif Roadmap Phase B Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the engine the "busy" ring trims and interior textures of the denser references: three seam motifs (`sawtooth`, `arcade`, `vesica_chain`) and three embellishments (`cap`, `hatch`, `dotted_echo`).

**Architecture:** The trims are seam motifs, built exactly like `scallop` and `band`: every seam-deciding value is drawn from `context.ring_rng`, open ends sit at angular exactly ±1.0, and the composer already gives every cell of a seam position its own stem, which anchors on the motif's ink on the axis and ties the ring to the structure inside it. Seam rings never stack, so the new trims join the existing avoid rule unchanged. The embellishments are handlers in `motifs/embellish.py`. `cap` and `hatch` are arcs at a constant radial (parallel to the ring edges) whose ends are inserted as vertices of the innermost outline, as `veins` and `fan` land theirs. `dotted_echo` is a border: a row of floating detail circles inside the outline, in place of a continuous echo.

**Tech Stack:** Python 3.10+, Shapely 2, pytest.

**Spec:** `docs/superpowers/specs/2026-10-11-motif-roadmap-design.md` (sections 3.2, 4, 7 Phase B, 8).

## Global Constraints

- Rings and dividers are never ink; every open end lands on ink or is a seam end at angular exactly ±1.0; every base joins one structure.
- Seam motifs: `seams: True`, `spans_cell: True`, zero overflow, every seam-deciding value from `ring_rng`, `require_full_budget`.
- Draw every parameter before applying any limit (determinism and monotone limits).
- An embellishment that does not fit is dropped and counted, never raised.
- Every face an embellishment makes holds a pen (`_faces_hold_pen`).
- `tests/test_layering.py` has uncommitted work in the user's checkout: do not edit it. New tests go in new files.

## Decisions taken where the roadmap is open

- **Sawtooth's tie.** The roadmap asks for a tie to the inward ring. The per-cell stem every seam position already gets is that tie, so no extra connector is drawn. When the inset second tooth line is drawn (complexity ≥ 0.6), a short detail connector on the axis joins the two apexes, so the zigzag strip between the lines is cut into one face per cell instead of encircling the centre.
- **Arcade's trefoil variant** is deferred: the plain cusped arcade comes first, and the trefoil lobe follows only if the review asks for it.
- **Vesica chain** is drawn as two half-circles per cell, one from each divider's circle, split at their two crossings on the axis so each crossing is a shared vertex. Its lens width is a drawn share of the circle's diameter, floored at a pen width; a cell too wide for its depth to overlap raises `MotifError`, and the size gates keep that rare.
- **Cap and hatch lines** are arcs at a constant radial: perpendicular to the host's axis where they cross it, and parallel to the ring edges, as the roadmap describes the cap.
- **Cap with veins.** Veins stop at the lowest cap arc: the midrib ends on it and every side vein that would cross it ends on it instead. `fan` and `hatch` are not offered beside a cap; picking one drops the cap from the pick.
- **Dotted echo order.** It runs after the interior fill, not first, so its dots can skip the places where vein, cap or hatch ends meet the outline. `echo` and `dotted_echo` are exclusive (`BORDERS`), as interior fills are.
- **Hosts.** `cap`: petal, rounded_petal, teardrop. `hatch`: leaf, teardrop, spike, kite. `dotted_echo`: petal, rounded_petal, teardrop. The roadmap's scallop and arcade lobes are open seam lines, not closed hosts, so they are left out.

## Review Focus

1. **Narrow, deep cells.** At 24 divisions a sawtooth or arcade tooth is tall and thin: its seam V must still hold a pen. Test at the smallest gate cell.
2. **Wide, shallow cells.** At 4 to 6 divisions the vesica circles cannot overlap: `MotifError`, never a crossing that is not a vertex. Test.
3. **Small hosts.** A cap, hatch or dotted echo on a host near its gate must drop (and count), never raise or leave a face below the pen floor. Test per embellishment.
4. **Cap beside veins.** The midrib and side veins end exactly on vertices of the lowest cap arc or the outline. Test.
5. **Dot after a dotted echo.** The axis `dot` keeps its clearance from the dotted row. Test.

---

### Task 1: sawtooth

**Files:** Create `motifs/trims.py` (`TRIM_MOTIFS`, appended to `MOTIFS` in `motifs/__init__.py`); test `tests/test_motifs_trims.py`.

**Interfaces:** `generate_sawtooth(context) -> MotifInstance`; registry `"sawtooth"`: geometric, positions `["centre", "divider"]`, roles `["base"]`, seams, `spans_cell True`, no embellishments, gates 12 / 16, overflow 0 / 0.

Shape: one open polyline per cell, `(b, -1) → (a, 0) → (b, 1)`; direction (outward `a > b` or inward) from `ring_rng`; each side a straight line or a cubic bowed toward the tooth's interior by a drawn share (`SAWTOOTH_BOW_RANGE`). At complexity ≥ 0.6 an inset tooth line, offset toward the apex, and a detail connector between the two apexes.

- [ ] Tests: seam ends at exactly ±1.0 and the same at two seeds with one ring stream; every point within limits; inset line present only at complexity ≥ 0.6 with its connector's ends on both apexes; every face between the two lines holds a pen.
- [ ] Implement, register, run `tests/test_motifs_trims.py tests/test_motifs.py`; commit `feat(motifs): sawtooth`.

### Task 2: arcade

**Files:** `motifs/trims.py`, `tests/test_motifs_trims.py`.

**Interfaces:** `generate_arcade(context)`; registry `"arcade"`: geometric, positions `["centre", "divider"]`, roles `["base"]`, seams, gates 12 / 16, overflow 0 / 0.

Shape: two page-space circular arcs per cell, from the seam ends `(b, ±1)` to a cusp `(a, 0)`, each bulging away from the tooth's interior by a drawn sagitta share (`ARCADE_BULGE_RANGE`), so the springing at the seam is never tangent to the divider. Direction from `ring_rng`. The sagitta shrinks in 0.9 steps until the arcs stay within ±1, as the scallop's apex does.

- [ ] Tests: seam ends and cusp are exact vertices; arcs round on the page (samples within 1% of one circle); within ±1; the seam V between neighbouring cells turns at least 20 degrees.
- [ ] Implement, register, test, commit `feat(motifs): arcade`.

### Task 3: vesica_chain

**Files:** `motifs/trims.py`, `tests/test_motifs_trims.py`.

**Interfaces:** `generate_vesica_chain(context)`; registry `"vesica_chain"`: geometric, positions `["centre", "divider"]`, roles `["base"]`, seams, gates 12 / 24, overflow 0 / 0.

Shape: circles centred on the dividers at radial `m` (`VESICA_CENTRE_RANGE`), page radius `R = D / (1 - s)` with `D` the centre's page distance from the cell axis and `s` (`VESICA_OVERLAP_RANGE`) the lens's share of the diameter; the cell draws each circle's inner half from its top seam end to its bottom seam end, split at the two crossings on the axis. Raise `MotifError` when `R` does not fit the ring depth or the lens is narrower than `clearance_px()`.

- [ ] Tests: four vectors, seam ends exact, the two axis crossings are vertices of both halves, the lens holds a pen, `MotifError` in a wide shallow cell.
- [ ] Implement, register, test, commit `feat(motifs): vesica_chain`.

### Task 4: cap and hatch

**Files:** `motifs/embellish.py`, `motifs/botanical.py` (accepted lists), `motifs/fillers.py` (kite), `motifs/geometric.py` (spike), `composer.py` (exclusive groups), `qa_patterns.py` (`embellishment_sets`); test `tests/test_embellish_textures.py`.

**Interfaces:** `EMBELLISHMENT_ORDER = ("echo", "cap", "veins", "fan", "hatch", "dotted_echo", "dot", "drop", "beads")`; `INTERIOR_FILLS` gains `hatch`; `BORDERS = ("echo", "dotted_echo")`; `EXCLUSIVE_GROUPS = (INTERIOR_FILLS, BORDERS)`; `CAP_EXCLUDES = ("fan", "hatch")`.

- `cap`: 1 to 3 arcs (`CAP_ARCS_RANGE`) at constant radials in the outer part of the innermost ring, the first where the tip face above it holds a pen, the rest a drawn multiple of the detail clearance below; every arc above the host's axis middle. The slot outline is cut below the lowest arc. Veins and fan read the lowest arc as their ceiling.
- `hatch`: constant-radial arcs across the whole innermost ring at a drawn multiple (`HATCH_SPACING_RANGE`) of the detail clearance, evenly spaced between the base and tip crossings; the end lines are dropped when their faces do not hold a pen, and fewer than `MIN_HATCH_LINES` drops the hatch.

- [ ] Tests: every end is a vertex of the outline; arcs at constant radial; faces hold a pen; veins with cap end on the lowest cap arc; dropped (count 1) on a host at its gate.
- [ ] Implement, test with the embellishment, composer and QA tests, commit `feat(embellish): cap and hatch`.

### Task 5: dotted_echo

**Files:** as Task 4.

- `dotted_echo`: detail circles of drawn diameter (`DOTTED_DIAMETER_RANGE`, min_white_space units) centred on the outline inset by the outline-to-detail clearance plus the radius, evenly spaced on each half from the tip to the base and mirrored; a dot too close to other ink is skipped; fewer than `MIN_DOTTED` per half drops it. The slot outline moves inside the row.

- [ ] Tests: dots round, mirrored, clear of the outline and each other; skipped beside vein ends; `dot` after it keeps clear; dropped on a small host.
- [ ] Implement, test, commit `feat(embellish): dotted echo`.

### Task 6: QA, corpus and review

- [ ] `qa_patterns.py --motif <name> --tier full` for each new motif and each host of a new embellishment; exit 0.
- [ ] `qa_report.py --corpus` 180/180, quotas held (each new motif and embellishment placed at least ten times; add corpus jobs if not); oversized designs at or under `OVERSIZED_DESIGN_CEILING`.
- [ ] Full suite: no failure beyond the base branch's.
- [ ] `docs/motifs.md`: a "Ring trims and textures (roadmap Phase B)" section.
- [ ] Twelve designs and their QA overlays for the visual review gate.
