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
import random
from typing import Dict, List, Optional, Tuple

from shapely.geometry import LineString

from composer import CellRecipe, Composer, DesignPlan, RingPlan, node_seed
from motifs import find_motif, safe_motif
from motifs.contract import MotifError, MotifInstance, ReachEnd
from motifs.geometry import MotifContext, PointTuple, cell_rotation_deg
from placement import InkIndex, PlacedPath, path_overflow, trace


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
class PlacedNode:
    """
    One generated motif placed in one cell. Regenerate it with
    `replace(node.context, rng=random.Random(node.rng_seed))`: the stored context's stream is spent.
    """

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


# ------------------------------------------------------------------- the design


@dataclass
class AssembledDesign:
    plan: DesignPlan
    paths: List[PlacedPath]
    nodes: List[PlacedNode]
    reaches: List[PlacedPath]
    dropped_children: int
    center: PointTuple

    def polylines(self) -> List[List[PointTuple]]:
        return [path.coords for path in self.paths]

    def base_mask(self) -> List[bool]:
        return [path.role == "base" for path in self.paths]

    def ring_ids(self) -> List[int]:
        return [path.ring_index for path in self.paths]

    def overflow_parts(self) -> List[Tuple[int, LineString]]:
        return [(path.ring_index, line) for path in self.paths for _, line in path_overflow(path, self.center)]


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
        self.dropped_attachments = 0
        self.index = InkIndex()

    def assemble(self) -> AssembledDesign:
        self.pass_one()
        return AssembledDesign(
            self.plan, list(self.paths), list(self.nodes), [], self.dropped_children, self.center
        )

    # ----------------------------------------------------------- pass one

    def pass_one(self) -> None:
        """Draw, place and index every cell, rings innermost first."""
        self._reset()
        for ring in self.plan.rings:
            self._place_ring(ring)

    def _place_ring(self, ring: RingPlan) -> None:
        """Place the ring's cells; a failing base is replaced and the ring placed again."""
        if not ring.sequence:
            raise AssemblyError(f"ring {ring.ring_index} has an empty sequence")
        replacements: Dict[Tuple[int, str], int] = {}
        while True:
            mark = self._mark()
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

    def _mark(self) -> Tuple[int, int, int, int, int]:
        return (len(self.nodes), len(self.paths), len(self.pending_reaches),
                self.dropped_children, self.dropped_attachments)

    def _rewind(self, mark: Tuple[int, int, int, int, int]) -> None:
        nodes, paths, reaches, self.dropped_children, self.dropped_attachments = mark
        for path in self.paths[paths:]:
            self.index.remove(path)
        del self.nodes[nodes:]
        del self.paths[paths:]
        del self.pending_reaches[reaches:]

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
        """
        Generate each attachment with the node's context and keep only its reach
        ends. Called once the node itself is placed; an attachment that fails is
        dropped and counted, never treated as a failure of the node.
        """
        for offset, attachment in enumerate(node.recipe.attachments):
            seed = node_seed(ring.ring_seed, ring.ring_index, node.node_path[0], ATTACHMENT_DEPTH + offset, node.position)
            node.attachment_seeds.append(seed)
            context = replace(node.context, radial_limits=(0.0, 1.0), rng=random.Random(seed))
            try:
                declaration = _registry_entry(attachment)["generator"](context).declaration
            except MotifError:
                self.dropped_attachments += 1
                continue
            for reach_end in declaration.reach_ends:
                page_point = node.context.to_cartesian(reach_end.point, rotation)
                self.pending_reaches.append((node, reach_end, page_point, rotation))
