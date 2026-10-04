# MandalaForge

Procedural generator for mandala-style colouring pages. A Flask app renders
radially symmetric SVG designs that are validated for **colourability**: every
line connects to something, and every enclosed space is big enough to colour.

## Quick start

```bash
.venv/Scripts/python app.py
```

Then open http://localhost:5000.

## How a design is built

1. The canvas is divided into concentric **rings** and radial **divisions**.
   One ring x one division is a **cell** — a wedge-shaped region.
2. Each ring picks ONE pattern, generated for a single cell and then rotated
   into every division, which is what produces the radial symmetry.
3. A ring may use several **variations** of its pattern (different detail from
   the same generator), interleaved across divisions.
4. Patterns declare which ring boundaries they need; those arcs are drawn.
5. The finished linework is validated by exact planar topology analysis.

## Architecture

| File | Role |
|---|---|
| `app.py` | Flask routes: `/`, `/generate`, `/regenerate-ring` |
| `coloring_generator.py` | `DesignGenerator` — ring geometry, assembly, boundary inference, validation |
| `pattern_generator.py` | `PatternGenerator` — pattern selection, size gates, ring-atomic fallback |
| `smart_patterns/` | The pattern library: `core.py` holds the cell contract, one module per category |
| `topology_validator.py` | Exact planar-topology QA (Shapely/GEOS) |
| `shape_extractor.py` | Parses SVG elements into sampled polylines for QA |
| `qa_report.py` | Whole-design QA over a pinned corpus |
| `qa_patterns.py` | Per-pattern coverage harness |

## The pattern catalog

21 patterns across five categories. Every one is validated across the full
parameter matrix by `qa_patterns.py`.

| Category | Patterns |
|---|---|
| Botanical | `petal`, `leaf`, `vine_band`, `scallop_band` |
| Geometric | `diamond`, `prism_lattice`, `triangle_band`, `star_point`, `chevron_stack` |
| Celtic | `laced`, `braid_knot`, `greek_key`, `twist_band` |
| Art Deco | `fan`, `stepped_band`, `sunburst`, `deco_shell` |
| Abstract | `bridge_band`, `resonance_ladder`, `ripple_stack`, `flame_band` |

Each also has a `smart_<category>_safe_spoke` fallback, used only when every
real candidate is rejected for the ring's size.

**Adding a pattern:** see `docs/smart-patterns.md`. Patterns are authored in
normalized cell space and must satisfy a connection contract; the guide covers
the contract, the archetypes that satisfy it, and the traps.

## Parameters

| Control | API key | Range | Default |
|---|---|---|---|
| Rings | `num_rings` | 2–7 | 4 |
| Divisions | `num_divisions` | 6–24 (even) | 12 |
| Min pattern size | `min_pattern_size` | 5–50 px | 10 |
| Detail level | `complexity` | 0.0–1.0 | 0.5 |
| Seed | `seed` | any integer, blank to randomise | — |
| Categories | `categories` | any subset of the five | `["botanical"]` |

`/generate` returns `svg`, `params_string`, `used_seed`, `validation`, and
`pattern_usage` (per-ring pattern names and boundary decisions).
`/regenerate-ring` re-rolls a single ring, preserving the rest of the design.

## Quality assurance

Designs are validated by building the true planar arrangement of all linework
and reading the answers off the topology, rather than guessing from proximity:

- **Dangling ends** — after noding every crossing, any endpoint with graph
  degree 1 connects to nothing.
- **Un-colourable regions** — the arrangement is polygonized into the faces a
  person would actually colour; a face fails if it is under 20px² or vanishes
  when eroded by a 2px pen tip.
- **Floating shapes** — disconnected open components. Isolated closed loops are
  allowed, since concentric circles are normal mandala structure.
- **Un-crossed lanes** — radii at which a full circle around the centre crosses
  no ink. That is a corridor running the whole way around the design, so a
  colourist could travel around it without ever crossing a line and the band
  reads as one enormous region.

Before measuring, the pipeline nodes the arrangement, prunes overshoot whiskers
below 5px, and bridges gaps under one stroke width — those read as connected on
paper.

```bash
.venv/Scripts/python qa_report.py --corpus     # 90 designs: categories x seeds x complexity
.venv/Scripts/python qa_patterns.py            # every pattern across the parameter matrix
.venv/Scripts/python qa_check.py design.svg    # any standalone SVG
```

All three exit non-zero on failure. `qa_report.py` and `qa_check.py` can write a
**visual QA overlay**: every detected region filled with a random pastel, with
defects in red — a machine-made colouring test.

## Documentation

- `docs/smart-patterns.md` — the cell contract and how to author a pattern
- `docs/architecture.md` — runtime flow and file roles
- `docs/pattern-category-audit.md` — pattern inventory and the archived legacy motif catalog
- `docs/local-development.md` — environment setup
- `docs/QA_REMEDIATION_PLAN.md` — history of the QA hardening work

## Known issues

- `templates/index.html` redirects to `/login.html`, which Flask does not serve;
  the auth flow is not wired up.
