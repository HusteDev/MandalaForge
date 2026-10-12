from collections import Counter
import math
import pytest
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

# Revision 2 petals dip up to half a ring depth (allowance (-0.5, 1.3)), and the manual plan's petal (ring seed 1)
# dips 0.43 of one, through ring 0's band, so it touches the band itself and its stem draws nothing. Ring seed 7
# draws a petal that dips 0.25 of a ring depth, as the revision-1 limit did, leaving a 6.9px gap above the band:
# overflow clear of its neighbour, and a stem to draw across the gap.
PETAL_LIMITS = (-0.5, 1.3)

# These tests exercise reaches across the gap between ring 1's petals and ring 0's band, measured against a band
# whose arcs sit mid-ring. A plain band now fills its ring (arcs at 0.08-0.15 and 0.85-0.92, from user feedback),
# which leaves no gap on this 60px ring for a petal dip to clear, so the module keeps the band geometry the
# scenarios were built on: the same draws, from the ranges a plain band used before.
@pytest.fixture(autouse=True)
def _mid_ring_band(monkeypatch):
    from motifs import geometric
    monkeypatch.setattr(geometric, "BAND_INNER_RANGE", (0.25, 0.45))
    monkeypatch.setattr(geometric, "BAND_OUTER_RANGE", (0.55, 0.75))
    monkeypatch.setattr(geometric, "LENS_SHARE_RANGE", (0.2, 0.4))

def shallow_plan(**kwargs):
    plan = manual_plan(**kwargs)
    plan.rings[1].ring_seed = 7
    return plan

def test_stems_land_on_inner_ring_ink():
    design = assemble(shallow_plan())
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
    design = assemble(shallow_plan())
    reach = design.reaches[0]
    hit = reach.coords[-1]
    assert any(any(math.isclose(x, hit[0], abs_tol=1e-6) and math.isclose(y, hit[1], abs_tol=1e-6)
                   for x, y in p.coords) for p in design.paths if p.role != "reach")

def test_curved_reach_has_interior_points():
    # Every stem is drawn curved (bow, s or wavy): a reach has interior points, and some leave the chord (these
    # stems are 4px long, so their curves are shallow).
    # (The manual plan's petal dips onto the band and draws no stems, so the shallow plan is used.)
    composer = Composer(1, GEOM, ComposerSettings(categories=["botanical", "geometric"]))
    design = Assembler(shallow_plan(), GEOM, CENTER, 0.9, 10.0, composer).assemble()
    assert design.reaches
    assert all(len(r.coords) >= 9 for r in design.reaches)
    assert any(LineString([r.coords[0], r.coords[-1]]).hausdorff_distance(LineString(r.coords)) > 0.1
               for r in design.reaches)

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
    a = placed(shallow_plan())
    petal = next(n for n in a.nodes if n.recipe.motif == "petal")
    before = list(petal.paths[0].coords)
    a.resolve_overflow(petal, "inward")
    assert petal.paths[0].coords == before and petal.context.radial_limits == PETAL_LIMITS

def test_innermost_inward_and_outermost_outward_are_kept():
    a = placed(manual_plan())
    band = next(n for n in a.nodes if n.ring_index == 0)
    petal = next(n for n in a.nodes if n.recipe.motif == "petal")
    a.resolve_overflow(band, "inward")
    a.resolve_overflow(petal, "outward")
    assert band.context.radial_limits == (0.0, 1.0) and petal.context.radial_limits == PETAL_LIMITS

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
    design = assemble(shallow_plan())
    petals = [n for n in design.nodes if n.recipe.motif == "petal"]
    for reach in design.reaches:
        petal = next(n for n in petals if n.cell_index == reach.cell_index)
        assert reach.coords[0] in petal.paths[0].coords

def test_wavy_reach_ends_exactly_on_ink():
    composer = composer_for(GEOM)
    design = Assembler(shallow_plan(), GEOM, CENTER, 0.9, 10.0, composer).assemble()
    assert design.reaches
    for reach in design.reaches:
        others = [p for p in design.paths if p is not reach]
        assert any(reach.coords[0] in p.coords for p in others)
        assert any(reach.coords[-1] in p.coords for p in others)

def test_reach_radials_are_in_its_own_ring():
    design = assemble(shallow_plan())
    assert design.reaches
    for reach in design.reaches:
        for (x, y), radial in zip(reach.coords, reach.radials):
            assert math.isclose(100.0 + 70.0 * radial, math.hypot(x - CENTER[0], y - CENTER[1]), abs_tol=1e-9)

