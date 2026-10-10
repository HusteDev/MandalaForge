import math
import random
from dataclasses import replace

import pytest
from shapely.geometry import LineString, Point, Polygon

from coloring_generator import DesignGenerator
from motifs import find_motif, safe_motif
from motifs.contract import Anatomy, MotifAnalyzer
from motifs.embellish import (
    EMBELLISHMENT_ORDER, INTERIOR_FILLS, apply_embellishments, embellishment_rng,
)
from motifs.geometry import SmartVector, salted_seed
from tests.test_motifs import make_ctx


def test_echo_repeats_the_outline_inside(cell_kwargs):
    ctx = make_ctx(cell_kwargs, 4, embellishments=("echo",), complexity=0.3)
    inst = find_motif("petal")["generator"](ctx)
    echoes = [v for v in inst.vectors if v.weight == "detail"]
    assert len(echoes) == 1 and echoes[0].closed
    outer = Polygon(ctx.polyline(inst.vectors[0], 0.0)); inner = Polygon(ctx.polyline(echoes[0], 0.0))
    assert outer.contains(inner)
    assert outer.exterior.distance(inner.exterior) >= ctx.clearance_px("outline", "detail") - 1e-6


# At the fixture's 10px white space a 60px-deep petal has room for one echo only, so the two-echo tests
# draw with 4px white space.
def test_two_echoes_at_high_complexity(cell_kwargs):
    ctx = make_ctx(cell_kwargs, 4, embellishments=("echo",), complexity=0.8, min_white_space=4.0)
    assert sum(v.weight == "detail" for v in find_motif("petal")["generator"](ctx).vectors) == 2


def test_second_echo_is_inset_from_the_first(cell_kwargs):
    ctx = make_ctx(cell_kwargs, 4, embellishments=("echo",), complexity=0.8, min_white_space=4.0)
    first, second = [v for v in find_motif("petal")["generator"](ctx).vectors if v.weight == "detail"]
    outer, inner = Polygon(ctx.polyline(first)), Polygon(ctx.polyline(second))
    assert outer.contains(inner)
    assert outer.exterior.distance(inner.exterior) >= ctx.clearance_px("detail", "detail") - 1e-6


def test_echoed_petal_keeps_a_slot_inside_the_innermost_echo(cell_kwargs):
    ctx = make_ctx(cell_kwargs, 4, embellishments=("echo",), complexity=0.8, min_white_space=4.0)
    inst = find_motif("petal")["generator"](ctx)
    assert inst.declaration.slot, "an echoed petal still offers a slot"
    innermost = Polygon(ctx.polyline([v for v in inst.vectors if v.weight == "detail"][-1]))
    slot = Polygon(ctx.polyline(SmartVector(inst.declaration.slot, closed=True)))
    assert innermost.contains(slot)
    assert innermost.exterior.distance(slot.exterior) >= ctx.clearance_px("detail", "outline") - 1e-6
    assert MotifAnalyzer(ctx).analyze(inst) == []


def test_petal_declares_its_anatomy(cell_kwargs):
    ctx = make_ctx(cell_kwargs, 4)
    inst = find_motif("petal")["generator"](ctx)
    anatomy = inst.declaration.anatomy
    assert anatomy.outline == 0 and anatomy.base.angular == 0.0 and anatomy.tip.angular == 0.0
    outline = inst.vectors[0].points
    assert anatomy.base == outline[0] and anatomy.tip in outline
    assert anatomy.tip.radial == max(p.radial for p in outline)


def test_echoed_leaf_validates_and_its_midrib_ends_on_the_innermost_echo(cell_kwargs):
    ctx = make_ctx(cell_kwargs, 5, embellishments=("echo", "veins"), complexity=0.8, min_white_space=4.0)
    inst = find_motif("leaf")["generator"](ctx)
    assert inst.dropped_embellishments == 0
    echoes = [v for v in inst.vectors if v.weight == "detail" and v.closed]
    assert len(echoes) == 2
    midrib = _midrib(inst)
    for end in (midrib.points[0], midrib.points[-1]):
        assert end in echoes[-1].points
    assert MotifAnalyzer(ctx).analyze(inst) == []


