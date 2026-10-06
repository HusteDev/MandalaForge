"""
Assembler: turns a `DesignPlan` into placed, indexed ink.

Pass one draws every motif tree of every cell in cell space, rotates it into
place on the page and indexes the ink. Attachments draw nothing yet: their reach
ends are recorded for pass two, which resolves overflow, reaches and contact.

Every `PlacedNode` keeps its recipe, the integer seed of its stream, its context
and its parent, so any node can be regenerated exactly with different limits.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import math
import random
from typing import Callable, Dict, List, Optional, Tuple

import shapely
from shapely.geometry import LineString, Point
from shapely.geometry.base import BaseGeometry
from shapely.strtree import STRtree

from composer import CellRecipe, Composer, DesignPlan, RingPlan, node_seed
from motifs import find_motif, safe_motif
from motifs.contract import MotifError, MotifInstance, ReachEnd
from motifs.geometry import MotifContext, PointTuple, SmartVector, cell_rotation_deg


POSITIONS = ("centre", "divider")

# A base whose generator keeps failing is replaced at most this many times.
MAX_BASE_REPLACEMENTS = 3

# Attachment i draws from stream depth ATTACHMENT_DEPTH + i; slot nesting only uses depths 0 to 2.
ATTACHMENT_DEPTH = 10

PendingReach = Tuple["PlacedNode", ReachEnd, PointTuple, float]


class AssemblyError(ValueError):
    """A cell could not be assembled, even after replacing its base motif."""


def stroke_width_for(complexity: float) -> float:
    return 1.0 + 1.5 * (1.0 - complexity * 0.5)


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


@dataclass(eq=False)
class PlacedNode:
    ring_index: int
    cell_index: int
    position: str
    node_path: Tuple[int, ...]
    recipe: CellRecipe
    rng_seed: int
    instance: MotifInstance
    paths: List[PlacedPath]
    context: MotifContext
    parent: Optional[PlacedNode]
    attachment_seeds: List[int] = field(default_factory=list)


# --------------------------------------------------------------------- geometry


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


def _overflow_side(radial: float) -> Optional[str]:
    if radial < 0.0:
        return "inward"
    if radial > 1.0:
        return "outward"
    return None


def path_overflow(path: PlacedPath) -> List[Tuple[str, LineString]]:
    """
    Each maximal run of coordinates past the inner (`inward`) or outer
    (`outward`) ring boundary, extended at each end to the point where the path
    crosses that boundary.
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

    def crossing(inside: int, outside: int, side: str) -> PointTuple:
        boundary = 0.0 if side == "inward" else 1.0
        t = (boundary - radials[inside]) / (radials[outside] - radials[inside])
        (x0, y0), (x1, y1) = coords[inside], coords[outside]
        return (x0 + (x1 - x0) * t, y0 + (y1 - y0) * t)

    parts: List[Tuple[str, LineString]] = []
    for side, first, final in runs:
        if first <= final:
            points = list(coords[first:final + 1])
        else:  # wrapped through the closing point
            points = list(coords[first:]) + list(coords[1:final + 1])
        if first > 0:
            points.insert(0, crossing(first - 1, first, side))
        if final < last:
            points.append(crossing(final + 1, final, side))
        if len(points) > 1:
            parts.append((side, LineString(points)))
    return parts


# ------------------------------------------------------------------- ink index


class InkIndex:
    """Spatial index over placed ink; the tree is rebuilt lazily after any change."""

    def __init__(self) -> None:
        self._paths: List[PlacedPath] = []
        self._geometries: List[BaseGeometry] = []
        self._tree: Optional[STRtree] = None

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
        """The nearest point where `ray` meets ink not excluded, and its distance from the ray's start."""
        start_x, start_y = ray.coords[0]
        best: Optional[Tuple[PlacedPath, PointTuple, float]] = None
        for index in self._candidate_indices(ray):
            path = self._paths[index]
            if exclude(path):
                continue
            hit = ray.intersection(self._geometries[index])
            if hit.is_empty:
                continue
            for x, y in shapely.get_coordinates(hit):
                distance = math.hypot(x - start_x, y - start_y)
                if best is None or distance < best[2]:
                    best = (path, (float(x), float(y)), distance)
        return best


