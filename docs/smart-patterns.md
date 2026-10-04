# Smart Patterns

The current active pattern system lives in the `smart_patterns/` package.

The older category modules under `patterns/` remain in the repo, but `pattern_generator.py` currently routes generation through the smart-pattern package because those functions enforce the cell contract.

## File Layout

```text
smart_patterns/
  __init__.py
  core.py
  botanical.py
  geometric.py
  celtic.py
  art_deco.py
  abstract.py
  fallback.py
```

`core.py` owns shared geometry and validation. Category files own only category-specific generators and registries.

## Cell Space

Smart patterns are written in normalized cell coordinates:

```python
CellPoint(radial=0.0, angular=0.0)
```

`radial`:

- `0.0` is the inner ring boundary.
- `1.0` is the outer ring boundary.

`angular`:

- `-1.0` is the left cell edge.
- `0.0` is the centerline of the cell.
- `1.0` is the right cell edge.

`SmartCellContext.to_cartesian()` converts these normalized points into canvas coordinates using the current ring radii, wedge angle, and mandala center.

## Vector Contract

A `SmartVector` is a polyline or closed shape:

```python
SmartVector([CellPoint(0.0, 0.0), CellPoint(1.0, 0.0)])
```

Rules:

- Open vector endpoints must touch a boundary or another vector.
- Closed vectors must touch a boundary or another vector.
- A vector must not float inside a cell.
- Radial coordinates may go below `0.0` or above `1.0` when a pattern intentionally crosses the lower or upper ring boundary.
- Left and right boundary ports must be paired at matching radial positions unless the vector opts into adjacent-cell intersection validation.
- Crossings that create white spaces smaller than `min_white_space` are rejected.

## Boundary Ports

If a vector touches the left side of a cell, repeated cells need a matching touch on the right side. The analyzer collects left and right ports and compares their radial values.

Valid side-to-side bridge:

```python
SmartVector([CellPoint(0.5, -1.0), CellPoint(0.5, 1.0)])
```

Invalid bridge by default:

```python
SmartVector([CellPoint(0.4, -1.0), CellPoint(0.7, 1.0)])
```

The invalid bridge would not meet its neighbor at the same radial position. A pattern can set `allow_adjacent_intersections=True` on its smart vectors only when another segment crosses the opposite side boundary at the unmatched radial position and the resulting connection does not create whitespace smaller than `min_white_space`.

## Boundary Line Policy

Boundary line policy is inferred from emitted smart vectors:

- `requires_inner_boundary`: an open endpoint touches the inner ring boundary and does not touch another smart vector.
- `requires_outer_boundary`: an open endpoint touches the outer ring boundary and does not touch another smart vector.
- `requires_radial_boundaries`: currently only a fallback for non-smart elements or future explicit cases.
- Pattern registries may use `force_inner_boundary`, `force_outer_boundary`, or `force_radial_boundaries` only for non-inferable requirements. Current smart patterns default these force flags to `False`.

For the outermost ring, `requires_outer_boundary` is suppressed when the emitted smart vectors include a closed outer contour. In that case the pattern's own linework is the printable enclosure, so the circular page border is redundant.

Side-to-side ports do not automatically require radial divider lines.

Non-smart elements default to all boundaries drawn because the generator cannot infer their connection contract.

Candidate pattern output is validated after inferred and forced boundaries are added. If the boundary-inclusive drawing fails final validation, the generator rejects that candidate and tries the next enabled smart pattern or the category-specific safe fallback.

## Minimum White Space

The UI's `Min Pattern Size` slider is passed into smart patterns as `min_white_space`.

When two segments intersect, `SmartVectorAnalyzer` measures the distance from the crossing point to nearby segment endpoints in actual pixels. If the intersection creates a region below the threshold, the pattern is rejected before SVG output.

Endpoint touches are allowed. This keeps valid line connections from being misclassified as tiny white-space regions. Smart-vector endpoints outside the radial cell bounds are treated as boundary crossings by both the smart analyzer and post-generation validator.

## Stroke Styling

Smart pattern SVG paths include:

```svg
stroke-linecap="butt"
stroke-linejoin="round"
```