def test_echo_is_deterministic_and_never_reaches_further_out(cell_kwargs):
    entry = find_motif("petal")
    ctx = make_ctx(cell_kwargs, 9, embellishments=("echo",), complexity=0.8, min_white_space=4.0)
    a = entry["generator"](replace(ctx, rng=random.Random(9)))
    b = entry["generator"](replace(ctx, rng=random.Random(9)))
    assert [v.points for v in a.vectors] == [v.points for v in b.vectors]
    narrow = entry["generator"](replace(ctx, rng=random.Random(9), radial_limits=(0.0, 0.8)))
    assert max(p.radial for v in narrow.vectors for p in v.points) <= 0.8 + 1e-9


def test_unknown_or_unimplemented_names_are_dropped_and_counted(cell_kwargs):
    ctx = make_ctx(cell_kwargs, 4, embellishments=("beads", "nonsense"))
    inst = find_motif("petal")["generator"](ctx)
    assert inst.dropped_embellishments == 2
    assert all(v.weight == "outline" for v in inst.vectors)


def test_echo_that_does_not_fit_is_dropped(cell_kwargs):
    ctx = make_ctx(cell_kwargs, 4, embellishments=("echo",), complexity=0.8, min_white_space=40.0)
    inst = find_motif("petal")["generator"](ctx)
    assert not any(v.weight == "detail" for v in inst.vectors)
    assert inst.dropped_embellishments == 1


def test_partly_drawn_echo_counts_no_drop(cell_kwargs):
    # Drops are counted per embellishment: two echoes are wanted and one fits at 10px white space, so the
    # echo was drawn and nothing is dropped.
    ctx = make_ctx(cell_kwargs, 4, embellishments=("echo",), complexity=0.8)
    inst = find_motif("petal")["generator"](ctx)
    assert sum(v.weight == "detail" for v in inst.vectors) == 1
    assert inst.dropped_embellishments == 0


def test_pipeline_without_anatomy_drops_echo(cell_kwargs):
    ctx = make_ctx(cell_kwargs, 4, embellishments=("echo",))
    outline = find_motif("petal")["generator"](make_ctx(cell_kwargs, 4)).vectors[0]
    result = apply_embellishments(ctx, [outline], None, list(outline.points))
    assert result.vectors == [outline] and result.dropped == 1 and result.slot_outline_weight == "outline"


def test_embellishment_streams_are_salted_per_name(cell_kwargs):
    ctx = make_ctx(cell_kwargs, 4, node_seed=1234)
    assert embellishment_rng(ctx, "echo").random() == random.Random(salted_seed(1234, "emb:echo")).random()
    assert embellishment_rng(ctx, "dot").random() != embellishment_rng(ctx, "echo").random()


def test_order_and_fills():
    assert EMBELLISHMENT_ORDER == ("echo", "veins", "fan", "dot", "beads")
    assert INTERIOR_FILLS == ("veins", "fan")
    assert Anatomy.__dataclass_params__.frozen


def test_oversized_white_space_drops_detail_silently():
    # Review focus 3: at 50px white space the embellishments do not fit; each is dropped and counted, never
    # raised, and the design validates. Hosts that asked only for implemented names must show real drops.
    g = DesignGenerator(seed=42, num_rings=4, ring_divisions=[8, 8, 8, 12], complexity=1.0,
                        min_pattern_size=50, categories=["botanical", "geometric"])
    g.generate()
    assert g.last_validation_result.is_valid and g.assembled.dropped_embellishments > 0
    implemented = {"echo", "veins", "fan", "dot"}
    real = [n for n in g.assembled.nodes
            if n.instance is not None and n.recipe.embellishments
            and set(n.recipe.embellishments) <= implemented and n.instance.dropped_embellishments]
    assert real, "no implemented embellishment was dropped for not fitting"
    assert {"echo", "veins", "fan", "dot"} <= {name for n in real for name in n.recipe.embellishments}


def test_embellished_design_is_valid_and_carries_echoes():
    g = DesignGenerator(seed=42, num_rings=4, ring_divisions=[8, 8, 8, 12], complexity=1.0,
                        categories=["botanical", "geometric"])
    g.generate()
    assert g.last_validation_result.is_valid
    assert any("echo" in n.recipe.embellishments for n in g.assembled.nodes)
    widths = {path.stroke_width for path in g.assembled.paths}
    assert min(widths) == pytest.approx(0.6 * max(widths))


# ----- veins, fan and dot (Task 10) ----------------------------------------------------------------------

