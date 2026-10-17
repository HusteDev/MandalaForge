"""
Oversized faces and the plan entries behind them (max-region-size spec 4.3).

Each face over the print-size cap is classified as a host interior, the open centre or background, and
matched to the plan through the ring, cell, position and node path every `PlacedPath` records. Symmetric
copies of a face share a key, so one plan change repairs the whole set.

`RegionRepair` then climbs the repair ladder (spec 5): each step edits a deep copy of the plan, re-assembles
and re-validates it, and is kept only when the design stays valid with no more oversized area.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import math
from typing import TYPE_CHECKING, Dict, List, Optional, Sequence, Tuple

from shapely.geometry import LineString, Point, Polygon
from shapely.geometry.base import BaseGeometry

from assembler import AssembledDesign
from composer import DesignPlan, RingPlan, node_rng, recipe_at
from motifs import find_motif, safe_motif
from motifs.embellish import INTERIOR_FILLS
from motifs.geometry import PointTuple
from placement import PlacedPath
from topology_validator import RegionInfo, TopologyReport

if TYPE_CHECKING:
    from coloring_generator import DesignGenerator

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


# ------------------------------------------------------------------ the repair ladder (max-region spec 5)

# At most this many face sets are handled per design.
MAX_LADDER_SETS = 8


@dataclass
class Trial:
    """
    One assembled candidate design: `source_plan` is the plan as it stood before assembly (what a replay
    assembles), `plan` the plan after it (with any fallbacks the assembly applied).
    """
    source_plan: DesignPlan
    plan: DesignPlan
    assembled: AssembledDesign
    report: TopologyReport
    polylines: List
    sets: List[FaceSet]

    @property
    def oversized_area(self) -> float:
        return sum(face_set.area for face_set in self.sets)


class RegionRepair:
    """
    Climbs the repair ladder for a valid design with oversized faces. Every step edits a deep copy of the
    current trial's plan, records the change in its `repairs`, and re-assembles and re-validates it through
    the generator; the step's trial is kept only when it is valid and leaves no more oversized area.
    """

    def __init__(self, generator: "DesignGenerator"):
        self.generator = generator

    def run(self, first: Trial) -> Trial:
        """Handle the current trial's face sets in order, each once, at most `MAX_LADDER_SETS` of them."""
        current = first
        handled: set = set()
        while len(handled) < MAX_LADDER_SETS:
            face_set = next((s for s in current.sets if s.key not in handled), None)
            if face_set is None:
                break
            handled.add(face_set.key)
            if face_set.kind == "host":
                current = self.step_host(current, face_set)
        return current

    def step_host(self, trial: Trial, face_set: FaceSet) -> Trial:
        """
        Step 1, detail inside the host: echo, then the interior fill the host accepts, then a slot child (when
        the placed host declares a slot), then a dot, each kept or undone in turn, until the set is gone.
        """
        face = face_set.first
        ring_index, position, node_path, on_back = face.ring_index, face.position, face.node_path, face.on_back
        current = trial
        for candidate in ("echo", "fill", "slot", "dot"):
            if all(s.key != face_set.key for s in current.sets):
                break
            plan = deepcopy(current.plan)
            ring = _ring_of(plan, ring_index)
            if ring is None:
                break
            composer = self.generator._new_composer()
            composer.adopt(plan)
            change = None
            if candidate == "slot":
                if not on_back and self._declares_slot(current, ring_index, position, node_path):
                    rng = node_rng(ring.ring_seed, ring_index, node_path[0], len(node_path) - 1, position, "repair:1")
                    if composer.add_slot_child(ring, position, node_path, rng):
                        change = f"slot_child:{recipe_at(ring, position, node_path).slot_child.motif}"
            else:
                name = candidate if candidate != "fill" else self._interior_fill(ring, position, node_path, on_back)
                if name is not None and composer.add_embellishment(ring, position, node_path, on_back, name):
                    change = f"embellishment:{name}"
            if change is None:
                continue
            plan.repairs.append({"step": 1, "kind": face_set.kind, "ring": ring_index, "change": change})
            current = self._keep_better(current, self.generator._trial(plan))
        return current

    @staticmethod
    def _keep_better(current: Trial, trial: Optional[Trial]) -> Trial:
        """`trial` when it assembled, is valid and leaves no more oversized area than `current`, else `current`."""
        if trial is not None and trial.report.is_valid and trial.oversized_area <= current.oversized_area:
            return trial
        return current

    @staticmethod
    def _interior_fill(ring: RingPlan, position: str, node_path: Tuple[int, ...], on_back: bool) -> Optional[str]:
        """The interior fill the host accepts; when it accepts both, one drawn from the node's repair stream."""
        host = recipe_at(ring, position, node_path, on_back)
        if host is None:
            return None
        entry = find_motif(host.motif) or safe_motif(host.category)
        accepted = [name for name in INTERIOR_FILLS if name in entry.get("embellishments", ())]
        if len(accepted) < 2:
            return accepted[0] if accepted else None
        rng = node_rng(ring.ring_seed, ring.ring_index, node_path[0], len(node_path) - 1, position, "repair:1")
        return rng.choice(accepted)

    @staticmethod
    def _declares_slot(trial: Trial, ring_index: int, position: str, node_path: Tuple[int, ...]) -> bool:
        """Whether the placed host (its first cell) declares a non-empty slot."""
        for node in trial.assembled.nodes:
            if node.ring_index == ring_index and node.position == position and tuple(node.node_path) == node_path:
                return node.instance is not None and bool(node.instance.declaration.slot)
        return False


def _ring_of(plan: DesignPlan, ring_index: int) -> Optional[RingPlan]:
    return next((ring for ring in plan.rings if ring.ring_index == ring_index), None)
