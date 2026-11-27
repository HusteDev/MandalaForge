# MandalaForge

Procedural generator for mandala-style colouring pages. A Flask app renders radially arranged SVG designs that are validated for **colourability**: every line connects to something, and every enclosed space is big enough to colour.

## Quick start

```bash
.venv/Scripts/python app.py
```

Then open http://localhost:5000.

## How a design is built

1. **Plan.** The canvas is divided into concentric **rings**. Each ring has its own number of **divisions**, and one ring times one division is a **cell**. Every design has a **base symmetry** `B`: every ring's division count is a multiple of it, and the design repeats exactly every `360 / B` degrees. The composer (`composer.py`) decides, from the seed and without drawing anything, what every ring contains: its division count, a short sequence of cell recipes that repeats whole in every wedge, for each cell entry a motif at the cell's centre, on its divider, or both, and how the ring connects to the ring inside it (its contact mode). A recipe is a small tree: a base motif, an optional slot child nested inside it, and optional attachments (stems) that reach toward the ring inside. Ring boundaries and division lines are construction lines; they are never drawn.
2. **Assemble, pass one.** The assembler (`assembler.py`) draws every motif of every cell in normalised cell space, rotates it into place, and indexes the ink. Motifs are parametric, so every cell instance is drawn from its own seeded stream within the ranges its author declared. Slot children are fitted to the slot their parent really declares in that cell, and dropped where they do not fit.
3. **Assemble, pass two.** The resolver (`resolver.py`) works ring by ring from the centre out, on one wedge, and mirrors every change to the other wedges by rotation. Neighbouring motifs in a ring meet at shared side vertices, so the ring is one band. Overflow past a ring's edge is pulled back until it neither crosses nor crowds the neighbouring ring's ink, then touches that ink where it comes close. Stems are cast from their motif to the first ink they meet, never past the inward neighbour ring, and drawn there. A base that is not connected to the structure gets a motif that touches its neighbours, a stem, a different motif, or the category's safe band, and the ring is resolved again. Every touch is exact: a shared vertex, never a snap tolerance.
4. **Validate.** The finished linework is checked by exact planar topology analysis (`topology_validator.py`): no dangling ends, no un-colourable regions, no floating base motifs, no overflow crossing another ring. The SVG emits every cell as explicit paths, grouped by ring.

The authoring guide `docs/motifs.md` explains the motif contract in full; `docs/architecture.md` describes the runtime flow.

## Architecture

| File | Role |
|---|---|
| `app.py` | Flask routes: `/`, `/generate`, `/regenerate-ring` |
| `coloring_generator.py` | `DesignGenerator`: ring radii, runs composer and assembler, renders SVG, validates |
| `composer.py` | `Composer` and the plan model (`DesignPlan`, `RingPlan`, `CellEntry`, `CellRecipe`): divisions, positions, motif choice, contact routes, node fallback |
| `assembler.py` | `Assembler`: pass one (draw, place, index every cell) and regeneration of nodes for pass two |
| `resolver.py` | Pass two: overflow pull-back and touches, reaches, per-ring contact check |
| `placement.py` | Pure geometry and the ink index: placed paths, tracing, overflow runs, `InkIndex` |
| `motifs/` | The motif library: `geometry.py` (cell space), `contract.py` (declaration and analyzer), `slot_fit.py`, `botanical.py`, `geometric.py`, `fallback.py`, registry in `__init__.py` |
| `topology_validator.py` | Exact planar-topology QA (Shapely/GEOS) |
| `qa_patterns.py` | Per-motif coverage harness |
| `qa_report.py` | Whole-design QA over a pinned corpus |
| `qa_check.py` | Topology QA for any standalone SVG |
| `templates/index.html`, `static/script.js` | Controls, preview, ring selector, debug bar, gallery and print |

## The motif catalog

