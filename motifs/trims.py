"""
Ring trims (motif roadmap Phase B): seam motifs that run round a whole ring, as `scallop` and `band` do.

Every seam-deciding value is drawn from `context.ring_rng`, so every cell of the ring draws the same trim and
neighbouring cells meet exactly at their shared seam ends. The composer gives every cell of a seam position
its own stem, which starts on the trim's lowest ink on the axis and ties the ring to the structure inside it.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

from motifs.contract import MotifError, MotifInstance, build_instance, require_full_budget
from motifs.embellish import _across_seam, _faces_hold_pen
from motifs.geometry import CellPoint, MotifContext, SmartVector, cubic_points, mirror_points

# Sawtooth: one tooth per cell, its apex on the axis and its feet on the seams. Shares of the ring depth.
SAWTOOTH_OUT_BASE_RANGE = (0.12, 0.3)  # the feet of an outward tooth
SAWTOOTH_IN_BASE_RANGE = (0.7, 0.88)  # the feet of an inward tooth
SAWTOOTH_HEIGHT_RANGE = (0.45, 0.7)
SAWTOOTH_CONCAVE_CHANCE = 0.5
# A concave side's controls move toward the axis by this share of their angular.
SAWTOOTH_BOW_RANGE = (0.12, 0.3)
SAWTOOTH_STEPS = 8
# A cell too wide for one sharp tooth takes more, up to this many: the fewest whose tips turn at least this much.
MAX_TEETH = 4
SAWTOOTH_MIN_TIP_DEG = 60.0
# At this complexity and above, a second, detail tooth line nests inside the first on the same feet, its apex
# this multiple of the outline-to-detail clearance nearer them, unless that leaves it under a share of the height.
SAWTOOTH_INSET_AT = 0.6
SAWTOOTH_INSET_RANGE = (1.3, 1.9)
SAWTOOTH_INSET_LEAST = 0.3

# Arcade: two page-space circular arcs per cell from the seam ends to a cusp on the axis, each bulging away
# from the tooth by a share of its chord.
ARCADE_OUT_BASE_RANGE = (0.12, 0.3)
ARCADE_IN_BASE_RANGE = (0.7, 0.88)
ARCADE_HEIGHT_RANGE = (0.45, 0.7)
ARCADE_BULGE_RANGE = (0.08, 0.2)
ARCADE_BULGE_FLOOR = 0.04
ARCADE_MIN_CUSP_DEG = 30.0
ARCADE_SHRINK = 0.9
ARCADE_MAX_SHRINKS = 120
ARCADE_STEPS = 12

# Vesica chain: overlapping circles centred on the dividers (and, in a cell too wide for one pair to overlap,
# evenly between them). Each overlap is a pointed lens whose width is a drawn share of a circle's diameter.
VESICA_CENTRE_RANGE = (0.47, 0.53)
VESICA_OVERLAP_RANGE = (0.2, 0.35)
VESICA_MAX_STEPS = 8  # circle spacings across a cell, from one divider to the other
VESICA_DEPTH_SHARE = 0.95  # how much of the room to the ring edges a circle may use
VESICA_STEPS = 48  # samples on a whole circle
VESICA_LENS_FLOOR = 1.1  # the narrowest lens, in clearances
VESICA_WAIST = 0.5  # the least gap between circles two centres apart, in clearances


def _tooth(base: float, apex: float, bow: float, half_width: float) -> List[CellPoint]:
    """
    The right side of a tooth centred on the axis, from its foot `(base, half_width)` to its apex `(apex, 0)`,
    exact ends; a concave side's controls move toward the axis by `bow` of their angular.
    """
    foot, top = CellPoint(base, half_width), CellPoint(apex, 0.0)
    third = lambda t: CellPoint(base + (apex - base) * t, (1.0 - t) * half_width * (1.0 - bow))
    return cubic_points(foot, third(1.0 / 3.0), third(2.0 / 3.0), top, SAWTOOTH_STEPS)


def _row(right: List[CellPoint], teeth: int) -> List[CellPoint]:
    """
    A row of `teeth` copies of the tooth whose right side is `right`, seam to seam. Shifting a cell point's angular
    turns it about the design's centre, so every copy is the same tooth on the page. Feet sit exactly at
    `-1 + 2 j / teeth`, so the ends are the seam ends and neighbouring teeth share their feet.
    """
    tooth = mirror_points(right) + right[::-1][1:]
    points: List[CellPoint] = []
    for j in range(teeth):
        centre = -1.0 + (2 * j + 1) / teeth
        shifted = [CellPoint(p.radial, p.angular + centre) for p in tooth]
        shifted[0] = CellPoint(tooth[0].radial, -1.0 + 2.0 * j / teeth)
        shifted[-1] = CellPoint(tooth[-1].radial, -1.0 + 2.0 * (j + 1) / teeth)
        shifted[len(right) - 1] = CellPoint(right[-1].radial, centre)
        points.extend(shifted if not points else shifted[1:])
    return points


def _tip_turn(context: MotifContext, right: List[CellPoint]) -> float:
    """The page turn, in degrees, at a centred tooth's tip between its right side (foot to tip) and its mirror."""
    (x1, y1), (x2, y2) = context.to_cartesian(right[-2]), context.to_cartesian(right[-1])
    x3, y3 = context.to_cartesian(CellPoint(right[-2].radial, -right[-2].angular))
    a = math.atan2(y2 - y1, x2 - x1)
    b = math.atan2(y3 - y2, x3 - x2)
    return abs(math.degrees(math.remainder(b - a, 2.0 * math.pi)))


