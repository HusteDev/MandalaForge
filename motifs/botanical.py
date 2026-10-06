"""Botanical motifs."""

from __future__ import annotations

import math
from typing import Dict, List

from motifs.contract import MotifError, MotifInstance, ReachEnd, build_instance
from motifs.geometry import CellPoint, MotifContext, SmartVector, mirror_points, quad_points
from motifs.slot_fit import fit_inside_slot, fit_slot_box

QUAD_STEPS = 8


def _petal_outline(
    base_radial: float,
    tip_radial: float,
    half_width: float,
    waist: float,
    wave: float,
    angular_bound: float,
) -> List[CellPoint]:
    """One closed, mirror-symmetric outline: right side base to tip, then the left side back."""
    base = CellPoint(base_radial, 0.0)
    tip = CellPoint(tip_radial, 0.0)
    widest = CellPoint(base.radial + (tip.radial - base.radial) * waist, half_width)
    lower = quad_points(
        base,
        CellPoint(base.radial + (widest.radial - base.radial) * 0.5, half_width * 1.15),
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
    length = rng.uniform(0.75, 1.25)
    dip = rng.uniform(0.0, 0.25)
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
        outline = _petal_outline(
            max(low, -dip), min(high, length), half_width, waist, wave, context.angular_limits
        )
    return build_instance(context, [SmartVector(outline, closed=True)], slot_outline=outline)


def _leaf_vectors(base_radial: float, apex_radial: float, half_width: float, roundness: float) -> List[SmartVector]:
    """A closed leaf outline plus a midrib whose ends are outline vertices."""
    middle = (base_radial + apex_radial) / 2.0
    apex = CellPoint(apex_radial, 0.0)
    right = quad_points(
        CellPoint(base_radial, half_width), CellPoint(middle, half_width * roundness), apex, QUAD_STEPS
    )
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
    length = rng.uniform(0.85, 1.15)
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
        vectors = _leaf_vectors(0.0, min(high, length), half_width, roundness)
    vectors = _drop_thin_midrib(context, vectors)
    return build_instance(context, vectors, base_point=vectors[0].points[0])


def generate_scallop(context: MotifContext) -> MotifInstance:
    rng = context.rng
    top = rng.uniform(0.5, 0.6)
    dip = rng.uniform(0.1, 0.3)

    low, high = context.radial_limits
    limit = context.angular_limits
    top = min(high, top)
    side_bottom = max(low, top - 0.2)
    lowest = max(low, -dip)
    # The curve's midpoint is (start + 2 * control + end) / 4, so this control lands it on `lowest`.
    control = CellPoint(2.0 * lowest - side_bottom, 0.0)
    arc = quad_points(CellPoint(side_bottom, limit), control, CellPoint(side_bottom, -limit), QUAD_STEPS)
    outline = [CellPoint(top, -limit), CellPoint(top, limit), *arc]
    return build_instance(context, [SmartVector(outline, closed=True)])


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
        "spans_cell": False,
        "min_cell_width_px": 14.0,
        "min_ring_depth_px": 18.0,
        "max_overflow_inward": 0.25,
        "max_overflow_outward": 0.25,
        "slot_estimate": (0.5, 0.5),
    },
    {
        "name": "leaf",
        "category": "botanical",
        "generator": generate_leaf,
        "positions": ["centre"],
        "roles": ["base", "slot"],
        "touch": True,
        "spans_cell": False,
        "min_cell_width_px": 14.0,
        "min_ring_depth_px": 20.0,
        "max_overflow_inward": 0.0,
        "max_overflow_outward": 0.15,
        "slot_estimate": None,
    },
    {
        "name": "scallop",
        "category": "botanical",
        "generator": generate_scallop,
        "positions": ["divider"],
        "roles": ["base"],
        "touch": True,
        "spans_cell": True,
        "min_cell_width_px": 12.0,
        "min_ring_depth_px": 16.0,
        "max_overflow_inward": 0.3,
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
        "spans_cell": False,
        "min_cell_width_px": 0.0,
        "min_ring_depth_px": 0.0,
        "max_overflow_inward": 0.0,
        "max_overflow_outward": 0.0,
        "slot_estimate": None,
    },
]
