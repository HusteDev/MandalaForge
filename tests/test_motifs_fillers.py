"""Shape-specific tests for the roadmap Phase A fillers (crescent, kite, stamen, floret, star)."""
import math
import random

import pytest
from shapely.geometry import Polygon

from motifs import find_motif
from motifs.contract import MotifError
from motifs.embellish import _faces_hold_pen, holds_pen
from motifs.fillers import STAR_EDGE_STEPS, STAR_TIPS
from motifs.geometry import CellPoint, MotifContext
from qa_patterns import tangent_error_deg, turn_at
from tests.test_motifs import children_in_real_slots, outline_polygon, slot_polygon


def make_ctx(cell_kwargs, seed=7, **over):
    return MotifContext(**{**cell_kwargs, "rng": random.Random(seed), **over})


def gate_kwargs(cell_kwargs, name):
    """`cell_kwargs` with the wedge narrowed so the cell is the motif's minimum width at mid radius."""
    mid = (cell_kwargs["inner_radius"] + cell_kwargs["outer_radius"]) / 2.0
    return {**cell_kwargs, "wedge_angle": math.degrees(find_motif(name)["min_cell_width_px"] / mid)}


@pytest.mark.parametrize("radial", [0.08, 0.35, 0.6])
@pytest.mark.parametrize("limit", [1.0, 0.25])
def test_crescent_horns_are_the_side_touch_vertices(cell_kwargs, radial, limit):
    gen = find_motif("crescent")["generator"]
    for seed in range(10):
        pts = gen(make_ctx(cell_kwargs, seed, angular_limits=limit, side_touch_radial=radial)).vectors[0].points
        assert CellPoint(radial, limit) in pts and CellPoint(radial, -limit) in pts
        assert max(abs(p.angular) for p in pts) <= limit + 1e-9


def test_crescent_stays_above_the_ring_floor(cell_kwargs):
    gen = find_motif("crescent")["generator"]
    for seed in range(40):
        pts = gen(make_ctx(cell_kwargs, seed, side_touch_radial=0.08)).vectors[0].points
        assert min(p.radial for p in pts) >= 0.0


@pytest.mark.parametrize("radial", [0.08, 0.35, 0.6])
def test_crescent_touch_is_smooth(cell_kwargs, radial):
    gen = find_motif("crescent")["generator"]
    for seed in range(20):
        for limit in (1.0, 0.5):
            ctx = make_ctx(cell_kwargs, seed, angular_limits=limit, side_touch_radial=radial)
            pts = gen(ctx).vectors[0].points
            for side in (limit, -limit):
                assert tangent_error_deg(ctx, pts, pts.index(CellPoint(radial, side))) <= 10.0, (seed, limit)


def test_crescent_face_holds_pen(cell_kwargs):
    gen = find_motif("crescent")["generator"]
    kwargs = gate_kwargs(cell_kwargs, "crescent")
    drawn = 0
    for seed in range(40):
        for limit in (1.0, 0.5, 0.25):
            for radial in (None, 0.08, 0.35):
                ctx = make_ctx(kwargs, seed, angular_limits=limit, side_touch_radial=radial)
                try:
                    inst = gen(ctx)
                except MotifError:
                    continue
                drawn += 1
                assert holds_pen(ctx, inst.vectors[0].points)
    assert drawn > 0


def test_crescent_slot_child_inside_slot(cell_kwargs):
    children = list(children_in_real_slots(cell_kwargs, "crescent"))
    assert len(children) >= 5
    for slot, inst in children:
        assert slot_polygon(slot).contains(outline_polygon(inst))


@pytest.mark.parametrize("radial", [0.35, 0.45, 0.6])
@pytest.mark.parametrize("limit", [1.0, 0.5])
def test_kite_side_vertices_are_the_touch_vertices(cell_kwargs, radial, limit):
    gen = find_motif("kite")["generator"]
    for seed in range(10):
        ctx = make_ctx(cell_kwargs, seed, angular_limits=limit, side_touch_radial=radial)
        pts = gen(ctx).vectors[0].points
        assert CellPoint(radial, limit) in pts and CellPoint(radial, -limit) in pts
        assert max(abs(p.angular) for p in pts) <= limit + 1e-9
        for side in (limit, -limit):
            assert tangent_error_deg(ctx, pts, pts.index(CellPoint(radial, side))) <= 10.0, (seed, limit)


