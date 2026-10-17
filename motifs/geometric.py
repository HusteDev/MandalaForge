"""Geometric motifs."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Dict, List, Optional, Tuple

from shapely.geometry import LineString, Point, Polygon
from shapely.geometry.base import BaseGeometry

from motifs.contract import Anatomy, MotifError, MotifInstance, build_instance, require_full_budget
from motifs.embellish import apply_embellishments, holds_pen as _holds_pen, polygon_holds_pen
from motifs.geometry import (
    CellPoint, MotifContext, PointTuple, SmartVector, cubic_points, insert_vertex_on_outline, mirror_points,
    quad_points, size_draw,
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
    aspect = size_draw(context, rng, 0.6, 1.0)
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
    length = size_draw(context, rng, *SPIKE_LENGTH_RANGE)
    corner = rng.uniform(*SPIKE_CORNER_RANGE)
    width = context.angular_limits * size_draw(context, rng, *SPIKE_WIDTH_RANGE)
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
    size = size_draw(context, rng, *BEAD_SIZE_RANGE)
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


# The rosette: a repair-only centre motif that fills the open middle inside ring 0 (max-region spec 5, step 3).
# Its cell is one lobe's wedge, from the page centre (inner radius 0) out to the point where the lobe touches
# ring 0's ink (radial 1), so the open centre splits into one face per gap between lobes and none encircles it.
# A lobe is a body on the dot arc and a stem: the body ends a stem's length inside the circle ring 0's ink leaves
# free, and the stem runs on along the axis to the touch point, out and back on the same line, so the body keeps
# its clearance from the ink however that ink meets the touch point. `fit_rosette` picks the lobe count and the
# axis on the page. Every value comes from the ring stream, so every wedge draws the same lobe: the dot's share
# of the body's radial, the lobe's half-width at its belly (its ends on the dot arc are `ROSETTE_NECK` of it), and
# the share of the dot-to-body-tip radial at which the lobe is widest.
ROSETTE_DOT_RANGE = (0.18, 0.28)
ROSETTE_LOBE_WIDTH_RANGE = (0.45, 0.75)
ROSETTE_BELLY_RANGE = (0.45, 0.7)
# The free radius must be at least this many detail-to-detail clearances, or nothing colourable fits in it.
ROSETTE_MIN_FREE_CLEARANCES = 3.0
# The lobe's ends on the dot arc sit at this share of its belly's half-width: a petal with a neck.
ROSETTE_NECK = 0.6
# When neighbouring lobes would come closer than a clearance on the dot arc, an adapting rosette grows the dot,
# up to this share of the body's radial, then narrows the neck, down to this angular; past both it is refused.
ROSETTE_MAX_DOT = 0.4
ROSETTE_MIN_NECK = 0.2
# Each narrowing step of a lobe whose flank comes closer than a clearance to its neighbour keeps this share of
# its neck and belly half-widths.
ROSETTE_NARROWING = 0.9
# Fewer lobes than this read as a propeller, not a rosette.
ROSETTE_MIN_LOBES = 3
# The stem is the detail-to-outline clearance plus this share of it, so the body clears ring 0's ink with room.
ROSETTE_STEM_MARGIN = 0.15
ROSETTE_STEPS = 12
# The body's sides: from the neck, the first control this share of the neck-to-belly radial on at the belly's
# half-width, the second as far short of the belly; from the belly, the first control this share of the
# belly-to-tip radial on at the full half-width, the second this share short of the tip at this share of it.
ROSETTE_FLANK = 0.35
ROSETTE_SHOULDER = 0.5
ROSETTE_TIP_LEAN = 0.3
ROSETTE_TIP_WIDTH = 0.2
# A ray this long from the centre crosses the whole page.
RAY_REACH_PX = 10000.0
# A lobe's touch point lies on the ink when it is this close to it (float noise on a turned copy).
ROSETTE_TOUCH_TOLERANCE_PX = 1e-6


def _rosette_body(dot: float, neck: float, half_width: float, belly: float, tip: float) -> List[CellPoint]:
    """
    The right half of a lobe body, from its neck `(dot, neck)` on the dot arc out to the belly `(belly,
    half_width)`, where it runs along the radial, and on to its sharp tip `(tip, 0)`.
    """
    rise = belly - dot
    lower = cubic_points(
        CellPoint(dot, neck), CellPoint(dot + rise * ROSETTE_FLANK, half_width),
        CellPoint(belly - rise * ROSETTE_FLANK, half_width), CellPoint(belly, half_width), ROSETTE_STEPS,
    )
    run = tip - belly
    upper = cubic_points(
        CellPoint(belly, half_width), CellPoint(belly + run * ROSETTE_SHOULDER, half_width),
        CellPoint(tip - run * ROSETTE_TIP_LEAN, half_width * ROSETTE_TIP_WIDTH), CellPoint(tip, 0.0),
        ROSETTE_STEPS,
    )
    return lower + upper[1:]


def rosette_stem_px(context: MotifContext) -> float:
    """The stem's length on the page: the clearance a detail line keeps from ring 0's outline, with a margin."""
    return context.clearance_px("detail", "outline") * (1.0 + ROSETTE_STEM_MARGIN)


def _draw_rosette(context: MotifContext, body_px: float, adapt: bool = True) -> MotifInstance:
    """
    One lobe and its stretch of the dot arc in a wedge that holds exactly one lobe, the body ending `body_px`
    from the centre and the stem running on to the touch point `(1, 0)`. Neighbouring lobes keep a clearance
    apart on the dot arc and at their bellies; without `adapt` the drawn dot and neck must already allow it.
    Raises `MotifError` when the free radius is under `ROSETTE_MIN_FREE_CLEARANCES` clearances, when the
    lobes are too crowded, when the dot cannot be coloured, or when the body is nowhere a clearance wide.
    """
    require_full_budget(context, "rosette")
    ring = context.ring_rng
    # Every parameter is drawn before any limit is applied, in a fixed order, so all wedges agree.
    dot_share = ring.uniform(*ROSETTE_DOT_RANGE)
    half_width = ring.uniform(*ROSETTE_LOBE_WIDTH_RANGE)
    belly_share = ring.uniform(*ROSETTE_BELLY_RANGE)

    clearance = context.clearance_px("detail", "detail")
    if context.radial_to_px(1.0) < ROSETTE_MIN_FREE_CLEARANCES * clearance:
        raise MotifError("rosette does not fit: the free radius is too small")
    low, high = context.radial_limits
    tip = min(1.0, high)
    body_tip = min(tip, context.px_to_radial(body_px - context.inner_radius))
    wedge = math.radians(context.half_angle)
    neck = half_width * ROSETTE_NECK
    dot = dot_share * body_tip

    def gap_px(radial: float, angular: float) -> float:
        """The page gap between neighbouring lobes whose sides sit at `angular` on `radial`."""
        return 2.0 * (1.0 - angular) * wedge * context.radius_at(radial)

    if gap_px(dot, neck) < clearance:
        if not adapt:
            raise MotifError("rosette lobes are too crowded on the dot arc")
        # The dot grows to the radial whose arc leaves a clearance beside the drawn neck, as far as it may.
        needed = context.px_to_radial(clearance / (2.0 * (1.0 - neck) * wedge) - context.inner_radius)
        dot = max(dot, min(needed, ROSETTE_MAX_DOT * body_tip))
        neck = min(neck, 1.0 - clearance / (2.0 * wedge * context.radius_at(dot)))
        if neck < ROSETTE_MIN_NECK:
            raise MotifError("rosette lobes are too crowded on the dot arc")
    if not low <= dot < body_tip:
        raise MotifError("rosette does not fit its radial limits")
    # The dot is one face, the disc inside the dot arc: a clearance across, and a face the validator accepts.
    dot_px = context.radius_at(dot)
    if 2.0 * dot_px < clearance or not polygon_holds_pen(Point(0.0, 0.0).buffer(dot_px)):
        raise MotifError("rosette dot is too small to colour")
    belly = dot + belly_share * (body_tip - dot)
    # The bellies keep a clearance apart too; the belly narrows to its neck at most.
    half_width = max(neck, min(half_width, 1.0 - clearance / (2.0 * wedge * context.radius_at(belly))))
    if gap_px(belly, half_width) < clearance:
        raise MotifError("rosette lobes are too crowded at their bellies")

    # The arc-length gaps above are measured on two radials only; a flank between them can still lean closer to
    # the neighbouring lobe. The true page distance between this lobe's side and its neighbour's decides: an
    # adapting rosette narrows its neck and belly together, keeping the lobe's shape, until it is a clearance.
    right = _rosette_body(dot, neck, half_width, belly, body_tip)
    while _neighbour_gap_px(context, right) < clearance:
        neck, half_width = neck * ROSETTE_NARROWING, half_width * ROSETTE_NARROWING
        if not adapt or neck < ROSETTE_MIN_NECK:
            raise MotifError("rosette lobes are too crowded along their flanks")
        right = _rosette_body(dot, neck, half_width, belly, body_tip)
    body = mirror_points(right)[:-1] + right[::-1]
    # The body's interior, closed by the dot arc between its ends, must hold the pen and be a clearance wide.
    interior = Polygon(context.polyline(SmartVector(body, closed=True)))
    if not _holds_pen(context, body) or interior.buffer(-clearance / 2.0).is_empty:
        raise MotifError("rosette lobe is too small to colour")
    # The stem runs out from the body tip to the touch point and back along the same line.
    stem = [CellPoint(tip, 0.0), CellPoint(body_tip, 0.0)] if body_tip < tip else []
    lobe = mirror_points(right) + stem + right[::-1][1:]
    # The dot arc is a seam arc, like the band's; the lobe's ends are exact vertices on it.
    arc = [CellPoint(dot, -1.0), CellPoint(dot, 1.0)]
    for end in (lobe[0], lobe[-1]):
        arc = insert_vertex_on_outline(arc, False, end)
    vectors = [SmartVector(arc, weight="detail"), SmartVector(lobe, weight="detail")]
    return build_instance(context, vectors, seams=True)


def _neighbour_gap_px(context: MotifContext, right: List[CellPoint]) -> float:
    """
    The least page distance between a lobe side `right` (the right half of a body, at rotation 0) and the
    facing side of the next lobe, its mirror turned by one lobe wedge.
    """
    own = LineString(context.polyline(SmartVector(right)))
    neighbour = LineString(context.polyline(SmartVector(mirror_points(right)), context.wedge_angle))
    return own.distance(neighbour)


def generate_rosette(context: MotifContext) -> MotifInstance:
    """One lobe of the rosette in a wedge that holds one lobe, touching at `(1, 0)`; see `_draw_rosette`."""
    return _draw_rosette(context, context.radius_at(1.0) - rosette_stem_px(context))


@dataclass
class RosetteFit:
    """
    A rosette fitted inside ring 0: one lobe drawn in `context` (inner radius 0, outer radius the touch
    distance, a wedge of `cells_per_lobe` of ring 0's cells), placed turned by each of `rotations` degrees,
    on ring 0's cell axes or its dividers (`axis`). `instance` is in `context`'s cell space; each lobe
    touches the ink at `(1, 0)`.
    """
    cells_per_lobe: int
    axis: str
    rotations: List[float]
    context: MotifContext
    instance: MotifInstance


def rosette_lobe_counts(divisions: int) -> List[int]:
    """
    The lobe counts a ring of `divisions` cells holds symmetrically, most first: its divisors from
    `ROSETTE_MIN_LOBES` up, one lobe every `divisions // count` cells.
    """
    return [count for count in range(divisions, ROSETTE_MIN_LOBES - 1, -1) if divisions % count == 0]


def _ray_px(center: PointTuple, ink: BaseGeometry, degrees: float) -> float:
    """How far from `center` a ray at `degrees` first meets `ink`; infinite when it never does."""
    angle = math.radians(degrees)
    far = (center[0] + RAY_REACH_PX * math.cos(angle), center[1] + RAY_REACH_PX * math.sin(angle))
    hit = LineString([center, far]).intersection(ink)
    return math.inf if hit.is_empty else Point(center).distance(hit)


def fit_rosette(context: MotifContext, ink: BaseGeometry) -> RosetteFit:
    """
    The rosette for ring 0, given the context of its cell 0 (the ring's cell wedge, rotation 0, its ring
    stream; its radii are ignored) and `ink`, every placed line on the page.

    A lobe's axis is a cell axis or a divider. Its tip touches the ink where a ray along that axis first meets
    it, and its body ends a stem's length inside the largest circle about the centre that the ink leaves free.
    The lobe counts of `rosette_lobe_counts` are tried most first, with each count's axes nearest ink first,
    once keeping the drawn dot and neck and then letting them adapt; the first fit whose every lobe draws,
    touches ink, and keeps `clearance_px("detail", "outline")` from the ink away from its own stem (a disc of
    `rosette_stem_px` about its touch point) is returned. Every try draws the same ring-stream values and the
    order is fixed, so the choice is deterministic. Raises `MotifError` when nothing fits.
    """
    divisions = round(360.0 / context.wedge_angle)
    centre = context.center
    keep = context.clearance_px("detail", "outline")
    free_px = Point(centre).distance(ink)
    axes = sorted((_ray_px(centre, ink, offset), name, offset)
                  for name, offset in (("cell", 0.0), ("divider", context.wedge_angle / 2.0)))
    reasons = []
    for adapt in (False, True):
        for count in rosette_lobe_counts(divisions):
            step = divisions // count
            for touch_px, axis, offset in axes:
                if not math.isfinite(touch_px):
                    continue
                label = f"{count} lobes on the {axis}{' (adapted)' if adapt else ''}"
                lobe_context = replace(context, inner_radius=0.0, outer_radius=touch_px,
                                       wedge_angle=context.wedge_angle * step)
                stem_px = rosette_stem_px(lobe_context)
                try:
                    instance = _draw_rosette(lobe_context, free_px - stem_px, adapt)
                except MotifError as error:
                    reasons.append(f"{label}: {error}")
                    continue
                rotations = [index * context.wedge_angle + offset for index in range(0, divisions, step)]
                # The ray may have met a deeper ring through a gap in ring 0, with another symmetry: every lobe
                # must touch ink where it ends.
                touches = [Point(lobe_context.to_cartesian(CellPoint(1.0, 0.0), r)).distance(ink) for r in rotations]
                if max(touches) > ROSETTE_TOUCH_TOLERANCE_PX:
                    reasons.append(f"{label}: not every lobe touches ink")
                elif not _rosette_clears(lobe_context, instance, rotations, ink, keep, stem_px):
                    reasons.append(f"{label}: closer than {keep:.1f}px to the ink")
                else:
                    return RosetteFit(step, axis, rotations, lobe_context, instance)
    if not reasons:
        raise MotifError(f"rosette needs at least {ROSETTE_MIN_LOBES} cells, the ring has {divisions}")
    raise MotifError("rosette fits nowhere: " + "; ".join(reasons))


def _rosette_clears(context: MotifContext, instance: MotifInstance, rotations: List[float],
                    ink: BaseGeometry, keep: float, stem_px: float) -> bool:
    """
    Whether every traced lobe keeps `keep` px from `ink` outside a disc of `stem_px` about its touch point: the
    stem meets the ink there on purpose, and only the body and the dot arc must keep their distance.
    """
    for rotation in rotations:
        touch = Point(context.to_cartesian(CellPoint(1.0, 0.0), rotation)).buffer(stem_px)
        for vector in instance.vectors:
            line = LineString(context.polyline(vector, rotation)).difference(touch)
            if not line.is_empty and line.distance(ink) < keep:
                return False
    return True

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
    {
        "name": "rosette",
        "category": "geometric",
        "generator": generate_rosette,
        "positions": ["centre"],
        # Repair-only: no composer filter asks for the "centre" role, so it is never a base, slot child, back
        # or attachment. The repair ladder places it inside ring 0 by name.
        "roles": ["centre"],
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