| Motif | Category | Kind | Roles | Positions | Touch heights | Embellishments | What it draws |
|---|---|---|---|---|---|---|---|
| `petal` | botanical | enclosing | base, slot, back | centre, divider | base, mid | echo, veins, fan, dot | lotus profile, length 0.95 to 1.3 of ring depth, dips into the ring below; declares a slot |
| `leaf` | botanical | enclosing | base, slot, back | centre | base, mid | echo, veins | mirror-symmetric pointed almond leaf; its midrib is the `veins` embellishment |
| `teardrop` | botanical | enclosing | base, slot, back | centre, divider | base, mid | echo, dot | round circular bulb below a drawn point; declares a slot |
| `rounded_petal` | botanical | enclosing | base, slot, back | centre, divider | base, mid | echo, veins, fan, dot | lotus profile with a circular cap for a tip; declares a slot |
| `heart` | botanical | enclosing | base, slot | centre | mid | echo | two circular lobes meeting at a cusp, running to a point; declares a slot |
| `curl` | botanical | open | base, slot | centre | mid | none | two mirrored spirals on stalks, each inner end landing on its own earlier turn; gates scale with white space |
| `scallop` | botanical | enclosing | base | divider | seams | none | one circular lobe per cell through shared seam ends, `spans_cell` |
| `stem` | botanical | open | attachment | centre, divider | none | none | inward reach to the neighbour ring, drawn as a bow, S-curve or wave |
| `diamond` | geometric | enclosing | slot | centre | none | none | pure island inside a parent's slot, sometimes with bowed edges |
| `band` | geometric | enclosing | base | centre, divider | seams | beads | two seam arcs tied by a lens per cell, `spans_cell`, the innermost ring (`ring_band` is an alias) |
| `bead` | geometric | enclosing | base, slot | divider | base, mid | echo | round bead on the divider (an oval when the circle cannot reach the touch vertices) |
| `spike` | geometric | enclosing | base, back | centre, divider | base | echo, fan | star point with concave sides on a rounded cup |
| `<category>_safe_band` | every category | enclosing | base (fallback) | centre, divider | mid | none | plain band at radial 0.4 to 0.6, `spans_cell`, valid in any cell |

Touch heights (`side_touch_heights` in the registry) say where a base draws to its full angular budget with exact vertices at the ring's side-touch radial, so it meets its neighbours there. A ring whose bases all support it is a `side` ring: one connected band that needs only one stem per wedge, and at least `MIN_RING_CONTACTS` (3) in the ring when the base symmetry is 1 or 2, or none when a base overflows inward.

Only botanical and geometric register motifs so far. The UI shows celtic, art deco and abstract disabled and unchecked with a "coming soon: no motifs yet" note, Randomise never picks them, and a saved gallery design that included them restores without them (botanical when nothing remains). The API still accepts them; a design limited to those categories is built from their safe bands.

**Adding a motif:** see `docs/motifs.md`. Motifs are authored in normalised cell space as parametric generators; the guide covers cell space and limits, the three-layer model, the measured declaration, positions, closure, the archetypes that satisfy it, the traps, and the registry entry.

## Parameters

| Control | API key | Range | Default |
|---|---|---|---|
| Rings | `num_rings` | 2–7 | 4 |
| Divisions | `num_divisions` | slider 6–24 in even steps; the API accepts any integer 4–24 | 12 |
| Vary divisions per ring | `vary_divisions` | boolean: the design draws a base symmetry `B` from the divisors of `num_divisions` between 3 and 8 (when there is none, the largest smaller divisor of at least 3, such as 11 for 22, or `num_divisions` itself for a prime), and each ring gets a multiple of `B` around `num_divisions`, lower for inner rings. Off, every ring has `num_divisions` cells and `B = num_divisions` | false |
| Limit large regions (slower) | `max_region_cap` | boolean: faces too large to colour at print size are repaired (detail inside a host, a background fill, a centre rosette, or a re-roll of the ring), at about 3 to 10 times the generation time; see `docs/motifs.md` | false |
| — | `ring_divisions` | optional list of exactly `num_rings` integers, each 4–24 (odd allowed); overrides both of the above, otherwise 400. Its base symmetry is the greatest common divisor of the counts, which may be 1 | — |
| Min pattern size | `min_pattern_size` | 5–50 px; the minimum white space inside and between motifs | 10 in the UI, 8 if omitted |
| Detail level | `complexity` | 0.0–1.0 | 0.5 |
| Seed | `seed` | any integer, blank to randomise | — |
| Categories | `categories` | any subset of the five | `["botanical"]` |
| — | `ring_seeds` | optional `{"<ring index>": seed}` from earlier ring regenerations, so the design rebuilds exactly | — |

`POST /generate` returns `svg`, `params_string`, `used_seed`, `validation` (`is_valid`, `issue_count`, `tiny_region_count`, `dangling_end_count`, `floating_base_count`, `overflow_crossing_count`, and up to 20 `issues`), `plan` (the serialised design plan: seed, style, `base_symmetry`, and per ring its divisions, `centre_share`, `contact_mode` (`side`, `overflow` or `stem`), `side_touch_radial`, ring seed and cell recipes, whose attachments carry `once_per_wedge`), and `ring_seeds`. `docs/architecture.md` shows a real response.

`POST /regenerate-ring` takes the same keys plus `ring_index` and an optional `ring_seed`. It re-plans that one ring with the new ring seed, keeps every other ring's plan, re-runs both assembly passes, and returns the whole new `svg`, the full `plan`, the merged `ring_seeds`, `ring_index`, `ring_seed` and `validation`. The whole document comes back because neighbouring rings' overflow and reaches land on the regenerated ring's new ink; the browser replaces the whole SVG. Invalid parameters, and a design that cannot be assembled, return 400 with `{"error": ...}`.

