# Smart Pattern Expansion Plan

**Status:** Proposed

**Date:** 2026-08-21

**Scope:** Pattern vocabulary, reusable decorators, independently shaped ring
boundaries, coherent selection rules, stroke policy, validation, API, UI, and QA.

## 1. Objective

Expand MandalaForge without turning generation into unrelated random choices.
The finished system should produce designs that look intentionally composed:

- each design has a consistent geometric language;
- ring density follows a readable rhythm;
- motifs recur as controlled callbacks rather than accidental duplication;
- decorations are sparse and subordinate to the structural pattern;
- every shared ring boundary has one authoritative shape;
- stroke weight has a stable hierarchy and scales with output size;
- the seed reproduces the complete design and survives unrelated implementation
  changes as far as practical;
- structural linework remains fully connected and colourable;
- decorative linework may float or have free ends, but cannot create
  uncolourable spaces.

This is an expansion of the current smart-cell system, not a replacement for
its normalized coordinates, ring-atomic fallback, or topology QA.

## 2. Current Constraints to Preserve

1. A ring uses one structural pattern family across all divisions.
2. Structural side ports match across repeated cells and across variations.
3. Structural linework crosses the full radial depth of its ring so it cannot
   leave an un-crossed circular lane.
4. Structural open endpoints connect to a boundary or another structural
   vector.
5. Structural closed vectors touch a boundary or another structural vector.
6. The finished composite is checked for small or too-thin colour regions.
7. Pattern fallback remains ring-atomic.
8. All generation decisions are deterministic for the same inputs and seed.

Decorations deliberately relax items 4 and 5. They do not relax minimum-space,
cell containment, deterministic placement, or composite colourability.

## 3. Target Architecture

Split the present flat list of SVG-like element dictionaries into semantic
layers. Keep a compatibility adapter while existing patterns are migrated.

```python
@dataclass
class PatternOutput:
    structure: list[SmartVector]
    decorations: list[DecorationVector]
    boundary_claims: BoundaryClaims
    diagnostics: dict[str, object]

@dataclass
class DecorationVector:
    points: list[CellPoint]
    closed: bool = False
    hollow: bool = False
    stroke_role: str = "decoration"
    cadence: int = 1
    phase: int = 0
    kind: str = "accent"

@dataclass
class BoundaryProfile:
    kind: str
    nominal_radius: float
    amplitude_px: float
    repetitions: int
    phase: float
    render_mode: str

@dataclass
class StrokePolicy:
    base_width: float
    widths: dict[str, float]
    snap_tolerance: float
    whisker_tolerance: float
    pen_radius: float

@dataclass
class DesignRecipe:
    geometry_language: str
    motion: str
    ring_roles: list[str]
    density_targets: list[float]
    feature_ring: int
    boundary_plan: list[BoundaryProfile]
    decoration_budget: int
    accent_families: list[str]
    callback_motifs: list[str]
    stroke_style: str
```

Suggested modules:

```text
smart_patterns/
  core.py                 existing structural vector contract
  model.py                PatternOutput and semantic roles
  primitives.py           reusable outline and carrier builders
  decorators.py           echo, vein, rib, bead, eye, fringe, scroll
  decoration_validator.py relaxed decoration contract
  ring_geometry.py        boundary profiles and warped cell mapping
  stroke_policy.py        role-based stroke calculation
  style_grammar.py        design recipe and scored selection rules
```

`PatternOutput.structure` is validated by the strict current contract.
`PatternOutput.decorations` is validated by the decoration contract. Both are
then combined for final face-size and printability validation.

## 4. Reusable Primitive Library

Do not encode every observed design as a separate generator. Build patterns
from a smaller outline, carrier, and decorator vocabulary.

### 4.1 Outline primitives

- rounded petal;
- pointed lotus or ogive;
- almond or lens;
- teardrop;
- leaf;
- concave kite or hourglass;
- fan or shell;
- scallop;
- crescent;
- paisley or comma;
- circle, oval, diamond, and shield medallions;
- chevron, star point, stepped crown, and folded angular rail.