def test_floating_base_cells_lists_unconnected_bases():
    a = placed(shallow_plan())
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

def test_inward_reach_casts_to_the_neighbour_boundary_whatever_its_declared_length():
    # A stem casts exactly to the inward neighbour ring's inner boundary (spec 13.2, fix round): a declared
    # 1px length does not stop it short of ring 0's band.
    a = placed(shallow_plan())
    node, end, point, rotation = a.pending_reaches[0]
    short = ReachEnd(end.point, end.direction, 1.0, end.style)
    reach = a.resolve_reach(node, short, point, rotation)
    assert reach is not None and reach.coords[0] in node.paths[0].coords
    assert any(reach.coords[-1] in p.coords for p in a.paths if p.ring_index == 0)

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
    return node, end, point, rotation

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
    assert petal.paths[0].coords == before and petal.context.radial_limits == PETAL_LIMITS

def test_reach_is_cast_forward_from_its_anchor():
    a = placed(shallow_plan())
    node, short, point, rotation = stem_of_cell_zero(a)
    anchor = lowest_vertex(node.paths[0])
    between = (anchor[0] + point[0]) / 2.0  # ink behind the anchor, between it and the page point
    behind = add_ink(a, 1, [(between, CENTER[1] - 6.0), (between, CENTER[1] + 6.0)])
    reach = a.resolve_reach(node, short, point, rotation)
    assert reach.coords[0] == anchor
    assert len(behind.coords) == 2
    assert any(reach.coords[-1] in p.coords for p in a.paths if p.ring_index == 0)

def test_anchor_already_on_other_ink_is_a_touch_without_a_path():
    a = placed(shallow_plan())
    node, short, point, rotation = stem_of_cell_zero(a)
    anchor = lowest_vertex(node.paths[0])
    through = add_ink(a, 0, [(anchor[0], CENTER[1] - 6.0), (anchor[0], CENTER[1] + 6.0)])
    assert a.resolve_reach(node, short, point, rotation) is None
    assert anchor in through.coords and not any(p.role == "reach" for p in a.paths)

def test_reach_onto_own_ring_ink_is_accepted_with_a_vertex():
    a = placed(shallow_plan())
    node, short, point, rotation = stem_of_cell_zero(a)
    anchor = lowest_vertex(node.paths[0])
    x = anchor[0] - 4.0  # past a pen's width, before ring 0's band
    own_ring = add_ink(a, 1, [(x, CENTER[1] - 6.0), (x, CENTER[1] + 6.0)])
    reach = a.resolve_reach(node, short, point, rotation)
    assert reach.coords[-1] in own_ring.coords
    assert math.isclose(reach.coords[-1][0], x, abs_tol=1e-9)

def test_touch_step_leaves_a_gap_over_the_touch_gap_alone():
    a = placed(shallow_plan())
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
    coords = resolver._curve_clear_of_ink(asm, (0.0, 0.0), (100.0, 0.0), resolver.wavy_coords)
    offsets = [abs(y) for _, y in coords]
    assert len(coords) == 9 and max(offsets) == 0.0
    assert coords[0] == (0.0, 0.0) and coords[-1] == (100.0, 0.0)

def test_wavy_reach_flattens_until_it_keeps_a_pen_width_from_ink():
    # The wave peaks 3px toward ink 5px off its line; it halves until the peak stays 4px clear (0.75px).
    asm = types.SimpleNamespace(index=InkIndex(), min_white_space=10.0)
    asm.index.add(PlacedPath(0, 0, "centre", (0,), "base", [(15.0, 5.0), (85.0, 5.0)], [0.5, 0.5], False, 1.0))
    coords = resolver._curve_clear_of_ink(asm, (0.0, 0.0), (100.0, 0.0), resolver.wavy_coords)
    assert math.isclose(max(abs(y) for _, y in coords), 0.75, abs_tol=1e-9)


def test_final_contact_check_names_a_base_that_floated_after_its_ring_was_resolved():
    a = Assembler(shallow_plan(), GEOM, CENTER, 0.5, 10.0, composer_for(GEOM))
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
    assert resolver._curve_clear_of_ink(asm, (0.0, 0.0), (100.0, 0.0), resolver.wavy_coords, lambda coords: False) is None

def test_touch_within_the_touch_radius_of_a_vertex_reuses_it():
    # A second touch landing 3e-7px from an earlier one used to add a vertex beside it; once both lines
    # held both vertices they overlapped along a sub-micron segment, which the validator reads as a crossing.
    path = PlacedPath(0, 0, "centre", (0,), "base", [(0.0, 0.0), (10.0, 0.0), (20.0, 0.0)], [0.5, 0.5, 0.5], False, 1.0)
    assert resolver.insert_vertex(path, (10.0 + 3e-7, 0.0)) == (10.0, 0.0)
    assert len(path.coords) == 3

