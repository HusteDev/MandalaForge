"""Geometric motifs."""

from __future__ import annotations

from typing import Dict, List

from motifs.contract import MotifError, MotifInstance, build_instance, require_full_budget
from motifs.geometry import CellPoint, MotifContext, SmartVector, cubic_points, mirror_points
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


LENS_STEPS = 8
# The lens's half-width as a share of the angular budget, drawn from the ring stream.
LENS_SHARE_RANGE = (0.2, 0.4)


def _lens_half_width(context: MotifContext, share: float, radial: float) -> float:
    """
    The lens's half-width in angular units at its widest radial: `share`, clamped so the lens is at least
    `clearance_px()` across and the face between it and the next cell's lens, over the seam, is too.
    A cell too narrow for both gets the even split (0.5), which keeps the narrower of the two widest.
    """
    unit_px = context.angular_to_px(1.0, radial)
    if unit_px <= 0:
        return 0.5
    least = context.clearance_px() / (2.0 * unit_px)
    if least > 1.0 - least:
        return 0.5
    return max(least, min(1.0 - least, share))


def _lens(inner: float, outer: float, half_width: float) -> List[CellPoint]:
    """
    A closed, mirror-symmetric lens on the axis with pointed tips at `(inner, 0)` and `(outer, 0)`.

    Each side is one cubic whose controls sit a third of the way in from each tip at the same angular,
    so the side runs straight out in radial and peaks at exactly `half_width` (0.75 of the controls'
    angular) at the middle radial.
    """
    third = (outer - inner) / 3.0
    reach = half_width / 0.75
    right = cubic_points(
        CellPoint(inner, 0.0), CellPoint(inner + third, reach), CellPoint(outer - third, reach),
        CellPoint(outer, 0.0), LENS_STEPS,
    )
    left = mirror_points(right)[1:-1][::-1]
    return right + left


def generate_band(context: MotifContext) -> MotifInstance:
    require_full_budget(context, "band")
    ring = context.ring_rng
    # Every seam-deciding value comes from the ring stream, so every cell of the ring draws the same band.
    r1 = ring.uniform(0.25, 0.45)
    r2 = ring.uniform(0.55, 0.75)
    share = ring.uniform(*LENS_SHARE_RANGE)

    low, high = context.radial_limits
    r1, r2 = max(low, r1), min(high, r2)
    if r2 <= r1:
        raise MotifError("band does not fit its radial limits")
    # Two seam arcs, each with a vertex on the axis where the lens tip meets it exactly.
    arcs = [SmartVector([CellPoint(r, -1.0), CellPoint(r, 0.0), CellPoint(r, 1.0)]) for r in (r1, r2)]
    # The lens ties the arcs together and cuts the annulus between them into faces, one per cell side.
    half_width = _lens_half_width(context, share, (r1 + r2) / 2.0)
    lens = SmartVector(_lens(r1, r2, half_width), closed=True)
    return build_instance(context, [*arcs, lens], seams=True)


GEOMETRIC_MOTIFS: List[Dict] = [
    {
        "name": "diamond",
        "category": "geometric",
        "generator": generate_diamond,
        "positions": ["centre"],
        "roles": ["slot"],
        "touch": False,
        "side_touch_heights": (),
        "seams": False,
        "embellishments": (),
        "spans_cell": False,
        "min_cell_width_px": 10.0,
        "min_ring_depth_px": 10.0,
        "max_overflow_inward": 0.0,
        "max_overflow_outward": 0.0,
        "slot_estimate": None,
    },
    {
        "name": "band",
        "category": "geometric",
        "generator": generate_band,
        "positions": ["centre", "divider"],
        "roles": ["base"],
        "touch": True,
        "side_touch_heights": (),
        "seams": True,
        "embellishments": (),
        "spans_cell": True,
        "min_cell_width_px": 0.0,
        "min_ring_depth_px": 0.0,
        "max_overflow_inward": 0.0,
        "max_overflow_outward": 0.0,
        "slot_estimate": None,
    },
]
