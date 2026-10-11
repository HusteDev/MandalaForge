"""Reaches from a band ring, against the real band geometry (no pinned band ranges, unlike test_assembler_pass_two)."""
from shapely.geometry import LineString
from composer import CellEntry, CellRecipe
from tests.test_assembler_pass_one import manual_plan
from tests.test_assembler_pass_two import assemble, validate


def band_ring_plan():
    plan = manual_plan()
    plan.rings[1].sequence[0] = CellEntry(CellRecipe(
        "band", "geometric", attachments=[CellRecipe("stem", "botanical", provides_contact=True)]), None)
    return plan


def test_stems_from_a_band_ring_are_drawn_curved():
    # A band's stems start on its lens tips, which its inner arc passes through: they keep their curves.
    design = assemble(band_ring_plan())
    stems = [r for r in design.reaches if r.ring_index == 1]
    assert stems
    assert all(LineString([r.coords[0], r.coords[-1]]).hausdorff_distance(LineString(r.coords)) > 0.5
               for r in stems)


def test_band_ring_plan_validates_with_the_real_band():
    report = validate(assemble(band_ring_plan()))
    assert report.is_valid, report.issues