def _midrib(inst):
    """The open vector along the axis (every point at angular 0)."""
    axis = [v for v in inst.vectors if not v.closed and all(abs(p.angular) < 1e-9 for p in v.points)]
    assert len(axis) == 1
    return axis[0]


@pytest.mark.parametrize("name", ["veins", "fan", "dot"])
@pytest.mark.parametrize("host", ["petal", "leaf"])
def test_embellishment_is_valid_or_dropped(name, host, cell_kwargs):
    if name not in find_motif(host)["embellishments"]:
        pytest.skip("host does not accept it")
    for seed in range(10):
        inst = find_motif(host)["generator"](make_ctx(cell_kwargs, seed, embellishments=(name,)))
        assert inst.dropped_embellishments in (0, 1)   # build_instance already validated the vectors


def test_vein_ends_are_vertices_of_the_ink_they_touch(cell_kwargs):
    inst = find_motif("leaf")["generator"](make_ctx(cell_kwargs, 2, embellishments=("veins",)))
    closed = [v for v in inst.vectors if v.closed]
    for v in inst.vectors:
        if not v.closed:
            for end in (v.points[0], v.points[-1]):
                assert any(end in c.points for c in closed) or any(end in o.points for o in inst.vectors if o is not v)


def test_fan_wedges_are_colourable(cell_kwargs):
    ctx = make_ctx(cell_kwargs, 5, embellishments=("fan",))
    inst = find_motif("petal")["generator"](ctx)
    rays = [v for v in inst.vectors if v.weight == "detail" and not v.closed]
    assert len(rays) >= 3


def test_each_embellishment_draws_for_some_seed(cell_kwargs):
    for host, name in (("petal", "veins"), ("petal", "fan"), ("petal", "dot"), ("leaf", "veins")):
        drawn = [find_motif(host)["generator"](make_ctx(cell_kwargs, seed, embellishments=(name,)))
                 .dropped_embellishments == 0 for seed in range(10)]
        assert any(drawn), (host, name)


def test_veins_are_a_midrib_and_mirrored_side_pairs(cell_kwargs):
    ctx = make_ctx(cell_kwargs, 2, embellishments=("veins",))
    inst = find_motif("leaf")["generator"](ctx)
    assert inst.dropped_embellishments == 0
    anatomy, outline = inst.declaration.anatomy, inst.vectors[0]
    midrib = _midrib(inst)
    assert midrib.points[0] == anatomy.base and midrib.points[-1] == anatomy.tip
    sides = [v for v in inst.vectors if not v.closed and v is not midrib]
    assert 2 <= len(sides) <= 8 and len(sides) % 2 == 0
    assert all(v.weight == "detail" and len(v.points) == 2 for v in sides)
    rights = sorted((v for v in sides if v.points[-1].angular > 0), key=lambda v: v.points[0].radial)
    lefts = sorted((v for v in sides if v.points[-1].angular < 0), key=lambda v: v.points[0].radial)
    assert len(rights) == len(lefts)
    for right, left in zip(rights, lefts):
        assert right.points[0] == left.points[0] and right.points[0] in midrib.points
        assert right.points[-1].radial == pytest.approx(left.points[-1].radial)
        assert right.points[-1].angular == pytest.approx(-left.points[-1].angular)
        assert right.points[-1] in outline.points and left.points[-1] in outline.points
        assert right.points[-1].radial > right.points[0].radial  # toward the tip
        # 35 to 50 degrees from the midrib, measured on the page at the vein's start.
        start, end = right.points
        rise = ctx.radial_to_px(end.radial - start.radial)
        across = ctx.angular_to_px(end.angular - start.angular, start.radial)
        assert 34.0 <= math.degrees(math.atan2(across, rise)) <= 51.0
    starts = [ctx.radial_to_px(v.points[0].radial) for v in rights]
    assert all(b - a >= ctx.clearance_px("detail", "detail") - 1e-6 for a, b in zip(starts, starts[1:]))


def test_leaf_without_veins_has_no_midrib(cell_kwargs):
    inst = find_motif("leaf")["generator"](make_ctx(cell_kwargs, 2))
    assert len(inst.vectors) == 1 and inst.vectors[0].closed
    assert inst.declaration.anatomy is not None


