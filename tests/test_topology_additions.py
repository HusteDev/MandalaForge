from shapely.geometry import LineString
from topology_validator import TopologyValidator, structural_components

SQ = lambda x: [(x, 0), (x + 10, 0), (x + 10, 10), (x, 10), (x, 0)]

def test_structural_components_groups_touching_lines():
    ids = structural_components([SQ(0), SQ(10), SQ(50)])
    assert ids[0] == ids[1] != ids[2]

def test_floating_base_reported():
    report = TopologyValidator().analyze([SQ(0), SQ(10), SQ(50)], base_mask=[True, True, True])
    assert report.stats["num_floating_base"] == 1
    assert any(i.startswith("Floating base motif") for i in report.issues)

def test_slot_island_is_not_floating_base():
    report = TopologyValidator().analyze([SQ(0), SQ(10), SQ(50)], base_mask=[True, True, False])
    assert report.stats["num_floating_base"] == 0

def test_overflow_crossing_detected():
    lines = [SQ(0), [(5, -20), (5, 20)]]
    report = TopologyValidator().analyze(
        lines, ring_ids=[0, 1], overflow_parts=[(1, LineString([(5, -20), (5, 20)]))])
    assert report.stats["num_overflow_crossings"] == 1

def test_overflow_touch_at_endpoint_is_allowed():
    lines = [SQ(0), [(5, -20), (5, 0)]]
    report = TopologyValidator().analyze(
        lines, ring_ids=[0, 1], overflow_parts=[(1, LineString([(5, -20), (5, 0)]))])
    assert report.stats["num_overflow_crossings"] == 0

def test_overflow_touch_at_shared_vertex_is_allowed():
    # The overflow line's middle vertex (5, 0) is also a vertex inserted into the square's bottom edge.
    square = [(0, 0), (5, 0), (10, 0), (10, -10), (0, -10), (0, 0)]
    overflow = [(2, 5), (5, 0), (8, 5)]
    report = TopologyValidator().analyze(
        [square, overflow], ring_ids=[0, 1], overflow_parts=[(1, LineString(overflow))])
    assert report.stats["num_overflow_crossings"] == 0

def test_overflow_vertex_off_the_other_lines_vertex_crosses():
    square = [(0, 0), (5, 0), (10, 0), (10, -10), (0, -10), (0, 0)]
    overflow = [(2, 5), (5.5, -0.5), (8, 5)]
    report = TopologyValidator().analyze(
        [square, overflow], ring_ids=[0, 1], overflow_parts=[(1, LineString(overflow))])
    assert report.stats["num_overflow_crossings"] == 1
