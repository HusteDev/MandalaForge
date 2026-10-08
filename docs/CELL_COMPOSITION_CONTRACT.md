> Note: the smart-pattern layer described here was retired on 2026-10-07 in favour of [docs/motifs.md](motifs.md).

# Cell composition and guide-independent linework

Status: design contract and implementation proposal; runtime unchanged.
Date: 2026-10-03.
Basis: user's annotated four-ring reference and current generator source.

## Governing rule

A ring defines where a repeating composition is anchored. Each cell contains
one or more reusable motifs. Their actual ink may extend beyond the cell's
nominal radial bounds. Ring circles and section rays are construction guides;
they are not automatically printable lines, clipping boundaries, or connections.

Ownership, placement, extent, and connectivity are separate properties. A stem
owned by ring 4 can occupy ring 3 without becoming a ring-3 motif.

## Reference decomposition

| Ring, inside to outside | Cell composition | Relationship |
| --- | --- | --- |
| 1, teal | Lower carrier forming a smaller ring; petal motif | Petal attaches to carrier; repeated neighboring cells complete the rhythm |
| 2, orange | One curved motif | Its silhouette may cross a nominal ring guide |
| 3, purple | Diamond; dominant center petal; adjoining petals | Two or three reusable motifs depending on whether adjoining petals are integral to the dominant petal |
| 4, lime | Inward stem; small center petal; large center petal; outward petal | Shared attachment/root relationships; stem occupies the preceding ring; outward petal passes the outer guide |

The outer ring has 12 equally spaced sections. The first three also have
equally spaced sections, but their counts are not specified. Store count and
angular phase per ring rather than inferring a single global count. Equal
spacing does not require equal counts, equal ring widths, or equal motif sizes.

A motif can emit several paths. A path count is not a pattern count. Nesting
alone does not require separately randomized patterns: use an independent motif
when it needs independent selection, parameters, placement, or editing.

## Terms and data responsibilities

- **RingLayout:** inner/outer guide radius, section count, angular phase.
- **CellFrame:** the nominal annular sector used to position motif geometry.
- **MotifDefinition:** reusable shape logic, parameter ranges, anchors, emitted
  paths, allowed extent, and compatibility information.
- **MotifInstance:** selected definition, parameters, role, owner ring/cell,
  placement, and declared attachments.
- **CellComposition:** compatible motif instances and their shared constraints.
- **RingRecipe:** composition repeated around a ring, including any deliberate
  variation schedule. The recipe is the atomic unit for selection and fallback.
- **DesignRecipe:** ring layouts, ring recipes, cross-ring constraints, seed,
  and recipe version.
- **Guide:** nonprinting positioning geometry.
- **Ink:** printable geometry. A circular carrier may coincide with a guide,
  but must be explicitly selected as ink.

Example roles are carrier, stem, primary petal, inner petal, side petal, and
accent. Roles explain relationships; they should not become mandatory slots
that force every cell to contain every motif.

## Placement and attachment

Continue using normalized cell coordinates for authoring:

```text
radius = inner_radius + radial * (outer_radius - inner_radius)
angle  = phase + cell_index * (360 / sections)
         + angular * (180 / sections)
```

Here radial 0 and 1 locate guides, not legal-ink limits. Approved geometry can
use radial values below 0 or above 1. Initially retain angular values within
[-1, 1]; joins on section edges must meet the rotated neighbor. Angular
overflow is a separate capability and is not required by this reference.

Resolve named anchors before generating final curves. For example, a stem tip,
small-petal root, and large-petal root can reference the same resolved root
point. Avoid independently sampled coordinates followed by approximate snapping.
Nested petals share an axis and fit relationship; they need not be identical
scaled copies. Side petals can join neighboring instances on a section edge.

Distinguish anchor constraints:

- attachment: touches actual ink at a resolved point;
- nesting: contained by another motif with printable clearance;
- seam: meets the rotated neighboring cell at the same world point;
- clearance: stays separated from another motif;
- crossing: intentional intersection with declared topology.

Touching a guide satisfies none of these ink relationships. A closed diamond
may be a separate colorable accent without touching a petal. The reference does
not establish that every closed shape must join one global ink component.

## Controlled radial overflow

Give each motif an explicit permitted inward/outward extent, measured in output
units or as a declared fraction of ring width. Resolve it against available
neighbor space and page margins. Record actual bounds after placement.

An inward stem and an outward closed petal are real shape extensions. The
existing 3px endpoint overshoot is a different feature and cannot represent
them. Do not clamp approved geometry back onto the guide or hide it with a
ring clip. Reject or refit an excessive extension explicitly.

Overflow permission does not authorize collisions. Check all actual affected
motifs, including adjacent cells and neighboring rings. A crossing may be a
junction, a deliberately separated over/under treatment, or invalid. SVG paint
order alone does not determine a valid connection or erase unwanted ink.

For different section counts, resolve cross-ring attachments in world polar
coordinates. Equal local angular coordinates in two cells are not necessarily
the same angle. If repeating 12 motifs against N motifs, the whole composition's
guaranteed rotational symmetry is determined by the layouts and motif schedules;
for simple uniform repetitions it is gcd(12, N), not automatically 12.

## Validation contract

