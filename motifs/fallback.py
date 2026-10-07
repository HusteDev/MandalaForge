"""Safe fallback motif: one plain band per category, valid in any cell."""

from __future__ import annotations

from typing import Dict

from motifs.contract import MotifInstance, build_instance
from motifs.geometry import CellPoint, MotifContext, SmartVector, side_touch_radial_within


def generate_safe_band(context: MotifContext) -> MotifInstance:
    limit = context.angular_limits
    # Side touch adds the shared vertex on each side edge when it falls inside that edge.
    touch = side_touch_radial_within(context, 0.4, 0.6)
    points = [
        CellPoint(0.4, -limit),
        CellPoint(0.4, limit),
        *([CellPoint(touch, limit)] if touch is not None else []),
        CellPoint(0.6, limit),
        CellPoint(0.6, -limit),
        *([CellPoint(touch, -limit)] if touch is not None else []),
    ]
    return build_instance(context, [SmartVector(points, closed=True)])


def safe_motif(category: str) -> Dict:
    return {
        "name": f"{category}_safe_band",
        "category": category,
        "generator": generate_safe_band,
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
        "is_safe_fallback": True,
    }
