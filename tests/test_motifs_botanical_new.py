"""Shape-specific tests for the Phase 3 botanical motifs (spec 7.3): teardrop, rounded_petal, heart and curl."""
import math
import random

import pytest

from motifs import find_motif
from motifs.contract import MotifError
from motifs.geometry import CellPoint, MotifContext
from qa_patterns import max_turn_deg, tangent_error_deg, turn_at


def make_ctx(cell_kwargs, seed=7, **over):
    return MotifContext(**{**cell_kwargs, "rng": random.Random(seed), **over})


def tip_and_base(pts):
    tip = max(range(len(pts)), key=lambda k: pts[k].radial)
    base = min(range(len(pts)), key=lambda k: (pts[k].radial, abs(pts[k].angular)))
    return tip, base


# ----- Task 14: teardrop and rounded petal -----------------------------------------------------------

def test_turn_at_reads_a_square_corner_and_a_straight_run(cell_kwargs):
    ctx = make_ctx(cell_kwargs)
    square = [CellPoint(0.2, -0.3), CellPoint(0.2, 0.3), CellPoint(0.8, 0.3), CellPoint(0.8, -0.3)]
    assert 80.0 < turn_at(ctx, square, 2) < 100.0
    line = [CellPoint(0.2, 0.3), CellPoint(0.5, 0.3), CellPoint(0.8, 0.3)]
    assert turn_at(ctx, line, 1) == pytest.approx(0.0, abs=1e-6)


def test_teardrop_has_a_round_base_and_a_sharp_tip(cell_kwargs):
    ctx = make_ctx(cell_kwargs, 6)
    pts = find_motif("teardrop")["generator"](ctx).vectors[0].points
    tip = max(range(len(pts)), key=lambda k: pts[k].radial)
    assert max_turn_deg(ctx, pts, True, {tip}) <= 35.0 and turn_at(ctx, pts, tip) >= 60.0


@pytest.mark.parametrize("touch", [None, 0.08, 0.12, 0.2, 0.35, 0.45, 0.6])
def test_teardrop_is_smooth_but_its_tip_for_every_draw(touch, cell_kwargs):
    for seed in range(20):
        ctx = make_ctx(cell_kwargs, seed, side_touch_radial=touch)
        pts = find_motif("teardrop")["generator"](ctx).vectors[0].points
        tip, _ = tip_and_base(pts)
        assert max_turn_deg(ctx, pts, True, {tip}) <= 35.0, seed
        assert turn_at(ctx, pts, tip) >= 60.0, seed


def test_teardrop_base_is_a_page_space_circular_arc(cell_kwargs):
    from motifs.botanical import TEARDROP_ARC_STEPS
    ctx = make_ctx(cell_kwargs, 3)
    pts = find_motif("teardrop")["generator"](ctx).vectors[0].points
    arc = pts[:TEARDROP_ARC_STEPS + 1]
    page = [ctx.to_cartesian(p) for p in arc]
    # The arc's first point is its bottom on the axis; the centre lies on the axis above it.
    assert arc[0].angular == 0.0
    # Fit the centre from the bottom and the far end: equal page distance from a point on the axis.
    bottom = page[0]
    radii = []
    for radial in [arc[0].radial + k * 0.001 for k in range(1, 800)]:
        centre = ctx.to_cartesian(CellPoint(radial, 0.0))
        radii.append((abs(math.dist(centre, page[-1]) - math.dist(centre, bottom)), centre))
    centre = min(radii)[1]
    distances = [math.dist(centre, p) for p in page]
    assert max(distances) - min(distances) < 0.05 * max(distances)


def test_teardrop_arc_meets_its_sides_tangentially(cell_kwargs):
    from motifs.botanical import TEARDROP_ARC_STEPS
    for seed in range(10):
        ctx = make_ctx(cell_kwargs, seed)
        pts = find_motif("teardrop")["generator"](ctx).vectors[0].points
        assert turn_at(ctx, pts, TEARDROP_ARC_STEPS) <= 10.0
        assert turn_at(ctx, pts, len(pts) - TEARDROP_ARC_STEPS) <= 10.0


