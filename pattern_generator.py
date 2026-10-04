"""
Pattern Generator for Mandala Coloring Pages

Selects and generates patterns for each ring of the mandala.
Each ring gets ONE pattern that will be rotated for radial symmetry.
"""

import math
import random
from typing import List, Dict, Any, Tuple


BOUNDARY_FORCE_KEYS = (
    'force_inner_boundary',
    'force_outer_boundary',
    'force_radial_boundaries',
)


class PatternGenerator:
    """
    Generates patterns for mandala rings.

    Workflow:
    1. Select a pattern from enabled categories for each ring
    2. Generate SVG elements for ONE wedge of that pattern
    3. The main generator rotates these elements for symmetry
    """

    def __init__(
        self,
        seed: int,
        complexity: float,
        min_pattern_size: float,
        categories: List[str],
        force_pattern_name: str | None = None
    ):
        self.seed = seed
        # Set by the QA harness to pin one pattern. Deliberately bypasses the
        # ring-position and size gates so the harness can probe OUTSIDE a
        # pattern's declared envelope, and disables the fallback chain so a
        # rejection surfaces as a failure instead of a silent substitution.
        self.force_pattern_name = force_pattern_name
        self.complexity = complexity
        self.min_pattern_size = min_pattern_size
        self.categories = categories
        self.selected_categories = {category.lower() for category in categories}

        # Create seeded random generator
        self.rng = random.Random(seed)

        from smart_patterns import get_smart_patterns_for_categories
        self.available_patterns = get_smart_patterns_for_categories(categories)
        self.last_used_pattern = None

        print(f"[PatternGenerator] Initialized:")
        print(f"  Categories: {categories}")
        print(f"  Available patterns: {len(self.available_patterns)}")

    @staticmethod
    def _cell_width_px(inner_radius: float, outer_radius: float, wedge_angle: float) -> float:
        """
        Width of a cell at its mid radius, in pixels.

        Ring width only measures the radial dimension, which varies about 8x
        across the supported settings. The angular dimension varies ~45x
        (a cell is a few px wide on the innermost ring at 24 divisions and
        ~150px on the outermost at 6), so it is the dimension that actually
        decides whether a motif fits.
        """
        mid_radius = inner_radius + (outer_radius - inner_radius) * 0.5
        return mid_radius * math.radians(wedge_angle)

    def _fits_cell(
        self,
        pattern: Dict[str, Any],
        cell_width_px: float | None,
        ring_width: float | None = None,
    ) -> bool:
        if cell_width_px is None:
            return True
        if cell_width_px < pattern.get('min_cell_width_px', 0.0):
            return False
        # Some motifs only read correctly on a band. A ring many times taller
        # than it is wide is a different shape, and forcing a band pattern into
        # it either pinches or leaves most of the ring bare.
        max_aspect = pattern.get('max_ring_aspect')
        if max_aspect and ring_width and cell_width_px > 0:
            if ring_width / cell_width_px > max_aspect:
                return False
        return True

    def _is_selected_category(self, category: str) -> bool:
        return category.lower() in self.selected_categories

    def _ensure_selected_category(self, pattern: Dict[str, Any]):
        if not self._is_selected_category(pattern.get('category', '')):
            raise ValueError(
                f"Pattern '{pattern.get('name')}' category '{pattern.get('category')}' "
                f"is not in selected categories {sorted(self.selected_categories)}"
            )

    def _boundary_forces(self, pattern: Dict[str, Any]) -> Dict[str, bool]:
        return {
            key: bool(pattern.get(key, False))
            for key in BOUNDARY_FORCE_KEYS
        }

    def _pattern_info(
        self,
        pattern: Dict[str, Any],
        pattern_rng_seed: int,
        ring_index: int
    ) -> Dict[str, Any]:
        return {
            'name': pattern['name'],
            'category': pattern['category'],
            'generator': pattern['generator'],
            'pattern_rng_seed': pattern_rng_seed,
            'ring_index': ring_index,
            'is_safe_fallback': bool(pattern.get('is_safe_fallback', False)),
            **self._boundary_forces(pattern)
        }

    def select_pattern_for_ring(
        self,
        ring_index: int,
        inner_radius: float,
        outer_radius: float,
        is_first_ring: bool,
        is_last_ring: bool,
        avoid_pattern_names: List[str] | None = None,
        wedge_angle: float | None = None
    ) -> Dict[str, Any]:
        """
        Select a pattern for a ring without generating it.

        Returns pattern info dict that can be passed to generate_ring_variations.
        """
        if self.force_pattern_name:
            forced = self._find_pattern(self.force_pattern_name)
            if forced is None:
                raise ValueError(f"Unknown forced pattern '{self.force_pattern_name}'")
            return self._pattern_info(forced, self.seed + ring_index * 17, ring_index)

        ring_width = outer_radius - inner_radius
        cell_width = (
            None if wedge_angle is None
            else self._cell_width_px(inner_radius, outer_radius, wedge_angle)
        )

        # Filter patterns valid for this ring position
        valid_patterns = []
        for pattern in self.available_patterns:
            if is_first_ring and not pattern.get('allow_first_ring', True):
                continue
            if is_last_ring and not pattern.get('allow_last_ring', True):
                continue
            min_size = pattern.get('min_ring_width', 0)
            if ring_width < min_size:
                continue
            if not self._fits_cell(pattern, cell_width, ring_width):
                continue
            valid_patterns.append(pattern)

        if not valid_patterns:
            return None

        avoid_pattern_names = avoid_pattern_names or []
        selection_pool = valid_patterns
        if avoid_pattern_names and len(valid_patterns) > 1:
            varied_pool = [
                pattern for pattern in valid_patterns
                if pattern['name'] not in avoid_pattern_names
            ]
            if varied_pool:
                selection_pool = varied_pool
                print(
                    f"  Variety filter: avoiding {avoid_pattern_names}; "
                    f"candidates: {[pattern['name'] for pattern in selection_pool]}"
                )
            else:
                print(
                    f"  Variety fallback: all valid patterns match {avoid_pattern_names}; "
                    "using full candidate pool"
                )

        print(f"  Valid pattern candidates: {[pattern['name'] for pattern in valid_patterns]}")

        # Select pattern using seeded randomness
        pattern_rng = random.Random(self.seed + ring_index * 17)
        selected_pattern = pattern_rng.choice(selection_pool)
        self._ensure_selected_category(selected_pattern)

        return self._pattern_info(selected_pattern, self.seed + ring_index * 17, ring_index)

    def _find_pattern(self, name: str) -> Dict[str, Any] | None:
        """Look a pattern up by name, including the per-category safe spokes."""
        from smart_patterns import SMART_PATTERNS, get_safe_fallback_pattern

        for pattern in SMART_PATTERNS:
            if pattern['name'] == name:
                return pattern
        for category in self.selected_categories:
            fallback = get_safe_fallback_pattern(category)
            if fallback['name'] == name:
                return fallback
        return None

    def _build_candidates(
        self,
        pattern_info: Dict[str, Any],
        inner_radius: float,
        outer_radius: float,
        is_first_ring: bool,
        is_last_ring: bool,
        wedge_angle: float | None = None
    ) -> List[Dict[str, Any]]:
        """Ordered fallback chain: the selection, then alternates, then the safe spoke."""
        if self.force_pattern_name:
            return [pattern_info]

        candidates = [pattern_info]
        self._ensure_selected_category(pattern_info)
        ring_width = outer_radius - inner_radius
        cell_width = (
            None if wedge_angle is None
            else self._cell_width_px(inner_radius, outer_radius, wedge_angle)
        )
        for pattern in self.available_patterns:
            self._ensure_selected_category(pattern)
            if pattern['name'] == pattern_info['name']:
                continue
            if is_first_ring and not pattern.get('allow_first_ring', True):
                continue
            if is_last_ring and not pattern.get('allow_last_ring', True):
                continue
            if ring_width < pattern.get('min_ring_width', 0):
                continue
            if not self._fits_cell(pattern, cell_width, ring_width):
                continue
            candidates.append(
                self._pattern_info(
                    pattern,
                    pattern_info['pattern_rng_seed'],
                    pattern_info.get('ring_index', 0)
                )
            )

        from smart_patterns import get_safe_fallback_pattern
        fallback = get_safe_fallback_pattern(pattern_info['category'])
        self._ensure_selected_category(fallback)
        candidates.append(
            self._pattern_info(
                fallback,
                pattern_info['pattern_rng_seed'],
                pattern_info.get('ring_index', 0)
            )
        )
        return candidates

    def _generate_candidate_elements(
        self,
        candidate: Dict[str, Any],
        inner_radius: float,
        outer_radius: float,
        wedge_angle: float,
        center: Tuple[float, float],
        is_first_ring: bool,
        is_last_ring: bool,
        extension: float
    ) -> List[Dict[str, Any]]:
        base_stroke = 1.0
        max_stroke = 2.5
        stroke_width = base_stroke + (max_stroke - base_stroke) * (1.0 - self.complexity * 0.5)

        pattern_rng = random.Random(candidate['pattern_rng_seed'] + int(extension * 1000))
        # Side ports must land at the same radius in every variation of a ring,
        # or cells drawn from different variations cannot meet at the boundary
        # they share. Anything positional on a side boundary draws from this
        # ring-stable stream instead of the per-variation one.
        port_rng = random.Random(candidate['pattern_rng_seed'])

        return candidate['generator'](
            inner_radius=inner_radius,
            outer_radius=outer_radius,
            wedge_angle=wedge_angle,
            center=center,
            complexity=self.complexity,
            stroke_width=stroke_width,
            ring_index=candidate.get('ring_index', 0),
            is_first_ring=is_first_ring,
            is_last_ring=is_last_ring,
            rng=pattern_rng,
            port_rng=port_rng,
            min_white_space=self.min_pattern_size
        )

    def generate_ring_variations(
        self,
        pattern_info: Dict[str, Any],
        inner_radius: float,
        outer_radius: float,
        wedge_angle: float,
        center: Tuple[float, float],
        is_first_ring: bool,
        is_last_ring: bool,
        extensions: List[float],
        candidate_validator=None
    ) -> Tuple[Dict[str, Any], List[List[Dict[str, Any]]]]:
        """
        Generate every variation of one ring from a SINGLE pattern.

        Fallback is a ring-level decision. Letting individual variations fall
        back separately produced rings whose cells came from different patterns,
        and since each pattern puts its side ports at its own radii, neighboring
        cells then had nothing to connect to.

        Args:
            extensions: one extension value per variation

        Returns:
            (policy of the pattern actually used, elements for each variation)
        """
        if not pattern_info:
            return {}, []

        # Smart patterns are generated inside the exact cell. They can touch
        # left/right boundaries, but they cannot extend the cell angle because
        # that breaks radial port matching between repeated neighbors.
        candidates = self._build_candidates(
            pattern_info, inner_radius, outer_radius, is_first_ring, is_last_ring,
            wedge_angle
        )

        errors = []
        for candidate in candidates:
            candidate_policy = {
                'name': candidate['name'],
                'category': candidate['category'],
                'is_fallback': candidate['name'] != pattern_info['name'],
                'is_safe_fallback': bool(candidate.get('is_safe_fallback', False)),
                **self._boundary_forces(candidate)
            }
            try:
                variations = [
                    self._generate_candidate_elements(
                        candidate, inner_radius, outer_radius, wedge_angle,
                        center, is_first_ring, is_last_ring, extension
                    )
                    for extension in extensions
                ]
                if any(not elements for elements in variations):
                    raise ValueError("pattern produced an empty variation")

                if candidate_validator is not None:
                    validation_error = candidate_validator(variations, candidate_policy)
                    if validation_error:
                        raise ValueError(validation_error)

                self.last_used_pattern = candidate_policy
                if candidate['name'] != pattern_info['name']:
                    fallback_type = "safe fallback" if candidate.get('is_safe_fallback') else "alternate pattern"
                    print(f"  Using {fallback_type}: {candidate['name']} after {pattern_info['name']} was rejected")
                return candidate_policy, variations
            except ValueError as exc:
                print(f"  Rejected pattern candidate: {candidate['name']} ({exc})")
                errors.append(f"{candidate['name']}: {exc}")

        raise ValueError("All smart pattern candidates failed: " + " | ".join(errors))
