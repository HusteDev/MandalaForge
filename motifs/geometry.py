"""
Geometry primitives for the motif engine.

Ported by copying from `smart_patterns/core.py` so this package is
self-contained. Motifs are authored in normalized cell space: `radial` runs 0 to
1 from the inner to the outer boundary of a ring, and `angular` runs -1 to 1
across the wedge. `MotifContext` converts that space to canvas pixels.

Unlike the old context, conversion does not clamp: the analyzer enforces cell
limits, and overflow past a boundary is legitimate.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import random
from typing import Any, Dict, List, Optional, Tuple


PointTuple = Tuple[float, float]

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


@dataclass
class MotifContext:
    inner_radius: float
    outer_radius: float
    wedge_angle: float
    center: PointTuple
    stroke_width: float
    complexity: float
    min_white_space: float
    rng: random.Random
    position: str = "centre"
    angular_limits: float = 1.0
    radial_limits: Tuple[float, float] = (0.0, 1.0)
    slot: Optional[List[CellPoint]] = None
    # Radial of the shared side vertex for base motifs in a side-touch ring (spec 13.2); None draws the plain shape.
    side_touch_radial: Optional[float] = None

    @property
    def ring_depth(self) -> float:
        return self.outer_radius - self.inner_radius

    @property
    def half_angle(self) -> float:
        return self.wedge_angle / 2

    def radius_at(self, radial: float) -> float:
        return self.inner_radius + self.ring_depth * radial

    def radial_to_px(self, span: float) -> float:
        return abs(span) * self.ring_depth

    def px_to_radial(self, px: float) -> float:
        return px / self.ring_depth if self.ring_depth else 0.0

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
        if span <= 0 or self.ring_depth <= 0:
            return 0.0
        needed_radius = target_px / span
        radial = (needed_radius - self.inner_radius) / self.ring_depth
        return max(0.0, min(limit, radial))

    def to_cartesian(self, point: CellPoint, rotation_deg: float = 0.0) -> PointTuple:
        """Canvas position of a cell point, with the cell turned by `rotation_deg`. Never clamps."""
        radius = self.radius_at(point.radial)
        angle = math.radians(rotation_deg + self.half_angle * point.angular)
        return (
            self.center[0] + radius * math.cos(angle),
            self.center[1] + radius * math.sin(angle),
        )

    def _segment_steps(self, start: CellPoint, end: CellPoint) -> int:
        """
        How many straight pieces a cell-space segment must be drawn with.

        A segment is a straight line in normalized cell space. Rendering it as
        ONE cartesian segment instead draws the chord, which bows away from that
        line by r*(1-cos(sweep/2)) - up to tens of pixels on a wide wedge.
        Subdivide until the rendered polyline tracks the cell-space line.
        """
        sweep = abs(end.angular - start.angular) * self.half_angle
        if sweep <= MAX_SEGMENT_ARC_DEGREES:
            return 1
        return min(64, int(math.ceil(sweep / MAX_SEGMENT_ARC_DEGREES)))

    def polyline(self, vector: SmartVector, rotation_deg: float = 0.0) -> List[PointTuple]:
        """
        Canvas coordinates tracing `vector`, with arcs subdivided.

        A closed vector gets its first point appended at the end so the closing
        run is subdivided like any other segment.
        """
        if not vector.points:
            raise ValueError("Smart vector needs at least one point")

        source = list(vector.points)
        if vector.closed and len(source) > 1:
            source.append(source[0])

        coords = [self.to_cartesian(source[0], rotation_deg)]
        for index in range(1, len(source)):
            previous = source[index - 1]
            point = source[index]
            steps = self._segment_steps(previous, point)
            for step in range(1, steps):
                t = step / steps
                coords.append(self.to_cartesian(CellPoint(
                    radial=previous.radial + (point.radial - previous.radial) * t,
                    angular=previous.angular + (point.angular - previous.angular) * t,
                ), rotation_deg))
            coords.append(self.to_cartesian(point, rotation_deg))
        return coords

    def make_path(self, vector: SmartVector, rotation_deg: float = 0.0) -> Dict[str, Any]:
        coords = self.polyline(vector, rotation_deg)

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


def cell_rotation_deg(cell_index: int, divisions: int, position: str) -> float:
    """Rotation of a cell about the ring centre; `divider` cells sit half a wedge on."""
    wedge = 360.0 / divisions
    rotation = cell_index * wedge
    if position == "divider":
        rotation += wedge / 2
    return rotation


def quad_points(
    start: CellPoint,
    control: CellPoint,
    end: CellPoint,
    steps: int = 8,
) -> List[CellPoint]:
    """
    Sample a quadratic bezier in cell space.

    Coarse is fine: `polyline` densifies afterwards, so the author picks the
    shape and the engine picks the fidelity. Samples are returned exactly as
    computed: nothing is clamped, because the analyzer enforces cell limits and
    overflow past a boundary is legitimate.
    """
    points = [start]
    for index in range(1, steps):
        t = index / steps
        inverse = 1.0 - t
        radial = inverse * inverse * start.radial + 2 * inverse * t * control.radial + t * t * end.radial
        angular = inverse * inverse * start.angular + 2 * inverse * t * control.angular + t * t * end.angular
        points.append(CellPoint(radial=radial, angular=angular))
    points.append(end)
    return points


def mirror_points(points: List[CellPoint]) -> List[CellPoint]:
    """Reflect a run across the cell centerline, preserving order."""
    return [CellPoint(point.radial, -point.angular) for point in points]


def side_touch_radial_within(context: MotifContext, low: float, high: float) -> Optional[float]:
    """
    The context's side-touch radial when it applies and lies strictly inside `(low, high)`, else None.

    Side touch applies to base motifs only: a slot child never uses it. A side edge whose radial
    range misses the value already ends at its nearest vertex, so it needs nothing extra.
    """
    radial = context.side_touch_radial
    if radial is None or context.slot:
        return None
    return radial if low < radial < high else None