Each builder returns cell-space points and named attachment points such as
`base`, `tip`, `left_port`, `right_port`, `spine_vertices`, and
`carrier_vertices`. Decorators use those attachment points instead of guessing
where another vector happens to be.

### 4.2 Carrier primitives

- inner-to-outer axis spine;
- side-to-side arc;
- side-to-side wave;
- paired rail;
- scallop carrier;
- radial hub;
- medallion carrier;
- boundary-following contour.

Carriers solve two problems: structural connectivity and a legal place to put
decorations that should appear attached.

### 4.3 Decorators

Implement these as parameterized operations over outlines and carriers:

| Decorator | Behaviour | Primary safeguards |
|---|---|---|
| `echo` | Add 1-3 inset contours | Pixel-derived inset; join to base or allow as decoration |
| `midrib` | Add an axis through a petal or leaf | End on named outline vertices |
| `veins` | Add paired branches from a midrib | Count from available length and clearance |
| `fan_ribs` | Add rays between a hub and shell | End on sampled shell vertices |
| `parallel_stripes` | Add parallel lines inside a host | Remove lines that violate minimum gaps |
| `herringbone` | Alternate short diagonal ribs | End on a carrier or host boundary |
| `eye` | Insert a lens or seed shape | Treat as hollow decoration if detached |
| `beads` | Place circles along a carrier | Sparse cadence; validate hollow interior |
| `teeth` | Place small triangles along a carrier | Root triangles on the carrier |
| `fringe` | Add rounded slots or petals to an arc | Count from available arc length |
| `scales` | Add overlapping semicircles | Composite face-size validation required |
| `scroll_pair` | Add mirrored C/S curls | Free ends allowed only as decorations |
| `dot_row` | Add filled or hollow dots | Design-wide density budget |
| `diamond_marks` | Add loose diamonds | Hollow-space validation and sparse cadence |

All count decisions must be derived from available physical space:

```text
usable_length >= count * feature_width + (count - 1) * required_gap
required_gap = min_white_space + half_stroke_a + half_stroke_b
```

When space is insufficient, reduce count or remove the decorator. Do not shrink
details below their printability threshold and do not reject an otherwise valid
structural pattern because an optional decoration does not fit.

## 5. Decoration Contract

Decorations may be disconnected closed shapes or disconnected open strokes.
They use a separate contract rather than bypassing validation entirely.

### 5.1 Allowed

- floating filled dots;
- floating hollow circles, diamonds, eyes, and droplets;
- open spirals and curls with one or two free ends;
- detached echo contours;
- short hatch, fringe, ray, and texture strokes;
- decorations that touch or cross structural linework when the composite
  remains colourable.

### 5.2 Required checks

1. Stay inside the cell by default. A decoration that crosses a side boundary
   must opt into paired-port validation or be emitted as a ring-level element.
2. Remain inside the ring's warped inner and outer profiles.
3. A hollow decoration must retain an internal colourable area after accounting
   for half its stroke width on every side.
4. Any face created between a decoration and nearby linework must pass the
   existing area and pen-radius checks.
5. Open decoration strokes must meet minimum rendered length and must use round
   caps so their free endpoints look intentional.
6. Decorative crossings must not create pockets below `min_white_space`.
7. A decoration cannot be the only linework crossing a radial band. Decorations
   never satisfy the structural radial-coverage requirement.
8. Decorative overshoot uses the same bounded pixel channel as structural
   overshoot and cannot silently leave the cell.

### 5.3 Validation passes

Use two explicit topology passes:

1. **Structural pass:** structure plus required boundaries. Enforce connections,
   floating-open checks, radial coverage, dangles, and colourable faces.
2. **Composite pass:** structure, boundaries, and decorations. Ignore decoration
   connectivity, but enforce face area, pen fit, clearances, containment, and
   un-crossed lanes.

Preserve element roles through `Shape.raw_element`, or introduce a tagged
polyline type instead of discarding roles in `polylines_from_shapes()`.

