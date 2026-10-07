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
    g = gen(); g.generate()
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
        for reach in g.assembled.reaches:
            floor = g.rings[reach.ring_index - 1]["inner_radius"]
            end = reach.coords[-1]
            # A landing may bend onto ink up to the touch gap beside its ray.
            assert math.hypot(end[0] - g.center[0], end[1] - g.center[1]) >= floor - TOUCH_GAP_PX - 1e-6


@pytest.mark.parametrize("vary", [False, True])
@pytest.mark.parametrize("seed", REVIEW_SEEDS)
def test_review_seeds_generate_and_validate(seed, vary):
    g = DesignGenerator(seed=seed, num_rings=4, num_divisions=12, complexity=0.5,
                        categories=["botanical", "geometric"], vary_divisions=vary)
    g.generate()
    assert g.last_validation_result.is_valid, g.last_validation_result.issues[:5]


def test_varied_division_design_is_deterministic():
    def run():
        g = DesignGenerator(seed=777, num_rings=4, num_divisions=12, complexity=0.5,
                            categories=["botanical", "geometric"], vary_divisions=True)
        return g.generate()
    assert run() == run()
