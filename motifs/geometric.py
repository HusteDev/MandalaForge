"""Geometric motifs."""

from __future__ import annotations

import math
from typing import Dict, List, Optional

from motifs.contract import Anatomy, MotifError, MotifInstance, build_instance, require_full_budget
from motifs.embellish import apply_embellishments, holds_pen as _holds_pen
from motifs.geometry import (
    CellPoint, MotifContext, SmartVector, cubic_points, mirror_points, quad_points,
)
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


# The spike: a star point on a rounded cup. Its tip length is a share of the ring depth (past the outer
# boundary, up to the outward overflow), and without side touch its base corners sit at a drawn radial and a
# drawn share of the angular budget.
SPIKE_LENGTH_RANGE = (0.95, 1.15)
SPIKE_CORNER_RANGE = (0.08, 0.2)
SPIKE_WIDTH_RANGE = (0.75, 1.0)
# Each concave side is a cubic from a base corner to the tip. Its first control sits at the corner's angular,
# this share of the corner-to-tip radial above it, so the side leaves the corner along the divider (smooth
# touch, spec 3.3) and turns inward gradually, with no visible corner at the touch vertex.
SPIKE_LEAVE_RANGE = (0.15, 0.18)
# The second control: its radial as a share of the corner-to-tip radial, and its angular as a share of the
# corner's half-width. A lower angular share draws a deeper concave side and a finer tip. The side at
# parameter t lies inside the straight corner-to-tip chord exactly when `(1 - t) * leave / t + waist + pinch < 1`,
# so from t = 0.18 / 0.63 (about 0.29) on for every draw; there the side has risen at most 0.18 of the run, so
# everything past the first fifth of the run is concave.
SPIKE_WAIST_RANGE = (0.35, 0.45)
SPIKE_PINCH_RANGE = (0.0, 0.1)
# The cup below the corners leaves the base vertex across the axis, its control this share of the half-width
# out, and arrives at the corner along the divider, its control this share of the cup's height below it.
SPIKE_CUP_SPREAD = 0.3
SPIKE_CUP_RISE = 0.8
# Samples per cubic, spaced quadratically closer toward the corner, so the traced pieces either side of the
# touch vertex are short and follow the curves' radial tangents there.
SPIKE_STEPS = 16


def _cubic_at(start: CellPoint, control1: CellPoint, control2: CellPoint, end: CellPoint,
              ts: List[float]) -> List[CellPoint]:
    """A cubic in cell space sampled at the parameters `ts`, which run from 0 to 1; exact ends, nothing clamped."""
    points = []
    for t in ts:
        u = 1.0 - t
        w0, w1, w2, w3 = u * u * u, 3 * u * u * t, 3 * u * t * t, t * t * t
        points.append(CellPoint(
            radial=w0 * start.radial + w1 * control1.radial + w2 * control2.radial + w3 * end.radial,
            angular=w0 * start.angular + w1 * control1.angular + w2 * control2.angular + w3 * end.angular,
        ))
    points[0], points[-1] = start, end
    return points


def _spike(base: float, corner: float, width: float, tip: float, leave: float, waist: float,
           pinch: float) -> List[CellPoint]:
    """
    A closed, mirror-symmetric spike: the base vertex `(base, 0)`, a cup out to the corner `(corner, width)`,
    a concave side to the sharp tip `(tip, 0)`, and the left side back. Both controls next to each corner
    sit at the corner's angular, so the outline runs along the divider there.
    """
    rise, run = corner - base, tip - corner
    away = [(k / SPIKE_STEPS) ** 2 for k in range(SPIKE_STEPS + 1)]
    toward = [1.0 - t for t in reversed(away)]
    cup = _cubic_at(
        CellPoint(base, 0.0), CellPoint(base, width * SPIKE_CUP_SPREAD),
        CellPoint(corner - rise * SPIKE_CUP_RISE, width), CellPoint(corner, width), toward,
    )
    side = _cubic_at(
        CellPoint(corner, width), CellPoint(corner + run * leave, width),
        CellPoint(corner + run * waist, width * pinch), CellPoint(tip, 0.0), away,
    )
    right = cup + side[1:]
    return right + mirror_points(right)[1:-1][::-1]


def generate_spike(context: MotifContext) -> MotifInstance:
    rng = context.rng
    # Every parameter is drawn before any limit is applied, whether side touch uses the corner draws or not.
    length = rng.uniform(*SPIKE_LENGTH_RANGE)
    corner = rng.uniform(*SPIKE_CORNER_RANGE)
    width = context.angular_limits * rng.uniform(*SPIKE_WIDTH_RANGE)
    leave = rng.uniform(*SPIKE_LEAVE_RANGE)
    waist = rng.uniform(*SPIKE_WAIST_RANGE)
    pinch = rng.uniform(*SPIKE_PINCH_RANGE)

    low, high = context.radial_limits
    base = max(low, 0.0)
    if context.side_touch_radial is not None and not context.slot:
        # The base corners are the side-touch vertices: the spike is widest there, at the full budget.
        corner, width = context.side_touch_radial, context.angular_limits
    tip = min(high, length)
    if not base < corner < tip:
        raise MotifError("spike does not fit its radial limits")
    points = _spike(base, corner, width, tip, leave, waist, pinch)
    anatomy = Anatomy(base=points[0], tip=points[2 * SPIKE_STEPS], outline=0)
    result = apply_embellishments(context, [SmartVector(points, closed=True)], anatomy, points)
    return build_instance(
        context, result.vectors, slot_outline=result.slot_outline, anatomy=anatomy,
        dropped_embellishments=result.dropped, slot_outline_weight=result.slot_outline_weight,
    )