Butt caps prevent open vectors from protruding beyond boundary lines. Round joins reduce sharp miter spikes at closed-shape corners.

## Pattern Families

| Category | Patterns |
|---|---|
| Botanical | `smart_petal`, `smart_leaf`, `smart_vine_band`, `smart_scallop_band` |
| Geometric | `smart_diamond`, `smart_prism_lattice`, `smart_triangle_band`, `smart_star_point`, `smart_chevron_stack` |
| Celtic | `smart_laced`, `smart_braid_knot`, `smart_greek_key`, `smart_twist_band` |
| Art Deco | `smart_fan`, `smart_stepped_band`, `smart_sunburst`, `smart_deco_shell` |
| Abstract | `smart_bridge_band`, `smart_resonance_ladder`, `smart_ripple_stack`, `smart_flame_band` |

`smart_<category>_safe_spoke` is a per-category fallback built on demand; it is
not a registry entry.

## Fallback Behavior

Some parameter combinations can make a selected pattern invalid under the minimum white-space rule. `PatternGenerator.generate_ring_variations()` handles this by:

1. trying the selected pattern,
2. trying other enabled smart patterns valid for the ring,
3. using a category-specific safe spoke fallback for the selected pattern category.

Fallback is a **ring-level** decision: every variation of a ring is generated
from the same pattern, and if any variation fails the whole ring moves to the
next candidate. Letting variations fall back individually produced rings whose
cells came from different patterns, and since each pattern puts its side ports
at its own radii, neighbouring cells then had nothing to connect to.

This prevents rejected geometry from becoming an HTTP 500.

Fallbacks must still belong to one of the selected categories. The generator rejects any candidate whose category is not selected.

## Cell Geometry Is Polar, Not Cartesian

`make_path` joins consecutive `CellPoint`s along the **cell-space** line, which
is what the analyzer measures, and subdivides any segment spanning more than
~4 degrees of arc so the rendered polyline tracks it. A constant-radial vector is
therefore drawn as a true arc, not a chord.

This matters because the two used to disagree: a two-point vector from
`(0.5, -1.0)` to `(0.5, 1.0)` looked like a straight line to the analyzer and
rendered as a chord bowing up to 37px away from it, which turned every endpoint
landing on the arc into a dangling line end. You no longer have to think about
it - write the two points and the engine handles fidelity.

## Archetypes

Build from one of these. They are the structures that provably satisfy the
contract:

| Archetype | Shape | Why it holds |
|---|---|---|
| **Side-to-side band** | `(r,-1)` ... `(r,+1)` | ends on side boundaries at the same radial, so ports match trivially and repeats tile |
| **Radial spoke** | `(0,a)` to `(1,a)` | ends on the inner/outer boundaries, which are then inferred and drawn |
| **Boundary-anchored closed shape** | closed, vertices on boundaries | a closed vector touching a boundary cannot float; corner points at radial 0 or 1 resolve as inner/outer, so they create no port obligation |
| **Axis motif with matched ports** | centreline shape, arms ending at `(p, -1)` and `(p, +1)` | arms terminate on the side boundaries at a shared port radial |
| **Carrier-attached accent** | arc with both feet on exact carrier vertices | the accent touches real ink instead of floating; see `smart_scallop_band` |

Anything that would float - a lone dot, a spiral ending in space - must be
attached to a carrier. Do not relax the "closed vector must touch something"
rule; it is the only defence against a pattern quietly emitting orphan ink.

## Authoring Rules

These are the traps that have actually bitten, each found by a failing harness
case:

1. **Side ports come from `port_rng`, never `rng`.** `port_rng` is stable across
   a ring's variations; `rng` is not. A port radial drawn from `rng` means cells
   from different variations of the same ring cannot meet - 12 dangling ends per
   affected ring.
2. **Put a vertex where you cross another vector.** The minimum-white-space
   check measures a crossing against the *endpoints of the segments involved*, so
   crossing mid-segment can read as a pinch. Crossing at a vertex does not.
3. **Never land an acute apex on a line.** A sharp vertex sitting on a spine or a
   boundary arc gets sliced into slivers thinner than a pen tip. Keep sharp tips
   in open space, or blunt them.