def test_final_touch_pass_snaps_a_tip_within_clearance_that_was_never_pulled_back():
    a = placed(shallow_plan())
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

def test_clearance_is_waived_around_a_vertex_the_run_shares_with_other_ink():
    # A reach landing on an overflow run is a touch: the run may come within a pen's width of it inside
    # the touch disc around the landing, as it may around its own extreme vertex; elsewhere it may not.
    asm = types.SimpleNamespace(index=InkIndex(), center=(0.0, 0.0), min_white_space=10.0)
    run = PlacedPath(0, 0, "centre", (0,), "base", [(0.0, 100.0), (20.0, 100.0), (40.0, 100.0)], [1.2] * 3, False, 1.0)
    landing = PlacedPath(1, 0, "centre", (0,), "reach", [(0.0, 120.0), (0.0, 100.0)], [0.2, 0.0], False, 1.0)
    for path in (run, landing):
        asm.index.add(path)
    assert not resolver._too_close(asm, [run], 1, "outward")
    # The same landing ignored as stale (the run replaces the ink it was drawn on) is crowding again.
    assert resolver._too_close(asm, [run], 1, "outward", {id(landing)})
    beside = PlacedPath(1, 1, "centre", (0,), "base", [(20.0, 103.0), (20.0, 120.0)], [0.0, 0.2], False, 1.0)
    asm.index.add(beside)
    assert resolver._too_close(asm, [run], 1, "outward")

def test_grazing_reach_runs_along_its_ray_then_bends_onto_the_ink():
    plan = shallow_plan()
    # Ring seed 10 draws ring 0's band with its outer arc 7.3px below the stem's anchor, so the stroke beside
    # the ray (3.9px on) is the first ink the reach comes near.
    plan.rings[0].ring_seed = 10
    a = placed(plan)
    node, short, point, rotation = stem_of_cell_zero(a)
    # The run along the ray is the straight reach's; a curved stem bends off the ray from its start.
    short = ReachEnd(short.point, short.direction, short.max_length_px, "straight")
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
    a = placed(shallow_plan())
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
        # The midrib is the veins embellishment; the leaf's apex is at radial 1.18.
        RingPlan(1, 12, 1.0, [CellEntry(CellRecipe("leaf", "botanical", embellishments=["veins"]), None)], 11),
        RingPlan(2, 12, 1.0, [CellEntry(CellRecipe("ring_band", "geometric", provides_contact=True), None)], 1),
    ])
    a = Assembler(plan, geom, CENTER, 0.5, 10.0, composer_for(geom))
    a.pass_one()
    leaf = next(n for n in a.nodes if n.recipe.motif == "leaf" and max(n.paths[0].radials) > 1.03)
    outline, midrib = leaf.paths[:2]
    apex = outline.coords[max(range(len(outline.radials)), key=lambda i: outline.radials[i])]
    assert apex in (midrib.coords[0], midrib.coords[-1])
    # Ring-2 ink square to the apex's radius, 2px short of it: the apex crosses it and must be pulled back.
    cx, cy = CENTER
    radius = math.hypot(apex[0] - cx, apex[1] - cy)
    ux, uy = (apex[0] - cx) / radius, (apex[1] - cy) / radius
    foot = (cx + ux * (radius - 2.0), cy + uy * (radius - 2.0))
    stroke = add_ink(a, 2, [(foot[0] - uy * 15.0, foot[1] + ux * 15.0), (foot[0] + uy * 15.0, foot[1] - ux * 15.0)])
    a.resolve_overflow(leaf, "outward")
    assert leaf.pull_backs.get("outward")
    outline, midrib = leaf.paths[:2]
    apex = outline.coords[max(range(len(outline.radials)), key=lambda i: outline.radials[i])]
    assert apex in (midrib.coords[0], midrib.coords[-1])
    # The pulled-back revision-2 leaf (apex drawn at 1.18) no longer meets the hand-placed stroke, whose own two
    # ends now dangle; nothing else may, the midrib's ends least of all.
    report = TopologyValidator(snap_tolerance=2.5, whisker_tolerance=5.0).analyze([p.coords for p in a.paths])
    loose = [point for point in report.unconnected_shapes
             if min(point.distance(Point(end)) for end in (stroke.coords[0], stroke.coords[-1])) > 0.1]
    assert loose == []