### 5.4 Decoration budgets

Decorations must remain accents:

- complexity below `0.20`: no floating decorations;
- `0.20-0.49`: one decorated ring, one decoration family;
- `0.50-0.74`: at most two decorated rings and two families;
- `0.75-1.00`: at most `ceil(num_rings * 0.4)` decorated rings, capped at three;
- one ring may use one major decorator or two minor decorators;
- only one decoration family may repeat as a callback on a non-adjacent ring;
- decoration cadence must divide `num_divisions`;
- heavy accents use cadence 2, 3, or 4 when possible instead of appearing in
  every cell.

Filled dots count as minor accents. Hollow beads, medallions, paisleys, and
scrolls count as major accents.

## 6. New and Expanded Smart Patterns

### 6.1 First implementation group: low structural risk

1. `smart_arc_band`
   - One or more side-to-side arcs with a radial connector.
   - Provides the carrier used by several later decorators.

2. `smart_lens_band`
   - Opposing arcs form a boundary-touching almond between matched side ports.
   - Optional midrib or eye decoration.

3. `smart_webbed_fan`
   - Scalloped shell from an inner hub with 3-7 ribs.
   - Rib count comes from arc length and minimum gap.

4. `smart_fluted_fan`
   - Ginkgo-like outer lobe with tapered radial flutes.
   - Degrades to a plain shell in narrow cells.

5. `smart_veined_leaf`
   - Refactor `smart_leaf` to expose its midrib and outline attachment points.
   - Add 1-4 vein pairs according to available physical length.

6. `smart_nested_chevron`
   - Two or three side-connected V contours plus a full radial connector.
   - Echo spacing comes from the stroke policy and minimum white space.

7. `smart_tooth_crown`
   - A carrier arc with rooted triangular teeth, optionally alternating height.

8. `smart_petal_fringe`
   - A carrier arc with rounded lobes rooted on it.
   - Can also be implemented as a richer `smart_scallop_band` mode.

### 6.2 Second implementation group: layered outlines

9. `smart_echoed_petal`
   - Pointed or rounded petal with one or two interior echoes.
   - Interior echoes either join the base/midrib or carry decoration role.

10. `smart_concave_kite`
    - Closed boundary-anchored hourglass or concave diamond.
    - Optional echo and center spine.

11. `smart_scale_band`
    - Overlapping semicircular scales attached to a carrier.
    - Composite validation is mandatory because overlap pockets are the risk.

12. `smart_medallion_band`
    - Carrier-connected circles or ovals with a simple rosette or crosshair.
    - Internal rosette strokes end on the medallion outline.

13. `smart_beaded_arc`
    - Sparse filled or hollow beads placed along an arc.
    - Beads are decorations; the arc and radial connector are structural.

### 6.3 Third implementation group: expressive decorations and crossings

14. `smart_paisley_vine`
    - Structural vine or arc carrier with sparse paisley decorations.
    - Inner curl may have a free end.

15. `smart_scroll_vine`
    - Mirrored scroll decorations on a structural stem.

16. `smart_folded_ribbon`
    - Parallel angular rails producing a folded geometric band.
    - Start without over-under gaps; add true crossing semantics only after the
      validator understands interrupted strokes at crossings.

### 6.4 Existing pattern upgrades

- `smart_petal`: optional echo, eye, and midrib decorators;
- `smart_leaf`: reusable vein decorator and rounded/pointed outline modes;
- `smart_vine_band`: sparse bead, leaf, paisley, or scroll accents;
- `smart_scallop_band`: scale, tooth, and petal-fringe modes;
- `smart_fan` and `smart_deco_shell`: flutes, web ribs, and stripe modes;
- `smart_chevron_stack`: alternating-height crown and echo modes;
- `smart_star_point`: inset star and eye decorations;
- `smart_ripple_stack`: attached bead or droplet cadence;
- `smart_flame_band`: echoed flame or seed insert.

## 7. Independently Shaped Rings

### 7.1 Shared-boundary model