def test_fan_is_a_half_disc_hub_and_rays_to_the_outline(cell_kwargs):
    ctx = make_ctx(cell_kwargs, 5, embellishments=("fan",))
    inst = find_motif("petal")["generator"](ctx)
    outline = inst.vectors[0]
    hub = min((v for v in inst.vectors if not v.closed), key=lambda v: max(p.radial for p in v.points))
    rays = [v for v in inst.vectors if not v.closed and v is not hub]
    assert len(rays) >= 3
    assert hub.points[0] in outline.points and hub.points[-1] in outline.points
    for ray in rays:
        assert ray.points[0] in hub.points and ray.points[-1] in outline.points
    # Wedges between rays are at least a detail clearance wide along the hub arc.
    arc = LineString(ctx.polyline(hub))
    along = sorted(arc.project(Point(ctx.to_cartesian(ray.points[0]))) for ray in rays)
    assert all(b - a >= ctx.clearance_px("detail", "detail") - 1e-6 for a, b in zip(along, along[1:]))
    assert inst.declaration.slot is None


def test_dot_keeps_clear_of_all_ink(cell_kwargs):
    ctx = make_ctx(cell_kwargs, 3, embellishments=("dot",), min_white_space=6.0)
    inst = find_motif("petal")["generator"](ctx)
    dots = [v for v in inst.vectors if v.closed and v.weight == "detail"]
    assert len(dots) == 1 and inst.dropped_embellishments == 0
    circle = Polygon(ctx.polyline(dots[0]))
    diameter = 2.0 * math.sqrt(circle.area / math.pi)
    assert ctx.min_white_space - 0.5 <= diameter <= 2.0 * ctx.min_white_space + 0.5
    for other in inst.vectors:
        if other is not dots[0]:
            gap = LineString(ctx.polyline(other)).distance(circle.exterior)
            assert gap >= ctx.clearance_px("outline", "detail") - 1e-6
    # The petal still offers a slot, and it keeps clear of the dot.
    assert inst.declaration.slot
    slot = Polygon(ctx.polyline(SmartVector(inst.declaration.slot, closed=True)))
    assert slot.distance(circle.exterior) >= ctx.clearance_px("detail", "outline") - 1e-6


def test_dot_that_does_not_fit_is_dropped(cell_kwargs):
    ctx = make_ctx(cell_kwargs, 3, embellishments=("veins", "dot"))
    inst = find_motif("petal")["generator"](ctx)
    # A midrib runs along the axis, so a dot centred on it can never keep clear.
    assert any(not v.closed for v in inst.vectors), "the veins should draw for this seed"
    assert not any(v.closed and v.weight == "detail" for v in inst.vectors)
    assert inst.dropped_embellishments == 1


@pytest.mark.parametrize("name", ["veins", "fan", "dot"])
def test_fill_is_deterministic_and_never_reaches_further_out(name, cell_kwargs):
    entry = find_motif("petal")
    ctx = make_ctx(cell_kwargs, 5, embellishments=(name,), min_white_space=6.0)
    a = entry["generator"](replace(ctx, rng=random.Random(5)))
    b = entry["generator"](replace(ctx, rng=random.Random(5)))
    assert [v.points for v in a.vectors] == [v.points for v in b.vectors]
    narrow = entry["generator"](replace(ctx, rng=random.Random(5), radial_limits=(0.0, 0.8)))
    assert max(p.radial for v in narrow.vectors for p in v.points) <= 0.8 + 1e-9


# ----- beads on bands (Task 11) ---------------------------------------------------------------------------

from motifs.geometry import CellPoint
from tests.test_composer import plan_for


def _band(cell_kwargs, seed=1, ring=5, **over):
    ctx = make_ctx(cell_kwargs, seed, ring_stream_seed=ring, embellishments=("beads",), **over)
    return ctx, find_motif("band")["generator"](ctx)


def _beads(inst):
    return [v for v in inst.vectors if v.closed and v.weight == "detail"]


def _centre(bead):
    radials = [p.radial for p in bead.points]
    angulars = [p.angular for p in bead.points]
    return CellPoint((min(radials) + max(radials)) / 2.0, (min(angulars) + max(angulars)) / 2.0)


# At the fixture's 10px white space a beaded band is thick enough, but its ~34px half-cell beside the lens
# rarely leaves room for a 10px bead with its clearances, so the bead tests draw with 4px white space.
def test_beads_are_the_same_in_every_cell(cell_kwargs):
    make = lambda s: find_motif("band")["generator"](make_ctx(
        cell_kwargs, s, ring_stream_seed=5, embellishments=("beads",), min_white_space=4.0))
    a, b = make(1), make(2)
    assert [v.points for v in a.vectors] == [v.points for v in b.vectors]
    assert any(v.closed and v.weight == "detail" for v in a.vectors)


