import random
from dataclasses import replace

import pytest
from shapely.geometry import Polygon

from coloring_generator import DesignGenerator
from motifs import find_motif
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
    ctx = make_ctx(cell_kwargs, 4, embellishments=("echo",), complexity=0.8, min_white_space=4.0)
    inst = find_motif("leaf")["generator"](ctx)
    echoes = [v for v in inst.vectors if v.weight == "detail" and v.closed]
    assert len(echoes) == 2
    midribs = [v for v in inst.vectors if not v.closed]
    assert len(midribs) == 1
    for end in (midribs[0].points[0], midribs[0].points[-1]):
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
    assert inst.dropped_embellishments >= 1


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
    g = DesignGenerator(seed=42, num_rings=4, ring_divisions=[8, 8, 8, 12], complexity=1.0,
                        min_pattern_size=50, categories=["botanical", "geometric"])
    g.generate()
    assert g.last_validation_result.is_valid and g.assembled.dropped_embellishments > 0


def test_embellished_design_is_valid_and_carries_echoes():
    g = DesignGenerator(seed=42, num_rings=4, ring_divisions=[8, 8, 8, 12], complexity=1.0,
                        categories=["botanical", "geometric"])
    g.generate()
    assert g.last_validation_result.is_valid
    assert any("echo" in n.recipe.embellishments for n in g.assembled.nodes)
    widths = {path.stroke_width for path in g.assembled.paths}
    assert min(widths) == pytest.approx(0.6 * max(widths))