Do not give adjacent rings separate copies of their touching boundary. Model
`num_rings + 1` boundary profiles:

```text
Boundary 0   Ring 0   Boundary 1   Ring 1   ...   Boundary N
```

Ring `i` uses boundary `i` as its inner profile and boundary `i + 1` as its
outer profile. Ring `i` independently selects or owns its outer profile, but
that profile is the authoritative inner edge of ring `i + 1`.

This prevents gaps, overlaps, duplicate strokes, and incompatible neighboring
contours.

### 7.2 Initial boundary profiles

Implement in this order:

1. `circle`: zero amplitude and current behaviour;
2. `soft_lobe`: cosine-based flower lobes;
3. `scallop`: one-sided rounded arcs;
4. `pointed_lobe`: smooth lotus or star-like peaks;
5. `wave`: shallow alternating inward/outward motion;
6. `polygonal`: straight-sided facets aligned to divisions;
7. `alternating_crown`: alternating tall and short peaks.

Stepped or discontinuous profiles should wait until all continuous profiles
pass. Sharp corners amplify thin-region and stroke-join problems.

### 7.3 Profile rules

- Profile repetitions must divide `num_divisions`.
- Profile phase comes from a small discrete set: cell-aligned, half-cell offset,
  or alternating. Never choose an arbitrary phase per ring.
- Every profile segment must have the same radius at a shared wedge edge as the
  neighboring segment.
- A one-cell profile may keep the current rotate-one-definition rendering path.
  Alternating or multi-cell profiles declare a finite number of phase classes.
  Generate one warped structural definition per phase class rather than
  pretending every cell has identical geometry.
- The least common multiple of pattern-variation cadence, decoration cadence,
  and boundary phase classes must divide `num_divisions`.
- Profile geometry comes from a ring-stable seed stream.
- Adjacent high-amplitude profiles are forbidden.
- At most one inner or middle boundary may use strong amplitude below complexity
  `0.65`.
- The outermost contour may be stronger than internal contours.
- Amplitude is specified in pixels, then clamped by local ring width.
- Every sampled angle must satisfy:

```text
outer_profile(theta) - inner_profile(theta) >= required_local_ring_width
```

- `required_local_ring_width` is the maximum of the pattern's minimum width,
  `min_pattern_size`, and the stroke-policy clearance requirement.
- If a candidate profile violates width, binary-search its amplitude downward.
  If the result becomes visually negligible, use `circle`.

### 7.4 Warped cell mapping

Replace constant-radius interpolation with profile-aware interpolation:

```text
theta = cell_center_angle + angular * half_wedge_angle
inner = inner_profile.radius_at(theta)
outer = outer_profile.radius_at(theta)
radius = inner + radial * (outer - inner)
```

`SmartCellContext` becomes profile-aware while preserving normalized
`CellPoint`. Existing patterns then inherit shaped rings without being rewritten.

For a multi-cell profile, mapping also receives `division_index` or a profile
phase-class index. The ring asset builder validates every combined pattern and
profile phase used in the final cycle. Initial delivery should restrict profiles
to one identical segment per cell; add alternating crowns only after the
phase-class path is proven.

Update physical measurement helpers to use conservative local measurements:

- `ring_width` becomes minimum, average, and maximum local width;
- pattern size gates use minimum local width;
- cell-width gates sample the narrow end and relevant motif radius;
- arc subdivision follows both angular sweep and profile curvature;
- boundary inference uses profile contact, not constant-radius assumptions.

### 7.5 Boundary rendering

- Circular boundaries keep the current `auto` visibility policy.
- A non-circular profile defaults to visible because otherwise it has no visual
  identity as a ring contour.
- A shared profile is rendered once, in a boundary layer, using its own stroke
  role.
- The outermost boundary is always rendered unless a pattern explicitly emits
  a validated complete replacement contour.

### 7.6 Ring regeneration

- Pattern-only regeneration preserves both boundary profiles and changes only
  the selected ring's structure and decorations.
