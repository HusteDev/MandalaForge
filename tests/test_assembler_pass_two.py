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

def test_forced_floating_cell_gets_a_stem():
    plan = manual_plan()
    plan.rings[1].sequence[0] = CellEntry(CellRecipe("ring_band", "geometric"), None)
    composer = composer_for(GEOM, force_motif={"name": "ring_band", "position": "centre", "role": "base"})
    design = Assembler(plan, GEOM, CENTER, 0.5, 10.0, composer).assemble()
    assert [r.motif for r in plan.rings[1].sequence[0].centre.attachments] == ["stem"]
    assert validate(design).stats["num_floating_base"] == 0

def test_floating_cell_that_cannot_be_replaced_raises():
    # The cell already has an attachment (a ring_band draws no reach), so the stem repair is spent and forcing forbids a swap.
    plan = manual_plan()
    plan.rings[1].sequence[0] = CellEntry(
        CellRecipe("ring_band", "geometric", attachments=[CellRecipe("ring_band", "geometric")]), None
    )
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

def test_touch_step_leaves_a_gap_over_the_touch_gap_alone():
    a = placed(manual_plan())
    petal = next(n for n in a.nodes if n.recipe.motif == "petal")
    band = [p for p in a.paths if p.ring_index == 0]
    gap = min(LineString(p.coords).distance(Point(lowest_vertex(petal.paths[0]))) for p in band)
    assert gap > resolver.TOUCH_GAP_PX
    before = [list(p.coords) for p in [petal.paths[0], *band]]
    resolver._touch(a, petal, "inward", 0)
    assert [list(p.coords) for p in [petal.paths[0], *band]] == before

def test_wavy_reach_flattens_when_the_wave_would_meet_ink():
    # Ink the full wave would meet is within a pen's width of every lesser wave too: the reach goes straight.
    asm = types.SimpleNamespace(index=InkIndex(), min_white_space=10.0)
    asm.index.add(PlacedPath(0, 0, "centre", (0,), "base", [(10.0, 2.0), (90.0, 2.0)], [0.5, 0.5], False, 1.0))
    coords = resolver._wavy_clear_of_ink(asm, (0.0, 0.0), (100.0, 0.0))
    offsets = [abs(y) for _, y in coords]
    assert len(coords) == 9 and max(offsets) == 0.0
    assert coords[0] == (0.0, 0.0) and coords[-1] == (100.0, 0.0)

def test_wavy_reach_flattens_until_it_keeps_a_pen_width_from_ink():
    # The wave peaks 3px toward ink 5px off its line; it halves until the peak stays 4px clear (0.75px).
    asm = types.SimpleNamespace(index=InkIndex(), min_white_space=10.0)
    asm.index.add(PlacedPath(0, 0, "centre", (0,), "base", [(15.0, 5.0), (85.0, 5.0)], [0.5, 0.5], False, 1.0))
    coords = resolver._wavy_clear_of_ink(asm, (0.0, 0.0), (100.0, 0.0))
    assert math.isclose(max(abs(y) for _, y in coords), 0.75, abs_tol=1e-9)


def test_final_contact_check_names_a_base_that_floated_after_its_ring_was_resolved():
    a = Assembler(manual_plan(), GEOM, CENTER, 0.5, 10.0, composer_for(GEOM))
    a.assemble()
    resolver.check_contact(a)
    reach = a.reaches[0]
    a.paths.remove(reach)
    a.index.remove(reach)
    with pytest.raises(AssemblyError, match=r"ring 1 cell 0 \(centre\).*floats"):
        resolver.check_contact(a)


def _slit(spread):
    # Two lines from one point, `spread` apart 40px along: a reach across their open end closes a face.
    asm = types.SimpleNamespace(index=InkIndex())
    asm.index.add(PlacedPath(0, 0, "centre", (0,), "base", [(0.0, 0.0), (40.0, spread / 2)], [0.5, 0.5], False, 1.0))
    asm.index.add(PlacedPath(0, 1, "centre", (0,), "base", [(0.0, 0.0), (40.0, -spread / 2)], [0.5, 0.5], False, 1.0))
    return asm

def test_reach_that_would_close_a_slit_too_thin_to_colour_is_refused():
    assert resolver._closes_uncolourable_face(_slit(3.0), 0, [(40.0, 1.5), (40.0, -1.5)])
    assert not resolver._closes_uncolourable_face(_slit(40.0), 0, [(40.0, 20.0), (40.0, -20.0)])

