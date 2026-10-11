"""Botanical motifs."""

from __future__ import annotations

import math
from typing import Dict, List, Optional

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
)
from motifs.slot_fit import fit_inside_slot, fit_slot_box

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
    length = rng.uniform(0.95, 1.3)
    dip = rng.uniform(0.0, 0.5)
    half_width = context.angular_limits * rng.uniform(0.55, 0.95)
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
    length = rng.uniform(1.0, 1.2)
    half_width = context.angular_limits * rng.uniform(0.45, 0.85)
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
    length = rng.uniform(*FILL_LENGTH_RANGE)
    half_width = context.angular_limits * rng.uniform(*TEARDROP_WIDTH_RANGE)
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
    length = rng.uniform(*FILL_LENGTH_RANGE)
    half_width = context.angular_limits * rng.uniform(0.55, 0.95)
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
