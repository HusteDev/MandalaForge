import math
from shapely.geometry import LineString
from assembler import Assembler, AssemblyError
from composer import Composer, ComposerSettings, CellRecipe, CellEntry, RingPlan, DesignPlan
from topology_validator import TopologyValidator, structural_components
from tests.test_assembler_pass_one import GEOM, CENTER, manual_plan

def assemble(plan, mws=10.0):
    composer = Composer(1, GEOM, ComposerSettings(categories=["botanical", "geometric"]))
    return Assembler(plan, GEOM, CENTER, 0.5, mws, composer).assemble()

def validate(design):
    return TopologyValidator(snap_tolerance=2.5, whisker_tolerance=5.0, pen_radius=2.0, min_region_area=20.0).analyze(
        design.polylines(), center=CENTER, base_mask=design.base_mask(),
        ring_ids=design.ring_ids(), overflow_parts=design.overflow_parts())

def test_stems_land_on_inner_ring_ink():
    design = assemble(manual_plan())
    assert len(design.reaches) == 12
    for reach in design.reaches:
        end = reach.coords[-1]
        assert math.hypot(end[0] - CENTER[0], end[1] - CENTER[1]) < 100.0

def test_overflow_never_crosses_neighbour_ink():
    design = assemble(manual_plan())
    report = validate(design)
    assert report.stats["num_overflow_crossings"] == 0

def test_all_bases_share_one_component():
    design = assemble(manual_plan())
    report = validate(design)
    assert report.stats["num_floating_base"] == 0

def test_coprime_counts_still_assemble_and_validate():
    design = assemble(manual_plan(divs=(7, 12)))
    report = validate(design)
    assert report.stats["num_dangles"] == 0 and report.stats["num_floating_base"] == 0

def test_touch_inserts_vertex_into_target_path():
    design = assemble(manual_plan())
    reach = design.reaches[0]
    hit = reach.coords[-1]
    assert any(any(math.isclose(x, hit[0], abs_tol=1e-6) and math.isclose(y, hit[1], abs_tol=1e-6)
                   for x, y in p.coords) for p in design.paths if p.role != "reach")

def test_wavy_reach_has_interior_points():
    plan = manual_plan()
    composer = Composer(1, GEOM, ComposerSettings(categories=["botanical", "geometric"]))
    design = Assembler(plan, GEOM, CENTER, 0.9, 10.0, composer).assemble()
    assert all(len(r.coords) == 9 for r in design.reaches)

def test_assembly_is_deterministic():
    a = assemble(manual_plan()); b = assemble(manual_plan())
    assert [p.coords for p in a.paths] == [p.coords for p in b.paths]


# ----- behaviour beyond the brief's tests -----

import pytest
from motifs.contract import ReachEnd

# Ring 1 deep enough that the petal's inward dip crosses ring 0's band.
DEEP = [dict(inner_radius=40, outer_radius=100), dict(inner_radius=100, outer_radius=220)]

def composer_for(geom, **settings):
    return Composer(1, geom, ComposerSettings(categories=["botanical", "geometric"], **settings))

def placed(plan, geom=GEOM):
    a = Assembler(plan, geom, CENTER, 0.5, 10.0, composer_for(geom))
    a.pass_one()
    return a

def crosses(a, b):
    """True unless the paths meet only at isolated points that are vertices of both: an exact touch."""
    hit = LineString(a.coords).intersection(LineString(b.coords))
    return not all(part.geom_type == "Point" and (part.x, part.y) in a.coords and (part.x, part.y) in b.coords
                   for part in getattr(hit, "geoms", [hit]) if not part.is_empty)

def lowest_vertex(path):
    return path.coords[min(range(len(path.radials)), key=lambda i: path.radials[i])]

def test_crossing_overflow_is_pulled_back_to_touch_the_band():
    a = placed(manual_plan(), DEEP)
    petal = next(n for n in a.nodes if n.recipe.motif == "petal")
    band = [p for p in a.paths if p.ring_index == 0]
    assert any(crosses(petal.paths[0], p) for p in band)
    a.resolve_overflow(petal, "inward")
    assert -0.25 < petal.context.radial_limits[0] < 0.0
    assert not any(crosses(petal.paths[0], p) for p in band)
    tip = lowest_vertex(petal.paths[0])
    assert any(tip in p.coords for p in band)
    assert len(a.index) == len(a.paths)

def test_overflow_clear_of_neighbour_is_left_alone():
    a = placed(manual_plan())
    petal = next(n for n in a.nodes if n.recipe.motif == "petal")
    before = list(petal.paths[0].coords)
    a.resolve_overflow(petal, "inward")
    assert petal.paths[0].coords == before and petal.context.radial_limits == (-0.25, 1.25)

