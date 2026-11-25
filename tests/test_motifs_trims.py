"""Shape-specific tests for the roadmap Phase B ring trims (sawtooth, arcade, vesica_chain)."""
import math
import random

import pytest

from motifs import find_motif
from motifs.contract import MotifError
from motifs.embellish import _across_seam, _faces_hold_pen
from motifs.geometry import CellPoint, MotifContext
from qa_patterns import turn_at

TRIMS = ["sawtooth", "arcade", "vesica_chain"]


def make_ctx(cell_kwargs, seed=7, ring_seed=11, **over):
    return MotifContext(**{**cell_kwargs, "rng": random.Random(seed), "ring_stream_seed": ring_seed, **over})


def seam_ends(instance):
    return sorted((p.radial, p.angular) for v in instance.vectors if not v.closed for p in (v.points[0], v.points[-1]))


@pytest.mark.parametrize("name", TRIMS)
def test_trim_ends_are_exact_seam_ends(cell_kwargs, name):
    gen = find_motif(name)["generator"]
    for ring_seed in range(10):
        inst = gen(make_ctx(cell_kwargs, ring_seed=ring_seed))
        for radial, angular in seam_ends(inst):
            assert abs(angular) == 1.0
        assert all(abs(p.angular) <= 1.0 + 1e-9 for v in inst.vectors for p in v.points)
        assert all(0.0 <= p.radial <= 1.0 for v in inst.vectors for p in v.points)


@pytest.mark.parametrize("name", TRIMS)
def test_trim_is_the_same_in_every_cell(cell_kwargs, name):
    gen = find_motif(name)["generator"]
    for ring_seed in range(5):
        a = gen(make_ctx(cell_kwargs, seed=1, ring_seed=ring_seed))
        b = gen(make_ctx(cell_kwargs, seed=2, ring_seed=ring_seed))
        assert [v.points for v in a.vectors] == [v.points for v in b.vectors]


@pytest.mark.parametrize("name", TRIMS)
def test_trim_needs_the_full_budget(cell_kwargs, name):
    with pytest.raises(MotifError):
        find_motif(name)["generator"](make_ctx(cell_kwargs, angular_limits=0.5))


def test_sawtooth_inset_line_only_at_high_complexity(cell_kwargs):
    gen = find_motif("sawtooth")["generator"]
    insets = 0
    for ring_seed in range(20):
        assert len(gen(make_ctx(cell_kwargs, ring_seed=ring_seed, complexity=0.3)).vectors) == 1
        inst = gen(make_ctx(cell_kwargs, ring_seed=ring_seed, complexity=0.9))
        if len(inst.vectors) == 2:
            insets += 1
            outer, inner = inst.vectors
            assert inner.weight == "detail"
            # Nested on the same feet, so the two lines close one chevron face in each cell.
            assert (inner.points[0], inner.points[-1]) == (outer.points[0], outer.points[-1])
            ctx = make_ctx(cell_kwargs, ring_seed=ring_seed, complexity=0.9)
            assert _faces_hold_pen(ctx, inst.vectors, ctx.clearance_px("outline", "detail"))
    assert insets >= 5


def test_arcade_cusp_and_seam_v_are_sharp(cell_kwargs):
    gen = find_motif("arcade")["generator"]
    for ring_seed in range(20):
        ctx = make_ctx(cell_kwargs, ring_seed=ring_seed)
        pts = gen(ctx).vectors[0].points
        cusp = len(pts) // 2
        assert pts[cusp].angular == 0.0
        assert turn_at(ctx, pts, cusp) >= 20.0
        # The neighbouring cell's arc is this one mirrored across the seam at angular 1.
        seam = [CellPoint(p.radial, 2.0 - p.angular) for p in reversed(pts[-2:])] + [pts[-2]]
        assert turn_at(ctx, [pts[-2], pts[-1], seam[0]], 1) >= 20.0


def test_arcade_arcs_are_round_on_the_page(cell_kwargs):
    gen = find_motif("arcade")["generator"]
    ctx = make_ctx(cell_kwargs, ring_seed=3)
    pts = gen(ctx).vectors[0].points
    right = [ctx.to_cartesian(p) for p in pts[len(pts) // 2:]]
    # The circle through three samples holds every other sample to within 1% of its radius.
    (ax, ay), (bx, by), (cx, cy) = right[0], right[len(right) // 2], right[-1]
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    ux = ((ax * ax + ay * ay) * (by - cy) + (bx * bx + by * by) * (cy - ay) + (cx * cx + cy * cy) * (ay - by)) / d
    uy = ((ax * ax + ay * ay) * (cx - bx) + (bx * bx + by * by) * (ax - cx) + (cx * cx + cy * cy) * (bx - ax)) / d
    radius = math.hypot(ax - ux, ay - uy)
    assert all(abs(math.hypot(x - ux, y - uy) - radius) <= 0.01 * radius for x, y in right)


def test_vesica_crossings_are_shared_vertices(cell_kwargs):
    gen = find_motif("vesica_chain")["generator"]
    for ring_seed in range(10):
        ctx = make_ctx(cell_kwargs, ring_seed=ring_seed)
        vectors = gen(ctx).vectors
        for a, b in zip(vectors, vectors[1:]):
            shared = set(a.points) & set(b.points)
            assert len(shared) == 2, ring_seed
        assert _faces_hold_pen(ctx, vectors + [_across_seam(v) for v in vectors], ctx.clearance_px())


def test_vesica_raises_in_a_shallow_ring(cell_kwargs):
    with pytest.raises(MotifError):
        find_motif("vesica_chain")["generator"](make_ctx(cell_kwargs, outer_radius=cell_kwargs["inner_radius"] + 30.0))


def test_vesica_fills_a_wide_cell_with_more_circles(cell_kwargs):
    gen = find_motif("vesica_chain")["generator"]
    narrow = gen(make_ctx(cell_kwargs, wedge_angle=15.0))
    wide = gen(make_ctx(cell_kwargs, wedge_angle=60.0))
    assert len(wide.vectors) > len(narrow.vectors) >= 2
    assert sum(v.closed for v in wide.vectors) == len(wide.vectors) - 2