def generate_sawtooth(context: MotifContext) -> MotifInstance:
    require_full_budget(context, "sawtooth")
    ring = context.ring_rng
    outward = ring.random() < 0.5
    base = ring.uniform(*(SAWTOOTH_OUT_BASE_RANGE if outward else SAWTOOTH_IN_BASE_RANGE))
    height = ring.uniform(*SAWTOOTH_HEIGHT_RANGE)
    concave = ring.random() < SAWTOOTH_CONCAVE_CHANCE
    bow = ring.uniform(*SAWTOOTH_BOW_RANGE)
    inset = ring.uniform(*SAWTOOTH_INSET_RANGE)

    low, high = context.radial_limits
    base = max(low, min(high, base))
    apex = min(high, base + height) if outward else max(low, base - height)
    if abs(apex - base) < 1e-6:
        raise MotifError("sawtooth does not fit its radial limits")
    bow = bow if concave else 0.0
    # A wide cell takes more teeth, the fewest whose tips stay sharp.
    teeth = next((k for k in range(1, MAX_TEETH + 1)
                  if _tip_turn(context, _tooth(base, apex, bow, 1.0 / k)) >= SAWTOOTH_MIN_TIP_DEG), MAX_TEETH)
    vectors = [SmartVector(_row(_tooth(base, apex, bow, 1.0 / teeth), teeth))]
    if context.complexity >= SAWTOOTH_INSET_AT:
        inner = _inset_line(context, base, apex, bow, inset, teeth)
        if inner is not None:
            vectors.append(inner)
    return build_instance(context, vectors, seams=True)


def _inset_line(context: MotifContext, base: float, apex: float, bow: float, inset: float,
                teeth: int) -> Optional[SmartVector]:
    """
    The detail tooth line nested inside the teeth: the same feet, each apex moved toward them by `inset`
    outline-to-detail clearances, so the two lines close a chevron face in each tooth. None when the nested
    tooth would be under `SAWTOOTH_INSET_LEAST` of the tooth's height or a face does not hold a pen.
    """
    shift = context.px_to_radial(inset * context.clearance_px("outline", "detail"))
    height = apex - base
    if abs(height) - shift < SAWTOOTH_INSET_LEAST * abs(height):
        return None
    apex2 = apex - math.copysign(shift, height)
    width = 1.0 / teeth
    line = SmartVector(_row(_tooth(base, apex2, bow, width), teeth), weight="detail")
    outer = SmartVector(_row(_tooth(base, apex, bow, width), teeth))
    if not _faces_hold_pen(context, [outer, line], context.clearance_px("outline", "detail")):
        return None
    return line


