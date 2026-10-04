"""Shared maths for motifs that are placed inside a parent's slot."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List

from shapely.geometry import Polygon

from motifs.contract import MotifError
from motifs.geometry import CellPoint, MotifContext

# Smallest drawable extent inside a slot, in pixels.
MIN_FIT_PX = 4.0

# A slot child is shrunk by this factor until it lies inside the slot polygon,
# and rejected once it would have to be smaller than MIN_FIT_SCALE of its box fit.
SHRINK_FACTOR = 0.92
MIN_FIT_SCALE = 0.4


@dataclass(frozen=True)
class SlotBox:
    """Cell-space bounding box of a slot, inset by a stroke-width margin."""

    radial_min: float
    radial_max: float
    half_width: float

    @property
    def radial_mid(self) -> float:
        return (self.radial_min + self.radial_max) / 2.0


def fit_slot_box(context: MotifContext, motif_name: str) -> SlotBox:
    """
    Bounding box of `context.slot` less a stroke-width margin. The slot is already inset from its parent's ink by the
    white-space clearance, so a child may sit a stroke width inside its edge.

    Raises `MotifError` when there is no slot, or when less than `MIN_FIT_PX` is
    left across the radial half-span or the angular half-width.
    """
    slot = context.slot
    if not slot:
        raise MotifError(f"{motif_name} requires a slot")

    radials = [point.radial for point in slot]
    angulars = [point.angular for point in slot]
    radial_min, radial_max = min(radials), max(radials)
    angular_min, angular_max = min(angulars), max(angulars)
    mid_radial = (radial_min + radial_max) / 2.0

    margin_radial = context.px_to_radial(context.stroke_width)
    margin_angular = context.px_to_angular(context.stroke_width, mid_radial)
    base = radial_min + margin_radial
    tip = radial_max - margin_radial
    half_width = (angular_max - angular_min) / 2.0 - margin_angular

    if (
        (tip - base) / 2.0 < context.px_to_radial(MIN_FIT_PX)
        or half_width < context.px_to_angular(MIN_FIT_PX, mid_radial)
    ):
        raise MotifError(f"{motif_name} does not fit slot")
    return SlotBox(radial_min=base, radial_max=tip, half_width=half_width)


def _polygon(points: List[CellPoint]) -> Polygon:
    return Polygon([(point.angular, point.radial) for point in points])


def fit_inside_slot(
    context: MotifContext,
    motif_name: str,
    builder: Callable[[float], List[CellPoint]],
) -> List[CellPoint]:
    """
    Outline from `builder(scale)`, shrunk until it lies inside the slot polygon.

    The slot box is only the bounding box of the slot, so a child fitted to it can
    poke through a curved slot edge. `builder` scales its extents about the slot
    box centre; the scale starts at 1.0 and drops by `SHRINK_FACTOR` until
    containment holds in cell space. Raises `MotifError` when the child would need
    to be smaller than `MIN_FIT_SCALE`.
    """
    slot = _polygon(list(context.slot or []))
    scale = 1.0
    while scale >= MIN_FIT_SCALE:
        outline = builder(scale)
        child = _polygon(outline)
        if child.is_valid and slot.contains(child):
            return outline
        scale *= SHRINK_FACTOR
    raise MotifError(f"{motif_name} does not fit slot")
