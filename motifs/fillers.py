"""
Fillers (motif roadmap Phase A): small motifs for the V gaps between side-touching petals and for slots.

The V-gap fillers are divider bases that side-touch, as `bead` does: in `both` mode the divider position is
the gap between two centre motifs, and the ring's shared side-touch vertices tie the filler to its
neighbours, so a filler needs no contact of its own.
"""

from __future__ import annotations

import math
from typing import Dict, List, Tuple

from shapely.geometry import LineString, Point, Polygon

from motifs.contract import Anatomy, MotifError, MotifInstance, build_instance
from motifs.embellish import _faces_hold_pen, apply_embellishments, holds_pen
from motifs.geometry import (
    CellPoint, MotifContext, SmartVector, cubic_points, mirror_points, quad_points,
)
from motifs.page_shapes import page_offsets, polar_offsets
from motifs.slot_fit import fit_inside_slot, fit_slot_box

FILL_STEPS = 10

# Crescent: a cup with two horns. Its widest vertices sit on the outer side of the horns, where the outline
# runs along the radial (the side-touch vertices when the ring side-touches); above them each horn rises to a
# sharp tip and turns down into the inner curve. Drawn as shares of the room the cell gives it.
CRESCENT_TOUCH_RANGE = (0.3, 0.55)  # without side touch, the radial of the widest vertices
CRESCENT_WIDTH_RANGE = (0.8, 0.95)  # without side touch, the widest vertices' share of the budget
CRESCENT_CUP_RANGE = (0.15, 0.35)  # how far the bottom sits below the widest vertices, in cell units
CRESCENT_HORN_RANGE = (0.25, 0.5)  # how far the horn tips rise above the widest vertices, in cell units
CRESCENT_TIP_IN = 0.7  # the horn tip's angular as a share of the half-width
CRESCENT_BODY_RANGE = (1.2, 1.6)  # the body's thickness at the bottom and sides, in clearances
CRESCENT_MOUTH_SHARE = 0.35  # the least inner half-width, as a share of the half-width
# The highest the horns may rise, as a share of the room below the radial ceiling, so the tips stay inside it.
CRESCENT_CEILING_SHARE = 0.98


def _crescent_right(bottom: float, touch: float, tip: float, half_width: float,
                    inner_bottom: float, inner_half_width: float) -> List[CellPoint]:
    """
    The right half of a crescent, from the outer bottom on the axis to the inner bottom on the axis: the
    outer curve up to the widest vertex `(touch, half_width)` (arriving along the radial), on up the horn to
    its tip, then the inner curve back down to `(inner_bottom, 0)`.
    """
    rise, horn = touch - bottom, tip - touch
    tip_point = CellPoint(tip, half_width * CRESCENT_TIP_IN)
    outer = cubic_points(
        CellPoint(bottom, 0.0), CellPoint(bottom, half_width * 0.6),
        CellPoint(touch - rise * 0.45, half_width), CellPoint(touch, half_width), FILL_STEPS,
    )
    horn_side = cubic_points(
        CellPoint(touch, half_width), CellPoint(touch + horn * 0.45, half_width),
        CellPoint(tip - horn * 0.15, half_width * (1.0 + CRESCENT_TIP_IN) / 2.0), tip_point, FILL_STEPS,
    )
    inner = cubic_points(
        tip_point, CellPoint(tip - horn * 0.5, inner_half_width),
        CellPoint(inner_bottom, inner_half_width * 0.6), CellPoint(inner_bottom, 0.0), 2 * FILL_STEPS,
    )
    return outer + horn_side[1:] + inner[1:]


def _closed_from_axis_run(right: List[CellPoint]) -> List[CellPoint]:
    """A closed mirror-symmetric outline from a right half that starts and ends on the axis."""
    return right + mirror_points(right)[::-1][1:-1]