def _arc_through(context: MotifContext, start: CellPoint, end: CellPoint, away: CellPoint,
                 bulge: float) -> List[CellPoint]:
    """
    A page-space circular arc from `start` to `end`, bulging away from `away` by `bulge` of its chord, sampled
    in cell space with exact ends.
    """
    (x1, y1), (x2, y2) = context.to_cartesian(start), context.to_cartesian(end)
    ax, ay = context.to_cartesian(away)
    chord = math.hypot(x2 - x1, y2 - y1)
    mx, my = (x1 + x2) / 2.0, (y1 + y2) / 2.0
    nx, ny = -(y2 - y1) / chord, (x2 - x1) / chord
    if nx * (ax - mx) + ny * (ay - my) > 0:
        nx, ny = -nx, -ny
    sagitta = bulge * chord
    radius = (chord * chord / 4.0 + sagitta * sagitta) / (2.0 * sagitta)
    cx, cy = mx - nx * (radius - sagitta), my - ny * (radius - sagitta)
    a1, a2 = math.atan2(y1 - cy, x1 - cx), math.atan2(y2 - cy, x2 - cx)
    # The short way round, which passes the bulge side (the arc is less than a half circle).
    sweep = math.remainder(a2 - a1, 2.0 * math.pi)
    points = [context.to_cell((cx + radius * math.cos(a1 + sweep * k / ARCADE_STEPS),
                               cy + radius * math.sin(a1 + sweep * k / ARCADE_STEPS)))
              for k in range(ARCADE_STEPS + 1)]
    points[0], points[-1] = start, end
    return points


def generate_arcade(context: MotifContext) -> MotifInstance:
    require_full_budget(context, "arcade")
    ring = context.ring_rng
    outward = ring.random() < 0.5
    base = ring.uniform(*(ARCADE_OUT_BASE_RANGE if outward else ARCADE_IN_BASE_RANGE))
    height = ring.uniform(*ARCADE_HEIGHT_RANGE)
    bulge = ring.uniform(*ARCADE_BULGE_RANGE)

    low, high = context.radial_limits
    base = max(low, min(high, base))
    apex = min(high, base + height) if outward else max(low, base - height)
    if abs(apex - base) < 1e-6:
        raise MotifError("arcade does not fit its radial limits")
    # Arcs that bulge past their tooth or a ring edge, or that round the cusp off, flatten toward
    # `ARCADE_BULGE_FLOOR`. Then a tooth too wide for its share of the cell lowers its cusp toward the feet, as the
    # scallop lowers its apex, and a cusp still blunt takes one more tooth in the cell, up to `MAX_TEETH`, then the
    # whole ring depth. It depends only on ring-wide values, so every cell of the ring decides alike.
    teeth, stretched = 1, False
    for _ in range(ARCADE_MAX_SHRINKS):
        width = 1.0 / teeth
        right = _arc_through(context, CellPoint(base, width), CellPoint(apex, 0.0), CellPoint(base, 0.0), bulge)
        wide = max(abs(p.angular) for p in right) > width + 1e-9
        tall = not all(low - 1e-9 <= p.radial <= high + 1e-9 for p in right)
        blunt = _tip_turn(context, right) < ARCADE_MIN_CUSP_DEG
        if not (wide or tall or blunt):
            break
        if tall:
            # Only flatter arcs keep inside the ring; no floor here.
            bulge *= ARCADE_SHRINK
        elif bulge > ARCADE_BULGE_FLOOR:
            bulge = max(ARCADE_BULGE_FLOOR, bulge * ARCADE_SHRINK)
        elif wide:
            apex = base + (apex - base) * ARCADE_SHRINK
        elif teeth < MAX_TEETH:
            teeth += 1
        elif not stretched:
            stretched, apex = True, high if apex > base else low
        else:
            raise MotifError("arcade cusp is too blunt for this cell")
    else:
        raise MotifError("arcade arcs do not fit the cell")
    return build_instance(context, [SmartVector(_row(right, teeth))], seams=True)


