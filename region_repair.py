"""
Oversized faces and the plan entries behind them (max-region-size spec 4.3).

Each face over the print-size cap is classified as a host interior, the open centre or background, and
matched to the plan through the ring, cell, position and node path every `PlacedPath` records. Symmetric
copies of a face share a key, so one plan change repairs the whole set.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Dict, List, Optional, Sequence, Tuple

from shapely.geometry import LineString, Point, Polygon
from shapely.geometry.base import BaseGeometry

from motifs.geometry import PointTuple
from placement import PlacedPath
from topology_validator import RegionInfo

FACE_KINDS = ("host", "background", "centre")
# Roles of closed outlines that can host a face: base and back outlines, slot children and detail echoes.
HOST_ROLES = ("base", "back", "slot", "detail")

# (ring_index, cell_index, position, node_path) of one placed node.
NodeKey = Tuple[int, int, str, Tuple[int, ...]]


@dataclass
class OversizedFace:
    region: RegionInfo
    kind: str
    ring_index: int
    position: Optional[str] = None
    node_path: Optional[Tuple[int, ...]] = None
    on_back: bool = False
    bordering: Tuple[NodeKey, ...] = ()

    @property
    def key(self) -> Tuple:
        """The plan entry behind the face; every symmetric copy of it has the same key."""
        if self.kind == "host":
            return ("host", self.ring_index, self.position, self.node_path[0], tuple(self.node_path[1:]), self.on_back)
        if self.kind == "background":
            return ("background", self.ring_index)
        return ("centre", 0)


@dataclass
class FaceSet:
    key: Tuple
    kind: str
    ring_index: int
    faces: List[OversizedFace] = field(default_factory=list)

    @property
    def area(self) -> float:
        return sum(face.region.area for face in self.faces)

    @property
    def first(self) -> OversizedFace:
        return self.faces[0]


def _node_key(path: PlacedPath) -> NodeKey:
    return (path.ring_index, path.cell_index, path.position, tuple(path.node_path))


def _outline(path: PlacedPath) -> Optional[BaseGeometry]:
    """The area a closed path encloses, or None when its coordinates enclose nothing."""
    if len(path.coords) < 3:
        return None
    polygon = Polygon(path.coords)
    if not polygon.is_valid:
        polygon = polygon.buffer(0)
    return None if polygon.is_empty or polygon.area <= 0.0 else polygon


def _within_node(key: NodeKey, host: NodeKey) -> bool:
    """True when `key` is the host node itself or one of its descendants (a slot child below it)."""
    return key[:3] == host[:3] and key[3][:len(host[3])] == host[3]


def _annulus(center: PointTuple, inner: float, outer: float) -> BaseGeometry:
    disc = Point(center).buffer(outer, quad_segs=64)
    return disc.difference(Point(center).buffer(inner, quad_segs=64)) if inner > 0.0 else disc


def _ring_holding(rings: Sequence[Dict[str, float]], center: PointTuple, point: PointTuple) -> Optional[int]:
    radial = math.hypot(point[0] - center[0], point[1] - center[1])
    for index, ring in enumerate(rings):
        if ring["inner_radius"] <= radial < ring["outer_radius"]:
            return index
    return None


def _background_owner(region: RegionInfo, rings: Sequence[Dict[str, float]], center: PointTuple) -> int:
    """The ring whose annulus holds the largest share of the face, ties to the ring holding its label point."""
    if not rings:
        return 0
    labelled = _ring_holding(rings, center, region.label_point)
    shares = [region.polygon.intersection(_annulus(center, r["inner_radius"], r["outer_radius"])).area for r in rings]
    best = max(shares)
    tied = [i for i, share in enumerate(shares) if math.isclose(share, best, rel_tol=1e-9, abs_tol=1e-6)]
    return labelled if labelled in tied else tied[0]


def classify_faces(regions: Sequence[RegionInfo], paths: Sequence[PlacedPath],
                   rings: Sequence[Dict[str, float]], center: PointTuple) -> List[OversizedFace]:
    """
    Classify each face, in order: the centre (it covers the design centre; ring 0), a host interior (the
    smallest closed host-role outline, widened by its stroke, that covers it), else background (owned by
    the ring holding most of its area, with the nodes whose paths border it).

    A covering outline is not the face's host when the face also borders the closed outline of another
    node lying inside it: the face is then the background around that node, not this outline's interior.
    A node's own descendants (slot children) and its echoes and back layer do not disqualify it.
    """
    centre_point = Point(center)
    outlines = []
    for path in paths:
        if path.closed and path.role in HOST_ROLES:
            polygon = _outline(path)
            if polygon is not None:
                outlines.append((path, polygon, polygon.buffer(path.stroke_width)))
    lines = [(path, LineString(path.coords)) for path in paths if len(path.coords) >= 2]

    faces = []
    for region in regions:
        face = region.polygon
        if face.covers(centre_point):
            faces.append(OversizedFace(region, "centre", 0))
            continue
        boundary = face.boundary
        bordering = sorted({_node_key(path) for path, line in lines if line.distance(boundary) <= path.stroke_width})
        host = None
        for path, polygon, widened in outlines:
            if host is not None and polygon.area >= host[1].area:
                continue
            if not widened.covers(face):
                continue
            key = _node_key(path)
            foreign_inside = any(
                not _within_node(_node_key(other), key) and other_polygon.within(widened)
                and _node_key(other) in bordering
                for other, other_polygon, _ in outlines
            )
            if not foreign_inside:
                host = (path, polygon)
        if host is not None:
            path = host[0]
            faces.append(OversizedFace(region, "host", path.ring_index, path.position, tuple(path.node_path),
                                       on_back=path.role == "back"))
            continue
        faces.append(OversizedFace(region, "background", _background_owner(region, rings, center),
                                   bordering=tuple(bordering)))
    return faces


def face_sets(faces: Sequence[OversizedFace]) -> List[FaceSet]:
    """The faces grouped by key, sorted by (ring_index, FACE_KINDS.index(kind), key)."""
    grouped: Dict[Tuple, FaceSet] = {}
    for face in faces:
        key = face.key
        if key not in grouped:
            grouped[key] = FaceSet(key, face.kind, face.ring_index, [])
        grouped[key].faces.append(face)
    return sorted(grouped.values(), key=lambda s: (s.ring_index, FACE_KINDS.index(s.kind), s.key))
