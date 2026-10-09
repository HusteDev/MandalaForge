"""Botanical motifs."""

from __future__ import annotations

import math
from typing import Dict, List, Optional

from motifs.contract import MotifError, MotifInstance, ReachEnd, build_instance, require_full_budget
from motifs.geometry import (
    CellPoint,
    MotifContext,
    SmartVector,
    mirror_points,
    quad_points,
    side_touch_radial_within,
)
from motifs.slot_fit import fit_inside_slot, fit_slot_box

QUAD_STEPS = 8
# A side-touching leaf's base corners sit at this fraction of the angular budget.
LEAF_SIDE_TOUCH_BASE = 0.6


def _petal_outline(
    base_radial: float,
    tip_radial: float,
    half_width: float,
    waist: float,
    wave: float,
    angular_bound: float,
    widest_radial: Optional[float] = None,
) -> List[CellPoint]:
    """
    One closed, mirror-symmetric outline: right side base to tip, then the left side back.

    `widest_radial` pins the widest vertex there instead of at `waist`, and drops the lower run's
    shoulder bulge so no sample of that run is wider than the widest vertex (side touch).
    """
    base = CellPoint(base_radial, 0.0)
    tip = CellPoint(tip_radial, 0.0)
    if widest_radial is None:
        widest = CellPoint(base.radial + (tip.radial - base.radial) * waist, half_width)
        shoulder = half_width * 1.15
    else:
        widest = CellPoint(widest_radial, half_width)
        shoulder = half_width
    lower = quad_points(
        base,
        CellPoint(base.radial + (widest.radial - base.radial) * 0.5, shoulder),
        widest,
        QUAD_STEPS,
    )
    upper = quad_points(
        widest,
        CellPoint(widest.radial + (tip.radial - widest.radial) * 0.5, half_width * 0.9),
        tip,
        QUAD_STEPS,
    )

    right: List[CellPoint] = []
    for run, samples in enumerate((lower, upper)):
        for index, point in enumerate(samples):
            if run == 1 and index == 0:
                continue  # the widest vertex already closes the lower run
            angular = point.angular
            if 0 < index < QUAD_STEPS:
                if wave > 0:
                    t = (run * QUAD_STEPS + index) / (2 * QUAD_STEPS)
                    angular += wave * math.sin(3 * math.pi * t)
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
    waist = rng.uniform(0.35, 0.6)
    wave = rng.uniform(0.0, context.complexity * 0.06)

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
            return _petal_outline(
                centre + (base_radial - centre) * scale,
                centre + (tip_radial - centre) * scale,
                half_width * scale,
                waist,
                wave,
                angular_bound * scale,
            )

        outline = fit_inside_slot(context, "petal", build)
    else:
        base_radial = max(low, -dip)
        tip_radial = min(high, length)
        # Side touch (spec 13.2): full angular budget, widest vertex exactly on the shared side vertex.
        touch = side_touch_radial_within(context, base_radial, tip_radial)
        if touch is not None:
            half_width = context.angular_limits
        outline = _petal_outline(
            base_radial, tip_radial, half_width, waist, wave, context.angular_limits, widest_radial=touch
        )
    return build_instance(context, [SmartVector(outline, closed=True)], slot_outline=outline)


def _leaf_vectors(
    base_radial: float,
    apex_radial: float,
    half_width: float,
    roundness: float,
    side_radial: Optional[float] = None,
) -> List[SmartVector]:
    """
    A closed leaf outline plus a midrib whose ends are outline vertices.

    With `side_radial`, `half_width` is the angular budget: the base corners sit at
    LEAF_SIDE_TOUCH_BASE of it and each edge runs corner, side vertex `(side_radial, half_width)`,
    apex, in two curves whose controls are no wider than the budget, so neither run is wider either.
    """
    middle = (base_radial + apex_radial) / 2.0
    apex = CellPoint(apex_radial, 0.0)
    if side_radial is None:
        right = quad_points(
            CellPoint(base_radial, half_width), CellPoint(middle, half_width * roundness), apex, QUAD_STEPS
        )
    else:
        corner = CellPoint(base_radial, half_width * LEAF_SIDE_TOUCH_BASE)
        side = CellPoint(side_radial, half_width)
        lower = quad_points(
            corner, CellPoint(base_radial + (side_radial - base_radial) * 0.5, half_width), side, QUAD_STEPS
        )
        upper = quad_points(
            side,
            CellPoint(side_radial + (apex_radial - side_radial) * 0.5, half_width * min(1.0, roundness)),
            apex,
            QUAD_STEPS,
        )
        right = lower + upper[1:]
    left = mirror_points(right)[:-1][::-1]
    # The base vertex sits on the straight base edge so the midrib's lower end touches outline ink.
    outline = [CellPoint(base_radial, 0.0), *right, *left]
    midrib = [CellPoint(base_radial, 0.0), apex]
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
    # Ring fill (spec 13.3): the apex reaches the ring boundary or a little past it.
    length = rng.uniform(1.0, 1.2)
    half_width = context.angular_limits * rng.uniform(0.45, 0.85)
    roundness = rng.uniform(0.25, 1.1)

    high = context.radial_limits[1]
    if context.slot:
        box = fit_slot_box(context, "leaf")
        base_radial = box.radial_min
        apex_radial = min(high, box.radial_max)
        if apex_radial <= base_radial:
            raise MotifError("leaf does not fit slot")
        half_width = min(half_width, box.half_width, context.angular_limits)
        centre = (base_radial + apex_radial) / 2.0

        built: List[List[SmartVector]] = []

        def build(scale: float) -> List[CellPoint]:
            built.append(_leaf_vectors(
                centre + (base_radial - centre) * scale,
                centre + (apex_radial - centre) * scale,
                half_width * scale,
                roundness,
            ))
            return built[-1][0].points

        # fit_inside_slot returns on the first outline that fits, so the last one built is the one kept.
        fit_inside_slot(context, "leaf", build)
        vectors = built[-1]
    else:
        apex_radial = min(high, length)
        # Side touch (spec 13.2): the leaf bulges out to the full budget at the shared side vertex.
        touch = side_touch_radial_within(context, 0.0, apex_radial)
        if touch is not None:
            half_width = context.angular_limits
        vectors = _leaf_vectors(0.0, apex_radial, half_width, roundness, side_radial=touch)
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


def generate_stem(context: MotifContext) -> MotifInstance:
    reach = ReachEnd(
        point=CellPoint(0.0, 0.0),
        direction="inward",
        max_length_px=context.ring_depth * 0.9,
        style="wavy" if context.complexity >= 0.6 else "straight",
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
