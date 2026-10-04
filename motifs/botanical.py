"""Botanical motifs."""

from __future__ import annotations

import math
from typing import Dict, List

from motifs.contract import MotifInstance, build_instance
from motifs.geometry import CellPoint, MotifContext, SmartVector, mirror_points, quad_points
from motifs.slot_fit import fit_slot_box

QUAD_STEPS = 8


def generate_petal(context: MotifContext) -> MotifInstance:
    rng = context.rng
    # Every parameter is drawn before any limit is applied, so tightening the
    # limits changes what is kept but never what the rng produced.
    length = rng.uniform(0.75, 1.25)
    dip = rng.uniform(0.0, 0.25)
    half_width = context.angular_limits * rng.uniform(0.55, 0.95)
    waist = rng.uniform(0.35, 0.6)
    wave = rng.uniform(0.0, context.complexity * 0.06)

    low, high = context.radial_limits
    angular_bound = context.angular_limits
    if context.slot:
        box = fit_slot_box(context, "petal")
        base_radial = max(low, box.radial_min)
        tip_radial = min(high, box.radial_max)
        half_width = min(half_width, box.half_width)
        angular_bound = min(angular_bound, box.half_width)
    else:
        base_radial = max(low, -dip)
        tip_radial = min(high, length)

    base = CellPoint(base_radial, 0.0)
    tip = CellPoint(tip_radial, 0.0)
    widest = CellPoint(base.radial + (tip.radial - base.radial) * waist, half_width)
    lower = quad_points(
        base,
        CellPoint(base.radial + (widest.radial - base.radial) * 0.5, half_width * 1.15),
        widest,
        QUAD_STEPS,
    )
    upper = quad_points(
        widest,
        CellPoint(widest.radial + (tip.radial - widest.radial) * 0.5, half_width * 0.9),
        tip,
        QUAD_STEPS,
    )

    right: List[CellPoint] = []
    for run, samples in enumerate((lower, upper)):
        for index, point in enumerate(samples):
            if run == 1 and index == 0:
                continue  # the widest vertex already closes the lower run
            angular = point.angular
            if 0 < index < QUAD_STEPS:
                if wave > 0:
                    t = (run * QUAD_STEPS + index) / (2 * QUAD_STEPS)
                    angular += wave * math.sin(3 * math.pi * t)
                angular = max(-angular_bound, min(angular_bound, angular))
            right.append(CellPoint(point.radial, angular))

    # Mirror tip to base along the left side, dropping the duplicated tip and base.
    left = mirror_points(right)[1:-1][::-1]
    outline = right + left
    return build_instance(context, [SmartVector(outline, closed=True)], slot_outline=outline)


BOTANICAL_MOTIFS: List[Dict] = [
    {
        "name": "petal",
        "category": "botanical",
        "generator": generate_petal,
        "positions": ["centre", "divider"],
        "roles": ["base", "slot"],
        "touch": True,
        "spans_cell": False,
        "min_cell_width_px": 14.0,
        "min_ring_depth_px": 18.0,
        "max_overflow_inward": 0.25,
        "max_overflow_outward": 0.25,
        "slot_estimate": (0.5, 0.5),
    },
]