# ----- revision 2: side-touch wiring, once-per-wedge attachments, symmetry groups -----

import assembler as assembler_module


def symmetric_plan(symmetry=4):
    plan = shallow_plan()
    plan.base_symmetry = symmetry
    return plan


def test_only_side_ring_bases_get_the_side_touch_radial(monkeypatch):
    plan = manual_plan()
    plan.rings[1].contact_mode, plan.rings[1].side_touch_radial = "side", 0.42
    seen = []
    entry = assembler_module._registry_entry

    def recording(recipe):
        found = dict(entry(recipe))
        generator = found["generator"]
        found["generator"] = lambda context: seen.append((recipe.motif, context.side_touch_radial)) or generator(context)
        return found

    monkeypatch.setattr(assembler_module, "_registry_entry", recording)
    a = placed(plan)
    for node in a.nodes:
        expected = 0.42 if node.ring_index == 1 and node.parent is None else None
        assert node.context.side_touch_radial == expected
    # The petal base gets it; its diamond slot child and its stem attachment never do; ring 0 is not in side mode.
    assert {value for motif, value in seen if motif == "petal"} == {0.42}
    assert {value for motif, value in seen if motif != "petal"} == {None}


@pytest.mark.parametrize("symmetry, cells", [(4, [0, 3, 6, 9]), (2, [0, 3, 6, 9]), (1, [0, 4, 8])])
def test_once_per_wedge_attachment_is_spread_to_at_least_three_cells_per_ring(symmetry, cells):
    # One per wedge of 360 / B degrees, but never fewer than three evenly spaced per ring: B = 2 draws two per
    # wedge (so both members of a group carry it) and B = 1 three in the ring.
    plan = symmetric_plan(symmetry)
    plan.rings[1].sequence[0].centre.attachments[0].once_per_wedge = True
    a = placed(plan)
    assert sorted(node.cell_index for node, *_ in a.pending_reaches) == cells


def test_symmetry_groups_relate_cells_by_the_base_rotation():
    a = placed(symmetric_plan(4))
    groups = a.symmetry_groups(1)
    bases = [[n.cell_index for n in g] for g in groups if g[0].parent is None]
    assert bases == [[0, 3, 6, 9], [1, 4, 7, 10], [2, 5, 8, 11]]
    assert all(len(g) == 4 and len({(n.position, n.node_path) for n in g}) == 1 for g in groups)
    assert [[n.cell_index for n in g] for g in a.symmetry_groups(0)] == [[0, 2, 4, 6], [1, 3, 5, 7]]
    # Without a usable base symmetry every node is its own group.
    assert all(len(g) == 1 for g in placed(manual_plan()).symmetry_groups(1))


def rotated(coords, degrees, center=CENTER):
    t = math.radians(degrees)
    c, s = math.cos(t), math.sin(t)
    return [(center[0] + (x - center[0]) * c - (y - center[1]) * s,
             center[1] + (x - center[0]) * s + (y - center[1]) * c) for x, y in coords]


def assert_symmetric(paths, degrees, center=CENTER):
    """
    The paths rotated by `degrees` about the centre are the same multiset of paths, each compared as its sorted
    coordinates rounded to 6 decimals; a key that misses only because a coordinate sits within float noise of a
    rounding boundary is paired with a distinct leftover path within 2e-6 (one rounding step).
    """
    def key(coords):
        return tuple(sorted((round(x, 6), round(y, 6)) for x, y in coords))

    mine = Counter(key(p.coords) for p in paths)
    turned = {}
    for p in paths:
        turned.setdefault(key(rotated(p.coords, degrees, center)), []).append(p)
    missing = Counter({k: len(v) for k, v in turned.items()}) - mine
    spare = list((mine - Counter({k: len(v) for k, v in turned.items()})).elements())
    for k in missing.elements():
        match = next((s for s in spare if len(s) == len(k)
                      and all(abs(a[0] - b[0]) <= 2e-6 and abs(a[1] - b[1]) <= 2e-6 for a, b in zip(k, s))), None)
        p = turned[k][0]
        assert match is not None, (p.ring_index, p.cell_index, p.role)
        spare.remove(match)


def test_manual_plan_with_base_symmetry_resolves_symmetrically():
    design = assemble(symmetric_plan(4))
    assert design.reaches
    assert_symmetric(design.paths, 90.0)
    assert validate(design).is_valid


