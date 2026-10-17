"""Botanical motifs."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from shapely.geometry import LineString, Polygon

from motifs.contract import Anatomy, MotifError, MotifInstance, ReachEnd, build_instance, require_full_budget
from motifs.embellish import apply_embellishments, holds_pen
from motifs.geometry import (
    CellPoint,
    MotifContext,
    SmartVector,
    cubic_points,
    mirror_points,
    page_arc_points,
    side_touch_radial_within,
    size_draw,
)
from motifs.slot_fit import MIN_FIT_SCALE, SHRINK_FACTOR, fit_inside_slot, fit_slot_box

CURVE_STEPS = 12
# Each control beside the belly sits this share of its segment's radial length from the belly, at the
# belly's angular, so the outline crosses its widest vertex parallel to the cell's centreline.
BELLY_HANDLE = 0.4
# A short segment below the belly (a base-height touch) still gets a handle at least this long in radial, up to
# its whole length, so it bends up into the belly over its length instead of in one sharp turn just below it.
BELLY_MIN_HANDLE = 0.15
# A ripple never moves a sample more than this share of the half-width, so a thin outline cannot fold.
WAVE_SHARE_CAP = 0.25

# Lotus petal: the belly sits at a drawn share of the length; the base control leaves the narrow base at a
# fixed reach and spread; the tip control is drawn per instance - its radial handle is the flare (longer is a
# deeper concave flare into the tip) and its angular share is the tip sharpness (smaller is sharper).
PETAL_BELLY_RANGE = (0.3, 0.6)
PETAL_BASE_REACH, PETAL_BASE_SPREAD = 0.35, 0.35
PETAL_FLARE_RANGE = (0.3, 0.55)
PETAL_SHARPNESS_RANGE = (0.1, 0.3)

# Leaf: an almond whose convex sides meet at a curved point. Its apex control's angular share is the drawn
# roundness (larger is a blunter, rounder apex).
LEAF_BELLY_RANGE = (0.35, 0.55)
LEAF_BASE_REACH, LEAF_BASE_SPREAD = 0.4, 0.5
LEAF_APEX_HANDLE = 0.35
LEAF_ROUNDNESS_RANGE = (0.35, 0.7)


def _ripple(s: float) -> float:
    """A one-wave ripple over a segment's parameter `s`, zero with zero slope at both ends."""
    return math.sin(2.0 * math.pi * s) * math.sin(math.pi * s)


def _pointed_outline(
    base_radial: float,
    tip_radial: float,
    belly_radial: float,
    half_width: float,
    base_reach: float,
    base_spread: float,
    tip_handle: float,
    tip_share: float,
    wave: float,
    angular_bound: float,
) -> List[CellPoint]:
    """
    One closed, mirror-symmetric outline pointed at both ends: the right side base to tip, then the left back.

    Each side is two cubic segments, base to belly and belly to tip, the belly vertex `(belly_radial,
    half_width)` exactly. The controls either side of the belly share its angular, so the tangent there runs
    along the radial and the belly is the widest vertex: a side-touch vertex placed there meets its neighbour
    smoothly (spec 3.3), and nothing above or below it is wider. `wave` ripples each segment's interior
    samples, outward near the base and inward either side of the belly, with zero offset and slope at the
    vertices, scaled by the segment's share of the length so a short segment is not crinkled; interior samples
    are clamped to `angular_bound`.
    """
    base = CellPoint(base_radial, 0.0)
    belly = CellPoint(belly_radial, half_width)
    tip = CellPoint(tip_radial, 0.0)
    lower_length = belly_radial - base_radial
    upper_length = tip_radial - belly_radial
    lower_handle = min(lower_length, max(lower_length * BELLY_HANDLE, BELLY_MIN_HANDLE))
    lower = cubic_points(
        base,
        CellPoint(base_radial + lower_length * base_reach, half_width * base_spread),
        CellPoint(belly_radial - lower_handle, half_width),
        belly,
        CURVE_STEPS,
    )
    upper = cubic_points(
        belly,
        CellPoint(belly_radial + upper_length * BELLY_HANDLE, half_width),
        CellPoint(tip_radial - upper_length * tip_handle, half_width * tip_share),
        tip,
        CURVE_STEPS,
    )
    amplitude = min(wave, half_width * WAVE_SHARE_CAP) / (tip_radial - base_radial)
    # Outward on the lower segment's base half, inward on the upper segment's belly half.
    runs = ((lower, amplitude * lower_length), (upper[1:], -amplitude * upper_length))

    right: List[CellPoint] = []
    for run, (samples, ripple) in enumerate(runs):
        for offset, point in enumerate(samples):
            index = offset + run  # the upper run starts past the belly, which closes the lower run
            angular = point.angular
            if 0 < index < CURVE_STEPS:
                angular += ripple * _ripple(index / CURVE_STEPS)
                angular = max(-angular_bound, min(angular_bound, angular))
            right.append(CellPoint(point.radial, angular))

    # Mirror tip to base along the left side, dropping the duplicated tip and base.
    left = mirror_points(right)[1:-1][::-1]
    return right + left


def generate_petal(context: MotifContext) -> MotifInstance:
    rng = context.rng
    # Every parameter is drawn before any limit is applied, so tightening the
    # limits changes what is kept but never what the rng produced.
    # Ring fill (spec 13.3): the tip reaches the next ring or past it, and the base may dip below.
    length = size_draw(context, rng, 0.95, 1.3)
    dip = rng.uniform(0.0, 0.5)
    half_width = context.angular_limits * size_draw(context, rng, 0.55, 0.95)
    belly = rng.uniform(*PETAL_BELLY_RANGE)
    flare = rng.uniform(*PETAL_FLARE_RANGE)
    sharpness = rng.uniform(*PETAL_SHARPNESS_RANGE)
    wave = rng.uniform(0.0, context.complexity * 0.06)

    def outline(base_radial: float, tip_radial: float, width: float, bound: float,
                belly_radial: Optional[float] = None) -> List[CellPoint]:
        if belly_radial is None:
            belly_radial = base_radial + (tip_radial - base_radial) * belly
        return _pointed_outline(
            base_radial, tip_radial, belly_radial, width,
            PETAL_BASE_REACH, PETAL_BASE_SPREAD, flare, sharpness, wave, bound,
        )

    low, high = context.radial_limits
    if context.slot:
        box = fit_slot_box(context, "petal")
        base_radial = max(low, box.radial_min)
        tip_radial = min(high, box.radial_max)
        if tip_radial <= base_radial:
            raise MotifError("petal does not fit slot")
        half_width = min(half_width, box.half_width)
        angular_bound = min(context.angular_limits, box.half_width)
        centre = (base_radial + tip_radial) / 2.0

        def build(scale: float) -> List[CellPoint]:
            return outline(
                centre + (base_radial - centre) * scale,
                centre + (tip_radial - centre) * scale,
                half_width * scale,
                angular_bound * scale,
            )

        points = fit_inside_slot(context, "petal", build)
        _require_pen_room(context, "petal", points)
    else:
        base_radial = max(low, -dip)
        tip_radial = min(high, length)
        # Side touch (spec 13.2, 3.3): the belly is the shared side vertex, at the full angular budget.
        touch = side_touch_radial_within(context, base_radial, tip_radial)
        if touch is not None:
            half_width = context.angular_limits
        points = outline(base_radial, tip_radial, half_width, context.angular_limits, belly_radial=touch)
    anatomy = _pointed_anatomy(points)
    result = apply_embellishments(context, [SmartVector(points, closed=True)], anatomy, points)
    return build_instance(
        context, result.vectors, slot_outline=result.slot_outline, anatomy=anatomy,
        dropped_embellishments=result.dropped, slot_outline_weight=result.slot_outline_weight,
    )


def _require_pen_room(context: MotifContext, name: str, outline: List[CellPoint]) -> None:
    """
    A slot-fitted outline must be a face the validator accepts (`holds_pen`, as the diamond's is): a slot
    cut shallow, by a dot for one, can otherwise fit a child too thin to colour. Raising drops the child.
    """
    if not holds_pen(context, outline):
        raise MotifError(f"{name} fitted to the slot is too thin to hold a pen")