def test_wavy_reach_is_refused_when_no_flattening_is_accepted():
    asm = types.SimpleNamespace(index=InkIndex(), min_white_space=10.0)
    assert resolver._wavy_clear_of_ink(asm, (0.0, 0.0), (100.0, 0.0), lambda coords: False) is None

def test_touch_within_the_touch_radius_of_a_vertex_reuses_it():
    # A second touch landing 3e-7px from an earlier one used to add a vertex beside it; once both lines
    # held both vertices they overlapped along a sub-micron segment, which the validator reads as a crossing.
    path = PlacedPath(0, 0, "centre", (0,), "base", [(0.0, 0.0), (10.0, 0.0), (20.0, 0.0)], [0.5, 0.5, 0.5], False, 1.0)
    assert resolver.insert_vertex(path, (10.0 + 3e-7, 0.0)) == (10.0, 0.0)
    assert len(path.coords) == 3

def test_final_touch_pass_snaps_a_tip_within_clearance_that_was_never_pulled_back():
    a = placed(manual_plan())
    petal = next(n for n in a.nodes if n.recipe.motif == "petal")
    tip = lowest_vertex(petal.paths[0])
    assert min(petal.paths[0].radials) < 0.0 and not petal.pull_backs
    # Neighbour ink 3px further toward the centre, square to the tip's radius: no crossing, no crowding.
    cx, cy = CENTER
    radius = math.hypot(tip[0] - cx, tip[1] - cy)
    ux, uy = (tip[0] - cx) / radius, (tip[1] - cy) / radius
    foot = (cx + ux * (radius - 3.0), cy + uy * (radius - 3.0))
    ink = add_ink(a, 0, [(foot[0] - uy * 2.0, foot[1] + ux * 2.0), (foot[0] + uy * 2.0, foot[1] - ux * 2.0)])
    resolver.final_touches(a)
    new_tip = lowest_vertex(petal.paths[0])
    assert new_tip in ink.coords
    assert math.isclose(math.hypot(new_tip[0] - foot[0], new_tip[1] - foot[1]), 0.0, abs_tol=1e-6)

def test_final_touch_is_undone_when_the_moved_tip_crowds_the_neighbours_overflow():
    # Seed 777 (vary_divisions): a ring-1 petal's outward tip was touched onto ring-2 ink, which kept its own
    # side clear, but the moved tip came within a pen's width of a ring-2 scallop's inward overflow outside
    # that run's touch disc, and the final check raised. The touch is judged from both rings.
    a = placed(manual_plan())
    petal = next(n for n in a.nodes if n.recipe.motif == "petal")
    tip = lowest_vertex(petal.paths[0])
    cx, cy = CENTER
    radius = math.hypot(tip[0] - cx, tip[1] - cy)
    ux, uy = (tip[0] - cx) / radius, (tip[1] - cy) / radius
    at = lambda u, w: (tip[0] + ux * u - uy * w, tip[1] + uy * u + ux * w)  # u along the radius, w across it
    target = add_ink(a, 0, [at(-3.0, -2.0), at(-3.0, 2.0)])  # 3px further in, square to the tip's radius
    # Ring-0 overflow past its outer boundary: down well to the tip's side, then in, square to the radius,
    # 4px further in than the tip, ending 3px to its side; its extreme vertex is far from that end.
    run = [at(5.0, 25.0), at(-4.0, 25.0), at(-4.0, 3.0)]
    facing = PlacedPath(0, 6, "centre", (0,), "base", run, [1.2] * len(run), False, 1.0)
    a.paths.append(facing)
    a.index.add(facing)
    assert not resolver._too_close(a, [facing], 1, "outward")
    assert min(LineString(run).distance(LineString(p.coords)) for p in petal.paths) > resolver.CLEARANCE_PX
    resolver.final_touches(a)
    # Touched, the tip would sit 3.2px from the run's end: the touch is undone.
    assert lowest_vertex(petal.paths[0]) == tip
    assert tip not in target.coords
    assert not resolver._too_close(a, [facing], 1, "outward")

