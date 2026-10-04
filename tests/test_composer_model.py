import random
from composer import CellRecipe, CellEntry, RingPlan, DesignPlan, node_rng

def test_plan_round_trips_through_json():
    leaf = CellRecipe("petal", "botanical", slot_child=CellRecipe("diamond", "geometric"),
                      attachments=[CellRecipe("stem", "botanical", provides_contact=True)])
    plan = DesignPlan(5, {"categories": ["botanical"], "positions": "both"},
                      [RingPlan(0, 8, 0.6, [CellEntry(leaf, None)], 5)])
    assert DesignPlan.from_json(plan.to_json()) == plan

def test_node_rng_is_stable_and_distinct():
    assert node_rng(1, 0, 0, 0, "centre").random() == node_rng(1, 0, 0, 0, "centre").random()
    assert node_rng(1, 0, 0, 0, "centre").random() != node_rng(1, 0, 0, 0, "divider").random()