- Decoration-only regeneration preserves pattern and profiles.
- Shape regeneration changes the selected ring's outer profile. Because that
  boundary is shared, regenerate and revalidate the selected ring and the next
  ring. The outermost ring has no next-ring dependency.
- The API must return every affected ring fragment and the shared boundary
  fragment in one atomic response.

### 7.7 Radial ring-width rhythm

Replace independent random width weights with role-based width targets:

| Ring role | Starting weight |
|---|---:|
| `center` | 0.80 |
| `support` | 1.00 |
| `transition` | 0.82 |
| `feature` | 1.25 |
| `border` | 1.08 |

Normalize these weights across the available radial span, then solve them under
the following constraints:

- every ring must meet its selected pattern's minimum local width;
- adjacent nominal widths may not differ by more than `1.6x`;
- a shaped boundary's amplitude reserve is deducted before fitting patterns;
- if the requested set does not fit, first reduce profile amplitude, then drop
  optional detail, then select a lower-density pattern;
- never preserve an ornamental choice by collapsing another ring below its
  usable width;
- a preset may select among a small set of width rhythms, but it may not roll an
  unrelated random weight for every ring.

Useful rhythms include `even`, `feature-emphasis`, `border-emphasis`, and
`alternating-wide-narrow`. The recipe chooses one rhythm and applies it to all
rings coherently.

## 8. Stroke-Width Policy

The current system calculates pattern and boundary widths separately. Replace
both with one `StrokePolicy` created once per design.

### 8.1 Base width

Scale against the 612px reference canvas and apply a named style factor:

```text
scale = min(canvas_width, canvas_height) / 612
style_factor = fine: 0.88, regular: 1.00, bold: 1.18
complexity_factor = interpolate(1.06, 0.92, complexity)
base_width = clamp(1.5 * scale * style_factor * complexity_factor,
                   1.0 * scale,
                   2.25 * scale)
```

Complexity changes the width only slightly. Its primary effect remains detail
count. A dense design should drop detail before making lines too thin to print.

### 8.2 Semantic stroke roles

| Role | Multiplier | Use |
|---|---:|---|
| `outer_perimeter` | 1.35 | Final silhouette |
| `ring_boundary` | 1.15 | Visible shared profiles |
| `structure` | 1.00 | Main pattern outlines and carriers |
| `detail` | 0.80 | Veins, ribs, echoes, stripes |
| `decoration` | 0.76 | Dots, eyes, diamonds, curls |
| `micro` | 0.65 | Rare high-complexity texture only |

Resolve roles centrally. Patterns declare roles; they do not calculate numeric
stroke widths and do not randomize them.

### 8.3 Clearance rules

For two centerlines with widths `a` and `b`:

```text
required_centerline_gap = min_white_space + (a + b) / 2
```

For a hollow decoration, offset its boundary inward by half its stroke and
require the remaining interior to contain a disk whose diameter is at least
`min_white_space`. This handles hollow circles, diamonds, eyes, droplets, and
medallions consistently.

If a detail cannot satisfy clearance:

1. reduce detail count;
2. remove the lowest-priority detail tier;
3. simplify the host motif;
4. reject the pattern only if its structural form still fails.

### 8.4 Caps, joins, overshoot, and validator tolerances

- Structural boundary endpoints use butt caps.
- Free decoration endpoints use round caps.
- Curved outlines and decoration shapes use round joins.
- Angular Art Deco and geometric outlines may use bevel joins when a round join
  changes the intended shape.
- Overshoot cap becomes `min(3px * scale, 1.5 * structure_width)` and remains
  below whisker tolerance.
- Derive topology tolerances from the stroke policy rather than fixed pixels:
  snap tolerance approximately one maximum structural stroke;
  whisker tolerance approximately two structural strokes;
  pen radius scaled with output size.

## 9. Coherent Design Grammar

Randomness chooses among valid alternatives inside a recipe. It does not make
every decision independently.

### 9.1 Named seed streams

Derive stable streams from a hash of semantic names rather than relying on the
order of calls to one random generator:

