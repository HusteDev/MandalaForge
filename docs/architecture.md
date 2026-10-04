# Architecture

MandalaForge is a Flask app that generates SVG mandala coloring pages.

## Runtime Flow

1. The browser sends `POST /generate` from `static/script.js`.
2. `app.py` parses generation parameters.
3. `DesignGenerator` in `coloring_generator.py` creates ring geometry.
4. `PatternGenerator` in `pattern_generator.py` selects one smart pattern for each ring.
5. The `smart_patterns/` package validates each cell pattern before SVG conversion.
6. `DesignGenerator` places each generated cell around the ring with SVG `<use>` rotation.
7. Pattern-required ring and segment boundaries are drawn as normal linework.
8. `pattern_validator.py` extracts shapes from the final element set and checks connectivity.
9. The API returns SVG plus a validation summary.

## Main Files

- `app.py`: Flask routes and API response shape.
- `coloring_generator.py`: ring layout, SVG assembly, repeated cell placement, validation orchestration.
- `pattern_generator.py`: pattern selection, retry, and fallback behavior.
- `smart_patterns/`: current active smart pattern system and geometric rules.
- `pattern_validator.py`: post-generation shape extraction and connectivity validation.
- `templates/index.html`: controls and preview layout.
- `static/script.js`: browser-side parameter collection, API call, preview rendering, gallery, print controls.

## Generation Model

The app creates circular rings only. Each ring is divided into equal angular cells:

- `num_rings` controls how many circular bands exist.
- `num_divisions` controls how many repeated cells each ring has.
- `complexity` influences ring spacing, pattern density, and variation count.
- `min_pattern_size` is now used as the minimum white-space threshold.
- `categories` selects which smart pattern families can be used.

Each ring picks one base pattern. The generator may create multiple variations for that ring, then assigns variations around the ring by division index. Variation count is constrained so the repetition still divides cleanly around the circle.

## Boundaries

Ring boundaries and radial division lines are pattern-selected output, not debug-only geometry. This matters because some smart vectors intentionally terminate on boundaries, while other patterns already connect through repeated cells or closed internal geometry.

Boundary requirements are inferred from the actual smart vectors emitted for each ring variation:

- `requires_inner_boundary`,
- `requires_outer_boundary`,
- `requires_radial_boundaries`.

Open endpoints on the inner or outer radius require the matching circular boundary only when they do not already touch another smart vector. Left and right side ports are treated as repeated-cell connections, so they do not force radial divider lines. Non-smart elements still default to all boundaries drawn. The renderer and post-generation validator use the same boundary element builder, so validation checks the exact linework emitted into the SVG.

Smart pattern metadata does not force borders by default. Registries may set `force_inner_boundary`, `force_outer_boundary`, or `force_radial_boundaries` only when geometry inference cannot express a real requirement. The public `requires_*` values in API output are computed from inference plus those explicit force flags.

## Validation

There are two validation layers:

- `smart_patterns/` validates a single cell before SVG conversion.
- `pattern_validator.py` validates the assembled output after cell repetition.

The live API validates the assembled output with boundary linework included. Candidate patterns that pass cell-level smart validation but fail final boundary-inclusive validation are rejected before they become ring output.

## API Response

`POST /generate` returns:

```json
{
  "svg": "<svg ...>",
  "params_string": "Seed: ...",
  "used_seed": 12345,
  "validation": {
    "is_valid": true,
    "issue_count": 0,
    "unconnected_shape_count": 0,
    "tiny_region_count": 0,
    "issues": []
  },
  "pattern_usage": [
    {
      "ring_index": 0,
      "variation_index": 0,
      "name": "smart_petal",
      "category": "botanical",
      "is_fallback": false,
      "force_inner_boundary": false,
      "force_outer_boundary": false,
      "force_radial_boundaries": false,
      "requires_inner_boundary": true,
      "requires_outer_boundary": true,
      "requires_radial_boundaries": false
    }
  ]
}
```
