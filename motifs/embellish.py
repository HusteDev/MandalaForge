"""
Embellishments: detail ink a host motif adds inside itself (spec section 6).

A generator draws its outline, then calls `apply_embellishments` before `build_instance`. The pipeline runs
`context.embellishments` in `EMBELLISHMENT_ORDER`, each from its own stream salted with its name, so adding
or dropping one never shifts another's draws. An embellishment that does not fit at this cell's pixel size,
or that is not implemented yet, is dropped and counted; the pipeline never raises.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import random
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import shapely
from shapely.geometry import LineString, MultiPoint, Point, Polygon, box
from shapely.ops import polygonize_full, unary_union

from motifs.contract import Anatomy, MotifError, inset_outline
from motifs.geometry import (
    CellPoint, MotifContext, SmartVector, insert_vertex_on_outline, mirror_points, page_arc_points,
    page_circle_points, salted_seed,
)
from motifs.page_shapes import page_offsets
from topology_validator import MIN_REGION_AREA_PX2, PEN_RADIUS_PX

EMBELLISHMENT_ORDER = ("echo", "veins", "fan", "dot", "drop", "beads")
# At most one of these per host; a host with one offers no slot.
INTERIOR_FILLS = ("veins", "fan")
# At or above this complexity a host gets two echoes, below it one.
ECHO_TWO_AT = 0.6

# Veins: side veins leave the midrib toward the tip at a drawn angle from it (page degrees); up to this many
# mirrored pairs, as many as fit. The lowest start sits a drawn share of the midrib's length above its base,
# the highest at VEIN_LAST_SHARE, the rest evenly between. When a set does not fit, the highest start steps
# down through VEIN_LAST_SHARE_FALLBACKS, then the lowest drops to the bottom of VEIN_FIRST_RANGE and the
# highest steps down again, before a pair is given up, so a shorter leaf keeps its veins spread along the
# midrib instead of dropping to a single pair.
VEIN_ANGLE_RANGE = (35.0, 50.0)
MAX_VEIN_PAIRS = 4
VEIN_FIRST_RANGE = (0.15, 0.3)
VEIN_LAST_SHARE = 0.7
VEIN_LAST_SHARE_FALLBACKS = (0.65, 0.6, 0.55, 0.5)
# Bisection steps for placing vein starts that split each half of the host into faces of equal area.
VEIN_AREA_STEPS = 8
# The span of midrib shares searched for those starts: within the same bounds as evenly spaced starts, clear of
# the narrow base and tip of the host.
VEIN_AREA_SEARCH = (VEIN_FIRST_RANGE[0], VEIN_LAST_SHARE)
# Fan: at least this many rays, or the fan is dropped; each piece of the hub arc between marks has this many steps.
MIN_FAN_RAYS = 3
FAN_ARC_STEPS = 6
# Dot: the centre is searched along the lower half of the axis in steps of this many pixels.
DOT_SEARCH_STEP_PX = 0.5
# Beads: up to this many in each half of the cell, drawn from the ring stream; the diameter is drawn between
# these multiples of `min_white_space` and capped to fit, and a row whose diameter falls below the lower one
# does not fit.
BEADS_PER_HALF_RANGE = (1, 3)
BEAD_DIAMETER_RANGE = (1.0, 2.0)
# These draw from `context.ring_rng`, continuing the stream the host drew its seam ink from, so every cell of
# the ring draws them alike; the rest draw from their own salted node stream.
RING_STREAM_EMBELLISHMENTS = ("beads",)
# Drop (roadmap Phase A): a teardrop hung from the host's tip vertex, in min_white_space units.
DROP_LENGTH_RANGE = (2.0, 3.5)  # point to the far side of the bulb
DROP_BULB_RANGE = (1.2, 2.0)  # the bulb's diameter
DROP_BULB_FLOOR = 1.0  # the smallest bulb it is shrunk to before it is dropped
DROP_POINT_ANGLE = 20.0  # degrees each side leaves the point at, from the axis
DROP_SHRINK = 0.9
DROP_SHORTEST = 1.3  # the shortest drop, as a multiple of its bulb
DROP_SIDE_STEPS = 8
# Cell-space length of the probe used to find where a vein or ray meets the ring: far past any cell.
_FAR = 50.0
# Page half-size of the polygon standing for a half-plane when measuring areas: far past any cell.
_HALF_PLANE_PX = 5000.0


@dataclass
class EmbellishResult:
    vectors: List[SmartVector]
    slot_outline: Optional[List[CellPoint]]
    slot_outline_weight: str
    dropped: int


@dataclass
class _State:
    vectors: List[SmartVector]
    slot_outline: Optional[List[CellPoint]]
    slot_outline_weight: str
    # Index of the innermost closed ring of ink: the host outline, or the last echo drawn.
    innermost: int


def embellishment_rng(context: MotifContext, name: str) -> random.Random:
    """The stream an embellishment draws from: the node's seed salted with `"emb:" + name`."""
    return random.Random(salted_seed(context.node_seed, "emb:" + name))


