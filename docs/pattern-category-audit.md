> Note: the smart-pattern layer described here was retired on 2026-10-07 in favour of [docs/motifs.md](motifs.md).

# Pattern Category Audit

This audit separates the active smart-pattern system from the older pattern libraries.

## Current Routing

`pattern_generator.py` currently uses the `smart_patterns/` package.

The files under `patterns/` still contain many older SVG generators, but they are not currently selected by the app. Treat them as reference material until each one is ported into the smart vector contract.

## Verification Snapshot

Current active checks:

- Botanical-only generation: passes validation.
- Geometric-only generation: passes validation.
- Celtic-only generation: passes validation.
- Art deco-only generation: passes validation.
- Abstract-only generation: passes validation.
- Mixed-category generation: passes validation.
- 200 randomized generation-only cases: zero generation failures.

## Active Smart Patterns

21 registered patterns plus a per-category `smart_<category>_safe_spoke`
fallback. All are covered by `qa_patterns.py`.

| Category | Patterns |
|---|---|
| Botanical | `smart_petal`, `smart_leaf`, `smart_vine_band`, `smart_scallop_band` |
| Geometric | `smart_diamond`, `smart_prism_lattice`, `smart_triangle_band`, `smart_star_point`, `smart_chevron_stack` |
| Celtic | `smart_laced`, `smart_braid_knot`, `smart_greek_key`, `smart_twist_band` |
| Art Deco | `smart_fan`, `smart_stepped_band`, `smart_sunburst`, `smart_deco_shell` |
| Abstract | `smart_bridge_band`, `smart_resonance_ladder`, `smart_ripple_stack`, `smart_flame_band` |

## Dormant Legacy Patterns

The `patterns/` package was deleted on 2026-08-21. The tables below are kept as
a port-risk assessment; the motif descriptions are in the inventory at the end
of this document.

### Botanical

| Pattern | Legacy status | Smart-port risk | Notes |
|---|---:|---:|---|
| `petal_simple` | Dormant | Medium | Good candidate for porting; must ensure petal edge and center line connect without slivers. |
| `petal_layered` | Dormant | High | Layered interiors are likely to create tiny spaces unless built with explicit connection points. |
| `petal_pointed` | Dormant | Medium | Good candidate after `petal_simple`; watch pointed joins near ring boundaries. |
| `leaf_simple` | Dormant | Medium | Needs paired side ports or boundary anchoring. |
| `leaf_round` | Dormant | Medium | Similar to `leaf_simple`; rounded shape must not float. |
| `teardrop` | Dormant | Medium | Good smart-shape candidate if its tip and base are explicitly connected. |
| `scallop_border` | Dormant | Low | Strong candidate for early porting because it naturally repeats along side boundaries. |
| `dots_row` | Dormant | High | Closed dots are floating islands under the current contract unless connected or converted to filled marks. |
| `arc_band` | Dormant | Low | Good early candidate; arcs can become paired side-to-side bridges. |
| `flower_center` | Dormant | High | Center-only special case; should be handled as a dedicated first-ring pattern. |

### Geometric

| Pattern | Legacy status | Smart-port risk | Notes |
|---|---:|---:|---|
| `triangle_solid` | Dormant | Low | Good early candidate. Boundaries are explicit and easy to normalize. |
| `triangle_inverted` | Dormant | Low | Good early candidate. |
| `diamond` | Dormant | Already represented | Current `smart_diamond` covers the core behavior. |
| `diamond_chain` | Dormant | Medium | Repeated small diamonds can create undersized spaces. |
| `chevron` | Dormant | Low | Good candidate if arms terminate on boundaries or shared center point. |
| `chevron_nested` | Dormant | Medium | Nested lines need spacing checks. |
| `star_point` | Dormant | Medium | Watch sharp tips and boundary protrusion. |
| `rays` | Dormant | Low | Already conceptually similar to `smart_fan`; easy to port. |
| `rays_tapered` | Dormant | Medium | Tapered closed shapes can create small tip pockets. |
| `zigzag` | Dormant | Medium | Needs exact side-port matching. |
| `concentric_arcs` | Dormant | Low | Good early candidate if arcs are side-to-side bridges. |

