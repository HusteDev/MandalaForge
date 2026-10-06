import math
from assembler import Assembler, stroke_width_for
from composer import Composer, ComposerSettings, CellRecipe, CellEntry, RingPlan, DesignPlan

GEOM = [dict(inner_radius=40, outer_radius=100), dict(inner_radius=100, outer_radius=170)]
CENTER = (306.0, 306.0)

def manual_plan(divs=(8, 12)):
    inner = RingPlan(0, divs[0], 1.0, [CellEntry(CellRecipe("ring_band", "geometric", provides_contact=True), None)], 1)
    outer = RingPlan(1, divs[1], 1.0, [CellEntry(CellRecipe("petal", "botanical",
                     slot_child=CellRecipe("diamond", "geometric"),
                     attachments=[CellRecipe("stem", "botanical", provides_contact=True)]), None)], 1)
    return DesignPlan(1, {"categories": ["botanical", "geometric"], "positions": "centre"}, [inner, outer])

def build(plan):
    composer = Composer(1, GEOM, ComposerSettings(categories=["botanical", "geometric"]))
    a = Assembler(plan, GEOM, CENTER, 0.5, 10.0, composer)
    a.pass_one()
    return a

def test_stroke_width_formula():
    assert stroke_width_for(0.0) == 2.5 and stroke_width_for(1.0) == 1.75

def test_pass_one_places_every_cell():
    a = build(manual_plan())
    bases = {(n.ring_index, n.cell_index) for n in a.nodes if len(n.node_path) == 1}
    assert len([c for c in bases if c[0] == 0]) == 8 and len([c for c in bases if c[0] == 1]) == 12

def test_cells_are_rotated_to_their_angle():
    a = build(manual_plan())
    node = next(n for n in a.nodes if n.ring_index == 1 and n.cell_index == 3 and len(n.node_path) == 1)
    xs = [x for x, y in node.paths[0].coords]; ys = [y for x, y in node.paths[0].coords]
    cx, cy = sum(xs) / len(xs) - CENTER[0], sum(ys) / len(ys) - CENTER[1]
    assert math.isclose(math.degrees(math.atan2(cy, cx)) % 360, 90.0, abs_tol=3.0)

def test_slot_child_is_placed_inside_parent_slot():
    a = build(manual_plan())
    child = next(n for n in a.nodes if n.recipe.motif == "diamond")
    assert child.parent.recipe.motif == "petal" and not child.recipe.dropped

def test_slot_child_dropped_when_margin_too_large():
    composer = Composer(1, GEOM, ComposerSettings(categories=["botanical", "geometric"]))
    a = Assembler(manual_plan(), GEOM, CENTER, 0.5, 50.0, composer)
    a.pass_one()
    assert a.dropped_children == 12

def test_reach_ends_recorded_but_not_drawn():
    a = build(manual_plan())
    assert not any(p.role == "reach" for p in a.paths)
    assert len(a.pending_reaches) == 12
    base = next(n for n in a.nodes if n.recipe.motif == "petal")
    child = next(n for n in a.nodes if n.parent is base)
    assert base.attachment_seeds[0] != child.rng_seed

def test_radials_track_overflow():
    a = build(manual_plan())
    petal = next(n for n in a.nodes if n.recipe.motif == "petal")
    assert max(petal.paths[0].radials) == max(p.radial for v in petal.instance.vectors for p in v.points)