```text
design/<seed>/recipe
design/<seed>/stroke
design/<seed>/boundary/<index>
design/<seed>/ring/<index>/pattern
design/<seed>/ring/<index>/variation
design/<seed>/ring/<index>/decoration
```

Adding a new random choice to a decoration must not change all later rings.

### 9.2 Recipe choices

Choose once per design:

- geometry language: curved, angular, or mixed;
- motion: radial, circular/banded, or balanced;
- stroke style: fine, regular, or bold;
- feature-ring position;
- density rhythm;
- allowed boundary-profile vocabulary;
- one dominant motif family;
- zero to two accent families;
- one optional non-adjacent callback motif.

### 9.3 Ring roles

Assign deterministic roles by radial position:

- `center`: simple hub-forming geometry;
- `support`: restrained pattern that establishes rhythm;
- `transition`: lower density between stronger rings;
- `feature`: highest detail and decoration budget;
- `border`: strong terminating contour or fringe.

For two rings use `center, border`. For three use `center, feature, border`.
For four or more, place at least one support or transition ring next to the
feature ring.

### 9.4 Density rhythm

Use a target sequence rather than independent density rolls. Examples:

- simple: `low, medium, medium, low`;
- balanced: `medium, low, high, medium`;
- ornate: `medium, high, low, high, medium`;
- radial emphasis: density rises toward the feature ring, then falls at border;
- border emphasis: interior remains restrained and the last ring is strongest.

Never place two maximum-density rings next to each other. A high-amplitude ring
profile also counts as visual density.

### 9.5 Pattern metadata

Extend registry descriptors with:

```text
geometry_language: curved | angular | mixed
motion: radial | banded | balanced
density: low | medium | high
ring_roles: allowed role set
decorator_tags: compatible decorators
profile_tolerance: circular_only | mild_warp | full_warp
visual_family: petal | leaf | fan | lattice | ribbon | wave | ...
```

### 9.6 Scored selection

Replace uniform `choice()` with scored candidates:

- hard-filter size, category, ring position, profile tolerance, and contract;
- reward ring-role compatibility;
- reward recipe geometry and motion compatibility;
- reward proximity to the ring's density target;
- reward the planned callback on its target ring;
- penalize the same visual family on adjacent rings;
- penalize repeating the same motion on three consecutive rings;
- penalize decoration or contour budget overflow;
- penalize a high-density pattern beside a high-amplitude profile;
- retain the top scoring candidates and use seeded weighted choice only among
  near-ties.

Record the winning score and reasons in diagnostics so generation is debuggable.

### 9.7 Variation rules

Stop choosing variation count by an unconstrained random integer.

- low-density rings use one variation;
- medium rings use two when `num_divisions` is divisible by two;
- feature rings may use 2, 3, or 4 based on divisors of `num_divisions`;
- structural ports, primary outline, ring profile, and stroke roles never vary;
- variations may change handedness, one interior decorator, echo count, or rib
  count within a one-step range;
- variation cadence must produce a complete repeating cycle.

## 10. API and UI

### 10.1 New design controls

Keep the default UI small:

- Style: `Balanced`, `Organic`, `Geometric`, `Ornate`, `Open`;
- Ring Shape: `Circular`, `Subtle`, `Expressive`;
- Decorations: `None`, `Sparse`, `Moderate`;
- Stroke: `Fine`, `Regular`, `Bold`.

Existing complexity and minimum pattern size remain authoritative. Presets map
to recipe constraints; they do not bypass validation.

### 10.2 Ring workflow

When a ring is selected, expose:

- regenerate pattern;
- regenerate decorations;
- change outer contour;
- simplify ring;
- inspect pattern, decorators, contour, density role, and stroke roles.

Changing a shared contour must clearly identify the adjacent ring that will be
reflowed.

### 10.3 API additions

Add optional request fields:

```json
{
  "style_preset": "balanced",
  "ring_shape_strength": "subtle",
  "decoration_level": "sparse",
  "stroke_style": "regular",
  "ring_overrides": {}
}
```