def test_pull_backs_are_judged_on_representatives_and_mirrored_to_their_groups():
    # On DEEP every petal dips through ring 0's band and is pulled back. Only the first wedge's petals are
    # resolved (one counter per group); the other wedges get turned copies of their ink, radials included.
    plan = manual_plan()
    plan.base_symmetry = 4
    a = Assembler(plan, DEEP, CENTER, 0.5, 10.0, composer_for(DEEP))
    design = a.assemble()
    petals = {n.cell_index: n for n in a.nodes if n.recipe.motif == "petal"}
    assert [c for c, n in sorted(petals.items()) if n.pull_backs] == [0, 1, 2]
    for cell, petal in petals.items():
        rep = petals[cell % 3]
        expected = rotated(rep.paths[0].coords, 90.0 * (cell // 3))
        assert all(math.isclose(x0, x1, abs_tol=1e-9) and math.isclose(y0, y1, abs_tol=1e-9)
                   for (x0, y0), (x1, y1) in zip(petal.paths[0].coords, expected))
        assert petal.paths[0].radials == rep.paths[0].radials
    assert_symmetric(design.paths, 90.0)
    assert validate(design).is_valid


def test_mirrored_touches_share_their_vertices_exactly():
    # A turned copy differs from ink traced in its own cell by float noise; the validator only reads a touch
    # where the shared vertex is the same point in both lines, so every mirrored end is snapped onto it.
    design = assemble(symmetric_plan(4))
    others = [p for p in design.paths if p.role != "reach"]
    for reach in design.reaches:
        assert any(reach.coords[0] in p.coords for p in others) and any(reach.coords[-1] in p.coords for p in others)
    assert validate(design).stats["num_dangles"] == 0


def _base_at_the_boundary(a):
    """The cell-0 petal redrawn with no inward overflow: its base vertex sits on ring 1's inner boundary, home ink."""
    petal = next(n for n in a.nodes if n.recipe.motif == "petal" and n.cell_index == 0)
    a.commit(a.regenerate(petal, (0.0, 1.3)))
    base = lowest_vertex(petal.paths[0])
    assert min(petal.paths[0].radials) == 0.0 and not resolver._overflows(petal, "inward")
    return petal, base


def test_final_touch_snaps_a_tip_on_the_boundary_that_does_not_overflow():
    # Spec 13.3: tips sit on the ring boundary and meet the next ring's ink there. A base at radial 0 (no
    # overflow) within the touch gap of ring-0 ink is moved onto it with a shared vertex.
    a = placed(shallow_plan())
    petal, base = _base_at_the_boundary(a)
    cx, cy = CENTER
    radius = math.hypot(base[0] - cx, base[1] - cy)
    ux, uy = (base[0] - cx) / radius, (base[1] - cy) / radius
    foot = (cx + ux * (radius - 3.0), cy + uy * (radius - 3.0))
    ink = add_ink(a, 0, [(foot[0] - uy * 2.0, foot[1] + ux * 2.0), (foot[0] + uy * 2.0, foot[1] - ux * 2.0)])
    resolver.final_touches(a)
    tip = lowest_vertex(petal.paths[0])
    assert tip in ink.coords and math.isclose(math.hypot(tip[0] - foot[0], tip[1] - foot[1]), 0.0, abs_tol=1e-6)


def test_home_ink_near_neighbour_ink_is_not_a_conflict():
    # Clearance is about overflow: home ink running within a pen's width of the next ring's ink, with no touch
    # to resolve it, is accepted; overflow doing the same is not.
    a = placed(shallow_plan())
    petal, base = _base_at_the_boundary(a)
    cx, cy = CENTER
    radius = math.hypot(base[0] - cx, base[1] - cy)
    ux, uy = (base[0] - cx) / radius, (base[1] - cy) / radius
    # Ring-0 ink 2px inside the boundary, square to the base's radius and beside it for 12px each way.
    foot = (cx + ux * (radius - 2.0), cy + uy * (radius - 2.0))
    add_ink(a, 0, [(foot[0] - uy * 12.0, foot[1] + ux * 12.0), (foot[0] + uy * 12.0, foot[1] - ux * 12.0)])
    assert not resolver._too_close(a, petal.paths, 0, "inward")
    assert not resolver._conflicts(a, petal.paths, 0, "inward")
    assert not resolver._rings_conflict(a, petal.paths + [p for p in a.paths if p.ring_index == 0], 1, 0)
    # Ink as near an overflow run (a neighbouring petal's flank below the boundary, outside its tip's disc) crowds it.
    flank = next(n for n in a.nodes if n.recipe.motif == "petal" and n.cell_index == 1).paths[0]
    tip = lowest_vertex(flank)
    i = next(i for i in range(1, len(flank.coords) - 1) if flank.radials[i] < 0.0
             and math.dist(flank.coords[i], tip) > resolver.touch_disc_px(a) + 2.0)
    (x0, y0), (x, y), (x1, y1) = flank.coords[i - 1:i + 2]
    tx, ty = (x1 - x0) / math.dist((x0, y0), (x1, y1)), (y1 - y0) / math.dist((x0, y0), (x1, y1))
    nx, ny = -ty, tx
    middle = LineString(flank.coords).centroid
    if (x + nx - middle.x) ** 2 + (y + ny - middle.y) ** 2 < (x - middle.x) ** 2 + (y - middle.y) ** 2:
        nx, ny = -nx, -ny  # point away from the petal
    near = (x + 2.0 * nx, y + 2.0 * ny)
    add_ink(a, 0, [(near[0] - tx, near[1] - ty), (near[0] + tx, near[1] + ty)])
    assert resolver._too_close(a, [flank], 0, "inward")


def test_stem_casts_no_further_than_the_inward_neighbours_inner_boundary():
    # Spec 13.2: a stem stays in the neighbour ring and never recasts. With ring 0's band gone from its path,
    # ink inside ring 0's inner boundary (r < 40) is past the boundary, however long the stem's declared
    # length: the stem misses.
    a = placed(shallow_plan())
    node, end, point, rotation = stem_of_cell_zero(a)
    end = ReachEnd(end.point, end.direction, 1000.0, end.style)
    for band in [p for p in a.paths if p.ring_index == 0]:
        a.paths.remove(band)
        a.index.remove(band)
    beyond = add_ink(a, 0, [(CENTER[0] + 30.0, CENTER[1] - 6.0), (CENTER[0] + 30.0, CENTER[1] + 6.0)])
    assert a.resolve_reach(node, end, point, rotation) is None
    assert len(beyond.coords) == 2 and not any(p.role == "reach" for p in a.paths)
    # Ink just inside the boundary is still within reach.
    within = add_ink(a, 0, [(CENTER[0] + 44.0, CENTER[1] - 6.0), (CENTER[0] + 44.0, CENTER[1] + 6.0)])
    reach = a.resolve_reach(node, end, point, rotation)
    assert reach is not None and reach.coords[-1] in within.coords


def test_replaced_cells_give_the_neighbours_facing_sides_a_fresh_pull_back_budget(monkeypatch):
    # The neighbours' facing sides were pulled back against ink a contact round replaces; without a fresh
    # budget they could not answer the new ink (a (24, 24, 24) slot fixture raised "still crosses").
    a = Assembler(shallow_plan(), GEOM, CENTER, 0.5, 10.0, composer_for(GEOM))
    a.pass_one()
    resolver._resolve_ring(a, a.plan.rings[0])
    for band in (n for n in a.nodes if n.ring_index == 0):
        band.pull_backs["outward"] = resolver.MAX_PULL_BACKS
    calls = []
    real = resolver.floating_base_cells

    def floating_once(asm, ring_index=None):
        calls.append(ring_index)
        return [(1, 0, "centre")] if len(calls) == 1 else real(asm, ring_index)

    monkeypatch.setattr(resolver, "floating_base_cells", floating_once)
    resolver._resolve_ring(a, a.plan.rings[1])
    assert all(n.pull_backs["outward"] == 0 for n in a.nodes if n.ring_index == 0)


def test_pass_one_cells_share_their_side_vertices_exactly():
    # Seven cells are traced with an inexact 360 / 7 rotation, so neighbouring bands met at side vertices 4e-14
    # apart; a third line touching one of them then overlapped the other along a sub-micron segment, which the
    # validator reads as an overflow crossing (seed 8, ring_divisions (7, 12)). Placed ink is snapped exactly.
    a = placed(manual_plan(divs=(7, 12)))
    vertices = [(point, id(path)) for path in a.paths for point in path.coords]
    for k, (point, owner) in enumerate(vertices):
        for other, other_owner in vertices[k + 1:]:
            if other_owner != owner and point != other:
                assert math.dist(point, other) > resolver.SAME_VERTEX_PX


def test_floating_groups_are_replaced_once_per_sequence_entry(monkeypatch):
    # In a symmetric ring the bases float in whole groups; the fallback runs per group, and groups sharing a
    # sequence entry share one call, since a second would advance that entry's chain again.
    plan = symmetric_plan(4)
    plan.rings[1].contact_mode = "side"
    plan.rings[1].sequence[0] = CellEntry(CellRecipe("ring_band", "geometric"), None)
    composer = composer_for(GEOM)
    calls = []
    real = composer.replace_node
    monkeypatch.setattr(composer, "replace_node", lambda *args: calls.append(args[1:3]) or real(*args))
    design = Assembler(plan, GEOM, CENTER, 0.5, 10.0, composer).assemble()
    assert calls and len(calls) == len(set(calls))
    assert_symmetric(design.paths, 90.0)
    assert validate(design).stats["num_floating_base"] == 0


def test_a_pull_back_never_hands_its_crossing_to_the_neighbour(monkeypatch):
    # A crossing is blamed on a side within half a pixel of its boundary, so the two sides' margins overlap. A
    # pull-back that only cleared its own blame moved the crossing just past the edge of its margin, into the
    # neighbour's; the neighbour's pull-back moved it back one step lower, and both ran out of pull-backs still
    # crossing (ring 2's petal bases dipping onto ring 1's tips, (24, 24, 24) with a 25px touch disc). A pulled-back
    # side now crosses the neighbour ring nowhere, or has no overflow left on that side.
    import io
    from contextlib import redirect_stdout
    from coloring_generator import DesignGenerator
    real = resolver._pull_back
    pulled = []

    def checked(asm, node, side):
        if not real(asm, node, side):
            return False
        neighbour = resolver._neighbour(asm, node.ring_index, side)
        bound = 0 if side == "inward" else 1
        at_bound = node.context.radial_limits[bound] == float(bound)
        crosses = resolver._ink_crosses(asm, resolver._subtree_paths(asm, node), neighbour)
        assert at_bound or not crosses, (node.ring_index, node.cell_index, side, node.context.radial_limits)
        pulled.append(node)
        return True

    monkeypatch.setattr(resolver, "_pull_back", checked)
    with redirect_stdout(io.StringIO()):
        g = DesignGenerator(seed=20260821, num_rings=3, num_divisions=24, complexity=0.5, min_pattern_size=25,
                            categories=["botanical"], ring_divisions=[24, 24, 24],
                            force_motif={"name": "petal", "position": "divider", "role": "base"})
        g.generate()
    assert pulled
    assert g.last_validation_result.is_valid


# ----- curved stems (bow and s) -----

from resolver import bow_coords, s_coords

@pytest.mark.parametrize("shape", [bow_coords, s_coords])
def test_curve_ends_are_exact_and_amplitude_capped(shape):
    start, end = (0.0, 0.0), (0.0, 100.0)
    coords = shape(start, end)
    assert coords[0] == start and coords[-1] == end
    assert max(abs(x) for x, _ in coords) == pytest.approx(min(8.0, 0.12 * 100.0), abs=0.2)

def test_bow_bows_to_the_same_side_under_rotation():
    # The bow sits to the left of start-to-end, whichever way the reach points.
    for start, end in [((0.0, 0.0), (100.0, 0.0)), ((0.0, 0.0), (0.0, 100.0)), ((5.0, 5.0), (-60.0, -40.0))]:
        dx, dy = end[0] - start[0], end[1] - start[1]
        sides = [dx * (y - start[1]) - dy * (x - start[0]) for x, y in bow_coords(start, end)[1:-1]]
        assert all(side > 0.0 for side in sides)

def test_reach_shapes_name_every_curved_style():
    assert resolver.REACH_SHAPES == {"wavy": resolver.wavy_coords, "bow": bow_coords, "s": s_coords}

@pytest.mark.parametrize("shape", ["bow", "s"])
def test_curved_reach_falls_down_the_ladder_to_straight_when_it_would_come_too_close_to_ink(shape):
    # Ink 2px off the line is within a pen's width of every curve on the ladder: the reach goes straight.
    asm = types.SimpleNamespace(index=InkIndex(), min_white_space=10.0)
    asm.index.add(PlacedPath(0, 0, "centre", (0,), "base", [(10.0, 2.0), (90.0, 2.0)], [0.5, 0.5], False, 1.0))
    asm.index.add(PlacedPath(0, 0, "centre", (0,), "base", [(10.0, -2.0), (90.0, -2.0)], [0.5, 0.5], False, 1.0))
    coords = resolver._curve_clear_of_ink(asm, (0.0, 0.0), (100.0, 0.0), resolver.REACH_SHAPES[shape])
    assert coords[0] == (0.0, 0.0) and coords[-1] == (100.0, 0.0)
    assert max(abs(y) for _, y in coords) == 0.0

def test_curved_reach_flattens_one_rung_at_a_time():
    # The bow peaks 8px; ink 9px off its line keeps it from 1.0 and 0.5 (5px clear) is the first rung to fit.
    asm = types.SimpleNamespace(index=InkIndex(), min_white_space=10.0)
    asm.index.add(PlacedPath(0, 0, "centre", (0,), "base", [(30.0, 9.0), (70.0, 9.0)], [0.5, 0.5], False, 1.0))
    asm.index.add(PlacedPath(0, 0, "centre", (0,), "base", [(30.0, -9.0), (70.0, -9.0)], [0.5, 0.5], False, 1.0))
    coords = resolver._curve_clear_of_ink(asm, (0.0, 0.0), (100.0, 0.0), bow_coords)
    assert math.isclose(max(abs(y) for _, y in coords), 4.0, abs_tol=1e-9)


# ----- reaches from or onto a junction: ink shared by other paths -----

def _junction_asm():
    # A band's lens tip on its inner arc at (0, 0): the stem starts on a vertex both paths hold. Its end at
    # (0, 100) lies on a target line and on the end of a midrib that meets the target there.
    asm = types.SimpleNamespace(index=InkIndex(), min_white_space=10.0)
    arc = PlacedPath(0, 0, "centre", (0,), "base", [(-50.0, 0.0), (0.0, 0.0), (50.0, 0.0)], [0.5] * 3, False, 1.0)
    lens = PlacedPath(0, 0, "centre", (0,), "base", [(0.0, 0.0), (6.0, -20.0), (0.0, -40.0), (-6.0, -20.0), (0.0, 0.0)],
                      [0.5] * 5, True, 1.0)
    target = PlacedPath(0, 1, "centre", (0,), "base", [(-50.0, 100.0), (0.0, 100.0), (50.0, 100.0)], [0.5] * 3, False, 1.0)
    midrib = PlacedPath(0, 1, "centre", (1,), "base", [(0.0, 100.0), (0.0, 140.0)], [0.5] * 2, False, 1.0)
    for path in (arc, lens, target, midrib):
        asm.index.add(path)
    return asm, lens, target

@pytest.mark.parametrize("shape", ["bow", "s"])
def test_curved_reach_from_a_junction_keeps_its_curve(shape):
    # Every path meeting the reach's start or end point may come closer within the touch disc there, not only
    # the anchor and target: the arc through the lens tip and the midrib ending on the target used to sit at
    # distance 0 from every curve, so each stem from a band's lens fell back to straight.
    asm, lens, target = _junction_asm()
    coords = resolver._curve_clear_of_ink(asm, (0.0, 0.0), (0.0, 100.0), resolver.REACH_SHAPES[shape],
                                          end_paths=[(lens, (0.0, 0.0)), (target, (0.0, 100.0))])
    assert coords[0] == (0.0, 0.0) and coords[-1] == (0.0, 100.0)
    assert max(abs(x) for x, _ in coords) == pytest.approx(8.0, abs=0.2)

@pytest.mark.parametrize("shape", ["bow", "s"])
def test_junction_path_is_exempt_only_near_the_junction(shape):
    # A path through the start that then runs 3px beside the reach, well past the touch disc, is within a pen's
    # width of every curve there: the reach still falls back to straight.
    asm, lens, target = _junction_asm()
    asm.index.add(PlacedPath(0, 0, "centre", (2,), "base", [(0.0, 0.0), (-3.0, 20.0), (-3.0, 80.0)], [0.5] * 3,
                             False, 1.0))
    coords = resolver._curve_clear_of_ink(asm, (0.0, 0.0), (0.0, 100.0), resolver.REACH_SHAPES[shape],
                                          end_paths=[(lens, (0.0, 0.0)), (target, (0.0, 100.0))])
    assert max(abs(x) for x, _ in coords) == 0.0


def test_pull_back_search_treats_a_layered_probe_failure_as_crossing(monkeypatch):
    # A probe on a layered composite can raise LayeredRingFailed (an AssemblyError); during the bisection that is
    # a shape that crosses, not a failure of the design. Only the final regenerate-and-commit may raise it.
    a = placed(manual_plan(), DEEP)
    petal = next(n for n in a.nodes if n.recipe.motif == "petal")
    real = a.regenerate
    calls = []

    def flaky(node, limits):
        calls.append(limits)
        if len(calls) <= 2:
            raise assembler_module.LayeredRingFailed(node.ring_index, "probe")
        return real(node, limits)

    monkeypatch.setattr(a, "regenerate", flaky)
    a.resolve_overflow(petal, "inward")
    assert len(calls) > 3                       # the search went on past the failed probes
    assert petal.pull_backs.get("inward") == 1