### Celtic

| Pattern | Legacy status | Smart-port risk | Notes |
|---|---:|---:|---|
| `knot_simple` | Dormant | Medium | Crossings need explicit spacing and intentional over/under behavior later. |
| `knot_loop` | Dormant | High | Loops can float unless tied to boundaries or other vectors. |
| `braid` | Dormant | High | Dense crossings need minimum-space enforcement. |
| `braid_simple` | Dormant | Medium | Better first celtic port than full `braid`. |
| `spiral` | Dormant | High | Spiral endpoints often float. Needs explicit anchors. |
| `triskele` | Dormant | High | First-ring special case; likely needs its own center rules. |
| `key_pattern` | Dormant | Medium | Angular geometry is port-friendly, but spacing must be tested. |
| `interlace_band` | Dormant | High | Should wait until there is a better crossing/over-under model. |

### Art Deco

| Pattern | Legacy status | Smart-port risk | Notes |
|---|---:|---:|---|
| `fan` | Dormant | Already represented | Current `smart_fan` is the simplified active version. |
| `fan_layered` | Dormant | Medium | Good next step if layer spacing is derived from `min_white_space`. |
| `sunburst` | Dormant | Low | Good candidate; similar to fan/rays. |
| `sunburst_filled` | Dormant | Medium | Closed wedges need tip and pocket checks. |
| `stepped_pyramid` | Dormant | Low | Good candidate; straight segments and stable corners. |
| `stepped_band` | Active as `smart_stepped_band` | Low | Ported as a side-paired stepped skyline band. |
| `feather` | Dormant | Medium | Interior ribs can create slivers if they cross the feather outline. |
| `deco_rays` | Dormant | Low | Good candidate. |
| `fountain` | Dormant | Medium | Multiple open curves need endpoint anchoring. |

### Abstract

| Pattern | Legacy status | Smart-port risk | Notes |
|---|---:|---:|---|
| `swirl` | Dormant | High | Open curve endpoints must be anchored. |
| `double_swirl` | Dormant | High | Same as `swirl`, plus crossing risk. |
| `wave` | Dormant | Low | Good candidate; current `smart_bridge_band` already proves this direction. |
| `wave_stacked` | Dormant | Medium | Needs minimum spacing between wave lines. |
| `crescent` | Dormant | Medium | Closed shape must touch boundary or another vector. |
| `crescent_nested` | Dormant | High | Nested closed shapes risk floating islands. |
| `flame` | Dormant | Medium | Tip and side contacts need careful handling. |
| `droplet` | Dormant | Medium | Similar to teardrop. |
| `bubbles` | Dormant | High | Floating circles violate the smart contract unless connected or decorative-filled. |
| `ribbon` | Dormant | Medium | Good later candidate once parallel-curve spacing is robust. |

## Where To Add Patterns First

Start with low-risk patterns that exercise one rule at a time.

1. Add side-to-side linework variants:
   - `smart_arc_band`
   - `smart_wave_stacked`
   - `smart_concentric_arcs`

2. Add simple closed boundary-touching shapes:
   - `smart_triangle`
   - `smart_inverted_triangle`
   - `smart_teardrop`
   - `smart_stepped_pyramid`

3. Add layered variants only after the above pass:
   - `smart_fan_layered`
   - `smart_chevron_nested`
   - `smart_petal_layered`

4. Delay high-risk floating or dense-crossing patterns:
   - dots,
   - bubbles,
   - spirals,
   - full braid/interlace,
   - triskele.

## Recommended Test Pattern Workflow

For each new pattern:

