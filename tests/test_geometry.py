import math

import pytest

from motifs.geometry import (
    CellPoint, SmartVector, MotifContext, cell_rotation_deg, quad_points,
    cubic_points, page_arc_points, page_circle_points, insert_vertex_on_outline,
)

def test_to_cartesian_does_not_clamp_overflow(cell_kwargs):
    ctx = MotifContext(**cell_kwargs)
    x, y = ctx.to_cartesian(CellPoint(1.25, 0.0))
    assert math.isclose(math.hypot(x - 306, y - 306), 175.0, abs_tol=1e-6)

def test_rotation_moves_centreline(cell_kwargs):
    ctx = MotifContext(**cell_kwargs)
    x, y = ctx.to_cartesian(CellPoint(0.5, 0.0), rotation_deg=90.0)
    assert math.isclose(x, 306.0, abs_tol=1e-6) and math.isclose(y, 436.0, abs_tol=1e-6)

def test_polyline_subdivides_arc(cell_kwargs):
    ctx = MotifContext(**cell_kwargs)
    pts = ctx.polyline(SmartVector([CellPoint(0.5, -1.0), CellPoint(0.5, 1.0)]))
    assert len(pts) >= 8
    assert all(math.isclose(math.hypot(x - 306, y - 306), 130.0, abs_tol=0.05) for x, y in pts)

def test_cell_rotation_positions():
    assert cell_rotation_deg(2, 12, "centre") == 60.0
    assert cell_rotation_deg(2, 12, "divider") == 75.0

def test_quad_points_are_not_clamped():
    pts = quad_points(CellPoint(-0.2, 0.0), CellPoint(0.5, 1.2), CellPoint(1.2, 0.0))
    assert len(pts) == 9
    assert pts[0] == CellPoint(-0.2, 0.0) and pts[-1] == CellPoint(1.2, 0.0)
    assert not all(0.0 <= p.radial <= 1.0 for p in pts)
    assert pts[1].radial < 0.0  # interior sample below the inner boundary survives


def test_ring_rng_is_fresh_after_replace(cell_kwargs):
    from dataclasses import replace
    ctx = MotifContext(**cell_kwargs, ring_stream_seed=99)
    first = ctx.ring_rng.random()
    assert replace(ctx).ring_rng.random() == first


def test_cubic_points_ends_and_midpoint():
    a, b, c, d = CellPoint(0, 0), CellPoint(0.2, 1), CellPoint(0.8, 1), CellPoint(1, 0)
    pts = cubic_points(a, b, c, d, steps=4)
    assert len(pts) == 5 and pts[0] == a and pts[-1] == d
    assert pts[2].radial == pytest.approx(0.5) and pts[2].angular == pytest.approx(0.75)


def test_page_circle_is_round_on_the_page(cell_kwargs):
    ctx = MotifContext(**cell_kwargs)
    centre = CellPoint(0.5, 0.0)
    cx, cy = ctx.to_cartesian(centre)
    for p in page_circle_points(ctx, centre, 8.0):
        x, y = ctx.to_cartesian(p)
        assert math.hypot(x - cx, y - cy) == pytest.approx(8.0, abs=0.3)


def test_page_arc_points_directions(cell_kwargs):
    ctx = MotifContext(**cell_kwargs)
    centre = CellPoint(0.5, 0.0)
    out = page_arc_points(ctx, centre, 8.0, 0.0, 90.0, steps=4)
    assert len(out) == 5
    assert out[0].radial > centre.radial and out[0].angular == pytest.approx(0.0)
    assert out[-1].radial == pytest.approx(centre.radial) and out[-1].angular > 0.0


def test_page_circle_is_closed_without_repeat(cell_kwargs):
    ctx = MotifContext(**cell_kwargs)
    pts = page_circle_points(ctx, CellPoint(0.5, 0.0), 8.0, steps=24)
    assert len(pts) == 24 and pts[0] != pts[-1]


def test_insert_vertex_on_outline():
    square = [CellPoint(0, -1), CellPoint(0, 1), CellPoint(1, 1), CellPoint(1, -1)]
    out = insert_vertex_on_outline(square, True, CellPoint(0.5, 1))
    assert out == [CellPoint(0, -1), CellPoint(0, 1), CellPoint(0.5, 1), CellPoint(1, 1), CellPoint(1, -1)]
    assert insert_vertex_on_outline(out, True, CellPoint(0.5, 1)) == out


def test_insert_vertex_on_closing_segment():
    square = [CellPoint(0, -1), CellPoint(0, 1), CellPoint(1, 1), CellPoint(1, -1)]
    out = insert_vertex_on_outline(square, True, CellPoint(0.5, -1))
    assert out[-1] == CellPoint(0.5, -1) and len(out) == 5
    assert insert_vertex_on_outline(square, False, CellPoint(0.5, -1)) == square


def test_to_cell_inverts_to_cartesian(cell_kwargs):
    ctx = MotifContext(**cell_kwargs)
    for point in (CellPoint(0.0, 0.0), CellPoint(0.37, -1.0), CellPoint(1.25, 0.6), CellPoint(-0.2, 0.99)):
        for rotation in (0.0, 47.5, 200.0):
            back = ctx.to_cell(ctx.to_cartesian(point, rotation), rotation)
            assert back.radial == pytest.approx(point.radial, abs=1e-12)
            assert back.angular == pytest.approx(point.angular, abs=1e-12)