def _echo(context: MotifContext, state: _State, anatomy: Anatomy, rng: random.Random) -> int:
    """
    One echo, or two at `ECHO_TWO_AT` and above: each the innermost ink inset in page space by the
    clearance between its weight and a detail line, drawn closed at detail weight. Returns 1 when no echo
    fits, else 0. The slot, when the host offers one, moves inside the innermost echo.
    """
    wanted = 2 if context.complexity >= ECHO_TWO_AT else 1
    drawn = 0
    for _ in range(wanted):
        inner = state.vectors[state.innermost]
        try:
            echo = inset_outline(context, list(inner.points), context.clearance_px(inner.weight, "detail"))
        except MotifError:
            echo = None
        if echo is None or len(echo) < 3 or not _colourable(context, echo):
            break
        state.vectors.append(SmartVector(echo, closed=True, weight="detail"))
        state.innermost = len(state.vectors) - 1
        drawn += 1
    if drawn and state.slot_outline is not None:
        state.slot_outline = list(state.vectors[state.innermost].points)
        state.slot_outline_weight = "detail"
    # Drops count per embellishment: an echo that drew at least one line was drawn.
    return 0 if drawn else 1


def _colourable(context: MotifContext, outline: List[CellPoint]) -> bool:
    """
    Whether the face inside a detail outline can be coloured: somewhere at least `min_white_space` of
    white between its own edges, and a face the topology validator would accept.
    """
    polygon = Polygon(context.polyline(SmartVector(list(outline), closed=True)))
    if not polygon.is_valid or polygon.area < MIN_REGION_AREA_PX2:
        return False
    return not polygon.buffer(-max(context.clearance_px("detail", "detail") / 2.0, PEN_RADIUS_PX)).is_empty


def holds_pen(context: MotifContext, outline: List[CellPoint]) -> bool:
    """
    Whether the closed outline is a face the validator would accept: at least `MIN_REGION_AREA_PX2`,
    and still non-empty when eroded by `PEN_RADIUS_PX` (the radius already covers half the stroke
    plus the marker tip), exactly as `topology_validator` judges a region.
    """
    return _face_holds_pen(Polygon(context.polyline(SmartVector(list(outline), closed=True))))


def _face_holds_pen(polygon: Polygon) -> bool:
    return (polygon.is_valid and polygon.area >= MIN_REGION_AREA_PX2
            and not polygon.buffer(-PEN_RADIUS_PX).is_empty)


def polygon_holds_pen(polygon: Polygon) -> bool:
    """Whether a face already on the page (pixel coordinates) is one the validator accepts, as `holds_pen`."""
    return _face_holds_pen(polygon)


def _faces_hold_pen(context: MotifContext, vectors: Sequence[SmartVector], clearance_px: float = 0.0) -> bool:
    """
    Whether every face the ink of `vectors` makes holds a pen by the validator's rule (`holds_pen`), the ink
    noded and polygonized on the page as `topology_validator` does it; and, given a `clearance_px` between
    the centrelines of the lines involved, whether each face is somewhere that wide, so it has
    `min_white_space` of white between its edges.

    Snap-rounding in this cell's own frame can turn a small face into an invalid ring that `polygonize`
    silently leaves out, while the same face, rotated onto the page, is valid and the validator measures it.
    Each invalid ring is therefore kept as a face too, repaired with `make_valid` (every polygon part kept), as
    the validator repairs a face it cannot measure, so no face below the floor goes unseen.
    """
    lines = [LineString(context.polyline(vector)) for vector in vectors]
    noded = shapely.set_precision(unary_union(lines), 0.001)
    polygons, _cuts, _dangles, invalids = polygonize_full(getattr(noded, "geoms", [noded]))
    faces = list(polygons.geoms)
    for ring in invalids.geoms:
        repaired = shapely.make_valid(Polygon(ring.coords))
        faces.extend(part for part in getattr(repaired, "geoms", [repaired]) if isinstance(part, Polygon))
    erode = clearance_px / 2.0
    return bool(faces) and all(
        _face_holds_pen(face) and (erode <= PEN_RADIUS_PX or not face.buffer(-erode).is_empty) for face in faces
    )


def _cell_polygon(points: Sequence[CellPoint]) -> Polygon:
    """A closed cell-space outline as a shapely polygon in (angular, radial) coordinates."""
    return Polygon([(p.angular, p.radial) for p in points])


def _first_hit(ring: Polygon, start: CellPoint, far: CellPoint) -> Optional[CellPoint]:
    """Where the cell-space segment from `start` toward `far` first meets `ring`'s boundary, past `start`."""
    hit = LineString([(start.angular, start.radial), (far.angular, far.radial)]).intersection(ring.exterior)
    coords = [c for geom in getattr(hit, "geoms", [hit]) if not geom.is_empty for c in geom.coords]
    coords = [c for c in coords if math.hypot(c[0] - start.angular, c[1] - start.radial) > 1e-9]
    if not coords:
        return None
    near = min(coords, key=lambda c: math.hypot(c[0] - start.angular, c[1] - start.radial))
    return CellPoint(near[1], near[0])