def _pointed_anatomy(points: List[CellPoint]) -> Anatomy:
    """A `_pointed_outline`'s anatomy: its base vertex first, its tip vertex where the right side ends."""
    return Anatomy(base=points[0], tip=points[2 * CURVE_STEPS], outline=0)


def _leaf_outline(
    base_radial: float,
    apex_radial: float,
    belly_radial: float,
    half_width: float,
    roundness: float,
    angular_bound: float,
) -> List[CellPoint]:
    """
    A closed leaf outline, pointed at the base and curved to a point at the apex; the belly vertex
    `(belly_radial, half_width)` is the widest. Its midrib, when it has one, is the `veins` embellishment.
    """
    return _pointed_outline(
        base_radial, apex_radial, belly_radial, half_width,
        LEAF_BASE_REACH, LEAF_BASE_SPREAD, LEAF_APEX_HANDLE, roundness, 0.0, angular_bound,
    )


def generate_leaf(context: MotifContext) -> MotifInstance:
    rng = context.rng
    # Every parameter is drawn before any limit is applied (the MONO property).
    # Ring fill (spec 13.3): the apex reaches the ring boundary or a little past it.
    length = size_draw(context, rng, 1.0, 1.2)
    half_width = context.angular_limits * size_draw(context, rng, 0.45, 0.85)
    belly = rng.uniform(*LEAF_BELLY_RANGE)
    roundness = rng.uniform(*LEAF_ROUNDNESS_RANGE)

    high = context.radial_limits[1]
    if context.slot:
        box = fit_slot_box(context, "leaf")
        base_radial = box.radial_min
        apex_radial = min(high, box.radial_max)
        if apex_radial <= base_radial:
            raise MotifError("leaf does not fit slot")
        half_width = min(half_width, box.half_width, context.angular_limits)
        angular_bound = min(context.angular_limits, box.half_width)
        centre = (base_radial + apex_radial) / 2.0

        built: List[List[CellPoint]] = []

        def build(scale: float) -> List[CellPoint]:
            low_end = centre + (base_radial - centre) * scale
            high_end = centre + (apex_radial - centre) * scale
            built.append(_leaf_outline(
                low_end, high_end, low_end + (high_end - low_end) * belly,
                half_width * scale, roundness, angular_bound * scale,
            ))
            return built[-1]

        # fit_inside_slot returns on the first outline that fits, so the last one built is the one kept.
        fit_inside_slot(context, "leaf", build)
        outline = built[-1]
        _require_pen_room(context, "leaf", outline)
    else:
        apex_radial = min(high, length)
        # Side touch (spec 13.2, 3.3): the belly is the shared side vertex, at the full angular budget.
        touch = side_touch_radial_within(context, 0.0, apex_radial)
        if touch is not None:
            half_width = context.angular_limits
        belly_radial = touch if touch is not None else apex_radial * belly
        outline = _leaf_outline(0.0, apex_radial, belly_radial, half_width, roundness, context.angular_limits)
    anatomy = _pointed_anatomy(outline)
    # The midrib and side veins are the veins embellishment (spec 6.3); a leaf without it has no midrib.
    result = apply_embellishments(context, [SmartVector(outline, closed=True)], anatomy, None)
    return build_instance(
        context, result.vectors, base_point=anatomy.base, anatomy=anatomy,
        dropped_embellishments=result.dropped,
    )


# Phase 3 bases (spec 7.3) fill the ring outward as the petal and leaf do: the tip on or past the outer
# boundary, within the 0.2 of outward overflow each declares; the base never dips (no inward overflow).
FILL_LENGTH_RANGE = (0.95, 1.2)
# A curve between two known tangents puts each control this share of the way to where the tangents cross,
# which reads as a smooth, nearly circular bend.
CONIC_HANDLE = 0.55
# A page-space arc that must fit is shrunk by this factor, at most this many times, before the motif gives up.
ARC_SHRINK = 0.85
ARC_MAX_SHRINKS = 12

# Teardrop: a round bulb below a pointed tip. The bulb is a page-space circular arc about the axis whose
# radius is a drawn share of the widest half-width; its ends sit at `90 + beta` degrees, beta searched upward
# from a drawn start until a smooth curve can carry the side out to the widest vertex. The widest vertex sits
# at a drawn share of the length (the side-touch radial when there is one); the point's half-angle is drawn.
TEARDROP_ARC_STEPS = 12
# The runs either side of the widest vertex are sampled twice as finely as other curves: the lower one can be
# short and sharply bent (a base-height touch), and even sampling keeps the vertex's neighbours balanced.
TEARDROP_SIDE_STEPS = 2 * CURVE_STEPS
TEARDROP_TIP_INDEX = TEARDROP_ARC_STEPS + 2 * TEARDROP_SIDE_STEPS
TEARDROP_WIDTH_RANGE = (0.55, 0.9)
TEARDROP_BELLY_RANGE = (0.25, 0.45)
TEARDROP_BULB_RANGE = (0.55, 0.8)
TEARDROP_BETA_RANGE = (10.0, 30.0)
TEARDROP_BETA_STEP, TEARDROP_BETA_MAX = 2.5, 88.0
TEARDROP_TIP_ANGLE_RANGE = (20.0, 35.0)
TEARDROP_TIP_HANDLE_RANGE = (0.35, 0.55)
# The bulb's ends stay inside this share of the widest half-width, and the tangent from a bulb end meets the
# widest vertex's radial tangent no higher than this share of the rise between them.
TEARDROP_END_SHARE = 0.85
TEARDROP_CORNER_SHARE = 0.6

# Rounded petal: the petal's lotus profile with its tip replaced by a page-space circular cap tangent to
# both sides. The cap's radius is a drawn share of the belly half-width, and its ends sit a drawn angle
# either side of the top, where the sides arrive tangent to it.
CAP_STEPS = 8
ROUNDED_TIP_INDEX = 2 * CURVE_STEPS + CAP_STEPS
ROUNDED_CAP_RANGE = (0.25, 0.45)
ROUNDED_CAP_ANGLE_RANGE = (40.0, 65.0)
# The cap's ends stay inside this share of the belly half-width and above this share of the belly-to-top run.
ROUNDED_END_SHARE = 0.8
ROUNDED_END_RISE = 0.25


def _arc_heading(context: MotifContext, centre_radial: float, radius_px: float, degrees: float) -> CellPoint:
    """
    The cell-space direction of a `page_arc_points` arc about `(centre_radial, 0)` at `degrees`, moving
    toward smaller angles (up the right side toward the top). Exact for the sampled arc, so a curve that
    leaves along it continues the arc without a corner.
    """
    theta = math.radians(degrees)
    return CellPoint(context.px_to_radial(radius_px * math.sin(theta)),
                     -context.px_to_angular(radius_px * math.cos(theta), centre_radial))


def _closed_from_right(right: List[CellPoint]) -> List[CellPoint]:
    """A closed mirror-symmetric outline from its right side, axis base to axis tip."""
    return right + mirror_points(right)[1:-1][::-1]


