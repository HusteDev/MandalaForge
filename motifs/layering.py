"""
Layered rings (spec section 5): a second ring of motifs behind the front ones, with hidden lines removed.

A layered ring's centre node is a composite. `compose_layered` draws the front as an ordinary base and the
back once from the ring's back stream, shifts the back onto the cell's two dividers, keeps the parts inside
the cell, cuts away everything the front's fill hides, and returns front and back ink as one `MotifInstance`.
All of it is cell space (x = angular, y = radial), which is exact because tracing maps straight cell-space
segments to the drawn curves, so a pull-back regenerates the whole composite and the back is cut again.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

import shapely
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union

from motifs.contract import MotifError, MotifInstance, build_instance
from motifs.geometry import CellPoint, MotifContext, SmartVector, insert_vertex_on_outline

# The back is drawn centred on angular 0 and shifted by these to sit on the cell's two dividers: one angular
# unit is half a wedge, and cell space is linear in angle.
SHIFTS = (1.0, -1.0)
# A cut point lies on a front outline segment to float noise; within this (cell units) it is that segment's.
CUT_TOLERANCE = 1e-9
# The touch disc round a cut end, where a back piece may come closer to the front than the clearance, is
# at least this many pixels across in radius (the resolver's touch-disc floor).
TOUCH_DISC_FLOOR_PX = 8.0


class LayeringError(MotifError):
    """The back layer, or its cut against the front, failed; the ring's back is dropped (spec 5.4)."""


Piece = Tuple[List[CellPoint], str, Tuple[bool, bool]]  # points, weight, (start is a cut, end is a cut)


def compose_layered(front_context: MotifContext, front_entry: Dict,
                    back_context: MotifContext, back_entry: Dict) -> MotifInstance:
    """
    The front with the back behind it (spec 5.2 steps 1 to 7). A failure of the front raises the front's
    own `MotifError`; any failure of the back or of the cut raises `LayeringError`.
    """
    front = front_entry["generator"](front_context)
    try:
        back = back_entry["generator"](back_context)
    except MotifError as error:
        raise LayeringError(f"back {back_entry['name']} failed: {error}") from error

    front_vectors = [SmartVector(list(v.points), v.closed, v.weight, v.layer) for v in front.vectors]
    fills = [i for i, v in enumerate(front_vectors) if v.closed and len(v.points) >= 3]
    if not fills:
        raise LayeringError(f"front {front_entry['name']} has no fill to hide a back behind")
    polygons = [Polygon([(p.angular, p.radial) for p in front_vectors[i].points]) for i in fills]
    if not all(polygon.is_valid for polygon in polygons):
        raise LayeringError(f"front {front_entry['name']} outline is not a simple polygon")
    fill = unary_union(polygons)
    edges = [
        (a, b)
        for i in fills
        for a, b in _segments(front_vectors[i].points, closed=True)
    ]

    pieces: List[Piece] = []
    for shift in SHIFTS:
        for vector in back.vectors:
            for run in _strip_runs([CellPoint(p.radial, p.angular + shift) for p in vector.points], vector.closed):
                pieces.extend((points, vector.weight, cuts) for points, cuts in _visible(run, fill, edges))

    # Step 5: a short piece with no seam end is noise between two cuts.
    shortest = 2.0 * front_context.min_white_space
    pieces = [piece for piece in pieces if _has_seam_end(piece[0]) or _length_px(front_context, piece[0]) >= shortest]
    # Below the side-touch vertex, and just above it where both fronts still hug the divider, neighbouring
    # fronts leave only a notch, and back ink there closes a face no pen fits.
    if front_context.side_touch_radial is not None:
        notch = front_context.side_touch_radial + front_context.px_to_radial(notch_margin_px(front_context))
        pieces = _outside_notch(pieces, notch)

    for points, weight, cuts in pieces:
        if weight == "outline" and not any(cuts):
            # Neither a cut nor (necessarily) its neighbour's half ties it to the structure: it would float.
            raise LayeringError("a back outline piece is not hidden anywhere by the front")

    # Step 4: every cut point becomes a vertex of the front outline it lies on, and the piece ends exactly there.
    placed: List[SmartVector] = []
    for points, weight, cuts in pieces:
        points = list(points)
        for end, is_cut in ((0, cuts[0]), (-1, cuts[1])):
            if is_cut:
                points[end] = _insert_cut(front_vectors, fills, points[end])
        placed.append(SmartVector(points, closed=False, weight=weight, layer="back"))

    _check_clearance(front_context, front_vectors, fills, pieces, placed)

    try:
        return build_instance(
            front_context, front_vectors + placed,
            reach_ends=front.declaration.reach_ends,
            base_point=front.declaration.base_point,
            seams=True,
            slot=front.declaration.slot,
            anatomy=front.declaration.anatomy,
            dropped_embellishments=front.dropped_embellishments + back.dropped_embellishments,
        )
    except MotifError as error:
        raise LayeringError(f"layered composite is invalid: {error}") from error