def test_kite_top_is_within_limits(cell_kwargs):
    gen = find_motif("kite")["generator"]
    for seed in range(40):
        pts = gen(make_ctx(cell_kwargs, seed, radial_limits=(0.0, 1.0))).vectors[0].points
        assert max(p.radial for p in pts) <= 1.0 and min(p.radial for p in pts) >= 0.0


def test_kite_bottom_keeps_a_clearance_above_the_floor(cell_kwargs):
    gen = find_motif("kite")["generator"]
    for seed in range(20):
        for radial in (None, 0.35):
            ctx = make_ctx(cell_kwargs, seed, side_touch_radial=radial)
            bottom = min(p.radial for p in gen(ctx).vectors[0].points)
            assert ctx.radial_to_px(bottom) >= ctx.clearance_px() - 1e-9


def test_kite_tips_are_sharp(cell_kwargs):
    gen = find_motif("kite")["generator"]
    for seed in range(20):
        for limit in (1.0, 0.5):
            ctx = make_ctx(cell_kwargs, seed, angular_limits=limit)
            pts = gen(ctx).vectors[0].points
            top = max(range(len(pts)), key=lambda k: pts[k].radial)
            assert turn_at(ctx, pts, top) >= 60.0, (seed, limit)
            # The bottom sits a clearance above the floor, so it is a shorter, blunter tip than the top.
            assert turn_at(ctx, pts, 0) >= 45.0, (seed, limit)


def stamen_parts(inst):
    cup, stem, ball = inst.vectors[:3]
    return cup, stem, ball, inst.vectors[3:]


@pytest.mark.parametrize("radial", [0.08, 0.2])
@pytest.mark.parametrize("limit", [1.0, 0.5])
def test_stamen_cup_widest_vertices_are_touch_vertices(cell_kwargs, radial, limit):
    gen = find_motif("stamen")["generator"]
    for seed in range(10):
        inst = gen(make_ctx(cell_kwargs, seed, angular_limits=limit, side_touch_radial=radial))
        cup = stamen_parts(inst)[0].points
        assert CellPoint(radial, limit) in cup and CellPoint(radial, -limit) in cup
        assert all(abs(p.angular) <= limit + 1e-9 for v in inst.vectors for p in v.points)


def test_stamen_stem_ends_on_cup_and_ball(cell_kwargs):
    gen = find_motif("stamen")["generator"]
    for seed in range(20):
        inst = gen(make_ctx(cell_kwargs, seed, complexity=0.9, side_touch_radial=0.1))
        cup, stem, ball, sides = stamen_parts(inst)
        assert not stem.closed and stem.points[0] in cup.points and stem.points[-1] in ball.points
        for side_stem, side_ball in zip(sides[0::2], sides[1::2]):
            assert side_stem.points[0] == stem.points[0] and side_stem.points[-1] in side_ball.points


def test_stamen_ball_is_round_on_the_page(cell_kwargs):
    gen = find_motif("stamen")["generator"]
    for seed in range(10):
        ctx = make_ctx(cell_kwargs, seed)
        ball = stamen_parts(gen(ctx))[2].points
        page = [ctx.to_cartesian(p) for p in ball]
        cx, cy = sum(x for x, _ in page) / len(page), sum(y for _, y in page) / len(page)
        radii = [math.hypot(x - cx, y - cy) for x, y in page]
        assert max(radii) <= min(radii) * 1.02


