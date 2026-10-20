"""Roadmap Phase B embellishments: cap, hatch and dotted_echo."""
import random

import pytest
from shapely.geometry import LineString

from composer import excludes, force_embellishment_picks, pick_embellishments
from motifs import find_motif
from motifs.embellish import EXCLUSIVE_GROUPS, MIN_HATCH_LINES, _faces_hold_pen, holds_pen
from motifs.geometry import MotifContext


def make_ctx(cell_kwargs, seed=1, **over):
    kwargs = {**cell_kwargs, "outer_radius": cell_kwargs["inner_radius"] + 70.0, "min_white_space": 6.0}
    return MotifContext(**{**kwargs, "rng": random.Random(seed), "node_seed": seed, **over})


def draw(cell_kwargs, host, names, seed=1, **over):
    ctx = make_ctx(cell_kwargs, seed, embellishments=tuple(names), **over)
    return ctx, find_motif(host)["generator"](ctx)


def detail_open(inst):
    return [v for v in inst.vectors if not v.closed and v.weight == "detail"]


def constant_radial(vector):
    return len({round(p.radial, 12) for p in vector.points}) == 1


@pytest.mark.parametrize("host", ["petal", "rounded_petal", "teardrop"])
def test_cap_arcs_cross_the_host_near_its_tip(cell_kwargs, host):
    drawn = 0
    for seed in range(12):
        ctx, inst = draw(cell_kwargs, host, ["cap"], seed)
        if inst.dropped_embellishments:
            continue
        drawn += 1
        arcs = detail_open(inst)
        assert 1 <= len(arcs) <= 3 and all(constant_radial(a) for a in arcs)
        outline = inst.vectors[0]
        tip = max(p.radial for p in outline.points if p.angular == 0.0)
        base = min(p.radial for p in outline.points if p.angular == 0.0)
        for arc in arcs:
            # Both ends are vertices of the outline, and the arc sits in the outer half of the axis.
            assert arc.points[0] in outline.points and arc.points[-1] in outline.points
            assert arc.points[0].radial > (base + tip) / 2.0
        assert _faces_hold_pen(ctx, inst.vectors, ctx.clearance_px("outline", "detail"))
    assert drawn >= 6


def test_veins_stop_at_the_lowest_cap_arc(cell_kwargs):
    both = 0
    for seed in range(12):
        ctx, inst = draw(cell_kwargs, "petal", ["cap", "veins"], seed)
        if inst.dropped_embellishments:
            continue
        both += 1
        arcs = [v for v in detail_open(inst) if constant_radial(v) and len(v.points) >= 3]
        lowest = min(arcs, key=lambda a: a.points[0].radial)
        ceiling = lowest.points[0].radial
        midrib = next(v for v in inst.vectors if not v.closed and v.weight == "outline")
        assert midrib.points[-1] in lowest.points
        for vein in detail_open(inst):
            if vein not in arcs:
                assert vein.points[-1].radial <= ceiling + 1e-9
                assert vein.points[-1] in lowest.points or vein.points[-1] in inst.vectors[0].points
    assert both >= 6


@pytest.mark.parametrize("host", ["leaf", "teardrop", "spike", "kite"])
def test_hatch_lines_run_across_the_host(cell_kwargs, host):
    drawn = 0
    for seed in range(12):
        ctx, inst = draw(cell_kwargs, host, ["hatch"], seed)
        if inst.dropped_embellishments:
            continue
        drawn += 1
        lines = detail_open(inst)
        assert len(lines) >= MIN_HATCH_LINES and all(constant_radial(v) for v in lines)
        radials = sorted(v.points[0].radial for v in lines)
        gaps = [b - a for a, b in zip(radials, radials[1:])]
        assert max(gaps) - min(gaps) < 1e-9
        assert all(v.points[0] in inst.vectors[0].points and v.points[-1] in inst.vectors[0].points for v in lines)
        assert _faces_hold_pen(ctx, inst.vectors, ctx.clearance_px("outline", "detail"))
    assert drawn >= 6


def test_hatch_drops_on_a_small_host(cell_kwargs):
    ctx, inst = draw(cell_kwargs, "kite", ["hatch"], 1, outer_radius=cell_kwargs["inner_radius"] + 20.0)
    assert inst.dropped_embellishments == 1 and not detail_open(inst)


@pytest.mark.parametrize("host", ["petal", "rounded_petal", "teardrop"])
def test_dotted_echo_dots_are_round_mirrored_and_clear(cell_kwargs, host):
    drawn = 0
    for seed in range(16):
        ctx, inst = draw(cell_kwargs, host, ["dotted_echo"], seed)
        if inst.dropped_embellishments:
            continue
        drawn += 1
        dots = [v for v in inst.vectors if v.closed and v.weight == "detail"]
        assert len(dots) >= 4 and len(dots) % 2 == 0
        half = len(dots) // 2
        for dot, mirrored in zip(dots[:half], dots[half:]):
            assert [p.angular for p in mirrored.points] == [-p.angular for p in dot.points]
        lines = [LineString(ctx.polyline(d)) for d in dots]
        outline = LineString(ctx.polyline(inst.vectors[0]))
        for k, line in enumerate(lines):
            assert holds_pen(ctx, dots[k].points)
            assert line.distance(outline) >= ctx.clearance_px("outline", "detail") - 1e-6
            assert all(line.distance(other) >= ctx.clearance_px("detail", "detail") - 1e-6 for other in lines[k + 1:])
    assert drawn >= 4


def test_dot_keeps_clear_of_a_dotted_echo(cell_kwargs):
    both = 0
    for seed in range(16):
        ctx, inst = draw(cell_kwargs, "petal", ["dotted_echo", "dot"], seed)
        if inst.dropped_embellishments:
            continue
        both += 1
        circles = [LineString(ctx.polyline(v)) for v in inst.vectors if v.closed and v.weight == "detail"]
        # The axis dot is the last circle drawn.
        dot = circles[-1]
        assert all(dot.distance(other) >= ctx.clearance_px("detail", "detail") - 1e-6 for other in circles[:-1])
    assert both >= 2


def test_exclusive_groups_keep_one_of_each():
    assert excludes("echo", "dotted_echo") and excludes("cap", "fan") and excludes("cap", "hatch")
    assert excludes("dotted_echo", "veins") and not excludes("cap", "veins") and not excludes("cap", "dot")
    entry = find_motif("petal")
    for seed in range(200):
        picked = pick_embellishments(entry, 0.95, random.Random(seed))
        for group in EXCLUSIVE_GROUPS:
            assert len(set(group) & set(picked)) <= 1
    assert force_embellishment_picks(entry, ["echo", "fan", "dot"], ["dotted_echo"]) == ["dotted_echo", "dot"]
    assert force_embellishment_picks(entry, ["cap", "veins"], ["fan"]) == ["fan"]
