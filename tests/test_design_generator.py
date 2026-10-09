import re
from coloring_generator import DesignGenerator

def gen(**over):
    return DesignGenerator(**{"seed": 42, "num_rings": 4, "ring_divisions": [8, 8, 8, 12],
                              "categories": ["botanical", "geometric"], **over})

def test_sketch_fixture_generates_and_validates():
    g = gen(); svg = g.generate()
    assert g.last_validation_result.is_valid, g.last_validation_result.issues[:5]
    assert "<use" not in svg and "<defs" not in svg
    assert len(re.findall(r'<g id="ring-\d+"', svg)) == 4

def test_svg_is_deterministic():
    assert gen().generate() == gen().generate()

def test_narrowest_cells_still_generate():
    g = DesignGenerator(seed=7, num_rings=7, num_divisions=24, complexity=0.9, categories=["botanical"])
    g.generate()
    assert g.last_validation_result.is_valid

def test_max_min_pattern_size_drops_nesting_silently():
    g = gen(min_pattern_size=50, complexity=1.0); g.generate()
    assert all(node.recipe.slot_child is None or node.recipe.slot_child.dropped
               for node in g.assembled.nodes if len(node.node_path) == 1)
    assert g.last_validation_result.is_valid

def test_regenerate_ring_changes_neighbour_reaches_not_plan():
    g = gen(seed=1); g.generate()
    before_plan = g.plan.rings[3]
    before_reaches = [r.coords for r in g.assembled.reaches if r.ring_index == 3]
    frag = g.generate_ring_fragment(2, 999)
    assert g.plan.rings[3] == before_plan
    assert [r.coords for r in g.assembled.reaches if r.ring_index == 3] != before_reaches
    assert frag["ring_seeds"] == {2: 999}
    assert "<svg" in frag["svg"] and '<g id="ring-0"' in frag["svg"]

def test_validation_summary_shape():
    g = gen(); g.generate()
    assert set(g.validation_summary()) == {"is_valid", "issue_count", "tiny_region_count", "dangling_end_count",
                                           "floating_base_count", "overflow_crossing_count", "issues"}


def test_innermost_ring_stays_inside_its_inner_boundary():
    # Ring 0 has no inward neighbour; its divider scallops used to dip toward the centre, where
    # neighbouring cells narrow, and bound faces between them too thin for a pen.
    g = DesignGenerator(seed=2, num_rings=4, num_divisions=12, complexity=0.5, min_pattern_size=10,
                        categories=["botanical", "geometric"])
    g.generate()
    report = g.last_validation_result
    assert report.is_valid, report.issues[:5]
    assert not [region for region in report.regions if region.is_uncolorable]
    assert all(min(path.radials) >= -1e-9 for path in g.assembled.paths if path.ring_index == 0)


def test_final_touch_never_leaves_a_ring_crowding_its_neighbours_overflow():
    # With varied divisions, ring-1 petal tips were touched onto ring-2 scallops in the final touch pass;
    # each touch kept ring 1's outward side clear, but the moved tip crowded ring 2's inward overflow,
    # and the final check raised "ring 2 still crosses or crowds ring 1".
    g = DesignGenerator(seed=777, num_rings=4, num_divisions=12, complexity=0.15, min_pattern_size=10,
                        categories=["botanical"], vary_divisions=True)
    g.generate()
    assert g.last_validation_result.is_valid, g.last_validation_result.issues[:5]


def test_clearance_exempts_every_vertex_a_run_shares_with_other_ink():
    # With varied divisions, a ring-3 stem grazed a ring-2 petal's outward overflow and bent onto the petal
    # just inside the boundary, 3.6px from the run's end and 14px from its extreme vertex: a deliberate
    # touch, which the clearance rule read as crowding, so the final check raised.
    g = DesignGenerator(seed=1, num_rings=4, num_divisions=12, complexity=0.5, min_pattern_size=10,
                        categories=["botanical", "geometric"], vary_divisions=True)
    g.generate()
    report = g.last_validation_result
    assert report.is_valid, report.issues[:5]
    assert not [region for region in report.regions if region.is_uncolorable]


# ----- revision 2: symmetry groups and bounded stems -----

import math

import pytest

from resolver import TOUCH_GAP_PX
from tests.test_assembler_pass_two import assert_symmetric

REVIEW_SEEDS = (42, 777, 12345, 254302, 955789, 984322)


