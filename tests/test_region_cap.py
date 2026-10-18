import hashlib
import math

import pytest

from coloring_generator import DesignGenerator
from composer import CellEntry, CellRecipe, RingPlan, recipe_at
from placement import PlacedPath
from region_repair import classify_faces, face_sets
from topology_validator import PX_PER_INCH, TopologyValidator, max_region_in2, max_region_px2

PRE_CAP_SVG_SHA = {
    (42, 0.5, "botanical"): "55a9ce0f8425ac958c69eac82ed0141359b8265221a56503d95596f7338a0e11",
    (42, 0.5, "geometric"): "063e031a20e787326a4b65bfd02bb7a6fdb1b91cd19a0e0902344f60c39cc9b6",
    (42, 0.85, "botanical"): "6a02bd39683fd68b1377e5efc255690327048fdd09d50e876ae993b4efd45108",
    (42, 0.85, "geometric"): "9f3f0e83ac58d3ec6fab1f6a9799acada2ae258271cb111ecd0ee8f6dbcb31b0",
    (777, 0.5, "botanical"): "fe84cd4b8a696c28b3cf9d8fe00771a662ceb82bc42b2c9c1d9c0f959cbb75d6",
    (777, 0.5, "geometric"): "f7a225a066752850c97039ad182087948ce1b1cbb27b55cc1a9ffc280de83efb",
    (777, 0.85, "botanical"): "574913f932717863b9fe5f759438cc3039f9b71ca448ff9b72d9834c52cacb6f",
    (777, 0.85, "geometric"): "e40f8a80b8266ea965fd429676939b18fb7d699861e04e402d574c4a8ca5e9d8",
    (12345, 0.5, "botanical"): "c978a536e6553f0ae4a99d8d9a806ddaeb3a57c9c3a22e84163068bb71a15c9e",
    (12345, 0.5, "geometric"): "e9b1e98245f1fbc6486abcc6c185b75215de0b178576658945c0d26db1320a16",
    (12345, 0.85, "botanical"): "805941795d11fa3e395bad5c991a34f56160eeb7aab767777cdd405bd2a89a4f",
    (12345, 0.85, "geometric"): "1162401d3cbe43420504c2bf2e6882048d631586cb7a2194e3b12e89f5102607",
}


def square(side, at=(100.0, 100.0)):
    x, y = at
    return [(x, y), (x + side, y), (x + side, y + side), (x, y + side), (x, y)]


def test_cap_values():
    assert max_region_in2(0.0) == pytest.approx(1.25)
    assert max_region_in2(0.6) == pytest.approx(0.86)
    assert max_region_in2(1.0) == pytest.approx(0.6)
    assert max_region_in2(-1.0) == pytest.approx(1.25) and max_region_in2(2.0) == pytest.approx(0.6)
    assert max_region_px2(0.6) == pytest.approx(0.86 * 5184.0) and PX_PER_INCH == 72.0


def test_oversized_face_is_reported_not_failed():
    cap = max_region_px2(0.5)                       # 4795.2 px2
    report = TopologyValidator(max_region_px2=cap).analyze([square(100.0)])
    plain = TopologyValidator().analyze([square(100.0)])
    assert len(report.oversized_regions) == 1 and report.stats["num_oversized_regions"] == 1
    assert report.stats["largest_region_in2"] == pytest.approx(round(10000.0 / 5184.0, 3))
    assert report.is_valid == plain.is_valid and report.issues == plain.issues
    assert plain.oversized_regions == [] and plain.stats["num_oversized_regions"] == 0


def test_face_under_the_cap_is_not_oversized():
    report = TopologyValidator(max_region_px2=max_region_px2(0.5)).analyze([square(60.0)])
    assert report.oversized_regions == []


def test_empty_linework_still_reports_the_cap_stats():
    report = TopologyValidator(max_region_px2=max_region_px2(0.5)).analyze([])
    assert not report.is_valid and report.oversized_regions == []
    assert report.stats["num_oversized_regions"] == 0 and report.stats["largest_region_in2"] == 0.0


