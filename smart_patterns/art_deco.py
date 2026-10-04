"""
Smart art deco patterns.
"""

import random
from typing import Any, Dict, List

from .core import CellPoint, PointTuple, SmartCellContext, SmartVector, _smart_elements, quad_points


def generate_fan_cell(
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
    Create a simple art-deco fan of radial rays.

    Each ray starts on the inner boundary and ends on the outer boundary. The
    inner endpoints are compressed toward the centerline so the fan reads as a
    spread while avoiding tiny cross-wave pockets.
    """
    context = SmartCellContext(inner_radius, outer_radius, wedge_angle, center, stroke_width, complexity, rng, min_white_space)
    ray_count = 3 + int(complexity * 2)
    vectors = []
    for index in range(ray_count):
        angular = -0.8 + (1.6 * index / max(1, ray_count - 1))
        inner_angular = angular * 0.45
        vectors.append(SmartVector([CellPoint(0.0, inner_angular), CellPoint(1.0, angular)]))
    return _smart_elements(context, vectors)


def generate_stepped_band_cell(
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
    Create an Art Deco stepped skyline band.

    The main line enters and exits the cell at the same radial port. Repeated
    wedges therefore form a continuous angular band while the interior steps
    give the ring a geometric Art Deco profile.
    """
    context = SmartCellContext(inner_radius, outer_radius, wedge_angle, center, stroke_width, complexity, rng, min_white_space)
    lower_band = SmartVector(
        [
            CellPoint(0.28, -1.0),
            CellPoint(0.28, -0.66),
            CellPoint(0.58, -0.66),
            CellPoint(0.58, -0.28),
            CellPoint(0.44, -0.28),
            CellPoint(0.44, 0.0),
            CellPoint(0.44, 0.28),
            CellPoint(0.58, 0.28),
            CellPoint(0.58, 0.66),
            CellPoint(0.28, 0.66),
            CellPoint(0.28, 1.0),
        ]
    )
    # Support column running the full height. It subdivides the ring, and it
    # keeps the bands above and below the skyline from being uncrossed lanes.
    vectors = [
        lower_band,
        SmartVector([CellPoint(0.0, 0.0), CellPoint(0.44, 0.0), CellPoint(1.0, 0.0)]),
    ]

    if complexity >= 0.55 and context.ring_width >= min_white_space * 1.8:
        vectors.append(
            SmartVector(
                [
                    CellPoint(0.82, -1.0),
                    CellPoint(0.82, -0.66),
                    CellPoint(0.66, -0.66),
                    CellPoint(0.66, -0.28),
                    CellPoint(0.74, -0.28),
                    CellPoint(0.74, 0.0),
                    CellPoint(0.74, 0.28),
                    CellPoint(0.66, 0.28),
                    CellPoint(0.66, 0.66),
                    CellPoint(0.82, 0.66),
                    CellPoint(0.82, 1.0),
                ]
            )
        )

    return _smart_elements(context, vectors)


def generate_sunburst(
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
    Create a burst of rays with alternating lengths.

    Short rays stop on an intermediate band rather than in open space, which is
    what makes alternating lengths legal: a ray that simply stopped short would
    be a line into nowhere. Long rays carry a vertex where they meet the band so
    the crossing lands on a vertex instead of mid-segment.
    """
    context = SmartCellContext(inner_radius, outer_radius, wedge_angle, center, stroke_width, complexity, rng, min_white_space)
    ports = port_rng if port_rng is not None else rng
    band = 0.5 + (ports.random() - 0.5) * 0.16

    # Rays hold a constant angular, so they are closest together at the inner
    # boundary. Size the count there, not at the band, or they crowd into
    # slivers on a tall ring.
    spacing = max(min_white_space, 9.0)
    count = int(context.cell_width_px(0.0) / spacing)
    count = max(1, min(count, 3 + int(complexity * 6)))

    vectors = [SmartVector([CellPoint(band, -1.0), CellPoint(band, 1.0)])]
    for index in range(count):
        angular = 0.0 if count == 1 else -0.82 + (1.64 * index / (count - 1))
        if index % 2 == 0:
            vectors.append(SmartVector([
                CellPoint(0.0, angular), CellPoint(band, angular), CellPoint(1.0, angular),
            ]))
        else:
            vectors.append(SmartVector([CellPoint(0.0, angular), CellPoint(band, angular)]))
    return _smart_elements(context, vectors)


def generate_deco_shell(
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
    Create a fanned shell rising from a hub on the inner boundary.

    The outline is closed and returns to the hub, so it never relies on side
    ports; the ring is held together by the inner boundary arc the descriptor
    forces. Ribs terminate on outline vertices, so no rib end floats.
    """
    context = SmartCellContext(inner_radius, outer_radius, wedge_angle, center, stroke_width, complexity, rng, min_white_space)
    hub = CellPoint(0.0, 0.0)
    crown = 0.72 + complexity * 0.16
    reach = 0.86

    spacing = max(min_white_space, 10.0)
    ribs = int(context.cell_width_px(crown) / spacing)
    ribs = max(1, min(ribs, 2 + int(complexity * 5)))

    arc = [CellPoint(crown, -reach + (2 * reach * i / 12)) for i in range(13)]
    vectors = [SmartVector([hub] + arc, closed=True)]

    for index in range(ribs):
        angular = 0.0 if ribs == 1 else -reach + (2 * reach * index / (ribs - 1))
        target = min(arc, key=lambda pt: abs(pt.angular - angular))
        if abs(target.angular) >= reach - 1e-9:
            continue          # the outline already draws that edge
        vectors.append(SmartVector([hub, target]))

    # Finial from the crown to the outer boundary. The shell alone stops short
    # of the ring edge, leaving a band that nothing crosses - that band is a
    # corridor running the whole way around the mandala.
    crown_apex = min(arc, key=lambda pt: abs(pt.angular))
    vectors.append(SmartVector([crown_apex, CellPoint(1.0, 0.0)]))
    return _smart_elements(context, vectors)


ART_DECO_SMART_PATTERNS = [
    {
        "name": "smart_sunburst",
        "min_cell_width_px": 20.0,
        "category": "art_deco",
        "generator": generate_sunburst,
        "allow_first_ring": True,
        "allow_last_ring": True,
        "min_ring_width": 18,
        "force_inner_boundary": False,
        "force_outer_boundary": False,
        "force_radial_boundaries": False,
    },
    {
        "name": "smart_deco_shell",
        "min_cell_width_px": 18.0,
        "category": "art_deco",
        "generator": generate_deco_shell,
        "allow_first_ring": True,
        "allow_last_ring": True,
        "min_ring_width": 20,
        "force_inner_boundary": True,
        "force_outer_boundary": False,
        "force_radial_boundaries": False,
    },
    {
        "name": "smart_fan",
        "min_cell_width_px": 0.0,
        "category": "art_deco",
        "generator": generate_fan_cell,
        "allow_first_ring": True,
        "allow_last_ring": True,
        "min_ring_width": 18,
        "force_inner_boundary": False,
        "force_outer_boundary": False,
        "force_radial_boundaries": False,
    },
    {
        "name": "smart_stepped_band",
        "min_cell_width_px": 0.0,
        "category": "art_deco",
        "generator": generate_stepped_band_cell,
        "allow_first_ring": True,
        "allow_last_ring": True,
        "min_ring_width": 24,
        "force_inner_boundary": False,
        "force_outer_boundary": False,
        "force_radial_boundaries": False,
    },
]