def _teardrop_outline(
    context: MotifContext,
    base_radial: float,
    tip_radial: float,
    belly_radial: float,
    half_width: float,
    bulb: float,
    beta_start: float,
    tip_angle: float,
    tip_handle: float,
) -> List[CellPoint]:
    """
    A closed teardrop: a page-space circular arc about the axis from the base vertex `(base_radial, 0)` to
    an end at `90 + beta` degrees, a cubic tangent to the arc there out to the widest vertex `(belly_radial,
    half_width)` (controls on the two tangents, so the outline runs along the radial at that vertex), and a
    cubic to the point `(tip_radial, 0)`, which it meets at the drawn `tip_angle` from the axis.
    """
    belly = CellPoint(belly_radial, half_width)
    belly_px = context.angular_to_px(half_width, belly_radial)
    for shrink in range(ARC_MAX_SHRINKS):
        radius = bulb * belly_px * ARC_SHRINK ** shrink
        centre = base_radial + context.px_to_radial(radius)
        beta = beta_start
        while beta <= TEARDROP_BETA_MAX:
            arc = page_arc_points(context, CellPoint(centre, 0.0), radius, 180.0, 90.0 + beta, TEARDROP_ARC_STEPS)
            end = arc[-1]
            heading = _arc_heading(context, centre, radius, 90.0 + beta)
            if end.radial < belly_radial and end.angular < TEARDROP_END_SHARE * half_width and heading.angular > 0:
                reach = (half_width - end.angular) / heading.angular
                corner = end.radial + reach * heading.radial
                if corner <= end.radial + TEARDROP_CORNER_SHARE * (belly_radial - end.radial):
                    arc[0] = CellPoint(base_radial, 0.0)
                    lower = cubic_points(
                        end,
                        CellPoint(end.radial + CONIC_HANDLE * reach * heading.radial,
                                  end.angular + CONIC_HANDLE * reach * heading.angular),
                        CellPoint(belly_radial - CONIC_HANDLE * (belly_radial - corner), half_width),
                        belly,
                        TEARDROP_SIDE_STEPS,
                    )
                    rise = tip_radial - belly_radial
                    angle = math.radians(tip_angle)
                    handle_px = tip_handle * context.radial_to_px(rise)
                    # The tip control stays inside the belly, so the belly remains the widest vertex.
                    across = context.px_to_angular(handle_px * math.sin(angle), tip_radial)
                    if across > 0.9 * half_width:
                        handle_px *= 0.9 * half_width / across
                    upper = cubic_points(
                        belly,
                        CellPoint(belly_radial + rise * BELLY_HANDLE, half_width),
                        CellPoint(tip_radial - context.px_to_radial(handle_px * math.cos(angle)),
                                  context.px_to_angular(handle_px * math.sin(angle), tip_radial)),
                        CellPoint(tip_radial, 0.0),
                        TEARDROP_SIDE_STEPS,
                    )
                    return _closed_from_right(arc + lower[1:] + upper[1:])
            beta += TEARDROP_BETA_STEP
    raise MotifError("teardrop: no round base fits below its widest vertex")


def generate_teardrop(context: MotifContext) -> MotifInstance:
    rng = context.rng
    # Every parameter is drawn before any limit is applied (the MONO property).
    length = size_draw(context, rng, *FILL_LENGTH_RANGE)
    half_width = context.angular_limits * size_draw(context, rng, *TEARDROP_WIDTH_RANGE)
    belly = rng.uniform(*TEARDROP_BELLY_RANGE)
    bulb = rng.uniform(*TEARDROP_BULB_RANGE)
    beta_start = rng.uniform(*TEARDROP_BETA_RANGE)
    tip_angle = rng.uniform(*TEARDROP_TIP_ANGLE_RANGE)
    tip_handle = rng.uniform(*TEARDROP_TIP_HANDLE_RANGE)

    def outline(base_radial: float, tip_radial: float, width: float,
                belly_radial: Optional[float] = None) -> List[CellPoint]:
        if belly_radial is None:
            belly_radial = base_radial + (tip_radial - base_radial) * belly
        return _teardrop_outline(context, base_radial, tip_radial, belly_radial, width,
                                 bulb, beta_start, tip_angle, tip_handle)

    points = _fill_or_fit(context, "teardrop", length, half_width, outline)
    anatomy = Anatomy(base=points[0], tip=points[TEARDROP_TIP_INDEX], outline=0)
    return _embellished_instance(context, points, anatomy)


def _fill_or_fit(context: MotifContext, name: str, length: float, half_width: float, outline) -> List[CellPoint]:
    """
    A closed outline from `outline(base, tip, half_width, belly_radial=None)`: fitted inside the slot for a
    slot child, which must hold a pen; otherwise from radial 0 (or the lower limit) to the drawn length,
    clamped to the upper limit, at the full angular budget with its widest vertex on the side-touch radial
    when the ring touches.
    """
    low, high = context.radial_limits
    if context.slot:
        box = fit_slot_box(context, name)
        base_radial, tip_radial = max(low, box.radial_min), min(high, box.radial_max)
        if tip_radial <= base_radial:
            raise MotifError(f"{name} does not fit slot")
        width = min(half_width, box.half_width)
        centre = (base_radial + tip_radial) / 2.0
        points = fit_inside_slot(context, name, lambda scale: outline(
            centre + (base_radial - centre) * scale, centre + (tip_radial - centre) * scale, width * scale))
        _require_pen_room(context, name, points)
        return points
    base_radial, tip_radial = max(low, 0.0), min(high, length)
    # Side touch (spec 3.3): the widest vertex is the shared side vertex, at the full angular budget.
    touch = side_touch_radial_within(context, base_radial, tip_radial)
    if touch is not None:
        half_width = context.angular_limits
    return outline(base_radial, tip_radial, half_width, belly_radial=touch)


def _embellished_instance(context: MotifContext, points: List[CellPoint], anatomy: Anatomy) -> MotifInstance:
    """The closed outline with its embellishments, declaring the slot inside it (or inside its innermost echo)."""
    result = apply_embellishments(context, [SmartVector(points, closed=True)], anatomy, points)
    return build_instance(
        context, result.vectors, slot_outline=result.slot_outline, anatomy=anatomy,
        dropped_embellishments=result.dropped, slot_outline_weight=result.slot_outline_weight,
    )


def _rounded_outline(
    context: MotifContext,
    base_radial: float,
    tip_radial: float,
    belly_radial: float,
    half_width: float,
    flare: float,
    cap: float,
    cap_angle: float,
) -> List[CellPoint]:
    """
    A closed rounded petal: the petal's lower run from the pointed base `(base_radial, 0)` to the belly
    vertex `(belly_radial, half_width)`, then a cubic from the belly (leaving along the radial) to the end of
    a page-space circular cap about the axis, arriving along the cap's own tangent, and the cap over the top
    `(tip_radial, 0)`. The cap's radius is `cap` of the belly half-width, shrunk until its ends sit inside
    the belly and well above it.
    """
    belly = CellPoint(belly_radial, half_width)
    lower_length = belly_radial - base_radial
    lower_handle = min(lower_length, max(lower_length * BELLY_HANDLE, BELLY_MIN_HANDLE))
    lower = cubic_points(
        CellPoint(base_radial, 0.0),
        CellPoint(base_radial + lower_length * PETAL_BASE_REACH, half_width * PETAL_BASE_SPREAD),
        CellPoint(belly_radial - lower_handle, half_width),
        belly,
        CURVE_STEPS,
    )
    belly_px = context.angular_to_px(half_width, belly_radial)
    for shrink in range(ARC_MAX_SHRINKS):
        radius = cap * belly_px * ARC_SHRINK ** shrink
        centre = tip_radial - context.px_to_radial(radius)
        arc = page_arc_points(context, CellPoint(centre, 0.0), radius, cap_angle, 0.0, CAP_STEPS)
        end = arc[0]
        if (end.radial > belly_radial + ROUNDED_END_RISE * (tip_radial - belly_radial)
                and end.angular < ROUNDED_END_SHARE * half_width):
            break
    else:
        raise MotifError("rounded_petal: no cap fits above the belly")
    arc[-1] = CellPoint(tip_radial, 0.0)
    heading = _arc_heading(context, centre, radius, cap_angle)
    rise = end.radial - belly_radial
    # The control below the cap end sits on the cap's tangent, `flare` of the rise below it; never wider
    # than the belly, so the belly stays the widest vertex.
    reach = flare * rise / heading.radial
    if heading.angular < 0:
        reach = min(reach, (half_width - end.angular) / -heading.angular)
    upper = cubic_points(
        belly,
        CellPoint(belly_radial + rise * BELLY_HANDLE, half_width),
        CellPoint(end.radial - reach * heading.radial, end.angular - reach * heading.angular),
        end,
        CURVE_STEPS,
    )
    return _closed_from_right(lower + upper[1:] + arc[1:])


