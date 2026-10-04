"""
SVG shape extraction for mandala designs.

Parses SVG element dictionaries into `Shape` objects carrying sampled polyline
points in absolute canvas coordinates, with each cell's rotation applied.

This is the front half of QA: `topology_validator` consumes these polylines and
does the actual connectivity and colorability analysis. The proximity-heuristic
validator that used to live here was replaced by that exact analysis and has
been removed.
"""

import math
import re
from typing import List, Dict, Any, Tuple, Optional
from dataclasses import dataclass


@dataclass
class Point:
    """A 2D point."""
    x: float
    y: float

    def distance_to(self, other: 'Point') -> float:
        return math.sqrt((self.x - other.x)**2 + (self.y - other.y)**2)

    def __hash__(self):
        return hash((round(self.x, 4), round(self.y, 4)))


@dataclass
class Shape:
    """Represents a shape extracted from SVG elements."""
    cell_id: str  # e.g., "ring-0-div-3"
    ring_index: int
    division_index: int
    is_closed: bool
    points: List[Point]  # Sampled points along the shape
    start_point: Point
    end_point: Point
    element_type: str  # 'path', 'circle', 'line', etc.
    raw_element: Dict[str, Any]


class ShapeExtractor:
    """
    Extracts Shape objects from SVG element dictionaries.
    Handles path parsing and point sampling.
    """

    def __init__(self, sample_resolution: int = 20, subdivide_lines: bool = True):
        self.sample_resolution = sample_resolution
        # Straight runs (L/H/V/Z) carry no curvature, so splitting them into
        # collinear points adds vertices without adding topology. Smart pattern
        # paths already arrive densely sampled, so callers validating those
        # should pass False.
        self.subdivide_lines = subdivide_lines

    @property
    def _line_steps(self) -> int:
        return self.sample_resolution if self.subdivide_lines else 1

    def extract_shapes(
        self,
        elements: List[Dict[str, Any]],
        cell_id: str,
        ring_index: int,
        division_index: int,
        rotation_angle: float,
        center: Tuple[float, float]
    ) -> List[Shape]:
        """
        Extract Shape objects from SVG elements.

        Args:
            elements: List of SVG element dicts
            cell_id: Identifier for this cell
            ring_index: Which ring
            division_index: Which division
            rotation_angle: Rotation applied to this cell (degrees)
            center: Center point for rotation

        Returns:
            List of Shape objects
        """
        shapes = []

        for elem in elements:
            tag = elem.get('tag')
            attrs = elem.get('attributes', {})

            if tag == 'path':
                shape = self._extract_path_shape(
                    attrs.get('d', ''),
                    elem, cell_id, ring_index, division_index,
                    rotation_angle, center
                )
                if shape:
                    shapes.append(shape)

            elif tag == 'circle':
                shape = self._extract_circle_shape(
                    attrs, elem, cell_id, ring_index, division_index,
                    rotation_angle, center
                )
                if shape:
                    shapes.append(shape)

            elif tag == 'line':
                shape = self._extract_line_shape(
                    attrs, elem, cell_id, ring_index, division_index,
                    rotation_angle, center
                )
                if shape:
                    shapes.append(shape)

            elif tag == 'ellipse':
                shape = self._extract_ellipse_shape(
                    attrs, elem, cell_id, ring_index, division_index,
                    rotation_angle, center
                )
                if shape:
                    shapes.append(shape)

        return shapes

    def _extract_path_shape(
        self,
        d: str,
        elem: Dict,
        cell_id: str,
        ring_index: int,
        division_index: int,
        rotation_angle: float,
        center: Tuple[float, float]
    ) -> Optional[Shape]:
        """Extract shape from SVG path data."""
        if not d:
            return None

        # Parse path and sample points
        points = self._parse_and_sample_path(d)
        if len(points) < 2:
            return None

        # Apply rotation
        rotated_points = [
            self._rotate_point(p, rotation_angle, center)
            for p in points
        ]

        # Check if closed (ends with Z or returns to start)
        is_closed = d.strip().upper().endswith('Z') or (
            len(rotated_points) >= 2 and
            rotated_points[0].distance_to(rotated_points[-1]) < 1.0
        )

        return Shape(
            cell_id=cell_id,
            ring_index=ring_index,
            division_index=division_index,
            is_closed=is_closed,
            points=rotated_points,
            start_point=rotated_points[0],
            end_point=rotated_points[-1],
            element_type='path',
            raw_element=elem
        )

    def _extract_circle_shape(
        self,
        attrs: Dict,
        elem: Dict,
        cell_id: str,
        ring_index: int,
        division_index: int,
        rotation_angle: float,
        center: Tuple[float, float]
    ) -> Optional[Shape]:
        """Extract shape from SVG circle."""
        try:
            cx = float(attrs.get('cx', 0))
            cy = float(attrs.get('cy', 0))
            r = float(attrs.get('r', 0))
        except (ValueError, TypeError):
            return None

        if r <= 0:
            return None

        # Sample points around the circle
        points = []
        for i in range(self.sample_resolution):
            angle = (i / self.sample_resolution) * 2 * math.pi
            p = Point(cx + r * math.cos(angle), cy + r * math.sin(angle))
            points.append(self._rotate_point(p, rotation_angle, center))

        # Close the circle
        points.append(points[0])

        return Shape(
            cell_id=cell_id,
            ring_index=ring_index,
            division_index=division_index,
            is_closed=True,
            points=points,
            start_point=points[0],
            end_point=points[-1],
            element_type='circle',
            raw_element=elem
        )

    def _extract_line_shape(
        self,
        attrs: Dict,
        elem: Dict,
        cell_id: str,
        ring_index: int,
        division_index: int,
        rotation_angle: float,
        center: Tuple[float, float]
    ) -> Optional[Shape]:
        """Extract shape from SVG line."""
        try:
            x1 = float(attrs.get('x1', 0))
            y1 = float(attrs.get('y1', 0))
            x2 = float(attrs.get('x2', 0))
            y2 = float(attrs.get('y2', 0))
        except (ValueError, TypeError):
            return None

        start = self._rotate_point(Point(x1, y1), rotation_angle, center)
        end = self._rotate_point(Point(x2, y2), rotation_angle, center)

        # Sample points along the line
        points = []
        for i in range(self.sample_resolution + 1):
            t = i / self.sample_resolution
            p = Point(
                start.x + t * (end.x - start.x),
                start.y + t * (end.y - start.y)
            )
            points.append(p)

        return Shape(
            cell_id=cell_id,
            ring_index=ring_index,
            division_index=division_index,
            is_closed=False,
            points=points,
            start_point=start,
            end_point=end,
            element_type='line',
            raw_element=elem
        )

    def _extract_ellipse_shape(
        self,
        attrs: Dict,
        elem: Dict,
        cell_id: str,
        ring_index: int,
        division_index: int,
        rotation_angle: float,
        center: Tuple[float, float]
    ) -> Optional[Shape]:
        """Extract shape from SVG ellipse."""
        try:
            cx = float(attrs.get('cx', 0))
            cy = float(attrs.get('cy', 0))
            rx = float(attrs.get('rx', 0))
            ry = float(attrs.get('ry', 0))
        except (ValueError, TypeError):
            return None

        if rx <= 0 or ry <= 0:
            return None

        # Sample points around the ellipse
        points = []
        for i in range(self.sample_resolution):
            angle = (i / self.sample_resolution) * 2 * math.pi
            p = Point(cx + rx * math.cos(angle), cy + ry * math.sin(angle))
            points.append(self._rotate_point(p, rotation_angle, center))

        points.append(points[0])

        return Shape(
            cell_id=cell_id,
            ring_index=ring_index,
            division_index=division_index,
            is_closed=True,
            points=points,
            start_point=points[0],
            end_point=points[-1],
            element_type='ellipse',
            raw_element=elem
        )

    def _parse_and_sample_path(self, d: str) -> List[Point]:
        """
        Parse SVG path data and return sampled points.
        Handles M, L, Q, C, A, Z commands.
        """
        points = []
        current = Point(0, 0)
        start = Point(0, 0)

        # Tokenize the path
        tokens = re.findall(r'[MLHVCSQTAZmlhvcsqtaz]|[-+]?[0-9]*\.?[0-9]+', d)

        i = 0
        while i < len(tokens):
            cmd = tokens[i] if tokens[i].isalpha() else None

            if cmd is None:
                i += 1
                continue

            i += 1

            if cmd in 'Mm':
                # Move to
                if i + 1 < len(tokens):
                    x, y = float(tokens[i]), float(tokens[i + 1])
                    if cmd == 'm':  # Relative
                        x += current.x
                        y += current.y
                    current = Point(x, y)
                    start = current
                    points.append(current)
                    i += 2

            elif cmd in 'Ll':
                # Line to
                while i + 1 < len(tokens) and not tokens[i].isalpha():
                    x, y = float(tokens[i]), float(tokens[i + 1])
                    if cmd == 'l':
                        x += current.x
                        y += current.y
                    # Sample along line
                    for t in range(1, self._line_steps + 1):
                        ratio = t / self._line_steps
                        p = Point(
                            current.x + ratio * (x - current.x),
                            current.y + ratio * (y - current.y)
                        )
                        points.append(p)
                    current = Point(x, y)
                    i += 2

            elif cmd in 'Hh':
                # Horizontal line
                if i < len(tokens) and not tokens[i].isalpha():
                    x = float(tokens[i])
                    if cmd == 'h':
                        x += current.x
                    for t in range(1, self._line_steps + 1):
                        ratio = t / self._line_steps
                        p = Point(current.x + ratio * (x - current.x), current.y)
                        points.append(p)
                    current = Point(x, current.y)
                    i += 1

            elif cmd in 'Vv':
                # Vertical line
                if i < len(tokens) and not tokens[i].isalpha():
                    y = float(tokens[i])
                    if cmd == 'v':
                        y += current.y
                    for t in range(1, self._line_steps + 1):
                        ratio = t / self._line_steps
                        p = Point(current.x, current.y + ratio * (y - current.y))
                        points.append(p)
                    current = Point(current.x, y)
                    i += 1

            elif cmd in 'Qq':
                # Quadratic bezier
                while i + 3 < len(tokens) and not tokens[i].isalpha():
                    cx, cy = float(tokens[i]), float(tokens[i + 1])
                    x, y = float(tokens[i + 2]), float(tokens[i + 3])
                    if cmd == 'q':
                        cx += current.x
                        cy += current.y
                        x += current.x
                        y += current.y
                    # Sample along quadratic bezier
                    for t in range(1, self.sample_resolution + 1):
                        ratio = t / self.sample_resolution
                        p = self._sample_quadratic_bezier(current, Point(cx, cy), Point(x, y), ratio)
                        points.append(p)
                    current = Point(x, y)
                    i += 4

            elif cmd in 'Cc':
                # Cubic bezier
                while i + 5 < len(tokens) and not tokens[i].isalpha():
                    c1x, c1y = float(tokens[i]), float(tokens[i + 1])
                    c2x, c2y = float(tokens[i + 2]), float(tokens[i + 3])
                    x, y = float(tokens[i + 4]), float(tokens[i + 5])
                    if cmd == 'c':
                        c1x += current.x
                        c1y += current.y
                        c2x += current.x
                        c2y += current.y
                        x += current.x
                        y += current.y
                    # Sample along cubic bezier
                    for t in range(1, self.sample_resolution + 1):
                        ratio = t / self.sample_resolution
                        p = self._sample_cubic_bezier(
                            current, Point(c1x, c1y), Point(c2x, c2y), Point(x, y), ratio
                        )
                        points.append(p)
                    current = Point(x, y)
                    i += 6

            elif cmd in 'Aa':
                # Arc - simplified handling (sample as line for now)
                if i + 6 < len(tokens):
                    # rx, ry, rotation, large-arc, sweep, x, y
                    x, y = float(tokens[i + 5]), float(tokens[i + 6])
                    if cmd == 'a':
                        x += current.x
                        y += current.y
                    # Simple linear interpolation (TODO: proper arc sampling)
                    for t in range(1, self.sample_resolution + 1):
                        ratio = t / self.sample_resolution
                        p = Point(
                            current.x + ratio * (x - current.x),
                            current.y + ratio * (y - current.y)
                        )
                        points.append(p)
                    current = Point(x, y)
                    i += 7

            elif cmd in 'Zz':
                # Close path
                if start.distance_to(current) > 0.1:
                    for t in range(1, self._line_steps + 1):
                        ratio = t / self._line_steps
                        p = Point(
                            current.x + ratio * (start.x - current.x),
                            current.y + ratio * (start.y - current.y)
                        )
                        points.append(p)
                current = start

            else:
                # Unknown command, skip
                i += 1

        return points

    def _sample_quadratic_bezier(self, p0: Point, p1: Point, p2: Point, t: float) -> Point:
        """Sample a point on a quadratic bezier curve."""
        mt = 1 - t
        x = mt * mt * p0.x + 2 * mt * t * p1.x + t * t * p2.x
        y = mt * mt * p0.y + 2 * mt * t * p1.y + t * t * p2.y
        return Point(x, y)

    def _sample_cubic_bezier(self, p0: Point, p1: Point, p2: Point, p3: Point, t: float) -> Point:
        """Sample a point on a cubic bezier curve."""
        mt = 1 - t
        x = (mt**3 * p0.x + 3 * mt**2 * t * p1.x +
             3 * mt * t**2 * p2.x + t**3 * p3.x)
        y = (mt**3 * p0.y + 3 * mt**2 * t * p1.y +
             3 * mt * t**2 * p2.y + t**3 * p3.y)
        return Point(x, y)

    def _rotate_point(self, point: Point, angle_deg: float, center: Tuple[float, float]) -> Point:
        """Rotate a point around a center."""
        if angle_deg == 0:
            return point

        angle_rad = math.radians(angle_deg)
        cos_a = math.cos(angle_rad)
        sin_a = math.sin(angle_rad)

        # Translate to origin
        dx = point.x - center[0]
        dy = point.y - center[1]

        # Rotate
        new_x = dx * cos_a - dy * sin_a
        new_y = dx * sin_a + dy * cos_a

        # Translate back
        return Point(new_x + center[0], new_y + center[1])
