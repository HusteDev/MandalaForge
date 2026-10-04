"""
Fallback smart patterns.
"""

import random
from typing import Any, Dict, List

from .core import CellPoint, PointTuple, SmartCellContext, SmartVector, _smart_elements


def generate_safe_spoke_cell(
    inner_radius: float,
    outer_radius: float,
    wedge_angle: float,
    center: PointTuple,
    complexity: float,
    stroke_width: float,
    rng: random.Random,
    min_white_space: float = 10.0,
    **_: Any,
) -> List[Dict[str, Any]]:
    """
    Create the minimal guaranteed-safe fallback cell.

    The pattern is a single radial spoke from the inner boundary to the outer
    boundary. It is used only when selected category patterns are rejected by
    the smart analyzer, usually because a high minimum-white-space setting
    makes richer geometry invalid.
    """
    context = SmartCellContext(inner_radius, outer_radius, wedge_angle, center, stroke_width, complexity, rng, min_white_space)
    vectors = [SmartVector([CellPoint(0.0, 0.0), CellPoint(1.0, 0.0)])]
    return _smart_elements(context, vectors)


def get_safe_fallback_pattern(category: str) -> Dict[str, Any]:
    safe_category = category.lower()
    return {
        "name": f"smart_{safe_category}_safe_spoke",
        "category": safe_category,
        "generator": generate_safe_spoke_cell,
        "allow_first_ring": True,
        "allow_last_ring": True,
        "min_ring_width": 0,
        "min_cell_width_px": 0.0,
        "is_safe_fallback": True,
        "force_inner_boundary": False,
        "force_outer_boundary": False,
        "force_radial_boundaries": False,
    }