def test_stamen_trident_keeps_clearance(cell_kwargs):
    from shapely.geometry import LineString, Point, Polygon
    gen = find_motif("stamen")["generator"]
    tridents = 0
    for seed in range(40):
        for limit in (1.0, 0.5):
            ctx = make_ctx(cell_kwargs, seed, complexity=0.9, angular_limits=limit, side_touch_radial=0.1)
            inst = gen(ctx)
            cup, stem, ball, sides = stamen_parts(inst)
            if not sides:
                continue
            tridents += 1
            disc = Point(ctx.to_cartesian(stem.points[0])).buffer(2.0 * ctx.clearance_px())
            shape = lambda v: (Polygon(ctx.polyline(v)).exterior if v.closed else LineString(ctx.polyline(v)))
            rooted = lambda v: v is cup or (not v.closed and v.points[0] == stem.points[0])
            for k, vector in enumerate(sides):
                partner = sides[k + 1] if k % 2 == 0 else sides[k - 1]
                for other in [cup, stem, ball] + [v for v in sides if v is not vector and v is not partner]:
                    a, b = shape(vector), shape(other)
                    if rooted(vector) and rooted(other):
                        # Only lines sharing the root vertex may meet inside its touch disc.
                        a, b = a.difference(disc), b.difference(disc)
                    assert a.distance(b) >= ctx.clearance_px() - 1e-6, (seed, limit, k)
    assert tridents >= 5


def test_stamen_draws_in_a_quarter_budget(cell_kwargs):
    gen = find_motif("stamen")["generator"]
    kwargs = {**gate_kwargs(cell_kwargs, "stamen"), "outer_radius": cell_kwargs["inner_radius"] + 36.0}
    for seed in range(40):
        try:
            gen(make_ctx(kwargs, seed, angular_limits=0.25, side_touch_radial=0.1))
        except MotifError:
            pass


def slot_children(cell_kwargs, name, white):
    return list(children_in_real_slots({**cell_kwargs, "min_white_space": white}, name))


@pytest.mark.parametrize("white", [4.0, 6.0, 10.0])
def test_floret_every_face_holds_pen(cell_kwargs, white):
    children = slot_children(cell_kwargs, "floret", white)
    assert len(children) >= 5
    for _slot, inst in children:
        ctx = make_ctx({**cell_kwargs, "min_white_space": white})
        assert _faces_hold_pen(ctx, inst.vectors)


def test_floret_dividers_end_on_ink(cell_kwargs):
    dividers = 0
    for _slot, inst in slot_children(cell_kwargs, "floret", 4.0):
        closed = [p for v in inst.vectors if v.closed for p in v.points]
        for vector in inst.vectors:
            if not vector.closed:
                dividers += 1
                assert vector.weight == "detail"
                assert vector.points[0] in closed and vector.points[-1] in closed
    assert dividers > 0


@pytest.mark.parametrize("name", ["floret", "star"])
def test_slot_set_is_contained_in_slot(cell_kwargs, name):
    children = slot_children(cell_kwargs, name, 6.0)
    assert len(children) >= 5
    for slot, inst in children:
        assert all(slot_polygon(slot).contains(Polygon([(p.angular, p.radial) for p in v.points]))
                   for v in inst.vectors if v.closed)


def test_star_has_k_tips(cell_kwargs):
    for _slot, inst in slot_children(cell_kwargs, "star", 6.0):
        ctx = make_ctx(cell_kwargs)
        page = [ctx.to_cartesian(p) for p in inst.vectors[0].points]
        cx, cy = sum(x for x, _ in page) / len(page), sum(y for _, y in page) / len(page)
        radii = [math.hypot(x - cx, y - cy) for x, y in page]
        count = len(radii)
        tips = sum(1 for k in range(count) if radii[k] > radii[k - 1] and radii[k] > radii[(k + 1) % count])
        assert STAR_TIPS[0] <= tips <= STAR_TIPS[1]
        assert count == 2 * tips * STAR_EDGE_STEPS


@pytest.mark.parametrize("name", ["floret", "star"])
def test_slot_sets_raise_below_gate(cell_kwargs, name):
    ctx = make_ctx(cell_kwargs)
    half = ctx.px_to_angular(2.0, 0.5)
    ctx.slot = [CellPoint(0.3, -half), CellPoint(0.3, half), CellPoint(0.7, half), CellPoint(0.7, -half)]
    with pytest.raises(MotifError):
        find_motif(name)["generator"](ctx)