def test_rounded_petal_has_no_corner_at_its_tip(cell_kwargs):
    for seed in range(10):
        ctx = make_ctx(cell_kwargs, seed, side_touch_radial=0.12)
        pts = find_motif("rounded_petal")["generator"](ctx).vectors[0].points
        base = min(range(len(pts)), key=lambda k: (pts[k].radial, abs(pts[k].angular)))
        assert max_turn_deg(ctx, pts, True, {base}) <= 35.0


@pytest.mark.parametrize("touch", [None, 0.08, 0.2, 0.35, 0.6])
def test_rounded_petal_has_no_corner_but_its_base_for_every_draw(touch, cell_kwargs):
    for seed in range(20):
        ctx = make_ctx(cell_kwargs, seed, complexity=1.0, side_touch_radial=touch)
        pts = find_motif("rounded_petal")["generator"](ctx).vectors[0].points
        _, base = tip_and_base(pts)
        assert max_turn_deg(ctx, pts, True, {base}) <= 35.0, seed


@pytest.mark.parametrize("name", ["teardrop", "rounded_petal"])
@pytest.mark.parametrize("radial", [0.08, 0.12, 0.2, 0.35, 0.45, 0.6])
def test_side_touch_vertex_is_exact_widest_and_smooth(name, radial, cell_kwargs):
    for seed in range(12):
        for limit in (1.0, 0.5):
            ctx = make_ctx(cell_kwargs, seed, angular_limits=limit, side_touch_radial=radial)
            pts = find_motif(name)["generator"](ctx).vectors[0].points
            for side in (limit, -limit):
                hits = [k for k, p in enumerate(pts) if p.radial == radial and p.angular == side]
                assert len(hits) == 1, (seed, side)
                assert tangent_error_deg(ctx, pts, hits[0]) <= 10.0
            assert max(abs(p.angular) for p in pts) <= limit


@pytest.mark.parametrize("name", ["teardrop", "rounded_petal"])
def test_outline_is_mirror_symmetric_with_two_axis_vertices(name, cell_kwargs):
    for seed in range(10):
        pts = find_motif(name)["generator"](make_ctx(cell_kwargs, seed)).vectors[0].points
        assert [p for p in pts if p.angular == 0.0] == [pts[0], max(pts, key=lambda p: p.radial)]
        mirrored = {(p.radial, -p.angular) for p in pts}
        assert mirrored == {(p.radial, p.angular) for p in pts}


@pytest.mark.parametrize("name", ["teardrop", "rounded_petal"])
def test_anatomy_names_the_base_and_the_tip(name, cell_kwargs):
    inst = find_motif(name)["generator"](make_ctx(cell_kwargs, 5))
    pts = inst.vectors[0].points
    anatomy = inst.declaration.anatomy
    assert anatomy.outline == 0 and anatomy.base == pts[0]
    assert anatomy.tip == max(pts, key=lambda p: p.radial) and anatomy.tip.angular == 0.0


@pytest.mark.parametrize("name", ["teardrop", "rounded_petal"])
def test_bases_stay_in_the_ring_and_reach_the_next(name, cell_kwargs):
    for seed in range(30):
        pts = find_motif(name)["generator"](make_ctx(cell_kwargs, seed, radial_limits=(-0.5, 1.5))).vectors[0].points
        assert min(p.radial for p in pts) >= -1e-12
        assert 0.95 - 1e-12 <= max(p.radial for p in pts) <= 1.2 + 1e-12