def test_twelve_fold_design_is_exactly_twelve_fold_symmetric():
    g = DesignGenerator(seed=42, num_rings=4, num_divisions=12, complexity=0.5, categories=["botanical", "geometric"])
    g.generate()
    assert g.plan.base_symmetry == 12 and [r.divisions for r in g.plan.rings] == [12, 12, 12, 12]
    assert_symmetric(g.assembled.paths, 30.0, g.center)
    assert g.last_validation_result.is_valid


def test_sketch_fixture_is_four_fold_symmetric():
    g = gen()
    g.generate()
    assert g.plan.base_symmetry == 4
    assert_symmetric(g.assembled.paths, 90.0, g.center)


@pytest.mark.parametrize("vary", [False, True])
def test_stems_end_in_their_inward_neighbour_ring_or_their_own(vary):
    for seed in (3, 11, 42):
        g = DesignGenerator(seed=seed, num_rings=4, num_divisions=12, complexity=0.9,
                            categories=["botanical", "geometric"], vary_divisions=vary)
        g.generate()
        radius = lambda point: math.hypot(point[0] - g.center[0], point[1] - g.center[1])
        stems = [reach for reach in g.assembled.reaches
                 if reach.ring_index > 0 and radius(reach.coords[-1]) < radius(reach.coords[0])]
        assert stems
        for reach in stems:
            floor = g.rings[reach.ring_index - 1]["inner_radius"]
            # A landing may bend onto ink up to the touch gap beside its ray.
            assert radius(reach.coords[-1]) >= floor - TOUCH_GAP_PX - 1e-6


@pytest.mark.parametrize("vary", [False, True])
@pytest.mark.parametrize("seed", REVIEW_SEEDS)
def test_review_seeds_generate_and_validate(seed, vary):
    g = DesignGenerator(seed=seed, num_rings=4, num_divisions=12, complexity=0.5,
                        categories=["botanical", "geometric"], vary_divisions=vary)
    g.generate()
    assert g.last_validation_result.is_valid, g.last_validation_result.issues[:5]


def test_seed_15_assembles_with_stems_cast_to_the_neighbour_boundary():
    # Ring 0 is 83px deep with its band mid-ring; ring 1's floating cells got a stem whose declared 46px fell
    # about 2px short of the band, so every contact round failed until stems cast to the neighbour boundary.
    g = DesignGenerator(seed=15, num_rings=4, num_divisions=12, complexity=0.5,
                        categories=["botanical", "geometric"], vary_divisions=False)
    g.generate()
    assert g.last_validation_result.is_valid, g.last_validation_result.issues[:5]


def test_touch_restored_onto_a_vertex_within_float_noise_is_exact():
    # Seed 1 (vary on, c0.9): a ring-2 petal base touched a ring-1 leaf apex on the boundary; the leaf was then
    # redrawn and its own apex, 5e-14 away, took the restored touch, so the petal's float-noise overflow run
    # overlapped the leaf and the validator read a crossing.
    g = DesignGenerator(seed=1, num_rings=4, num_divisions=12, complexity=0.9,
                        categories=["botanical", "geometric"], vary_divisions=True)
    g.generate()
    assert g.last_validation_result.is_valid, g.last_validation_result.issues[:5]


@pytest.mark.parametrize("seed", [95, 116])
def test_members_float_noise_does_not_fail_the_final_check(seed):
    # A member's boundary-exact tip read as a -5.7e-14 overflow run that its representative's did not, and the
    # final check, judging every member, raised "still crosses or crowds" (fix round 2).
    g = DesignGenerator(seed=seed, num_rings=4, num_divisions=12, complexity=0.7,
                        categories=["botanical", "geometric"], vary_divisions=True)
    g.generate()
    assert g.last_validation_result.is_valid, g.last_validation_result.issues[:5]


def test_guarded_tips_are_touched_from_the_other_side():
    # Seed 3 pulls a ring-2 leaf back outward and a ring-3 leaf back inward, so their tips meet at the shared
    # boundary. Both apexes are shared with their midribs and neither can move onto the other, so the ring-3
    # outline must come to the ring-2 apex.
    g = DesignGenerator(seed=3, num_rings=4, num_divisions=12, complexity=0.7,
                        categories=["botanical", "geometric"], vary_divisions=True)
    g.generate()
    assert g.last_validation_result.is_valid, g.last_validation_result.issues[:5]
    nodes = g.assembled.nodes
    leaves = [n for n in nodes if n.recipe.motif == "leaf" and n.parent is None]
    assert any(n.pull_backs.get("outward") for n in leaves if n.ring_index == 2)
    assert any(n.pull_backs.get("inward") for n in leaves if n.ring_index == 3)
    outer = [n.paths[0] for n in nodes if n.ring_index == 3 and n.recipe.motif == "leaf" and n.parent is None]
    inner = [n.paths[0] for n in nodes if n.ring_index == 2 and n.recipe.motif == "leaf" and n.parent is None]
    assert inner and outer
    for outline in inner:
        apex = outline.coords[max(range(len(outline.radials)), key=lambda i: outline.radials[i])]
        assert any(apex in other.coords for other in outer)