def test_grazing_reach_runs_along_its_ray_then_bends_onto_the_ink():
    a = placed(manual_plan())
    node, short, point, rotation = stem_of_cell_zero(a)
    anchor = lowest_vertex(node.paths[0])
    # A short stroke 3px beside the reach's ray (which runs toward the centre along y = anchor y), its end 3.9px on.
    x, y = anchor[0] - 3.9, anchor[1] + 3.0
    beside = add_ink(a, 1, [(x, y), (x, y + 5.0)])
    reach = a.resolve_reach(node, short, point, rotation)
    assert len(reach.coords) == 3
    lead = reach.coords[1]
    assert math.isclose(lead[1], anchor[1], abs_tol=1e-6)  # still on the ray
    assert math.isclose(math.hypot(lead[0] - x, lead[1] - y), resolver.TOUCH_GAP_PX, abs_tol=0.01)
    assert reach.coords[-1] in beside.coords and math.isclose(reach.coords[-1][0], x, abs_tol=1e-9)

def test_reach_shorter_than_a_pen_width_is_a_touch():
    a = placed(manual_plan())
    node, short, point, rotation = stem_of_cell_zero(a)
    anchor = lowest_vertex(node.paths[0])
    x = anchor[0] - 3.0  # 3px on along the reach's ray, square to it
    near = add_ink(a, 1, [(x, anchor[1] - 6.0), (x, anchor[1] + 6.0)])
    assert a.resolve_reach(node, short, point, rotation) is None
    assert not any(p.role == "reach" for p in a.paths)
    tip = lowest_vertex(node.paths[0])
    assert tip in near.coords and math.isclose(tip[0], x, abs_tol=1e-9)

def test_a_vertex_shared_with_the_nodes_own_ink_is_not_moved():
    # A leaf's midrib ends on its outline's apex; moving the apex for a touch would leave the midrib dangling.
    asm = types.SimpleNamespace(index=InkIndex())
    outline = PlacedPath(1, 0, "centre", (0,), "base", [(0.0, 0.0), (10.0, 5.0), (20.0, 0.0)], [0.0, 1.1, 0.0], False, 1.0)
    midrib = PlacedPath(1, 0, "centre", (0,), "base", [(10.0, 0.0), (10.0, 5.0)], [0.0, 1.1], False, 1.0)
    asm.index.add(outline)
    asm.index.add(midrib)
    assert resolver._shared_with_other_ink(asm, outline, (10.0, 5.0))
    assert not resolver._shared_with_other_ink(asm, outline, (20.0, 0.0))

def test_pull_back_touch_never_detaches_a_leafs_midrib():
    # A leaf's midrib ends on its outline's apex; the touch after a pull-back must not move that shared apex.
    geom = [dict(inner_radius=40, outer_radius=100), dict(inner_radius=100, outer_radius=200),
            dict(inner_radius=200, outer_radius=240)]
    plan = DesignPlan(1, {"categories": ["botanical", "geometric"], "positions": "centre"}, [
        RingPlan(0, 8, 1.0, [CellEntry(CellRecipe("ring_band", "geometric", provides_contact=True), None)], 1),
        RingPlan(1, 12, 1.0, [CellEntry(CellRecipe("leaf", "botanical"), None)], 11),  # apex at radial 1.12
        RingPlan(2, 12, 1.0, [CellEntry(CellRecipe("ring_band", "geometric", provides_contact=True), None)], 1),
    ])
    a = Assembler(plan, geom, CENTER, 0.5, 10.0, composer_for(geom))
    a.pass_one()
    leaf = next(n for n in a.nodes if n.recipe.motif == "leaf" and max(n.paths[0].radials) > 1.03)
    outline, midrib = leaf.paths
    apex = outline.coords[max(range(len(outline.radials)), key=lambda i: outline.radials[i])]
    assert apex in (midrib.coords[0], midrib.coords[-1])
    # Ring-2 ink square to the apex's radius, 2px short of it: the apex crosses it and must be pulled back.
    cx, cy = CENTER
    radius = math.hypot(apex[0] - cx, apex[1] - cy)
    ux, uy = (apex[0] - cx) / radius, (apex[1] - cy) / radius
    foot = (cx + ux * (radius - 2.0), cy + uy * (radius - 2.0))
    add_ink(a, 2, [(foot[0] - uy * 15.0, foot[1] + ux * 15.0), (foot[0] + uy * 15.0, foot[1] - ux * 15.0)])
    a.resolve_overflow(leaf, "outward")
    assert leaf.pull_backs.get("outward")
    outline, midrib = leaf.paths
    apex = outline.coords[max(range(len(outline.radials)), key=lambda i: outline.radials[i])]
    assert apex in (midrib.coords[0], midrib.coords[-1])
    report = TopologyValidator(snap_tolerance=2.5, whisker_tolerance=5.0).analyze([p.coords for p in a.paths])
    assert report.stats["num_dangles"] == 0
