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

from copy import deepcopy
from dataclasses import dataclass, field, replace
import math
import random
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple

import numpy as np
from shapely.geometry import LineString, Point
from shapely.ops import unary_union

from composer import CellRecipe, Composer, DesignPlan, RingPlan, node_seed, ring_stream_seed
from motifs import find_motif, safe_motif
from motifs.cache import MotifCache, call_generator
from motifs.contract import MotifError, MotifInstance, ReachEnd
from motifs.geometric import fit_rosette
from motifs.geometry import CellPoint, MotifContext, PointTuple, SmartVector, cell_rotation_deg
import motifs.layering as layering
from motifs.layering import LayeringError
from placement import InkIndex, PlacedPath, path_geometry, path_overflow, trace
import resolver


POSITIONS = ("centre", "divider")

# A base whose generator keeps failing is replaced at most this many times.
MAX_BASE_REPLACEMENTS = 3

# Attachment i draws from stream depth ATTACHMENT_DEPTH + i; slot nesting only uses depths 0 to 2.
ATTACHMENT_DEPTH = 10

# A ring's once-per-wedge contact is drawn in at least this many cells, spaced round the ring, so a design with a base
# symmetry of 1 or 2 never joins a ring to the one inside it at a single point (the band between would be one
# face running all the way round the centre).
MIN_RING_CONTACTS = 3

# The node path of every rosette path: the rosette is no node of the plan's sequence (max-region spec 5, step 3).
ROSETTE_NODE = -1

PendingReach = Tuple["PlacedNode", ReachEnd, PointTuple, float]

# One regenerated node: the node, its new instance (None once it no longer fits), context and paths.
Regenerated = Tuple["PlacedNode", Optional[MotifInstance], MotifContext, List[PlacedPath]]


class AssemblyError(ValueError):
    """A cell could not be assembled, even after replacing its base motif."""


class LayeredRingFailed(AssemblyError):
    """
    A layered ring's composite failed after pass one placed it (a pull-back, or cells placed again in pass
    two). Its back must be dropped for the whole ring and the design assembled again (spec 5.4).
    """

    def __init__(self, ring_index: int, message: str = "") -> None:
        super().__init__(f"ring {ring_index}: layered composite failed in pass two{': ' + message if message else ''}")
        self.ring_index = ring_index


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
    # The seed of the back stream a layered ring's centre base drew its back from (None for every other node).
    back_seed: Optional[int] = None


# ------------------------------------------------------------------- the design


@dataclass
class AssembledDesign:
    plan: DesignPlan
    paths: List[PlacedPath]
    nodes: List[PlacedNode]
    reaches: List[PlacedPath]
    dropped_children: int
    center: PointTuple
    # Embellishments asked for but not drawn, summed over the placed instances.
    dropped_embellishments: int = 0
    # True when the innermost ring asked for a rosette and none fitted, so nothing was placed.
    rosette_dropped: bool = False

    def polylines(self) -> List[List[PointTuple]]:
        return [path.coords for path in self.paths]

    def base_mask(self) -> List[bool]:
        return [path.role in resolver.STRUCTURAL_ROLES for path in self.paths]

    def ring_ids(self) -> List[int]:
        return [path.ring_index for path in self.paths]

    def overflow_parts(self) -> List[Tuple[int, LineString]]:
        return [(path.ring_index, line) for path in self.paths for _, line in path_overflow(path, self.center)]


# -------------------------------------------------------------------- assembler


def _registry_entry(recipe: CellRecipe) -> Dict:
    return find_motif(recipe.motif) or safe_motif(recipe.category)


def _path_role(vector: SmartVector, node_role: str) -> str:
    """
    A traced vector's role: "detail" for embellishment ink, a back layer's included (it floats inside its
    host, as a slot child may, so it is not base structure), "back" for the back layer's outline beneath
    the base ink, else the node's own role.
    """
    if vector.weight == "detail":
        return "detail"
    return "back" if vector.layer == "back" else node_role


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


def _recipe_pairs(mine: Optional[CellRecipe], theirs: Optional[CellRecipe]):
    if mine is None or theirs is None:
        return
    yield mine, theirs
    yield from _recipe_pairs(mine.slot_child, theirs.slot_child)
    for a, b in zip(mine.attachments, theirs.attachments):
        yield from _recipe_pairs(a, b)


