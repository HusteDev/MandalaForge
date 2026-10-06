from composer import CellRecipe, CellEntry, RingPlan, DesignPlan
from tests.test_assembler_pass_two import assemble, validate

def petal_over_band_plan():
    inner = RingPlan(0, 8, 1.0, [CellEntry(CellRecipe("ring_band", "geometric", provides_contact=True), None)], 1)
    outer = RingPlan(1, 8, 1.0, [CellEntry(CellRecipe("petal", "botanical", provides_contact=True), None)], 3)
    return DesignPlan(3, {"categories": ["botanical", "geometric"], "positions": "centre"}, [inner, outer])

def both_positions_plan():
    inner = RingPlan(0, 8, 1.0, [CellEntry(CellRecipe("ring_band", "geometric", provides_contact=True), None)], 1)
    entry = CellEntry(CellRecipe("petal", "botanical", attachments=[CellRecipe("stem", "botanical", provides_contact=True)]),
                      CellRecipe("petal", "botanical", attachments=[CellRecipe("stem", "botanical", provides_contact=True)]))
    outer = RingPlan(1, 8, 0.6, [entry], 5)
    return DesignPlan(5, {"categories": ["botanical"], "positions": "both"}, [inner, outer])

def test_petal_inward_overflow_stops_at_band():
    report = validate(assemble(petal_over_band_plan()))
    assert report.stats["num_overflow_crossings"] == 0 and report.stats["num_dangles"] == 0

def test_centre_and_divider_petals_coexist_without_crossing():
    design = assemble(both_positions_plan())
    report = validate(design)
    assert report.stats["num_floating_base"] == 0
    assert report.stats["num_uncolorable_regions"] == 0
