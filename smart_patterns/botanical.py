"""
Smart botanical patterns.
"""

import math
import random
from typing import Any, Dict, List

from .core import (
    CellPoint,
    PointTuple,
    SmartCellContext,
    SmartVector,
    _smart_elements,
    _wave_points,
    quad_points,
)


def _interpolate(first: CellPoint, second: CellPoint, t: float) -> CellPoint:
    return CellPoint(
        radial=first.radial + (second.radial - first.radial) * t,
        angular=first.angular + (second.angular - first.angular) * t,
    )


def _edge_points(
    start: CellPoint,
    end: CellPoint,
    mode: str,
    roundness: float,
    complexity: float,
    side: int,
    steps: int = 5,
) -> List[CellPoint]:
    points = []
    for index in range(steps + 1):
        t = index / steps
        base = _interpolate(start, end, t)
        if index in (0, steps) or mode == "straight":
            points.append(base)
            continue

        bulge = math.sin(t * math.pi)
        angular_offset = side * roundness * 0.16 * bulge
        radial_offset = roundness * 0.04 * bulge
        if mode == "wavy":
            wave = math.sin(t * math.pi * 3.0)
            angular_offset += side * wave * complexity * 0.06
            radial_offset += wave * complexity * 0.025
        points.append(
            CellPoint(
                radial=max(0.0, min(1.0, base.radial + radial_offset)),
                angular=max(-1.0, min(1.0, base.angular + angular_offset)),
            )
        )
    return points


