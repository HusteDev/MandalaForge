import pytest
from motifs.geometry import CellPoint, SmartVector, MotifContext
from motifs.contract import (
    MotifAnalyzer,
    MotifError,
    ReachEnd,
    build_instance,
    measure_footprint,
    measure_overflow,
    measure_slot,
)


def closed_box(lo, hi, w):
    return SmartVector([CellPoint(lo, -w), CellPoint(lo, w), CellPoint(hi, w), CellPoint(hi, -w)], closed=True)


def test_closed_box_is_enclosing(cell_kwargs):
    inst = build_instance(MotifContext(**cell_kwargs), [closed_box(0.1, 0.9, 0.6)])
    assert inst.kind == "enclosing"
    assert inst.declaration.base_point == CellPoint(0.1, -0.6) or inst.declaration.base_point == CellPoint(0.1, 0.6)


def test_open_end_without_reach_is_rejected(cell_kwargs):
    with pytest.raises(MotifError, match="open end"):
        build_instance(MotifContext(**cell_kwargs), [SmartVector([CellPoint(0.2, 0.0), CellPoint(0.8, 0.0)])])


def test_open_end_declared_as_reach_is_accepted(cell_kwargs):
    reach = ReachEnd(CellPoint(0.0, 0.0), "inward", 40.0)
    inst = build_instance(MotifContext(**cell_kwargs),
                          [closed_box(0.0, 0.9, 0.6)], reach_ends=[reach])
    assert inst.declaration.reach_ends == [reach]


def test_radial_limit_violation_is_rejected(cell_kwargs):
    ctx = MotifContext(**cell_kwargs, radial_limits=(0.0, 1.0))
    with pytest.raises(MotifError, match="radial"):
        build_instance(ctx, [closed_box(0.1, 1.2, 0.6)])


def test_angular_limit_violation_is_rejected(cell_kwargs):
    ctx = MotifContext(**cell_kwargs, angular_limits=0.5)
    with pytest.raises(MotifError, match="angular"):
        build_instance(ctx, [closed_box(0.1, 0.9, 0.8)])


def test_slot_is_inset_and_clear(cell_kwargs):
    ctx = MotifContext(**cell_kwargs)
    outline = closed_box(0.0, 1.0, 1.0).points
    slot = measure_slot(ctx, outline)
    assert slot is not None
    assert all(0.15 < p.radial < 0.85 for p in slot)


def test_slot_vanishes_when_margin_exceeds_shape(cell_kwargs):
    ctx = MotifContext(**{**cell_kwargs, "min_white_space": 50.0})
    assert measure_slot(ctx, closed_box(0.0, 1.0, 1.0).points) is None


def test_pure_reach_motif_has_no_vectors(cell_kwargs):
    reach = ReachEnd(CellPoint(0.0, 0.0), "outward", 30.0)
    inst = build_instance(MotifContext(**cell_kwargs), [], reach_ends=[reach])
    assert inst.kind == "open"
    assert inst.declaration.footprint == [CellPoint(0.0, 0.0)]
    assert inst.declaration.base_point == CellPoint(0.0, 0.0)
    assert (inst.declaration.overflow_inward, inst.declaration.overflow_outward) == (0.0, 0.0)


def test_no_vectors_and_no_reach_is_rejected(cell_kwargs):
    with pytest.raises(MotifError):
        build_instance(MotifContext(**cell_kwargs), [])


def test_reach_end_rejects_unknown_direction_and_style():
    with pytest.raises(MotifError):
        ReachEnd(CellPoint(0.0, 0.0), "sideways", 10.0)
    with pytest.raises(MotifError):
        ReachEnd(CellPoint(0.0, 0.0), "inward", 10.0, style="curly")


def test_open_ends_resting_on_another_vector_are_accepted(cell_kwargs):
    ctx = MotifContext(**cell_kwargs)
    spine = SmartVector([CellPoint(0.1, 0.0), CellPoint(0.9, 0.0)])
    inst = build_instance(ctx, [closed_box(0.1, 0.9, 0.6), spine])
    assert inst.kind == "enclosing"