def _once_per_wedge_stems(g):
    """{ring index: sorted cells of drawn reaches} for every ring whose plan carries a once-per-wedge stem."""
    rings = [ring.ring_index for ring in g.plan.rings
             if any(a.once_per_wedge for e in ring.sequence for n in (e.centre, e.divider) if n for a in n.attachments)]
    return {r: sorted(p.cell_index for p in g.assembled.reaches if p.ring_index == r) for r in rings}


def test_base_symmetry_one_still_gets_three_inward_contacts_per_ring():
    # With ring_divisions (7, 12) the base symmetry is 1, so "once per wedge" meant one stem for the whole ring and
    # the band between rings could be one face running round the centre. Ring 2's stem sits on the first of its
    # three sequence entries, so the contacts are spaced among the four cells holding it.
    g = DesignGenerator(seed=20260821, ring_divisions=[7, 12], complexity=0.5, min_pattern_size=10,
                        categories=["botanical", "geometric"])
    g.generate()
    report = g.last_validation_result
    assert g.plan.base_symmetry == 1
    assert report.is_valid and report.stats["num_encircling_regions"] == 0, report.issues[:5]
    stems = _once_per_wedge_stems(g)
    assert stems and all(len(cells) >= 3 for cells in stems.values())
    assert stems[2] == [0, 3, 6, 9]


def test_neighbouring_cells_of_an_inexact_rotation_share_side_vertices_exactly():
    # Seed 8 with (7, 12): ring-0 bands of cells 2 and 3 met 4e-14 apart; a ring-1 petal restored onto one of the
    # two overlapped the other's edge along a sub-micron segment, "Overflow crosses ring 0".
    g = DesignGenerator(seed=8, ring_divisions=[7, 12], complexity=0.5, min_pattern_size=10,
                        categories=["botanical", "geometric"])
    g.generate()
    assert g.last_validation_result.is_valid, g.last_validation_result.issues[:5]


@pytest.mark.parametrize("seed", [9, 69])
def test_validator_measures_a_face_polygonize_returns_invalid(seed):
    # Snap-rounded linework polygonized into a self-intersecting face and the face measurement raised a GEOS
    # "side location conflict"; the validator now repairs such a face before measuring it.
    g = DesignGenerator(seed=seed, ring_divisions=[7, 12], complexity=0.5, min_pattern_size=10,
                        categories=["botanical", "geometric"])
    g.generate()
    assert g.last_validation_result.is_valid, g.last_validation_result.issues[:5]


def test_base_symmetry_four_keeps_one_inward_contact_per_wedge():
    g = DesignGenerator(seed=20260821, ring_divisions=[8, 12], complexity=0.5, min_pattern_size=10,
                        categories=["botanical", "geometric"])
    g.generate()
    report = g.last_validation_result
    assert g.plan.base_symmetry == 4
    assert report.is_valid and report.stats["num_encircling_regions"] == 0, report.issues[:5]
    assert _once_per_wedge_stems(g) == {1: [0, 3, 6, 9]}


def test_varied_division_design_is_deterministic():
    def run():
        g = DesignGenerator(seed=777, num_rings=4, num_divisions=12, complexity=0.5,
                            categories=["botanical", "geometric"], vary_divisions=True)
        return g.generate()
    assert run() == run()


def test_vary_twenty_two_divisions_uses_symmetry_eleven_and_finishes_quickly():
    # 22 has no divisor in 3..8; the base symmetry used to fall back to 1, so pass two resolved every cell on its
    # own. It is now 11, so pass two resolves one wedge of one or two cells per ring.
    import time
    start = time.perf_counter()
    g = DesignGenerator(seed=1, num_rings=7, num_divisions=22, complexity=1.0, min_pattern_size=5,
                        categories=["botanical", "geometric"], vary_divisions=True)
    g.generate()
    elapsed = time.perf_counter() - start
    assert g.plan.base_symmetry == 11
    assert all(r.divisions in (11, 22) for r in g.plan.rings)
    assert g.last_validation_result.is_valid, g.last_validation_result.issues[:5]
    assert elapsed < 10, f"generation took {elapsed:.1f}s"
