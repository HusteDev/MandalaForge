import hashlib
import math

import pytest

from coloring_generator import DesignGenerator
from composer import CellEntry, CellRecipe, RingPlan, recipe_at
from placement import PlacedPath
from region_repair import classify_faces, face_sets
from topology_validator import PX_PER_INCH, TopologyValidator, max_region_in2, max_region_px2

PRE_CAP_SVG_SHA = {
    (42, 0.5, "botanical"): "f5647414865e908afe58afa2ebc2bf8b29c3d6b2f34fc5127064db33bc404706",
    (42, 0.5, "geometric"): "b2efe41e9cbac64dc8a034016c352b60730e9ab678a07c0bbd923eb45cb87b36",
    (42, 0.85, "botanical"): "9db6b8ecd5217ba1bcc8b8cb1734ddf045e7f104082529aa60ca4ce6d6bdf9f6",
    (42, 0.85, "geometric"): "993620b0be5bfa38566167b281114507d7a5c29519bfaff3ceb3496bb76f1170",
    (777, 0.5, "botanical"): "fe84cd4b8a696c28b3cf9d8fe00771a662ceb82bc42b2c9c1d9c0f959cbb75d6",
    (777, 0.5, "geometric"): "9d410d41976045cb024d46b68f3df807d56845bad641e618d98ea7f3dcd27374",
    (777, 0.85, "botanical"): "86bce39f7b371171d07e868c1436058e56fb9c6c5d0c94bc661c171d95122389",
    (777, 0.85, "geometric"): "54a6edffb8d0d7450dd5d9c93780750a49ae323ee6e681f7ae0075ac116bb21d",
    (12345, 0.5, "botanical"): "61cdf264996d3046cdc613fc8222a956369621f97597d58535f782598dfa6243",
    (12345, 0.5, "geometric"): "323c4fad8bde122a759836f0f66d2a52bd727035fb4b4da3896bfec5b7dbafb1",
    (12345, 0.85, "botanical"): "81d4b8c39c37d95e476ff901477390188bed87b607df421d0dc43c5e234b4d11",
    (12345, 0.85, "geometric"): "a15cc34de566d570cdb6f6e29e11bc9f2d4155fae05139010472c05c45c4d012",
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


def test_cap_is_off_by_default():
    """The repair ladder makes generation several times slower, so the cap is opt-in."""
    from composer import ComposerSettings
    g = DesignGenerator(seed=42)
    assert g.max_region_cap is False and ComposerSettings().max_region_cap is False
    assert g._new_composer().settings.max_region_cap is False
    svg = DesignGenerator(seed=42, complexity=0.5, categories=["botanical"]).generate()
    assert hashlib.sha256(svg.encode("utf-8")).hexdigest() == PRE_CAP_SVG_SHA[(42, 0.5, "botanical")]


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
