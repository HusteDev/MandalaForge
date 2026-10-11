"""Geometric motifs."""

from __future__ import annotations

import math
from typing import Dict, List, Optional

from motifs.contract import Anatomy, MotifError, MotifInstance, build_instance, require_full_budget
from motifs.embellish import apply_embellishments, holds_pen as _holds_pen
from motifs.geometry import CellPoint, MotifContext, SmartVector, cubic_points, mirror_points, quad_points
from motifs.slot_fit import fit_inside_slot, fit_slot_box


DIAMOND_CONCAVE_CHANCE = 0.5
# A concave edge's midpoint (at the radial halfway between tip and side vertex) sits this share of the
# half-width inside the straight edge's.
DIAMOND_BOW_RANGE = (0.15, 0.35)
DIAMOND_EDGE_STEPS = 8
# A concave edge is a quadratic whose control sits this share of the tip-to-side-vertex radial from the tip.
# Leaning it toward the side vertex keeps the control's angular positive for every bow in the range, so the
# edge leaves the tip on its own side of the axis and the tip stays a point, never a cusp.
DIAMOND_CONTROL_LEAN = 0.8


def _concave_edge_control_share(bow: float) -> float:
    """
    The control's angular, as a share of the half-width, that puts the edge's halfway-radial point `bow`
    of the half-width inside the straight edge. The quadratic's radial is `hh (2 L t (1 - t) + t^2)` for
    lean L, which is half the height at the root `t` of `(1 - 2L) t^2 + 2 L t - 1/2`; the angular there,
    `2 t (1 - t) a + t^2`, must equal `1/2 - bow`.
    """
    a, b = 1.0 - 2.0 * DIAMOND_CONTROL_LEAN, 2.0 * DIAMOND_CONTROL_LEAN
    t = (-b + math.sqrt(b * b + 2.0 * a)) / (2.0 * a)
    return (0.5 - bow - t * t) / (2.0 * t * (1.0 - t))


def _diamond(mid: float, half_height: float, width: float, bow: Optional[float]) -> List[CellPoint]:
    """A closed diamond on the axis, straight-sided, or with every edge bowed inward by `bow` of `width`."""
    if bow is None:
        return [
            CellPoint(mid - half_height, 0.0),
            CellPoint(mid, width),
            CellPoint(mid + half_height, 0.0),
            CellPoint(mid, -width),
        ]
    tip = CellPoint(mid - half_height, 0.0)
    control = CellPoint(mid - half_height * (1.0 - DIAMOND_CONTROL_LEAN), width * _concave_edge_control_share(bow))
    lower = quad_points(tip, control, CellPoint(mid, width), DIAMOND_EDGE_STEPS)
    # The upper edge is the lower one reflected across the side vertex's radial.
    upper = [CellPoint(2.0 * mid - point.radial, point.angular) for point in reversed(lower)]
    right = lower + upper[1:]
    left = mirror_points(right)[1:-1][::-1]
    return right + left


def generate_diamond(context: MotifContext) -> MotifInstance:
    rng = context.rng
    # Every parameter is drawn before the slot is measured, whichever variant is kept.
    aspect = rng.uniform(0.6, 1.0)
    concave = rng.random() < DIAMOND_CONCAVE_CHANCE
    bow = rng.uniform(*DIAMOND_BOW_RANGE)
    box = fit_slot_box(context, "diamond")
    mid = box.radial_mid
    full_half_height = (box.radial_max - box.radial_min) / 2.0 * aspect

    def build_for(edge_bow: Optional[float]):
        return lambda scale: _diamond(mid, full_half_height * scale, box.half_width * scale, edge_bow)

    points = fit_inside_slot(context, "diamond", build_for(bow if concave else None))
    if concave and not _holds_pen(context, points):
        # Bowed edges thin the diamond; the straight one in the same slot is wider.
        points = fit_inside_slot(context, "diamond", build_for(None))
    if not _holds_pen(context, points):
        raise MotifError("diamond does not fit slot: its interior is too small to colour")
    return build_instance(context, [SmartVector(points, closed=True)])


# The band's inner and outer arc radials, drawn from the ring stream. A plain band's arcs sit near the ring's
# edges, so the band fills its ring and its stems are short connectors rather than long spokes; a beaded band
# keeps the ranges its beads were fitted to.
BAND_INNER_RANGE = (0.08, 0.15)
BAND_OUTER_RANGE = (0.85, 0.92)
BEADED_BAND_INNER_RANGE = (0.12, 0.25)
BEADED_BAND_OUTER_RANGE = (0.75, 0.88)
LENS_STEPS = 8
# The lens's half-width as a share of the angular budget, drawn from the ring stream: a fat lens on a plain band,
# a narrower one on a beaded band so a bead has room in the face beside it.
LENS_SHARE_RANGE = (0.3, 0.45)
BEADED_LENS_SHARE_RANGE = (0.2, 0.4)


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
    # A beaded band draws the same values, in the same order, from its own ranges, so a row of beads has room.
    beaded = "beads" in context.embellishments
    r1 = ring.uniform(*(BEADED_BAND_INNER_RANGE if beaded else BAND_INNER_RANGE))
    r2 = ring.uniform(*(BEADED_BAND_OUTER_RANGE if beaded else BAND_OUTER_RANGE))
    share = ring.uniform(*(BEADED_LENS_SHARE_RANGE if beaded else LENS_SHARE_RANGE))

    low, high = context.radial_limits
    r1, r2 = max(low, r1), min(high, r2)
    if r2 <= r1:
        raise MotifError("band does not fit its radial limits")
    # Two seam arcs, each with a vertex on the axis where the lens tip meets it exactly.
    arcs = [SmartVector([CellPoint(r, -1.0), CellPoint(r, 0.0), CellPoint(r, 1.0)]) for r in (r1, r2)]
    # The lens ties the arcs together and cuts the annulus between them into faces, one per cell side.
    half_width = _lens_half_width(context, share, (r1 + r2) / 2.0)
    lens = SmartVector(_lens(r1, r2, half_width), closed=True)
    # Its anatomy is the lens, from its tip on the inner arc to its tip on the outer one. The band offers no
    # slot; its beads continue the ring stream, so they are the same in every cell too.
    anatomy = Anatomy(base=CellPoint(r1, 0.0), tip=CellPoint(r2, 0.0), outline=2)
    result = apply_embellishments(context, [*arcs, lens], anatomy, None)
    return build_instance(context, result.vectors, seams=True, anatomy=anatomy,
                          dropped_embellishments=result.dropped)


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
        "embellishments": ("beads",),
        "spans_cell": True,
        "min_cell_width_px": 0.0,
        "min_ring_depth_px": 0.0,
        "max_overflow_inward": 0.0,
        "max_overflow_outward": 0.0,
        "slot_estimate": None,
    },
]