def test_innermost_inward_and_outermost_outward_are_kept():
    a = placed(manual_plan())
    band = next(n for n in a.nodes if n.ring_index == 0)
    petal = next(n for n in a.nodes if n.recipe.motif == "petal")
    a.resolve_overflow(band, "inward")
    a.resolve_overflow(petal, "outward")
    assert band.context.radial_limits == (0.0, 1.0) and petal.context.radial_limits == (-0.25, 1.25)

def test_regeneration_carries_the_slot_child_along():
    a = placed(manual_plan(), DEEP)
    petal = next(n for n in a.nodes if n.recipe.motif == "petal")
    child = a.subtree(petal)[1]
    before = list(child.paths[0].coords)
    a.resolve_overflow(petal, "inward")
    assert a.subtree(petal) == [petal, child] and child.paths[0].coords != before
    assert all(p in a.paths for p in child.paths)

def test_commit_drops_a_child_that_no_longer_fits():
    a = placed(manual_plan(), DEEP)
    petal = next(n for n in a.nodes if n.recipe.motif == "petal")
    regenerated = a.regenerate(petal, (-0.1, 1.25))
    child, _, context, _ = regenerated[1]
    a.commit([regenerated[0], (child, None, context, [])])
    assert child not in a.nodes and child.recipe.dropped and a.dropped_children == 1
    assert not any(p in a.paths for p in child.paths)
    assert len(a.index) == len(a.paths)

def test_reach_starts_on_its_own_motif():
    design = assemble(manual_plan())
    petals = [n for n in design.nodes if n.recipe.motif == "petal"]
    for reach in design.reaches:
        petal = next(n for n in petals if n.cell_index == reach.cell_index)
        assert reach.coords[0] in petal.paths[0].coords

def test_wavy_reach_ends_exactly_on_ink():
    composer = composer_for(GEOM)
    design = Assembler(manual_plan(), GEOM, CENTER, 0.9, 10.0, composer).assemble()
    for reach in design.reaches:
        others = [p for p in design.paths if p is not reach]
        assert any(reach.coords[0] in p.coords for p in others)
        assert any(reach.coords[-1] in p.coords for p in others)

def test_reach_radials_are_in_its_own_ring():
    design = assemble(manual_plan())
    for reach in design.reaches:
        for (x, y), radial in zip(reach.coords, reach.radials):
            assert math.isclose(100.0 + 70.0 * radial, math.hypot(x - CENTER[0], y - CENTER[1]), abs_tol=1e-9)

def test_reach_with_nothing_in_range_draws_nothing():
    a = placed(manual_plan())
    node, end, point, rotation = a.pending_reaches[0]
    short = ReachEnd(end.point, end.direction, 1.0, end.style)
    assert a.resolve_reach(node, short, point, rotation) is None
    assert not any(p.role == "reach" for p in a.paths)

def test_floating_base_cells_lists_unconnected_bases():
    a = placed(manual_plan())
    a.current_ring = 1
    assert a.floating_base_cells() == [(1, c, "centre") for c in range(12)]
    a.current_ring = 0
    assert a.floating_base_cells() == []

def test_floating_cell_is_replaced_and_reassembled():
    plan = manual_plan()
    plan.rings[1].sequence[0] = CellEntry(CellRecipe("ring_band", "geometric"), None)
    a = Assembler(plan, GEOM, CENTER, 0.5, 10.0, composer_for(GEOM))
    design = a.assemble()
    assert plan.rings[1].sequence[0].centre.motif != "ring_band"
    assert validate(design).stats["num_floating_base"] == 0
    assert len(a.index) == len(a.paths) and all(r in design.paths for r in design.reaches)
    assert [n.cell_index for n in design.nodes if n.ring_index == 1 and len(n.node_path) == 1] == list(range(12))

def test_floating_cell_that_cannot_be_replaced_raises():
    plan = manual_plan()
    plan.rings[1].sequence[0] = CellEntry(CellRecipe("ring_band", "geometric"), None)
    composer = composer_for(GEOM, force_motif={"name": "ring_band", "position": "centre", "role": "base"})
    with pytest.raises(AssemblyError, match="floating base cannot be replaced"):
        Assembler(plan, GEOM, CENTER, 0.5, 10.0, composer).assemble()

def test_composer_plans_assemble_deterministically():
    geom = [dict(inner_radius=40 + 60 * i, outer_radius=100 + 60 * i) for i in range(4)]
    def run():
        composer = Composer(4, geom, ComposerSettings(complexity=0.5, categories=["botanical", "geometric"]))
        return Assembler(composer.plan(), geom, CENTER, 0.5, 10.0, composer).assemble()
    a, b = run(), run()
    assert [p.coords for p in a.paths] == [p.coords for p in b.paths]
    report = validate(a)
    assert report.stats["num_dangles"] == 0 and report.stats["num_floating_base"] == 0