def _toward(start: CellPoint, through: CellPoint) -> CellPoint:
    """A cell point `_FAR` from `start` on the line from `start` through `through`."""
    dr, da = through.radial - start.radial, through.angular - start.angular
    scale = _FAR / math.hypot(dr, da)
    return CellPoint(start.radial + dr * scale, start.angular + da * scale)


def _land(ring: SmartVector, point: CellPoint) -> Tuple[SmartVector, Optional[CellPoint]]:
    """`ring` with `point` made one of its vertices, and that vertex; None when `point` is not on the ring."""
    landed, (placed,) = end_on_outline(ring, [point])
    return landed, (placed if placed in landed.points else None)


def _veins(context: MotifContext, state: _State, anatomy: Anatomy, rng: random.Random) -> int:
    """
    A midrib along the axis across the innermost ring of ink, from its base crossing to its tip crossing,
    plus mirrored pairs of detail side veins from points on the midrib toward the tip at a drawn 35 to 50
    degrees from it, each ending on that ring. As many pairs as fit, up to `MAX_VEIN_PAIRS`, the highest
    start lowered through `VEIN_LAST_SHARE_FALLBACKS` and the lowest dropped to the bottom of its range before a
    pair is given up: consecutive
    starts at least a detail clearance apart along the midrib, and every face the veins make holding a pen
    with `min_white_space` of white across it somewhere.
    The midrib takes the ring's weight: outline on the host outline, detail inside an echo. Every end is a
    vertex of the line it lands on. Returns 1 when not even one pair fits.
    """
    angle = math.radians(rng.uniform(*VEIN_ANGLE_RANGE))
    first = rng.uniform(*VEIN_FIRST_RANGE)
    ring = state.vectors[state.innermost]
    span = axis_span(ring.points)
    if span is None:
        return 1
    ring, ends = end_on_outline(ring, span)
    if any(end not in ring.points for end in ends):
        return 1
    base, tip = ends
    length_px = context.radial_to_px(tip.radial - base.radial)
    spacing = context.clearance_px("detail", "detail")
    polygon = _cell_polygon(ring.points)
    lasts = (VEIN_LAST_SHARE,) + VEIN_LAST_SHARE_FALLBACKS
    spans = [(first, last) for last in lasts]
    if first > VEIN_FIRST_RANGE[0]:
        spans += [(VEIN_FIRST_RANGE[0], last) for last in lasts]
    area_below = _vein_area_below(context, ring, polygon, base, tip, angle)
    half_area = Polygon(context.polyline(SmartVector(list(ring.points), closed=True))).area / 2.0
    for pairs in range(MAX_VEIN_PAIRS, 0, -1):
        # Starts that split each half into equal areas first, then equal areas below a top vein that steps down,
        # then starts evenly along the midrib.
        candidates = [_even_area_shares(area_below, half_area, pairs)]
        candidates += [_even_area_shares(area_below, half_area, pairs, last) for last in lasts
                       if pairs > 1 and (last - VEIN_AREA_SEARCH[0]) * length_px / (pairs - 1) >= spacing]
        for low, high in spans:
            if high <= low or pairs > 1 and (high - low) * length_px / (pairs - 1) < spacing:
                continue
            candidates.append([(low + high) / 2.0] if pairs == 1 else
                              [low + (high - low) * k / (pairs - 1) for k in range(pairs)])
        for shares in candidates:
            if shares is None or any(b - a < spacing / length_px for a, b in zip(shares, shares[1:])):
                continue
            drawn = _vein_set(context, ring, polygon, base, tip, shares, angle)
            if drawn is not None:
                state.vectors[state.innermost] = drawn[0]
                state.vectors.extend(drawn[1])
                return 0
    return 1


def _vein_end(polygon: Polygon, start: CellPoint, rise: float, across: float) -> Optional[CellPoint]:
    """Where a side vein from `start`, heading `rise` outward and `across` sideways in cell units, meets the ring."""
    end = _first_hit(polygon, start, _toward(start, CellPoint(start.radial + rise, across)))
    return None if end is None or end.radial <= start.radial else end