def test_open_end_touching_non_adjacent_segment_of_own_vector_is_accepted(cell_kwargs):
    ctx = MotifContext(**cell_kwargs)
    loop = SmartVector([CellPoint(0.3, 0.0), CellPoint(0.3, 0.5), CellPoint(0.7, 0.5),
                        CellPoint(0.7, 0.0), CellPoint(0.3, 0.0)])
    # Each end lies on a segment of the same vector that is neither its own nor the next one.
    reach = ReachEnd(CellPoint(0.5, 0.5), "outward", 10.0)
    inst = build_instance(ctx, [loop], reach_ends=[reach])
    assert inst.kind == "open"


def test_open_end_on_adjacent_segment_only_is_floating(cell_kwargs):
    ctx = MotifContext(**cell_kwargs)
    line = SmartVector([CellPoint(0.2, 0.0), CellPoint(0.5, 0.0), CellPoint(0.8, 0.0)])
    issues = MotifAnalyzer(ctx).analyze(
        build_instance(ctx, [line], reach_ends=[ReachEnd(CellPoint(0.2, 0.0), "inward", 10.0),
                                                ReachEnd(CellPoint(0.8, 0.0), "outward", 10.0)]))
    assert issues == []
    with pytest.raises(MotifError, match="open end"):
        build_instance(ctx, [line], reach_ends=[ReachEnd(CellPoint(0.2, 0.0), "inward", 10.0)])


def _cross(half_r, half_a):
    return [
        SmartVector([CellPoint(0.5 - half_r, -half_a), CellPoint(0.5 + half_r, half_a)]),
        SmartVector([CellPoint(0.5 - half_r, half_a), CellPoint(0.5 + half_r, -half_a)]),
    ]


def _reaches(vectors):
    return [ReachEnd(v.points[i], "inward", 10.0) for v in vectors for i in (0, -1)]


def test_tight_crossing_creates_tiny_space_and_is_rejected(cell_kwargs):
    ctx = MotifContext(**cell_kwargs)
    vectors = _cross(0.05, 0.1)
    with pytest.raises(MotifError, match="whitespace"):
        build_instance(ctx, vectors, reach_ends=_reaches(vectors))


def test_wide_crossing_is_accepted(cell_kwargs):
    ctx = MotifContext(**cell_kwargs)
    vectors = _cross(0.3, 0.5)
    inst = build_instance(ctx, vectors, reach_ends=_reaches(vectors))
    assert inst.kind == "open"


def test_slot_too_close_to_a_vector_is_rejected(cell_kwargs):
    ctx = MotifContext(**cell_kwargs)
    outline = closed_box(0.0, 1.0, 1.0).points
    with pytest.raises(MotifError, match="Slot"):
        build_instance(ctx, [closed_box(0.0, 1.0, 1.0), closed_box(0.4, 0.6, 0.1)], slot_outline=outline)


def test_clear_slot_is_recorded_on_declaration(cell_kwargs):
    ctx = MotifContext(**cell_kwargs)
    box = closed_box(0.0, 1.0, 1.0)
    inst = build_instance(ctx, [box], slot_outline=box.points)
    assert inst.declaration.slot == measure_slot(ctx, box.points)
    assert inst.declaration.slot is not None


def test_overflow_is_measured_beyond_zero_and_one():
    vectors = [closed_box(-0.2, 1.3, 0.5)]
    assert measure_overflow(vectors) == pytest.approx((0.2, 0.3))
    assert measure_overflow([closed_box(0.1, 0.9, 0.5)]) == (0.0, 0.0)


def test_footprint_is_convex_hull():
    interior = SmartVector([CellPoint(0.5, 0.0), CellPoint(0.6, 0.1)])
    hull = measure_footprint([closed_box(0.1, 0.9, 0.6), interior])
    assert set(hull) == {CellPoint(0.1, -0.6), CellPoint(0.1, 0.6), CellPoint(0.9, 0.6), CellPoint(0.9, -0.6)}