def test_beaded_band_draws_wider_arcs_from_the_same_draws(cell_kwargs):
    from motifs.geometric import (
        BAND_INNER_RANGE, BAND_OUTER_RANGE, BEADED_BAND_INNER_RANGE, BEADED_BAND_OUTER_RANGE,
    )
    assert (BEADED_BAND_INNER_RANGE, BEADED_BAND_OUTER_RANGE) == ((0.12, 0.25), (0.75, 0.88))
    assert (BAND_INNER_RANGE, BAND_OUTER_RANGE) == ((0.25, 0.45), (0.55, 0.75))
    for ring in range(20):
        plain = find_motif("band")["generator"](make_ctx(cell_kwargs, 1, ring_stream_seed=ring))
        beaded = find_motif("band")["generator"](make_ctx(cell_kwargs, 1, ring_stream_seed=ring,
                                                          embellishments=("beads",)))
        (p1, p2), (b1, b2) = [(i.vectors[0].points[0].radial, i.vectors[1].points[0].radial) for i in (plain, beaded)]
        assert 0.25 <= p1 <= 0.45 and 0.55 <= p2 <= 0.75
        assert 0.12 <= b1 <= 0.25 and 0.75 <= b2 <= 0.88
        # The same draws, in the same order: each radial sits at the same share of its range.
        assert (b1 - 0.12) / 0.13 == pytest.approx((p1 - 0.25) / 0.2)
        assert (b2 - 0.75) / 0.13 == pytest.approx((p2 - 0.55) / 0.2)


def test_beads_draw_only_from_the_ring_stream(cell_kwargs):
    _, a = _band(cell_kwargs, seed=1, node_seed=11, min_white_space=4.0)
    _, b = _band(cell_kwargs, seed=2, node_seed=99, min_white_space=4.0)
    assert _beads(a) and [v.points for v in _beads(a)] == [v.points for v in _beads(b)]
    rows = {tuple(tuple(v.points) for v in _beads(_band(cell_kwargs, ring=r, min_white_space=4.0)[1]))
            for r in range(8)}
    assert len(rows) > 1, "the ring stream should decide the beads"


def test_seam_recipe_copies_carry_embellishments():
    for seed in range(40):
        for ring in plan_for(seed=seed, categories=["geometric"], complexity=1.0).rings:
            for pos in ("centre", "divider"):
                nodes = [getattr(e, pos) for e in ring.sequence]
                # A planned fallback (the category's safe band) is not in the registry; the composer reads it
                # from `safe_motif`, and it has no seams.
                if nodes[0] and (find_motif(nodes[0].motif) or safe_motif(nodes[0].category))["seams"]:
                    assert all(n.embellishments == nodes[0].embellishments for n in nodes)



def test_seam_recipe_copies_carry_embellishments_when_picks_vary():
    # At complexity 1.0 a band always takes its one embellishment; at 0.3 it takes none or one, so copies
    # composed with their own picks would differ. A sequence longer than one entry needs a base symmetry
    # below the division count, which mixed ring divisions give.
    picked = set()
    for seed in range(40):
        for ring in plan_for(seed=seed, categories=["geometric"], complexity=0.3,
                             ring_divisions=[8, 8, 8, 12]).rings:
            for pos in ("centre", "divider"):
                nodes = [getattr(e, pos) for e in ring.sequence]
                if nodes[0] and (find_motif(nodes[0].motif) or safe_motif(nodes[0].category))["seams"]:
                    assert all(n.embellishments == nodes[0].embellishments for n in nodes)
                    if len(nodes) > 1:
                        picked.add(tuple(nodes[0].embellishments))
    assert len(picked) > 1