def crescent_outline(context: MotifContext, bottom: float, touch: float, tip: float, half_width: float,
                     body_clearances: float) -> List[CellPoint]:
    """
    A closed crescent with its outer bottom at `bottom`, its widest vertices at `(touch, ±half_width)` and
    its horn tips at `tip`, the body `body_clearances` clearances thick at the bottom and at the sides.
    """
    body_px = context.clearance_px() * body_clearances
    inner_bottom = min(bottom + context.px_to_radial(body_px), (touch + tip) / 2.0)
    # A body too thick for the width would close the mouth; the mouth keeps a share of the width instead.
    inner_half_width = max(half_width - context.px_to_angular(body_px, touch), half_width * CRESCENT_MOUTH_SHARE)
    return _closed_from_axis_run(_crescent_right(bottom, touch, tip, half_width, inner_bottom, inner_half_width))


def _crescent_draws(context: MotifContext) -> Dict[str, float]:
    rng = context.rng
    return {
        "touch": rng.uniform(*CRESCENT_TOUCH_RANGE),
        "width": rng.uniform(*CRESCENT_WIDTH_RANGE),
        "cup": rng.uniform(*CRESCENT_CUP_RANGE),
        "horn": rng.uniform(*CRESCENT_HORN_RANGE),
        "body": rng.uniform(*CRESCENT_BODY_RANGE),
    }


