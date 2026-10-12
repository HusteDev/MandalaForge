"""Shapes laid out in page pixels about a cell point, then mapped into the cell, so they are true to the page."""

from __future__ import annotations

import math
from typing import List, Tuple

from motifs.geometry import CellPoint, MotifContext


def page_offsets(context: MotifContext, centre: CellPoint, offsets: List[Tuple[float, float]]) -> List[CellPoint]:
    """
    Cell points at page-pixel `offsets` from `centre`, each `(along, across)`: `along` outward on the radius
    through the centre, `across` toward increasing angular.
    """
    cx, cy = context.to_cartesian(centre)
    out_x, out_y = cx - context.center[0], cy - context.center[1]
    length = math.hypot(out_x, out_y)
    out_x, out_y = out_x / length, out_y / length
    side_x, side_y = context.to_cartesian(CellPoint(centre.radial, centre.angular + 1e-3))
    side_x, side_y = side_x - cx, side_y - cy
    turn = 1.0 if out_x * side_y - out_y * side_x >= 0 else -1.0  # which page normal is increasing angular
    return [context.to_cell((cx + along * out_x - turn * across * out_y, cy + along * out_y + turn * across * out_x))
            for along, across in offsets]


def polar_offsets(radii_and_angles: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
    """`(radius_px, theta)` pairs, theta in radians from outward toward increasing angular, as page offsets."""
    return [(r * math.cos(theta), r * math.sin(theta)) for r, theta in radii_and_angles]
