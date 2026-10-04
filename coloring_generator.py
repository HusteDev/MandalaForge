"""
Mandala Coloring Page Generator

Generates procedural mandala designs with perfect radial symmetry.
Each ring contains a single pattern that is rotated around the center.
"""

import svgwrite
import random
import math
from typing import Any


class DesignGenerator:
    """
    Generates mandala-style coloring page designs.

    Architecture:
    - All rings are circular (no polygon support)
    - Each ring gets ONE pattern that is rotated for radial symmetry
    - Patterns are selected from enabled categories
    - Complexity controls detail level within patterns
    """

    def __init__(
        self,
        seed: int = None,
        canvas_size: tuple[int, int] = (612, 612),
        num_divisions: int = 12,
        num_rings: int = 4,
        complexity: float = 0.5,
        min_pattern_size: int = 8,
        categories: list[str] = None,
        # Debug options
        draw_rings: bool = False,
        draw_divisions: bool = False,
        colored_rings: bool = False,
        force_pattern_name: str = None
    ):
        # Set seed for reproducibility
        self.seed = seed if seed is not None else random.randint(0, 1000000)
        random.seed(self.seed)
        self.rng = random.Random(self.seed)

        # Canvas setup
        self.width, self.height = canvas_size
        self.center_x = self.width / 2
        self.center_y = self.height / 2
        self.center = (self.center_x, self.center_y)

        # Design parameters
        self.num_divisions = num_divisions
        self.num_rings = num_rings
        self.complexity = max(0.0, min(1.0, complexity))
        self.min_pattern_size = min_pattern_size
        self.categories = categories or ['botanical']

        # Derived values
        self.wedge_angle = 360.0 / self.num_divisions

        # Debug options
        self.draw_rings = draw_rings
        self.draw_divisions = draw_divisions
        self.colored_rings = colored_rings

        # Calculate ring system
        self._calculate_rings()
        self.force_pattern_name = force_pattern_name
        self.last_validation_result = None
        self.last_validation_polylines = None
        self.pattern_usage = []

        # SVG drawing
        self.dwg = svgwrite.Drawing(
            profile='full',
            size=(self.width, self.height)
        )

        print(f"[DesignGenerator] Initialized:")
        print(f"  Seed: {self.seed}")
        print(f"  Rings: {self.num_rings}, Divisions: {self.num_divisions}")
        print(f"  Complexity: {self.complexity}")
        print(f"  Categories: {self.categories}")

    def _calculate_rings(self):
        """
        Calculate ring boundaries (inner and outer radii for each ring).

        Ring spacing varies based on complexity:
        - Low complexity: even spacing
        - High complexity: variable spacing
        """
        # Reserve space at center and edge
        min_radius = 15 + (self.complexity * 10)  # 15-25 based on complexity
        max_radius = min(self.width, self.height) / 2 - 20

        total_span = max_radius - min_radius

        self.rings = []

        if self.complexity < 0.1:
            # Even spacing for low complexity
            ring_width = total_span / self.num_rings
            for i in range(self.num_rings):
                inner_r = min_radius + (i * ring_width)
                outer_r = min_radius + ((i + 1) * ring_width)
                self.rings.append({
                    'index': i,
                    'inner_radius': inner_r,
                    'outer_radius': outer_r,
                    'is_first': i == 0,
                    'is_last': i == self.num_rings - 1
                })
        else:
            # Variable spacing based on complexity
            weights = []
            for i in range(self.num_rings):
                # More variation with higher complexity
                variation = (self.rng.random() - 0.5) * self.complexity
                weight = 1.0 + variation
                weights.append(max(0.5, weight))  # Minimum 0.5 weight

            # Normalize weights
            total_weight = sum(weights)
            normalized = [w / total_weight for w in weights]

            current_radius = min_radius
            for i, weight in enumerate(normalized):
                inner_r = current_radius
                outer_r = current_radius + (total_span * weight)
                self.rings.append({
                    'index': i,
                    'inner_radius': inner_r,
                    'outer_radius': outer_r,
                    'is_first': i == 0,
                    'is_last': i == self.num_rings - 1
                })
                current_radius = outer_r

        # Log ring info
        for ring in self.rings:
            width = ring['outer_radius'] - ring['inner_radius']
            print(f"  Ring {ring['index']}: r={ring['inner_radius']:.1f}-{ring['outer_radius']:.1f} (width={width:.1f})")

    def _polar_to_cartesian(self, radius: float, angle_deg: float) -> tuple[float, float]:
        """Convert polar coordinates to cartesian (centered on canvas)."""
        angle_rad = math.radians(angle_deg)
        x = self.center_x + radius * math.cos(angle_rad)
        y = self.center_y + radius * math.sin(angle_rad)
        return (x, y)

    def _create_arc_path(self, radius: float, start_angle: float, end_angle: float) -> str:
        """Create SVG arc path data for a circular arc."""
        start = self._polar_to_cartesian(radius, start_angle)
        end = self._polar_to_cartesian(radius, end_angle)

        # Determine if arc should be large (> 180 degrees)
        angle_diff = end_angle - start_angle
        large_arc = 1 if angle_diff > 180 else 0

        # SVG arc: A rx ry x-axis-rotation large-arc-flag sweep-flag x y
        return f"M {start[0]},{start[1]} A {radius},{radius} 0 {large_arc} 1 {end[0]},{end[1]}"

    def generate(self, validate: bool = True) -> str:
        """
        Generate the complete mandala design.

        Args:
            validate: Whether to run validation checks (default True)

        Returns:
            SVG string of the complete design
        """
        print(f"\n=== GENERATING MANDALA ===")

        # Create defs section for reusable patterns
        defs = self.dwg.defs

        # Main drawing group
        main_group = self.dwg.g(id='mandala')

        # Debug colors
        debug_colors = ['red', 'blue', 'green', 'orange', 'purple', 'brown', 'pink', 'cyan']

        # Calculate stroke width based on design size
        base_stroke = max(1.0, min(2.5, 300 / self.num_divisions))

        # Store generated elements for validation
        # Key: (ring_index, var_idx), Value: list of element dicts
        generated_elements = {}
        boundary_requirements = self._empty_boundary_requirements()
        previous_pattern_names = []
        previous_ring_elements = None
        previous_ring_requirements = None

        # Generate patterns for each ring with variation support
        for ring in self.rings:
            ring_assets = self._generate_ring_assets(
                ring=ring,
                pattern_seed=self.seed,
                variation_rng=self.rng,
                debug_colors=debug_colors,
                avoid_pattern_names=previous_pattern_names,
                context_elements=previous_ring_elements,
                context_boundary_requirements=previous_ring_requirements
            )
            if not ring_assets:
                continue

            for pattern_group in ring_assets['defs_groups']:
                defs.add(pattern_group)

            main_group.add(ring_assets['ring_group'])
            generated_elements.update(ring_assets['generated_elements'])
            self._merge_all_boundary_requirements(
                boundary_requirements,
                ring_assets['boundary_requirements']
            )
            previous_pattern_names = ring_assets['used_pattern_names']
            previous_ring_elements = ring_assets['generated_elements']
            previous_ring_requirements = ring_assets['boundary_requirements']

        # Add debug overlays if enabled
        self._draw_ring_boundaries(main_group, boundary_requirements, base_stroke)

        if self.draw_rings:
            self._add_ring_debug(main_group, debug_colors)

        if self.draw_divisions:
            self._add_division_debug(main_group)

        self.dwg.add(main_group)

        # Run validation if enabled
        if validate:
            self.last_validation_result = self._validate_design(generated_elements, boundary_requirements)

        print(f"\n=== GENERATION COMPLETE ===\n")
        return self.dwg.tostring()

    def generate_ring_fragment(self, ring_index: int, ring_seed: int, validate: bool = True) -> dict[str, Any]:
        """
        Generate replacement SVG fragments for a single ring.

        The existing design seed is still used for ring geometry. ring_seed only
        changes the selected ring's pattern and variation choices.
        """
        if ring_index < 0 or ring_index >= len(self.rings):
            raise ValueError(f"ring_index must be between 0 and {len(self.rings) - 1}")

        print(f"\n=== REGENERATING RING {ring_index} ===")

        debug_colors = ['red', 'blue', 'green', 'orange', 'purple', 'brown', 'pink', 'cyan']
        variation_rng = random.Random(ring_seed)
        ring_assets = self._generate_ring_assets(
            ring=self.rings[ring_index],
            pattern_seed=ring_seed,
            variation_rng=variation_rng,
            debug_colors=debug_colors,
            avoid_pattern_names=[]
        )
        if not ring_assets:
            raise ValueError(f"Could not generate ring {ring_index}")

        if validate:
            self.last_validation_result = self._validate_design(
                ring_assets['generated_elements'],
                ring_assets['boundary_requirements']
            )

        return {
            'ring_index': ring_index,
            'defs_svg': ''.join(group.tostring() for group in ring_assets['defs_groups']),
            'ring_svg': ring_assets['ring_group'].tostring(),
            'ring_seed': ring_seed
        }

    def _generate_ring_assets(
        self,
        ring: dict,
        pattern_seed: int,
        variation_rng: random.Random,
        debug_colors: list[str],
        avoid_pattern_names: list[str] | None = None,
        context_elements: dict | None = None,
        context_boundary_requirements: dict | None = None
    ) -> dict[str, Any] | None:
        from pattern_generator import PatternGenerator

        pattern_gen = PatternGenerator(
            seed=pattern_seed,
            complexity=self.complexity,
            min_pattern_size=self.min_pattern_size,
            categories=self.categories,
            force_pattern_name=self.force_pattern_name
        )

        ring_index = ring['index']
        inner_r = ring['inner_radius']
        outer_r = ring['outer_radius']
        ring_width = outer_r - inner_r

        print(f"\nRing {ring_index}: inner={inner_r:.1f}, outer={outer_r:.1f}, width={ring_width:.1f}")

        # A ring too narrow for real pattern work still has to be CROSSED.
        # Leaving it empty produced a blank band that no line crosses, i.e. a
        # corridor a colourist can follow the whole way around the design.
        # The safe spoke has no size gate, so it can always fill the gap.
        force_safe_spoke = ring_width < self.min_pattern_size
        if force_safe_spoke:
            print(f"  Ring too narrow for patterns ({ring_width:.1f} < "
                  f"{self.min_pattern_size}); using spokes so it is not a blank lane")

        num_variations = self._calculate_num_variations(ring_index, variation_rng)
        variation_extensions = self._generate_variation_extensions(num_variations, ring_index, variation_rng)

        print(f"  Using {num_variations} variation(s) with extensions: {[f'{e:.2f}' for e in variation_extensions]}")

        base_pattern_info = None
        if not force_safe_spoke:
            base_pattern_info = pattern_gen.select_pattern_for_ring(
                ring_index=ring_index,
                inner_radius=inner_r,
                outer_radius=outer_r,
                is_first_ring=ring['is_first'],
                is_last_ring=ring['is_last'],
                avoid_pattern_names=avoid_pattern_names,
                wedge_angle=self.wedge_angle
            )

        if not base_pattern_info:
            # Nothing fits this ring's size, so fall back rather than leaving it
            # blank. The category still comes from the user's selection.
            from smart_patterns import get_safe_fallback_pattern

            category = (self.categories or ['botanical'])[ring_index % len(self.categories or ['botanical'])]
            base_pattern_info = pattern_gen._pattern_info(
                get_safe_fallback_pattern(category.lower()),
                self.seed + ring_index * 17,
                ring_index,
            )
            print(f"  No sized pattern for ring {ring_index}; using {base_pattern_info['name']}")

        print(f"  Selected pattern: {base_pattern_info['name']} (category: {base_pattern_info['category']})")

        defs_groups = []
        generated_elements = {}
        boundary_requirements = self._empty_boundary_requirements()
        used_pattern_names = []

        def validate_ring_candidate(variations: list[list[dict]], candidate_policy: dict) -> str | None:
            effective_policy = self._effective_boundary_policy(
                candidate_policy,
                self._infer_boundary_requirements_for_variations(variations, ring['is_last'])
            )
            candidate_requirements = self._empty_boundary_requirements()
            if context_boundary_requirements:
                self._merge_all_boundary_requirements(
                    candidate_requirements,
                    context_boundary_requirements
                )
            self._merge_boundary_requirements(
                candidate_requirements,
                ring_index,
                effective_policy,
                log=False
            )
            # Validate every variation together, interleaved across divisions
            # exactly as they will be placed, and against the neighboring ring
            # that was already accepted. Checking a single variation replicated
            # to all cells hid both port mismatches between variations and
            # pockets at the shared ring interface.
            candidate_elements = {
                (ring_index, index): elements
                for index, elements in enumerate(variations)
            }
            validation_result = self._validate_design(
                {**(context_elements or {}), **candidate_elements},
                candidate_requirements,
                check_tiny_regions=True
            )
            if validation_result.is_valid:
                return None
            return "final boundary-inclusive validation failed: " + "; ".join(
                validation_result.issues[:3]
            )

        ring_policy, ring_variations = pattern_gen.generate_ring_variations(
            pattern_info=base_pattern_info,
            inner_radius=inner_r,
            outer_radius=outer_r,
            wedge_angle=self.wedge_angle,
            center=self.center,
            is_first_ring=ring['is_first'],
            is_last_ring=ring['is_last'],
            extensions=variation_extensions,
            candidate_validator=validate_ring_candidate
        )

        num_variations = len(ring_variations)

        for var_idx, pattern_elements in enumerate(ring_variations):
            actual_pattern_policy = self._effective_boundary_policy(
                ring_policy,
                self._infer_boundary_requirements_from_elements(
                    pattern_elements,
                    is_last_ring=ring['is_last']
                )
            )
            self.pattern_usage.append({
                'ring_index': ring_index,
                'variation_index': var_idx,
                **actual_pattern_policy
            })
            if actual_pattern_policy['name'] not in used_pattern_names:
                used_pattern_names.append(actual_pattern_policy['name'])
            self._merge_boundary_requirements(
                boundary_requirements,
                ring_index,
                actual_pattern_policy
            )

            generated_elements[(ring_index, var_idx)] = pattern_elements

            pattern_id = f"ring-{ring_index}-var-{var_idx}"
            pattern_group = self.dwg.g(id=pattern_id)

            for elem in pattern_elements:
                svg_elem = self._dict_to_svg_element(elem)
                if svg_elem:
                    if self.colored_rings:
                        color = debug_colors[ring_index % len(debug_colors)]
                        if hasattr(svg_elem, 'stroke'):
                            svg_elem.stroke(color)
                    pattern_group.add(svg_elem)

            defs_groups.append(pattern_group)

        if not defs_groups:
            return None

        ring_group = self.dwg.g(id=f"ring-{ring_index}")
        for i in range(self.num_divisions):
            var_idx = i % num_variations
            pattern_id = f"ring-{ring_index}-var-{var_idx}"
            rotation_angle = i * self.wedge_angle
            use_elem = self.dwg.use(
                href=f"#{pattern_id}",
                transform=f"rotate({rotation_angle}, {self.center_x}, {self.center_y})"
            )
            ring_group.add(use_elem)

        print(f"  Generated {self.num_divisions} cells with {num_variations} variation(s)")
        print(f"  Actual ring pattern(s): {used_pattern_names}")
        print(f"  Boundary requirements: {boundary_requirements[ring_index]}")

        return {
            'defs_groups': defs_groups,
            'ring_group': ring_group,
            'generated_elements': generated_elements,
            'boundary_requirements': boundary_requirements,
            'used_pattern_names': used_pattern_names
        }

    def _validate_design(
        self,
        generated_elements: dict,
        boundary_requirements: dict,
        check_tiny_regions: bool = True
    ):
        """
        Validate the generated design for proper connections and colorable regions.

        Uses exact planar-topology analysis (topology_validator): dangling line
        ends, floating open shapes, and un-colorable regions are derived from
        the true arrangement of the linework instead of proximity heuristics.

        Args:
            generated_elements: Dict mapping (ring_index, var_idx) to element lists
        """
        from shape_extractor import ShapeExtractor
        from topology_validator import TopologyValidator, polylines_from_shapes

        print(f"\n=== VALIDATING DESIGN ===")

        # Extract all shapes from generated elements
        # Smart pattern paths and boundary arcs are already dense polylines;
        # re-splitting their straight runs would only multiply vertices.
        extractor = ShapeExtractor(sample_resolution=8, subdivide_lines=False)
        all_shapes = []

        for (ring_index, var_idx), elements in generated_elements.items():
            # For each variation, it gets placed at multiple divisions
            num_variations = len([k for k in generated_elements.keys() if k[0] == ring_index])

            for div_idx in range(self.num_divisions):
                # Check if this division uses this variation
                if div_idx % num_variations != var_idx:
                    continue

                rotation_angle = div_idx * self.wedge_angle
                cell_id = f"ring-{ring_index}-div-{div_idx}"

                shapes = extractor.extract_shapes(
                    elements=elements,
                    cell_id=cell_id,
                    ring_index=ring_index,
                    division_index=div_idx,
                    rotation_angle=rotation_angle,
                    center=self.center
                )
                all_shapes.extend(shapes)

        boundary_shapes = extractor.extract_shapes(
            elements=self._get_boundary_element_dicts(boundary_requirements),
            cell_id="mandala-boundary",
            ring_index=-1,
            division_index=-1,
            rotation_angle=0,
            center=self.center
        )
        all_shapes.extend(boundary_shapes)

        print(f"  Extracted {len(all_shapes)} shapes from {len(generated_elements)} pattern variations")

        polylines = polylines_from_shapes(all_shapes)

        # When validating a subset of rings (candidate patterns, single-ring
        # regeneration) only the two radial FRONTIERS are genuinely unknown:
        # inward of the lowest validated ring and outward of the highest. Every
        # boundary between validated rings must be satisfied for real, which is
        # what catches endpoints that rely on a neighbor that isn't there.
        # Full-design validation stays strict: no exemptions at all.
        validated_ring_indices = {key[0] for key in generated_elements.keys()}
        is_partial = len(validated_ring_indices) < len(self.rings)
        exempt_dangle_fn = None
        if is_partial and validated_ring_indices:
            lowest = min(validated_ring_indices)
            highest = max(validated_ring_indices)
            frontier_radii = []
            for ring in self.rings:
                if ring['index'] == lowest:
                    frontier_radii.append(ring['inner_radius'])
                if ring['index'] == highest:
                    frontier_radii.append(ring['outer_radius'])

            def exempt_dangle_fn(x, y, _radii=tuple(frontier_radii)):
                dist = math.hypot(x - self.center_x, y - self.center_y)
                return any(abs(dist - r) <= 1.0 for r in _radii)

        validator = TopologyValidator(
            snap_tolerance=2.5,     # gaps under a stroke width render connected
            whisker_tolerance=5.0,  # overshoot stubs up to 5px read as corners
            pen_radius=2.0,         # a face must fit a 2px pen tip somewhere
            min_region_area=20.0,
            check_tiny_regions=check_tiny_regions
        )

        result = validator.analyze(
            polylines,
            exempt_dangle_fn=exempt_dangle_fn,
            center=(self.center_x, self.center_y),
            divisions=self.num_divisions,
        )
        self.last_validation_polylines = polylines

        stats = result.stats
        print(
            f"  Topology: {stats.get('num_regions', 0)} colorable regions, "
            f"{stats.get('num_components', 0)} components "
            f"({stats.get('num_whiskers_pruned', 0)} whiskers pruned, "
            f"{stats.get('num_gaps_bridged', 0)} gaps bridged)"
        )
        if result.is_valid:
            print("  Design PASSED validation")
        else:
            print(f"  Design has {len(result.issues)} validation issues:")
            print(f"    - {stats.get('num_dangles', 0)} dangling line ends")
            print(f"    - {stats.get('num_floating_open', 0)} floating open shapes")
            print(f"    - {stats.get('num_uncolorable_regions', 0)} un-colorable regions")
            print(f"    - {stats.get('num_free_lanes', 0)} un-crossed lanes "
                  f"(widest {stats.get('widest_lane_px', 0)}px)")

        return result

    def _empty_boundary_requirements(self) -> dict:
        return {
            ring['index']: {
                'requires_inner_boundary': False,
                'requires_outer_boundary': False,
                'requires_radial_boundaries': False
            }
            for ring in self.rings
        }

    def _merge_boundary_requirements(self, requirements: dict, ring_index: int, policy: dict, log: bool = True):
        ring_requirements = requirements.setdefault(
            ring_index,
            {
                'requires_inner_boundary': False,
                'requires_outer_boundary': False,
                'requires_radial_boundaries': False
            }
        )
        for key in (
            'requires_inner_boundary',
            'requires_outer_boundary',
            'requires_radial_boundaries'
        ):
            previous_value = ring_requirements[key]
            next_value = previous_value or bool(policy.get(key, False))
            if log and not previous_value and next_value:
                print(
                    f"  Boundary enabled for ring {ring_index}: "
                    f"{key} by {policy.get('name', 'unknown pattern')}"
                )
            ring_requirements[key] = next_value

    def _merge_all_boundary_requirements(self, target: dict, source: dict):
        for ring_index, policy in source.items():
            self._merge_boundary_requirements(target, ring_index, policy, log=False)

    def _effective_boundary_policy(self, pattern_policy: dict, inferred_policy: dict) -> dict:
        force_inner = bool(pattern_policy.get('force_inner_boundary', False))
        force_outer = bool(pattern_policy.get('force_outer_boundary', False))
        force_radial = bool(pattern_policy.get('force_radial_boundaries', False))
        return {
            **pattern_policy,
            **inferred_policy,
            'requires_inner_boundary': force_inner or bool(inferred_policy.get('requires_inner_boundary', False)),
            'requires_outer_boundary': force_outer or bool(inferred_policy.get('requires_outer_boundary', False)),
            'requires_radial_boundaries': force_radial or bool(inferred_policy.get('requires_radial_boundaries', False)),
        }

    def _infer_boundary_requirements_for_variations(
        self,
        variations: list[list[dict]],
        is_last_ring: bool = False
    ) -> dict:
        """Union of the boundary needs of every variation in a ring."""
        merged = {
            'requires_inner_boundary': False,
            'requires_outer_boundary': False,
            'requires_radial_boundaries': False
        }
        for elements in variations:
            inferred = self._infer_boundary_requirements_from_elements(
                elements,
                is_last_ring=is_last_ring
            )
            for key in merged:
                merged[key] = merged[key] or bool(inferred.get(key, False))
        return merged

    def _infer_boundary_requirements_from_elements(self, elements: list[dict], is_last_ring: bool = False) -> dict:
        vectors = [
            elem.get('smart_vector')
            for elem in elements
            if elem.get('smart_vector') is not None
        ]
        if len(vectors) != len(elements):
            print("  Boundary policy fallback: non-smart element defaults to drawn boundaries")
            return {
                'requires_inner_boundary': True,
                'requires_outer_boundary': True,
                'requires_radial_boundaries': True
            }

        all_segments = self._smart_vector_segments(vectors)
        has_outer_enclosure = is_last_ring and self._has_outer_pattern_enclosure(vectors)
        policy = {
            'requires_inner_boundary': False,
            'requires_outer_boundary': False,
            'requires_radial_boundaries': False
        }

        for vector_index, vector in enumerate(vectors):
            if vector.closed:
                continue
            for endpoint in (vector.points[0], vector.points[-1]):
                boundary_side = self._smart_boundary_side(endpoint)
                if boundary_side not in ('inner', 'outer'):
                    continue
                if self._smart_point_touches_other_segment(endpoint, all_segments, vector_index):
                    continue
                if boundary_side == 'inner':
                    policy['requires_inner_boundary'] = True
                elif boundary_side == 'outer':
                    if has_outer_enclosure:
                        print("  Outermost ring outer boundary suppressed by pattern enclosure")
                    else:
                        policy['requires_outer_boundary'] = True

        return policy

    def _has_outer_pattern_enclosure(self, vectors: list, tolerance: float = 0.025) -> bool:
        """
        Detect whether repeated outermost pattern linework forms its own outer
        contour, making the circular outer ring boundary redundant.

        The shape has to actually REACH the outer boundary. This used to accept
        anything past mid-radius, which suppressed the boundary arc for motifs
        that merely reached into the outer half - and then any line ending on
        that boundary had nothing to connect to.
        """
        for vector in vectors:
            if vector.closed and self._smart_vector_reaches_outer_boundary(vector, tolerance):
                return True
        return False

    def _smart_vector_reaches_outer_boundary(self, vector, tolerance: float = 0.025) -> bool:
        return any(point.radial >= 1.0 - tolerance for point in vector.points)

    def _smart_vector_segments(self, vectors: list) -> list[tuple]:
        segments = []
        for vector_index, vector in enumerate(vectors):
            points = vector.points[:]
            if vector.closed and points:
                points.append(points[0])
            for point_index in range(len(points) - 1):
                segments.append((points[point_index], points[point_index + 1], vector_index))
        return segments

    def _smart_boundary_side(self, point, tolerance: float = 0.025) -> str | None:
        # Shared with the smart-cell analyzer: the two used to disagree, and a
        # pattern endpoint could be "on the inner boundary" for the analyzer
        # while matching no side here, so no boundary arc was ever drawn for it.
        from smart_patterns.core import boundary_side

        return boundary_side(point, tolerance)

    def _smart_point_touches_other_segment(
        self,
        point,
        segments: list[tuple],
        vector_index: int,
        tolerance: float = 0.025
    ) -> bool:
        for start, end, segment_vector_index in segments:
            if segment_vector_index == vector_index:
                continue
            if self._smart_point_to_segment_distance(point, start, end) <= tolerance:
                return True
        return False

    def _smart_point_to_segment_distance(self, point, start, end) -> float:
        px, py = point.angular, point.radial
        ax, ay = start.angular, start.radial
        bx, by = end.angular, end.radial
        dx = bx - ax
        dy = by - ay
        if dx == 0 and dy == 0:
            return math.hypot(px - ax, py - ay)
        t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
        closest_x = ax + t * dx
        closest_y = ay + t * dy
        return math.hypot(px - closest_x, py - closest_y)

    def _get_boundary_element_dicts(self, boundary_requirements: dict, stroke_width: float = 1.0) -> list[dict]:
        """Return SVG element dictionaries for pattern-required boundaries."""
        elements = []

        for ring in self.rings:
            ring_requirements = boundary_requirements.get(ring['index'], {})
            if ring_requirements.get('requires_inner_boundary', False):
                elements.extend(self._ring_boundary_arc_elements(ring['inner_radius'], stroke_width))
            if ring_requirements.get('requires_outer_boundary', False):
                elements.extend(self._ring_boundary_arc_elements(ring['outer_radius'], stroke_width))
            if not ring_requirements.get('requires_radial_boundaries', False):
                continue
            for i in range(self.num_divisions):
                angle = i * self.wedge_angle
                start = self._polar_to_cartesian(ring['inner_radius'], angle)
                end = self._polar_to_cartesian(ring['outer_radius'], angle)
                elements.append({
                    'tag': 'line',
                    'attributes': {
                        'x1': str(start[0]),
                        'y1': str(start[1]),
                        'x2': str(end[0]),
                        'y2': str(end[1]),
                        'stroke': 'black',
                        'stroke-width': str(stroke_width)
                    }
                })

        return elements

    def _ring_boundary_arc_elements(self, radius: float, stroke_width: float) -> list[dict]:
        elements = []
        for i in range(self.num_divisions):
            start_angle = i * self.wedge_angle
            end_angle = (i + 1) * self.wedge_angle
            steps = max(4, int(self.wedge_angle / 4))
            points = [
                self._polar_to_cartesian(
                    radius,
                    start_angle + ((end_angle - start_angle) * step / steps)
                )
                for step in range(steps + 1)
            ]
            commands = [f"M {points[0][0]},{points[0][1]}"]
            commands.extend(f"L {x},{y}" for x, y in points[1:])
            elements.append({
                'tag': 'path',
                'attributes': {
                    'd': ' '.join(commands),
                    'fill': 'none',
                    'stroke': 'black',
                    'stroke-width': str(stroke_width)
                }
            })
        return elements

    def _dict_to_svg_element(self, elem_dict: dict):
        """Convert a pattern element dictionary to an SVG element."""
        tag = elem_dict.get('tag')
        attrs = elem_dict.get('attributes', {})

        if tag == 'path':
            path = self.dwg.path(
                d=attrs.get('d', ''),
                fill=attrs.get('fill', 'none'),
                stroke=attrs.get('stroke', 'black'),
                stroke_width=attrs.get('stroke-width', '1')
            )
            if 'stroke-linecap' in attrs:
                path['stroke-linecap'] = attrs['stroke-linecap']
            if 'stroke-linejoin' in attrs:
                path['stroke-linejoin'] = attrs['stroke-linejoin']
            return path
        elif tag == 'circle':
            return self.dwg.circle(
                center=(float(attrs.get('cx', 0)), float(attrs.get('cy', 0))),
                r=float(attrs.get('r', 1)),
                fill=attrs.get('fill', 'none'),
                stroke=attrs.get('stroke', 'black'),
                stroke_width=attrs.get('stroke-width', '1')
            )
        elif tag == 'ellipse':
            return self.dwg.ellipse(
                center=(float(attrs.get('cx', 0)), float(attrs.get('cy', 0))),
                r=(float(attrs.get('rx', 1)), float(attrs.get('ry', 1))),
                fill=attrs.get('fill', 'none'),
                stroke=attrs.get('stroke', 'black'),
                stroke_width=attrs.get('stroke-width', '1')
            )
        elif tag == 'line':
            line = self.dwg.line(
                start=(float(attrs.get('x1', 0)), float(attrs.get('y1', 0))),
                end=(float(attrs.get('x2', 0)), float(attrs.get('y2', 0))),
                stroke=attrs.get('stroke', 'black'),
                stroke_width=attrs.get('stroke-width', '1')
            )
            if 'stroke-linecap' in attrs:
                line['stroke-linecap'] = attrs['stroke-linecap']
            return line
        elif tag == 'polygon':
            points_str = attrs.get('points', '')
            points = []
            for pair in points_str.split():
                if ',' in pair:
                    x, y = pair.split(',')
                    points.append((float(x), float(y)))
            polygon = self.dwg.polygon(
                points=points,
                fill=attrs.get('fill', 'none'),
                stroke=attrs.get('stroke', 'black'),
                stroke_width=attrs.get('stroke-width', '1')
            )
            if 'stroke-linejoin' in attrs:
                polygon['stroke-linejoin'] = attrs['stroke-linejoin']
            return polygon
        else:
            print(f"  Warning: Unknown SVG tag '{tag}'")
            return None

    def _draw_ring_boundaries(self, group, boundary_requirements: dict, stroke_width: float):
        """Draw only the boundaries required by selected smart patterns."""
        boundary_group = self.dwg.g(id='ring-boundaries')

        for elem in self._get_boundary_element_dicts(boundary_requirements, stroke_width):
            svg_elem = self._dict_to_svg_element(elem)
            if svg_elem:
                boundary_group.add(svg_elem)

        group.add(boundary_group)

    def _add_ring_debug(self, group, colors):
        """Add ring boundary circles for debugging."""
        for ring in self.rings:
            color = colors[ring['index'] % len(colors)] if self.colored_rings else 'gray'
            # Outer boundary
            circle = self.dwg.circle(
                center=self.center,
                r=ring['outer_radius'],
                fill='none',
                stroke=color,
                stroke_width=0.5,
                stroke_dasharray='4,2'
            )
            group.add(circle)

    def _add_division_debug(self, group):
        """Add wedge division lines for debugging."""
        max_radius = self.rings[-1]['outer_radius'] if self.rings else 100
        for i in range(self.num_divisions):
            angle = i * self.wedge_angle
            end_point = self._polar_to_cartesian(max_radius, angle)
            line = self.dwg.line(
                start=self.center,
                end=end_point,
                stroke='gray',
                stroke_width=0.5,
                stroke_dasharray='2,4'
            )
            group.add(line)

    def _calculate_num_variations(self, ring_index: int, rng: random.Random | None = None) -> int:
        """
        Calculate how many pattern variations to use for a ring.

        Rules for symmetry:
        - Even divisions: use even number of variations (or 1)
        - Odd divisions: use odd number of variations

        Higher complexity = more variations allowed.
        """
        # Base number of variations scales with complexity
        # At complexity 0: 1 variation (uniform)
        # At complexity 1: up to 4 variations
        max_variations = 1 + int(self.complexity * 3)

        # Randomize actual number (1 to max)
        rng = rng or self.rng
        num_variations = rng.randint(1, max_variations)

        # Enforce symmetry rules
        if self.num_divisions % 2 == 0:
            # Even divisions: need even variations or 1
            if num_variations > 1 and num_variations % 2 != 0:
                num_variations = max(2, num_variations - 1)
        else:
            # Odd divisions: need odd variations
            if num_variations % 2 == 0:
                num_variations = max(1, num_variations - 1)

        # Variations must divide evenly into divisions for clean repetition
        while num_variations > 1 and self.num_divisions % num_variations != 0:
            num_variations -= 1
            if num_variations < 1:
                num_variations = 1
                break

        return num_variations

    def _generate_variation_extensions(
        self,
        num_variations: int,
        ring_index: int,
        rng: random.Random | None = None
    ) -> list[float]:
        """
        Generate extension amounts for each variation.

        Extension is how much the pattern extends beyond its cell boundaries.
        Range: 0.0 (contained within cell) to 0.3 (extends 30% beyond)

        Higher complexity = larger potential extensions.
        """
        extensions = []
        max_extension = 0.1 + (self.complexity * 0.2)  # 0.1 to 0.3
        rng = rng or self.rng

        for i in range(num_variations):
            # Random extension for this variation
            ext = rng.uniform(0.0, max_extension)
            extensions.append(ext)

        return extensions

    def get_params_as_string(self) -> str:
        """Return parameter string for display."""
        params = [
            f"Seed: {self.seed}",
            f"Rings: {self.num_rings}",
            f"Divisions: {self.num_divisions}",
            f"Complexity: {self.complexity}",
            f"Categories: {', '.join(self.categories)}"
        ]
        return "\n".join(params)


# CLI testing
if __name__ == "__main__":
    import os
    import webbrowser
    from datetime import datetime

    generator = DesignGenerator(
        seed=12345,
        num_rings=5,
        num_divisions=12,
        complexity=0.6,
        min_pattern_size=10,
        categories=['botanical'],
        draw_rings=True,
        draw_divisions=True,
        colored_rings=True
    )

    svg_output = generator.generate()

    # Save to file
    output_dir = "generated_designs"
    os.makedirs(output_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = os.path.join(output_dir, f"mandala_{timestamp}.svg")

    with open(filepath, "w") as f:
        f.write(svg_output)

    print(f"Saved: {filepath}")
    webbrowser.open(f"file://{os.path.realpath(filepath)}")
