"""
Smart geometric patterns.
"""

import random
from typing import Any, Dict, List

from .core import (
    CellPoint,
    PointTuple,
    SmartCellContext,
    SmartVector,
    _smart_elements,
    mirror_points,
)


def generate_diamond_cell(
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
    Create a diamond cell with four boundary contacts.

    The outer point, inner point, and paired side points create a closed
    colorable diamond. A radial spoke and side-to-side line subdivide the
    diamond while keeping all endpoints connected to boundaries or other
    vectors.
    """
    context = SmartCellContext(inner_radius, outer_radius, wedge_angle, center, stroke_width, complexity, rng, min_white_space)
    vectors = [
        SmartVector(
            [
                CellPoint(1.0, 0.0),
                CellPoint(0.5, -1.0),
                CellPoint(0.0, 0.0),
                CellPoint(0.5, 1.0),
            ],
            closed=True,
        ),
        SmartVector([CellPoint(0.0, 0.0), CellPoint(1.0, 0.0)]),
        SmartVector([CellPoint(0.5, -1.0), CellPoint(0.5, 1.0)]),
    ]
    return _smart_elements(context, vectors)


def generate_prism_lattice(
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
    Create a faceted prism lattice with mirrored side ports.

    The outer closed polygon gives each repeated wedge matching side contacts.
    Interior struts terminate on that polygon or ring boundaries, forming
    colorable triangular facets without floating endpoints.
    """
    context = SmartCellContext(inner_radius, outer_radius, wedge_angle, center, stroke_width, complexity, rng, min_white_space)

    lower_port = 0.32
    upper_port = 0.68
    left_lower = CellPoint(lower_port, -1.0)
    left_upper = CellPoint(upper_port, -1.0)
    right_lower = CellPoint(lower_port, 1.0)
    right_upper = CellPoint(upper_port, 1.0)
    inner_anchor = CellPoint(0.0, 0.0)
    outer_anchor = CellPoint(1.0, 0.0)
    left_mid = CellPoint(0.5, -0.82)
    right_mid = CellPoint(0.5, 0.82)

    vectors = [
        SmartVector(
            [
                inner_anchor,
                left_lower,
                left_mid,
                left_upper,
                outer_anchor,
                right_upper,
                right_mid,
                right_lower,
            ],
            closed=True,
        ),
        SmartVector([inner_anchor, outer_anchor]),
    ]

    if complexity >= 0.45:
        vectors.extend(
            [
                SmartVector([inner_anchor, left_mid]),
                SmartVector([inner_anchor, right_mid]),
            ]
        )

    if complexity >= 0.7:
        vectors.extend(
            [
                SmartVector([outer_anchor, left_mid]),
                SmartVector([outer_anchor, right_mid]),
            ]
        )

    return _smart_elements(context, vectors)


def generate_triangle_band(
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
    Create a triangle standing on the inner boundary, apex at the outer.

    Corner points sit at radial 0 and 1, which `boundary_side` resolves as
    inner/outer rather than left/right, so the corners anchor to the ring
    boundaries without creating any side-port obligation. Adjacent cells share
    those corners, so the ring reads as a continuous zigzag of triangles.
    """
    context = SmartCellContext(inner_radius, outer_radius, wedge_angle, center, stroke_width, complexity, rng, min_white_space)

    # On a tall ring at high division counts the cell is only a few px across at
    # the inner boundary, which would make the triangle a needle thinner than a
    # pen tip for most of its length. Start the base where the cell is wide
    # enough to colour; the corners then sit on the side boundaries at a shared
    # radial, so neighbouring cells still meet.
    base = context.radial_for_cell_width(max(min_white_space, 10.0) * 1.4)
    # A small lift would leave a paper-thin annulus between the inner boundary
    # and the base that nothing can colour. Either clear that gap properly or
    # sit on the boundary.
    if context.radial_to_px(base) < max(min_white_space, 8.0):
        base = 0.0

    # The spine anchors the motif to both ring boundaries and gives any
    # centerline vertex something to terminate on.
    # Split at `base` so the spine MEETS the triangle's base edge at a shared
    # vertex instead of crossing it mid-segment: a crossing there reads as a
    # tiny pocket to the white-space check, which measures the crossing against
    # the endpoints of the segments involved.
    vectors = [
        SmartVector([CellPoint(0.0, 0.0), CellPoint(base, 0.0)]),
        SmartVector([CellPoint(base, 0.0), CellPoint(1.0, 0.0)]),
        SmartVector(
            [CellPoint(base, -1.0), CellPoint(base, 1.0), CellPoint(1.0, 0.0)],
            closed=True,
        ),
    ]

    # A cross-tie between the two edges bands the triangle. Its ends sit ON the
    # edges, so nothing floats, and unlike a nested apex it never puts an acute
    # vertex on the spine - that shape pinches into slivers thinner than a pen.
    if complexity >= 0.5:
        for ratio in ((0.42,) if complexity < 0.75 else (0.32, 0.6)):
            left = CellPoint(
                base + (1.0 - base) * ratio,
                -1.0 + ratio,
            )
            right = CellPoint(left.radial, -left.angular)
            if context.angular_to_px(right.angular - left.angular, left.radial) >= min_white_space:
                # Carry a vertex at the centerline, where the tie meets the
                # spine. The white-space check measures a crossing against the
                # endpoints of the segments involved, so crossing mid-segment
                # reads as a pinch; crossing AT a vertex does not.
                vectors.append(SmartVector([left, CellPoint(left.radial, 0.0), right]))

    return _smart_elements(context, vectors)


def generate_star_point(
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
    Create one spike of an n-pointed star; repeats close the star around the ring.

    The outline is authored as a half and mirrored, so the left and right side
    ports are identical by construction and can never drift apart.
    """
    context = SmartCellContext(inner_radius, outer_radius, wedge_angle, center, stroke_width, complexity, rng, min_white_space)
    ports = port_rng if port_rng is not None else rng
    port = 0.34 + ports.random() * 0.16

    # Pull the notch toward the centerline when the cell is narrow, or the
    # shoulder pinches into a sliver against the spike edge.
    notch_angular = -0.45 if context.cell_width_px(0.6) >= min_white_space * 4.0 else -0.25
    half = [
        CellPoint(1.0, 0.0),
        CellPoint(0.6, notch_angular),
        CellPoint(port, -1.0),
    ]
    outline = half + [CellPoint(0.0, 0.0)] + list(reversed(mirror_points(half)))
    vectors = [SmartVector(outline, closed=True)]

    if complexity >= 0.4:
        vectors.append(SmartVector([CellPoint(0.0, 0.0), CellPoint(1.0, 0.0)]))
    return _smart_elements(context, vectors)


def generate_chevron_stack(
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
    Create nested chevrons pointing inward, each spanning side to side.

    Every chevron enters and leaves at the same radial, so ports match by
    construction. Spacing is computed in pixels because ring width varies far
    less than cell width across the supported settings.
    """
    context = SmartCellContext(inner_radius, outer_radius, wedge_angle, center, stroke_width, complexity, rng, min_white_space)
    ports = port_rng if port_rng is not None else rng

    gap = max(context.px_to_radial(max(min_white_space, 8.0)), 0.16)
    count = 1 + int(complexity * 2.5)
    count = max(1, min(count, int((0.82 - 0.18) / gap) or 1))

    base = 0.28 + ports.random() * 0.12
    drop = min(gap * 0.8, 0.22)

    vectors = []
    apexes = []
    for index in range(count):
        radial = base + index * gap
        if radial + 0.02 > 1.0:
            break
        apex = max(0.0, radial - drop)
        apexes.append(apex)
        vectors.append(SmartVector([
            CellPoint(radial, -1.0),
            CellPoint(apex, 0.0),
            CellPoint(radial, 1.0),
        ]))

    # Spine from boundary to boundary, passing through each chevron's apex.
    # It subdivides the ring AND makes sure no radial band is left uncrossed,
    # which would otherwise be a lane running around the design.
    spine = [CellPoint(0.0, 0.0)]
    spine += [CellPoint(apex, 0.0) for apex in apexes]
    spine.append(CellPoint(1.0, 0.0))
    vectors.append(SmartVector(spine))
    return _smart_elements(context, vectors)


GEOMETRIC_SMART_PATTERNS = [
    {
        "name": "smart_triangle_band",
        "min_cell_width_px": 0.0,
        "category": "geometric",
        "generator": generate_triangle_band,
        "allow_first_ring": True,
        "allow_last_ring": True,
        "min_ring_width": 16,
        "force_inner_boundary": True,
        "force_outer_boundary": False,
        "force_radial_boundaries": False,
    },
    {
        "name": "smart_star_point",
        "min_cell_width_px": 0.0,
        "category": "geometric",
        "generator": generate_star_point,
        "allow_first_ring": True,
        "allow_last_ring": True,
        "min_ring_width": 20,
        "force_inner_boundary": False,
        "force_outer_boundary": False,
        "force_radial_boundaries": False,
    },
    {
        "name": "smart_chevron_stack",
        "min_cell_width_px": 0.0,
        "category": "geometric",
        "generator": generate_chevron_stack,
        "allow_first_ring": True,
        "allow_last_ring": True,
        "min_ring_width": 20,
        "force_inner_boundary": False,
        "force_outer_boundary": False,
        "force_radial_boundaries": False,
    },
    {
        "name": "smart_diamond",
        "min_cell_width_px": 26.0,
        "category": "geometric",
        "generator": generate_diamond_cell,
        "allow_first_ring": True,
        "allow_last_ring": True,
        "min_ring_width": 18,
        "force_inner_boundary": False,
        "force_outer_boundary": False,
        "force_radial_boundaries": False,
    },
    {
        "name": "smart_prism_lattice",
        "min_cell_width_px": 26.0,
        "category": "geometric",
        "generator": generate_prism_lattice,
        "allow_first_ring": True,
        "allow_last_ring": True,
        "min_ring_width": 26,
        "force_inner_boundary": False,
        "force_outer_boundary": False,
        "force_radial_boundaries": False,
    },
]