Expand `pattern_usage` or add `design_recipe` output containing:

- ring role and density target;
- selected pattern and score reasons;
- decorators and cadence;
- inner and outer boundary profile IDs;
- resolved stroke widths;
- simplifications or dropped decorators;
- fallback reason when applicable.

### 10.4 File impact map

| File or module | Planned responsibility |
|---|---|
| `smart_patterns/core.py` | Strict structure contract and profile-aware cell conversion |
| `smart_patterns/model.py` | Semantic pattern output and element roles |
| `smart_patterns/primitives.py` | Outlines, carriers, and named attachment points |
| `smart_patterns/decorators.py` | Reusable interior and floating accents |
| `smart_patterns/decoration_validator.py` | Relaxed connectivity and strict space checks |
| `smart_patterns/ring_geometry.py` | Boundary profiles, local widths, and warped coordinates |
| `smart_patterns/stroke_policy.py` | Role widths, caps, joins, overshoot, and tolerances |
| `smart_patterns/style_grammar.py` | Recipes, ring roles, seed streams, scoring, and budgets |
| Category modules | Pattern assembly from primitives and decorators |
| `pattern_generator.py` | Metadata filtering, scored selection, simplification, fallback |
| `coloring_generator.py` | Width rhythm, boundary ownership, layered rendering, regeneration |
| `shape_extractor.py` | Preserve semantic roles on extracted geometry |
| `topology_validator.py` | Role-aware or split structural/composite analysis |
| `app.py` | New request parameters and atomic multi-ring regeneration response |
| `templates/index.html` | Top-level and selected-ring controls |
| `static/script.js` | Recipe parameters, diagnostics, and multi-fragment replacement |
| `qa_patterns.py` | Pattern, decorator, profile, and stroke matrices |
| `qa_report.py` | Corpus and visual regression coverage |
| Documentation | Updated architecture, authoring rules, and registry inventory |

## 11. Implementation Phases

### Phase 0: Baseline and fixtures

- Run and record the current per-pattern smoke/full harness and 90-design corpus.
- Pin representative SVG fixtures for circular-ring output.
- Add seed-determinism tests.
- Correct documentation references that still mention removed validators.

**Gate:** Current behaviour remains green before refactoring.

### Phase 1: Semantic output and stroke policy

- Add `PatternOutput`, element roles, and the compatibility adapter.
- Add centralized `StrokePolicy`.
- Route structure, details, decorations, boundaries, and perimeter through roles.
- Derive topology tolerances from the policy.
- Migrate current patterns without visual or topological change.

**Gate:** Existing patterns and corpus remain green; SVG uses consistent role
widths at 612px and at least one larger export size.

### Phase 2: Decoration contract

- Add `DecorationVector` and decoration validation.
- Preserve roles through shape extraction.
- Split structural and composite topology passes.
- Add cadence-aware decoration rendering.
- Implement `echo`, `eye`, `dot_row`, `diamond_marks`, and `beads` first.

**Gate:** A structural floating line still fails. A tagged free spiral may pass.
A hollow floating shape fails when its usable interior is below the configured
minimum. Composite tiny pockets always fail.

### Phase 3: Primitive and decorator library

- Add named outline attachment points and carrier builders.
- Implement veins, ribs, stripes, herringbone, teeth, fringe, scales, and
  scroll-pair decorators.
- Refactor existing petal, leaf, vine, scallop, fan, shell, chevron, star,
  ripple, and flame patterns to use the shared operations.

**Gate:** Decorator counts degrade monotonically with available space and never
force fallback when the undecorated host remains valid.

### Phase 4: New pattern groups

- Land the low-risk group one pattern at a time.
- Land layered patterns only after their host primitives pass the full matrix.
- Land paisley, scroll, and ribbon work last.
- Add explicit size gates and compatible decorator/profile metadata for every
  pattern.

**Gate:** Every registered pattern passes `qa_patterns.py --tier full`, including
decoration-on and decoration-off cases.

