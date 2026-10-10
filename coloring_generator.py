"""
Mandala Coloring Page Generator

Generates procedural mandala designs with perfect radial symmetry. The
composer plans every ring, the assembler places and resolves the ink, and the
topology validator checks the result; this module turns that ink into SVG.
"""

import svgwrite
import random
import math
from typing import Any

from assembler import Assembler, AssembledDesign, LayeredRingFailed
from composer import Composer, ComposerSettings, DesignPlan
from motifs.geometry import cell_rotation_deg
from placement import PlacedPath
from topology_validator import MIN_REGION_AREA_PX2, PEN_RADIUS_PX, TopologyReport, TopologyValidator


class DesignGenerator:
    """
    Generates mandala-style coloring page designs.

    Architecture:
    - All rings are circular (no polygon support)
    - Each ring has its own division count and a planned sequence of motif cells
    - Motifs are selected from enabled categories
    - Complexity controls detail level within motifs
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
        vary_divisions: bool = False,
        ring_divisions: list[int] | None = None,
        ring_seeds: dict[int, int] | None = None,
        force_motif: dict[str, str] | None = None,
        force_position_mode: str | None = None,
        # Debug options
        draw_rings: bool = False,
        draw_divisions: bool = False,
    ):
        # Set seed for reproducibility
        self.seed = seed if seed is not None else random.randint(0, 1000000)
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
        self.vary_divisions = vary_divisions
        self.ring_divisions = ring_divisions
        self.ring_seeds = dict(ring_seeds or {})
        self.force_motif = force_motif
        # "centre", "divider", "both" or "layered", forced on every ring past the innermost where eligible.
        self.force_position_mode = force_position_mode

        # Debug options
        self.draw_rings = draw_rings
        self.draw_divisions = draw_divisions

        # Calculate ring system
        self._calculate_rings()

        # Set by generate()
        self.composer: Composer | None = None
        self.plan: DesignPlan | None = None
        self.assembled: AssembledDesign | None = None
        self.last_validation_result: TopologyReport | None = None
        self.last_validation_polylines = None

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

    def generate(self, validate: bool = True) -> str:
        """
        Plan, assemble and (optionally) validate the design.

        Returns the SVG document: one explicit path per placed piece of ink,
        grouped by ring. Raises `AssemblyError` (a `ValueError`) when a cell
        cannot be assembled.
        """
        print("\n=== GENERATING MANDALA ===")
        settings = ComposerSettings(
            num_divisions=self.num_divisions,
            vary_divisions=self.vary_divisions,
            ring_divisions=self.ring_divisions,
            complexity=self.complexity,
            min_pattern_size=self.min_pattern_size,
            categories=self.categories,
            force_motif=self.force_motif,
            ring_seeds=self.ring_seeds,
            force_position_mode=self.force_position_mode,
        )
        self.composer = Composer(self.seed, self.rings, settings)
        self.plan = self.composer.plan()
        self.assembled = self._assemble()
        print(f"  Ring divisions: {[ring.divisions for ring in self.plan.rings]}")
        print(f"  Placed {len(self.assembled.paths)} paths, {len(self.assembled.reaches)} reaches, "
              f"{self.assembled.dropped_children} dropped children, "
              f"{self.assembled.dropped_embellishments} dropped embellishments")

        svg = self._render_svg()

        self.last_validation_result = None
        self.last_validation_polylines = None
        if validate:
            self._validate()

        print("=== GENERATION COMPLETE ===\n")
        return svg

    def _assemble(self) -> AssembledDesign:
        """
        Assemble the plan. A layered ring whose composite fails in pass two, or whose back a pass-two
        replacement dropped, loses its back for the whole ring and the design is assembled again (spec 5.4),
        at most once per ring.
        """
        dropped: set[int] = set()
        while True:
            try:
                return Assembler(
                    self.plan, self.rings, self.center, self.complexity, self.min_pattern_size, self.composer
                ).assemble()
            except LayeredRingFailed as failure:
                ring = next((r for r in self.plan.rings if r.ring_index == failure.ring_index), None)
                if failure.ring_index in dropped or ring is None:
                    raise
                dropped.add(failure.ring_index)
                print(f"  {failure}; dropping its back layer and assembling again")
                self.composer.drop_back(ring)

    def generate_ring_fragment(self, ring_index: int, ring_seed: int, validate: bool = True) -> dict[str, Any]:
        """
        Re-plan one ring with its own seed and re-assemble the whole design.

        The whole document is returned because a changed ring changes its
        neighbours' reaches and overflow resolution.
        """
        if ring_index < 0 or ring_index >= len(self.rings):
            raise ValueError(f"ring_index must be between 0 and {len(self.rings) - 1}")

        print(f"\n=== REGENERATING RING {ring_index} ===")
        self.ring_seeds[ring_index] = ring_seed
        svg = self.generate(validate)
        return {
            'ring_index': ring_index,
            'ring_seed': ring_seed,
            'svg': svg,
            'plan': self.plan,
            'ring_seeds': dict(self.ring_seeds),
        }

    def _render_svg(self) -> str:
        # svgwrite's attribute validator rejects data-* attributes, so the drawing runs without it.
        dwg = svgwrite.Drawing(profile='full', size=(self.width, self.height), debug=False)
        dwg.elements.remove(dwg.defs)  # nothing is reused, so no empty <defs />
        mandala = dwg.g(id='mandala')
        groups = {ring['index']: dwg.g(id=f"ring-{ring['index']}") for ring in self.rings}
        for path in self.assembled.paths:
            groups[path.ring_index].add(self._path_element(dwg, path))
        for ring in self.rings:
            mandala.add(groups[ring['index']])
        dwg.add(mandala)

        if self.draw_rings or self.draw_divisions:
            debug = dwg.g(id='debug')
            if self.draw_rings:
                self._add_ring_debug(dwg, debug)
            if self.draw_divisions:
                self._add_division_debug(dwg, debug)
            dwg.add(debug)
        return dwg.tostring()

    @staticmethod
    def _path_element(dwg: svgwrite.Drawing, path: PlacedPath):
        commands = [f"M {path.coords[0][0]:.3f},{path.coords[0][1]:.3f}"]
        commands.extend(f"L {x:.3f},{y:.3f}" for x, y in path.coords[1:])
        if path.closed:
            commands.append("Z")
        element = dwg.path(d=' '.join(commands), fill='none', stroke='black', stroke_width=str(path.stroke_width))
        element['stroke-linecap'] = 'butt'
        element['stroke-linejoin'] = 'round'
        element['data-role'] = path.role
        return element

    def _validate(self) -> None:
        print("\n=== VALIDATING DESIGN ===")
        polylines = self.assembled.polylines()
        validator = TopologyValidator(
            snap_tolerance=2.5,     # gaps under a stroke width render connected
            whisker_tolerance=5.0,  # overshoot stubs up to 5px read as corners
            pen_radius=PEN_RADIUS_PX,  # a face must fit a 2px pen tip somewhere
            min_region_area=MIN_REGION_AREA_PX2,
        )
        result = validator.analyze(
            polylines,
            center=self.center,
            base_mask=self.assembled.base_mask(),
            ring_ids=self.assembled.ring_ids(),
            overflow_parts=self.assembled.overflow_parts(),
        )
        self.last_validation_result = result
        self.last_validation_polylines = polylines

        stats = result.stats
        print(f"  Topology: {stats.get('num_regions', 0)} colorable regions, "
              f"{stats.get('num_components', 0)} components")
        if result.is_valid:
            print("  Design PASSED validation")
        else:
            print(f"  Design has {len(result.issues)} validation issues:")
            for issue in result.issues[:5]:
                print(f"    - {issue}")

    def validation_summary(self) -> dict[str, Any] | None:
        """Counts from the last validation, or None when none ran."""
        report = self.last_validation_result
        if report is None:
            return None
        stats = report.stats
        return {
            'is_valid': report.is_valid,
            'issue_count': len(report.issues),
            'tiny_region_count': len(report.tiny_regions),
            'dangling_end_count': stats.get('num_dangles', 0),
            'floating_base_count': stats.get('num_floating_base', 0),
            'overflow_crossing_count': stats.get('num_overflow_crossings', 0),
            'issues': report.issues[:20],
        }

    def _add_ring_debug(self, dwg: svgwrite.Drawing, group):
        """Add ring boundary circles for debugging."""
        for ring in self.rings:
            group.add(dwg.circle(
                center=self.center,
                r=ring['outer_radius'],
                fill='none',
                stroke='gray',
                stroke_width=0.5,
                stroke_dasharray='4,2'
            ))

    def _add_division_debug(self, dwg: svgwrite.Drawing, group):
        """Add each ring's own cell dividers for debugging."""
        for ring, ring_plan in zip(self.rings, self.plan.rings):
            for i in range(ring_plan.divisions):
                angle = cell_rotation_deg(i, ring_plan.divisions, 'divider')
                group.add(dwg.line(
                    start=self._polar_to_cartesian(ring['inner_radius'], angle),
                    end=self._polar_to_cartesian(ring['outer_radius'], angle),
                    stroke='gray',
                    stroke_width=0.5,
                    stroke_dasharray='2,4'
                ))

    def get_params_as_string(self) -> str:
        """Return parameter string for display."""
        params = [
            f"Seed: {self.seed}",
            f"Rings: {self.num_rings}",
            f"Divisions: {self.num_divisions}",
        ]
        if self.plan is not None:
            params.append(f"Ring divisions: {', '.join(str(ring.divisions) for ring in self.plan.rings)}")
        params.extend([
            f"Complexity: {self.complexity}",
            f"Categories: {', '.join(self.categories)}",
        ])
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
        vary_divisions=True,
        draw_rings=True,
        draw_divisions=True,
    )

    svg_output = generator.generate()
    print(generator.get_params_as_string())

    # Save to file
    output_dir = "generated_designs"
    os.makedirs(output_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = os.path.join(output_dir, f"mandala_{timestamp}.svg")

    with open(filepath, "w") as f:
        f.write(svg_output)

    print(f"Saved: {filepath}")
    webbrowser.open(f"file://{os.path.realpath(filepath)}")