def generate_crescent(context: MotifContext) -> MotifInstance:
    # Every parameter is drawn before any limit is applied (determinism and monotone limits).
    draws = _crescent_draws(context)
    low, high = context.radial_limits
    if context.slot:
        box = fit_slot_box(context, "crescent")
        height = box.radial_max - box.radial_min
        mid = box.radial_mid
        cup_share = draws["cup"] / (draws["cup"] + draws["horn"])

        def build(scale: float) -> List[CellPoint]:
            bottom = mid - height * scale / 2.0
            return crescent_outline(context, bottom, bottom + height * scale * cup_share, mid + height * scale / 2.0,
                                    box.half_width * scale, draws["body"])

        try:
            points = fit_inside_slot(context, "crescent", build)
        except MotifError as error:
            raise MotifError(f"crescent does not fit slot: {error}") from error
    else:
        floor = max(low, 0.0)
        if context.side_touch_radial is not None:
            touch, half_width = context.side_touch_radial, context.angular_limits
        else:
            touch, half_width = draws["touch"], context.angular_limits * draws["width"]
        bottom = max(floor, touch - draws["cup"])
        tip = min(touch + draws["horn"], touch + (high - touch) * CRESCENT_CEILING_SHARE)
        if not floor <= bottom < touch < tip:
            raise MotifError("crescent does not fit its radial limits")
        points = crescent_outline(context, bottom, touch, tip, half_width, draws["body"])
    if not holds_pen(context, points):
        raise MotifError("crescent is too thin to colour")
    anatomy = Anatomy(base=points[0], tip=points[len(points) // 2], outline=0)
    result = apply_embellishments(context, [SmartVector(points, closed=True)], anatomy, None)
    return build_instance(context, result.vectors, anatomy=anatomy, dropped_embellishments=result.dropped)


# Kite: four vertices joined by gently inward-bowed edges. Its side vertices are where the outline runs along
# the radial (the side-touch vertices when the ring side-touches); bottom and top are sharp tips on the axis.
# The bottom tip's radial above the clearance it keeps over the ring floor. A sharp tip on the floor would meet
# the inner ring's overflow tip to tip, and with no inward overflow of its own the kite could not give way.
KITE_BASE_RANGE = (0.0, 0.05)
KITE_LENGTH_RANGE = (0.9, 1.15)  # the top tip's radial, before the radial ceiling
KITE_SIDE_RANGE = (0.3, 0.45)  # without side touch, the side vertices' share of the way from bottom to top
KITE_WIDTH_SHARE = 0.85  # without side touch, the side vertices' share of the angular budget
KITE_BOW_RANGE = (0.0, 0.2)  # how far each edge bows in, as a share of the half-width
KITE_SIDE_GAP = 0.05  # the least radial between the bottom tip and the side vertices
KITE_TOP_GAP = 0.1  # the least radial between the side vertices and the top tip


def kite_outline(bottom: float, side: float, top: float, half_width: float, bow: float) -> List[CellPoint]:
    """A closed kite from `(bottom, 0)` through `(side, ±half_width)` to `(top, 0)`, its right half first."""
    lower, upper = side - bottom, top - side
    inward = half_width * (0.5 - bow)
    right = cubic_points(
        CellPoint(bottom, 0.0), CellPoint(bottom + lower * 0.5, inward),
        CellPoint(side - lower * 0.25, half_width), CellPoint(side, half_width), FILL_STEPS,
    ) + cubic_points(
        CellPoint(side, half_width), CellPoint(side + upper * 0.25, half_width),
        CellPoint(side + upper * 0.5, inward), CellPoint(top, 0.0), FILL_STEPS,
    )[1:]
    return _closed_from_axis_run(right)


def generate_kite(context: MotifContext) -> MotifInstance:
    rng = context.rng
    # Every parameter is drawn before any limit is applied (determinism and monotone limits).
    base, length = rng.uniform(*KITE_BASE_RANGE), rng.uniform(*KITE_LENGTH_RANGE)
    free_side, bow = rng.uniform(*KITE_SIDE_RANGE), rng.uniform(*KITE_BOW_RANGE)
    low, high = context.radial_limits
    top = min(length, high)
    touch = context.side_touch_radial
    if touch is not None and low < touch < high:
        side, half_width = touch, context.angular_limits
    else:
        side, half_width = None, context.angular_limits * KITE_WIDTH_SHARE
    bottom = max(low, 0.0) + context.px_to_radial(context.clearance_px()) + base
    if side is None:
        side = bottom + (top - bottom) * free_side
    if side - bottom < KITE_SIDE_GAP or top - side < KITE_TOP_GAP:
        raise MotifError("kite does not fit its radial limits")
    points = kite_outline(bottom, side, top, half_width, bow)
    if not holds_pen(context, points):
        raise MotifError("kite is too thin to colour")
    anatomy = Anatomy(base=points[0], tip=points[2 * FILL_STEPS], outline=0)
    result = apply_embellishments(context, [SmartVector(points, closed=True)], anatomy, points)
    return build_instance(
        context, result.vectors, slot_outline=result.slot_outline, anatomy=anatomy,
        dropped_embellishments=result.dropped, slot_outline_weight=result.slot_outline_weight,
    )


# Stamen: a small cup whose widest vertices side-touch, a stem up the axis from the cup's inner bottom vertex,
# and a ball (round on the page) whose bottom vertex is the stem's end. From complexity 0.5, two side stems from
# the same root vertex lean out to smaller balls when they keep clear of everything; else they are left out.
STAMEN_CUP_TOUCH_RANGE = (0.1, 0.3)  # without side touch, the cup's widest vertices' radial
STAMEN_CUP_WIDTH_RANGE = (0.6, 0.85)  # without side touch, the cup's share of the angular budget
STAMEN_CUP_RANGE = (0.08, 0.18)  # how far the cup's bottom sits below its widest vertices
STAMEN_HORN_RANGE = (0.06, 0.14)  # how far the cup's horns rise above its widest vertices
STAMEN_BODY = 1.2  # the cup body's thickness, in clearances
STAMEN_LENGTH_RANGE = (0.75, 1.1)  # the ball centre's radial, before the radial ceiling
STAMEN_BALL_RANGE = (0.35, 0.6)  # the ball's diameter as a share of the budget's width at its radial
STAMEN_BALL_MIN = 1.5  # the smallest ball diameter, in min_white_space
STAMEN_BALL_DEPTH_SHARE = 0.35  # the largest ball diameter, as a share of the ring depth
STAMEN_BOW_RANGE = (-0.08, 0.08)  # the stem's sideways bow, as a share of the half-width
STAMEN_SIDE_COMPLEXITY = 0.5  # the complexity from which side stems are tried
STAMEN_SIDE_BALL = 0.7  # a side ball's size as a share of the centre ball's
STAMEN_SIDE_HEIGHT_RANGE = (0.45, 0.7)  # a side ball's radial as a share of the way from root to centre ball
STAMEN_SIDE_SPREAD_RANGE = (0.85, 1.0)  # a side ball's angular as a share of the room beside the centre ball
STAMEN_SIDE_BOW = 0.35  # a side stem's control angular as a share of its ball's: below 0.5 it rises before leaning out
STAMEN_ROOT_DISC = 2.0  # the root's touch disc radius, in clearances: side stems may meet other ink inside it
BALL_STEPS = 36


def _page_polygon(context: MotifContext, points: List[CellPoint]) -> Polygon:
    return Polygon(context.polyline(SmartVector(list(points), closed=True)))


def _page_line(context: MotifContext, points: List[CellPoint]) -> LineString:
    return LineString(context.polyline(SmartVector(list(points))))


def _ball(context: MotifContext, centre: CellPoint, radius_px: float) -> Tuple[List[CellPoint], CellPoint]:
    """A ball round on the page and its bottom vertex."""
    points = page_offsets(context, centre, polar_offsets(
        [(radius_px, 2.0 * math.pi * index / BALL_STEPS) for index in range(BALL_STEPS)]))
    bottom = CellPoint(points[BALL_STEPS // 2].radial, centre.angular)
    points[BALL_STEPS // 2] = bottom
    return points, bottom


def _stamen_draws(context: MotifContext) -> Dict[str, float]:
    rng = context.rng
    return {
        "touch": rng.uniform(*STAMEN_CUP_TOUCH_RANGE), "width": rng.uniform(*STAMEN_CUP_WIDTH_RANGE),
        "cup": rng.uniform(*STAMEN_CUP_RANGE), "horn": rng.uniform(*STAMEN_HORN_RANGE),
        "length": rng.uniform(*STAMEN_LENGTH_RANGE), "ball": rng.uniform(*STAMEN_BALL_RANGE),
        "bow": rng.uniform(*STAMEN_BOW_RANGE), "side_height": rng.uniform(*STAMEN_SIDE_HEIGHT_RANGE),
        "side_spread": rng.uniform(*STAMEN_SIDE_SPREAD_RANGE),
    }


def _side_stems(context: MotifContext, draws: Dict[str, float], root: CellPoint, ball_centre: CellPoint,
                ball_px: float, others: List[SmartVector]) -> List[SmartVector]:
    """The two mirrored side stems and their balls, or none when either would come within a clearance of ink."""
    low, high = context.radial_limits
    radius_px = ball_px * STAMEN_SIDE_BALL
    radial = root.radial + (ball_centre.radial - root.radial) * draws["side_height"]
    room = context.angular_limits - context.px_to_angular(radius_px, radial)
    angular = room * draws["side_spread"]
    if room <= 0.0 or radial - context.px_to_radial(radius_px) <= root.radial:
        return []
    ball, bottom = _ball(context, CellPoint(radial, angular), radius_px)
    rise = bottom.radial - root.radial
    stem = quad_points(root, CellPoint(root.radial + rise * 0.5, bottom.angular * STAMEN_SIDE_BOW), bottom, FILL_STEPS)
    right = [SmartVector(stem), SmartVector(ball, closed=True)]
    pair = right + [SmartVector(mirror_points(v.points), closed=v.closed) for v in right]
    every = [p for v in pair for p in v.points]
    if (max(abs(p.angular) for p in every) > context.angular_limits
            or min(p.radial for p in every) < low or max(p.radial for p in every) > high
            or not holds_pen(context, ball)):
        return []
    clearance = context.clearance_px()
    root_disc = Point(context.to_cartesian(root)).buffer(clearance * STAMEN_ROOT_DISC)
    shapes = [
        (_page_polygon(context, v.points).exterior if v.closed else _page_line(context, v.points))
        for v in others + pair
    ]
    stems = {k for k, v in enumerate(others + pair) if not v.closed and v.points[0] == root}
    shared_root = stems | {0}  # the cup holds the root vertex too
    count = len(others)
    for k in range(count, len(shapes)):
        partner = k + 1 if (k - count) % 2 == 0 else k - 1  # a stem and its own ball meet at the bottom vertex
        for j, other in enumerate(shapes):
            if j == k or j == partner:
                continue
            mine = shapes[k]
            if k in shared_root and j in shared_root:
                # Lines leaving the same root vertex meet there; they keep apart only outside its touch disc.
                mine, other = mine.difference(root_disc), other.difference(root_disc)
            if mine.distance(other) < clearance - 1e-9:
                return []
    return pair


def generate_stamen(context: MotifContext) -> MotifInstance:
    # Every parameter is drawn before any limit is applied (determinism and monotone limits).
    draws = _stamen_draws(context)
    low, high = context.radial_limits
    floor = max(low, 0.0)
    if context.side_touch_radial is not None and not context.slot:
        touch, half_width = context.side_touch_radial, context.angular_limits
    else:
        touch, half_width = draws["touch"], context.angular_limits * draws["width"]
    # The ball goes in first, as high as the ceiling lets it; the cup's horns stop a clearance below it.
    width_px = context.angular_to_px(2.0 * context.angular_limits, draws["length"])
    smallest_px = context.min_white_space * STAMEN_BALL_MIN / 2.0
    drawn_px = max(smallest_px * 2.0, min(width_px * draws["ball"], context.ring_depth * STAMEN_BALL_DEPTH_SHARE)) / 2.0
    clearance = context.clearance_px()
    bottom = max(floor, touch - draws["cup"])
    # A cup set high leaves the ball less room: the smallest ball, against the ceiling, is tried before giving up.
    for ball_px, length in ((drawn_px, draws["length"]), (smallest_px, high)):
        ball_px = min(ball_px, context.angular_to_px(context.angular_limits, length) * 0.9)
        centre_radial = min(length, high - context.px_to_radial(ball_px))
        ball, ball_bottom = _ball(context, CellPoint(centre_radial, 0.0), ball_px)
        tip = min(touch + draws["horn"], ball_bottom.radial - context.px_to_radial(clearance))
        if tip > touch:
            break
    if not floor <= bottom < touch < tip:
        raise MotifError("stamen does not fit its radial limits")
    cup = crescent_outline(context, bottom, touch, tip, half_width, STAMEN_BODY)
    root = cup[len(cup) // 2]
    if ball_bottom.radial <= root.radial or not holds_pen(context, ball):
        raise MotifError("stamen ball does not fit")
    if not holds_pen(context, cup):
        raise MotifError("stamen cup is too thin to colour")
    rise = ball_bottom.radial - root.radial
    stem = quad_points(root, CellPoint(root.radial + rise * 0.5, half_width * draws["bow"]), ball_bottom, FILL_STEPS)
    if _page_polygon(context, ball).exterior.distance(_page_polygon(context, cup).exterior) < clearance:
        raise MotifError("stamen ball is too close to its cup")
    vectors = [SmartVector(cup, closed=True), SmartVector(stem), SmartVector(ball, closed=True)]
    if context.complexity >= STAMEN_SIDE_COMPLEXITY:
        vectors += _side_stems(context, draws, root, CellPoint(centre_radial, 0.0), ball_px, vectors)
    anatomy = Anatomy(base=cup[0], tip=ball[0], outline=0)
    return build_instance(context, vectors, anatomy=anatomy)


# Floret and star: slot sets, laid out round on the page about the slot box's middle and shrunk into the slot.
FLORET_PETALS = (5, 8)  # petal count, inclusive
FLORET_DEPTH_RANGE = (0.25, 0.4)  # how deep the notches cut, as a share of the radius
FLORET_CENTRE_SHARE = (0.25, 0.35)  # the centre circle's radius as a share of the outer radius
FLORET_HALF_LOBE_STEPS = 5  # samples from a lobe tip to the next notch
STAR_TIPS = (5, 8)  # tip count, inclusive
STAR_INNER_RANGE = (0.4, 0.6)  # the inner vertices' radius as a share of the tips'
STAR_BOW_RANGE = (0.0, 0.2)  # how far an edge's middle is pulled in, as a share of the edge
STAR_EDGE_STEPS = 4


def _slot_round_radius(context: MotifContext, name: str):
    """The slot box, its middle and the largest page radius that fits the box."""
    box = fit_slot_box(context, name)
    mid = box.radial_mid
    radius_px = min(context.radial_to_px(box.radial_max - box.radial_min) / 2.0,
                    context.angular_to_px(box.half_width, mid))
    return CellPoint(mid, 0.0), radius_px


def _fit_round(context: MotifContext, name: str, build) -> float:
    """The scale at which `build(scale)`'s outline fits inside the slot (`fit_inside_slot`'s first fit)."""
    scales: List[float] = []

    def recorded(scale: float) -> List[CellPoint]:
        scales.append(scale)
        return build(scale)

    fit_inside_slot(context, name, recorded)
    return scales[-1]


def floret_angles(petals: int) -> List[float]:
    """Sample angles, a lobe tip at every `2*pi*j/petals` and a notch half way between."""
    steps = 2 * petals * FLORET_HALF_LOBE_STEPS
    return [2.0 * math.pi * index / steps for index in range(steps)]


def generate_floret(context: MotifContext) -> MotifInstance:
    rng = context.rng
    # Every parameter is drawn before the slot is measured (determinism).
    petals = rng.randint(*FLORET_PETALS)
    depth = rng.uniform(*FLORET_DEPTH_RANGE)
    centre_share = rng.uniform(*FLORET_CENTRE_SHARE)
    centre, radius_px = _slot_round_radius(context, "floret")
    angles = floret_angles(petals)

    def outline(scale: float) -> List[CellPoint]:
        radius = radius_px * scale
        return page_offsets(context, centre, polar_offsets(
            [(radius * (1.0 - depth + depth * abs(math.cos(petals * theta / 2.0))), theta) for theta in angles]))

    scale = _fit_round(context, "floret", outline)
    points = outline(scale)
    if not holds_pen(context, points):
        raise MotifError("floret does not fit slot: its interior is too small to colour")
    circle = page_offsets(context, centre, polar_offsets([(radius_px * scale * centre_share, t) for t in angles]))
    notches = range(FLORET_HALF_LOBE_STEPS, len(angles), 2 * FLORET_HALF_LOBE_STEPS)
    dividers = [SmartVector([circle[k], points[k]], weight="detail") for k in notches]
    clearance = context.clearance_px("outline", "detail")
    # The fullest variant whose every face holds a pen: dividers dropped first, then the centre circle.
    for vectors in (
        [SmartVector(points, closed=True), SmartVector(circle, closed=True)] + dividers,
        [SmartVector(points, closed=True), SmartVector(circle, closed=True)],
        [SmartVector(points, closed=True)],
    ):
        if _faces_hold_pen(context, vectors, clearance):
            break
    return build_instance(context, vectors)


def star_outline(context: MotifContext, centre: CellPoint, radius_px: float, tips: int, inner: float,
                 bow: float) -> List[CellPoint]:
    """A star with a tip outward at angle 0, its edges straight (`bow` 0) or pulled in at the middle."""
    corners = [(radius_px if index % 2 == 0 else radius_px * inner, math.pi * index / tips)
               for index in range(2 * tips)]
    corners = polar_offsets(corners)
    offsets: List[Tuple[float, float]] = []
    for index, (x0, y0) in enumerate(corners):
        x1, y1 = corners[(index + 1) % len(corners)]
        mx, my = (x0 + x1) / 2.0, (y0 + y1) / 2.0
        pull = bow * math.hypot(x1 - x0, y1 - y0) / max(math.hypot(mx, my), 1e-9)
        cx, cy = mx * (1.0 - pull), my * (1.0 - pull)
        for step in range(STAR_EDGE_STEPS):
            t = step / STAR_EDGE_STEPS
            u = 1.0 - t
            offsets.append((u * u * x0 + 2 * u * t * cx + t * t * x1, u * u * y0 + 2 * u * t * cy + t * t * y1))
    return page_offsets(context, centre, offsets)


def generate_star(context: MotifContext) -> MotifInstance:
    rng = context.rng
    # Every parameter is drawn before the slot is measured (determinism).
    tips = rng.randint(*STAR_TIPS)
    inner = rng.uniform(*STAR_INNER_RANGE)
    bow = rng.uniform(*STAR_BOW_RANGE)
    centre, radius_px = _slot_round_radius(context, "star")
    points = None
    # Bowed edges thin the star; the straight one in the same slot is wider.
    for edge_bow in dict.fromkeys((bow, 0.0)):
        scale = _fit_round(context, "star", lambda s: star_outline(context, centre, radius_px * s, tips, inner, edge_bow))
        points = star_outline(context, centre, radius_px * scale, tips, inner, edge_bow)
        if holds_pen(context, points):
            return build_instance(context, [SmartVector(points, closed=True)])
    raise MotifError("star does not fit slot: its interior is too small to colour")


FILLER_MOTIFS: List[Dict] = [
    {
        "name": "crescent",
        "category": "botanical",
        "generator": generate_crescent,
        "positions": ["divider"],
        "roles": ["base", "slot"],
        "touch": True,
        "side_touch_heights": ("base", "mid"),
        "seams": False,
        "embellishments": (),
        "spans_cell": False,
        "min_cell_width_px": 10.0,
        "min_ring_depth_px": 12.0,
        "max_overflow_inward": 0.0,
        "max_overflow_outward": 0.0,
        "slot_estimate": None,
    },
    {
        "name": "stamen",
        "category": "botanical",
        "generator": generate_stamen,
        "positions": ["divider"],
        "roles": ["base"],
        "touch": True,
        "side_touch_heights": ("base",),
        "seams": False,
        "embellishments": (),
        "spans_cell": False,
        "min_cell_width_px": 12.0,
        "min_ring_depth_px": 36.0,
        # The cup body, a clearance, then the ball: its drawing scales with the white space.
        "min_ring_depth_clearances": 4.0,
        "max_overflow_inward": 0.0,
        "max_overflow_outward": 0.2,
        "slot_estimate": None,
    },
    {
        "name": "kite",
        "category": "geometric",
        "generator": generate_kite,
        "positions": ["centre", "divider"],
        "roles": ["base"],
        "touch": True,
        "side_touch_heights": ("mid",),
        "seams": False,
        "embellishments": ("echo", "dot", "drop"),
        "spans_cell": False,
        "min_cell_width_px": 12.0,
        "min_ring_depth_px": 16.0,
        # The bottom keeps a clearance over the floor and the side vertices sit above it at mid height.
        "min_ring_depth_clearances": 4.0,
        "max_overflow_inward": 0.0,
        "max_overflow_outward": 0.2,
        "slot_estimate": (0.35, 0.35),
    },
    {
        "name": "floret",
        "category": "botanical",
        "generator": generate_floret,
        "positions": ["centre"],
        "roles": ["slot"],
        "touch": False,
        "side_touch_heights": (),
        "seams": False,
        "embellishments": (),
        "spans_cell": False,
        "min_cell_width_px": 16.0,
        "min_ring_depth_px": 16.0,
        "max_overflow_inward": 0.0,
        "max_overflow_outward": 0.0,
        "slot_estimate": None,
    },
    {
        "name": "star",
        "category": "geometric",
        "generator": generate_star,
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
]
