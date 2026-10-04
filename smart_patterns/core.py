"""
Core smart-pattern geometry primitives and validation.

Category modules should build patterns out of normalized `CellPoint` values and
return them through `_smart_elements()`. This keeps all pattern families under
one connection and minimum-white-space contract.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import random
from typing import Any, Dict, List, Optional, Tuple


PointTuple = Tuple[float, float]

# Normalized slack for deciding a point sits ON a cell boundary.
BOUNDARY_TOLERANCE = 0.025

# Hard cap on how far an open endpoint may bleed past a radial boundary, in
# absolute pixels. Kept under the topology validator's 5px whisker tolerance so
# the stub is pruned as an intentional overshoot rather than reported as a
# dangling line end.
MAX_OVERSHOOT_PX = 3.0

# A rendered segment may span at most this much arc before it is subdivided.
# 4 degrees holds the chord/arc error under ~0.25px at the largest canvas radius.
MAX_SEGMENT_ARC_DEGREES = 4.0


@dataclass(frozen=True)
class CellPoint:
    radial: float
    angular: float


@dataclass
class SmartVector:
    points: List[CellPoint]
    closed: bool = False
    allow_adjacent_intersections: bool = False
    # Absolute pixel bleed applied to the first / last point when it sits on the
    # inner or outer boundary. Patterns use this for a hand-drawn overshoot
    # instead of pushing radial coordinates outside the cell, which used to
    # strand endpoints in the neighboring ring where nothing is guaranteed to
    # exist. Only a lone line may bleed - see SmartVectorAnalyzer._contract_issues.
    overshoot_start_px: float = 0.0
    overshoot_end_px: float = 0.0


def boundary_side(point: CellPoint, tolerance: float = BOUNDARY_TOLERANCE) -> Optional[str]:
    """
    Which cell boundary a point sits on, or None.

    The radial tests are symmetric: a point must be within tolerance of the
    boundary on EITHER side. Points further outside the cell are contract
    violations, not boundary contacts - use `cell_overrun` to detect them.
    """
    if -tolerance <= point.radial <= tolerance:
        return "inner"
    if 1.0 - tolerance <= point.radial <= 1.0 + tolerance:
        return "outer"
    if abs(point.angular + 1.0) <= tolerance:
        return "left"
    if abs(point.angular - 1.0) <= tolerance:
        return "right"
    return None


def cell_overrun(point: CellPoint, tolerance: float = BOUNDARY_TOLERANCE) -> float:
    """How far outside the cell a point sits, in normalized radial units."""
    if point.radial < -tolerance:
        return -tolerance - point.radial
    if point.radial > 1.0 + tolerance:
        return point.radial - (1.0 + tolerance)
    return 0.0


@dataclass
class SmartAnalysis:
    is_valid: bool
    issues: List[str]
    intersections: List[PointTuple]
    left_ports: List[float]
    right_ports: List[float]


@dataclass
class SmartCellContext:
    inner_radius: float
    outer_radius: float
    wedge_angle: float
    center: PointTuple
    stroke_width: float
    complexity: float
    rng: random.Random
    min_white_space: float

    @property
    def ring_width(self) -> float:
        return self.outer_radius - self.inner_radius

    @property
    def half_angle(self) -> float:
        return self.wedge_angle / 2

    def radius_at(self, radial: float) -> float:
        return self.inner_radius + self.ring_width * radial

    def radial_to_px(self, span: float) -> float:
        return abs(span) * self.ring_width

    def px_to_radial(self, px: float) -> float:
        return px / self.ring_width if self.ring_width else 0.0

    def angular_to_px(self, span: float, at_radial: float) -> float:
        return abs(span) * self.radius_at(at_radial) * math.radians(self.half_angle)

    def px_to_angular(self, px: float, at_radial: float) -> float:
        denominator = self.radius_at(at_radial) * math.radians(self.half_angle)
        return px / denominator if denominator else 0.0

    def cell_width_px(self, at_radial: float = 0.5) -> float:
        """Full left-to-right width of the cell at this radial, in pixels."""
        return self.angular_to_px(2.0, at_radial)

    def radial_for_cell_width(self, target_px: float, limit: float = 0.5) -> float:
        """
        Lowest radial at which the cell is at least `target_px` wide.

        A cell is a wedge, so it is narrowest at the inner boundary - on a tall
        ring at high division counts it can be a few px across there while being
        comfortably wide further out. Motifs that would degenerate into a needle
        at the inner edge start at this radial instead.
        """
        span = math.radians(self.half_angle) * 2.0
        if span <= 0 or self.ring_width <= 0:
            return 0.0
        needed_radius = target_px / span
        radial = (needed_radius - self.inner_radius) / self.ring_width
        return max(0.0, min(limit, radial))

    def to_cartesian(self, point: CellPoint, overshoot_px: float = 0.0) -> PointTuple:
        radial = max(0.0, min(1.0, point.radial))
        angular = max(-1.0, min(1.0, point.angular))
        radius = self.inner_radius + self.ring_width * radial
        if overshoot_px > 0.0:
            side = boundary_side(point)
            if side == "inner":
                radius = max(1.0, radius - overshoot_px)
            elif side == "outer":
                radius += overshoot_px
        angle = math.radians(self.half_angle * angular)
        return (
            self.center[0] + radius * math.cos(angle),
            self.center[1] + radius * math.sin(angle),
        )

    def _segment_steps(self, start: CellPoint, end: CellPoint) -> int:
        """
        How many straight pieces a cell-space segment must be drawn with.

        The analyzer measures in normalized cell space, where a segment is a
        straight line. Rendering it as ONE cartesian segment instead draws the
        chord, which bows away from that line by r*(1-cos(sweep/2)) - up to
        tens of pixels on a wide wedge. Anything past the topology validator's
        snap tolerance becomes a dangling end, so subdivide until the rendered
        polyline tracks the line the analyzer approved.
        """
        sweep = abs(end.angular - start.angular) * self.half_angle
        if sweep <= MAX_SEGMENT_ARC_DEGREES:
            return 1
        return min(64, int(math.ceil(sweep / MAX_SEGMENT_ARC_DEGREES)))

    def make_path(self, vector: SmartVector) -> Dict[str, Any]:
        if not vector.points:
            raise ValueError("Smart vector needs at least one point")

        start_bleed = 0.0 if vector.closed else min(vector.overshoot_start_px, MAX_OVERSHOOT_PX)
        end_bleed = 0.0 if vector.closed else min(vector.overshoot_end_px, MAX_OVERSHOOT_PX)

        source = list(vector.points)
        last_index = len(source) - 1
        if vector.closed and len(source) > 1:
            # the closing run needs the same treatment as any other segment
            source.append(source[0])

        coords = [self.to_cartesian(source[0], start_bleed)]
        for index in range(1, len(source)):
            previous = source[index - 1]
            point = source[index]
            steps = self._segment_steps(previous, point)
            for step in range(1, steps):
                t = step / steps
                coords.append(self.to_cartesian(CellPoint(
                    radial=previous.radial + (point.radial - previous.radial) * t,
                    angular=previous.angular + (point.angular - previous.angular) * t,
                )))
            bleed = end_bleed if (index == last_index and not vector.closed) else 0.0
            coords.append(self.to_cartesian(point, bleed))

        commands = [f"M {coords[0][0]},{coords[0][1]}"]
        commands.extend(f"L {x},{y}" for x, y in coords[1:])
        if vector.closed:
            commands.append("Z")

        return {
            "tag": "path",
            "attributes": {
                "d": " ".join(commands),
                "fill": "none",
                "stroke": "black",
                "stroke-width": str(self.stroke_width),
                "stroke-linecap": "butt",
                "stroke-linejoin": "round",
            },
            "smart_vector": vector,
        }


class SmartVectorAnalyzer:
    def __init__(self, context: SmartCellContext, tolerance: float = 0.025):
        self.context = context
        self.tolerance = tolerance

    def analyze(self, vectors: List[SmartVector]) -> SmartAnalysis:
        issues: List[str] = []
        left_ports: List[float] = []
        right_ports: List[float] = []
        intersections: List[PointTuple] = []

        contract_issues = self._contract_issues(vectors)
        if contract_issues:
            # Connectivity results are meaningless once geometry sits outside
            # the cell, so report the contract break on its own.
            return SmartAnalysis(
                is_valid=False,
                issues=contract_issues,
                intersections=[],
                left_ports=[],
                right_ports=[],
            )

        all_segments = self._all_segments(vectors)
        for idx, vector in enumerate(vectors):
            touches_boundary = False
            for point in vector.points:
                side = self._boundary_side(point)
                if side:
                    touches_boundary = True
                    if side == "left":
                        left_ports.append(round(point.radial, 3))
                    elif side == "right":
                        right_ports.append(round(point.radial, 3))

            touches_other = self._touches_other_vector(idx, vector, vectors)
            if vector.closed:
                if not touches_boundary and not touches_other:
                    issues.append(f"Closed vector {idx} floats inside the cell")
            else:
                for endpoint_name, endpoint in (
                    ("start", vector.points[0]),
                    ("end", vector.points[-1]),
                ):
                    if not self._boundary_side(endpoint) and not self._point_touches_segments(
                        endpoint,
                        all_segments,
                        exclude_vector_index=idx,
                    ):
                        issues.append(f"Open vector {idx} has floating {endpoint_name} point")

        left_sorted = sorted(left_ports)
        right_sorted = sorted(right_ports)
        port_issues = self._boundary_port_issues(left_sorted, right_sorted, all_segments, vectors)
        issues.extend(port_issues)

        for i, (a1, a2, vector_a) in enumerate(all_segments):
            for b1, b2, vector_b in all_segments[i + 1:]:
                if vector_a == vector_b:
                    continue
                intersection = self._segment_intersection(a1, a2, b1, b2)
                if intersection:
                    intersections.append(intersection)
                    if self._intersection_makes_tiny_space(intersection, a1, a2, b1, b2):
                        issues.append(
                            "Vector crossing creates whitespace smaller than "
                            f"{self.context.min_white_space:.1f}px"
                        )

        return SmartAnalysis(
            is_valid=len(issues) == 0,
            issues=issues,
            intersections=intersections,
            left_ports=left_sorted,
            right_ports=right_sorted,
        )

    def _boundary_side(self, point: CellPoint) -> Optional[str]:
        return boundary_side(point, self.tolerance)

    def _contract_issues(self, vectors: List[SmartVector]) -> List[str]:
        """
        Enforce the cell contract before any connectivity analysis.

        A pattern may not place geometry outside its own cell: an endpoint in
        the neighboring ring has nothing guaranteed to connect to, which is
        what produced dangling ends and floating ring assemblies. Deliberate
        bleed goes through `overshoot_start_px` / `overshoot_end_px`, which are
        capped and only apply to endpoints that genuinely sit on a radial
        boundary (so the boundary arc is inferred, drawn, and crossed).
        """
        issues: List[str] = []
        issues.extend(self._radial_coverage_issues(vectors))
        for index, vector in enumerate(vectors):
            if not vector.points:
                issues.append(f"Vector {index} has no points")
                continue

            for point in vector.points:
                overrun = cell_overrun(point, self.tolerance)
                if overrun > 0:
                    issues.append(
                        f"Vector {index} leaves the cell radially by {overrun:.3f} "
                        f"(radial={point.radial:.3f})"
                    )
                if abs(point.angular) > 1.0 + self.tolerance:
                    issues.append(
                        f"Vector {index} leaves the cell angularly "
                        f"(angular={point.angular:.3f})"
                    )

            for label, bleed, endpoint in (
                ("start", vector.overshoot_start_px, vector.points[0]),
                ("end", vector.overshoot_end_px, vector.points[-1]),
            ):
                if bleed <= 0.0:
                    continue
                if bleed > MAX_OVERSHOOT_PX:
                    issues.append(
                        f"Vector {index} {label} overshoot {bleed:.2f}px exceeds "
                        f"the {MAX_OVERSHOOT_PX:.1f}px cap"
                    )
                if vector.closed:
                    issues.append(f"Closed vector {index} cannot declare an overshoot")
                    continue
                issues.extend(self._overshoot_endpoint_issues(index, label, endpoint, vectors))
        return issues

    def _radial_coverage_issues(self, vectors: List[SmartVector]) -> List[str]:
        """
        The cell's linework must reach across its whole radial span.

        A radial band that no line crosses is a corridor running the entire way
        around the finished mandala: a colourist can travel around it without
        ever crossing a line, and the whole band reads as one region. Ring
        boundary arcs cannot fix this - they are circles, so they only put ink
        at one radius. Only cell content can bridge the gap.
        """
        spans = []
        for vector in vectors:
            points = vector.points
            if len(points) < 2:
                continue
            sequence = list(points) + ([points[0]] if vector.closed else [])
            for index in range(len(sequence) - 1):
                low = min(sequence[index].radial, sequence[index + 1].radial)
                high = max(sequence[index].radial, sequence[index + 1].radial)
                if high > low:
                    spans.append((low, high))
        if not spans:
            return ["Pattern has no radial extent"]

        spans.sort()
        merged = [list(spans[0])]
        for low, high in spans[1:]:
            if low <= merged[-1][1] + 1e-9:
                merged[-1][1] = max(merged[-1][1], high)
            else:
                merged.append([low, high])

        ring_width = self.context.ring_width or 1.0
        min_gap = max(4.0, self.context.stroke_width * 2.0) / ring_width
        issues = []
        edges = [(0.0, merged[0][0])] + [
            (merged[i][1], merged[i + 1][0]) for i in range(len(merged) - 1)
        ] + [(merged[-1][1], 1.0)]
        for low, high in edges:
            if high - low >= min_gap:
                issues.append(
                    f"Radial band {low:.2f}-{high:.2f} "
                    f"({(high - low) * ring_width:.0f}px) is crossed by nothing, "
                    "so it becomes a lane running around the design"
                )
        return issues

    def _overshoot_endpoint_issues(
        self,
        index: int,
        label: str,
        endpoint: CellPoint,
        vectors: List[SmartVector],
    ) -> List[str]:
        """
        Only a lone line may bleed past a boundary.

        When several lines share an endpoint that is pushed outside the ring,
        they fan out from a point beyond the boundary arc, and the arc slices
        tiny un-colorable triangles off that fan. An endpoint on a side boundary
        is shared with the neighboring cell for the same reason.
        """
        issues: List[str] = []
        if self._boundary_side(endpoint) not in ("inner", "outer"):
            issues.append(
                f"Vector {index} declares a {label} overshoot but that endpoint "
                "does not sit on a radial boundary"
            )
            return issues

        if min(abs(endpoint.angular + 1.0), abs(endpoint.angular - 1.0)) <= self.tolerance:
            issues.append(
                f"Vector {index} cannot bleed at its {label}: the endpoint is on a "
                "side boundary, so the neighboring cell shares it"
            )

        for other_index, other in enumerate(vectors):
            if other_index == index:
                continue
            if any(
                self._point_to_segment_distance(endpoint, point, point) <= self.tolerance
                for point in other.points
            ):
                issues.append(
                    f"Vector {index} cannot bleed at its {label}: vector "
                    f"{other_index} shares that endpoint"
                )
                break
        return issues

    def _boundary_port_issues(
        self,
        left_ports: List[float],
        right_ports: List[float],
        all_segments: List[Tuple[CellPoint, CellPoint, int]],
        vectors: List[SmartVector],
    ) -> List[str]:
        issues: List[str] = []
        unmatched_left = self._unmatched_ports(left_ports, right_ports)
        unmatched_right = self._unmatched_ports(right_ports, left_ports)
        if not unmatched_left and not unmatched_right:
            return issues

        if not any(vector.allow_adjacent_intersections for vector in vectors):
            if len(left_ports) != len(right_ports):
                return ["Left/right cell boundary port counts do not match"]
            return [
                f"Left/right cell boundary ports do not match: {left:.3f} vs {right:.3f}"
                for left, right in zip(left_ports, right_ports)
                if abs(left - right) > self.tolerance
            ]

        left_crossings = self._boundary_crossing_radials(all_segments, "left")
        right_crossings = self._boundary_crossing_radials(all_segments, "right")
        for radial in unmatched_left:
            if not self._has_adjacent_boundary_connection(radial, right_crossings, right_ports, "left"):
                issues.append(f"Left boundary port has no adjacent-cell connection: {radial:.3f}")
        for radial in unmatched_right:
            if not self._has_adjacent_boundary_connection(radial, left_crossings, left_ports, "right"):
                issues.append(f"Right boundary port has no adjacent-cell connection: {radial:.3f}")
        return issues

    def _unmatched_ports(self, source: List[float], target: List[float]) -> List[float]:
        return [
            port
            for port in source
            if not any(abs(port - other) <= self.tolerance for other in target)
        ]

    def _boundary_crossing_radials(
        self,
        segments: List[Tuple[CellPoint, CellPoint, int]],
        side: str,
    ) -> List[float]:
        angular = -1.0 if side == "left" else 1.0
        crossings: List[float] = []
        for start, end, _ in segments:
            if abs(start.angular - angular) <= self.tolerance:
                crossings.append(start.radial)
            if abs(end.angular - angular) <= self.tolerance:
                crossings.append(end.radial)
            if (start.angular - angular) * (end.angular - angular) >= 0:
                continue
            span = end.angular - start.angular
            if abs(span) < 1e-9:
                continue
            t = (angular - start.angular) / span
            if 0.0 <= t <= 1.0:
                crossings.append(start.radial + (end.radial - start.radial) * t)
        return sorted(crossings)

    def _has_adjacent_boundary_connection(
        self,
        radial: float,
        opposite_crossings: List[float],
        same_side_ports: List[float],
        side: str,
    ) -> bool:
        if not any(abs(radial - crossing) <= self.tolerance for crossing in opposite_crossings):
            return False
        side_angular = -1.0 if side == "left" else 1.0
        candidate = CellPoint(radial=radial, angular=side_angular)
        for port in same_side_ports:
            if abs(port - radial) <= self.tolerance:
                continue
            other = CellPoint(radial=port, angular=side_angular)
            if self._physical_distance(candidate, other) < self.context.min_white_space:
                return False
        return True

    def _all_segments(self, vectors: List[SmartVector]) -> List[Tuple[CellPoint, CellPoint, int]]:
        segments: List[Tuple[CellPoint, CellPoint, int]] = []
        for vector_index, vector in enumerate(vectors):
            points = vector.points[:]
            if vector.closed and points:
                points.append(points[0])
            for idx in range(len(points) - 1):
                segments.append((points[idx], points[idx + 1], vector_index))
        return segments

    def _touches_other_vector(
        self,
        vector_index: int,
        vector: SmartVector,
        vectors: List[SmartVector],
    ) -> bool:
        other_segments = [
            segment
            for segment in self._all_segments(vectors)
            if segment[2] != vector_index
        ]
        return any(
            self._point_touches_segments(point, other_segments)
            for point in vector.points
        )

    def _point_touches_segments(
        self,
        point: CellPoint,
        segments: List[Tuple[CellPoint, CellPoint, int]],
        exclude_vector_index: Optional[int] = None,
    ) -> bool:
        for start, end, vector_index in segments:
            if exclude_vector_index is not None and vector_index == exclude_vector_index:
                continue
            if self._point_to_segment_distance(point, start, end) <= self.tolerance:
                return True
        return False

    def _point_to_segment_distance(
        self,
        point: CellPoint,
        start: CellPoint,
        end: CellPoint,
    ) -> float:
        px, py = point.angular, point.radial
        ax, ay = start.angular, start.radial
        bx, by = end.angular, end.radial
        dx = bx - ax
        dy = by - ay
        if dx == 0 and dy == 0:
            return math.hypot(px - ax, py - ay)
        t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
        closest_x = ax + t * dx
        closest_y = ay + t * dy
        return math.hypot(px - closest_x, py - closest_y)

    def _segment_intersection(
        self,
        a1: CellPoint,
        a2: CellPoint,
        b1: CellPoint,
        b2: CellPoint,
    ) -> Optional[PointTuple]:
        x1, y1 = a1.angular, a1.radial
        x2, y2 = a2.angular, a2.radial
        x3, y3 = b1.angular, b1.radial
        x4, y4 = b2.angular, b2.radial

        denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
        if abs(denom) < 1e-9:
            return None

        px = (
            (x1 * y2 - y1 * x2) * (x3 - x4)
            - (x1 - x2) * (x3 * y4 - y3 * x4)
        ) / denom
        py = (
            (x1 * y2 - y1 * x2) * (y3 - y4)
            - (y1 - y2) * (x3 * y4 - y3 * x4)
        ) / denom

        if (
            min(x1, x2) - self.tolerance <= px <= max(x1, x2) + self.tolerance
            and min(y1, y2) - self.tolerance <= py <= max(y1, y2) + self.tolerance
            and min(x3, x4) - self.tolerance <= px <= max(x3, x4) + self.tolerance
            and min(y3, y4) - self.tolerance <= py <= max(y3, y4) + self.tolerance
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
        endpoints = [a1, a2, b1, b2]
        endpoint_touch_distance = max(self.context.stroke_width * 2.0, 3.0)
        if any(
            self._physical_distance(intersection_point, endpoint) <= endpoint_touch_distance
            for endpoint in endpoints
        ):
            return False

        min_distance = min(
            self._physical_distance(intersection_point, endpoint)
            for endpoint in endpoints
        )
        return min_distance < self.context.min_white_space

    def _physical_distance(self, first: CellPoint, second: CellPoint) -> float:
        first_xy = self.context.to_cartesian(first)
        second_xy = self.context.to_cartesian(second)
        return math.hypot(first_xy[0] - second_xy[0], first_xy[1] - second_xy[1])


def _smart_elements(context: SmartCellContext, vectors: List[SmartVector]) -> List[Dict[str, Any]]:
    analysis = SmartVectorAnalyzer(context).analyze(vectors)
    if not analysis.is_valid:
        issue_text = "; ".join(analysis.issues)
        raise ValueError(f"Invalid smart pattern: {issue_text}")
    return [context.make_path(vector) for vector in vectors]


def quad_points(
    start: CellPoint,
    control: CellPoint,
    end: CellPoint,
    steps: int = 8,
) -> List[CellPoint]:
    """
    Sample a quadratic bezier in cell space.

    Coarse is fine: `make_path` densifies afterwards, so the author picks the
    shape and the engine picks the fidelity. Interior samples are clamped into
    the cell, and kept off the side boundaries so a control point can never
    manufacture a port the pattern did not intend.
    """
    points = [start]
    for index in range(1, steps):
        t = index / steps
        inverse = 1.0 - t
        radial = inverse * inverse * start.radial + 2 * inverse * t * control.radial + t * t * end.radial
        angular = inverse * inverse * start.angular + 2 * inverse * t * control.angular + t * t * end.angular
        limit = 1.0 - BOUNDARY_TOLERANCE * 1.5
        points.append(CellPoint(
            radial=max(0.0, min(1.0, radial)),
            angular=max(-limit, min(limit, angular)),
        ))
    points.append(end)
    return points


def mirror_points(points: List[CellPoint]) -> List[CellPoint]:
    """Reflect a run across the cell centerline, preserving order."""
    return [CellPoint(point.radial, -point.angular) for point in points]


def _wave_points(radial: float, amplitude: float, steps: int, phase: float = 0.0) -> List[CellPoint]:
    points = []
    for index in range(steps + 1):
        t = index / steps
        angular = -1.0 + 2.0 * t
        wave = math.sin((t + phase) * math.pi * 2)
        points.append(CellPoint(radial + amplitude * wave, angular))
    points[0] = CellPoint(radial, -1.0)
    points[-1] = CellPoint(radial, 1.0)
    return points
