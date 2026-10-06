"""
Assembler: turns a `DesignPlan` into placed, indexed ink.

Pass one draws every motif tree of every cell in cell space, rotates it into
place on the page and indexes the ink. Attachments draw nothing yet: their reach
ends are recorded for pass two (`resolver.py`), which resolves overflow, reaches
and contact.

Every `PlacedNode` keeps its recipe, the integer seed of its stream, its context
and its parent, so any node can be regenerated exactly with different limits.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import random
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from shapely.geometry import LineString

from composer import CellRecipe, Composer, DesignPlan, RingPlan, node_seed
from motifs import find_motif, safe_motif
from motifs.contract import MotifError, MotifInstance, ReachEnd
from motifs.geometry import MotifContext, PointTuple, cell_rotation_deg
from placement import InkIndex, PlacedPath, path_overflow, trace
import resolver


POSITIONS = ("centre", "divider")

# A base whose generator keeps failing is replaced at most this many times.
MAX_BASE_REPLACEMENTS = 3

# Attachment i draws from stream depth ATTACHMENT_DEPTH + i; slot nesting only uses depths 0 to 2.
ATTACHMENT_DEPTH = 10

PendingReach = Tuple["PlacedNode", ReachEnd, PointTuple, float]

# One regenerated node: the node, its new instance (None once it no longer fits), context and paths.
Regenerated = Tuple["PlacedNode", Optional[MotifInstance], MotifContext, List[PlacedPath]]


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
    # True when this node's slot child could not be placed in this cell.
    child_dropped: bool = False
    # Overflow sides pass two has resolved for this node, and how often it pulled each back.
    resolved_sides: Set[str] = field(default_factory=set)
    pull_backs: Dict[str, int] = field(default_factory=dict)


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


def _splice(items: List, cell_of: Callable[[object], Optional[int]], replacements: Dict[int, List]) -> List:
    """
    `items` with each replaced cell's old run swapped for that cell's new items,
    at the position of the cell's first old item. Items whose cell is None stay.
    """
    result: List = []
    emitted: Set[int] = set()
    for item in items:
        cell = cell_of(item)
        if cell is None:
            result.append(item)
        elif cell not in emitted:
            emitted.add(cell)
            result.extend(replacements.get(cell, []))
    for cell in sorted(set(replacements) - emitted):
        result.extend(replacements[cell])
    return result


def _by_cell(items: List, cell_of: Callable[[object], int]) -> Dict[int, List]:
    grouped: Dict[int, List] = {}
    for item in items:
        grouped.setdefault(cell_of(item), []).append(item)
    return grouped


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
        # Pass two: drawn reach paths, a record per resolved pending reach, the ring being resolved.
        self.reaches: List[PlacedPath] = []
        self.resolved_reaches: List[resolver.ResolvedReach] = []
        self.current_ring: Optional[int] = None

    def assemble(self) -> AssembledDesign:
        self.pass_one()
        self.pass_two()
        return AssembledDesign(
            self.plan, list(self.paths), list(self.nodes), list(self.reaches), self.dropped_children, self.center
        )

    # ----------------------------------------------------------- pass two

    def pass_two(self) -> None:
        """Resolve overflow, reaches and contact, rings innermost first (see `resolver.py`)."""
        resolver.pass_two(self)

    def resolve_overflow(self, node: PlacedNode, side: str) -> None:
        resolver.resolve_overflow(self, node, side)

    def resolve_reach(self, node: PlacedNode, reach_end: ReachEnd, page_point: PointTuple,
                      rotation_deg: float) -> Optional[PlacedPath]:
        return resolver.resolve_reach(self, node, reach_end, page_point, rotation_deg)

    def floating_base_cells(self) -> List[Tuple[int, int, str]]:
        """Floating `(ring, cell, position)` bases of the ring being resolved, or of every ring."""
        return resolver.floating_base_cells(self, self.current_ring)

    # ----------------------------------------------------------- pass one

    def pass_one(self) -> None:
        """Draw, place and index every cell, rings innermost first."""
        self._reset()
        for ring in self.plan.rings:
            self._place_ring(ring, range(ring.divisions))

    def _place_ring(self, ring: RingPlan, cells: Iterable[int]) -> None:
        """Place `cells` of the ring; a failing base is replaced and those cells placed again."""
        if not ring.sequence:
            raise AssemblyError(f"ring {ring.ring_index} has an empty sequence")
        cells = list(cells)
        replacements: Dict[Tuple[int, str], int] = {}
        while True:
            mark = self._mark()
            failure = self._place_cells(ring, cells)
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

    def _place_cells(self, ring: RingPlan, cells: Sequence[int]) -> Optional[Tuple[int, str, MotifError]]:
        """Place every cell in order; return the first base failure, if any."""
        for cell_index in cells:
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
        """
        Place the slot child chain under `parent`, dropping a child that cannot be
        placed. A child's fit depends on this cell's slot, so it is always tried;
        `recipe.dropped` only reports that it was dropped in at least one cell.
        """
        recipe = parent.recipe.slot_child
        if recipe is None:
            return
        slot = parent.instance.declaration.slot
        child = None
        if slot:
            try:
                child = self._place_node(
                    ring, parent.cell_index, parent.position, recipe,
                    parent.node_path + (0,), (0.0, 1.0), slot, parent,
                )
            except MotifError:
                child = None
        if child is None:
            recipe.dropped = True
            parent.child_dropped = True
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

    def _trace_node(self, ring_index: int, cell_index: int, position: str, node_path: Tuple[int, ...],
                    role: str, context: MotifContext, instance: MotifInstance,
                    rotation: float) -> List[PlacedPath]:
        paths = []
        for vector in instance.vectors:
            coords, radials = trace(context, vector, rotation)
            paths.append(PlacedPath(
                ring_index, cell_index, position, node_path, role,
                coords, radials, vector.closed, self.stroke_width,
            ))
        return paths

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
        paths = self._trace_node(ring.ring_index, cell_index, position, node_path, role, context, instance, rotation)
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

    # ------------------------------------------------- regeneration (pass two)

    def ring_plan(self, ring_index: int) -> RingPlan:
        return next(ring for ring in self.plan.rings if ring.ring_index == ring_index)

    def subtree(self, node: PlacedNode) -> List[PlacedNode]:
        """`node` and its placed slot descendants, parents first."""
        found = [node]
        for other in self.nodes:
            if any(other.parent is member for member in found):
                found.append(other)
        return found

    def reindex(self, path: PlacedPath) -> None:
        """Refresh a path's indexed geometry after its coordinates changed."""
        self.index.remove(path)
        self.index.add(path)

    def regenerate(self, node: PlacedNode, radial_limits: Tuple[float, float]) -> List[Regenerated]:
        """
        `node` and its slot descendants generated again from their stored seeds,
        `node` with `radial_limits`. Changes nothing; raises `MotifError` when
        `node` itself fails. A descendant that no longer fits its parent's slot
        comes back with instance None, as does everything below it.
        """
        rotation = cell_rotation_deg(node.cell_index, self.ring_plan(node.ring_index).divisions, node.position)
        context = replace(node.context, rng=random.Random(node.rng_seed), radial_limits=radial_limits)
        instance = _registry_entry(node.recipe)["generator"](context)
        result: List[Regenerated] = [(node, instance, context, self._retrace(node, context, instance, rotation))]
        slot = instance.declaration.slot
        for child in self.subtree(node)[1:]:
            child_instance, child_context = None, child.context
            if slot:
                child_context = replace(child.context, rng=random.Random(child.rng_seed), slot=slot)
                try:
                    child_instance = _registry_entry(child.recipe)["generator"](child_context)
                except MotifError:
                    child_instance = None
            paths = [] if child_instance is None else self._retrace(child, child_context, child_instance, rotation)
            result.append((child, child_instance, child_context, paths))
            slot = None if child_instance is None else child_instance.declaration.slot
        return result

    def _retrace(self, node: PlacedNode, context: MotifContext, instance: MotifInstance,
                 rotation: float) -> List[PlacedPath]:
        role = "base" if node.parent is None else "slot"
        return self._trace_node(node.ring_index, node.cell_index, node.position, node.node_path,
                                role, context, instance, rotation)

    def commit(self, regenerated: List[Regenerated]) -> None:
        """
        Swap regenerated ink in for the old, at the old ink's position in `paths`.
        A descendant that no longer fits is dropped with everything below it.
        """
        old = [path for node, _, _, _ in regenerated for path in node.paths]
        old_ids = {id(path) for path in old}
        at = next((i for i, path in enumerate(self.paths) if id(path) in old_ids), len(self.paths))
        for path in old:
            self.index.remove(path)
        self.paths = [path for path in self.paths if id(path) not in old_ids]

        new_paths: List[PlacedPath] = []
        dropping = False
        for node, instance, context, paths in regenerated:
            if instance is None:
                if not dropping:
                    node.recipe.dropped = True
                    node.parent.child_dropped = True
                    self.dropped_children += 1
                    dropping = True
                self.nodes = [other for other in self.nodes if other is not node]
                self.pending_reaches = [pending for pending in self.pending_reaches if pending[0] is not node]
                continue
            node.instance, node.context, node.paths = instance, context, paths
            new_paths.extend(paths)
        self.paths[at:at] = new_paths
        for path in new_paths:
            self.index.add(path)

    def replace_cells(self, ring: RingPlan, seq_positions: Iterable[int]) -> None:
        """
        Place again, pass-one style, every cell of `ring` whose sequence entry is
        in `seq_positions`. The old cells' nodes, ink, pending and drawn reaches
        are removed and the new ones take their place in every list. A reach of
        another cell that ended on removed ink is removed and becomes pending again.
        """
        seq_positions = set(seq_positions)
        cells = [c for c in range(ring.divisions) if c % len(ring.sequence) in seq_positions]
        cell_set = set(cells)

        def cell_of(item) -> Optional[int]:
            if item.ring_index == ring.ring_index and item.cell_index in cell_set:
                return item.cell_index
            return None

        removed = {id(path) for path in self.paths if cell_of(path) is not None}
        stale = [record for record in self.resolved_reaches
                 if cell_of(record.pending[0]) is not None
                 or (record.target is not None and id(record.target) in removed)]
        removed.update(id(record.path) for record in stale if record.path is not None)
        self.resolved_reaches = [r for r in self.resolved_reaches if not any(r is s for s in stale)]
        self.reaches = [path for path in self.reaches if id(path) not in removed]

        mark = self._mark()
        self._place_ring(ring, cells)
        new_nodes, new_paths = self.nodes[mark[0]:], self.paths[mark[1]:]
        new_pending = self.pending_reaches[mark[2]:]
        del self.nodes[mark[0]:], self.paths[mark[1]:], self.pending_reaches[mark[2]:]

        for path in self.paths:
            if id(path) in removed:
                self.index.remove(path)
        self.nodes = _splice(self.nodes, cell_of, _by_cell(new_nodes, lambda n: n.cell_index))
        # Removed reach paths simply go; the cells' own ink is swapped in place.
        kept = [path for path in self.paths if id(path) not in removed or path.role != "reach"]
        self.paths = _splice(kept, lambda p: cell_of(p) if id(p) in removed else None,
                             _by_cell(new_paths, lambda p: p.cell_index))
        self.pending_reaches = _splice(self.pending_reaches, lambda p: cell_of(p[0]),
                                       _by_cell(new_pending, lambda p: p[0].cell_index))