## Quality assurance

Designs are validated by building the true planar arrangement of all linework and reading the answers off the topology, rather than guessing from proximity:

- **Dangling ends**: after noding every crossing, any endpoint with graph degree 1 connects to nothing. This is the closure rule proven on the page.
- **Un-colourable regions**: the arrangement is polygonised into the faces a person would actually colour; a face fails if it is under 20px² or vanishes when eroded by a 2px pen tip.
- **Floating shapes**: disconnected open components. Isolated closed loops are allowed, since a slot child is a closed island inside its parent.
- **Floating base motifs**: every base motif, in both positions of every cell, must belong to one connected structure; any base outside the largest connected group of bases is reported. Slot children may be islands.
- **Overflow crossings**: overflow past a ring's edge may touch another ring's ink at a shared vertex but never cross it.
- **Un-crossed lanes and encircling regions**: a corridor running the whole way around the design, so a colourist could travel around it without crossing a line.

Before measuring, the pipeline nodes the arrangement, prunes overshoot whiskers below 5px, and bridges gaps under 2.5px; those read as connected on paper.

```bash
.venv/Scripts/python qa_patterns.py --motif petal          # one motif, smoke tier
.venv/Scripts/python qa_patterns.py --tier full --jobs 6   # every motif over the full matrix (about ten minutes)
.venv/Scripts/python qa_report.py --corpus --jobs 6        # 180 designs: categories x complexities x seeds x division modes
.venv/Scripts/python qa_check.py design.svg                # any standalone SVG
```

`qa_patterns.py` forces each registered motif in every position (centre, divider, both) and role (base, slot child, contact attachment) over a matrix of ring-division fixtures, whose base symmetries run from 1 to 24 and appear in each case's label, with fallback disabled, runs a pairing job for every embellishment a motif accepts and every layered front and back pair, and runs eight generator property checks (determinism, monotone limits, angular containment, slot honesty, seams, smooth side touch, layered cuts, embellished output). The full tier must list all twelve motifs with every property column PASS. `qa_patterns.py --list` lists the registry and `--probe` ignores the declared size gates for recalibration. `qa_report.py --corpus` runs the pinned corpus with uniform and varied divisions, and its table shows each design's base symmetry in the `B` column; `--overlays always` writes an overlay for every design instead of only for failures.

All of these exit non-zero on failure. `qa_report.py` and `qa_check.py` can write a **visual QA overlay**: every detected region filled with a random pastel, defects in red (floating base motifs in dashed boxes), and reaches traced in green.

## Live site: coloring.husted.dev

coloring.husted.dev serves this repository's `main` behind a sign-in page. The husted-dot-dev repository keeps only that sign-in shell and copies the rest from here at build time, so nothing is synced by hand:

- `static/` as is;
- the app markup in `templates/index.html` between the `embed:app:start` and `embed:app:end` comments (with `../static/` rewritten to `/static/`), so keep anything specific to the local page, such as its own sign-in bar, outside those markers;
- every top-level `*.py` except `app.py` and `qa_*.py`, plus `motifs/`, as the engine behind its Cloud Functions. `coloring_api.py` holds the request handling for `/generate` and `/regenerate-ring`; `app.py` and the Cloud Functions both call it, so change request parsing there.

`static/script.js` and `static/help.js` start on `DOMContentLoaded`, or at once if the page has already loaded, because the live site adds them only after sign-in.

Every push to `main` runs the tests (`.github/workflows/deploy-coloring-site.yml`); when they pass, husted-dot-dev builds and deploys the site. If the engine starts needing a new Python package, add it to husted-dot-dev's `functions/requirements.txt` as well, or that deploy stops at its smoke test.

## Documentation

- `docs/motifs.md`: the motif authoring guide
- `docs/architecture.md`: runtime flow, generation model and API shape
- `docs/motif-inventory.md`: motifs extracted from the reference sketches
- `docs/local-development.md`: environment setup
- `docs/superpowers/specs/2026-10-04-motif-engine-design.md`: the motif engine design spec

## Known issues

- `templates/index.html` redirects signed-out users to `/login.html` when not on localhost, and Flask does not serve that page; the auth flow is not wired up.
- The composer gates slot children on a fixed `slot_estimate` of (0.5, 0.5) for the petal. At high division counts the real slots are much smaller, so designs there drop many slot children: they stay valid, but are sparser than the plan suggests.
- The category descriptions in the UI still name the retired pattern families.