1. Add one generator function to the relevant `smart_patterns/` category module.
2. Register it in `SMART_PATTERNS`.
3. Test category-only generation.
4. Test mixed-category generation.
5. Run generation stress with high `num_divisions`, high `num_rings`, and large `min_pattern_size`.
6. Only then add complexity-based extra lines or nested shapes.

## Immediate Next Pattern Candidates

Best next three:

1. `smart_arc_band`: abstract. Low risk. Tests side-to-side arcs.
2. `smart_triangle`: geometric. Low risk. Tests closed shape boundary contacts.
3. `smart_deco_rays`: art deco. Low risk. Tests short radial ray accents without side-port requirements.

Do not start with dots, bubbles, spirals, or dense celtic braids. Those need additional semantics for connected decorative marks, over/under crossings, or intentional floating filled shapes.

---

# Legacy Motif Inventory (archived 2026-08-21)

The `patterns/` package was deleted on 2026-08-21. It was 3,154 lines across 48
generator functions and was never imported — `pattern_generator.py` has always
routed to `smart_patterns/`. Its geometry used an incompatible API (raw
`inner_radius/outer_radius/wedge_angle` rather than normalized cell space) and
several functions carried real bugs, so the code was not worth porting. The
*design vocabulary* was, and it is recorded here.

All 48 were single-wedge motifs; there was never a full-ring generator.

Contact key: **I** inner radius · **O** outer radius · **S** reaches side edges ·
**F** floats free of all boundaries · **TILE** authored to abut into a
continuous band across wedges.

## Botanical (10)

| motif | description | contact |
|---|---|---|
| `petal_simple` | rounded teardrop petal, base pinched at inner, tip at outer, optional center vein | I·O·S |
| `petal_layered` | 2–3 concentric nested petals, each inset 15%, strokes thinning inward | I·O·S |
| `petal_pointed` | sharp lotus kite with shoulders at 35% height, center + 2 angled veins | I·O·S |
| `leaf_simple` | pointed asymmetric leaf, center vein + 2 pairs of side veins | I·O·S |
| `leaf_round` | fuller egg-shaped leaf, no veins | F |
| `teardrop` | droplet, sharp point inward, fat round top outward, optional inner echo | I·O |
| `scallop_border` | row of scallop swags hanging from the outer edge, optional trough dots | TILE·O |
| `dots_row` | 3 or 5 filled dots evenly spaced at mid-radius | F |
| `arc_band` | boxed arc segment: two concentric arcs closed by radial connectors | S, near-I/O |
| `flower_center` | first-ring petal + center line + 2 axis dots (near-duplicate of `petal_simple`) | I·O·S |

## Geometric (11)

| motif | description | contact |
|---|---|---|
| `triangle_solid` | isoceles triangle, base on inner, apex at outer, optional echo | I·O·S |
| `triangle_inverted` | downward triangle, chord near outer, apex toward center | F |
| `diamond` | 4-point rhombus touching all four boundaries, optional cross-hairs | I·O·S |
| `diamond_chain` | 2–3 small diamonds stacked radially | F |
| `chevron` | filled V pointing outward with a notch vertex at 40% | S |
| `chevron_nested` | 2–3 open Vs stacked radially, arms shrinking outward | F |
| `star_point` | one spike of an n-pointed star; open path so repeats close the star | S |
| `rays` | 3 or 5 plain straight radial lines | spans angle |
| `rays_tapered` | single solid beam widening outward | F |
| `zigzag` | sawtooth alternating between inner+20% and outer−20% | TILE |
| `concentric_arcs` | 3 or 5 stacked arc segments, strokes thinning outward | S |

## Celtic (8)