def _circle_cell(context: MotifContext, centre: Tuple[float, float], radius: float, start: float, sweep: float,
                 marks: List[Tuple[float, CellPoint]], clear_px: float) -> List[CellPoint]:
    """
    A page circle from angle `start` through `sweep` radians, sampled at `VESICA_STEPS` per turn plus the
    crossing angles in `marks`, whose points are placed exactly. Angles are page angles about `centre`.
    """
    steps = max(2, int(math.ceil(VESICA_STEPS * abs(sweep) / (2.0 * math.pi))))
    params = [k / steps for k in range(steps + 1)]
    exact: Dict[float, CellPoint] = {}
    for angle, point in marks:
        t = math.remainder(angle - start, 2.0 * math.pi) / sweep if sweep else 0.0
        if sweep > 0 and t < 0:
            t += 2.0 * math.pi / sweep
        if 0.0 < t < 1.0:
            params.append(t)
            exact[t] = point

    # No sample within `clear_px` of a crossing along the circle: the chords beside a shared vertex then start
    # on it, so the analyzer never reads two chords that pass close by it as a second crossing.
    clear = clear_px / radius / abs(sweep) if sweep else 0.0
    params = sorted({t for t in params if t in exact or t in (0.0, 1.0)
                     or all(abs(t - m) > clear for m in exact)})
    cx, cy = centre
    return [exact.get(t) or context.to_cell((cx + radius * math.cos(start + sweep * t),
                                             cy + radius * math.sin(start + sweep * t))) for t in params]


def _crossings(first: Tuple[float, float], second: Tuple[float, float], radius: float) -> List[Tuple[float, float]]:
    """The two page points where equal circles of `radius` about `first` and `second` cross."""
    (x1, y1), (x2, y2) = first, second
    d = math.hypot(x2 - x1, y2 - y1)
    h = math.sqrt(max(0.0, radius * radius - d * d / 4.0))
    mx, my = (x1 + x2) / 2.0, (y1 + y2) / 2.0
    ux, uy = (x2 - x1) / d, (y2 - y1) / d
    return [(mx - uy * h, my + ux * h), (mx + uy * h, my - ux * h)]


def generate_vesica_chain(context: MotifContext) -> MotifInstance:
    require_full_budget(context, "vesica_chain")
    ring = context.ring_rng
    middle = ring.uniform(*VESICA_CENTRE_RANGE)
    overlap = ring.uniform(*VESICA_OVERLAP_RANGE)

    low, high = context.radial_limits
    middle = max(low, min(high, middle))
    room = min(middle - low, high - middle) * context.ring_depth * VESICA_DEPTH_SHARE
    lens_floor = VESICA_LENS_FLOOR * context.clearance_px()
    waist = VESICA_WAIST * context.clearance_px()
    r_mid = context.radius_at(middle)
    half = math.radians(context.half_angle)
    for steps in range(1, VESICA_MAX_STEPS + 1):
        # Half the page distance between neighbouring centres, which sit `2 * half / steps` apart in angle.
        apart = r_mid * math.sin(half / steps)
        # The lens between neighbours is `2 (radius - apart)` across and keeps the lens floor; the circles two
        # centres apart, `4 apart - 2 radius` apart at the waist between a circle's two lenses, keep the waist gap
        # so they never meet. The drawn share is clamped between the two.
        radius = min(max(apart / (1.0 - overlap), apart + lens_floor / 2.0), 2.0 * apart - waist / 2.0)
        if radius - apart >= lens_floor / 2.0 - 1e-9 and radius <= room:
            break
    else:
        raise MotifError("vesica_chain circles cannot overlap in this cell")
    return build_instance(context, _vesica_vectors(context, middle, radius, steps), seams=True)


