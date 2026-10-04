"""
Smart abstract patterns.
"""

import random
from typing import Any, Dict, List

from .core import (
    CellPoint,
    PointTuple,
    SmartCellContext,
    SmartVector,
    _smart_elements,
    _wave_points,
    mirror_points,
    quad_points,
)


def generate_bridge_band(
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
    Create one or more side-to-side wave bridges through the cell.

    Each wave begins on the left side and exits on the right side at a matching
    radial port, so repeated cells form continuous ring bands. A central radial
    connector anchors the waves to the ring boundaries.
    """
    context = SmartCellContext(inner_radius, outer_radius, wedge_angle, center, stroke_width, complexity, rng, min_white_space)
    line_count = 1 + int(complexity * 1.5)
    if line_count == 1:
        radials = [0.5]
    else:
        radials = [0.25 + (0.5 * idx / (line_count - 1)) for idx in range(line_count)]
    vectors = [
        SmartVector(_wave_points(radial, 0.04 + complexity * 0.04, 8, idx * 0.25))
        for idx, radial in enumerate(radials)
    ]
    vectors.append(SmartVector([CellPoint(0.0, 0.0), CellPoint(1.0, 0.0)]))
    return _smart_elements(context, vectors)


def generate_resonance_ladder(
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
    Create paired side-to-side rails with alternating diagonal rungs.

    The rails provide matching left/right ports across repeated cells. The
    rungs terminate on those rails, so they subdivide the cell without floating
    endpoints or extra side-boundary contracts.
    """
    context = SmartCellContext(inner_radius, outer_radius, wedge_angle, center, stroke_width, complexity, rng, min_white_space)
    lower_radial = 0.32
    upper_radial = 0.68
    rung_count = 2 + int(complexity * 2.0)
    rung_count = max(2, min(4, rung_count))
    step = 1.6 / rung_count

    vectors = [
        SmartVector([CellPoint(lower_radial, -1.0), CellPoint(lower_radial, 0.0), CellPoint(lower_radial, 1.0)]),
        SmartVector([CellPoint(upper_radial, -1.0), CellPoint(upper_radial, 0.0), CellPoint(upper_radial, 1.0)]),
        # Cross the bands outside the rails, or each becomes a lane running
        # around the design. These sit on the cell's left edge - shared with the
        # neighbouring cell, and clear of the rungs, so they add no crossings.
        SmartVector([CellPoint(0.0, -1.0), CellPoint(lower_radial, -1.0)]),
        SmartVector([CellPoint(upper_radial, -1.0), CellPoint(1.0, -1.0)]),
    ]

    for index in range(rung_count):
        left = -0.8 + step * index
        right = left + step * 0.72
        start_r, end_r = (
            (lower_radial, upper_radial) if index % 2 == 0
            else (upper_radial, lower_radial)
        )
        vectors.append(SmartVector([CellPoint(start_r, left), CellPoint(end_r, right)]))

    return _smart_elements(context, vectors)


def generate_ripple_stack(
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
    Create a stack of phase-shifted ripples across the cell.

    Band spacing is computed in pixels so the stack thins out on a narrow ring
    instead of collapsing into slivers. The centerline riser crosses each wave
    at the wave's own angular-0 vertex, so no crossing lands mid-segment.
    """
    context = SmartCellContext(inner_radius, outer_radius, wedge_angle, center, stroke_width, complexity, rng, min_white_space)

    gap_px = max(min_white_space, 9.0)
    room = int(context.radial_to_px(0.78 - 0.16) / gap_px)
    count = max(1, min(room, 2 + int(complexity * 3)))

    amplitude = min(0.05 + complexity * 0.04, context.px_to_radial(gap_px) * 0.35)
    vectors = []
    for index in range(count):
        radial = 0.16 + (0.62 * index / max(1, count - 1)) if count > 1 else 0.5
        vectors.append(SmartVector(_wave_points(radial, amplitude, 8, index * 0.3)))
    vectors.append(SmartVector([CellPoint(0.0, 0.0), CellPoint(1.0, 0.0)]))
    return _smart_elements(context, vectors)


def generate_flame_band(
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
    Create a closed flame rising from paired side ports.

    Authored as a half and mirrored, so the left and right ports are identical
    by construction. The tip stays strictly inside the cell: a sharp apex landing
    on a boundary arc gets sliced into slivers thinner than a pen tip.
    """
    context = SmartCellContext(inner_radius, outer_radius, wedge_angle, center, stroke_width, complexity, rng, min_white_space)
    ports = port_rng if port_rng is not None else rng

    base = 0.1 + ports.random() * 0.12
    tip = min(0.9, base + 0.45 + complexity * 0.2)
    half = quad_points(
        CellPoint(base, -1.0),
        CellPoint(base + (tip - base) * 0.75, -0.92),
        CellPoint(tip, 0.0),
        steps=8,
    )
    outline = half + list(reversed(mirror_points(half)))[1:]
    vectors = [
        SmartVector(outline, closed=True),
        # Midrib: ties the flame to the inner boundary and carries on past the
        # tip to the outer one, so no band is left uncrossed.
        SmartVector([
            CellPoint(0.0, 0.0),
            CellPoint(base, 0.0),
            CellPoint(tip, 0.0),
            CellPoint(1.0, 0.0),
        ]),
    ]

    if complexity >= 0.6 and context.radial_to_px(tip - base) >= max(min_white_space, 8.0) * 2.5:
        inner_tip = base + (tip - base) * 0.55
        inner_half = quad_points(
            CellPoint(base, -0.55),
            CellPoint(base + (inner_tip - base) * 0.75, -0.5),
            CellPoint(inner_tip, 0.0),
            steps=6,
        )
        vectors.append(SmartVector(
            inner_half + list(reversed(mirror_points(inner_half)))[1:],
            closed=True,
        ))
    return _smart_elements(context, vectors)


ABSTRACT_SMART_PATTERNS = [
    {
        "name": "smart_ripple_stack",
        "min_cell_width_px": 0.0,
        "category": "abstract",
        "generator": generate_ripple_stack,
        "allow_first_ring": True,
        "allow_last_ring": True,
        "min_ring_width": 18,
        "force_inner_boundary": False,
        "force_outer_boundary": False,
        "force_radial_boundaries": False,
    },
    {
        "name": "smart_flame_band",
        "min_cell_width_px": 24.0,
        "category": "abstract",
        "generator": generate_flame_band,
        "allow_first_ring": True,
        "allow_last_ring": True,
        "min_ring_width": 20,
        "force_inner_boundary": False,
        "force_outer_boundary": False,
        "force_radial_boundaries": False,
    },
    {
        "name": "smart_bridge_band",
        "min_cell_width_px": 0.0,
        "category": "abstract",
        "generator": generate_bridge_band,
        "allow_first_ring": True,
        "allow_last_ring": True,
        "min_ring_width": 16,
        "force_inner_boundary": False,
        "force_outer_boundary": False,
        "force_radial_boundaries": False,
    },
    {
        "name": "smart_resonance_ladder",
        "min_cell_width_px": 0.0,
        "category": "abstract",
        "generator": generate_resonance_ladder,
        "allow_first_ring": True,
        "allow_last_ring": True,
        "min_ring_width": 24,
        "force_inner_boundary": False,
        "force_outer_boundary": False,
        "force_radial_boundaries": False,
    },
]
