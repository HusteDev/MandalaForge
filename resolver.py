"""
Assembler pass two: overflow, reaches and per-cell contact.

The functions here work on an `Assembler`'s state (its nodes, ink, index and
pending reaches) once pass one has placed every ring. Rings are resolved
innermost first; within a ring, inward overflow, then outward overflow, then the
ring's pending reaches, then the contact check, which replaces floating cells
and resolves the ring again.

A touch is always exact: the touching end is a vertex of its own path and the
point it lands on is inserted as a vertex into the path it touches, so nothing
relies on a snap tolerance to read as connected.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import math
from typing import TYPE_CHECKING, Callable, Dict, List, Optional, Sequence, Set, Tuple

import numpy as np
import shapely
from shapely.geometry import LineString, Point
from shapely.geometry.base import BaseGeometry
from shapely.ops import nearest_points

import assembler
from motifs.contract import MotifError, ReachEnd
from motifs.geometry import MotifContext, PointTuple
from placement import PlacedPath, path_geometry
from topology_validator import structural_components

if TYPE_CHECKING:
    from assembler import Assembler, PendingReach, PlacedNode, Regenerated
    from composer import RingPlan


# Halvings of the overflow limit before settling on the last clear one.
SEARCH_STEPS = 10
# A resolved overflow within this gap of neighbour ink is moved onto it.
TOUCH_GAP_PX = 2.0
# A point this close to ink is on it.
ON_INK_PX = 1e-6
# A point this close to an existing vertex is that vertex.
SAME_VERTEX_PX = 1e-9
# Ink this close meets: float noise leaves lines meant to be collinear about this far apart.
MEET_PX = 1e-9
# Ink meeting only this close to a point that is a vertex of both lines touches there.
TOUCH_RADIUS_PX = 1e-6
# A crossing this close to a ring boundary, or past it, is blamed on overflow on that side.
BOUNDARY_MARGIN_PX = 0.5
# A node side pulled back this many times is left as it is.
MAX_PULL_BACKS = 4
# Rounds of floating-cell replacement per ring before assembly gives up.
MAX_CONTACT_ROUNDS = 3

WAVY_POINTS = 9
WAVY_MAX_AMPLITUDE_PX = 3.0
WAVY_AMPLITUDE_SHARE = 0.1
# A wave that would cross ink is flattened through these amplitude scales.
WAVY_FALLBACK_SCALES = (1.0, 0.5, 0.25, 0.0)


@dataclass(eq=False)
class ResolvedReach:
    pending: PendingReach
    path: Optional[PlacedPath]  # the drawn reach; None when nothing was drawn
    target: Optional[PlacedPath]  # the ink it ends on, if any


# ---------------------------------------------------------------- vertices


def insert_vertex(path: PlacedPath, point: PointTuple) -> PointTuple:
    """
    Make `point`, which lies on `path`, a vertex of it: inserted into the segment
    it lands on, with a radial interpolated along that segment. Returns the
    vertex, which is an existing one when `point` already coincides with it.
    """
    coords, radials = path.coords, path.radials
    if len(coords) < 2:
        return point
    px, py = point
    best: Optional[Tuple[float, int, float]] = None  # distance, segment, parameter
    for i in range(len(coords) - 1):
        (x0, y0), (x1, y1) = coords[i], coords[i + 1]
        dx, dy = x1 - x0, y1 - y0
        length_sq = dx * dx + dy * dy
        t = 0.0 if length_sq == 0 else max(0.0, min(1.0, ((px - x0) * dx + (py - y0) * dy) / length_sq))
        distance = math.hypot(px - (x0 + t * dx), py - (y0 + t * dy))
        if best is None or distance < best[0]:
            best = (distance, i, t)
    _, i, t = best
    for end in (i, i + 1):
        if math.hypot(px - coords[end][0], py - coords[end][1]) <= SAME_VERTEX_PX:
            return coords[end]
    coords.insert(i + 1, point)
    radials.insert(i + 1, radials[i] + (radials[i + 1] - radials[i]) * t)
    return point


def _radial(context: MotifContext, point: PointTuple) -> float:
    radius = math.hypot(point[0] - context.center[0], point[1] - context.center[1])
    return (radius - context.inner_radius) / context.ring_depth


def wavy_coords(start: PointTuple, end: PointTuple, scale: float = 1.0) -> List[PointTuple]:
    """`WAVY_POINTS` points from `start` to `end`, offset sideways by one full sine wave."""
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = math.hypot(dx, dy)
    amplitude = scale * min(WAVY_MAX_AMPLITUDE_PX, WAVY_AMPLITUDE_SHARE * length)
    nx, ny = -dy / length, dx / length
    coords = []
    for k in range(WAVY_POINTS):
        t = k / (WAVY_POINTS - 1)
        offset = amplitude * math.sin(2.0 * math.pi * t)
        coords.append((start[0] + dx * t + nx * offset, start[1] + dy * t + ny * offset))
    coords[0], coords[-1] = start, end
    return coords


# ---------------------------------------------------------------- overflow


def _neighbour(asm: Assembler, ring_index: int, side: str) -> Optional[int]:
    neighbour = ring_index - 1 if side == "inward" else ring_index + 1
    return neighbour if any(ring.ring_index == neighbour for ring in asm.plan.rings) else None


def _crossing(line: BaseGeometry, other: BaseGeometry, line_vertices: Sequence[PointTuple],
              other_vertices: Sequence[PointTuple]) -> Optional[BaseGeometry]:
    """
    Where two pieces of ink cross, or None. They meet where they come within
    `MEET_PX`, so lines meant to be collinear meet despite float noise. Meeting
    only within `TOUCH_RADIUS_PX` of a point that is a vertex of both is a
    touch, which is how every touch here is made (the validator's rule too).
    """
    if not shapely.dwithin(line, other, MEET_PX):
        return None
    near = line.intersection(other.buffer(MEET_PX))
    if near.is_empty:
        return None
    x0, y0, x1, y1 = near.bounds

    def close(vertices: Sequence[PointTuple]) -> np.ndarray:
        points = np.asarray(vertices, dtype=float)
        return points[
            (points[:, 0] >= x0 - TOUCH_RADIUS_PX) & (points[:, 0] <= x1 + TOUCH_RADIUS_PX)
            & (points[:, 1] >= y0 - TOUCH_RADIUS_PX) & (points[:, 1] <= y1 + TOUCH_RADIUS_PX)
        ]

    mine, theirs = close(line_vertices), close(other_vertices)
    shared = [
        point for point in mine
        if len(theirs) and np.min(np.hypot(theirs[:, 0] - point[0], theirs[:, 1] - point[1])) <= TOUCH_RADIUS_PX
    ]
    rest = near if not shared else near.difference(shapely.MultiPoint(shared).buffer(TOUCH_RADIUS_PX))
    return None if rest.is_empty else rest


def _beyond(asm: Assembler, ring_index: int, side: str, geometry: BaseGeometry) -> bool:
    """Whether `geometry` reaches the ring's boundary on `side`, or past it, within `BOUNDARY_MARGIN_PX`."""
    coords = shapely.get_coordinates(geometry)
    radii = np.hypot(coords[:, 0] - asm.center[0], coords[:, 1] - asm.center[1])
    bounds = asm.ring_geometry[ring_index]
    if side == "inward":
        return bool(radii.min() <= bounds["inner_radius"] + BOUNDARY_MARGIN_PX)
    return bool(radii.max() >= bounds["outer_radius"] - BOUNDARY_MARGIN_PX)


def _ink_crosses(asm: Assembler, paths: Sequence[PlacedPath], neighbour: int, side: Optional[str] = None) -> bool:
    """
    Whether `paths` cross ink of ring `neighbour`; with `side`, only where the
    crossing reaches their ring's boundary on that side, which is where their
    own overflow is to blame. Whole paths are tested rather than overflow runs:
    an arc's chords sag a fraction of a pixel inside its ring, and a crossing
    there is as visible as one past the boundary.
    """
    for path in paths:
        geometry = path_geometry(path)
        for other in asm.index.candidates(geometry):
            if other.ring_index != neighbour:
                continue
            crossing = _crossing(geometry, path_geometry(other), path.coords, other.coords)
            if crossing is not None and (side is None or _beyond(asm, path.ring_index, side, crossing)):
                return True
    return False


def _with_limit(limits: Tuple[float, float], bound: int, value: float) -> Tuple[float, float]:
    return (value, limits[1]) if bound == 0 else (limits[0], value)


def resolve_overflow(asm: Assembler, node: PlacedNode, side: str) -> None:
    """
    Pull `node`'s overflow on `side` back until it no longer crosses the
    neighbouring ring's ink, then touch that ink if the gap left is small.
    """
    node.resolved_sides.add(side)
    _settle(asm, [(node, side)])


def _settle(asm: Assembler, work: List[Tuple[PlacedNode, str]]) -> None:
    """
    Pull back each `(node, side)` in turn. A pull-back reshapes the motif inside
    its own ring too, so its own other side and the facing sides of every node
    in the neighbouring rings are queued to be checked again, as they would have
    been had the motif been drawn this way in pass one. A worklist rather than
    recursion, and `MAX_PULL_BACKS` per node side, bound the whole exchange.
    """
    queue = deque(work)
    while queue:
        node, side = queue.popleft()
        if not _is_placed(asm, node) or not _pull_back(asm, node, side):
            continue
        queue.append((node, "outward" if side == "inward" else "inward"))
        for near_side in ("inward", "outward"):
            neighbour = _neighbour(asm, node.ring_index, near_side)
            facing = "outward" if near_side == "inward" else "inward"
            queue.extend((other, facing) for other in asm.nodes if other.ring_index == neighbour)


def _pull_back(asm: Assembler, node: PlacedNode, side: str) -> bool:
    """
    One pull-back of `node`'s overflow on `side`, without marking the side
    resolved. False, changing nothing, when its ink does not cross the
    neighbouring ring there or the side has used up its `MAX_PULL_BACKS`.
    """
    neighbour = _neighbour(asm, node.ring_index, side)
    if neighbour is None or node.pull_backs.get(side, 0) >= MAX_PULL_BACKS:
        return False
    old_paths = _subtree_paths(asm, node)
    if not _ink_crosses(asm, old_paths, neighbour, side):
        return False

    bound = 0 if side == "inward" else 1
    limits = node.context.radial_limits
    clear, cross = float(bound), limits[bound]
    for _ in range(SEARCH_STEPS):
        mid = (clear + cross) / 2.0
        try:
            regenerated = asm.regenerate(node, _with_limit(limits, bound, mid))
            crosses = _ink_crosses(asm, [path for *_, paths in regenerated for path in paths], neighbour, side)
        except MotifError:
            crosses = True
        if crosses:
            cross = mid
        else:
            clear = mid
    node.pull_backs[side] = node.pull_backs.get(side, 0) + 1
    _regenerate_and_commit(asm, node, side, _with_limit(limits, bound, clear))
    # The node was drawn afresh: touches it made are made again.
    for pulled in ("inward", "outward"):
        if pulled in node.pull_backs:
            _touch(asm, node, pulled, _neighbour(asm, node.ring_index, pulled))
    if _ink_crosses(asm, _subtree_paths(asm, node), neighbour, side):
        # The touch, or a shape the search never tried, still crosses: no overflow on this side at all.
        _regenerate_and_commit(asm, node, side, _with_limit(limits, bound, float(bound)))
        other_side = "outward" if side == "inward" else "inward"
        if other_side in node.pull_backs:
            _touch(asm, node, other_side, _neighbour(asm, node.ring_index, other_side))
    _restore_touches(asm, node)
    _redraw_reaches(asm, node, {id(path) for path in old_paths})
    return True


def _subtree_paths(asm: Assembler, node: PlacedNode) -> List[PlacedPath]:
    return [path for member in asm.subtree(node) for path in member.paths]


def _regenerate_and_commit(asm: Assembler, node: PlacedNode, side: str, limits: Tuple[float, float]) -> None:
    try:
        regenerated = asm.regenerate(node, limits)
    except MotifError as error:
        raise assembler.AssemblyError(
            f"ring {node.ring_index} cell {node.cell_index} ({node.position}): "
            f"{node.recipe.motif} fails with {side} overflow limited: {error}"
        ) from error
    asm.commit(regenerated)


def _restore_touches(asm: Assembler, node: PlacedNode) -> None:
    """Make every vertex of other rings' ink that lies on the node's new ink a vertex of it too."""
    for member in asm.subtree(node):
        for path in member.paths:
            geometry = path_geometry(path)
            touched = False
            for other in asm.index.candidates(geometry.buffer(ON_INK_PX)):
                if other.ring_index == node.ring_index:
                    continue
                for vertex in list(other.coords):
                    if geometry.distance(Point(vertex)) <= ON_INK_PX:
                        insert_vertex(path, vertex)
                        touched = True
            if touched:
                asm.reindex(path)


def _redraw_reaches(asm: Assembler, node: PlacedNode, old_ids: Set[int]) -> None:
    """Draw again every resolved reach that started on the node or ended on its old ink."""
    stale = [record for record in asm.resolved_reaches
             if record.pending[0] is node or (record.target is not None and id(record.target) in old_ids)]
    for record in stale:
        asm.resolved_reaches = [r for r in asm.resolved_reaches if r is not record]
        if record.path is not None:
            asm.paths = [path for path in asm.paths if path is not record.path]
            asm.reaches = [path for path in asm.reaches if path is not record.path]
            asm.index.remove(record.path)
    for record in stale:
        _resolve_pending(asm, record.pending)


def _touch(asm: Assembler, node: PlacedNode, side: str, neighbour: int) -> None:
    """Move the node's extreme vertex on `side` onto neighbour ink within `TOUCH_GAP_PX`."""
    extreme: Optional[Tuple[float, PlacedPath, int]] = None
    sign = 1.0 if side == "inward" else -1.0
    for path in node.paths:
        for i, radial in enumerate(path.radials):
            if extreme is None or sign * radial < extreme[0]:
                extreme = (sign * radial, path, i)
    if extreme is None:
        return
    _, path, i = extreme
    vertex = Point(path.coords[i])

    nearest: Optional[Tuple[float, PlacedPath]] = None
    for other in asm.index.candidates(vertex.buffer(TOUCH_GAP_PX)):
        if other.ring_index != neighbour:
            continue
        distance = path_geometry(other).distance(vertex)
        if distance <= TOUCH_GAP_PX and (nearest is None or distance < nearest[0]):
            nearest = (distance, other)
    if nearest is None:
        return
    other = nearest[1]
    projected = nearest_points(path_geometry(other), vertex)[0]
    landed = insert_vertex(other, (projected.x, projected.y))

    moved = [i]
    if path.closed and i in (0, len(path.coords) - 1):
        moved = [0, len(path.coords) - 1]
    for index in moved:
        path.coords[index] = landed
        path.radials[index] = _radial(node.context, landed)
    asm.reindex(other)
    asm.reindex(path)


# ----------------------------------------------------------------- reaches


def resolve_reach(asm: Assembler, node: PlacedNode, reach_end: ReachEnd, page_point: PointTuple,
                  rotation_deg: float) -> Optional[PlacedPath]:
    """Draw one reach from `node` to the first ink in its direction; None when nothing is drawn."""
    return _draw_reach(asm, node, reach_end, page_point)[0]


def _draw_reach(asm: Assembler, node: PlacedNode, reach_end: ReachEnd,
                page_point: PointTuple) -> Tuple[Optional[PlacedPath], Optional[PlacedPath]]:
    """The drawn reach (or None) and the ink it ends on (or None when it found none)."""
    subtree_ids = {id(path) for member in asm.subtree(node) for path in member.paths}
    cx, cy = asm.center
    dx, dy = cx - page_point[0], cy - page_point[1]
    norm = math.hypot(dx, dy)
    sign = 1.0 if reach_end.direction == "inward" else -1.0
    direction = (sign * dx / norm, sign * dy / norm)
    anchor = _anchor(node, page_point, direction)
    start = page_point if anchor is None else anchor[1]
    far = (start[0] + direction[0] * reach_end.max_length_px, start[1] + direction[1] * reach_end.max_length_px)
    exclude = lambda path: id(path) in subtree_ids
    hit = _first_hit(asm, LineString([start, far]), exclude)
    if hit is None and reach_end.direction == "inward":
        # The innermost ring is a closed band of ink, so an inward reach always lands
        # somewhere; past its declared length it runs on toward the centre.
        hit = _first_hit(asm, LineString([start, asm.center]), exclude)
    if hit is None:
        return None, None
    target, hit_point, _ = hit

    if anchor is not None:
        start = insert_vertex(anchor[0], start)
        asm.reindex(anchor[0])
    end = insert_vertex(target, hit_point)
    asm.reindex(target)
    if math.hypot(end[0] - start[0], end[1] - start[1]) <= ON_INK_PX:
        return None, target  # the start already lies on other ink: a touch, with a vertex on both

    coords = [start, end] if reach_end.style == "straight" else _wavy_clear_of_ink(asm, start, end)
    path = PlacedPath(
        node.ring_index, node.cell_index, node.position, node.node_path, "reach",
        coords, [_radial(node.context, point) for point in coords], False, asm.stroke_width,
    )
    asm.paths.append(path)
    asm.reaches.append(path)
    asm.index.add(path)
    return path, target


def _wavy_clear_of_ink(asm: Assembler, start: PointTuple, end: PointTuple) -> List[PointTuple]:
    """
    The wavy reach from `start` to `end`, its wave flattened step by step until
    it meets ink only at its two ends. The straight segment always qualifies,
    being the ray up to its first hit.
    """
    ends = (Point(start), Point(end))
    for scale in WAVY_FALLBACK_SCALES:
        coords = wavy_coords(start, end, scale)
        line = LineString(coords)
        if scale == 0.0 or all(_only_at(line.intersection(path_geometry(other)), ends)
                               for other in asm.index.candidates(line)):
            return coords
    return coords


def _only_at(hit: BaseGeometry, points: Sequence[Point]) -> bool:
    """Whether `hit` is empty or nothing but isolated points at `points`."""
    return all(
        part.geom_type == "Point" and any(part.distance(point) <= ON_INK_PX for point in points)
        for part in getattr(hit, "geoms", [hit]) if not part.is_empty
    )


def _first_hit(asm: Assembler, ray: LineString,
               exclude: Callable[[PlacedPath], bool]) -> Optional[Tuple[PlacedPath, PointTuple, float]]:
    """
    Like `InkIndex.first_hit`, but robust to float noise along seams: a ray
    along the seam where two cells' outlines meet can slip between their shared
    corners, run beside an edge without touching it, or meet it at a point that
    is not the first. Ink is also hit where the ray first comes within
    `ON_INK_PX` of it, at the ink's point nearest there.
    """
    best: Optional[Tuple[PlacedPath, PointTuple, float]] = None
    for path in asm.index.candidates(ray.buffer(ON_INK_PX)):
        if exclude(path):
            continue
        geometry = path_geometry(path)
        if not shapely.dwithin(geometry, ray, ON_INK_PX):
            continue
        zone = ray.intersection(geometry.buffer(ON_INK_PX))
        first = min(ray.project(Point(x, y)) for x, y in shapely.get_coordinates(zone))
        near = nearest_points(geometry, ray.interpolate(first))[0]
        points = [(near.x, near.y)] + [(float(x), float(y)) for x, y in
                                       shapely.get_coordinates(ray.intersection(geometry))]
        for point in points:
            along = ray.project(Point(point))
            if best is None or along < best[2]:
                best = (path, point, along)
    return best


def _anchor(node: PlacedNode, page_point: PointTuple,
            direction: PointTuple) -> Optional[Tuple[PlacedPath, PointTuple]]:
    """
    Where the reach starts, so that its start is a touch too: the node's own ink
    furthest along the reach's line in its direction, within two ring depths of
    the page point either way (a motif's ink, overflow included, lies closer). A stem whose page point lies inside its petal
    starts where it leaves the petal; one whose page point lies short of its
    band starts on the band. None when the line misses the node's ink.
    """
    span = 2.0 * node.context.ring_depth
    line = LineString([
        (page_point[0] - direction[0] * span, page_point[1] - direction[1] * span),
        (page_point[0] + direction[0] * span, page_point[1] + direction[1] * span),
    ])
    best: Optional[Tuple[float, PlacedPath, PointTuple]] = None
    for path in node.paths:
        geometry = path_geometry(path)
        points = [(float(x), float(y)) for x, y in shapely.get_coordinates(line.intersection(geometry))]
        if geometry.distance(Point(page_point)) <= ON_INK_PX:
            points.append(page_point)
        for point in points:
            along = line.project(Point(point))
            if best is None or along > best[0]:
                best = (along, path, point)
    return None if best is None else (best[1], best[2])


# ----------------------------------------------------------------- contact


def floating_base_cells(asm: Assembler, ring_index: Optional[int] = None) -> List[Tuple[int, int, str]]:
    """
    `(ring, cell, position)` of every base not connected to the structure, the
    component holding most of the innermost ring's bases; for one ring or all.
    """
    paths = asm.paths
    if not paths:
        return []
    ids = structural_components([path.coords for path in paths])
    innermost = min(ring.ring_index for ring in asm.plan.rings)
    counts: Dict[int, int] = {}
    for i, path in enumerate(paths):
        if path.role == "base" and path.ring_index == innermost:
            counts[ids[i]] = counts.get(ids[i], 0) + 1
    if not counts:
        return []
    structure = min(counts, key=lambda component: (-counts[component], component))
    return sorted({
        (path.ring_index, path.cell_index, path.position)
        for i, path in enumerate(paths)
        if path.role == "base" and ids[i] != structure and ring_index in (None, path.ring_index)
    })


# ------------------------------------------------------------------- order


def pass_two(asm: Assembler) -> None:
    for ring in asm.plan.rings:
        asm.current_ring = ring.ring_index
        _resolve_ring(asm, ring)
    asm.current_ring = None
    for ring in asm.plan.rings:
        inner = _neighbour(asm, ring.ring_index, "inward")
        own = [path for path in asm.paths if path.ring_index == ring.ring_index]
        if inner is not None and _ink_crosses(asm, own, inner):
            raise assembler.AssemblyError(
                f"ring {ring.ring_index} still crosses ring {inner} after {MAX_PULL_BACKS} pull-backs per side"
            )


def _resolve_ring(asm: Assembler, ring: RingPlan) -> None:
    """Resolve the ring's ink; replace floating cells and resolve again, up to `MAX_CONTACT_ROUNDS` times."""
    for round_number in range(MAX_CONTACT_ROUNDS + 1):
        _resolve_ring_ink(asm, ring.ring_index)
        floating = floating_base_cells(asm, ring.ring_index)
        if not floating:
            return
        if round_number == MAX_CONTACT_ROUNDS:
            raise assembler.AssemblyError(
                f"ring {ring.ring_index}: bases {floating} still float after {MAX_CONTACT_ROUNDS} replacement rounds"
            )
        before = [entry.to_dict() for entry in ring.sequence]
        targets = sorted({(cell % len(ring.sequence), position) for _, cell, position in floating})
        for seq_pos, position in targets:
            if not asm.composer.replace_node(ring, seq_pos, position, "floating"):
                raise assembler.AssemblyError(
                    f"ring {ring.ring_index} sequence {seq_pos} ({position}): floating base cannot be replaced"
                )
        changed = {seq_pos for seq_pos, _ in targets}
        changed.update(s for s, entry in enumerate(ring.sequence) if entry.to_dict() != before[s])
        asm.replace_cells(ring, sorted(changed))


def _resolve_ring_ink(asm: Assembler, ring_index: int) -> None:
    """
    Overflow inward then outward for every node of the ring, then its
    unresolved reaches. The inward ring's outward overflow was resolved against
    this ring's ink as pass one drew it; replaced cells change that ink, so it
    is checked again first.
    """
    inner = _neighbour(asm, ring_index, "inward")
    _settle(asm, [(node, "outward") for node in asm.nodes if node.ring_index == inner])
    nodes = [node for node in asm.nodes if node.ring_index == ring_index]
    for side in ("inward", "outward"):
        for node in nodes:
            if side not in node.resolved_sides and _is_placed(asm, node):
                resolve_overflow(asm, node, side)
    for pending in [p for p in asm.pending_reaches if p[0].ring_index == ring_index]:
        if any(record.pending is pending for record in asm.resolved_reaches):
            continue
        _resolve_pending(asm, pending)


def _is_placed(asm: Assembler, node: PlacedNode) -> bool:
    """False once regeneration has dropped the node."""
    return any(node is placed for placed in asm.nodes)


def _resolve_pending(asm: Assembler, pending: PendingReach) -> None:
    node, reach_end, page_point, _ = pending
    path, target = _draw_reach(asm, node, reach_end, page_point)
    asm.resolved_reaches.append(ResolvedReach(pending, path, target))