# ------------------------------------------------------------------- the design


@dataclass
class AssembledDesign:
    plan: DesignPlan
    paths: List[PlacedPath]
    nodes: List[PlacedNode]
    reaches: List[PlacedPath]
    dropped_children: int

    def polylines(self) -> List[List[PointTuple]]:
        return [path.coords for path in self.paths]

    def base_mask(self) -> List[bool]:
        return [path.role == "base" for path in self.paths]

    def ring_ids(self) -> List[int]:
        return [path.ring_index for path in self.paths]

    def overflow_parts(self) -> List[Tuple[int, LineString]]:
        return [(path.ring_index, line) for path in self.paths for _, line in path_overflow(path)]


# -------------------------------------------------------------------- assembler


def _registry_entry(recipe: CellRecipe) -> Dict:
    return find_motif(recipe.motif) or safe_motif(recipe.category)


def _angular_limit(ring: RingPlan, position: str) -> float:
    if ring.centre_share >= 1.0:
        return 1.0
    return ring.centre_share if position == "centre" else 1.0 - ring.centre_share


class Assembler:
    def __init__(
        self,
        plan: DesignPlan,
        ring_geometry: List[Dict[str, float]],
        center: PointTuple,
        complexity: float,
        min_white_space: float,
        composer: Composer,
    ) -> None:
        self.plan = plan
        self.ring_geometry = ring_geometry
        self.center = center
        self.complexity = complexity
        self.min_white_space = min_white_space
        self.composer = composer
        self.stroke_width = stroke_width_for(complexity)
        self._reset()

    def _reset(self) -> None:
        self.nodes: List[PlacedNode] = []
        self.paths: List[PlacedPath] = []
        self.pending_reaches: List[PendingReach] = []
        self.dropped_children = 0
        self.index = InkIndex()

    def assemble(self) -> AssembledDesign:
        self.pass_one()
        return AssembledDesign(self.plan, list(self.paths), list(self.nodes), [], self.dropped_children)

    # ----------------------------------------------------------- pass one

    def pass_one(self) -> None:
        """Draw, place and index every cell, rings innermost first."""
        self._reset()
        for ring in self.plan.rings:
            self._place_ring(ring)

    def _place_ring(self, ring: RingPlan) -> None:
        """Place the ring's cells; a failing base is replaced and the ring placed again."""
        replacements: Dict[Tuple[int, str], int] = {}
        while True:
            mark = (len(self.nodes), len(self.paths), len(self.pending_reaches), self.dropped_children)
            failure = self._place_cells(ring)
            if failure is None:
                return
            self._rewind(mark)
            cell_index, position, error = failure
            seq_pos = cell_index % len(ring.sequence)
            count = replacements.get((seq_pos, position), 0)
            if count >= MAX_BASE_REPLACEMENTS or not self.composer.replace_node(ring, seq_pos, position, "generation"):
                raise AssemblyError(
                    f"ring {ring.ring_index} cell {cell_index} ({position}): base motif failed "
                    f"after {count} replacements: {error}"
                ) from error
            replacements[(seq_pos, position)] = count + 1

    def _place_cells(self, ring: RingPlan) -> Optional[Tuple[int, str, MotifError]]:
        """Place every cell in index order; return the first base failure, if any."""
        for cell_index in range(ring.divisions):
            seq_pos = cell_index % len(ring.sequence)
            entry = ring.sequence[seq_pos]
            for position in POSITIONS:
                recipe = entry.centre if position == "centre" else entry.divider
                if recipe is None:
                    continue
                entry_info = _registry_entry(recipe)
                limits = (-entry_info["max_overflow_inward"], 1.0 + entry_info["max_overflow_outward"])
                try:
                    base = self._place_node(ring, cell_index, position, recipe, (seq_pos,), limits, None, None)
                except MotifError as error:
                    return cell_index, position, error
                self._place_slot_children(ring, base)
        return None

    def _rewind(self, mark: Tuple[int, int, int, int]) -> None:
        nodes, paths, reaches, dropped = mark
        for path in self.paths[paths:]:
            self.index.remove(path)
        del self.nodes[nodes:]
        del self.paths[paths:]
        del self.pending_reaches[reaches:]
        self.dropped_children = dropped

    def _place_slot_children(self, ring: RingPlan, parent: PlacedNode) -> None:
        """Place the slot child chain under `parent`, dropping a child that cannot be placed."""
        recipe = parent.recipe.slot_child
        if recipe is None:
            return
        slot = parent.instance.declaration.slot
        child = None
        if not recipe.dropped and slot:
            try:
                child = self._place_node(
                    ring, parent.cell_index, parent.position, recipe,
                    parent.node_path + (0,), (0.0, 1.0), slot, parent,
                )
            except MotifError:
                child = None
        if child is None:
            recipe.dropped = True
            self.dropped_children += 1
            return
        self._place_slot_children(ring, child)

    def _context(self, ring: RingPlan, position: str, rng_seed: int, radial_limits: Tuple[float, float],
                 slot: Optional[list]) -> MotifContext:
        geometry = self.ring_geometry[ring.ring_index]
        return MotifContext(
            inner_radius=geometry["inner_radius"],
            outer_radius=geometry["outer_radius"],
            wedge_angle=360.0 / ring.divisions,
            center=self.center,
            stroke_width=self.stroke_width,
            complexity=self.complexity,
            min_white_space=self.min_white_space,
            rng=random.Random(rng_seed),
            position=position,
            angular_limits=_angular_limit(ring, position),
            radial_limits=radial_limits,
            slot=slot,
        )

    def _place_node(
        self,
        ring: RingPlan,
        cell_index: int,
        position: str,
        recipe: CellRecipe,
        node_path: Tuple[int, ...],
        radial_limits: Tuple[float, float],
        slot: Optional[list],
        parent: Optional[PlacedNode],
    ) -> PlacedNode:
        """Generate one node, place and index its ink, and record its attachments' reach ends."""
        depth = len(node_path) - 1
        rng_seed = node_seed(ring.ring_seed, ring.ring_index, node_path[0], depth, position)
        context = self._context(ring, position, rng_seed, radial_limits, slot)
        instance = _registry_entry(recipe)["generator"](context)

        rotation = cell_rotation_deg(cell_index, ring.divisions, position)
        role = "base" if parent is None else "slot"
        paths = []
        for vector in instance.vectors:
            coords, radials = trace(context, vector, rotation)
            paths.append(PlacedPath(
                ring.ring_index, cell_index, position, node_path, role,
                coords, radials, vector.closed, self.stroke_width,
            ))

        node = PlacedNode(
            ring.ring_index, cell_index, position, node_path, recipe,
            rng_seed, instance, paths, context, parent,
        )
        self.nodes.append(node)
        for path in paths:
            self.paths.append(path)
            self.index.add(path)
        self._record_reaches(ring, node, rotation)
        return node

    def _record_reaches(self, ring: RingPlan, node: PlacedNode, rotation: float) -> None:
        """Generate each attachment with the node's context and keep only its reach ends."""
        for offset, attachment in enumerate(node.recipe.attachments):
            seed = node_seed(ring.ring_seed, ring.ring_index, node.node_path[0], ATTACHMENT_DEPTH + offset, node.position)
            node.attachment_seeds.append(seed)
            context = replace(node.context, radial_limits=(0.0, 1.0), rng=random.Random(seed))
            declaration = _registry_entry(attachment)["generator"](context).declaration
            for reach_end in declaration.reach_ends:
                page_point = node.context.to_cartesian(reach_end.point, rotation)
                self.pending_reaches.append((node, reach_end, page_point, rotation))
