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
import resolver
from shapely.geometry import Point
import shapely
from motifs.contract import ReachEnd
from motifs.geometry import CellPoint

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
    assert [r.motif for r in plan.rings[1].sequence[0].centre.attachments] == ["stem"]
    assert len(design.reaches) == 12
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

def test_inward_reach_runs_on_past_its_length_to_find_ink():
    a = placed(manual_plan())
    node, end, point, rotation = a.pending_reaches[0]
    short = ReachEnd(end.point, end.direction, 1.0, end.style)
    reach = a.resolve_reach(node, short, point, rotation)
    assert reach is not None
    petal = next(n for n in a.nodes if n is node)
    assert reach.coords[0] in petal.paths[0].coords
    hit = reach.coords[-1]
    assert any(hit in p.coords for p in a.paths if p.ring_index == 0)

def test_outward_reach_keeps_its_declared_length():
    a = placed(manual_plan())
    band = next(n for n in a.nodes if n.ring_index == 0 and n.cell_index == 0)
    # Start on the band's outer edge: the petals above are a few px away, beyond the 1px cap.
    edge = LineString(band.paths[0].coords).intersection(LineString([CENTER, (CENTER[0] + 100.0, CENTER[1])]))
    page_point = max(((x, y) for x, y in shapely.get_coordinates(edge)), key=lambda c: c[0])
    assert a.resolve_reach(band, ReachEnd(CellPoint(0.9, 0.0), "outward", 1.0), page_point, 0.0) is None

def test_slot_child_drop_is_per_cell():
    a = placed(manual_plan(), DEEP)
    petals = [n for n in a.nodes if n.recipe.motif == "petal"]
    first = petals[0]
    regenerated = a.regenerate(first, (-0.1, 1.25))
    child, _, context, _ = regenerated[1]
    a.commit([regenerated[0], (child, None, context, [])])
    assert first.child_dropped and child.recipe.dropped
    assert not any(p.child_dropped for p in petals[1:])
    # The shared recipe now reports a drop, yet another cell still gets its child.
    a.replace_cells(a.plan.rings[1], [0])
    assert all(len(a.subtree(n)) == 2 for n in a.nodes if n.recipe.motif == "petal")

import types
import resolver
from placement import InkIndex, PlacedPath

def stem_of_cell_zero(a):
    node, end, point, rotation = a.pending_reaches[0]
    assert node.cell_index == 0 and node.recipe.motif == "petal"
    return node, ReachEnd(end.point, end.direction, 1.0, end.style), point, rotation

def add_ink(a, ring_index, coords):
    path = PlacedPath(ring_index, 5, "centre", (0,), "base", list(coords), [0.5] * len(coords), False, 1.0)
    a.paths.append(path)
    a.index.add(path)
    return path

def test_pull_back_terminates_when_neighbours_keep_crossing(monkeypatch):
    monkeypatch.setattr(resolver, "_ink_crosses", lambda *args, **kwargs: True)
    a = Assembler(manual_plan(), GEOM, CENTER, 0.5, 10.0, composer_for(GEOM))
    with pytest.raises(AssemblyError, match="still crosses"):
        a.assemble()
    assert all(count <= resolver.MAX_PULL_BACKS for n in a.nodes for count in n.pull_backs.values())

def test_side_at_its_pull_back_cap_is_left_alone():
    a = placed(manual_plan(), DEEP)
    petal = next(n for n in a.nodes if n.recipe.motif == "petal")
    petal.pull_backs["inward"] = resolver.MAX_PULL_BACKS
    before = list(petal.paths[0].coords)
    a.resolve_overflow(petal, "inward")
    assert petal.paths[0].coords == before and petal.context.radial_limits == (-0.25, 1.25)

def test_reach_is_cast_forward_from_its_anchor():
    a = placed(manual_plan())
    node, short, point, rotation = stem_of_cell_zero(a)
    anchor = lowest_vertex(node.paths[0])
    between = (anchor[0] + point[0]) / 2.0  # ink behind the anchor, between it and the page point
    behind = add_ink(a, 1, [(between, CENTER[1] - 6.0), (between, CENTER[1] + 6.0)])
    reach = a.resolve_reach(node, short, point, rotation)
    assert reach.coords[0] == anchor
    assert len(behind.coords) == 2
    assert any(reach.coords[-1] in p.coords for p in a.paths if p.ring_index == 0)

def test_anchor_already_on_other_ink_is_a_touch_without_a_path():
    a = placed(manual_plan())
    node, short, point, rotation = stem_of_cell_zero(a)
    anchor = lowest_vertex(node.paths[0])
    through = add_ink(a, 0, [(anchor[0], CENTER[1] - 6.0), (anchor[0], CENTER[1] + 6.0)])
    assert a.resolve_reach(node, short, point, rotation) is None
    assert anchor in through.coords and not any(p.role == "reach" for p in a.paths)

def test_recast_onto_own_ring_ink_is_accepted_with_a_vertex():
    a = placed(manual_plan())
    node, short, point, rotation = stem_of_cell_zero(a)
    anchor = lowest_vertex(node.paths[0])
    x = anchor[0] - 4.0  # past the 1px cap, before ring 0's band
    own_ring = add_ink(a, 1, [(x, CENTER[1] - 6.0), (x, CENTER[1] + 6.0)])
    reach = a.resolve_reach(node, short, point, rotation)
    assert reach.coords[-1] in own_ring.coords
    assert math.isclose(reach.coords[-1][0], x, abs_tol=1e-9)

def test_touch_step_leaves_a_gap_over_two_px_alone():
    a = placed(manual_plan())
    petal = next(n for n in a.nodes if n.recipe.motif == "petal")
    band = [p for p in a.paths if p.ring_index == 0]
    gap = min(LineString(p.coords).distance(Point(lowest_vertex(petal.paths[0]))) for p in band)
    assert gap > resolver.TOUCH_GAP_PX
    before = [list(p.coords) for p in [petal.paths[0], *band]]
    resolver._touch(a, petal, "inward", 0)
    assert [list(p.coords) for p in [petal.paths[0], *band]] == before

def test_wavy_reach_flattens_when_the_wave_would_meet_ink():
    asm = types.SimpleNamespace(index=InkIndex())
    asm.index.add(PlacedPath(0, 0, "centre", (0,), "base", [(10.0, 2.0), (90.0, 2.0)], [0.5, 0.5], False, 1.0))
    coords = resolver._wavy_clear_of_ink(asm, (0.0, 0.0), (100.0, 0.0))
    offsets = [abs(y) for _, y in coords]
    assert len(coords) == 9 and math.isclose(max(offsets), 1.5, abs_tol=1e-9)
    assert coords[0] == (0.0, 0.0) and coords[-1] == (100.0, 0.0)


def test_final_contact_check_names_a_base_that_floated_after_its_ring_was_resolved():
    a = Assembler(manual_plan(), GEOM, CENTER, 0.5, 10.0, composer_for(GEOM))
    a.assemble()
    resolver.check_contact(a)
    reach = a.reaches[0]
    a.paths.remove(reach)
    a.index.remove(reach)
    with pytest.raises(AssemblyError, match=r"ring 1 cell 0 \(centre\).*floats"):
        resolver.check_contact(a)
