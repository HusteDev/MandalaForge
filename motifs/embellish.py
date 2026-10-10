"""
Embellishments: detail ink a host motif adds inside itself (spec section 6).

A generator draws its outline, then calls `apply_embellishments` before `build_instance`. The pipeline runs
`context.embellishments` in `EMBELLISHMENT_ORDER`, each from its own stream salted with its name, so adding
or dropping one never shifts another's draws. An embellishment that does not fit at this cell's pixel size,
or that is not implemented yet, is dropped and counted; the pipeline never raises.
"""

from __future__ import annotations

from dataclasses import dataclass
import random
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from shapely.geometry import LineString, MultiPoint, Point, Polygon

from motifs.contract import Anatomy, MotifError, inset_outline
from motifs.geometry import CellPoint, MotifContext, SmartVector, insert_vertex_on_outline, salted_seed
from topology_validator import MIN_REGION_AREA_PX2, PEN_RADIUS_PX

EMBELLISHMENT_ORDER = ("echo", "veins", "fan", "dot", "beads")
# At most one of these per host; a host with one offers no slot.
INTERIOR_FILLS = ("veins", "fan")
# At or above this complexity a host gets two echoes, below it one.
ECHO_TWO_AT = 0.6


@dataclass
class EmbellishResult:
    vectors: List[SmartVector]
    slot_outline: Optional[List[CellPoint]]
    slot_outline_weight: str
    dropped: int


@dataclass
class _State:
    vectors: List[SmartVector]
    slot_outline: Optional[List[CellPoint]]
    slot_outline_weight: str
    # Index of the innermost closed ring of ink: the host outline, or the last echo drawn.
    innermost: int


def embellishment_rng(context: MotifContext, name: str) -> random.Random:
    """The stream an embellishment draws from: the node's seed salted with `"emb:" + name`."""
    return random.Random(salted_seed(context.node_seed, "emb:" + name))


def _echo(context: MotifContext, state: _State, anatomy: Anatomy, rng: random.Random) -> int:
    """
    One echo, or two at `ECHO_TWO_AT` and above: each the innermost ink inset in page space by the
    clearance between its weight and a detail line, drawn closed at detail weight. Returns how many
    echoes did not fit. The slot, when the host offers one, moves inside the innermost echo.
    """
    wanted = 2 if context.complexity >= ECHO_TWO_AT else 1
    drawn = 0
    for _ in range(wanted):
        inner = state.vectors[state.innermost]
        try:
            echo = inset_outline(context, list(inner.points), context.clearance_px(inner.weight, "detail"))
        except MotifError:
            echo = None
        if echo is None or len(echo) < 3 or not _colourable(context, echo):
            break
        state.vectors.append(SmartVector(echo, closed=True, weight="detail"))
        state.innermost = len(state.vectors) - 1
        drawn += 1
    if drawn and state.slot_outline is not None:
        state.slot_outline = list(state.vectors[state.innermost].points)
        state.slot_outline_weight = "detail"
    return wanted - drawn


def _colourable(context: MotifContext, outline: List[CellPoint]) -> bool:
    """
    Whether the face inside a detail outline can be coloured: somewhere at least `min_white_space` of
    white between its own edges, and a face the topology validator would accept.
    """
    polygon = Polygon(context.polyline(SmartVector(list(outline), closed=True)))
    if not polygon.is_valid or polygon.area < MIN_REGION_AREA_PX2:
        return False
    return not polygon.buffer(-max(context.clearance_px("detail", "detail") / 2.0, PEN_RADIUS_PX)).is_empty


Handler = Callable[[MotifContext, _State, Anatomy, random.Random], int]

# Implemented embellishments; a name in EMBELLISHMENT_ORDER missing here is dropped until it arrives.
_HANDLERS: Dict[str, Handler] = {"echo": _echo}


def apply_embellishments(
    context: MotifContext,
    vectors: Sequence[SmartVector],
    anatomy: Optional[Anatomy],
    slot_outline: Optional[List[CellPoint]],
) -> EmbellishResult:
    """
    The host's `vectors` with `context.embellishments` added, in `EMBELLISHMENT_ORDER`, and the slot outline
    the host should declare (moved inside the innermost echo, or None after an interior fill). Every
    embellishment needs the host's anatomy; without it, or when it does not fit, it is dropped and counted.
    """
    requested = set(context.embellishments)
    state = _State(
        vectors=list(vectors),
        slot_outline=None if slot_outline is None else list(slot_outline),
        slot_outline_weight="outline",
        innermost=anatomy.outline if anatomy is not None else 0,
    )
    dropped = sum(1 for name in requested if name not in EMBELLISHMENT_ORDER)
    for name in EMBELLISHMENT_ORDER:
        if name not in requested:
            continue
        handler = _HANDLERS.get(name)
        if handler is None or anatomy is None:
            dropped += 1
            continue
        missed = handler(context, state, anatomy, embellishment_rng(context, name))
        dropped += missed
        if name in INTERIOR_FILLS and not missed:
            state.slot_outline = None
    return EmbellishResult(state.vectors, state.slot_outline, state.slot_outline_weight, dropped)


def innermost_ink(vectors: Sequence[SmartVector], anatomy: Anatomy) -> int:
    """Index of the innermost closed ring of ink: the last echo after the outline, else the outline."""
    innermost = anatomy.outline
    for index in range(anatomy.outline + 1, len(vectors)):
        vector = vectors[index]
        if vector.closed and vector.weight == "detail":
            innermost = index
    return innermost


def axis_span(points: List[CellPoint]) -> Optional[List[CellPoint]]:
    """
    Where the cell's centreline (angular 0) crosses the closed cell-space outline `points`: the lowest and
    highest crossings, or None when it does not cross twice.
    """
    radials = [p.radial for p in points]
    axis = LineString([(0.0, min(radials) - 1.0), (0.0, max(radials) + 1.0)])
    ring = Polygon([(p.angular, p.radial) for p in points]).exterior
    hit = axis.intersection(ring)
    if isinstance(hit, Point):
        coords = [hit.coords[0]]
    elif isinstance(hit, MultiPoint):
        coords = [geom.coords[0] for geom in hit.geoms]
    else:
        return None
    if len(coords) < 2:
        return None
    low, high = min(coords, key=lambda c: c[1]), max(coords, key=lambda c: c[1])
    return [CellPoint(low[1], 0.0), CellPoint(high[1], 0.0)]


def end_on_outline(vector: SmartVector, ends: Sequence[CellPoint],
                   tolerance: float = 1e-7) -> Tuple[SmartVector, List[CellPoint]]:
    """
    `vector` (closed) with each of `ends` made a vertex: an end within `tolerance` of a vertex snaps to it,
    one on an edge is inserted there. Returns the vector and the vertices the ends became.
    """
    points = list(vector.points)
    placed = []
    for end in ends:
        near = next((p for p in points if abs(p.radial - end.radial) <= tolerance
                     and abs(p.angular - end.angular) <= tolerance), None)
        if near is None:
            points = insert_vertex_on_outline(points, True, end, tolerance=tolerance)
            near = end
        placed.append(near)
    return SmartVector(points, closed=vector.closed, weight=vector.weight, layer=vector.layer), placed