| motif | description | contact |
|---|---|---|
| `knot_simple` | X of two crossing bands + circle at the crossing (no over/under) | F |
| `knot_loop` | figure-eight: two side curves linking inner and outer levels | F |
| `braid` | three strands, angular position sine-modulated at 2π/3 phase offsets | S |
| `braid_simple` | two quad curves crossing once — an X of curves | F |
| `spiral` | Archimedean spiral, 1.5–2.5 turns | F |
| `triskele` | first-ring center circle + curved arm + curl | center·O |
| `key_pattern` | Greek/Celtic meander, 10-vertex orthogonal staircase, asymmetric | TILE·S |
| `interlace_band` | two quad curves crossing at cell center, one bowing out, one in | TILE·S |

## Art Deco (9)

| motif | description | contact |
|---|---|---|
| `fan` | solid shell, apex at inner, arc across outer, 3/5/7 ribs | I·O·S |
| `fan_layered` | open fan skeleton, 3–4 nested arcs + two edge lines | F |
| `sunburst` | 5 or 7 rays with alternating lengths and stroke weights | near-I·S |
| `sunburst_filled` | row of 3 or 5 solid triangular spikes | F |
| `stepped_pyramid` | ziggurat, 3–4 stacked quads narrowing outward | I·S |
| `stepped_band` | crenellated band, 4 or 6 alternating tall/short blocks | TILE |
| `feather` | central radial spine with 4–6 pairs of barbs narrowing to the tip | near-I/O |
| `deco_rays` | focal point at inner edge, outer arc, boundary rays + thin inner rays | S |
| `fountain` | 3 or 5 spray jets arcing out from a single base point | S |

## Abstract (10)

| motif | description | contact |
|---|---|---|
| `swirl` | single S-curve sweeping diagonally, optional parallel second curve | F |
| `double_swirl` | two mirrored curves rising from lower corners to meet on the outer axis | F |
| `wave` | sinusoid oscillating radially about mid-radius, 2–3 wavelengths | TILE·S |
| `wave_stacked` | 3–4 parallel low-amplitude ripples at different radii | TILE·S |
| `crescent` | lune from an outer arc closed against a smaller counter-arc | F |
| `crescent_nested` | 2–3 nested lunes stacked inward | F |
| `flame` | closed flame, wide base on inner, sides bulging to edges, tip at outer | I·O·S |
| `droplet` | water drop, point inward, round top outward, optional highlight | F |
| `bubbles` | cluster of 3 or 5 circles of varying radius around mid-radius | F |
| `ribbon` | closed twisting band from two offset curves joined at both ends | F |

## Porting guidance

Deduped, the 48 functions collapse to ~24 ideas in four structural families:

- **Radial fills** — petal, leaf, teardrop/droplet, flame, triangle, diamond,
  star spike, tapered beam, fan/shell, stepped pyramid
- **Angular tiling bands** — scallop swag, zigzag, sine wave, stacked ripples,
  crenellated blocks, Greek key, interlace crossover, braid
- **Line textures** — radial rays, alternating sunburst, feather, concentric
  arcs, fountain spray
- **Floating accents** — dot row, bubbles, spiral, crescent, ribbon, S-swirl,
  X-knot

The first three families map cleanly onto the smart-cell archetypes. **Floating
accents cannot be ported literally** — the contract forbids ink that touches
nothing. Port them as accents anchored to a carrier line (see
`docs/smart-patterns.md`).

Already covered by `smart_patterns/`: fan, stepped band, petal, leaf, vine band,
laced cell, braid knot, diamond, prism lattice, bridge band, resonance ladder.

Known defects in the deleted code, for anyone tempted to recover it from a
backup: `spiral` used absolute cartesian angles and was not wedge-oriented;
`triskele` redrew the mandala center circle once per wedge; `knot_simple` and
`braid_simple` had no over/under gaps so they did not read as interlace; `braid`
sampled too coarsely to look curved; `crescent` carried dead path-building code;
`flower_center` duplicated `petal_simple`. Most band motifs stopped at 0.8–0.9
of the half-angle, so tiled copies showed a seam at every wedge boundary.
