"""Shape-specific tests for the Phase 3 geometric motifs (spec 7.3): bead and spike."""
import random

import pytest

from motifs import find_motif
from motifs.geometry import CellPoint, MotifContext


def make_ctx(cell_kwargs, seed=7, **over):
    return MotifContext(**{**cell_kwargs, "rng": random.Random(seed), **over})


def test_spike_sides_are_concave(cell_kwargs):
    ctx = make_ctx(cell_kwargs, 4, side_touch_radial=0.12)
    pts = find_motif("spike")["generator"](ctx).vectors[0].points
    tip = max(pts, key=lambda p: p.radial)
    corner = CellPoint(0.12, 1.0)
    right = [p for p in pts if p.angular > 0 and corner.radial < p.radial < tip.radial]
    chord = lambda r: 1.0 - (r - corner.radial) / (tip.radial - corner.radial)
    assert right and all(p.angular < chord(p.radial) for p in right)


def test_spike_sides_are_concave_for_every_draw(cell_kwargs):
    gen = find_motif("spike")["generator"]
    for seed in range(40):
        for limit in (1.0, 0.5):
            for radial in (0.08, 0.2):
                pts = gen(make_ctx(cell_kwargs, seed, angular_limits=limit, side_touch_radial=radial)).vectors[0].points
                tip = max(pts, key=lambda p: p.radial)
                chord = lambda r: limit * (1.0 - (r - radial) / (tip.radial - radial))
                right = [p for p in pts if p.angular > 0 and radial < p.radial < tip.radial]
                assert right and all(p.angular < chord(p.radial) for p in right), (seed, limit, radial)


def test_spike_has_exact_touch_vertices_a_sharp_tip_and_nothing_wider(cell_kwargs):
    gen = find_motif("spike")["generator"]
    for seed in range(20):
        for limit in (1.0, 0.6):
            pts = gen(make_ctx(cell_kwargs, seed, angular_limits=limit, side_touch_radial=0.15)).vectors[0].points
            assert CellPoint(0.15, limit) in pts and CellPoint(0.15, -limit) in pts
            assert all(abs(p.angular) <= limit for p in pts)
            tip = max(pts, key=lambda p: p.radial)
            assert tip.angular == 0.0
            # The widest points are the base corners: the spike narrows all the way to its tip.
            assert all(abs(p.angular) < limit for p in pts if p.radial > 0.15)


def test_spike_is_mirror_symmetric_and_widest_at_its_base_without_side_touch(cell_kwargs):
    gen = find_motif("spike")["generator"]
    for seed in range(20):
        pts = gen(make_ctx(cell_kwargs, seed)).vectors[0].points
        assert {(p.radial, -p.angular) for p in pts} == {(p.radial, p.angular) for p in pts}
        widest = max(pts, key=lambda p: abs(p.angular))
        assert widest.radial < 0.25


# ----- bead -----------------------------------------------------------------

from shapely.geometry import Polygon

from qa_patterns import tangent_error_deg


def _bead(ctx):
    return find_motif("bead")["generator"](ctx).vectors[0].points


def _touch_index(pts, radial, angular):
    return next(k for k, p in enumerate(pts) if p.radial == radial and p.angular == angular)


def test_bead_diameter_spans_the_touch_vertices(cell_kwargs):
    ctx = make_ctx(cell_kwargs, 1, side_touch_radial=0.45, angular_limits=0.4)
    pts = find_motif("bead")["generator"](ctx).vectors[0].points
    assert CellPoint(0.45, 0.4) in pts and CellPoint(0.45, -0.4) in pts


def test_bead_is_a_true_page_circle_when_it_fits(cell_kwargs):
    for seed in range(5):
        ctx = make_ctx(cell_kwargs, seed, side_touch_radial=0.45, angular_limits=0.4)
        pts = _bead(ctx)
        radius_px = ctx.angular_to_px(0.4, 0.45)
        # Round on the page in the cell's local frame: the vertical semi-axis equals the horizontal one.
        assert max(p.radial for p in pts) - 0.45 == pytest.approx(ctx.px_to_radial(radius_px))
        assert 0.45 - min(p.radial for p in pts) == pytest.approx(ctx.px_to_radial(radius_px))
        assert all(abs(p.angular) <= 0.4 for p in pts)


def test_bead_becomes_an_oval_with_exact_ends_and_radial_tangents_at_full_budget(cell_kwargs):
    for radial in (0.08, 0.12, 0.2, 0.45, 0.6):
        for seed in range(5):
            ctx = make_ctx(cell_kwargs, seed, side_touch_radial=radial)
            pts = _bead(ctx)
            assert CellPoint(radial, 1.0) in pts and CellPoint(radial, -1.0) in pts
            assert all(abs(p.angular) <= 1.0 for p in pts)
            assert min(p.radial for p in pts) >= 0.0 - 1e-12 and max(p.radial for p in pts) <= 1.0 + 1e-12
            for side in (1.0, -1.0):
                k = _touch_index(pts, radial, side)
                before, after = pts[k - 1], pts[(k + 1) % len(pts)]
                # The vertex's neighbours sit on one ray, either side of it: the outline crosses it radially.
                assert before.angular == pytest.approx(after.angular, abs=1e-12)
                assert before.radial - radial == pytest.approx(radial - after.radial, abs=1e-12) or                     after.radial - radial == pytest.approx(radial - before.radial, abs=1e-12)
                # The chord measure only reads the ray beside the vertex's own, well inside the TANG limit.
                assert tangent_error_deg(ctx, pts, k) < 1.0
            # Squashed: the circle through those ends would not fit, so the radial extent is clamped.
            assert max(p.radial for p in pts) - min(p.radial for p in pts) < 2 * ctx.px_to_radial(
                ctx.angular_to_px(1.0, radial))


def test_bead_with_side_touch_never_reaches_further_under_narrower_limits(cell_kwargs):
    for radial in (0.12, 0.45):
        for seed in range(10):
            wide = _bead(make_ctx(cell_kwargs, seed, side_touch_radial=radial, radial_limits=(-0.25, 1.25)))
            narrow = _bead(make_ctx(cell_kwargs, seed, side_touch_radial=radial, radial_limits=(0.0, 0.9)))
            assert max(p.radial for p in narrow) <= max(p.radial for p in wide) + 1e-12
            assert min(p.radial for p in narrow) >= min(p.radial for p in wide) - 1e-12


def test_bead_in_a_slot_is_a_circle_inside_the_slot(cell_kwargs):
    slot = [CellPoint(0.2, -0.4), CellPoint(0.2, 0.4), CellPoint(0.8, 0.4), CellPoint(0.8, -0.4)]
    for seed in range(5):
        ctx = make_ctx(cell_kwargs, seed, slot=slot)
        pts = _bead(ctx)
        assert Polygon([(p.angular, p.radial) for p in slot]).contains(Polygon([(p.angular, p.radial) for p in pts]))
        top, bottom = max(p.radial for p in pts), min(p.radial for p in pts)
        half_px = ctx.radial_to_px(top - bottom) / 2.0
        mid = (top + bottom) / 2.0
        assert ctx.angular_to_px(max(p.angular for p in pts), mid) == pytest.approx(half_px)