def test_generator_reports_largest_region():
    g = DesignGenerator(seed=42, num_rings=4, ring_divisions=[8, 8, 8, 12], max_region_cap=False)
    g.generate()
    assert g.last_validation_result.stats["num_oversized_regions"] == 0
    assert g.last_validation_result.stats["largest_region_in2"] > 0.0


@pytest.mark.parametrize("case", sorted(PRE_CAP_SVG_SHA))
def test_cap_off_reproduces_the_pre_cap_engine(case):
    seed, complexity, category = case
    svg = DesignGenerator(seed=seed, complexity=complexity, categories=[category], max_region_cap=False).generate()
    assert hashlib.sha256(svg.encode("utf-8")).hexdigest() == PRE_CAP_SVG_SHA[case]


CENTER = (306.0, 306.0)
RINGS = [{"inner_radius": 20, "outer_radius": 100}, {"inner_radius": 100, "outer_radius": 200}]


def circle(radius, n=96):
    cx, cy = CENTER
    pts = [(cx + radius * math.cos(2 * math.pi * i / n), cy + radius * math.sin(2 * math.pi * i / n)) for i in range(n)]
    return pts + [pts[0]]


def petal(angle_deg, radius=150.0, side=40.0):
    cx = CENTER[0] + radius * math.cos(math.radians(angle_deg)) - side / 2
    cy = CENTER[1] + radius * math.sin(math.radians(angle_deg)) - side / 2
    return square(side, (cx, cy))


def placed(ring, cell, position, node_path, role, coords):
    return PlacedPath(ring, cell, position, node_path, role, list(coords), [0.5] * len(coords), True, 1.0)


def build_design(petal_cells):
    paths = [placed(0, 0, "centre", (0,), "base", circle(100.0)),
             placed(1, 0, "centre", (0,), "base", circle(200.0))]
    paths += [placed(1, cell, "divider", (1,), "base", petal(cell * 30.0)) for cell in petal_cells]
    regions = TopologyValidator().faces([p.coords for p in paths])
    return regions, paths, RINGS, CENTER


@pytest.fixture
def design():
    return build_design([3])


@pytest.fixture
def design_four_petals():
    return build_design([0, 3, 6, 9])


def test_centre_face_is_owned_by_ring_zero(design):
    centre = [f for f in classify_faces(*design) if f.kind == "centre"]
    assert len(centre) == 1 and centre[0].ring_index == 0 and centre[0].key == ("centre", 0)


def test_host_face_maps_to_its_node(design):
    host = [f for f in classify_faces(*design) if f.kind == "host"]
    assert len(host) == 1
    assert (host[0].ring_index, host[0].position, host[0].node_path) == (1, "divider", (1,))
    assert host[0].key == ("host", 1, "divider", 1, (), False)


def test_background_face_is_owned_by_the_ring_holding_most_of_it(design):
    back = [f for f in classify_faces(*design) if f.kind == "background"]
    assert len(back) == 1 and back[0].ring_index == 1
    assert (1, 3, "divider", (1,)) in back[0].bordering and (0, 0, "centre", (0,)) in back[0].bordering


def test_symmetric_copies_form_one_set(design_four_petals):    # four copies of the petal, cells 0, 3, 6, 9
    sets = face_sets([f for f in classify_faces(*design_four_petals) if f.kind == "host"])
    assert len(sets) == 1 and len(sets[0].faces) == 4


def test_recipe_at_walks_slot_children_and_back():
    child = CellRecipe("diamond", "geometric")
    ring = RingPlan(1, 8, 1.0, [CellEntry(CellRecipe("petal", "botanical", slot_child=child), None)], 0,
                    back=CellRecipe("leaf", "botanical"))
    assert recipe_at(ring, "centre", (0,)) is ring.sequence[0].centre
    assert recipe_at(ring, "centre", (0, 0, 0)) is None
    assert recipe_at(ring, "centre", (0, 0)) is ring.sequence[0].centre.slot_child
    assert recipe_at(ring, "divider", (0,), on_back=True) is ring.back
