"""Geometric motifs."""

from __future__ import annotations

from typing import Dict, List

from motifs.contract import MotifInstance, build_instance
from motifs.geometry import CellPoint, MotifContext, SmartVector, side_edge_containing_touch, side_touch_radial_within
from motifs.slot_fit import fit_inside_slot, fit_slot_box


def generate_diamond(context: MotifContext) -> MotifInstance:
    aspect = context.rng.uniform(0.6, 1.0)
    box = fit_slot_box(context, "diamond")
    mid = box.radial_mid
    full_half_height = (box.radial_max - box.radial_min) / 2.0 * aspect

    def build(scale: float) -> List[CellPoint]:
        half_height = full_half_height * scale
        width = box.half_width * scale
        return [
            CellPoint(mid - half_height, 0.0),
            CellPoint(mid, width),
            CellPoint(mid + half_height, 0.0),
            CellPoint(mid, -width),
        ]

    points = fit_inside_slot(context, "diamond", build)
    return build_instance(context, [SmartVector(points, closed=True)])


def generate_ring_band(context: MotifContext) -> MotifInstance:
    # Any pair of draws overlaps radially within [0.45, 0.55], so neighbouring cells meet along a shared radial edge.
    r1 = context.rng.uniform(0.30, 0.45)
    r2 = context.rng.uniform(0.55, 0.70)
    limit = context.angular_limits
    # Side touch (spec 13.2): the side edges widen to contain the ring's side-touch radial, and the
    # shared vertex is added on each.
    r1, r2 = side_edge_containing_touch(context, r1, r2)
    touch = side_touch_radial_within(context, r1, r2)
    outline = [
        CellPoint(r1, -limit),
        CellPoint(r1, 0.0),
        CellPoint(r1, limit),
        *([CellPoint(touch, limit)] if touch is not None else []),
        CellPoint(r2, limit),
        CellPoint(r2, 0.0),
        CellPoint(r2, -limit),
        *([CellPoint(touch, -limit)] if touch is not None else []),
    ]
    vectors = [SmartVector(outline, closed=True)]
    if context.complexity >= 0.5:
        vectors.append(SmartVector([CellPoint(r1, 0.0), CellPoint(r2, 0.0)]))
    return build_instance(context, vectors)


GEOMETRIC_MOTIFS: List[Dict] = [
    {
        "name": "diamond",
        "category": "geometric",
        "generator": generate_diamond,
        "positions": ["centre"],
        "roles": ["slot"],
        "touch": False,
        "side_touch": False,
        "spans_cell": False,
        "min_cell_width_px": 10.0,
        "min_ring_depth_px": 10.0,
        "max_overflow_inward": 0.0,
        "max_overflow_outward": 0.0,
        "slot_estimate": None,
    },
    {
        "name": "ring_band",
        "category": "geometric",
        "generator": generate_ring_band,
        "positions": ["centre", "divider"],
        "roles": ["base"],
        "touch": True,
        "side_touch": True,
        "spans_cell": True,
        "min_cell_width_px": 0.0,
        "min_ring_depth_px": 0.0,
        "max_overflow_inward": 0.0,
        "max_overflow_outward": 0.0,
        "slot_estimate": None,
    },
]