# ---------------------------------------------------------------- the strip


def _segments(points: Sequence[CellPoint], closed: bool) -> List[Tuple[CellPoint, CellPoint]]:
    pairs = list(zip(points, points[1:]))
    if closed and len(points) > 2:
        pairs.append((points[-1], points[0]))
    return pairs


def _at(a: CellPoint, b: CellPoint, t: float, angular: Optional[float] = None) -> CellPoint:
    """The point a fraction `t` from `a` to `b`, with its angular set exactly when given."""
    if t <= 0.0:
        return a
    if t >= 1.0:
        return b
    return CellPoint(a.radial + (b.radial - a.radial) * t,
                     angular if angular is not None else a.angular + (b.angular - a.angular) * t)


def _strip_span(a: CellPoint, b: CellPoint) -> Optional[Tuple[CellPoint, CellPoint]]:
    """
    The part of segment `a`-`b` inside the cell, `abs(angular) <= 1`, with ends on a divider exactly at
    angular +/-1; None when nothing of it is inside, or it only runs along a divider (both cells would draw it).
    """
    xa, xb = a.angular, b.angular
    if xa == xb:
        return (a, b) if abs(xa) < 1.0 else None
    # The fractions at which the segment meets each divider, in the order it meets them.
    (t_in, edge_in), (t_out, edge_out) = sorted(((edge - xa) / (xb - xa), edge) for edge in (-1.0, 1.0))
    low, high = max(0.0, t_in), min(1.0, t_out)
    if low >= high:
        return None
    start = _at(a, b, low, edge_in) if low > 0.0 else a
    end = _at(a, b, high, edge_out) if high < 1.0 else b
    return start, end


def _strip_runs(points: List[CellPoint], closed: bool) -> List[List[CellPoint]]:
    """The runs of a shifted back vector inside the cell, as open polylines whose divider ends sit at +/-1."""
    if closed:
        outside = [i for i, p in enumerate(points) if abs(p.angular) > 1.0]
        if not outside:
            if all(abs(p.angular) < 1.0 for p in points):
                raise LayeringError("a closed back vector lies wholly inside one cell")
            outside = [i for i, p in enumerate(points) if abs(p.angular) >= 1.0]
        start = outside[0]
        points = points[start:] + points[:start] + [points[start]]
    runs: List[List[CellPoint]] = []
    current: List[CellPoint] = []
    for a, b in zip(points, points[1:]):
        span = _strip_span(a, b)
        if span is None:
            if len(current) > 1:
                runs.append(current)
            current = []
            continue
        start, end = span
        if current and current[-1] == start:
            current.append(end)
        else:
            if len(current) > 1:
                runs.append(current)
            current = [start, end]
    if len(current) > 1:
        runs.append(current)
    return [_dedupe(run) for run in runs if len(_dedupe(run)) > 1]


def _dedupe(run: List[CellPoint]) -> List[CellPoint]:
    out = [run[0]]
    for point in run[1:]:
        if point != out[-1]:
            out.append(point)
    return out


# ---------------------------------------------------------------- the cut


def _crossings(a: CellPoint, b: CellPoint, edges: Sequence[Tuple[CellPoint, CellPoint]]) -> List[Tuple[float, CellPoint]]:
    """`(t, point)` where segment `a`-`b` meets a front edge, `t` its fraction along `a`-`b`."""
    found = []
    dx, dy = b.angular - a.angular, b.radial - a.radial
    for c, d in edges:
        ex, ey = d.angular - c.angular, d.radial - c.radial
        denom = dx * ey - dy * ex
        if abs(denom) < 1e-15:
            continue
        qx, qy = c.angular - a.angular, c.radial - a.radial
        t = (qx * ey - qy * ex) / denom
        u = (qx * dy - qy * dx) / denom
        if -1e-12 <= t <= 1.0 + 1e-12 and -1e-12 <= u <= 1.0 + 1e-12:
            t = min(1.0, max(0.0, t))
            u = min(1.0, max(0.0, u))
            # The point on the front edge, so it lies on the outline it will be inserted into.
            found.append((t, c if u == 0.0 else d if u == 1.0 else
                          CellPoint(c.radial + ey * u, c.angular + ex * u)))
    return found


