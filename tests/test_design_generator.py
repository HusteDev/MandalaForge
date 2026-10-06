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