Validate local motif geometry, then the assembled drawing. Independent motifs
need not span the ring, match their own side ports, or connect without their
composition partners. Those checks belong to the composition where applicable.

1. No guide is added as ink to rescue an endpoint. Structural endpoints must
   meet actual ink; an intentional decorative free end needs an explicit role.
2. Closed isolated motifs are permitted when declared and large enough to
   color. They must not become accidental orphan fragments.
3. Check seam contacts after rotation and across the actual variation schedule.
   Unconnected motifs do not need artificial seam ports.
4. Check regions and clearance on final physical geometry, including strokes:
   centerline gap >= minimum white space + (stroke_a + stroke_b) / 2.
5. Check unintended crossings, tiny pockets, duplicate shared paths, collapsed
   shapes, and printable-page extent in the full affected neighborhood.
6. Treat broad blank annuli as a composition/density rule. Coverage can come
   from several motifs or neighboring-ring overflow. Do not force a spine into
   every motif or forbid an intentionally selected circular band.
7. Guides provide no topology edges. A partial validation frontier is not proof
   of a real cross-ring connection in the completed drawing.

The assembled motif contours provide enclosures. Explicit carriers and borders
remain valid design elements, including circles, when the recipe selects them.

## Composition selection

Select compatible recipes rather than independently choosing arbitrary motifs.
Resolve shared roots, axes, relative sizes, nesting, and overflow before drawing.
Complexity controls optional detail and density within a coherent composition.
If an inner petal cannot fit, omit or simplify it before replacing the whole
recipe. Preserve required attachment relationships during simplification.

Use stable named random streams keyed by design seed, ring, motif instance,
and parameter role. Seam and shared-anchor values must remain stable across
variations. Save resolved recipes so replay and editing do not depend solely
on the current registry ordering.

## Current implementation gaps

| Current source | Conflict | Required change |
| --- | --- | --- |
| `pattern_generator.py`: `select_pattern_for_ring`, `generate_ring_variations` | One registered generator selected per ring | Select a composition recipe; retain whole-ring fallback and coordinated variation |
| `coloring_generator.py`: `self.wedge_angle`, `_generate_ring_assets`, `_validate_design` | One global division count/angle used for placement and validation | Carry each ring's count/phase through generation, rotation, extraction, and API state |
| `smart_patterns/core.py`: `to_cartesian`, `_contract_issues` | Coordinates clamped; real radial overrun rejected | Validate explicit extent, then transform approved unclamped coordinates |
| `smart_patterns/core.py`: `SmartVectorAnalyzer` | Local boundary contact and coverage stand in for composition connectivity | Add motif roles/anchors and composition validation without imaginary guide edges |
| `coloring_generator.py`: `_infer_boundary_requirements_from_elements`, `_get_boundary_element_dicts` | Dangling guide contacts can trigger printed circles | Emit only explicitly selected ink carriers/borders; reject unresolved endpoints |
| `coloring_generator.py`: `generate_ring_fragment` | Ring replacement is validated without complete neighbor state | Validate replacement with affected neighbor geometry and update any dependent shared anchors |

The current `docs/smart-patterns.md` says radial coordinates can leave the cell,
but runtime rejects substantial overrun and clamps the transform. Its later
Deliberate Bleed section documents the narrower implemented feature. Neither
is full motif overflow.

This contract revises the August expansion plan where it preserves one
structural pattern per ring, per-pattern full-depth coverage, boundary-based
connections, and decorative containment. Shared boundary profiles may still
describe shared guides; sharing a guide does not imply drawing it.

## Implementation sequence and acceptance

1. Build one deterministic four-ring reference recipe using explicit motif
   instances. Keep the first three section counts configurable; set ring 4 to
   12. Render guides in a separate debug group excluded from print/export.
2. Introduce recipe/anchor/extent types and a compatibility adapter for legacy
   generators. Keep legacy validation on legacy output while adding the new
   composition contract; do not globally disable checks.
3. Implement approved radial overflow and neighbor-aware validation. Demonstrate
   an orange curve outside its guide, an inward stem, and an outward closed
   petal without clipping or boundary-circle repair.
4. Replace single-pattern selection with compatible recipe selection; propagate
   per-ring divisions and phase through saved state, API, UI, and validation.
5. Make regeneration dependency-aware: preserve layout, regenerate the selected
   recipe, validate all affected contacts, and return a consistent update. If
   changed shared anchors require neighbor changes, include them explicitly.

Acceptance examples:

- A guide-free export retains teal carrier/petals, orange curve, purple layered
  motifs, and the four lime roles. No guide appears as a closure line.
- Nested/attached components share intended roots; repeated seams have no gaps
  or duplicate strokes, including the last-to-first cell seam.
- An unattached endpoint exactly on a magenta guide fails structural validation.
- A closed, adequately sized diamond passes as an explicitly declared accent.
- A legal protruding closed petal passes; excessive overflow or a tiny pocket
  created in the preceding ring fails.
- Multiple motifs collectively satisfy density intent without added spines.
- Distinct ring counts and phases render and validate using their own layouts.
- Seed plus saved recipe reproduces the composition. Regeneration detects
  collisions with unchanged neighboring motifs before replacing SVG.

Runtime implementation and rendered reference validation remain future work.
