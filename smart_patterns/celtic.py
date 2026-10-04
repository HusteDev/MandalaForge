"""
Smart celtic patterns.
"""

import random
from typing import Any, Dict, List

from .core import CellPoint, PointTuple, SmartCellContext, SmartVector, _smart_elements


def generate_laced_cell(
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
    Create a simple laced-cell motif with paired side ports.

    Two mirrored side-to-side vectors meet at the center of the cell, producing
    a lightweight celtic-style crossing without separate over-under semantics.
    At higher complexity a horizontal bridge is added across the cell.
    """
    context = SmartCellContext(inner_radius, outer_radius, wedge_angle, center, stroke_width, complexity, rng, min_white_space)
    vectors = [
        SmartVector([CellPoint(0.28, -1.0), CellPoint(0.5, 0.0), CellPoint(0.28, 1.0)]),
        SmartVector([CellPoint(0.72, -1.0), CellPoint(0.5, 0.0), CellPoint(0.72, 1.0)]),
        SmartVector([CellPoint(0.0, 0.0), CellPoint(1.0, 0.0)]),
    ]
    if complexity >= 0.5:
        vectors.append(SmartVector([CellPoint(0.5, -1.0), CellPoint(0.5, 1.0)]))
    return _smart_elements(context, vectors)


def generate_braid_knot_cell(
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
    Create a compact Celtic braid knot.

    The two main strands enter and leave each side of the cell at matching
    radial ports, so repeated wedges read as a continuous braided band. The
    current smart analyzer does not model over-under semantics, so this uses
    close mirrored cords instead of actual strand crossings.
    """
    context = SmartCellContext(inner_radius, outer_radius, wedge_angle, center, stroke_width, complexity, rng, min_white_space)
    vectors = [
        SmartVector(
            [
                CellPoint(0.34, -1.0),
                CellPoint(0.46, -0.5),
                CellPoint(0.34, 0.0),
                CellPoint(0.46, 0.5),
                CellPoint(0.34, 1.0),
            ]
        ),
        SmartVector(
            [
                CellPoint(0.66, -1.0),
                CellPoint(0.54, -0.5),
                CellPoint(0.66, 0.0),
                CellPoint(0.54, 0.5),
                CellPoint(0.66, 1.0),
            ]
        ),
    ]
    inner_cord, outer_cord = 0.34, 0.66
    if complexity >= 0.55:
        vectors.extend(
            [
                SmartVector([CellPoint(0.22, -1.0), CellPoint(0.22, 0.0), CellPoint(0.22, 1.0)]),
                SmartVector([CellPoint(0.78, -1.0), CellPoint(0.78, 0.0), CellPoint(0.78, 1.0)]),
            ]
        )
        inner_cord, outer_cord = 0.22, 0.78

    # Binding rung, carried out to both boundaries. Without a radial connector
    # the cords are concentric loops that never subdivide the ring; without
    # reaching the boundaries the bands beyond the outer cord and inside the
    # inner one are crossed by nothing and become lanes around the design.
    vectors.append(SmartVector([
        CellPoint(0.0, 0.0),
        CellPoint(inner_cord, 0.0),
        CellPoint(outer_cord, 0.0),
        CellPoint(1.0, 0.0),
    ]))
    return _smart_elements(context, vectors)


def generate_greek_key(
    inner_radius: float,
    outer_radius: float,
    wedge_angle: float,
    center: PointTuple,
    complexity: float,
    stroke_width: float,
    rng: random.Random,
    min_white_space: float = 10.0,
    port_rng: random.Random | None = None,
    **_: Any,
) -> List[Dict[str, Any]]:
    """
    Create a Greek-key meander running side to side.

    The path enters and leaves at the same radial, so repeats form a continuous
    running key around the ring. A centerline riser ties the key to the inner
    boundary so the ring is subdivided rather than being one deep annulus.
    """
    context = SmartCellContext(inner_radius, outer_radius, wedge_angle, center, stroke_width, complexity, rng, min_white_space)
    ports = port_rng if port_rng is not None else rng

    low = 0.16 + ports.random() * 0.1
    high = 0.84
    if context.radial_to_px(high - low) < max(min_white_space, 8.0) * 2:
        high = min(0.9, low + context.px_to_radial(max(min_white_space, 8.0) * 2))

    shoulder = 0.62
    key = [
        CellPoint(low, -1.0),
        CellPoint(low, -shoulder),
        CellPoint(high, -shoulder),
        CellPoint(high, 0.0),
        CellPoint(high, shoulder),
        CellPoint(low, shoulder),
        CellPoint(low, 1.0),
    ]
    vectors = [
        SmartVector(key),
        SmartVector([CellPoint(0.0, 0.0), CellPoint(high, 0.0), CellPoint(1.0, 0.0)]),
    ]

    if complexity >= 0.55 and context.cell_width_px(low) >= min_white_space * 4.0:
        inner_step = low + (high - low) * 0.45
        vectors.append(SmartVector([
            CellPoint(inner_step, -shoulder), CellPoint(inner_step, shoulder),
        ]))
    return _smart_elements(context, vectors)


def generate_twist_band(
    inner_radius: float,
    outer_radius: float,
    wedge_angle: float,
    center: PointTuple,
    complexity: float,
    stroke_width: float,
    rng: random.Random,
    min_white_space: float = 10.0,
    port_rng: random.Random | None = None,
    **_: Any,
) -> List[Dict[str, Any]]:
    """
    Create two strands that trade places across the cell.

    Each strand enters at one radial and leaves at the other, so the SET of left
    ports equals the set of right ports and repeats interlock around the ring.
    Both strands carry a vertex at the crossing, so the meeting point lands on a
    vertex rather than mid-segment.
    """
    context = SmartCellContext(inner_radius, outer_radius, wedge_angle, center, stroke_width, complexity, rng, min_white_space)
    ports = port_rng if port_rng is not None else rng

    spread = max(context.px_to_radial(max(min_white_space, 9.0) * 2.0), 0.3)
    lower = 0.5 - spread / 2 + (ports.random() - 0.5) * 0.08
    lower = max(0.08, min(lower, 0.4))
    upper = min(0.94, lower + spread)
    middle = (lower + upper) / 2

    vectors = [
        SmartVector([CellPoint(lower, -1.0), CellPoint(middle, 0.0), CellPoint(upper, 1.0)]),
        SmartVector([CellPoint(upper, -1.0), CellPoint(middle, 0.0), CellPoint(lower, 1.0)]),
        SmartVector([CellPoint(0.0, 0.0), CellPoint(middle, 0.0), CellPoint(1.0, 0.0)]),
    ]
    return _smart_elements(context, vectors)


CELTIC_SMART_PATTERNS = [
    {
        "name": "smart_twist_band",
        "min_cell_width_px": 0.0,
        "category": "celtic",
        "generator": generate_twist_band,
        "allow_first_ring": True,
        "allow_last_ring": True,
        "min_ring_width": 18,
        "force_inner_boundary": False,
        "force_outer_boundary": False,
        "force_radial_boundaries": False,
    },
    {
        "name": "smart_greek_key",
        "min_cell_width_px": 0.0,
        "category": "celtic",
        "generator": generate_greek_key,
        "allow_first_ring": True,
        "allow_last_ring": True,
        "min_ring_width": 18,
        "force_inner_boundary": False,
        "force_outer_boundary": False,
        "force_radial_boundaries": False,
    },
    {
        "name": "smart_laced",
        "min_cell_width_px": 22.0,
        "category": "celtic",
        "generator": generate_laced_cell,
        "allow_first_ring": True,
        "allow_last_ring": True,
        "min_ring_width": 22,
        "force_inner_boundary": False,
        "force_outer_boundary": False,
        "force_radial_boundaries": False,
    },
    {
        "name": "smart_braid_knot",
        "min_cell_width_px": 0.0,
        "category": "celtic",
        "generator": generate_braid_knot_cell,
        "allow_first_ring": True,
        "allow_last_ring": True,
        "min_ring_width": 28,
        "force_inner_boundary": False,
        "force_outer_boundary": False,
        "force_radial_boundaries": False,
    },
]