def test_beads_are_mirrored_rows_in_each_half_cell(cell_kwargs):
    seen = set()
    for ring in range(12):
        ctx, inst = _band(cell_kwargs, ring=ring, min_white_space=4.0)
        beads = _beads(inst)
        if not beads:
            continue
        r1, r2 = inst.vectors[0].points[0].radial, inst.vectors[1].points[0].radial
        lens = inst.vectors[2]
        lens_edge = max(p.angular for p in lens.points)
        rights = sorted((b for b in beads if _centre(b).angular > 0), key=lambda b: _centre(b).angular)
        lefts = sorted((b for b in beads if _centre(b).angular < 0), key=lambda b: -_centre(b).angular)
        assert len(rights) == len(lefts) == len(beads) // 2 and 1 <= len(rights) <= 3
        seen.add(len(rights))
        for right, left in zip(rights, lefts):
            assert sorted((p.radial, -p.angular) for p in left.points) == pytest.approx(
                sorted((p.radial, p.angular) for p in right.points))
            assert _centre(right).radial == pytest.approx((r1 + r2) / 2.0)
            assert lens_edge < min(p.angular for p in right.points) and max(p.angular for p in right.points) < 1.0
        centres = [_centre(b).angular for b in rights]
        middle = (r1 + r2) / 2.0
        start = lens_edge + ctx.px_to_angular(
            ctx.clearance_px("outline", "detail") - ctx.clearance_px("detail", "detail") / 2.0, middle)
        gaps = [b - a for a, b in zip([start] + centres, centres + [1.0])]
        # Evenly spaced across the free span: equal pitch between beads, half a pitch at either end.
        assert gaps[0] == pytest.approx(gaps[-1], abs=1e-6)
        assert all(g == pytest.approx(2.0 * gaps[0], abs=1e-6) for g in gaps[1:-1])
    assert len(seen) > 1, "k should vary with the ring stream"


def test_beads_keep_clear_of_ink_neighbours_and_the_seam(cell_kwargs):
    drawn = 0
    for ring in range(12):
        for mws in (3.0, 4.0, 5.0):
            ctx, inst = _band(cell_kwargs, ring=ring, min_white_space=mws)
            beads = _beads(inst)
            drawn += bool(beads)
            od, dd = ctx.clearance_px("outline", "detail"), ctx.clearance_px("detail", "detail")
            for bead in beads:
                line = LineString(ctx.polyline(bead))
                for other in inst.vectors:
                    if other is bead:
                        continue
                    gap = line.distance(LineString(ctx.polyline(other)))
                    assert gap >= (dd if other.weight == "detail" else od) - 1e-6
                # The bead in the neighbouring cell is this one reflected across the seam at angular 1.
                mirrored = SmartVector([CellPoint(p.radial, 2.0 - p.angular) for p in bead.points], closed=True)
                if _centre(bead).angular > 0:
                    assert line.distance(LineString(ctx.polyline(mirrored))) >= dd - 1e-6
    assert drawn >= 12


def test_beads_are_round_on_the_page(cell_kwargs):
    ctx, inst = _band(cell_kwargs, min_white_space=4.0)
    assert _beads(inst)
    for bead in _beads(inst):
        cx, cy = ctx.to_cartesian(_centre(bead))
        radii = [math.hypot(x - cx, y - cy) for x, y in (ctx.to_cartesian(p) for p in bead.points)]
        assert max(radii) - min(radii) < 0.05 * max(radii)
        assert ctx.min_white_space / 2.0 - 1e-6 <= max(radii) <= ctx.min_white_space + 1e-6


def test_beads_that_do_not_fit_are_dropped(cell_kwargs):
    ctx, inst = _band(cell_kwargs, min_white_space=40.0)
    assert not _beads(inst) and inst.dropped_embellishments == 1


def test_beads_need_a_band(cell_kwargs):
    inst = find_motif("petal")["generator"](make_ctx(cell_kwargs, 4, embellishments=("beads",)))
    assert inst.dropped_embellishments == 1 and all(v.weight == "outline" for v in inst.vectors)


def test_beaded_bands_are_detail_ink_in_a_valid_design():
    from assembler import _path_role
    for seed in range(6):
        g = DesignGenerator(seed=seed, num_rings=4, ring_divisions=[8, 8, 8, 12], complexity=1.0,
                            categories=["geometric"])
        g.generate()
        beaded = [n for n in g.assembled.nodes if n.recipe.motif == "band" and n.instance is not None
                  and "beads" in n.recipe.embellishments and _beads(n.instance)]
        if beaded:
            assert g.last_validation_result.is_valid
            assert g.last_validation_result.stats.get("num_floating_base", 0) == 0
            assert all(_path_role(b, "base") == "detail" for n in beaded for b in _beads(n.instance))
            return
    pytest.fail("no seed drew beads on a band")