def generate_rounded_petal(context: MotifContext) -> MotifInstance:
    rng = context.rng
    # Every parameter is drawn before any limit is applied (the MONO property).
    length = size_draw(context, rng, *FILL_LENGTH_RANGE)
    half_width = context.angular_limits * size_draw(context, rng, 0.55, 0.95)
    belly = rng.uniform(*PETAL_BELLY_RANGE)
    flare = rng.uniform(*PETAL_FLARE_RANGE)
    cap = rng.uniform(*ROUNDED_CAP_RANGE)
    cap_angle = rng.uniform(*ROUNDED_CAP_ANGLE_RANGE)

    def outline(base_radial: float, tip_radial: float, width: float,
                belly_radial: Optional[float] = None) -> List[CellPoint]:
        if belly_radial is None:
            belly_radial = base_radial + (tip_radial - base_radial) * belly
        return _rounded_outline(context, base_radial, tip_radial, belly_radial, width, flare, cap, cap_angle)

    points = _fill_or_fit(context, "rounded_petal", length, half_width, outline)
    anatomy = Anatomy(base=points[0], tip=points[ROUNDED_TIP_INDEX], outline=0)
    return _embellished_instance(context, points, anatomy)


# Heart: two lobes, each a page-space circular arc, meeting at a cusp on the axis at the top and running by
# cubics down to a point on the axis at the bottom. The lobe's widest vertex `(waist, half_width)` sits at a
# drawn share of the height (the side-touch radial when there is one), the point at a drawn bottom radial, and
# the cusp's notch is drawn as the angle `notch` its arcs leave the axis at. A lobe whose round arc would rise
# past the top limit is lowered into a shoulder: a smaller circle whose arc ends partway down, joined to the
# widest vertex by a cubic tangent to both.
HEART_ARC_STEPS = 16
HEART_BOTTOM_RANGE = (0.0, 0.1)
HEART_WAIST_RANGE = (0.45, 0.6)
HEART_WIDTH_RANGE = (0.65, 0.95)
HEART_NOTCH_RANGE = (25.0, 45.0)
HEART_SPREAD_RANGE = (0.15, 0.4)
HEART_POINT_REACH = 0.35
# A shouldered lobe's circle is this share of the room above the widest vertex, and its arc ends no lower than
# where its tangent meets the widest vertex's radial tangent this share of the way up the shoulder.
HEART_SHOULDER_SHARE = 0.85
HEART_SHOULDER_CORNER = 0.25
HEART_SHOULDER_STEP, HEART_SHOULDER_MIN = 2.5, 10.0


def _heart_lobe(context: MotifContext, waist: CellPoint, top_limit: float, notch: float):
    """
    The right lobe's circle (centre in cell space, radius in px) and the angle its arc ends at, in the page
    frame of `page_arc_points`: 90 when the arc runs down to the widest vertex `waist` itself, less when a
    shoulder cubic joins it. The arc runs from that angle over the top to the cusp at `-(90 - notch)`.
    """
    lean = math.cos(math.radians(notch))  # the cusp sits this share of the radius left of the lobe's centre
    radius = context.angular_to_px(waist.angular, waist.radial) / (1.0 + lean)
    if waist.radial + context.px_to_radial(radius) <= top_limit:
        centre = CellPoint(waist.radial, context.px_to_angular(radius * lean, waist.radial))
        return centre, radius, 90.0
    room = context.radial_to_px(top_limit - waist.radial)
    radius = HEART_SHOULDER_SHARE * room
    centre_radial = top_limit - context.px_to_radial(radius)
    centre = CellPoint(centre_radial, context.px_to_angular(radius * lean, centre_radial))
    end_deg = 90.0 - HEART_SHOULDER_STEP
    while end_deg >= HEART_SHOULDER_MIN:
        theta = math.radians(end_deg)
        end = CellPoint(centre.radial + context.px_to_radial(radius * math.cos(theta)),
                        centre.angular + context.px_to_angular(radius * math.sin(theta), centre.radial))
        heading = _arc_heading(context, centre.radial, radius, end_deg)
        if end.angular < waist.angular and heading.angular < 0:
            back = (end.angular - waist.angular) / heading.angular
            corner = end.radial - back * heading.radial
            if corner >= waist.radial + HEART_SHOULDER_CORNER * (end.radial - waist.radial):
                return centre, radius, end_deg
        end_deg -= HEART_SHOULDER_STEP
    raise MotifError("heart: no lobe fits below the top limit")


def _heart_outline(
    context: MotifContext,
    bottom: float,
    waist: CellPoint,
    top_limit: float,
    notch: float,
    spread: float,
) -> List[CellPoint]:
    """
    A closed heart: the point `(bottom, 0)`, a cubic up to the widest vertex `waist` arriving along the
    radial, an optional shoulder cubic, and the lobe arc over the top to the cusp on the axis; mirrored.
    """
    centre, radius, end_deg = _heart_lobe(context, waist, top_limit, notch)
    rise = waist.radial - bottom
    handle = min(rise, max(rise * BELLY_HANDLE, BELLY_MIN_HANDLE))
    right = cubic_points(
        CellPoint(bottom, 0.0),
        CellPoint(bottom + rise * HEART_POINT_REACH, waist.angular * spread),
        CellPoint(waist.radial - handle, waist.angular),
        waist,
        CURVE_STEPS,
    )
    arc = page_arc_points(context, centre, radius, end_deg, -(90.0 - notch), HEART_ARC_STEPS)
    if end_deg < 90.0:
        end = arc[0]
        heading = _arc_heading(context, centre.radial, radius, end_deg)
        back = (end.angular - waist.angular) / heading.angular
        corner = end.radial - back * heading.radial
        right += cubic_points(
            waist,
            CellPoint(waist.radial + CONIC_HANDLE * (corner - waist.radial), waist.angular),
            CellPoint(end.radial - CONIC_HANDLE * back * heading.radial,
                      end.angular - CONIC_HANDLE * back * heading.angular),
            end,
            CURVE_STEPS,
        )[1:]
    else:
        arc[0] = waist
    arc[-1] = CellPoint(arc[-1].radial, 0.0)
    return _closed_from_right(right + arc[1:])


def generate_heart(context: MotifContext) -> MotifInstance:
    rng = context.rng
    # Every parameter is drawn before any limit is applied (the MONO property).
    bottom = rng.uniform(*HEART_BOTTOM_RANGE)
    waist_share = rng.uniform(*HEART_WAIST_RANGE)
    width_share = size_draw(context, rng, *HEART_WIDTH_RANGE)
    notch = rng.uniform(*HEART_NOTCH_RANGE)
    spread = rng.uniform(*HEART_SPREAD_RANGE)

    def outline(low: float, high: float, half_width: float, waist_radial: Optional[float] = None) -> List[CellPoint]:
        if waist_radial is None:
            waist_radial = low + (high - low) * waist_share
        return _heart_outline(context, low, CellPoint(waist_radial, half_width), high, notch, spread)

    low, high = context.radial_limits
    half_width = context.angular_limits * width_share
    if context.slot:
        box = fit_slot_box(context, "heart")
        base, top = max(low, box.radial_min), min(high, box.radial_max)
        if top <= base:
            raise MotifError("heart does not fit slot")
        width = min(half_width, box.half_width)
        centre = (base + top) / 2.0
        points = fit_inside_slot(context, "heart", lambda scale: outline(
            centre + (base - centre) * scale, centre + (top - centre) * scale, width * scale))
        _require_pen_room(context, "heart", points)
    else:
        base, top = max(low, 0.0, bottom), high
        # Side touch (spec 7.3): the lobes' widest vertices are the shared side vertices, at the full budget.
        touch = side_touch_radial_within(context, base, top)
        if touch is not None:
            half_width = context.angular_limits
        points = outline(base, top, half_width, touch)
    cusp = next(k for k, point in enumerate(points) if k and point.angular == 0.0)
    anatomy = Anatomy(base=points[0], tip=points[cusp], outline=0)
    return _embellished_instance(context, points, anatomy)