def _visible(run: List[CellPoint], fill, edges) -> List[Tuple[List[CellPoint], Tuple[bool, bool]]]:
    """
    The parts of `run` outside the front's fill, each with whether its start and end are cuts. A piece
    breaks only where the run passes into the fill, never where it merely touches its boundary.
    """
    pieces: List[Tuple[List[CellPoint], Tuple[bool, bool]]] = []
    current: List[CellPoint] = []
    start_cut = False
    for a, b in zip(run, run[1:]):
        breaks = sorted({t: p for t, p in _crossings(a, b, edges) if 0.0 < t < 1.0}.items())
        stops = [(0.0, a)] + breaks + [(1.0, b)]
        for (t0, p0), (t1, p1) in zip(stops, stops[1:]):
            if t1 - t0 <= 0.0:
                continue
            mid = Point(a.angular + (b.angular - a.angular) * (t0 + t1) / 2.0,
                        a.radial + (b.radial - a.radial) * (t0 + t1) / 2.0)
            hidden = fill.contains(mid)
            if hidden:
                if len(current) > 1:
                    pieces.append((current, (start_cut, True)))
                current = []
                start_cut = True
                continue
            if not current:
                current = [p0]
            if p1 != current[-1]:
                current.append(p1)
    if len(current) > 1:
        pieces.append((current, (start_cut, False)))
    return pieces


def _insert_cut(front_vectors: List[SmartVector], fills: Sequence[int], point: CellPoint) -> CellPoint:
    """Make `point` a vertex of the front outline it lies on, and return that vertex exactly."""
    for i in fills:
        points = front_vectors[i].points
        near = next((p for p in points if abs(p.radial - point.radial) <= CUT_TOLERANCE
                     and abs(p.angular - point.angular) <= CUT_TOLERANCE), None)
        if near is not None:
            return near
        inserted = insert_vertex_on_outline(points, True, point, tolerance=CUT_TOLERANCE)
        if inserted is not points:
            front_vectors[i].points = inserted
            return point
    raise LayeringError(f"cut point ({point.radial:.4f}, {point.angular:.4f}) lies on no front outline")


def _has_seam_end(points: Sequence[CellPoint]) -> bool:
    return abs(points[0].angular) == 1.0 or abs(points[-1].angular) == 1.0


def _outside_notch(pieces: Sequence[Piece], notch: float) -> List[Piece]:
    """
    The pieces with no seam end at or below radial `notch`. Whether a seam end lies there reads only the
    back and the ring's touch radial, which both cells of a divider share, so the two halves meeting at a
    notch seam are dropped together. A piece joining a notch seam to a seam above it cannot be dropped
    without leaving its upper seam's other half dangling, so it fails the composite (and so the ring's back).
    """
    kept = []
    for piece in pieces:
        points = piece[0]
        in_notch = [end.radial <= notch for end in (points[0], points[-1]) if abs(end.angular) == 1.0]
        if not any(in_notch):
            kept.append(piece)
        elif not all(in_notch):
            raise LayeringError("a back piece joins the notch below the side touch to a seam above it")
    return kept


def _length_px(context: MotifContext, points: Sequence[CellPoint]) -> float:
    return LineString(context.polyline(SmartVector(list(points)))).length


# ---------------------------------------------------------------- clearance


def touch_disc_px(context: MotifContext) -> float:
    """
    Radius of the disc round a cut end inside which a back piece may approach the front outline: the
    clearance itself plus `max(min_white_space, TOUCH_DISC_FLOOR_PX)`. A piece leaves its cut at an angle, so
    at a disc radius below the clearance it would always be too close at the disc's edge.
    """
    return context.clearance_px() + max(context.min_white_space, TOUCH_DISC_FLOOR_PX)


def notch_margin_px(context: MotifContext) -> float:
    """How far above the side-touch vertex a seam end still counts as in the notch between two fronts."""
    return touch_disc_px(context)


def _check_clearance(context: MotifContext, front_vectors: List[SmartVector], fills: Sequence[int],
                     pieces: Sequence[Piece], placed: Sequence[SmartVector]) -> None:
    """
    Spec 5.2 step 6, in page space: every visible back piece keeps `min_white_space` plus half of each
    stroke from the front outline, except within the touch disc of its own cut ends. A seam end is checked
    on its own, so a short piece cannot hide one beside the front inside a cut end's disc.
    """
    disc = touch_disc_px(context)
    outlines = [(LineString(context.polyline(front_vectors[i])), front_vectors[i].weight) for i in fills]
    for (_, weight, cuts), vector in zip(pieces, placed):
        line = LineString(context.polyline(vector))
        ends = [context.to_cartesian(p) for p, is_cut in ((vector.points[0], cuts[0]), (vector.points[-1], cuts[1]))
                if is_cut]
        rest = line.difference(shapely.MultiPoint(ends).buffer(disc)) if ends else line
        # A seam end is no cut: it keeps clear of the front even when the whole piece lies in a touch disc.
        seams = [Point(context.to_cartesian(p)) for p in (vector.points[0], vector.points[-1]) if abs(p.angular) == 1.0]
        for outline, outline_weight in outlines:
            needed = context.clearance_px(weight, outline_weight)
            gaps = [rest.distance(outline)] if not rest.is_empty else []
            gaps.extend(seam.distance(outline) for seam in seams)
            if gaps and min(gaps) < needed:
                raise LayeringError(f"a back piece comes {min(gaps):.1f}px from the front, needs {needed:.1f}px")