def generate_petal_cell(
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
    """Create petal arms from the lower center toward side boundaries."""
    context = SmartCellContext(inner_radius, outer_radius, wedge_angle, center, stroke_width, complexity, rng, min_white_space)
    ports = port_rng if port_rng is not None else rng
    roundness = 0.15 + rng.random() * 0.7
    base = CellPoint(0.0, 0.0)
    left_port = 0.62 + ports.random() * 0.2
    right_port = left_port
    allow_adjacent = False
    if complexity >= 0.7:
        offset = (ports.random() - 0.5) * 0.24
        right_port = max(0.5, min(0.92, left_port + offset))
        allow_adjacent = abs(left_port - right_port) > 0.015

    left_tip = CellPoint(left_port, -1.0)
    right_tip = CellPoint(right_port, 1.0)
    peak = CellPoint(1.0, 0.0)
    left_mode = "rounded" if complexity >= 0.35 else "straight"
    right_mode = "rounded" if complexity >= 0.35 else "straight"
    if complexity >= 0.82 and rng.random() < 0.5:
        left_mode = "wavy"
    if complexity >= 0.82 and rng.random() < 0.5:
        right_mode = "wavy"
    vectors = [
        SmartVector(
            _edge_points(base, left_tip, left_mode, roundness, complexity, -1),
            allow_adjacent_intersections=allow_adjacent,
        ),
        SmartVector(
            _edge_points(base, right_tip, right_mode, roundness, complexity, 1),
            allow_adjacent_intersections=allow_adjacent,
        ),
        SmartVector([base, peak]),
        # Upper arms from each side port to the tip. Without them everything
        # above the ports is bare except the stem, leaving an empty band.
        SmartVector(_edge_points(peak, left_tip, left_mode, roundness * 0.7, complexity, -1)),
        SmartVector(_edge_points(peak, right_tip, right_mode, roundness * 0.7, complexity, 1)),
    ]
    if allow_adjacent:
        vectors.extend(
            [
                SmartVector(
                    [CellPoint(left_port, -1.0), CellPoint(right_port, -1.0)],
                    allow_adjacent_intersections=True,
                ),
                SmartVector(
                    [CellPoint(left_port, 1.0), CellPoint(right_port, 1.0)],
                    allow_adjacent_intersections=True,
                ),
            ]
        )
    return _smart_elements(context, vectors)


def generate_leaf_cell(
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
    """Create a leaf from a centerline apex and lower corner edges."""
    context = SmartCellContext(inner_radius, outer_radius, wedge_angle, center, stroke_width, complexity, rng, min_white_space)
    roundness = 0.15 + rng.random() * 0.7
    # The tip always reaches the outer boundary. A shorter apex left the band
    # above it carrying nothing but the midrib - twelve bare spokes across an
    # otherwise empty ring, which reads as a corridor even though it is
    # technically crossed. Shape variety comes from the waist instead.
    apex_radial = 1.0
    apex = CellPoint(apex_radial, 0.0)
    roundness = 0.25 + rng.random() * 0.85
    lower_port = 0.0
    left_corner = CellPoint(lower_port, -1.0)
    right_corner = CellPoint(lower_port, 1.0)
    if complexity < 0.35:
        mode = "straight"
    elif complexity < 0.75:
        mode = "rounded"
    else:
        mode = "wavy" if rng.random() < 0.5 else "rounded"
    left_edge = _edge_points(apex, left_corner, mode, roundness, complexity, -1)
    right_edge = _edge_points(apex, right_corner, mode, roundness, complexity, 1)
    vectors = [
        SmartVector([CellPoint(lower_port, 0.0), apex]),
        SmartVector(left_edge),
        SmartVector(right_edge),
    ]
    if complexity >= 0.55:
        branch_anchor = CellPoint(apex_radial * 0.62, 0.0)
        left_branch_target = left_edge[max(2, len(left_edge) // 2)]
        right_branch_target = right_edge[max(2, len(right_edge) // 2)]
        vectors.extend(
            [
                SmartVector([branch_anchor, left_branch_target]),
                SmartVector([branch_anchor, right_branch_target]),
            ]
        )
    return _smart_elements(context, vectors)


def generate_vine_band(
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
    Create side-to-side botanical bands that read as vines around the ring.

    Every band enters and exits at paired side ports. A central radial stem
    anchors the linework to the ring boundaries.
    """
    context = SmartCellContext(inner_radius, outer_radius, wedge_angle, center, stroke_width, complexity, rng, min_white_space)
    amplitude = 0.035 + complexity * 0.035
    vectors = [
        SmartVector(_wave_points(0.38, amplitude, 8, 0.0)),
        SmartVector(_wave_points(0.66, amplitude, 8, 0.5)),
        SmartVector([CellPoint(0.0, 0.0), CellPoint(1.0, 0.0)]),
    ]
    if complexity >= 0.7:
        vectors.append(SmartVector(_wave_points(0.52, amplitude * 0.75, 8, 0.25)))
    return _smart_elements(context, vectors)


def generate_scallop_band(
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
    Create rows of scallop swags hanging from carrier bands.

    Each swag starts and ends on an exact carrier vertex, so it is an arc with
    both feet on real ink rather than a floating loop. Two rows are used when
    the ring is deep enough: a single row left most of the ring carrying
    nothing but the stem, which reads as an empty band running around the
    design even though the stem technically crosses it.
    """
    context = SmartCellContext(inner_radius, outer_radius, wedge_angle, center, stroke_width, complexity, rng, min_white_space)
    ports = port_rng if port_rng is not None else rng

    # Wide scallops: one or two per cell, so each swag is deep enough to be
    # worth colouring instead of a shallow nick.
    swags = 1 if context.cell_width_px(0.6) < max(min_white_space, 10.0) * 5.0 else 2
    chord_px = context.angular_to_px(2.0 / swags, 0.6)
    dip_px = max(5.0, min(chord_px * 0.32, context.ring_width * 0.30))
    dip = context.px_to_radial(dip_px)

    # Stack rows from just under the outer boundary downwards, spaced so each
    # row's swags nearly meet the carrier below. One row left most of the ring
    # carrying nothing but the stem, which reads as an empty band running right
    # around the design even though the stem technically crosses it.
    # The top carrier has to clear the OUTER boundary by a colourable margin as
    # well, or the strip between the two is thinner than a pen tip.
    margin = context.px_to_radial(max(min_white_space, 10.0))
    top = min(0.90 + ports.random() * 0.06, 1.0 - margin)
    # Each row sits a full swag-depth PLUS a colourable gap below the one above,
    # so the pocket between a swag's belly and the next carrier is worth
    # colouring rather than a pinched sliver.
    step = dip + context.px_to_radial(max(min_white_space, 10.0) * 1.2)
    carriers = []
    level = top
    # The lowest swag has to clear the inner boundary by a colourable margin,
    # or the sliver beneath it is thinner than a pen tip.
    floor = margin
    while level - dip > floor and len(carriers) < 6:
        carriers.append(level)
        level -= step

    vectors = []
    rows = []
    for carrier_radial in carriers:
        anchors = [CellPoint(carrier_radial, -1.0 + 2.0 * i / swags) for i in range(swags + 1)]
        rows.append((carrier_radial, swags, anchors))
        vectors.append(SmartVector(anchors))

    # Depth is a fraction of the swag's own CHORD, not a fixed pixel drop. A
    # fixed drop made each swag as deep as it was wide, so it rendered as a
    # narrow spike - a stray tick mark rather than a scallop.
    for carrier_radial, swags, anchors in rows:
        chord_px = context.angular_to_px(2.0 / swags, carrier_radial)
        drop = min(dip, carrier_radial * 0.75)
        dip_real = context.radial_to_px(drop)

        # The pocket under each swag has to be worth colouring: roughly
        # (2/3) * chord * dip of area, and deep enough for a pen tip.
        if chord_px < 12.0 or dip_real < 5.0:
            continue
        if (2.0 / 3.0) * chord_px * dip_real < 20.0:
            continue
        for index in range(swags):
            start_pt, end_pt = anchors[index], anchors[index + 1]
            vectors.append(SmartVector(quad_points(
                start_pt,
                CellPoint(max(0.02, carrier_radial - drop * 2.0),
                          (start_pt.angular + end_pt.angular) / 2),
                end_pt,
                steps=6,
            )))

    # Full-height stem. It must carry a vertex at EVERY radial where something
    # meets it - each carrier and each swag belly. A belly landing mid-segment
    # reads as a pinched pocket to the white-space check.
    levels = {0.0, 1.0}
    for carrier_radial, _, _ in rows:
        levels.add(carrier_radial)
        levels.add(max(0.0, carrier_radial - min(dip, carrier_radial * 0.75)))
    spine = [CellPoint(level, 0.0) for level in sorted(levels)]
    vectors.append(SmartVector(spine))
    return _smart_elements(context, vectors)


BOTANICAL_SMART_PATTERNS = [
    {
        "name": "smart_scallop_band",
        "min_cell_width_px": 26.0,
        # a scallop border reads as a band; on a ring several times taller than
        # its cells the rows stack into pinched pockets instead
        "max_ring_aspect": 3.5,
        "category": "botanical",
        "generator": generate_scallop_band,
        "allow_first_ring": True,
        "allow_last_ring": True,
        "min_ring_width": 18,
        "force_inner_boundary": False,
        "force_outer_boundary": False,
        "force_radial_boundaries": False,
    },
    {
        "name": "smart_petal",
        "min_cell_width_px": 0.0,
        "category": "botanical",
        "generator": generate_petal_cell,
        "allow_first_ring": True,
        "allow_last_ring": True,
        "min_ring_width": 18,
        "force_inner_boundary": False,
        "force_outer_boundary": False,
        "force_radial_boundaries": False,
    },
    {
        "name": "smart_leaf",
        "min_cell_width_px": 22.0,
        "category": "botanical",
        "generator": generate_leaf_cell,
        "allow_first_ring": True,
        "allow_last_ring": True,
        "min_ring_width": 18,
        "force_inner_boundary": False,
        "force_outer_boundary": False,
        "force_radial_boundaries": False,
    },
    {
        "name": "smart_vine_band",
        "min_cell_width_px": 0.0,
        "category": "botanical",
        "generator": generate_vine_band,
        "allow_first_ring": True,
        "allow_last_ring": True,
        "min_ring_width": 16,
        "force_inner_boundary": False,
        "force_outer_boundary": False,
        "force_radial_boundaries": False,
    },
]
