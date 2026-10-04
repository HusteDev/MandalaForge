"""Shared maths for motifs that are placed inside a parent's slot."""

from __future__ import annotations

from dataclasses import dataclass

from motifs.contract import MotifError
from motifs.geometry import MotifContext

# Smallest drawable extent inside a slot, in pixels.
MIN_FIT_PX = 4.0


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