# Curl: two mirrored spirals joined at the base. Each is one open vector: a stalk from the base on the axis out
# to the bottom of its spiral, the spiral winding up the outer side, over the top and down the side facing the
# axis, tightening by one pitch per turn, and a straight connector from the inner end out to the turn before
# it, so the end lands on the vector's own earlier ink. The spiral is built in true page coordinates about its
# centre (offsets along and across the centre's radius) and mapped into the cell with `to_cell`, so consecutive
# turns sit a pitch of at least `clearance_px()` apart on the page; it may be stretched (by at least 1) along
# the radial to suit a tall cell and across it to fill a wide one, up to `CURL_MAX_STRETCH`, past which it keeps
# to the cell edge and a longer stalk reaches the axis. Its outermost vertex, where the tangent runs along the
# radial, is the side-touch vertex. It winds a drawn 1.15 to 1.5 turns, fewer when the cell is small, and raises
# `MotifError` when not even `CURL_MIN_TURNS` fits, since its end would have no earlier turn to land on. Near
# the eye the turns run slantwise, so their true distance apart is the pitch times the cosine of the slant
# angle `atan(tighten / radius)`; the eye is kept wide enough that this stays at least the clearance.
CURL_STALK_STEPS = 8
# The stalk's controls sit this share of the centre's distance from the axis along its end tangents.
CURL_STALK_HANDLE = 0.4
CURL_STEPS_PER_TURN = 64
CURL_TURNS_RANGE = (1.15, 1.5)
CURL_MIN_TURNS = 1.05
CURL_EYE_RANGE = (0.3, 0.7)  # the inner end's distance from the centre, as a share of the pitch
CURL_PITCH_RANGE = (1.2, 1.35)  # the pitch as a multiple of the clearance, room to slant near the eye
CURL_TALL_RANGE = (1.0, 1.2)  # radial stretch of the spiral
CURL_WIDTH_RANGE = (0.75, 0.95)  # without side touch, the share of the half-cell the curl spans
CURL_CENTRE_RANGE = (0.4, 0.6)  # without side touch, the radial of the spiral's centre
CURL_DIP_RANGE = (0.0, 0.15)  # how far the base sits below the spiral's bottom, as a share of the pitch
CURL_MIN_EYE_PX = 1.5
CURL_EYE_SLACK = 1.0
CURL_MAX_STRETCH = 1.6
CURL_PASSES = 10
CURL_DROP_MARGIN = 1.1
# The size is fitted in a flat approximation of the cell and then pinned exactly on the page; the fit leaves
# this share of the room, so the exact across-stretch never has to fall below 1.
CURL_FIT_SHARE = 0.97
CURL_PIN_PASSES = 4
CURL_TOP_PASSES = 8
# Each refit holds back this many times the overshoot, plus this many px: the top moves less than the room
# held back, since pinning the touch vertex moves the centre after the fit.
CURL_TOP_STEP, CURL_TOP_STEP_PX = 2.0, 1.0
CURL_FLOOR_MARGIN_PX = 0.5
CURL_OUTERMOST_BRACKET = 0.5


@dataclass
class CurlLayout:
    """The right spiral of a curl: its centre on the page and its shape in px about that centre."""

    centre: CellPoint
    centre_radius: float  # px from the ring centre to the spiral's centre
    centre_angle: float  # the spiral centre's angle in the unturned cell, in radians
    centre_y: float  # px across from the axis to the spiral's centre
    start_radius: float  # px from the centre to the spiral's start, at its bottom
    tighten: float  # px per radian the radius shrinks
    sweep: float  # radians the spiral turns through
    stretch_radial: float
    stretch_angular: float
    dip: float  # px the base sits below the spiral's bottom
    outermost: float  # the sweep angle of the outermost vertex
    touch: Optional[float]

    @property
    def centres(self) -> List[CellPoint]:
        """Both spirals' centres, right then left."""
        return [self.centre, CellPoint(self.centre.radial, -self.centre.angular)]


def _curl_draws(rng: random.Random) -> Tuple[float, ...]:
    """Every curl parameter, drawn before any limit is applied (the MONO property)."""
    return (rng.uniform(*CURL_TURNS_RANGE), rng.uniform(*CURL_EYE_RANGE), rng.uniform(*CURL_PITCH_RANGE),
            rng.uniform(*CURL_TALL_RANGE), rng.uniform(*CURL_WIDTH_RANGE), rng.uniform(*CURL_CENTRE_RANGE),
            rng.uniform(*CURL_DIP_RANGE))


def curl_layout(context: MotifContext, draws: Optional[Tuple[float, ...]] = None,
                box: Optional[Tuple[float, float, float]] = None) -> CurlLayout:
    """
    Lay out the right spiral. As a base, the curl spans its half-cell from the axis to the side-touch vertex
    (or a drawn share of the half-cell) between radial 0 and its upper radial limit, centred on the side-touch
    radial (or a drawn radial); a slot child passes `box`, its `(floor, ceiling, half_width_px)`, and is
    centred in it. Raises `MotifError` when not even `CURL_MIN_TURNS` fit.

    The room above the centre is fitted flat, and pinning the touch vertex moves the centre afterwards, so the
    drawn spiral can pass its ceiling by a hair. Then more room is held back and it is fitted again, at most
    `CURL_TOP_PASSES` times.
    """
    draws = draws or _curl_draws(context.rng)
    ceiling = box[1] if box is not None else context.radial_limits[1]
    reserve = 0.0
    for _ in range(CURL_TOP_PASSES):
        layout = _curl_layout_once(context, draws, box, reserve)
        top = max(point.radial for point in _curl_vector(context, layout))
        if top <= ceiling + 1e-12:
            return layout
        reserve += CURL_TOP_STEP * context.radial_to_px(top - ceiling) + CURL_TOP_STEP_PX
    raise MotifError("curl does not fit below its ceiling")


