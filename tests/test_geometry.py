import math
from motifs.geometry import CellPoint, SmartVector, MotifContext, cell_rotation_deg

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