4. **Size in pixels, not cell fractions.** Ring width varies about 8x across the
   supported settings, but cell *width* varies about 45x. Use
   `context.cell_width_px()`, `radial_to_px()`, `px_to_angular()` and friends. A
   motif tuned for a mid-size cell becomes a needle on a tall ring at 24
   divisions.
5. **Measure at the narrow end.** A wedge is narrowest at its inner boundary.
   Count rays and space elements using the width where they are closest, not at
   mid radius. `context.radial_for_cell_width()` finds where the cell first
   reaches a target width.
6. **Do not leave a paper-thin gap.** If you lift a shape off a boundary, either
   clear a colourable gap or sit on the boundary. A 2px annulus is not
   colourable.
7. **Subdivide the ring.** A pattern of concentric bands with no radial connector
   polygonizes into one big annulus - the harness fails it. Include a spoke or a
   rung.
8. **Degrade gracefully.** When a cell is too small for a detail, drop the detail
   rather than raising; raising forces the whole ring onto another pattern.
9. **Span the whole cell radially.** Some line must cross every radius from 0 to
   1. A radial band nothing crosses becomes a corridor running the entire way
   around the finished mandala - a colourist can follow it around without ever
   crossing a line, and the whole band reads as one region. Ring boundary arcs
   cannot save you: they are circles, so they only put ink at a single radius.
   This is enforced by the contract, and 10 of the first 21 patterns failed it.
   Usually the fix is a spine from `(0, 0)` to `(1, 0)` carrying a vertex
   wherever it meets existing linework - or, when a centre spine would cut
   through the motif, a pair of short connectors on the cell's side boundary
   (see `smart_resonance_ladder`).

Declare `min_ring_width` and `min_cell_width_px` so selection skips a pattern
whose cell is too small, rather than generating it and rejecting it.

## Adding A New Smart Pattern

Add the generator to the relevant category file under `smart_patterns/`, then
register it in that module's `*_SMART_PATTERNS` list.

```python
def generate_new_cell(
    inner_radius,
    outer_radius,
    wedge_angle,
    center,
    complexity,
    stroke_width,
    rng,
    min_white_space=10.0,
    port_rng=None,          # ring-stable stream: use for anything on a side boundary
    **_,
):
    context = SmartCellContext(
        inner_radius, outer_radius, wedge_angle, center,
        stroke_width, complexity, rng, min_white_space,
    )
    ports = port_rng if port_rng is not None else rng
    port = 0.4 + ports.random() * 0.2

    vectors = [
        SmartVector([CellPoint(port, -1.0), CellPoint(port, 1.0)]),
        SmartVector([CellPoint(0.0, 0.0), CellPoint(port, 0.0)]),
    ]
    return _smart_elements(context, vectors)
```

Registry entry:

```python
{
    "name": "smart_new",
    "category": "geometric",
    "generator": generate_new_cell,
    "allow_first_ring": True,
    "allow_last_ring": True,
    "min_ring_width": 18,
    "min_cell_width_px": 0.0,
    "force_inner_boundary": False,
    "force_outer_boundary": False,
    "force_radial_boundaries": False,
}
```

Then prove it:

```bash
.venv/Scripts/python qa_patterns.py --pattern smart_new
.venv/Scripts/python qa_report.py --corpus
```

`qa_patterns.py` forces the pattern into every ring across divisions, ring
counts and complexity, with fallback disabled so a rejection is a visible
failure. It also checks port stability directly. Use `--probe` to ignore the
declared size gates when recalibrating them.

## Deliberate Bleed

An open endpoint may overshoot a radial boundary by up to 3px via
`overshoot_start_px` / `overshoot_end_px`, which reads as a hand-drawn overrun.
It is legal only where a **lone** line crosses: the endpoint must sit on a radial
boundary, must not sit on a side boundary (the neighbouring cell shares it), and
must not coincide with another vector in the cell. When several lines share an
endpoint pushed outside the ring they fan out from a point beyond the boundary
arc, and the arc slices tiny un-colourable triangles off the fan.