def _curl_layout_once(context: MotifContext, draws: Tuple[float, ...],
                      box: Optional[Tuple[float, float, float]], reserve: float) -> CurlLayout:
    """`curl_layout` with `reserve` px held back from the room above the centre."""
    turns, eye, pitch_share, tall, width_share, centre_share, dip_share = draws
    low, high = context.radial_limits
    if box is not None:
        floor, ceiling, width_px = box
        touch, centre = None, (floor + ceiling) / 2.0
    else:
        floor, ceiling, width_px = max(low, 0.0), high, None
        touch = side_touch_radial_within(context, floor, ceiling)
        # An absolute drawn radial, so a narrower ceiling only ever shrinks the curl (the MONO property).
        centre = touch if touch is not None else max(floor, min(ceiling, centre_share))
    clearance = context.clearance_px()
    pitch, gap = clearance * pitch_share, clearance / 2.0
    # `sink` is how far the base sits below the spiral's bottom on the page; `lift` how much further out on
    # the page than in the flat layout the base sits, off to one side of the centre's radius. The flat dip is
    # their sum, so the base lands `sink` below the bottom and only `sink` is taken from the room below.
    sink, lift, lean = dip_share * pitch, 0.0, 1.0
    for _ in range(CURL_PASSES):
        if width_px is not None:
            half_width = width_px
        elif touch is not None:
            half_width = context.angular_to_px(context.angular_limits, centre)
        else:
            half_width = width_share * context.angular_to_px(context.angular_limits, centre)
        below = context.radial_to_px(centre - floor) - sink - CURL_FLOOR_MARGIN_PX
        above = context.radial_to_px(ceiling - centre) - reserve
        fit = _curl_fit(turns, eye, pitch, clearance, tall, CURL_FIT_SHARE * half_width - lean * gap,
                        below, above, lean)
        if fit is None and width_px is None and touch is None:
            # Without side touch the drawn width share is only a preference: a curl that needs the whole
            # half-cell takes it rather than failing.
            full = context.angular_to_px(context.angular_limits, centre)
            fit = _curl_fit(turns, eye, pitch, clearance, tall, CURL_FIT_SHARE * full - lean * gap,
                            below, above, lean)
        if fit is None:
            raise MotifError("curl does not fit its cell")
        start, tighten, sweep, stretch_r, stretch_a, offset, outermost = fit
        moved = centre
        if touch is not None:
            # The outermost vertex is the side-touch vertex: the centre sits so that vertex is on the radial.
            radius = start - tighten * outermost
            moved = touch - context.px_to_radial(stretch_r * radius * math.cos(math.pi - outermost))
        # The stalk's control beside the spiral's bottom lies on the spiral's tangent, a little below the
        # bottom; the base sits at least that low, so it stays the curl's lowest point.
        stalk_drop = _curl_stalk_drop(gap + offset, start, tighten, stretch_r, stretch_a)
        new_sink = max(dip_share * pitch, CURL_DROP_MARGIN * stalk_drop if stalk_drop > sink else sink)
        base_radius = context.radius_at(moved) - stretch_r * start - new_sink
        if base_radius <= 0:
            raise MotifError("curl does not fit below its centre")
        new_lift = math.hypot(base_radius, gap + offset) - base_radius
        # The run across to the axis sits at the base's radius, lower than the centre's, where the same px
        # span a wider angle: it counts `lean` times over in the room measured at the centre.
        new_lean = context.radius_at(moved) / base_radius
        if (new_sink == sink and abs(moved - centre) <= 1e-12 and abs(new_lift - lift) <= 1e-9
                and abs(new_lean - lean) <= 1e-12):
            break
        centre, sink, lift, lean = moved, new_sink, new_lift, new_lean
    dip = sink + lift
    layout = CurlLayout(
        centre=CellPoint(centre, 0.0), centre_radius=context.radius_at(centre), centre_angle=0.0,
        centre_y=gap + offset, start_radius=start, tighten=tighten, sweep=sweep, stretch_radial=stretch_r,
        stretch_angular=stretch_a, dip=dip, outermost=outermost, touch=touch,
    )
    layout.centre_angle = _curl_centre_angle(layout)
    inner = offset / stretch_a if stretch_a < CURL_MAX_STRETCH else None
    for _ in range(CURL_PASSES):
        if touch is not None:
            _pin_curl(context, layout, gap, inner)
        # Off to one side of the centre's radius, the base sits a little further out on the page than the
        # flat layout says; it goes deeper until it is below the spiral's end of the stalk. (Beside the base
        # the stalk may sag a hair below it; `CURL_FLOOR_MARGIN_PX` keeps that inside the limits.)
        lowest = min(math.hypot(*(a - b for a, b in zip(page, context.center)))
                     for page in _curl_stalk_pages(context, layout)[32:])
        base = math.hypot(*(a - b for a, b in zip(_curl_page(context, layout, *_curl_base_offset(layout)),
                                                  context.center)))
        if base <= lowest + 1e-9:
            break
        layout.dip += CURL_DROP_MARGIN * (base - lowest)
        layout.centre_angle = _curl_centre_angle(layout)
    layout.outermost = _curl_outermost(layout)[0]
    layout.centre = context.to_cell(_curl_page(context, layout, 0.0, 0.0))
    return layout


def _curl_base_offset(layout: CurlLayout) -> Tuple[float, float]:
    """The base's px offsets from the spiral's centre: the dip below the spiral's bottom, across on the axis."""
    return -layout.stretch_radial * layout.start_radius - layout.dip, -layout.centre_y


def _curl_stalk_pages(context: MotifContext, layout: CurlLayout) -> List[Tuple[float, float]]:
    """The stalk sampled finely on the page, base to the spiral's start."""
    at = _curl_stalk(layout)
    return [_curl_page(context, layout, *at(k / 64)) for k in range(65)]


def _curl_stalk(layout: CurlLayout):
    """
    The stalk as a function of its parameter (0 at the base, 1 at the spiral's start), in px offsets from the
    spiral's centre: from the base on the axis, the dip below the spiral's bottom, out to the spiral's start,
    leaving the axis square to it on the page (so the two stalks meet there in one smooth curve) and arriving
    along the spiral's own tangent.
    """
    bottom = -layout.stretch_radial * layout.start_radius
    tangent = (layout.stretch_radial * layout.tighten, layout.stretch_angular * layout.start_radius)
    norm = math.hypot(*tangent)
    handle = CURL_STALK_HANDLE * layout.centre_y
    base = _curl_base_offset(layout)
    # Square to the axis on the page is tilted by the centre's angle in the centre's own frame.
    square = (math.sin(layout.centre_angle), math.cos(layout.centre_angle))
    controls = [base, (base[0] + handle * square[0], base[1] + handle * square[1]),
                (bottom - handle * tangent[0] / norm, -handle * tangent[1] / norm), (bottom, 0.0)]

    def at(u: float) -> Tuple[float, float]:
        w = ((1 - u) ** 3, 3 * (1 - u) ** 2 * u, 3 * (1 - u) * u * u, u ** 3)
        return sum(a * c[0] for a, c in zip(w, controls)), sum(a * c[1] for a, c in zip(w, controls))

    return at


def _curl_centre_angle(layout: CurlLayout) -> float:
    """The spiral centre's angle that puts the base, below and across from it, exactly on the axis."""
    return math.atan2(layout.centre_y,
                      layout.centre_radius - layout.stretch_radial * layout.start_radius - layout.dip)


def _curl_page(context: MotifContext, layout: CurlLayout, x: float, y: float) -> Tuple[float, float]:
    """The page point `x` px out along the spiral centre's radius and `y` px across it, toward the cell edge."""
    angle = layout.centre_angle
    along, across = (math.cos(angle), math.sin(angle)), (-math.sin(angle), math.cos(angle))
    reach = layout.centre_radius + x
    return (context.center[0] + reach * along[0] + y * across[0],
            context.center[1] + reach * along[1] + y * across[1])


def _curl_outermost(layout: CurlLayout) -> Tuple[float, float, float]:
    """
    The sweep angle, page angle (radians, in the unturned cell) and page radius of the spiral's outermost
    point: the largest angle about the ring centre, where the spiral's tangent runs along the radial. A
    golden-section search finds it within `CURL_OUTERMOST_BRACKET` of the flat layout's outermost angle.
    """
    def angle_at(t: float) -> float:
        x, y = _curl_offsets(layout, t)
        return math.atan2(y, layout.centre_radius + x)

    lo = max(0.0, layout.outermost - CURL_OUTERMOST_BRACKET)
    hi = min(math.pi, layout.outermost + CURL_OUTERMOST_BRACKET)
    golden = (math.sqrt(5.0) - 1.0) / 2.0
    for _ in range(60):
        a, b = hi - golden * (hi - lo), lo + golden * (hi - lo)
        lo, hi = (a, hi) if angle_at(a) < angle_at(b) else (lo, b)
    t = (lo + hi) / 2.0
    x, y = _curl_offsets(layout, t)
    return t, layout.centre_angle + angle_at(t), math.hypot(layout.centre_radius + x, y)


def _pin_curl(context: MotifContext, layout: CurlLayout, gap: float, inner: Optional[float]) -> None:
    """
    Pin the outermost vertex on the side-touch vertex: solve the across-stretch (keeping the gap to the axis)
    or, when the stretch is capped (`inner` is None), the centre's distance from the axis, so the outermost
    angle is the cell edge's; then move the centre along its radius so that vertex sits on the side-touch
    radial. Alternating passes settle both; the generator then sets the vertex to the exact cell point.
    """
    target_angle = math.radians(context.half_angle * context.angular_limits)
    target_radius = context.radius_at(layout.touch)

    def outer_angle(value: float) -> float:
        if inner is None:
            layout.centre_y = value
        else:
            layout.stretch_angular, layout.centre_y = value, gap + value * inner
        layout.centre_angle = _curl_centre_angle(layout)
        return _curl_outermost(layout)[1]

    for _ in range(CURL_PIN_PASSES):
        layout.centre_radius += target_radius - _curl_outermost(layout)[2]
        # Secant steps on the stretch (or distance), which the outermost angle follows almost linearly.
        a = layout.centre_y if inner is None else layout.stretch_angular
        b = a * 1.01
        fa, fb = outer_angle(a) - target_angle, outer_angle(b) - target_angle
        for _ in range(30):
            if fb == fa or abs(fb) <= 1e-15:
                break
            a, b, fa = b, b - fb * (b - a) / (fb - fa), fb
            fb = outer_angle(b) - target_angle
        outer_angle(b)
    if inner is not None and layout.stretch_angular < 1.0 - 1e-9:
        raise MotifError("curl is too wide for its cell")


