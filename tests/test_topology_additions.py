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


# A slot petal from the (24,24,24) c0.9 harness design: a pen fits it with 4.9px to spare, but eroding
# the face on the validator's 0.001px noding grid collapsed it to empty in GEOS.
GRID_COLLAPSE_LOOP = [
    (502.26329708847595, 253.41140804127338), (506.8554086185208, 253.92370418872514),
    (511.36439952134197, 254.15944454661195), (515.7621070666041, 253.97950117077232),
    (520.0425520978688, 253.33593364422407), (524.2233002532889, 252.2887031460434),
    (528.3407646569744, 250.98508566175298), (532.4395551260124, 249.60781435169125),
    (536.8128733083117, 249.33949701747076), (540.30031608508, 247.36328282438018),
    (544.0861683721572, 246.58961964745743), (547.8761507691208, 245.83302228475986),
    (551.6173013725303, 244.8803963634508), (555.2591945726767, 243.5303891754469),
    (558.768854546301, 241.6614834663111), (562.1405959849494, 239.2745901538943),
    (565.3989057476717, 236.49427268739447), (561.1869679865055, 235.71560201218114),
    (557.0735075894348, 235.33436248682926), (553.0996000390628, 235.47067265225178),
    (549.2706244158643, 236.122478732222), (545.5543799932738, 237.16805578576975),
    (541.8938602762585, 238.40781444771898), (538.2283844322129, 239.63072862606987),
    (534.2200632967417, 239.66299831991844), (530.298499984928, 241.61728778335743),
    (526.0602076589205, 242.47393107545932), (521.8425701440057, 243.40369741908916),
    (517.6983207854964, 244.58714328175677), (513.6695628856444, 246.17001997034777),
    (509.77106474511294, 248.213038208259), (505.9840342567803, 250.67169079829662),
    (502.26329708847595, 253.41140804127338),
]

def test_pen_test_erodes_faces_in_floating_precision():
    [face] = TopologyValidator().faces([GRID_COLLAPSE_LOOP])
    assert not face.is_too_thin and not face.is_uncolorable
    report = TopologyValidator().analyze([GRID_COLLAPSE_LOOP])
    assert not report.tiny_regions