### Phase 5: Boundary profiles and ring warping

- Introduce `BoundaryProfile` with circle-only behaviour first.
- Move all polar mapping and boundary rendering through `ring_geometry.py`.
- Add continuous profiles one at a time.
- Add local-width clamping and profile-aware size gates.
- Make ring-fragment regeneration dependency-aware.

**Gate:** No sampled profile pair crosses or falls below required width. All
supported division counts close exactly at cell seams. Pattern ports remain
stable after warping.

### Phase 6: Design recipe and scored selection

- Add named seed streams.
- Add pattern metadata and ring roles.
- Replace uniform selection, unconstrained ring-width variation, and random
  variation count with the recipe and scoring rules.
- Add selection diagnostics to API output.

**Gate:** Same seed and inputs produce the same recipe and SVG. Adjacent pattern,
density, profile, and decoration constraints hold across a large seed sweep.

### Phase 7: UI and ring-specific controls

- Add the four top-level design controls.
- Add selected-ring pattern, decoration, and contour actions.
- Update ring replacement to accept multiple affected fragments atomically.
- Display concise recipe and ring diagnostics.

**Gate:** Pattern-only regeneration leaves contours and other rings unchanged.
Shape regeneration changes only the shared boundary and its two dependent rings.

## 12. QA Matrix

Extend automated QA across:

- divisions: `6, 8, 12, 16, 24`;
- rings: `2, 3, 5, 7`;
- complexity: `0.15, 0.35, 0.5, 0.7, 0.9`;
- minimum white space: `5, 10, 25, 50`;
- stroke styles: fine, regular, bold;
- ring shapes: circular, subtle continuous, expressive continuous;
- decorations: none, sparse, moderate;
- every pattern forced on first, middle, and last rings where allowed;
- at least two canvas sizes;
- normal generation and ring regeneration.

Add focused cases for:

1. disconnected structural open vector fails;
2. disconnected decorative open vector passes connectivity;
3. hollow decoration below minimum internal space fails;
4. filled dot does not require internal space;
5. decoration creates tiny pocket against structure and fails;
6. decoration cadence closes symmetrically;
7. adjacent boundary profiles never overlap;
8. high-amplitude profile is clamped or replaced;
9. warped left/right ports still match;
10. profile regeneration updates both dependent rings atomically;
11. role-based strokes scale with canvas size;
12. unavailable detail is dropped before structural fallback;
13. seed streams isolate unrelated choices;
14. every selection has recorded score reasons;
15. decoration and contour budgets are never exceeded.

Visual QA should include a pinned sheet covering:

- one design per style preset;
- low, medium, and high complexity;
- every boundary profile;
- every stroke style;
- examples with free curls, hollow accents, filled dots, nested outlines, and
  decorated carriers.

## 13. Acceptance Criteria

- All existing structural QA remains green.
- Every new pattern passes the full forced-pattern matrix.
- Floating or open decorations are allowed only when explicitly tagged.
- Hollow decorations satisfy the configured usable internal-space minimum.
- Decorations never exempt tiny composite regions.
- Non-circular shared boundaries render once and close without seams.
- Every ring retains its required local width at every angle.
- Stroke widths come from semantic roles and one design policy.
- Complexity changes detail count more than stroke thickness.
- Pattern, contour, density, and decoration choices follow a recorded recipe.
- Seeded output is deterministic.
- Pattern-only ring regeneration remains local.
- Shape regeneration reflows only the two rings sharing the changed boundary.
- API diagnostics distinguish intended selection, simplification, alternate
  fallback, and safe-spoke fallback.

## 14. Deferred Work

- True Celtic over-under rendering with stroke gaps at crossings;
- decorations spanning arbitrary numbers of cells;
- asymmetric divisions or per-ring division counts;
- arbitrary hand-drawn ring contours;
- filled black regions as a separate visual language;
- cross-ring motifs that occupy several rings as one structural object.

These require new topology or composition semantics and should not block the
pattern, decoration, ring-profile, stroke, and recipe work above.