def _curl_stalk_drop(centre_y: float, start: float, tighten: float, stretch_r: float, stretch_a: float) -> float:
    """How far below the spiral's bottom the stalk's second control sits, in px (see `_curl_vector`)."""
    tangent = (stretch_r * tighten, stretch_a * start)
    return CURL_STALK_HANDLE * centre_y * tangent[0] / math.hypot(*tangent)


def _curl_extent(start: float, tighten: float, sweep: float) -> Tuple[float, float, float]:
    """
    The unstretched spiral's reach toward the cell edge and toward the axis, in px from its centre, and the
    sweep angle of its outermost point, where `d/dt (r sin t) = 0`, so `tan t = r / tighten`.
    """
    angle = math.pi / 2.0
    for _ in range(60):
        angle = math.atan2(start - tighten * angle, tighten)
    samples = [sweep * k / 2000 for k in range(2001)]
    inner = -min((start - tighten * t) * math.sin(t) for t in samples)
    return (start - tighten * angle) * math.sin(angle), inner, angle


def _curl_fit(turns, eye, pitch, clearance, tall, room, below, above, lean=1.0):
    """
    `(start, tighten, sweep, stretch_radial, stretch_angular, offset, outermost)` for a spiral filling `room`
    px beside the gap to the axis (`offset` is its centre's distance past the gap; the side facing the axis
    counts `lean` times over, see `curl_layout`), with `below` px under its centre (the base's dip already
    taken off) and `above` px over it, in a flat approximation of the cell;
    None when not even `CURL_MIN_TURNS` fit. The spiral winds the drawn `turns` when there is room, fewer
    when there is not. Its inner end stays at least `_curl_min_eye(pitch, clearance)` from the centre.
    """
    if room <= 0 or below <= 0 or above <= 0:
        return None
    tighten = pitch / (2.0 * math.pi)
    eye_min = _curl_min_eye(pitch, clearance)
    start = min(max(eye * pitch, eye_min) + turns * pitch, (room + pitch) / 2.0, below, above + pitch / 2.0)
    for _ in range(20):
        sweep = 2.0 * math.pi * min(turns, (start - eye_min) / pitch)
        if sweep < 2.0 * math.pi * CURL_MIN_TURNS:
            return None
        # The width is only about 2 * start - pitch: shrink the start until the true width fits the room.
        outer, inner, outermost = _curl_extent(start, tighten, sweep)
        if outer + lean * inner <= room:
            break
        start -= (outer + lean * inner - room) / 2.0 + 1e-9
    else:
        return None
    stretch_r = max(1.0, min(tall, below / start, above / (start - tighten * math.pi)))
    # Stretched across to fill the room, up to `CURL_MAX_STRETCH`; past that the spiral keeps to the cell
    # edge (its outermost vertex on the side-touch vertex) and a longer stalk reaches the axis.
    stretch_a = min(room / (outer + lean * inner), CURL_MAX_STRETCH)
    return start, tighten, sweep, stretch_r, stretch_a, (room - stretch_a * outer) / lean, outermost


def _curl_min_eye(pitch: float, clearance: float) -> float:
    """
    The least distance from the centre the inner end may have. Consecutive turns cross a ray from the centre a
    pitch apart, but slant to it at `atan(tighten / r)`, so their true distance apart is about `pitch * cos` of
    that angle, smallest at the eye: `r >= tighten / sqrt((pitch / clearance)^2 - 1)` keeps it at least the
    clearance, with `CURL_EYE_SLACK` for the curvature there.
    """
    tighten = pitch / (2.0 * math.pi)
    return max(CURL_MIN_EYE_PX, CURL_EYE_SLACK * tighten / math.sqrt((pitch / clearance) ** 2 - 1.0))


def _curl_offsets(layout: CurlLayout, t: float) -> Tuple[float, float]:
    """The spiral's px offsets from its centre at sweep angle `t` (0 at its bottom, then up the outer side)."""
    radius = layout.start_radius - layout.tighten * t
    return (layout.stretch_radial * radius * math.cos(math.pi - t),
            layout.stretch_angular * radius * math.sin(math.pi - t))


def _curl_vector(context: MotifContext, layout: CurlLayout) -> List[CellPoint]:
    """The right spiral's open vector: stalk, spiral and connector, ending on its own earlier ink."""
    def point(x: float, y: float) -> CellPoint:
        return context.to_cell(_curl_page(context, layout, x, y))

    count = max(8, int(math.ceil(layout.sweep / (2.0 * math.pi) * CURL_STEPS_PER_TURN)))
    landing_angle = layout.sweep - 2.0 * math.pi  # the earlier turn the inner end lands on
    angles = sorted({layout.sweep * k / count for k in range(count + 1)} | {layout.outermost, landing_angle})
    spiral = [point(*_curl_offsets(layout, t)) for t in angles]
    if layout.touch is not None:
        spiral[angles.index(layout.outermost)] = CellPoint(layout.touch, context.angular_limits)

    stalk_at = _curl_stalk(layout)
    stalk = [point(*stalk_at(k / CURL_STALK_STEPS)) for k in range(CURL_STALK_STEPS)]
    stalk[0] = CellPoint(stalk[0].radial, 0.0)
    landing = spiral[angles.index(landing_angle)]
    # The stalk stops a sample short of the spiral's start, which the spiral already carries.
    return stalk + spiral + [landing]


def generate_curl(context: MotifContext) -> MotifInstance:
    right = _curl_in_slot(context) if context.slot else _curl_base(context)
    base = right[0]
    # A base's own reach ends are never drawn: this one marks the curl as an open motif hanging from its base,
    # whose contact with the structure comes from the ring (side touch, or a stem the composer adds).
    reach = ReachEnd(point=base, direction="inward", max_length_px=context.ring_depth, style="straight")
    return build_instance(context, [SmartVector(right), SmartVector(mirror_points(right))],
                          reach_ends=[reach], base_point=base)


def _curl_base(context: MotifContext) -> List[CellPoint]:
    """The right spiral of a base curl, which must keep inside its radial and angular limits."""
    right = _curl_vector(context, curl_layout(context))
    low, high = context.radial_limits
    if (min(p.radial for p in right) < max(low, 0.0) - 1e-9
            or max(p.radial for p in right) > high + 1e-9
            or max(p.angular for p in right) > context.angular_limits + 1e-12):
        raise MotifError("curl does not fit its cell")
    return right


def _curl_in_slot(context: MotifContext) -> List[CellPoint]:
    """The right spiral laid out in the slot's box and shrunk about its middle until both lie inside the slot."""
    box = fit_slot_box(context, "curl")
    draws = _curl_draws(context.rng)
    slot = Polygon([(p.angular, p.radial) for p in context.slot])
    mid = box.radial_mid
    scale = 1.0
    while scale >= MIN_FIT_SCALE:
        floor, ceiling = mid + (box.radial_min - mid) * scale, mid + (box.radial_max - mid) * scale
        try:
            right = _curl_vector(context, curl_layout(
                context, draws, (floor, ceiling, context.angular_to_px(box.half_width, mid) * scale)))
        except MotifError:
            break
        if all(slot.contains(LineString([(side * p.angular, p.radial) for p in right])) for side in (1, -1)):
            return right
        scale *= SHRINK_FACTOR
    raise MotifError("curl does not fit slot")


SCALLOP_STEPS = 24
# Each step toward the base radial keeps this share of the lobe's height.
SCALLOP_SHRINK = 0.9
SCALLOP_MAX_SHRINKS = 100