def test_rounded_petal_tip_is_a_page_space_circular_arc_tangent_to_both_sides(cell_kwargs):
    from motifs.botanical import CAP_STEPS
    for seed in range(10):
        ctx = make_ctx(cell_kwargs, seed)
        pts = find_motif("rounded_petal")["generator"](ctx).vectors[0].points
        top = max(range(len(pts)), key=lambda k: pts[k].radial)
        cap = pts[top - CAP_STEPS: top + CAP_STEPS + 1]
        assert turn_at(ctx, pts, top - CAP_STEPS) <= 10.0 and turn_at(ctx, pts, top + CAP_STEPS) <= 10.0
        page = [ctx.to_cartesian(p) for p in cap]
        # The cap's centre is on the axis below the top, equidistant from the top and the cap's ends.
        best = min((abs(math.dist(ctx.to_cartesian(CellPoint(r, 0.0)), page[0])
                        - math.dist(ctx.to_cartesian(CellPoint(r, 0.0)), page[CAP_STEPS])), r)
                   for r in [pts[top].radial - k * 0.0005 for k in range(1, 1200)])
        centre = ctx.to_cartesian(CellPoint(best[1], 0.0))
        distances = [math.dist(centre, p) for p in page]
        assert max(distances) - min(distances) < 0.05 * max(distances)


@pytest.mark.parametrize("name", ["teardrop", "rounded_petal"])
def test_slot_child_fits_inside_the_slot_and_holds_a_pen(name, cell_kwargs):
    from shapely.geometry import Polygon
    from motifs.embellish import holds_pen
    placed = 0
    for seed in range(15):
        slot = find_motif("petal")["generator"](make_ctx(cell_kwargs, seed, complexity=1.0)).declaration.slot
        if slot is None:
            continue
        ctx = make_ctx(cell_kwargs, seed)
        ctx.slot = slot
        try:
            inst = find_motif(name)["generator"](ctx)
        except MotifError:
            continue
        placed += 1
        outline = inst.vectors[0].points
        assert Polygon([(p.angular, p.radial) for p in slot]).buffer(1e-9).contains(
            Polygon([(p.angular, p.radial) for p in outline]))
        assert holds_pen(ctx, outline)
    assert placed > 0


# ----- Task 15: heart and curl -----------------------------------------------------------------------

from shapely.geometry import LineString, Point
from motifs.geometry import SmartVector


def test_heart_has_its_cusp_and_point_on_the_centreline(cell_kwargs):
    pts = find_motif("heart")["generator"](make_ctx(cell_kwargs, 2)).vectors[0].points
    on_axis = [p for p in pts if p.angular == 0.0]
    assert len(on_axis) == 2


@pytest.mark.parametrize("touch", [None, 0.35, 0.45, 0.6])
def test_heart_point_is_lowest_and_cusp_sits_below_the_lobe_tops(touch, cell_kwargs):
    for seed in range(20):
        ctx = make_ctx(cell_kwargs, seed, side_touch_radial=touch)
        inst = find_motif("heart")["generator"](ctx)
        pts = inst.vectors[0].points
        point, cusp = [p for p in pts if p.angular == 0.0]
        assert point == pts[0] and point.radial == min(p.radial for p in pts)
        assert point.radial < cusp.radial < max(p.radial for p in pts)
        assert inst.declaration.anatomy.base == point and inst.declaration.anatomy.tip == cusp
        assert max(p.radial for p in pts) <= 1.2 + 1e-12 and min(p.radial for p in pts) >= -1e-12


@pytest.mark.parametrize("radial", [0.35, 0.45, 0.6])
def test_heart_lobes_widest_vertices_are_the_touch_vertices_with_radial_tangents(radial, cell_kwargs):
    for seed in range(12):
        for limit in (1.0, 0.5):
            ctx = make_ctx(cell_kwargs, seed, angular_limits=limit, side_touch_radial=radial)
            pts = find_motif("heart")["generator"](ctx).vectors[0].points
            for side in (limit, -limit):
                hits = [k for k, p in enumerate(pts) if p.radial == radial and p.angular == side]
                assert len(hits) == 1
                assert tangent_error_deg(ctx, pts, hits[0]) <= 10.0
            assert max(abs(p.angular) for p in pts) <= limit


