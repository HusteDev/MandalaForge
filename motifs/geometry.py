"""
Geometry primitives for the motif engine.

Ported by copying from the retired smart-pattern analyzer so this package is
self-contained. Motifs are authored in normalized cell space: `radial` runs 0 to
1 from the inner to the outer boundary of a ring, and `angular` runs -1 to 1
across the wedge. `MotifContext` converts that space to canvas pixels.

Unlike the old context, conversion does not clamp: the analyzer enforces cell
limits, and overflow past a boundary is legitimate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
import random
import zlib
from typing import Any, Dict, List, Optional, Tuple


PointTuple = Tuple[float, float]

# A rendered segment may span at most this much arc before it is subdivided.
# 4 degrees holds the chord/arc error under ~0.25px at the largest canvas radius.
MAX_SEGMENT_ARC_DEGREES = 4.0


def salted_seed(seed: int, salt: str) -> int:
    """A seed forked by a salt; crc32 keeps it stable across processes (unlike hash())."""
    return seed * 31 + zlib.crc32(salt.encode("utf-8"))


WEIGHTS = ("outline", "detail")
DETAIL_WEIGHT_SHARE = 0.6


@dataclass(frozen=True)
class CellPoint:
    radial: float
    angular: float


@dataclass
class SmartVector:
    points: List[CellPoint]
    closed: bool = False
    # "outline" strokes at the full width, "detail" at DETAIL_WEIGHT_SHARE of it; "back" layers draw beneath the base ink.
    weight: str = "outline"
    layer: str = "front"


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
    # Seed shared by every cell of a ring with the same motif and position, and this node's own stream seed.
    ring_stream_seed: int = 0
    node_seed: int = 0
    # Rebuilt from ring_stream_seed on every construction, so dataclasses.replace yields a fresh, identical stream.
    ring_rng: random.Random = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        self.ring_rng = random.Random(self.ring_stream_seed)

    @property
    def ring_depth(self) -> float:
        return self.outer_radius - self.inner_radius

    @property
    def half_angle(self) -> float:
        return self.wedge_angle / 2

    def stroke_for(self, weight: str) -> float:
        """Stroke width in pixels for a line weight."""
        if weight not in WEIGHTS:
            raise ValueError(f"Line weight must be one of {WEIGHTS}, got {weight!r}")
        return self.stroke_width * (DETAIL_WEIGHT_SHARE if weight == "detail" else 1.0)

    def clearance_px(self, weight_a: str = "outline", weight_b: str = "outline") -> float:
        """Centreline-to-centreline gap that leaves `min_white_space` between two lines' edges."""
        return self.min_white_space + (self.stroke_for(weight_a) + self.stroke_for(weight_b)) / 2.0

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

    def to_cell(self, point: PointTuple, rotation_deg: float = 0.0) -> CellPoint:
        """The cell point of a canvas position in the cell turned by `rotation_deg`; inverts `to_cartesian`."""
        dx, dy = point[0] - self.center[0], point[1] - self.center[1]
        angle = math.remainder(math.degrees(math.atan2(dy, dx)) - rotation_deg, 360.0)
        return CellPoint(
            radial=(math.hypot(dx, dy) - self.inner_radius) / self.ring_depth,
            angular=angle / self.half_angle,
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


def cubic_points(
    start: CellPoint,
    control1: CellPoint,
    control2: CellPoint,
    end: CellPoint,
    steps: int = 8,
) -> List[CellPoint]:
    """Sample a cubic bezier in cell space: `steps + 1` points, exact ends, nothing clamped."""
    points = [start]
    for index in range(1, steps):
        t = index / steps
        u = 1.0 - t
        w0, w1, w2, w3 = u * u * u, 3 * u * u * t, 3 * u * t * t, t * t * t
        points.append(CellPoint(
            radial=w0 * start.radial + w1 * control1.radial + w2 * control2.radial + w3 * end.radial,
            angular=w0 * start.angular + w1 * control1.angular + w2 * control2.angular + w3 * end.angular,
        ))
    points.append(end)
    return points


def page_arc_points(
    context: MotifContext,
    centre: CellPoint,
    radius_px: float,
    start_deg: float,
    end_deg: float,
    steps: int = 16,
) -> List[CellPoint]:
    """
    An arc that is round on the page, sampled in cell space.

    Angles are in the cell's local page frame at `centre`: 0 degrees points outward along the
    radius, 90 degrees toward increasing angular. Pixel offsets are converted at the centre's radial.
    """
    points = []
    for index in range(steps + 1):
        theta = math.radians(start_deg + (end_deg - start_deg) * index / steps)
        points.append(CellPoint(
            radial=centre.radial + context.px_to_radial(radius_px * math.cos(theta)),
            angular=centre.angular + context.px_to_angular(radius_px * math.sin(theta), centre.radial),
        ))
    return points


def page_circle_points(
    context: MotifContext,
    centre: CellPoint,
    radius_px: float,
    steps: int = 24,
) -> List[CellPoint]:
    """A closed circle round on the page; the first point is not repeated at the end."""
    return page_arc_points(context, centre, radius_px, 0.0, 360.0, steps)[:-1]


def insert_vertex_on_outline(
    points: List[CellPoint],
    closed: bool,
    point: CellPoint,
    tolerance: float = 1e-9,
) -> List[CellPoint]:
    """
    Insert `point` into the outline segment it lies on, in cell space.

    Returns the input unchanged when `point` is already a vertex or lies on no segment.
    """
    def near(a: CellPoint, b: CellPoint) -> bool:
        return abs(a.radial - b.radial) <= tolerance and abs(a.angular - b.angular) <= tolerance

    if any(near(vertex, point) for vertex in points):
        return points
    count = len(points)
    for index in range(count if closed else count - 1):
        a, b = points[index], points[(index + 1) % count]
        dr, da = b.radial - a.radial, b.angular - a.angular
        length_sq = dr * dr + da * da
        if length_sq == 0:
            continue
        t = ((point.radial - a.radial) * dr + (point.angular - a.angular) * da) / length_sq
        if not 0.0 < t < 1.0:
            continue
        if math.hypot(a.radial + dr * t - point.radial, a.angular + da * t - point.angular) <= tolerance:
            return points[:index + 1] + [point] + points[index + 1:]
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


# A band's side edge reaches at least this far past the side-touch radial on each side.
SIDE_EDGE_MARGIN = 0.05


def side_edge_containing_touch(context: MotifContext, low: float, high: float) -> Tuple[float, float]:
    """
    A side edge `(low, high)` widened so the side-touch radial lies strictly inside it, at least
    `SIDE_EDGE_MARGIN` from each end, clamped to the radial limits; unchanged when side touch does
    not apply. Bands drawn from different sequence entries then all carry the shared side vertex.
    """
    radial = context.side_touch_radial
    if radial is None or context.slot:
        return low, high
    lowest, highest = context.radial_limits
    return max(lowest, min(low, radial - SIDE_EDGE_MARGIN)), min(highest, max(high, radial + SIDE_EDGE_MARGIN))
