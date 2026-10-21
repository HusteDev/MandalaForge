"""
Mandala Coloring Page Generator

Generates procedural mandala designs with perfect radial symmetry. The
composer plans every ring, the assembler places and resolves the ink, and the
topology validator checks the result; this module turns that ink into SVG.
"""

import svgwrite
import logging
import random
import math
from copy import deepcopy
from typing import Any, List, Tuple

from assembler import Assembler, AssembledDesign, AssemblyError, LayeredRingFailed
from composer import Composer, ComposerSettings, DesignPlan
from motifs.geometry import cell_rotation_deg
from placement import PlacedPath
from region_repair import FaceSet, RegionRepair, Trial, classify_faces, face_sets
from topology_validator import (
    MIN_REGION_AREA_PX2, PEN_RADIUS_PX, TopologyReport, TopologyValidator, max_region_px2,
)

logger = logging.getLogger(__name__)

# Width bounds for a regenerated ring, as fractions of the mean ring width.
RING_WIDTH_MIN = 0.6
RING_WIDTH_MAX = 1.5
RING_WIDTH_FLOOR = 0.5          # no neighbour is squeezed below this
RING_WIDTH_MIN_CHANGE = 0.15    # a re-picked width aims to differ by at least this much
RING_WIDTH_DRAWS = 4


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
        force_embellishments: tuple[str, ...] | None = None,
        max_region_cap: bool = False,
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
        self.max_region_cap = max_region_cap
        # Embellishments added to every base and back that accepts them (QA forcing, see ComposerSettings).
        self.force_embellishments = tuple(force_embellishments) if force_embellishments else None

        # Debug options
        self.draw_rings = draw_rings
        self.draw_divisions = draw_divisions

        # Calculate ring system
        self._calculate_rings()

        # Set by generate()
        self.composer: Composer | None = None
        self.plan: DesignPlan | None = None
        # The plan as it stood before its final assembly (repairs included): generate_from_plan replays it.
        self.source_plan: DesignPlan | None = None
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

        A ring in ring_seeds was regenerated, so its width is re-picked from its
        ring seed and its neighbours absorb the change; the inner and outer
        radii of the whole design stay fixed. Recomputed from scratch on every
        call, so the same seeds always give the same rings.
        """
        # Reserve space at center and edge
        min_radius = 15 + (self.complexity * 10)  # 15-25 based on complexity
        max_radius = min(self.width, self.height) / 2 - 20

        total_span = max_radius - min_radius

        if self.complexity < 0.1:
            # Even spacing for low complexity
            widths = [total_span / self.num_rings] * self.num_rings
        else:
            # Variable spacing based on complexity
            self.rng = random.Random(self.seed)
            weights = []
            for i in range(self.num_rings):
                # More variation with higher complexity
                variation = (self.rng.random() - 0.5) * self.complexity
                weight = 1.0 + variation
                weights.append(max(0.5, weight))  # Minimum 0.5 weight

            # Normalize weights
            total_weight = sum(weights)
            widths = [total_span * w / total_weight for w in weights]

        self._repick_regenerated_widths(widths, total_span)

        self.rings = []
        current_radius = min_radius
        for i, width in enumerate(widths):
            inner_r = current_radius
            outer_r = max_radius if i == self.num_rings - 1 else current_radius + width
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

    def _repick_regenerated_widths(self, widths: list[float], total_span: float):
        """
        Re-pick the width of every regenerated ring, in ring order, in place.

        The new width is drawn from the ring's own seed within 0.6x-1.5x the mean
        ring width, and the adjacent rings shrink or grow to absorb the change,
        none narrower than half the mean, so the total span is unchanged.
        """
        if self.num_rings < 2:
            return
        mean = total_span / self.num_rings
        floor = RING_WIDTH_FLOOR * mean
        for i in sorted(self.ring_seeds):
            if not 0 <= i < self.num_rings:
                continue
            neighbours = [j for j in (i - 1, i + 1) if 0 <= j < self.num_rings]
            spare = sum(widths[j] - floor for j in neighbours)
            lo = RING_WIDTH_MIN * mean
            hi = min(RING_WIDTH_MAX * mean, widths[i] + spare)
            if hi <= lo:
                continue
            rng = random.Random(f"ring-width:{self.ring_seeds[i]}:{i}")
            # Prefer a width that visibly differs from the current one.
            target = max((rng.uniform(lo, hi) for _ in range(RING_WIDTH_DRAWS)),
                         key=lambda w: min(abs(w - widths[i]), RING_WIDTH_MIN_CHANGE * mean))
            delta = target - widths[i]
            if delta > 0:
                shares = [widths[j] - floor for j in neighbours]
            else:
                shares = [widths[j] for j in neighbours]
            total_share = sum(shares)
            if total_share <= 0:
                continue
            for j, share in zip(neighbours, shares):
                widths[j] -= delta * share / total_share
            widths[i] = target

    def _polar_to_cartesian(self, radius: float, angle_deg: float) -> tuple[float, float]:
        """Convert polar coordinates to cartesian (centered on canvas)."""
        angle_rad = math.radians(angle_deg)
        x = self.center_x + radius * math.cos(angle_rad)
        y = self.center_y + radius * math.sin(angle_rad)
        return (x, y)

    def generate(self, validate: bool = True) -> str:
        """
        Plan, assemble and (optionally) validate the design. With `max_region_cap` on, a valid design with
        oversized faces climbs the repair ladder (`region_repair.RegionRepair`) whether or not `validate` is
        set; `source_plan` keeps the plan of the final assembly, repairs included, for `generate_from_plan`.
        With the cap on, `validate=False` still validates internally, so the SVG does not depend on it.

        Returns the SVG document: one explicit path per placed piece of ink,
        grouped by ring. Raises `AssemblyError` (a `ValueError`) when a cell
        cannot be assembled.
        """
        print("\n=== GENERATING MANDALA ===")
        self.composer = self._new_composer()
        self.plan = self.composer.plan()
        self.source_plan = deepcopy(self.plan)
        self.assembled = self._assemble()
        self._log_assembly()

        self.last_validation_result = None
        self.last_validation_polylines = None
        if self.max_region_cap:
            # The ladder runs whatever `validate` says, so the SVG never depends on it (max-region spec 5).
            report, polylines = self._validation_report(self.assembled)
            final = Trial(self.source_plan, self.plan, self.assembled, report, polylines,
                          self._face_sets(self.assembled, report))
            if report.is_valid and final.sets:
                final = RegionRepair(self).run(final)
                self.source_plan, self.plan, self.assembled = final.source_plan, final.plan, final.assembled
                self.composer.adopt(self.plan)
                print(f"  Region cap: kept {len(self.plan.repairs)} repair(s), "
                      f"{len(final.sets)} oversized face set(s) left")
            if validate:
                self._record_validation(final.report, final.polylines)
        elif validate:
            self._validate()

        svg = self._render_svg()
        print("=== GENERATION COMPLETE ===\n")
        return svg

    def generate_from_plan(self, plan: DesignPlan, validate: bool = True) -> str:
        """
        Assemble and render a saved plan (a `source_plan`, repairs included) without planning or running
        the repair ladder, so a repaired design replays exactly. `plan` itself is left unchanged. Replay
        requires this generator's seed and ring_seeds (its ring geometry) to match the plan's.
        """
        print("\n=== GENERATING MANDALA FROM PLAN ===")
        self.source_plan = deepcopy(plan)
        self.plan = deepcopy(plan)
        self.composer = self._new_composer()
        self.composer.adopt(self.plan)
        self.assembled = self._assemble()
        self._log_assembly()

        self.last_validation_result = None
        self.last_validation_polylines = None
        if validate:
            self._validate()
        svg = self._render_svg()
        print("=== GENERATION COMPLETE ===\n")
        return svg

    def _log_assembly(self) -> None:
        print(f"  Ring divisions: {[ring.divisions for ring in self.plan.rings]}")
        print(f"  Placed {len(self.assembled.paths)} paths, {len(self.assembled.reaches)} reaches, "
              f"{self.assembled.dropped_children} dropped children, "
              f"{self.assembled.dropped_embellishments} dropped embellishments")

    def _new_composer(self) -> Composer:
        """A fresh composer with this generator's seed, rings and settings."""
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
            force_embellishments=self.force_embellishments,
            max_region_cap=self.max_region_cap,
        )
        return Composer(self.seed, self.rings, settings)

    def _face_sets(self, assembled: AssembledDesign, report: TopologyReport) -> List[FaceSet]:
        """The report's oversized faces, classified and grouped by the plan entry behind them."""
        return face_sets(classify_faces(report.oversized_regions, assembled.paths, self.rings, self.center))

    def _trial(self, plan: DesignPlan) -> Trial | None:
        """
        One repair trial: `plan` deep-copied as the trial's `source_plan`, another copy assembled with a
        fresh composer that adopts it, then validated and classified. None (the trial is rejected) when
        assembly fails, or when anything else in the trial raises: that is logged as a warning naming the
        trial's step and ring, and the ladder keeps its current valid design. The repair pass is best-effort
        (a design is never rejected for size), so only the first, unrepaired assembly in `generate` raises.
        """
        source_plan = deepcopy(plan)
        work = deepcopy(plan)
        try:
            composer = self._new_composer()
            composer.adopt(work)
            assembled = self._assemble(work, composer)
            report, polylines = self._validation_report(assembled)
            return Trial(source_plan, work, assembled, report, polylines, self._face_sets(assembled, report))
        except AssemblyError as error:
            print(f"  Repair trial failed to assemble: {error}")
            return None
        except Exception:
            last = plan.repairs[-1] if plan.repairs else {}
            logger.warning("Repair trial (step %s, ring %s) raised; rejecting it", last.get("step"), last.get("ring"),
                           exc_info=True)
            return None

    def _assemble(self, plan: DesignPlan | None = None, composer: Composer | None = None) -> AssembledDesign:
        """
        Assemble `plan` (default `self.plan`) with `composer` (default `self.composer`). A layered ring whose
        composite fails in pass two, or whose back a pass-two replacement dropped, loses its back for the
        whole ring and the design is assembled again (spec 5.4), at most once per ring.
        """
        plan = self.plan if plan is None else plan
        composer = self.composer if composer is None else composer
        dropped: set[int] = set()
        while True:
            try:
                return Assembler(
                    plan, self.rings, self.center, self.complexity, self.min_pattern_size, composer
                ).assemble()
            except LayeredRingFailed as failure:
                ring = next((r for r in plan.rings if r.ring_index == failure.ring_index), None)
                if failure.ring_index in dropped or ring is None:
                    raise
                dropped.add(failure.ring_index)
                print(f"  {failure}; dropping its back layer and assembling again")
                composer.drop_back(ring)

    def generate_ring_fragment(self, ring_index: int, ring_seed: int, validate: bool = True) -> dict[str, Any]:
        """
        Re-plan one ring with its own seed, re-pick its width (its neighbours
        absorb the change) and re-assemble the whole design.

        The whole document is returned because a changed ring changes its
        neighbours' reaches and overflow resolution.
        """
        if ring_index < 0 or ring_index >= len(self.rings):
            raise ValueError(f"ring_index must be between 0 and {len(self.rings) - 1}")

        print(f"\n=== REGENERATING RING {ring_index} ===")
        self.ring_seeds[ring_index] = ring_seed
        self._calculate_rings()
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

    def _validation_report(self, assembled: AssembledDesign) -> Tuple[TopologyReport, List[List[Tuple[float, float]]]]:
        """Validate `assembled` and return the report with the polylines it was measured on."""
        polylines = assembled.polylines()
        validator = TopologyValidator(
            snap_tolerance=2.5,     # gaps under a stroke width render connected
            whisker_tolerance=5.0,  # overshoot stubs up to 5px read as corners
            pen_radius=PEN_RADIUS_PX,  # a face must fit a 2px pen tip somewhere
            min_region_area=MIN_REGION_AREA_PX2,
            max_region_px2=max_region_px2(self.complexity) if self.max_region_cap else None,
        )
        result = validator.analyze(
            polylines,
            center=self.center,
            base_mask=assembled.base_mask(),
            ring_ids=assembled.ring_ids(),
            overflow_parts=assembled.overflow_parts(),
        )
        return result, polylines

    def _validate(self) -> None:
        result, polylines = self._validation_report(self.assembled)
        self._record_validation(result, polylines)

    def _record_validation(self, result: TopologyReport, polylines: List[List[Tuple[float, float]]]) -> None:
        """Keep `result` as the last validation and print its summary."""
        print("\n=== VALIDATING DESIGN ===")
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