def _scallop_lobe(context: MotifContext, base: float, apex: float) -> List[CellPoint]:
    """
    The circle through the seam ends `(base, +/-1)` and the apex `(apex, 0)`, built in page pixels so it is
    round on the page, sampled from the left end through the apex to the right end and mapped back into
    cell space. In the unturned cell the ends sit at radius Rb, angle +/-a and the apex at radius Ra, angle 0,
    so the centre lies on the axis at c = (Ra^2 - Rb^2) / (2 (Ra - Rb cos a)). The ends and apex are pinned
    exactly, so neighbouring cells meet at the same seam point.
    """
    half = math.radians(context.half_angle)
    rb, ra = context.radius_at(base), context.radius_at(apex)
    denominator = ra - rb * math.cos(half)
    if abs(denominator) < 1e-9 * rb:
        # The three points are collinear (an inward apex exactly on the chord): nudge it off the line.
        ra -= 1e-6 * rb
        denominator = ra - rb * math.cos(half)
    centre = (ra * ra - rb * rb) / (2.0 * denominator)
    radius = abs(ra - centre)
    start = math.atan2(rb * math.sin(half), rb * math.cos(half) - centre)  # the +a end, in (0, pi)
    # The apex is at circle angle 0 when it lies beyond the centre, else at pi.
    end = -start if ra > centre else 2.0 * math.pi - start
    cx, cy = context.center
    points = []
    for index in range(SCALLOP_STEPS + 1):
        theta = start + (end - start) * index / SCALLOP_STEPS
        points.append(context.to_cell((cx + centre + radius * math.cos(theta), cy + radius * math.sin(theta))))
    points.reverse()  # left end first
    points[0], points[-1] = CellPoint(base, -1.0), CellPoint(base, 1.0)
    points[SCALLOP_STEPS // 2] = CellPoint(apex, 0.0)
    return points


def generate_scallop(context: MotifContext) -> MotifInstance:
    require_full_budget(context, "scallop")
    ring = context.ring_rng
    # Every seam-deciding value comes from the ring stream, so every cell of the ring draws the same lobe.
    base = ring.uniform(0.3, 0.5)
    height = ring.uniform(0.25, 0.45)
    outward = ring.random() < 0.5

    low, high = context.radial_limits
    base = max(low, min(high, base))
    apex = min(high, base + height) if outward else max(low, base - height)
    lobe = _scallop_lobe(context, base, apex)
    # A lobe taller than its cell is wide bellies past the cell edges; lower it until it fits. The shrink
    # depends only on ring-wide values, so every cell of the ring shrinks alike.
    for _ in range(SCALLOP_MAX_SHRINKS):
        if max(abs(point.angular) for point in lobe) <= 1.0 + 1e-9:
            break
        apex = base + (apex - base) * SCALLOP_SHRINK
        lobe = _scallop_lobe(context, base, apex)
    return build_instance(context, [SmartVector(lobe)], seams=True)


STEM_STYLES = ["bow", "s", "wavy"]
STEM_STYLE_WEIGHTS = [2, 2, 1]


def generate_stem(context: MotifContext) -> MotifInstance:
    reach = ReachEnd(
        point=CellPoint(0.0, 0.0),
        direction="inward",
        max_length_px=context.ring_depth * 0.9,
        # A stem is never drawn straight by choice (spec 7.2); the resolver flattens it only to keep clear of ink.
        style=context.rng.choices(STEM_STYLES, weights=STEM_STYLE_WEIGHTS)[0],
    )
    return build_instance(context, [], reach_ends=[reach], base_point=CellPoint(0.0, 0.0))


BOTANICAL_MOTIFS: List[Dict] = [
    {
        "name": "petal",
        "category": "botanical",
        "generator": generate_petal,
        "positions": ["centre", "divider"],
        "roles": ["base", "slot", "back"],
        "touch": True,
        "side_touch_heights": ("base", "mid"),
        "seams": False,
        "embellishments": ("echo", "veins", "fan", "dot"),
        "spans_cell": False,
        "min_cell_width_px": 14.0,
        "min_ring_depth_px": 18.0,
        "max_overflow_inward": 0.5,
        "max_overflow_outward": 0.3,
        "slot_estimate": (0.5, 0.5),
    },
    {
        "name": "leaf",
        "category": "botanical",
        "generator": generate_leaf,
        "positions": ["centre"],
        "roles": ["base", "slot", "back"],
        "touch": True,
        "side_touch_heights": ("base", "mid"),
        "seams": False,
        "embellishments": ("echo", "veins"),
        "spans_cell": False,
        "min_cell_width_px": 14.0,
        "min_ring_depth_px": 20.0,
        "max_overflow_inward": 0.0,
        "max_overflow_outward": 0.2,
        "slot_estimate": None,
    },
    {
        "name": "teardrop",
        "category": "botanical",
        "generator": generate_teardrop,
        "positions": ["centre", "divider"],
        "roles": ["base", "slot", "back"],
        "touch": True,
        "side_touch_heights": ("base", "mid"),
        "seams": False,
        "embellishments": ("echo", "dot"),
        "spans_cell": False,
        "min_cell_width_px": 14.0,
        "min_ring_depth_px": 18.0,
        "max_overflow_inward": 0.0,
        "max_overflow_outward": 0.2,
        "slot_estimate": (0.45, 0.45),
    },
    {
        "name": "rounded_petal",
        "category": "botanical",
        "generator": generate_rounded_petal,
        "positions": ["centre", "divider"],
        "roles": ["base", "slot", "back"],
        "touch": True,
        "side_touch_heights": ("base", "mid"),
        "seams": False,
        "embellishments": ("echo", "veins", "fan", "dot"),
        "spans_cell": False,
        "min_cell_width_px": 14.0,
        "min_ring_depth_px": 18.0,
        "max_overflow_inward": 0.0,
        "max_overflow_outward": 0.2,
        "slot_estimate": (0.5, 0.5),
    },
    {
        "name": "heart",
        "category": "botanical",
        "generator": generate_heart,
        "positions": ["centre"],
        "roles": ["base", "slot"],
        "touch": True,
        "side_touch_heights": ("mid",),
        "seams": False,
        "embellishments": ("echo",),
        "spans_cell": False,
        "min_cell_width_px": 14.0,
        "min_ring_depth_px": 18.0,
        "max_overflow_inward": 0.0,
        "max_overflow_outward": 0.2,
        "slot_estimate": (0.45, 0.4),
    },
    {
        "name": "curl",
        "category": "botanical",
        "generator": generate_curl,
        "positions": ["centre"],
        "roles": ["base", "slot"],
        "touch": True,
        "side_touch_heights": ("mid",),
        "seams": False,
        "embellishments": (),
        "spans_cell": False,
        "min_cell_width_px": 28.0,
        "min_ring_depth_px": 24.0,
        # Its turns sit a clearance apart, so it needs room in proportion to the white space: measured over
        # 7,875 cells of rings inside the page (inner radius 80px and up, outer 300px at most), every curl draws
        # once the mid-ring cell is 8.5 clearances wide and the ring 7 deep.
        "min_cell_width_clearances": 8.5,
        "min_ring_depth_clearances": 7.0,
        "max_overflow_inward": 0.0,
        "max_overflow_outward": 0.2,
        "slot_estimate": None,
    },
    {
        "name": "scallop",
        "category": "botanical",
        "generator": generate_scallop,
        "positions": ["divider"],
        "roles": ["base"],
        "touch": True,
        "side_touch_heights": (),
        "seams": True,
        "embellishments": (),
        "spans_cell": True,
        "min_cell_width_px": 12.0,
        "min_ring_depth_px": 16.0,
        "max_overflow_inward": 0.0,
        "max_overflow_outward": 0.0,
        "slot_estimate": None,
    },
    {
        "name": "stem",
        "category": "botanical",
        "generator": generate_stem,
        "positions": ["centre", "divider"],
        "roles": ["attachment"],
        "touch": True,
        "side_touch_heights": (),
        "seams": False,
        "embellishments": (),
        "spans_cell": False,
        "min_cell_width_px": 0.0,
        "min_ring_depth_px": 0.0,
        "max_overflow_inward": 0.0,
        "max_overflow_outward": 0.0,
        "slot_estimate": None,
    },
]