def _plan_pairs(mine: DesignPlan, theirs: DesignPlan):
    """(object of `mine`, object in the same place in `theirs`) for every ring, entry and recipe of two plans."""
    for ring, other in zip(mine.rings, theirs.rings):
        yield ring, other
        for entry, other_entry in zip(ring.sequence, other.sequence):
            yield entry, other_entry
            yield from _recipe_pairs(entry.centre, other_entry.centre)
            yield from _recipe_pairs(entry.divider, other_entry.divider)
        yield from _recipe_pairs(ring.back, other.back)
        yield from _recipe_pairs(ring.rosette, other.rosette)


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
        motif_cache: Optional[MotifCache] = None,
    ) -> None:
        self.plan = plan
        self.ring_geometry = ring_geometry
        self.center = center
        self.complexity = complexity
        self.min_white_space = min_white_space
        self.composer = composer
        # The design's memo of generator calls (`motifs.cache`); None calls every generator directly.
        self.motif_cache = motif_cache
        # Called with this assembler between pass two and `finish` (the generator keeps pre-rosette states).
        self.after_pass_two: Optional[Callable[["Assembler"], None]] = None
        self.stroke_width = stroke_width_for(complexity)
        self._reset()

    def _call(self, entry: Dict, context: MotifContext) -> MotifInstance:
        """`entry`'s generator on `context`, through the design's memo when it has one."""
        if self.motif_cache is None:
            return call_generator(entry, context)
        return self.motif_cache.generate(entry, context)

    def _through_memo(self, entry: Dict) -> Dict:
        """`entry`, or with a memo a copy whose generator answers through it (what `compose_layered` calls)."""
        return entry if self.motif_cache is None else self.motif_cache.wrap(entry)

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
        if self.after_pass_two is not None:
            self.after_pass_two(self)
        return self.finish()

    def finish(self) -> AssembledDesign:
        """
        After pass two: place the innermost ring's rosette when the plan asks for one, and return the design.
        Pass one and pass two never read `RingPlan.rosette`, `DesignPlan.repairs` or a recipe's `dropped`, so
        the state they leave is the same with or without them (`copy_for` relies on it).
        """
        rosette_dropped = False
        innermost = self.ring_plan(self._innermost()) if self.plan.rings else None
        if innermost is not None and innermost.rosette is not None:
            rosette_dropped = not self.place_rosette()
        return AssembledDesign(
            self.plan, list(self.paths), list(self.nodes), list(self.reaches), self.dropped_children, self.center,
            dropped_embellishments=sum(node.instance.dropped_embellishments for node in self.nodes),
            rosette_dropped=rosette_dropped,
        )

    def copy_for(self, plan: DesignPlan, composer: Composer) -> "Assembler":
        """
        A deep copy of this assembler's state bound to `plan` and `composer`: `plan` has this plan's shape
        (rings, entries and recipes in the same places), and each copied reference to a ring or recipe of this
        plan becomes a reference to the one in the same place in `plan`, so every node's recipe is `plan`'s.
        The ring geometry and the motif memo are shared, not copied; the ink index shares its immutable
        geometries (`InkIndex.__deepcopy__`). This assembler is left untouched.
        """
        memo = {id(self.plan): plan, id(self.composer): composer, id(self.ring_geometry): self.ring_geometry,
                id(self.motif_cache): self.motif_cache}
        for mine, theirs in _plan_pairs(self.plan, plan):
            memo[id(mine)] = theirs
        copy = deepcopy(self, memo)
        copy.after_pass_two = None
        return copy

    # ----------------------------------------------------------- the rosette

    def place_rosette(self) -> bool:
        """
        Fit the innermost ring's rosette against every placed line (`motifs.geometric.fit_rosette`, with the
        context of the ring's cell 0 and its "repair:3" ring stream), trace each lobe as detail ink of ring 0
        with node path `(ROSETTE_NODE,)`, and make each lobe's tip a vertex of the ink it touches. The fit is
        not stored: it depends only on the plan and the ink, so a replay fits it again exactly. False, with
        nothing placed, when no rosette fits.
        """
        ring = self.ring_plan(self._innermost())
        seed = ring_stream_seed(ring.ring_seed, ring.ring_index, "repair:3")
        context = MotifContext(
            inner_radius=0.0,
            outer_radius=self.ring_geometry[ring.ring_index]["outer_radius"],
            wedge_angle=360.0 / ring.divisions,
            center=self.center,
            stroke_width=self.stroke_width,
            complexity=self.complexity,
            min_white_space=self.min_white_space,
            rng=random.Random(seed),
            position="centre",
            ring_stream_seed=seed,
            node_seed=seed,
        )
        ink = unary_union([path_geometry(path) for path in self.paths])
        try:
            fit = fit_rosette(context, ink)
        except MotifError:
            return False
        cell_wedge = 360.0 / ring.divisions
        # The lobe on divider i is assigned to cell i, the cell whose end it sits on.
        offset = 0.0 if fit.axis == "cell" else cell_wedge / 2.0
        # Every path through a lobe's tip, in index (insertion) order; the fit fails when a tip touches none.
        tips = []
        for rotation in fit.rotations:
            tip = fit.context.to_cartesian(CellPoint(1.0, 0.0), rotation)
            touched = [
                path for path in self.index.candidates(Point(tip).buffer(resolver.SAME_VERTEX_PX))
                if path_geometry(path).distance(Point(tip)) <= resolver.SAME_VERTEX_PX
            ]
            if not touched:
                return False
            tips.append((rotation, tip, touched))
        placed: List[PlacedPath] = []
        for rotation, tip, touched in tips:
            for path in touched:
                resolver.insert_vertex(path, tip)
                self.reindex(path)
            cell_index = round((rotation - offset) / cell_wedge) % ring.divisions
            placed.extend(self._trace_node(ring.ring_index, cell_index, "centre", (ROSETTE_NODE,), "detail",
                                           fit.context, fit.instance, rotation))
        for path in placed:
            self.paths.append(path)
            self.index.add(path)
        for path in placed:
            self.snap_to_ink(path)
        return True

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

    def _place_ring(self, ring: RingPlan, cells: Iterable[int], drop_back: bool = True) -> None:
        """
        Place `cells` of the ring; a failing base is replaced and those cells placed again. A failing
        layered composite drops the ring's back and places the cells again without counting a replacement
        (spec 5.4); when only some cells are placed (`drop_back` False), the cells already drawn with the
        back would keep it, so the ring fails as a whole with `LayeredRingFailed`.
        """
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
            if isinstance(error, LayeringError) and ring.back is not None:
                if not drop_back:
                    raise LayeredRingFailed(ring.ring_index, str(error)) from error
                self.composer.drop_back(ring)
                continue
            seq_pos = cell_index % len(ring.sequence)
            count = replacements.get((seq_pos, position), 0)
            had_back = ring.back is not None
            if count >= MAX_BASE_REPLACEMENTS or not self.composer.replace_node(ring, seq_pos, position, "generation"):
                raise AssemblyError(
                    f"ring {ring.ring_index} cell {cell_index} ({position}): base motif failed "
                    f"after {count} replacements: {error}"
                ) from error
            if had_back and ring.back is None and not drop_back:
                # The replacement dropped the back (a safe fallback), but cells outside `cells` still draw it.
                raise LayeredRingFailed(ring.ring_index, "a replacement dropped the back") from error
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
                # The innermost ring never overflows inward: its bases keep to its inner boundary.
                inward = 0.0 if ring.ring_index == self._innermost() else entry_info["max_overflow_inward"]
                limits = (-inward, 1.0 + entry_info["max_overflow_outward"])
                try:
                    base = self._place_node(ring, cell_index, position, recipe, (seq_pos,), limits, None, None)
                except MotifError as error:
                    return cell_index, position, error
                self._place_slot_children(ring, base)
        return None

    def _innermost(self) -> int:
        return min(ring.ring_index for ring in self.plan.rings)

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

    def _context(self, ring: RingPlan, position: str, recipe: CellRecipe, rng_seed: int, radial_limits: Tuple[float, float],
                 slot: Optional[list], is_base: bool = False) -> MotifContext:
        """A node's context; a base motif of a side-touch ring gets the ring's side-touch radial (spec 13.2)."""
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
            side_touch_radial=ring.side_touch_radial if is_base and ring.contact_mode == "side" else None,
            ring_stream_seed=ring_stream_seed(ring.ring_seed, ring.ring_index, f"ring:{recipe.motif}:{position}"),
            node_seed=rng_seed,
            embellishments=tuple(recipe.embellishments),
            size_floor=recipe.size_floor,
        )

    def _back_context(self, ring: RingPlan, front_context: MotifContext) -> MotifContext:
        """
        The back's context (spec 5.2 step 2): the whole cell on a divider, radial limits (0, 1), and the
        ring's back stream for its rng, its node seed (so its embellishments) and its ring stream, so every
        cell of the ring draws the same back.
        """
        seed = ring_stream_seed(ring.ring_seed, ring.ring_index, "back")
        return replace(
            front_context, rng=random.Random(seed), node_seed=seed, ring_stream_seed=seed, position="divider",
            angular_limits=1.0, radial_limits=(0.0, 1.0), slot=None, side_touch_radial=None,
            embellishments=tuple(ring.back.embellishments), size_floor=ring.back.size_floor,
        )

    def _generate(self, ring: RingPlan, recipe: CellRecipe, context: MotifContext,
                  is_base: bool) -> Tuple[MotifInstance, Optional[int]]:
        """
        One node's instance, and the back seed when it is a layered composite: a centre base of a ring
        with a back is drawn by `compose_layered`, everything else by its own generator.
        """
        entry = _registry_entry(recipe)
        if is_base and context.position == "centre" and ring.back is not None:
            back_context = self._back_context(ring, context)
            instance = layering.compose_layered(context, self._through_memo(entry), back_context,
                                                self._through_memo(_registry_entry(ring.back)))
            return instance, back_context.node_seed
        return self._call(entry, context), None

    def _trace_node(self, ring_index: int, cell_index: int, position: str, node_path: Tuple[int, ...],
                    role: str, context: MotifContext, instance: MotifInstance,
                    rotation: float) -> List[PlacedPath]:
        paths = []
        for vector in instance.vectors:
            coords, radials = trace(context, vector, rotation)
            paths.append(PlacedPath(
                ring_index, cell_index, position, node_path,
                _path_role(vector, role),
                coords, radials, vector.closed, context.stroke_for(vector.weight),
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
        context = self._context(ring, position, recipe, rng_seed, radial_limits, slot, is_base=parent is None)
        instance, back_seed = self._generate(ring, recipe, context, is_base=parent is None)

        rotation = cell_rotation_deg(cell_index, ring.divisions, position)
        role = "base" if parent is None else "slot"
        paths = self._trace_node(ring.ring_index, cell_index, position, node_path, role, context, instance, rotation)
        node = PlacedNode(
            ring.ring_index, cell_index, position, node_path, recipe,
            rng_seed, instance, paths, context, parent, back_seed=back_seed,
        )
        self.nodes.append(node)
        for path in paths:
            self.paths.append(path)
            self.index.add(path)
        for path in paths:
            # Cells traced with an inexact rotation (360 / 7) meet their neighbours' side vertices only to float noise.
            self.snap_to_ink(path)
        self._record_reaches(ring, node, rotation)
        return node

    def _record_reaches(self, ring: RingPlan, node: PlacedNode, rotation: float) -> None:
        """
        Generate each attachment with the node's context and keep only its reach
        ends. Called once the node itself is placed; an attachment that fails is
        dropped and counted, never treated as a failure of the node. A
        once-per-wedge attachment is generated and recorded only in the cells
        `_draws_once_per_wedge` picks.
        """
        draws_once = self._draws_once_per_wedge(ring, node)
        for offset, attachment in enumerate(node.recipe.attachments):
            if attachment.once_per_wedge and not draws_once:
                continue
            seed = node_seed(ring.ring_seed, ring.ring_index, node.node_path[0], ATTACHMENT_DEPTH + offset, node.position)
            node.attachment_seeds.append(seed)
            context = replace(node.context, radial_limits=(0.0, 1.0), rng=random.Random(seed), side_touch_radial=None)
            try:
                declaration = self._call(_registry_entry(attachment), context).declaration
            except MotifError:
                self.dropped_attachments += 1
                continue
            for reach_end in declaration.reach_ends:
                page_point = node.context.to_cartesian(reach_end.point, rotation)
                self.pending_reaches.append((node, reach_end, page_point, rotation))

    def _draws_once_per_wedge(self, ring: RingPlan, node: PlacedNode) -> bool:
        """
        Whether the node's cell draws its once-per-wedge attachments: the first
        cell of each wedge of `360 / B` degrees, or, while that gives fewer than
        `MIN_RING_CONTACTS` in the ring (B of 1 or 2), cells spaced through each
        wedge, at least `ceil(MIN_RING_CONTACTS / B)` per wedge where the wedge
        holds that many cells of the node's entry. Only cells holding the
        node's sequence entry carry the attachment, so the spacing counts those:
        the m = wedge / len(sequence) of them in each wedge, every k-th one with
        k = max(1, m // per-wedge count). The rule depends only on a cell's place
        in its wedge, so every symmetry group draws it in all its members or none.
        """
        wedge = ring.divisions // self.symmetry
        holding = max(1, wedge // len(ring.sequence))
        per_wedge = math.ceil(MIN_RING_CONTACTS / self.symmetry)
        step = max(1, holding // per_wedge)
        return ((node.cell_index % wedge) // len(ring.sequence)) % step == 0

    # ------------------------------------------------- regeneration (pass two)

    def ring_plan(self, ring_index: int) -> RingPlan:
        return next(ring for ring in self.plan.rings if ring.ring_index == ring_index)

    # ------------------------------------------------------------ symmetry

    @property
    def symmetry(self) -> int:
        """
        The plan's base symmetry `B` (spec 13.1), or 1 when some ring does not
        repeat whole in each of `B` wedges (a hand-made plan), so no
        operation is ever mirrored onto a cell that differs from its group.
        """
        symmetry = max(1, self.plan.base_symmetry)
        for ring in self.plan.rings:
            if ring.divisions % symmetry or (ring.sequence and (ring.divisions // symmetry) % len(ring.sequence)):
                return 1
        return symmetry

    def wedge_cells(self, ring_index: int) -> int:
        """Cells of the ring in one wedge of `360 / B` degrees."""
        return self.ring_plan(ring_index).divisions // self.symmetry

    def symmetry_groups(self, ring_index: int) -> List[List[PlacedNode]]:
        """
        The ring's nodes in groups of `B` related by rotation `360 / B`: in a
        ring of N cells, cell i with cells i + k * N / B, same position and node
        path. Members are in cell order, so the first, the group's
        representative, lies in the first wedge. Groups follow their
        representatives' order in `nodes`.
        """
        wedge = self.wedge_cells(ring_index)
        groups: Dict[Tuple[int, str, Tuple[int, ...]], List[PlacedNode]] = {}
        for node in self.nodes:
            if node.ring_index == ring_index:
                groups.setdefault((node.cell_index % wedge, node.position, node.node_path), []).append(node)
        order = {id(node): i for i, node in enumerate(self.nodes)}
        found = [sorted(group, key=lambda node: node.cell_index) for group in groups.values()]
        return sorted(found, key=lambda group: order[id(group[0])])

    def is_representative(self, node: PlacedNode) -> bool:
        """Whether the node is its symmetry group's representative: its cell lies in the first wedge."""
        return node.cell_index < self.wedge_cells(node.ring_index)

    # Mirroring (spec 13.1). Pass two works on representatives; each change it makes to ink is
    # repeated for every shift k = 1 .. B - 1: on the counterpart of each changed path, the path of
    # the same node path and index in the cell k * N / B on (N the cells of that path's ring), with
    # coordinates turned by k * 360 / B about the centre and radials copied. A counterpart of a
    # path in a later wedge wraps round, so an edit to any member of a group reaches all of them.

    def turn(self, coords: Sequence[PointTuple], k: int) -> List[PointTuple]:
        """`coords` turned about the centre by `k * 360 / B` degrees, the turn from a cell to its k-th counterpart."""
        angle = math.radians(k * 360.0 / self.symmetry)
        c, s = math.cos(angle), math.sin(angle)
        cx, cy = self.center
        return [(cx + (x - cx) * c - (y - cy) * s, cy + (x - cx) * s + (y - cy) * c) for x, y in coords]

    def shifts(self) -> range:
        """The shifts `k` from a node to the other members of its group."""
        return range(1, self.symmetry)

    def _node_lookup(self) -> Dict[Tuple[int, int, str, Tuple[int, ...]], PlacedNode]:
        return {(n.ring_index, n.cell_index, n.position, n.node_path): n for n in self.nodes}

    def _shifted_key(self, item, k: int) -> Tuple[int, int, str, Tuple[int, ...]]:
        divisions = self.ring_plan(item.ring_index).divisions
        cell = (item.cell_index + k * (divisions // self.symmetry)) % divisions
        return item.ring_index, cell, item.position, item.node_path

    def node_counterparts(self, node: PlacedNode) -> List[Tuple[int, PlacedNode]]:
        """`(k, member)` for every other member of the node's group, by shift."""
        lookup = self._node_lookup() if self.symmetry > 1 else {}
        found = [(k, lookup.get(self._shifted_key(node, k))) for k in self.shifts()]
        return [(k, member) for k, member in found if member is not None]

    def pending_counterparts(self, pending: PendingReach) -> List[Tuple[int, PendingReach]]:
        """`(k, pending)`: the same reach end of each other member of the pending reach's node's group."""
        node = pending[0]
        index = [i for i, other in enumerate(p for p in self.pending_reaches if p[0] is node) if other is pending]
        if not index:
            return []
        found = []
        for k, member in self.node_counterparts(node):
            own = [p for p in self.pending_reaches if p[0] is member]
            if index[0] < len(own):
                found.append((k, own[index[0]]))
        return found

    def representative_pending(self, pending: PendingReach) -> PendingReach:
        """The pending reach of the group's representative that `pending` mirrors (itself for a representative)."""
        node = pending[0]
        if self.is_representative(node):
            return pending
        wedge = self.wedge_cells(node.ring_index)
        owner = self._node_lookup().get((node.ring_index, node.cell_index % wedge, node.position, node.node_path))
        mine = [p for p in self.pending_reaches if p[0] is node]
        index = next(i for i, other in enumerate(mine) if other is pending)
        own = [p for p in self.pending_reaches if p[0] is owner]
        return own[index] if owner is not None and index < len(own) else pending

    def path_counterparts(self, path: PlacedPath) -> List[Tuple[int, PlacedPath]]:
        """`(k, path)` for each counterpart of `path`; ink no node owns (none in a design) has none."""
        if self.symmetry == 1:
            return []
        if path.role == "reach":
            record = next((r for r in self.resolved_reaches if r.path is path), None)
            if record is None:
                return []
            drawn = {id(r.pending): r.path for r in self.resolved_reaches}
            return [(k, drawn[id(pending)]) for k, pending in self.pending_counterparts(record.pending)
                    if drawn.get(id(pending)) is not None]
        lookup = self._node_lookup()
        owner = lookup.get((path.ring_index, path.cell_index, path.position, path.node_path))
        index = next((i for i, own in enumerate(owner.paths) if own is path), None) if owner else None
        if index is None:
            return []
        found = []
        for k in self.shifts():
            member = lookup.get(self._shifted_key(owner, k))
            if member is not None and index < len(member.paths):
                found.append((k, member.paths[index]))
        return found

    def snap_to_ink(self, path: PlacedPath) -> None:
        """
        Make every vertex of `path` within `SAME_VERTEX_PX` of a vertex of other
        ink exactly that vertex, and reindex it. A turned copy differs from ink
        drawn in its own cell by float noise, as does a cell traced with an
        inexact rotation from its neighbour at their shared side vertex, and a
        touch is only read as one by the validator when the shared vertex is the
        same point in both lines (else a third line through it can overlap one of
        them along a sub-micron segment). Every placed, committed or mirrored
        path is snapped.
        """
        tolerance = resolver.SAME_VERTEX_PX
        others = [other for other in self.index.candidates(path_geometry(path).buffer(tolerance)) if other is not path]
        vertices = [point for other in others for point in other.coords]
        if vertices:
            grid = np.asarray(vertices, dtype=float)
            for i, (x, y) in enumerate(path.coords):
                distances = np.hypot(grid[:, 0] - x, grid[:, 1] - y)
                j = int(np.argmin(distances))
                if distances[j] <= tolerance:
                    path.coords[i] = vertices[j]
        self.reindex(path)

    def mirror_insert(self, path: PlacedPath, point: PointTuple) -> None:
        """Repeat the insertion of vertex `point` into `path` on each counterpart, at the turned point."""
        for k, other in self.path_counterparts(path):
            resolver.insert_vertex(other, self.turn([point], k)[0])
            if len(other.radials) == len(path.radials):
                other.radials[:] = path.radials
            self.snap_to_ink(other)

    def mirror_move(self, path: PlacedPath, old: PointTuple, new: PointTuple) -> None:
        """Repeat moving `path`'s vertices at `old` onto `new` on each counterpart, with the radial `path` gave them."""
        radial = next(r for point, r in zip(path.coords, path.radials) if point == new)
        for k, other in self.path_counterparts(path):
            (turned_old, turned_new) = self.turn([old, new], k)
            for i, point in enumerate(other.coords):
                if math.hypot(point[0] - turned_old[0], point[1] - turned_old[1]) <= resolver.SAME_VERTEX_PX:
                    other.coords[i] = turned_new
                    other.radials[i] = radial
            self.snap_to_ink(other)

    def commit_group(self, regenerated: List[Regenerated]) -> None:
        """`commit` for a representative, then for each member its turned copy of the same regenerated ink."""
        copies = []
        for k in self.shifts():
            lookup = self._node_lookup()
            copy: List[Regenerated] = []
            for node, instance, context, paths in regenerated:
                member = lookup.get(self._shifted_key(node, k))
                if member is None:
                    break
                copy.append((member, instance, context, [
                    PlacedPath(path.ring_index, member.cell_index, path.position, path.node_path, path.role,
                               self.turn(path.coords, k), list(path.radials), path.closed, path.stroke_width)
                    for path in paths
                ]))
            else:
                copies.append(copy)
        self.commit(regenerated)
        for copy in copies:
            self.commit(copy)

    def snapshot(self, paths: Iterable[PlacedPath]) -> List[Tuple[PlacedPath, List[PointTuple], List[float]]]:
        """The coordinates and radials of `paths` and all their counterparts, for `restore`."""
        seen: Dict[int, PlacedPath] = {}
        for path in paths:
            seen.setdefault(id(path), path)
            for _, other in self.path_counterparts(path):
                seen.setdefault(id(other), other)
        return [(path, list(path.coords), list(path.radials)) for path in seen.values()]

    def restore(self, saved: List[Tuple[PlacedPath, List[PointTuple], List[float]]]) -> None:
        for path, coords, radials in saved:
            path.coords[:], path.radials[:] = coords, radials
            self.reindex(path)

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
        `node` itself fails. A layered composite is regenerated whole, its back
        cut again against the new front (spec 5.2); when the composite fails the
        ring's back must go, which raises `LayeredRingFailed`. A descendant
        that no longer fits its parent's slot comes back with instance None, as
        does everything below it.
        """
        ring = self.ring_plan(node.ring_index)
        rotation = cell_rotation_deg(node.cell_index, ring.divisions, node.position)
        context = replace(node.context, rng=random.Random(node.rng_seed), radial_limits=radial_limits)
        try:
            instance, _ = self._generate(ring, node.recipe, context, is_base=node.parent is None)
        except LayeringError as error:
            raise LayeredRingFailed(node.ring_index, str(error)) from error
        result: List[Regenerated] = [(node, instance, context, self._retrace(node, context, instance, rotation))]
        slot = instance.declaration.slot
        for child in self.subtree(node)[1:]:
            child_instance, child_context = None, child.context
            if slot:
                child_context = replace(child.context, rng=random.Random(child.rng_seed), slot=slot)
                try:
                    child_instance = self._call(_registry_entry(child.recipe), child_context)
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
        for path in new_paths:
            self.snap_to_ink(path)

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
        self._place_ring(ring, cells, drop_back=False)
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
