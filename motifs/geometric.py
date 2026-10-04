"""Geometric motifs."""

from __future__ import annotations

from typing import Dict, List

from motifs.contract import MotifInstance, build_instance
from motifs.geometry import CellPoint, MotifContext, SmartVector
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


GEOMETRIC_MOTIFS: List[Dict] = [
    {
        "name": "diamond",
        "category": "geometric",
        "generator": generate_diamond,
        "positions": ["centre"],
        "roles": ["slot"],
        "touch": False,
        "spans_cell": False,
        "min_cell_width_px": 10.0,
        "min_ring_depth_px": 10.0,
        "max_overflow_inward": 0.0,
        "max_overflow_outward": 0.0,
        "slot_estimate": None,
    },
]