def _vesica_vectors(context: MotifContext, middle: float, radius: float, steps: int) -> List[SmartVector]:
    """
    The cell's part of the chain: the inner half of each divider's circle, from its top seam end to its bottom
    one, and every circle centred between the dividers whole; every crossing between neighbours is a shared
    vertex, and every vector is checked to stay within the cell.
    """
    angulars = [1.0 - 2.0 * j / steps for j in range(steps + 1)]
    centres = [context.to_cartesian(CellPoint(middle, a)) for a in angulars]
    marks: List[List[Tuple[float, CellPoint]]] = [[] for _ in centres]
    for j in range(steps):
        for x, y in _crossings(centres[j], centres[j + 1], radius):
            point = context.to_cell((x, y))
            if abs(point.angular) < 1e-9:
                point = CellPoint(point.radial, 0.0)
            for k in (j, j + 1):
                cx, cy = centres[k]
                marks[k].append((math.atan2(y - cy, x - cx), point))
    vectors = []
    for k, (centre, angular) in enumerate(zip(centres, angulars)):
        cx, cy = centre
        if k in (0, steps):
            # The divider's own direction outward, then the half on this cell's side of the divider.
            outward = math.atan2(cy - context.center[1], cx - context.center[0])
            side = -1.0 if angular > 0 else 1.0
            points = _circle_cell(context, centre, radius, outward, side * math.pi, marks[k], context.min_white_space)
            points[0] = CellPoint(context.to_cell((cx + radius * math.cos(outward),
                                                   cy + radius * math.sin(outward))).radial, angular)
            points[-1] = CellPoint(context.to_cell((cx - radius * math.cos(outward),
                                                    cy - radius * math.sin(outward))).radial, angular)
            vectors.append(SmartVector(points))
        else:
            points = _circle_cell(context, centre, radius, 0.0, 2.0 * math.pi, marks[k], context.min_white_space)[:-1]
            vectors.append(SmartVector(points, closed=True))
    low, high = context.radial_limits
    for vector in vectors:
        if max(abs(p.angular) for p in vector.points) > 1.0 + 1e-9:
            raise MotifError("vesica_chain circle crosses the far divider")
        if min(p.radial for p in vector.points) < low - 1e-9 or max(p.radial for p in vector.points) > high + 1e-9:
            raise MotifError("vesica_chain circle leaves its radial limits")
    if not _faces_hold_pen(context, vectors + [_across_seam(v) for v in vectors], context.clearance_px()):
        raise MotifError("vesica_chain lens does not hold a pen")
    return vectors


def _trim_entry(name: str, generator, min_depth: float, **extra) -> Dict:
    return {
        "name": name,
        "category": "geometric",
        "generator": generator,
        "positions": ["centre", "divider"],
        "roles": ["base"],
        "touch": True,
        "side_touch_heights": (),
        "seams": True,
        "embellishments": (),
        "spans_cell": True,
        "min_cell_width_px": 12.0,
        "min_ring_depth_px": min_depth,
        "max_overflow_inward": 0.0,
        "max_overflow_outward": 0.0,
        "slot_estimate": None,
        **extra,
    }


TRIM_MOTIFS: List[Dict] = [
    _trim_entry("sawtooth", generate_sawtooth, 16.0),
    _trim_entry("arcade", generate_arcade, 16.0),
    # Some circle spacing must fit a lens and a waist gap within 0.45 of the ring depth, and spacings one circle
    # apart differ by up to a factor of two: about 2.2 clearances of radius.
    _trim_entry("vesica_chain", generate_vesica_chain, 24.0, min_ring_depth_clearances=5.0),
]
