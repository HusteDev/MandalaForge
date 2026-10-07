"""
Placement primitives for the assembler: placed ink records, tracing a cell-space
vector onto the page with per-coordinate radials, overflow runs, and a spatial
index over placed ink. Pure geometry and indexing: nothing here knows about plans.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Callable, List, Optional, Tuple

import shapely
from shapely.geometry import LineString, Point
from shapely.geometry.base import BaseGeometry
from shapely.strtree import STRtree

from motifs.geometry import MotifContext, PointTuple, SmartVector


@dataclass(eq=False)
class PlacedPath:
    ring_index: int
    cell_index: int
    position: str
    node_path: Tuple[int, ...]
    role: str
    coords: List[PointTuple]
    radials: List[float]
    closed: bool
    stroke_width: float


def trace(context: MotifContext, vector: SmartVector, rotation_deg: float) -> Tuple[List[PointTuple], List[float]]:
    """
    Page coordinates of `vector` (as `context.polyline` draws them) and the
    cell-space radial of each one. Radials are interpolated through the arc
    subdivision and exact at every original vertex.
    """
    source = list(vector.points)
    if vector.closed and len(source) > 1:
        source.append(source[0])

    coords = [context.to_cartesian(source[0], rotation_deg)]
    radials = [source[0].radial]
    for start, end in zip(source, source[1:]):
        segment = context.polyline(SmartVector([start, end]), rotation_deg)
        steps = len(segment) - 1
        coords.extend(segment[1:])
        radials.extend(start.radial + (end.radial - start.radial) * step / steps for step in range(1, steps))
        radials.append(end.radial)
    return coords, radials


def path_geometry(path: PlacedPath) -> BaseGeometry:
    return LineString(path.coords) if len(path.coords) > 1 else Point(path.coords[0])


# A run whose radials go less than this far past 0 or 1 is float noise on a boundary-exact vertex, not overflow.
OVERFLOW_EPSILON = 1e-9


def _overflow_side(radial: float) -> Optional[str]:
    if radial < 0.0:
        return "inward"
    if radial > 1.0:
        return "outward"
    return None


def boundary_crossing(path: PlacedPath, inside: int, outside: int, side: str, center: PointTuple) -> PointTuple:
    """
    Where the path between coordinates `inside` and `outside` crosses the ring
    boundary on `side`. The point lies on the drawn segment between the two
    coordinates, since an overflow run is ink and is checked as ink, and on the
    boundary circle: radius is linear in the cell-space parameter between two
    traced coordinates, which gives the circle's radius, and the segment from
    inside it to outside meets that circle once.
    """
    boundary = 0.0 if side == "inward" else 1.0
    radials = path.radials
    t = (boundary - radials[inside]) / (radials[outside] - radials[inside])
    cx, cy = center
    (x0, y0), (x1, y1) = path.coords[inside], path.coords[outside]
    r0, r1 = math.hypot(x0 - cx, y0 - cy), math.hypot(x1 - cx, y1 - cy)
    radius = r0 + (r1 - r0) * t
    # |p0 - c + s (p1 - p0)| = radius, a quadratic in s along the segment.
    dx, dy = x1 - x0, y1 - y0
    ox, oy = x0 - cx, y0 - cy
    a = dx * dx + dy * dy
    b = 2.0 * (ox * dx + oy * dy)
    c = ox * ox + oy * oy - radius * radius
    s = t
    discriminant = b * b - 4.0 * a * c
    if a > 0.0 and discriminant >= 0.0:
        root = math.sqrt(discriminant)
        roots = [r for r in ((-b - root) / (2.0 * a), (-b + root) / (2.0 * a)) if -1e-9 <= r <= 1.0 + 1e-9]
        if roots:
            s = min(roots, key=lambda r: abs(r - t))
    s = max(0.0, min(1.0, s))
    return (x0 + dx * s, y0 + dy * s)


def path_overflow(path: PlacedPath, center: PointTuple) -> List[Tuple[str, LineString]]:
    """
    Each maximal run of coordinates past the inner (`inward`) or outer
    (`outward`) ring boundary, extended at each end to the point where the path
    crosses that boundary. A run that goes less than `OVERFLOW_EPSILON` past
    the boundary is float noise on a vertex that lies on it, and is left out.
    """
    coords, radials = path.coords, path.radials
    last = len(coords) - 1

    runs: List[List] = []  # [side, first index, last index]
    for index, radial in enumerate(radials):
        side = _overflow_side(radial)
        if side is None:
            continue
        if runs and runs[-1][0] == side and runs[-1][2] == index - 1:
            runs[-1][2] = index
        else:
            runs.append([side, index, index])

    # A closed path repeats its first coordinate last, so a run through that point is one run.
    if path.closed and len(runs) > 1 and runs[0][1] == 0 and runs[-1][2] == last and runs[0][0] == runs[-1][0]:
        side, first, _ = runs.pop()
        runs[0] = [side, first, runs[0][2]]

    def excursion(side: str, first: int, final: int) -> float:
        indices = range(first, final + 1) if first <= final else [*range(first, last + 1), *range(0, final + 1)]
        return max(-radials[i] if side == "inward" else radials[i] - 1.0 for i in indices)

    parts: List[Tuple[str, LineString]] = []
    for side, first, final in runs:
        if excursion(side, first, final) < OVERFLOW_EPSILON:
            continue
        if first <= final:
            points = list(coords[first:final + 1])
        else:  # wrapped through the closing point
            points = list(coords[first:]) + list(coords[1:final + 1])
        if first > 0:
            points.insert(0, boundary_crossing(path, first - 1, first, side, center))
        if final < last:
            points.append(boundary_crossing(path, final + 1, final, side, center))
        if len(points) > 1:
            parts.append((side, LineString(points)))
    return parts


class InkIndex:
    """Spatial index over placed ink; the tree is rebuilt lazily after any change."""

    def __init__(self) -> None:
        self._paths: List[PlacedPath] = []
        self._geometries: List[BaseGeometry] = []
        self._tree: Optional[STRtree] = None

    def __len__(self) -> int:
        return len(self._paths)

    def add(self, path: PlacedPath) -> None:
        self._paths.append(path)
        self._geometries.append(path_geometry(path))
        self._tree = None

    def remove(self, path: PlacedPath) -> None:
        for index, existing in enumerate(self._paths):
            if existing is path:
                del self._paths[index]
                del self._geometries[index]
                self._tree = None
                return
        raise ValueError("path is not in the index")

    def rebuild(self) -> None:
        self._tree = STRtree(self._geometries)

    def _candidate_indices(self, geom: BaseGeometry) -> List[int]:
        if self._tree is None:
            self.rebuild()
        return sorted(int(index) for index in self._tree.query(geom))

    def candidates(self, geom: BaseGeometry) -> List[PlacedPath]:
        """Paths whose bounds meet `geom`'s, in insertion order."""
        return [self._paths[index] for index in self._candidate_indices(geom)]

    def first_hit(
        self, ray: LineString, exclude: Callable[[PlacedPath], bool]
    ) -> Optional[Tuple[PlacedPath, PointTuple, float]]:
        """The nearest point where `ray` meets ink not excluded, and its distance along the ray."""
        best: Optional[Tuple[PlacedPath, PointTuple, float]] = None
        for index in self._candidate_indices(ray):
            path = self._paths[index]
            if exclude(path):
                continue
            hit = ray.intersection(self._geometries[index])
            if hit.is_empty:
                continue
            for x, y in shapely.get_coordinates(hit):
                distance = ray.project(Point(x, y))
                if best is None or distance < best[2]:
                    best = (path, (float(x), float(y)), distance)
        return best