def test_heart_lobes_are_page_space_circular_arcs(cell_kwargs):
    from motifs.botanical import HEART_ARC_STEPS
    for seed in range(10):
        ctx = make_ctx(cell_kwargs, seed)
        pts = find_motif("heart")["generator"](ctx).vectors[0].points
        cusp = next(k for k, p in enumerate(pts) if k and p.angular == 0.0)
        arc = [ctx.to_cartesian(p) for p in pts[cusp - HEART_ARC_STEPS: cusp + 1]]
        # The circle through three of the arc's points holds every other point of it.
        (ax, ay), (bx, by), (cx, cy) = arc[0], arc[len(arc) // 2], arc[-1]
        d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
        ux = ((ax * ax + ay * ay) * (by - cy) + (bx * bx + by * by) * (cy - ay) + (cx * cx + cy * cy) * (ay - by)) / d
        uy = ((ax * ax + ay * ay) * (cx - bx) + (bx * bx + by * by) * (ax - cx) + (cx * cx + cy * cy) * (bx - ax)) / d
        radius = math.dist((ux, uy), arc[0])
        assert all(abs(math.dist((ux, uy), p) - radius) < 0.05 * radius for p in arc)


def test_heart_has_no_corner_but_its_point_and_cusp(cell_kwargs):
    for touch in (None, 0.35, 0.45, 0.6):
        for seed in range(15):
            ctx = make_ctx(cell_kwargs, seed, side_touch_radial=touch)
            pts = find_motif("heart")["generator"](ctx).vectors[0].points
            axis = {k for k, p in enumerate(pts) if p.angular == 0.0}
            assert max_turn_deg(ctx, pts, True, axis) <= 35.0, (touch, seed)


def test_heart_fits_a_wide_shallow_cell_with_side_touch():
    # A cell much wider than deep: a round lobe as wide as the budget would rise past the outer limit.
    wide = dict(inner_radius=183.0, outer_radius=286.0, wedge_angle=60.0, center=(306.0, 306.0),
                stroke_width=1.75, complexity=0.5, min_white_space=10.0)
    for seed in range(10):
        for radial in (0.35, 0.6):
            ctx = MotifContext(**wide, rng=random.Random(seed), side_touch_radial=radial, radial_limits=(0.0, 1.0))
            pts = find_motif("heart")["generator"](ctx).vectors[0].points
            assert max(p.radial for p in pts) <= 1.0 + 1e-12
            assert any(p.radial == radial and p.angular == 1.0 for p in pts)


def test_curl_inner_end_lands_on_an_earlier_turn(cell_kwargs):
    ctx = make_ctx(cell_kwargs, 8, side_touch_radial=0.45)
    for v in find_motif("curl")["generator"](ctx).vectors:
        earlier = LineString(ctx.polyline(SmartVector(v.points[:-3])))
        assert earlier.distance(Point(ctx.to_cartesian(v.points[-1]))) <= 1e-6


def _unwrapped(centre, page):
    angles, total = [], 0.0
    previous = math.atan2(page[0][1] - centre[1], page[0][0] - centre[0])
    for x, y in page:
        angle = math.atan2(y - centre[1], x - centre[0])
        total += math.remainder(angle - previous, 2 * math.pi)
        previous = angle
        angles.append(abs(total))
    return angles


def _at(angles, page, target):
    for k in range(1, len(angles)):
        if angles[k - 1] <= target <= angles[k]:
            share = (target - angles[k - 1]) / (angles[k] - angles[k - 1]) if angles[k] > angles[k - 1] else 0.0
            return (page[k - 1][0] + (page[k][0] - page[k - 1][0]) * share,
                    page[k - 1][1] + (page[k][1] - page[k - 1][1]) * share)
    return None


@pytest.mark.parametrize("touch", [None, 0.35, 0.45, 0.6])
def test_curl_turns_keep_white_space(touch, cell_kwargs):
    from motifs.botanical import CURL_STALK_STEPS, curl_layout
    turned = 0
    for seed in range(15):
        for wide in (False, True):
            kwargs = dict(cell_kwargs, inner_radius=200.0, outer_radius=300.0) if wide else cell_kwargs
            ctx = make_ctx(kwargs, seed, side_touch_radial=touch)
            inst = find_motif("curl")["generator"](ctx)
            layout = curl_layout(make_ctx(kwargs, seed, side_touch_radial=touch))
            for vector, centre in zip(inst.vectors, layout.centres):
                # The spiral alone, from the stalk's end to the inner end, without the connector.
                page = ctx.polyline(SmartVector(vector.points[CURL_STALK_STEPS:-1]))
                centre_px = ctx.to_cartesian(centre)
                angles = _unwrapped(centre_px, page)
                assert angles[-1] <= 3 * math.pi + 1e-6  # at most 1.5 turns
                for k in range(0, 721):
                    t = math.radians(k * 0.5)
                    a, b = _at(angles, page, t), _at(angles, page, t + 2 * math.pi)
                    if a is None or b is None:
                        continue
                    turned += 1
                    assert math.dist(a, b) >= ctx.clearance_px() - 1e-6, (seed, wide, k)
    assert turned > 0


@pytest.mark.parametrize("radial", [0.35, 0.45, 0.6])
def test_curl_outermost_vertices_are_the_touch_vertices(radial, cell_kwargs):
    for seed in range(12):
        ctx = make_ctx(cell_kwargs, seed, side_touch_radial=radial)
        inst = find_motif("curl")["generator"](ctx)
        assert len(inst.vectors) == 2 and not any(v.closed for v in inst.vectors)
        for vector, side in zip(inst.vectors, (1.0, -1.0)):
            pts = vector.points
            hits = [k for k, p in enumerate(pts) if p.radial == radial and p.angular == side]
            assert len(hits) == 1
            assert tangent_error_deg(ctx, pts, hits[0]) <= 10.0
            assert max(abs(p.angular) for p in pts) == 1.0


def test_curl_spirals_are_mirrored_and_joined_at_the_base(cell_kwargs):
    for seed in range(10):
        right, left = find_motif("curl")["generator"](make_ctx(cell_kwargs, seed)).vectors
        assert left.points == [CellPoint(p.radial, -p.angular) for p in right.points]
        base = right.points[0]
        assert base.angular == 0.0 and base == left.points[0]
        # The base is the curl's lowest point, to within a sag of the stalk beside it far below a pixel.
        assert base.radial <= min(p.radial for p in right.points) + 0.1 / 60.0
        assert all(p.angular > 0 for p in right.points[1:])


def test_curl_stays_in_its_ring(cell_kwargs):
    for seed in range(20):
        for touch in (None, 0.45):
            pts = [p for v in find_motif("curl")["generator"](
                make_ctx(cell_kwargs, seed, side_touch_radial=touch, radial_limits=(-0.5, 1.5))).vectors
                for p in v.points]
            assert min(p.radial for p in pts) >= -1e-12 and max(p.radial for p in pts) <= 1.2 + 1e-12


def test_curl_in_a_slot_stays_inside_it(cell_kwargs):
    from shapely.geometry import Polygon
    placed = 0
    big = dict(cell_kwargs, inner_radius=200.0, outer_radius=320.0, wedge_angle=40.0, min_white_space=5.0)
    for seed in range(15):
        slot = find_motif("petal")["generator"](make_ctx(big, seed, complexity=1.0)).declaration.slot
        if slot is None:
            continue
        ctx = make_ctx(big, seed)
        ctx.slot = slot
        try:
            inst = find_motif("curl")["generator"](ctx)
        except MotifError:
            continue
        placed += 1
        polygon = Polygon([(p.angular, p.radial) for p in slot]).buffer(1e-9)
        assert all(polygon.contains(LineString([(p.angular, p.radial) for p in v.points])) for v in inst.vectors)
    assert placed > 0