def _half_plane(a: Tuple[float, float], b: Tuple[float, float], inside: Point) -> Polygon:
    """A large page polygon covering the side of the line through `a` and `b` that holds `inside`."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    norm = math.hypot(dx, dy) or 1.0
    ux, uy = dx / norm * _HALF_PLANE_PX, dy / norm * _HALF_PLANE_PX
    side = 1.0 if (dx * (inside.y - a[1]) - dy * (inside.x - a[0])) > 0 else -1.0
    nx, ny = -uy * side, ux * side
    return Polygon([(a[0] - ux, a[1] - uy), (a[0] + ux, a[1] + uy),
                    (a[0] + ux + nx, a[1] + uy + ny), (a[0] - ux + nx, a[1] - uy + ny)])


def _vein_area_below(context: MotifContext, ring: SmartVector, polygon: Polygon, base: CellPoint,
                     tip: CellPoint, angle: float) -> Callable[[float], Optional[float]]:
    """
    For a share of the midrib, the page area of one half of the host between its base and a side vein starting
    there; None where no vein fits. The host is symmetric about its axis, so one half stands for both.
    """
    outline = Polygon(context.polyline(SmartVector(list(ring.points), closed=True))).buffer(0)
    base_px = Point(context.to_cartesian(base))
    side_px = Point(context.to_cartesian(CellPoint((base.radial + tip.radial) / 2.0, 0.5)))
    half = outline.intersection(_half_plane(context.to_cartesian(base), context.to_cartesian(tip), side_px))
    rise = context.px_to_radial(math.cos(angle))
    known: Dict[float, Optional[float]] = {}

    def area(share: float) -> Optional[float]:
        if share not in known:
            start = CellPoint(base.radial + (tip.radial - base.radial) * share, 0.0)
            end = _vein_end(polygon, start, rise, context.px_to_angular(math.sin(angle), start.radial))
            known[share] = None if end is None else half.intersection(
                _half_plane(context.to_cartesian(start), context.to_cartesian(end), base_px)).area
        return known[share]

    return area


def _even_area_shares(area_below: Callable[[float], Optional[float]], half_area: float, pairs: int,
                      highest: Optional[float] = None) -> Optional[List[float]]:
    """
    Vein starts along the midrib that split each half of the host into faces of equal area, rather than starts
    evenly along the midrib: a host that bulges near its base would otherwise get one large face there and small
    ones toward the tip. With no `highest`, the `pairs + 1` faces from base to tip are equal; with it, the highest
    vein starts there and the `pairs` faces below it are equal, leaving the tip face as it falls. None when the
    areas cannot be read, or when two starts would coincide.
    """
    lowest, top = VEIN_AREA_SEARCH
    if highest is not None:
        half_area, parts, top = area_below(highest), pairs, highest
        if half_area is None:
            return None
    else:
        parts = pairs + 1
    a_low, a_top = area_below(lowest), area_below(top)
    if a_low is None or a_top is None:
        return None
    shares = []
    for k in range(1, pairs + 1):
        target = half_area * k / parts
        if highest is not None and k == pairs:
            shares.append(highest)
            break
        # A target past either end of the search takes that end: a host that bulges at its base puts its lowest
        # vein at the bottom of the search, and the rest split what lies above it.
        if target <= a_low or target >= a_top:
            shares.append(lowest if target <= a_low else top)
            continue
        lo, hi = (shares[-1] if shares else lowest), top
        for _ in range(VEIN_AREA_STEPS):
            mid = (lo + hi) / 2.0
            a_mid = area_below(mid)
            if a_mid is None:
                return None
            lo, hi = (mid, hi) if a_mid < target else (lo, mid)
        shares.append((lo + hi) / 2.0)
    return shares if all(b > a for a, b in zip(shares, shares[1:])) else None


def _vein_set(context: MotifContext, ring: SmartVector, polygon: Polygon, base: CellPoint, tip: CellPoint,
              shares: Sequence[float], angle: float) -> Optional[Tuple[SmartVector, List[SmartVector]]]:
    """The ring with the vein ends landed on it, then the midrib and side veins; None when they do not fit."""
    starts, veins = [], []
    for share in shares:
        start = CellPoint(base.radial + (tip.radial - base.radial) * share, 0.0)
        # The vein's direction on the page at its start, `angle` off the midrib, in cell units.
        rise = context.px_to_radial(math.cos(angle))
        across = context.px_to_angular(math.sin(angle), start.radial)
        for side in (1.0, -1.0):
            end = _first_hit(polygon, start, _toward(start, CellPoint(start.radial + rise, side * across)))
            if end is None or end.radial <= start.radial:
                return None
            ring, end = _land(ring, end)
            if end is None:
                return None
            veins.append(SmartVector([start, end], weight="detail"))
        starts.append(start)
    midrib = SmartVector([base] + starts + [tip], weight=ring.weight)
    # Each half and each face between veins keeps min_white_space of white across, as an echo does.
    if not _faces_hold_pen(context, [ring, midrib] + veins, context.clearance_px(ring.weight, "detail")):
        return None
    return ring, [midrib] + veins


def _side_crossing(polygon: Polygon, radial: float, side: float) -> Optional[CellPoint]:
    """Where the line of constant `radial` leaving the axis on `side` (+1 or -1) first meets the ring."""
    return _first_hit(polygon, CellPoint(radial, 0.0), CellPoint(radial, side * _FAR))


def _hub_radial(context: MotifContext, polygon: Polygon, low: float, high: float,
                hub_px: float) -> Optional[float]:
    """
    The radial on the axis where the ring is exactly `hub_px` from the axis on the right, by bisection
    between the ring's lowest axis crossing `low` and its widest vertex below `high`; None when it never is.
    """
    def excess(radial: float) -> Optional[float]:
        crossing = _side_crossing(polygon, radial, 1.0)
        if crossing is None:
            return None
        return context.angular_to_px(crossing.angular, radial) - hub_px

    widest = max((CellPoint(y, x) for x, y in polygon.exterior.coords if x > 0 and low < y < high),
                 key=lambda p: context.angular_to_px(p.angular, p.radial), default=None)
    if widest is None:
        return None
    lo, hi = low, widest.radial
    top = excess(hi)
    if top is None or top <= 0:
        return None
    for _ in range(60):
        mid = (lo + hi) / 2.0
        value = excess(mid)
        if value is None:
            return None
        if value > 0:
            hi = mid
        else:
            lo = mid
    return hi


def _fan(context: MotifContext, state: _State, anatomy: Anatomy, rng: random.Random) -> int:
    """
    A half-disc hub of radius one detail clearance, centred on the axis where the innermost ring is exactly
    that far from it, so the hub arc's ends land on the ring square to the axis; and detail rays from the hub
    arc, straight out from its centre, to the ring. The ray count is the most for which every wedge between
    neighbouring rays is at least a detail clearance wide along the hub arc, the rays evenly spaced with half
    a wedge at either end, and every face holding a pen. Returns 1 when fewer than `MIN_FAN_RAYS` fit.
    """
    ring = state.vectors[state.innermost]
    span = axis_span(ring.points)
    if span is None:
        return 1
    hub_px = width_px = context.clearance_px("detail", "detail")
    polygon = _cell_polygon(ring.points)
    radial = _hub_radial(context, polygon, span[0].radial, span[1].radial, hub_px)
    if radial is None:
        return 1
    centre = CellPoint(radial, 0.0)
    left, right = _side_crossing(polygon, radial, -1.0), _side_crossing(polygon, radial, 1.0)
    if left is None or right is None:
        return 1
    # n rays over the half-disc's pi radians leave wedges of pi / n radians between neighbours.
    most = int(math.floor(math.pi * hub_px / width_px + 1e-9))
    for count in range(most, MIN_FAN_RAYS - 1, -1):
        drawn = _fan_set(context, ring, polygon, centre, hub_px, count, left, right)
        if drawn is not None:
            state.vectors[state.innermost] = drawn[0]
            state.vectors.extend(drawn[1])
            return 0
    return 1


def _fan_set(context: MotifContext, ring: SmartVector, polygon: Polygon, centre: CellPoint, hub_px: float,
             count: int, left: CellPoint, right: CellPoint) -> Optional[Tuple[SmartVector, List[SmartVector]]]:
    """The ring with the hub and ray ends landed on it, then the hub arc and rays; None when they do not fit."""
    marks = [-90.0] + [-90.0 + 180.0 * (k + 0.5) / count for k in range(count)] + [90.0]
    arc: List[CellPoint] = []
    for start_deg, end_deg in zip(marks, marks[1:]):
        piece = page_arc_points(context, centre, hub_px, start_deg, end_deg, FAN_ARC_STEPS)
        arc.extend(piece if not arc else piece[1:])
    # -90 degrees is toward negative angular; the arc's ends are the ring crossings themselves.
    arc[0], arc[-1] = left, right
    if not polygon.buffer(1e-9).contains(LineString([(p.angular, p.radial) for p in arc])):
        return None
    for end in (left, right):
        ring, landed = _land(ring, end)
        if landed is None:
            return None
    rays = []
    for k in range(1, count + 1):
        start = arc[k * FAN_ARC_STEPS]
        end = _first_hit(polygon, start, _toward(centre, start))
        if end is None:
            return None
        ring, end = _land(ring, end)
        if end is None:
            return None
        rays.append(SmartVector([start, end], weight="detail"))
    hub = SmartVector(arc, weight="detail")
    if not _faces_hold_pen(context, [ring, hub] + rays):
        return None
    return ring, [hub] + rays


def _dot(context: MotifContext, state: _State, anatomy: Anatomy, rng: random.Random) -> int:
    """
    A closed detail circle, round on the page, of drawn diameter between `min_white_space` and twice that,
    centred on the axis at the lowest point of the lower half of the innermost ring where it keeps an
    outline-to-detail clearance from all ink. It floats, as a slot child may; when the host still offers a
    slot, the slot outline is cut at the dot's top so the slot keeps clear of it. Returns 1 when it does not fit.
    """
    radius = rng.uniform(context.min_white_space, 2.0 * context.min_white_space) / 2.0
    ring = state.vectors[state.innermost]
    span = axis_span(ring.points)
    if span is None:
        return 1
    keep = context.clearance_px("outline", "detail")
    ink = unary_union([LineString(context.polyline(vector)) for vector in state.vectors])
    low, high = span[0].radial, span[1].radial
    steps = int(context.radial_to_px(high - low) / 2.0 / DOT_SEARCH_STEP_PX)
    for step in range(steps + 1):
        centre = CellPoint(low + context.px_to_radial(step * DOT_SEARCH_STEP_PX), 0.0)
        # A cheap screen on the centre first; the circle is round on the page to well within a pixel.
        if ink.distance(Point(context.to_cartesian(centre))) < radius + keep - 1.0:
            continue
        circle = page_circle_points(context, centre, radius)
        if LineString(context.polyline(SmartVector(circle, closed=True))).distance(ink) < keep:
            continue
        if not holds_pen(context, circle):
            return 1
        if state.slot_outline is not None:
            state.slot_outline = _cut_below(state.slot_outline, max(p.radial for p in circle))
        state.vectors.append(SmartVector(circle, closed=True, weight="detail"))
        return 0
    return 1


def _cut_below(outline: List[CellPoint], radial: float) -> Optional[List[CellPoint]]:
    """
    The part of the closed `outline` at or above `radial`. The cut runs along that radial, a circle about the
    design's centre, so ink below it (a dot) lies at least the slot's inset from the slot measured inside.
    """
    kept = _cell_polygon(outline).intersection(box(-_FAR, radial, _FAR, _FAR))
    parts = [part for part in getattr(kept, "geoms", [kept]) if isinstance(part, Polygon) and not part.is_empty]
    if not parts:
        return None
    largest = max(parts, key=lambda part: part.area)
    return [CellPoint(y, x) for x, y in list(largest.exterior.coords)[:-1]]


def _seam_arc(vectors: Sequence[SmartVector], radial: float) -> bool:
    """Whether some open vector is an arc at `radial` running the whole cell, seam to seam."""
    return any(
        not v.closed and all(abs(p.radial - radial) <= 1e-9 for p in v.points)
        and min(p.angular for p in v.points) <= -1.0 and max(p.angular for p in v.points) >= 1.0
        for v in vectors
    )


def _beads(context: MotifContext, state: _State, anatomy: Anatomy, rng: random.Random) -> int:
    """
    A row of `k` closed detail circles, round on the page, in each half of a band's cell, mirrored about the
    axis: centred at the radial halfway between the band's arcs, evenly spaced in angular across the free span
    from the lens to the seam (a full pitch between beads, half a pitch at either end, so the row runs on
    evenly through the neighbouring cell's mirrored beads). The span starts past the lens's edge by the
    outline clearance less half a detail one, so one cap on the diameter keeps every clearance at once.
    `k` in `BEADS_PER_HALF_RANGE` and the diameter are drawn from the ring stream; the diameter is capped so
    each bead keeps an outline-to-detail clearance from all other ink and a detail clearance from every
    other bead, its own row's and the neighbouring cell's. Fewer beads are tried when the drawn number does
    not fit; returns 1 when not even one does.

    The host is a band: `anatomy` gives its lens (`outline`) and the lens tips, which sit on its two seam arcs.
    The beads float, as a slot child may; at detail weight they are detail ink, not base structure.
    """
    wanted = rng.randint(*BEADS_PER_HALF_RANGE)
    drawn_radius = rng.uniform(*BEAD_DIAMETER_RANGE) * context.min_white_space / 2.0
    inner, outer = anatomy.base.radial, anatomy.tip.radial
    if not (inner < outer and _seam_arc(state.vectors, inner) and _seam_arc(state.vectors, outer)):
        return 1
    lens = _cell_polygon(state.vectors[anatomy.outline].points)
    middle = (inner + outer) / 2.0
    edge = _side_crossing(lens, middle, 1.0)
    if edge is None or not 0.0 < edge.angular < 1.0:
        return 1
    # The row starts past the lens by the part of its clearance a bead's neighbour does not already ask for,
    # so the lens keeps an outline clearance exactly when neighbouring beads keep a detail one.
    start = edge.angular + context.px_to_angular(
        context.clearance_px("outline", "detail") - context.clearance_px("detail", "detail") / 2.0, middle)
    if not start < 1.0:
        return 1
    least = BEAD_DIAMETER_RANGE[0] * context.min_white_space / 2.0
    for count in range(wanted, 0, -1):
        pitch = (1.0 - start) / count
        centres = [CellPoint(middle, start + pitch * (k + 0.5)) for k in range(count)]
        radius = min(drawn_radius, _bead_room(context, state.vectors, centres))
        if radius < least:
            continue
        right = [page_circle_points(context, centre, radius) for centre in centres]
        beads = [SmartVector(points, closed=True, weight="detail") for points in right]
        beads += [SmartVector(mirror_points(points), closed=True, weight="detail") for points in right]
        if not all(holds_pen(context, bead.points) for bead in beads):
            continue
        if not _beads_keep_clear(context, state.vectors, beads):
            continue
        state.vectors.extend(beads)
        return 0
    return 1


def _bead_room(context: MotifContext, vectors: Sequence[SmartVector], centres: Sequence[CellPoint]) -> float:
    """
    The largest page radius beads at `centres` (one half's row, mirrored onto the other) may have: each keeps
    the clearance from every line of `vectors` and a detail clearance from every other bead, including its
    reflection across the seam at angular 1, the neighbouring cell's bead. Distances run between centres;
    a page circle's polygon lies within its radius, so these bound the true gaps.
    """
    every = list(centres) + [CellPoint(c.radial, -c.angular) for c in centres]
    across = context.clearance_px("detail", "detail")
    room = math.inf
    for vector in vectors:
        line = LineString(context.polyline(vector))
        keep = context.clearance_px(vector.weight, "detail")
        room = min(room, min(line.distance(Point(context.to_cartesian(c))) for c in every) - keep)
    points = [Point(context.to_cartesian(c)) for c in every]
    for index, a in enumerate(points):
        for b in points[index + 1:]:
            room = min(room, (a.distance(b) - across) / 2.0)
    for centre in centres:
        seam = Point(context.to_cartesian(CellPoint(centre.radial, 2.0 - centre.angular)))
        room = min(room, (Point(context.to_cartesian(centre)).distance(seam) - across) / 2.0)
    return room


def _across_seam(vector: SmartVector) -> SmartVector:
    """`vector` reflected across the seam at angular 1: the neighbouring cell's copy of mirrored ink."""
    return SmartVector([CellPoint(p.radial, 2.0 - p.angular) for p in vector.points], closed=vector.closed,
                       weight=vector.weight, layer=vector.layer)


def _beads_keep_clear(context: MotifContext, vectors: Sequence[SmartVector],
                      beads: Sequence[SmartVector]) -> bool:
    """The traced beads' exact gaps: from all other ink, from each other, and from the neighbouring cell's."""
    lines = [LineString(context.polyline(bead)) for bead in beads]
    across = context.clearance_px("detail", "detail")
    for vector in vectors:
        ink = LineString(context.polyline(vector))
        keep = context.clearance_px(vector.weight, "detail")
        if any(ink.distance(line) < keep - 1e-9 for line in lines):
            return False
    neighbours = [LineString(context.polyline(_across_seam(bead))) for bead in beads]
    for index, line in enumerate(lines):
        others = lines[index + 1:] + neighbours
        if any(line.distance(other) < across - 1e-9 for other in others):
            return False
    return True


Handler = Callable[[MotifContext, _State, Anatomy, random.Random], int]

def drop_outline(context: MotifContext, tip: CellPoint, length_px: float, bulb_px: float) -> List[CellPoint]:
    """
    A closed teardrop, round on the page, whose point is `tip` and whose bulb lies outward along the radius:
    each side leaves the point at `DROP_POINT_ANGLE` from the axis, swells to the bulb's widest at
    `length_px - bulb_px / 2`, and rounds over to the far end. The point is the first vertex.
    """
    radius = bulb_px / 2.0
    widest = length_px - radius
    angle = math.radians(DROP_POINT_ANGLE)
    reach = widest * 0.6
    side = _cubic_offsets((0.0, 0.0), (reach * math.cos(angle), reach * math.sin(angle)),
                          (widest - radius * 1.3, radius), (widest, radius))
    # A quarter circle, as a cubic, from the widest point to the far end of the bulb.
    kappa = 0.5523 * radius
    cap = _cubic_offsets((widest, radius), (widest + kappa, radius), (length_px, kappa), (length_px, 0.0))
    right = side + cap[1:]
    offsets = right + [(along, -across) for along, across in reversed(right[1:-1])]
    points = page_offsets(context, tip, offsets)
    points[0] = tip
    return points


def _cubic_offsets(p0, p1, p2, p3) -> List[Tuple[float, float]]:
    out = []
    for index in range(DROP_SIDE_STEPS + 1):
        t = index / DROP_SIDE_STEPS
        u = 1.0 - t
        w = (u * u * u, 3 * u * u * t, 3 * u * t * t, t * t * t)
        out.append((sum(wk * p[0] for wk, p in zip(w, (p0, p1, p2, p3))),
                    sum(wk * p[1] for wk, p in zip(w, (p0, p1, p2, p3)))))
    return out


def _drop(context: MotifContext, state: _State, anatomy: Anatomy, rng: random.Random) -> int:
    """
    A closed outline-weight teardrop hung from the host's tip vertex, its bulb outward. Drawn at a length and
    bulb from `DROP_LENGTH_RANGE` and `DROP_BULB_RANGE` (min_white_space units), both shrunk by the same factor
    until it lies inside the radial ceiling and the angular budget and keeps a clearance from other ink away
    from the tip, the bulb no smaller than `DROP_BULB_FLOOR`; dropped (returns 1) once it would be shorter
    than `DROP_SHORTEST` bulbs.
    """
    white = context.min_white_space
    length_px = rng.uniform(*DROP_LENGTH_RANGE) * white
    bulb_px = rng.uniform(*DROP_BULB_RANGE) * white
    tip = anatomy.tip
    high = context.radial_limits[1]
    keep = context.clearance_px()
    disc = Point(context.to_cartesian(tip)).buffer(keep)
    ink = unary_union([LineString(context.polyline(vector)) for vector in state.vectors]).difference(disc)
    floor = DROP_BULB_FLOOR * white
    bulb_px = max(bulb_px, floor)
    while length_px >= bulb_px * DROP_SHORTEST:
        points = drop_outline(context, tip, length_px, bulb_px)
        inside = (max(p.radial for p in points) <= high
                  and max(abs(p.angular) for p in points) <= context.angular_limits)
        if inside and holds_pen(context, points):
            line = LineString(context.polyline(SmartVector(points, closed=True))).difference(disc)
            if ink.is_empty or line.distance(ink) >= keep:
                state.vectors.append(SmartVector(points, closed=True))
                return 0
        # Both shrink together; a bulb at its floor stays there while the neck shortens.
        length_px *= DROP_SHRINK
        bulb_px = max(bulb_px * DROP_SHRINK, floor)
    return 1


# Implemented embellishments; a name in EMBELLISHMENT_ORDER missing here is dropped until it arrives.
_HANDLERS: Dict[str, Handler] = {
    "echo": _echo, "veins": _veins, "fan": _fan, "dot": _dot, "drop": _drop, "beads": _beads,
}


def apply_embellishments(
    context: MotifContext,
    vectors: Sequence[SmartVector],
    anatomy: Optional[Anatomy],
    slot_outline: Optional[List[CellPoint]],
) -> EmbellishResult:
    """
    The host's `vectors` with `context.embellishments` added, in `EMBELLISHMENT_ORDER`, and the slot outline
    the host should declare (moved inside the innermost echo, or None after an interior fill). Every
    embellishment needs the host's anatomy; without it, or when it does not fit, it is dropped and counted.
    """
    requested = set(context.embellishments)
    state = _State(
        vectors=list(vectors),
        slot_outline=None if slot_outline is None else list(slot_outline),
        slot_outline_weight="outline",
        innermost=anatomy.outline if anatomy is not None else 0,
    )
    dropped = sum(1 for name in requested if name not in EMBELLISHMENT_ORDER)
    for name in EMBELLISHMENT_ORDER:
        if name not in requested:
            continue
        handler = _HANDLERS.get(name)
        if handler is None or anatomy is None:
            dropped += 1
            continue
        rng = context.ring_rng if name in RING_STREAM_EMBELLISHMENTS else embellishment_rng(context, name)
        missed = handler(context, state, anatomy, rng)
        dropped += missed
        if name in INTERIOR_FILLS and not missed:
            state.slot_outline = None
    return EmbellishResult(state.vectors, state.slot_outline, state.slot_outline_weight, dropped)


def axis_span(points: List[CellPoint]) -> Optional[List[CellPoint]]:
    """
    Where the cell's centreline (angular 0) crosses the closed cell-space outline `points`: the lowest and
    highest crossings, or None when it does not cross twice.
    """
    radials = [p.radial for p in points]
    axis = LineString([(0.0, min(radials) - 1.0), (0.0, max(radials) + 1.0)])
    ring = Polygon([(p.angular, p.radial) for p in points]).exterior
    hit = axis.intersection(ring)
    if isinstance(hit, Point):
        coords = [hit.coords[0]]
    elif isinstance(hit, MultiPoint):
        coords = [geom.coords[0] for geom in hit.geoms]
    else:
        return None
    if len(coords) < 2:
        return None
    low, high = min(coords, key=lambda c: c[1]), max(coords, key=lambda c: c[1])
    return [CellPoint(low[1], 0.0), CellPoint(high[1], 0.0)]


def end_on_outline(vector: SmartVector, ends: Sequence[CellPoint],
                   tolerance: float = 1e-7) -> Tuple[SmartVector, List[CellPoint]]:
    """
    `vector` (closed) with each of `ends` made a vertex: an end within `tolerance` of a vertex snaps to it,
    one on an edge is inserted there. Returns the vector and the vertices the ends became.
    """
    points = list(vector.points)
    placed = []
    for end in ends:
        near = next((p for p in points if abs(p.radial - end.radial) <= tolerance
                     and abs(p.angular - end.angular) <= tolerance), None)
        if near is None:
            points = insert_vertex_on_outline(points, True, end, tolerance=tolerance)
            near = end
        placed.append(near)
    return SmartVector(points, closed=vector.closed, weight=vector.weight, layer=vector.layer), placed
