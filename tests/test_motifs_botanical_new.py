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
