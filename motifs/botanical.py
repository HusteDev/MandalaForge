"""Botanical motifs."""

from __future__ import annotations

import math
from typing import Dict, List, Optional

from motifs.contract import MotifError, MotifInstance, ReachEnd, build_instance, require_full_budget
from motifs.geometry import (
    CellPoint,
    MotifContext,
    SmartVector,
    cubic_points,
    mirror_points,
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
    else:
        base_radial = max(low, -dip)
        tip_radial = min(high, length)
        # Side touch (spec 13.2, 3.3): the belly is the shared side vertex, at the full angular budget.
        touch = side_touch_radial_within(context, base_radial, tip_radial)
        if touch is not None:
            half_width = context.angular_limits
        points = outline(base_radial, tip_radial, half_width, context.angular_limits, belly_radial=touch)
    return build_instance(context, [SmartVector(points, closed=True)], slot_outline=points)


def _leaf_vectors(
    base_radial: float,
    apex_radial: float,
    belly_radial: float,
    half_width: float,
    roundness: float,
    angular_bound: float,
) -> List[SmartVector]:
    """
    A closed leaf outline, pointed at the base and curved to a point at the apex, plus a midrib whose ends
    are the outline's base and apex vertices. The belly vertex `(belly_radial, half_width)` is the widest.
    """
    outline = _pointed_outline(
        base_radial, apex_radial, belly_radial, half_width,
        LEAF_BASE_REACH, LEAF_BASE_SPREAD, LEAF_APEX_HANDLE, roundness, 0.0, angular_bound,
    )
    midrib = [outline[0], CellPoint(apex_radial, 0.0)]
    return [SmartVector(outline, closed=True), SmartVector(midrib)]


def _drop_thin_midrib(context: MotifContext, vectors: List[SmartVector]) -> List[SmartVector]:
    """
    Keep the midrib only when each half it makes is colourable: at the leaf's
    widest point a half is as wide as that point's angular offset.
    """
    widest = max(vectors[0].points, key=lambda point: abs(point.angular))
    if context.angular_to_px(widest.angular, widest.radial) >= context.min_white_space:
        return vectors
    return vectors[:1]


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

        built: List[List[SmartVector]] = []

        def build(scale: float) -> List[CellPoint]:
            low_end = centre + (base_radial - centre) * scale
            high_end = centre + (apex_radial - centre) * scale
            built.append(_leaf_vectors(
                low_end, high_end, low_end + (high_end - low_end) * belly,
                half_width * scale, roundness, angular_bound * scale,
            ))
            return built[-1][0].points

        # fit_inside_slot returns on the first outline that fits, so the last one built is the one kept.
        fit_inside_slot(context, "leaf", build)
        vectors = built[-1]
    else:
        apex_radial = min(high, length)
        # Side touch (spec 13.2, 3.3): the belly is the shared side vertex, at the full angular budget.
        touch = side_touch_radial_within(context, 0.0, apex_radial)
        if touch is not None:
            half_width = context.angular_limits
        belly_radial = touch if touch is not None else apex_radial * belly
        vectors = _leaf_vectors(0.0, apex_radial, belly_radial, half_width, roundness, context.angular_limits)
    vectors = _drop_thin_midrib(context, vectors)
    return build_instance(context, vectors, base_point=vectors[0].points[0])


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
        "roles": ["base", "slot"],
        "touch": True,
        "side_touch_heights": ("base", "mid"),
        "seams": False,
        "embellishments": (),
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
        "roles": ["base", "slot"],
        "touch": True,
        "side_touch_heights": ("base", "mid"),
        "seams": False,
        "embellishments": (),
        "spans_cell": False,
        "min_cell_width_px": 14.0,
        "min_ring_depth_px": 20.0,
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
