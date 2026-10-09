"""
Motif contract: what a motif declares about itself, and the analyzer that holds
it to that declaration.

A motif is a list of `SmartVector`s in normalized cell space plus a measured
`Declaration` (footprint, interior slot, reach ends, base point, overflow).
`build_instance` measures the declaration and runs `MotifAnalyzer`, raising
`MotifError` when the motif breaks the contract. Limits restrict rather than
rescale: nothing here moves a point, it only reports.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import List, Optional, Sequence, Set, Tuple

from shapely.geometry import LineString, MultiPoint, MultiPolygon, Polygon

from motifs.geometry import CellPoint, MotifContext, PointTuple, SmartVector


REACH_DIRECTIONS = ("inward", "outward")
REACH_STYLES = ("straight", "wavy", "bow", "s")
MOTIF_KINDS = ("enclosing", "open")

# Slots smaller than this (square pixels) are treated as not there.
MIN_SLOT_AREA_PX = 1.0

Segment = Tuple[CellPoint, CellPoint, int]


class MotifError(ValueError):
    """A motif broke the contract; the message lists every issue found."""


@dataclass(frozen=True)
class ReachEnd:
    point: CellPoint
    direction: str
    max_length_px: float
    style: str = "straight"

    def __post_init__(self) -> None:
        if self.direction not in REACH_DIRECTIONS:
            raise MotifError(f"Reach direction must be one of {REACH_DIRECTIONS}, got {self.direction!r}")
        if self.style not in REACH_STYLES:
            raise MotifError(f"Reach style must be one of {REACH_STYLES}, got {self.style!r}")


@dataclass
class Declaration:
    footprint: List[CellPoint]
    slot: Optional[List[CellPoint]]
    reach_ends: List[ReachEnd]
    base_point: CellPoint
    overflow_inward: float
    overflow_outward: float
    seams: bool = False


@dataclass
class MotifInstance:
    vectors: List[SmartVector]
    declaration: Declaration
    kind: str

    def __post_init__(self) -> None:
        if self.kind not in MOTIF_KINDS:
            raise MotifError(f"Motif kind must be one of {MOTIF_KINDS}, got {self.kind!r}")


def _all_points(vectors: Sequence[SmartVector]) -> List[CellPoint]:
    return [point for vector in vectors for point in vector.points]


def measure_footprint(vectors: Sequence[SmartVector]) -> List[CellPoint]:
    """Convex hull of every point, in cell space. A lone point or a line gives one or two points."""
    points = _all_points(vectors)
    if not points:
        return []
    hull = MultiPoint([(p.angular, p.radial) for p in points]).convex_hull
    if isinstance(hull, Polygon):
        coords = list(hull.exterior.coords)[:-1]
    else:
        coords = list(hull.coords)
    return [CellPoint(radial=y, angular=x) for x, y in coords]


def measure_overflow(vectors: Sequence[SmartVector]) -> Tuple[float, float]:
    """How far the motif reaches past radial 0.0 (inward) and 1.0 (outward), in cell units."""
    points = _all_points(vectors)
    if not points:
        return (0.0, 0.0)
    inward = max(0.0, -min(p.radial for p in points))
    outward = max(0.0, max(p.radial for p in points) - 1.0)
    return (inward, outward)


def inset_outline(context: MotifContext, outline: List[CellPoint], inset_px: float) -> Optional[List[CellPoint]]:
    """
    `outline` (closed, cell space) inset by `inset_px` in true page space, or None when
    nothing worth drawing is left.

    The inset is taken on the arc-subdivided, unrotated outline so the analyzer's pixel
    clearance check holds exactly, then mapped back to cell space.
    """
    if len(outline) < 3:
        raise MotifError("Slot outline needs at least three points")
    if context.ring_depth <= 0 or context.half_angle <= 0:
        return None

    polygon = Polygon(context.polyline(SmartVector(list(outline), closed=True)))
    if not polygon.is_valid:
        raise MotifError("Slot outline is not a simple polygon")

    inset = polygon.buffer(-inset_px, join_style="mitre")
    if inset.is_empty:
        return None
    if isinstance(inset, MultiPolygon):
        inset = max(inset.geoms, key=lambda part: part.area)
    if not isinstance(inset, Polygon) or inset.area < MIN_SLOT_AREA_PX:
        return None

    center_x, center_y = context.center
    result = []
    for x, y in list(inset.exterior.coords)[:-1]:
        radius = math.hypot(x - center_x, y - center_y)
        angle_deg = math.degrees(math.atan2(y - center_y, x - center_x))
        result.append(CellPoint(
            radial=(radius - context.inner_radius) / context.ring_depth,
            angular=angle_deg / context.half_angle,
        ))
    return result


def measure_slot(
    context: MotifContext, outline: List[CellPoint], outline_weight: str = "outline"
) -> Optional[List[CellPoint]]:
    """
    Interior space a later motif may occupy: `outline` inset by the white-space margin
    plus half the outline's stroke and half an outline-weight stroke of whatever fills
    the slot, or None when nothing worth drawing is left.
    """
    return inset_outline(context, outline, context.clearance_px(outline_weight, "outline"))


def _default_base_point(points: Sequence[CellPoint]) -> CellPoint:
    return min(points, key=lambda p: (p.radial, abs(p.angular)))


def build_instance(
    context: MotifContext,
    vectors: Sequence[SmartVector],
    reach_ends: Sequence[ReachEnd] = (),
    slot_outline: Optional[List[CellPoint]] = None,
    base_point: Optional[CellPoint] = None,
    *,
    seams: bool = False,
    slot: Optional[List[CellPoint]] = None,
) -> MotifInstance:
    """Measure the declaration for `vectors`, then analyze; raises `MotifError` on any issue."""
    if slot is not None and slot_outline is not None:
        raise MotifError("Pass either slot_outline or an already-measured slot, not both")
    vectors = list(vectors)
    reach_ends = list(reach_ends)
    if not vectors and not reach_ends:
        raise MotifError("Motif needs at least one vector or one reach end")
    if any(not vector.points for vector in vectors):
        raise MotifError("Every vector needs at least one point")

    if vectors:
        footprint = measure_footprint(vectors)
        overflow_inward, overflow_outward = measure_overflow(vectors)
        anchor_candidates = _all_points(vectors)
    else:
        # A pure reach (a stem): the footprint is where it attaches.
        footprint = measure_footprint([SmartVector([end.point for end in reach_ends])])
        overflow_inward, overflow_outward = 0.0, 0.0
        anchor_candidates = [end.point for end in reach_ends]

    declaration = Declaration(
        footprint=footprint,
        slot=slot if slot is not None else (measure_slot(context, slot_outline) if slot_outline is not None else None),
        reach_ends=reach_ends,
        base_point=base_point if base_point is not None else _default_base_point(anchor_candidates),
        overflow_inward=overflow_inward,
        overflow_outward=overflow_outward,
        seams=seams,
    )
    kind = "enclosing" if any(vector.closed for vector in vectors) else "open"
    instance = MotifInstance(vectors=vectors, declaration=declaration, kind=kind)

    issues = MotifAnalyzer(context).analyze(instance)
    if issues:
        raise MotifError("Invalid motif: " + "; ".join(issues))
    return instance


class MotifAnalyzer:
    """Checks a `MotifInstance` against the contract. Tolerance is in cell units."""

    def __init__(self, context: MotifContext, tolerance: float = 0.025) -> None:
        self.context = context
        self.tolerance = tolerance

    def analyze(self, instance: MotifInstance) -> List[str]:
        vectors = instance.vectors
        declaration = instance.declaration
        segments = self._all_segments(vectors)
        issues: List[str] = []

        if instance.kind == "open" and not declaration.reach_ends and not declaration.seams:
            issues.append("Open motif declares no reach ends")

        issues.extend(self._open_end_issues(vectors, segments, declaration.reach_ends, declaration.seams))
        issues.extend(self._limit_issues(vectors))
        issues.extend(self._crossing_issues(segments))
        issues.extend(self._slot_issues(declaration.slot, segments))
        return issues

    # ----- structure -------------------------------------------------------

    @staticmethod
    def _vector_segments(vector: SmartVector, index: int) -> List[Segment]:
        points = vector.points
        segments = [(points[i], points[i + 1], index) for i in range(len(points) - 1)]
        if vector.closed and len(points) > 2:
            segments.append((points[-1], points[0], index))
        return segments

    def _all_segments(self, vectors: Sequence[SmartVector]) -> List[Segment]:
        return [
            segment
            for index, vector in enumerate(vectors)
            for segment in self._vector_segments(vector, index)
        ]

    # ----- open ends -------------------------------------------------------

    def _open_end_issues(
        self,
        vectors: Sequence[SmartVector],
        segments: List[Segment],
        reach_ends: Sequence[ReachEnd],
        seams: bool = False,
    ) -> List[str]:
        issues = []
        for index, vector in enumerate(vectors):
            if vector.closed:
                continue
            own = [segment for segment in segments if segment[2] == index]
            last = len(own) - 1
            for name, endpoint, adjacent in (
                ("start", vector.points[0], {0, 1}),
                ("end", vector.points[-1], {last, last - 1}),
            ):
                if self._end_is_accounted_for(endpoint, index, own, adjacent, segments, reach_ends, seams):
                    continue
                issues.append(
                    f"Vector {index} has an open end at its {name} "
                    f"(radial {endpoint.radial:.3f}, angular {endpoint.angular:.3f}) "
                    "that is neither a reach end nor touching other ink"
                )
        return issues

    def _end_is_accounted_for(
        self,
        endpoint: CellPoint,
        vector_index: int,
        own_segments: List[Segment],
        adjacent: Set[int],
        segments: List[Segment],
        reach_ends: Sequence[ReachEnd],
        seams: bool = False,
    ) -> bool:
        # A seam end sits exactly on the cell edge and meets its neighbour's mirror there (spec 4.3).
        if (
            seams
            and self.context.angular_limits == 1.0
            and abs(abs(endpoint.angular) - 1.0) <= self.tolerance
        ):
            return True
        if any(self._cell_distance(endpoint, reach.point) <= self.tolerance for reach in reach_ends):
            return True
        others = [segment for segment in segments if segment[2] != vector_index]
        if self._point_touches_segments(endpoint, others):
            return True
        own_far = [segment for position, segment in enumerate(own_segments) if position not in adjacent]
        return self._point_touches_segments(endpoint, own_far)

    # ----- limits ----------------------------------------------------------

    def _limit_issues(self, vectors: Sequence[SmartVector]) -> List[str]:
        low, high = self.context.radial_limits
        angular_limit = self.context.angular_limits
        issues = []
        for index, vector in enumerate(vectors):
            radials = [p.radial for p in vector.points]
            if min(radials) < low - self.tolerance:
                issues.append(
                    f"Vector {index} radial {min(radials):.3f} is below the radial limit {low:.3f}"
                )
            if max(radials) > high + self.tolerance:
                issues.append(
                    f"Vector {index} radial {max(radials):.3f} is above the radial limit {high:.3f}"
                )
            widest = max(abs(p.angular) for p in vector.points)
            if widest > angular_limit + self.tolerance:
                issues.append(
                    f"Vector {index} angular extent {widest:.3f} is beyond the angular limit {angular_limit:.3f}"
                )
        return issues

    # ----- crossings -------------------------------------------------------

    def _crossing_issues(self, segments: List[Segment]) -> List[str]:
        issues = []
        for i, (a1, a2, vector_a) in enumerate(segments):
            for b1, b2, vector_b in segments[i + 1:]:
                if vector_a == vector_b:
                    continue
                intersection = self._segment_intersection(a1, a2, b1, b2)
                if intersection and self._intersection_makes_tiny_space(intersection, a1, a2, b1, b2):
                    issues.append(
                        f"Vectors {vector_a} and {vector_b} cross and create whitespace smaller than "
                        f"{self.context.min_white_space:.1f}px"
                    )
        return issues

    # ----- slot ------------------------------------------------------------

    def _slot_issues(self, slot: Optional[List[CellPoint]], segments: List[Segment]) -> List[str]:
        if not slot or len(slot) < 3:
            return []
        # Polylines, not chords: a cell-space edge is an arc on the canvas, and a chord sags well off it.
        polygon = Polygon(self.context.polyline(SmartVector(slot, closed=True)))
        required = self.context.min_white_space
        issues = []
        reported: Set[int] = set()
        for start, end, vector_index in segments:
            if vector_index in reported:
                continue
            line = LineString(self.context.polyline(SmartVector([start, end])))
            distance = polygon.distance(line)
            if distance < required:
                reported.add(vector_index)
                issues.append(
                    f"Slot is {distance:.1f}px from vector {vector_index}, "
                    f"needs at least {required:.1f}px"
                )
        return issues

    # ----- ported helpers (from the retired smart-pattern analyzer) --------------------

    def _point_touches_segments(self, point: CellPoint, segments: List[Segment]) -> bool:
        return any(
            self._point_to_segment_distance(point, start, end) <= self.tolerance
            for start, end, _ in segments
        )

    @staticmethod
    def _cell_distance(first: CellPoint, second: CellPoint) -> float:
        return math.hypot(first.angular - second.angular, first.radial - second.radial)

    @staticmethod
    def _point_to_segment_distance(point: CellPoint, start: CellPoint, end: CellPoint) -> float:
        px, py = point.angular, point.radial
        ax, ay = start.angular, start.radial
        bx, by = end.angular, end.radial
        dx = bx - ax
        dy = by - ay
        if dx == 0 and dy == 0:
            return math.hypot(px - ax, py - ay)
        t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
        return math.hypot(px - (ax + t * dx), py - (ay + t * dy))

    def _segment_intersection(
        self, a1: CellPoint, a2: CellPoint, b1: CellPoint, b2: CellPoint
    ) -> Optional[PointTuple]:
        x1, y1 = a1.angular, a1.radial
        x2, y2 = a2.angular, a2.radial
        x3, y3 = b1.angular, b1.radial
        x4, y4 = b2.angular, b2.radial

        denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
        if abs(denom) < 1e-9:
            return None

        px = ((x1 * y2 - y1 * x2) * (x3 - x4) - (x1 - x2) * (x3 * y4 - y3 * x4)) / denom
        py = ((x1 * y2 - y1 * x2) * (y3 - y4) - (y1 - y2) * (x3 * y4 - y3 * x4)) / denom

        tol = self.tolerance
        if (
            min(x1, x2) - tol <= px <= max(x1, x2) + tol
            and min(y1, y2) - tol <= py <= max(y1, y2) + tol
            and min(x3, x4) - tol <= px <= max(x3, x4) + tol
            and min(y3, y4) - tol <= py <= max(y3, y4) + tol
        ):
            return (px, py)
        return None

    def _intersection_makes_tiny_space(
        self,
        intersection: PointTuple,
        a1: CellPoint,
        a2: CellPoint,
        b1: CellPoint,
        b2: CellPoint,
    ) -> bool:
        intersection_point = CellPoint(radial=intersection[1], angular=intersection[0])
        distances = [self._physical_distance(intersection_point, end) for end in (a1, a2, b1, b2)]
        touch_distance = max(self.context.stroke_width * 2.0, 3.0)
        if any(distance <= touch_distance for distance in distances):
            return False
        return min(distances) < self.context.min_white_space

    def _physical_distance(self, first: CellPoint, second: CellPoint) -> float:
        first_xy = self.context.to_cartesian(first)
        second_xy = self.context.to_cartesian(second)
        return math.hypot(first_xy[0] - second_xy[0], first_xy[1] - second_xy[1])