# The bead without side touch (an overflow or stem ring): its centre radial and its radius as a share of the
# largest that fits the budget and half the ring depth, drawn from the node stream.
BEAD_CENTRE_RANGE = (0.35, 0.65)
BEAD_SIZE_RANGE = (0.6, 0.95)
# Samples per half outline: the top, the angular extreme and the bottom are always vertices.
BEAD_HALF_STEPS = 12


def _bead_outline(context: MotifContext, centre: float, half_width: float, along_px: float) -> List[CellPoint]:
    """
    A closed, mirror-symmetric bead centred on `(centre, 0)`, `half_width` across in angular units and
    `along_px` from the centre to the top and the bottom. When `along_px` is `angular_to_px(half_width,
    centre)` it is the circle `page_circle_points` draws, round on the page; a smaller `along_px` squashes it
    into an oval with the same ends. The ends `(centre, ±half_width)` are exact vertices, and the outline runs radially through them.
    """
    right = []
    for index in range(BEAD_HALF_STEPS + 1):
        theta = math.pi * index / BEAD_HALF_STEPS
        right.append(CellPoint(centre + context.px_to_radial(along_px * math.cos(theta)),
                               half_width * math.sin(theta)))
    along = context.px_to_radial(along_px)
    quarter = BEAD_HALF_STEPS // 2
    right[0], right[quarter], right[-1] = (
        CellPoint(centre + along, 0.0), CellPoint(centre, half_width), CellPoint(centre - along, 0.0))
    return right + mirror_points(right)[1:-1][::-1]


def generate_bead(context: MotifContext) -> MotifInstance:
    rng = context.rng
    # Every parameter is drawn before the slot or the limits are looked at, whichever branch draws.
    centre = rng.uniform(*BEAD_CENTRE_RANGE)
    size = rng.uniform(*BEAD_SIZE_RANGE)
    low, high = context.radial_limits

    if context.slot:
        # A slot child is the largest true circle the slot polygon contains.
        box = fit_slot_box(context, "bead")
        mid = box.radial_mid
        radius_px = min(context.radial_to_px(box.radial_max - box.radial_min) / 2.0,
                        context.angular_to_px(box.half_width, mid))

        def build(scale: float) -> List[CellPoint]:
            return _bead_outline(context, mid, context.px_to_angular(radius_px * scale, mid), radius_px * scale)

        points = fit_inside_slot(context, "bead", build)
    elif context.side_touch_radial is not None:
        # The horizontal diameter's ends are the side-touch vertices; a circle when it fits the radial limits,
        # else an oval with the same ends, squashed radially to fit.
        centre = context.side_touch_radial
        across_px = context.angular_to_px(context.angular_limits, centre)
        along_px = min(across_px, context.radial_to_px(centre - low), context.radial_to_px(high - centre))
        if not low < centre < high or along_px <= 0.0:
            raise MotifError("bead does not fit its radial limits")
        points = _bead_outline(context, centre, context.angular_limits, along_px)
    else:
        if not low < centre < high:
            raise MotifError("bead does not fit its radial limits")
        largest_px = min(context.angular_to_px(context.angular_limits, centre), context.ring_depth / 2.0)
        radius_px = min(largest_px * size, context.radial_to_px(centre - low), context.radial_to_px(high - centre))
        points = _bead_outline(context, centre, context.px_to_angular(radius_px, centre), radius_px)
    if not _holds_pen(context, points):
        raise MotifError("bead is too small to colour")
    anatomy = Anatomy(base=points[BEAD_HALF_STEPS], tip=points[0], outline=0)
    result = apply_embellishments(context, [SmartVector(points, closed=True)], anatomy, None)
    return build_instance(context, result.vectors, anatomy=anatomy, dropped_embellishments=result.dropped)


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
    {
        "name": "bead",
        "category": "geometric",
        "generator": generate_bead,
        "positions": ["divider"],
        "roles": ["base", "slot"],
        "touch": True,
        "side_touch_heights": ("base", "mid"),
        "seams": False,
        "embellishments": ("echo",),
        "spans_cell": False,
        "min_cell_width_px": 10.0,
        "min_ring_depth_px": 10.0,
        "max_overflow_inward": 0.0,
        "max_overflow_outward": 0.2,
        "slot_estimate": None,
    },
    {
        "name": "spike",
        "category": "geometric",
        "generator": generate_spike,
        "positions": ["centre", "divider"],
        "roles": ["base", "back"],
        "touch": True,
        "side_touch_heights": ("base",),
        "seams": False,
        "embellishments": ("echo", "fan"),
        "spans_cell": False,
        "min_cell_width_px": 14.0,
        "min_ring_depth_px": 18.0,
        "max_overflow_inward": 0.0,
        "max_overflow_outward": 0.2,
        # Measured: the spike's slot is a narrow triangle, its bounding box a median 0.37 of the mid-ring cell
        # width and 0.34 of the ring depth; at 0.3 most slot children the gate admits really fit.
        "slot_estimate": (0.3, 0.3),
    },
]
