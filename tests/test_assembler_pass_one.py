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


# ----- behaviour beyond the brief's tests -----

import pytest
from shapely.geometry import Point, LineString
from assembler import AssemblyError
from placement import path_overflow
from motifs.geometry import cell_rotation_deg

def slot_motif_base_plan():
    plan = manual_plan()
    plan.rings[1].sequence[0].centre = CellRecipe("diamond", "geometric")
    return plan

def test_failing_base_is_replaced_and_ink_rewound():
    plan = slot_motif_base_plan()
    a = build(plan)
    replaced = plan.rings[1].sequence[0].centre
    assert replaced.is_fallback or replaced.motif != "diamond"
    assert len([n for n in a.nodes if n.ring_index == 1 and len(n.node_path) == 1]) == 12
    assert len(a.index) == len(a.paths)

def test_unreplaceable_base_raises_assembly_error():
    force = {"name": "diamond", "position": "centre", "role": "base"}
    composer = Composer(1, GEOM, ComposerSettings(categories=["botanical", "geometric"], force_motif=force))
    with pytest.raises(AssemblyError):
        Assembler(slot_motif_base_plan(), GEOM, CENTER, 0.5, 10.0, composer).pass_one()

def test_petal_inward_overflow_ends_on_the_boundary_circle():
    a = build(manual_plan())
    petals = [n for n in a.nodes if n.recipe.motif == "petal"]
    assert len(petals) == 12
    for petal in petals:
        inward = [line for side, line in path_overflow(petal.paths[0], CENTER) if side == "inward"]
        assert len(inward) == 1
        for x, y in (inward[0].coords[0], inward[0].coords[-1]):
            assert math.isclose(math.hypot(x - CENTER[0], y - CENTER[1]), 100.0, abs_tol=1e-6)

def test_first_hit_from_ring_one_boundary_finds_ring_zero_ink():
    a = build(manual_plan())
    start = (CENTER[0] + 100.0, CENTER[1])
    ray = LineString([start, (CENTER[0] + 30.0, CENTER[1])])
    path, point, distance = a.index.first_hit(ray, lambda p: p.ring_index == 1)
    assert path.ring_index == 0
    assert math.isclose(distance, ray.project(Point(point)), abs_tol=1e-9)

def test_every_path_has_a_radial_per_coordinate():
    a = build(manual_plan())
    assert all(len(p.radials) == len(p.coords) for p in a.paths)

def test_pass_one_is_deterministic():
    assert [p.coords for p in build(manual_plan()).paths] == [p.coords for p in build(manual_plan()).paths]

def test_divider_cells_sit_at_divider_rotation():
    plan = manual_plan()
    plan.rings[1].sequence[0] = CellEntry(None, CellRecipe("petal", "botanical"))
    a = build(plan)
    for cell in (0, 3, 7):
        node = next(n for n in a.nodes if n.ring_index == 1 and n.cell_index == cell)
        xs = [x for x, y in node.paths[0].coords]; ys = [y for x, y in node.paths[0].coords]
        angle = math.degrees(math.atan2(sum(ys) / len(ys) - CENTER[1], sum(xs) / len(xs) - CENTER[0])) % 360
        assert math.isclose(angle, cell_rotation_deg(cell, 12, "divider"), abs_tol=3.0)

def test_failing_attachment_is_dropped_not_mistaken_for_base_failure():
    plan = manual_plan()
    plan.rings[1].sequence[0].centre.attachments = [CellRecipe("diamond", "geometric")]
    a = build(plan)
    assert a.dropped_attachments == 12 and a.pending_reaches == []
    assert plan.rings[1].sequence[0].centre.motif == "petal"
    assert len(a.index) == len(a.paths)

def test_empty_sequence_raises_assembly_error():
    plan = manual_plan()
    plan.rings[1].sequence = []
    with pytest.raises(AssemblyError, match="ring 1 has an empty sequence"):
        build(plan)
