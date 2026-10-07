import math
import random
import pytest
from shapely.geometry import Polygon
from motifs import MOTIFS, find_motif, safe_motif, motifs_for_categories
from motifs.geometry import MotifContext, CellPoint
from motifs.contract import MotifInstance, MotifError

def make_ctx(cell_kwargs, seed=7, **over):
    kw = {**cell_kwargs, "rng": random.Random(seed), **over}
    return MotifContext(**kw)

def slot_for(cell_kwargs):
    return [CellPoint(0.2, -0.4), CellPoint(0.2, 0.4), CellPoint(0.8, 0.4), CellPoint(0.8, -0.4)]

def all_entries():
    return MOTIFS + [safe_motif("botanical")]

def generate(entry, ctx, cell_kwargs):
    if "base" not in entry["roles"]:
        ctx.slot = slot_for(cell_kwargs)
    return entry["generator"](ctx)

@pytest.mark.parametrize("entry", all_entries(), ids=lambda e: e["name"])
def test_motif_is_deterministic(entry, cell_kwargs):
    a = generate(entry, make_ctx(cell_kwargs, 11), cell_kwargs)
    b = generate(entry, make_ctx(cell_kwargs, 11), cell_kwargs)
    assert [v.points for v in a.vectors] == [v.points for v in b.vectors]

@pytest.mark.parametrize("entry", all_entries(), ids=lambda e: e["name"])
def test_motif_respects_narrow_limits(entry, cell_kwargs):
    ctx = make_ctx(cell_kwargs, 3, radial_limits=(0.0, 1.0), angular_limits=0.5)
    inst = generate(entry, ctx, cell_kwargs)
    assert all(-0.03 <= p.radial <= 1.03 and abs(p.angular) <= 0.53 for v in inst.vectors for p in v.points)

@pytest.mark.parametrize("entry", all_entries(), ids=lambda e: e["name"])
def test_narrower_radial_limits_never_reach_further(entry, cell_kwargs):
    wide = generate(entry, make_ctx(cell_kwargs, 5, radial_limits=(-0.25, 1.25)), cell_kwargs)
    narrow = generate(entry, make_ctx(cell_kwargs, 5, radial_limits=(-0.1, 1.1)), cell_kwargs)
    hi = lambda inst: max(p.radial for v in inst.vectors for p in v.points) if inst.vectors else 0
    lo = lambda inst: min(p.radial for v in inst.vectors for p in v.points) if inst.vectors else 0
    assert hi(narrow) <= hi(wide) + 1e-9 and lo(narrow) >= lo(wide) - 1e-9

@pytest.mark.parametrize("entry", [e for e in all_entries() if e["slot_estimate"]], ids=lambda e: e["name"])
def test_declared_slot_is_present_at_default_size(entry, cell_kwargs):
    inst = generate(entry, make_ctx(cell_kwargs, 9), cell_kwargs)
    assert inst.declaration.slot is not None

def test_registry_lookup():
    assert find_motif("petal")["category"] == "botanical"
    assert find_motif("nope") is None
    assert {e["name"] for e in motifs_for_categories(["geometric"])} == {"diamond", "ring_band"}
    assert safe_motif("celtic")["name"] == "celtic_safe_band"

def test_diamond_requires_slot(cell_kwargs):
    with pytest.raises(MotifError):
        find_motif("diamond")["generator"](make_ctx(cell_kwargs))

def test_safe_band_spans_angular_limits(cell_kwargs):
    inst = safe_motif("botanical")["generator"](make_ctx(cell_kwargs, angular_limits=0.7))
    angs = {round(p.angular, 6) for p in inst.vectors[0].points}
    assert angs == {-0.7, 0.7}


def parent_slot(cell_kwargs, seed):
    parent = find_motif("petal")["generator"](make_ctx(cell_kwargs, seed, complexity=1.0))
    return parent.declaration.slot


def slot_polygon(slot):
    return Polygon([(p.angular, p.radial) for p in slot])


def outline_polygon(inst):
    return Polygon([(p.angular, p.radial) for p in inst.vectors[0].points])


def children_in_real_slots(cell_kwargs, name):
    """Yield (slot, instance) for every seed whose parent slot is big enough for the child."""
    for seed in range(25):
        slot = parent_slot(cell_kwargs, seed)
        if slot is None:
            continue
        ctx = make_ctx(cell_kwargs, seed, complexity=1.0)
        ctx.slot = slot
        try:
            yield slot, find_motif(name)["generator"](ctx)
        except MotifError as error:
            assert "does not fit slot" in str(error)


@pytest.mark.parametrize("name", ["petal", "diamond", "leaf"])
def test_slot_child_is_contained_in_the_slot_polygon(name, cell_kwargs):
    children = list(children_in_real_slots(cell_kwargs, name))
    assert len(children) >= 5
    for slot, inst in children:
        assert slot_polygon(slot).contains(outline_polygon(inst))


def test_petal_in_slot_stays_inside_slot_radial_range(cell_kwargs):
    children = 0
    for seed in range(25):
        slot = parent_slot(cell_kwargs, seed)
        if slot is None:
            continue
        ctx = make_ctx(cell_kwargs, seed, complexity=1.0, radial_limits=(-0.25, 1.25))
        ctx.slot = slot
        try:
            inst = find_motif("petal")["generator"](ctx)
        except MotifError:
            continue
        children += 1
        radials = [p.radial for p in inst.vectors[0].points]
        assert min(radials) >= min(p.radial for p in slot)
        assert max(radials) <= max(p.radial for p in slot)
        assert max(radials) <= 1.0
    assert children >= 5


@pytest.mark.parametrize("name", ["petal", "diamond", "leaf"])
def test_slot_two_pixels_wide_does_not_fit(name, cell_kwargs):
    ctx = make_ctx(cell_kwargs)
    half = ctx.px_to_angular(1.0, 0.5)
    ctx.slot = [CellPoint(0.2, -half), CellPoint(0.2, half), CellPoint(0.8, half), CellPoint(0.8, -half)]
    with pytest.raises(MotifError, match="does not fit slot"):
        find_motif(name)["generator"](ctx)


def test_petal_outline_is_closed_unique_and_mirror_symmetric(cell_kwargs):
    inst = find_motif("petal")["generator"](make_ctx(cell_kwargs, 3, complexity=1.0))
    vector = inst.vectors[0]
    pts = vector.points
    assert vector.closed
    assert all(a != b for a, b in zip(pts, pts[1:] + pts[:1]))
    for p in pts:
        assert min(math.hypot(p.radial - q.radial, -p.angular - q.angular) for q in pts) < 1e-9


def test_leaf_midrib_touches_outline(cell_kwargs):
    inst = find_motif("leaf")["generator"](make_ctx(cell_kwargs))
    assert inst.kind == "enclosing" and len(inst.vectors) == 2
    outline, midrib = inst.vectors
    assert midrib.points[0] == CellPoint(0.0, 0.0) and midrib.points[0] in outline.points
    assert midrib.points[-1] in outline.points


def test_ring_band_draws_overlap_in_shared_range(cell_kwargs):
    gen = find_motif("ring_band")["generator"]
    for seed in range(20):
        pts = gen(make_ctx(cell_kwargs, seed)).vectors[0].points
        rs = sorted({p.radial for p in pts})
        assert rs[0] <= 0.45 and rs[-1] >= 0.55


def test_stem_is_a_pure_reach(cell_kwargs):
    inst = find_motif("stem")["generator"](make_ctx(cell_kwargs))
    assert inst.vectors == [] and inst.kind == "open"
    assert inst.declaration.reach_ends[0].direction == "inward"


def test_leaf_midrib_is_dropped_when_its_halves_are_too_thin_to_colour(cell_kwargs):
    ctx = make_ctx(cell_kwargs, 7)
    ctx.slot = [CellPoint(0.2, -0.2), CellPoint(0.2, 0.2), CellPoint(0.8, 0.2), CellPoint(0.8, -0.2)]
    narrow = find_motif("leaf")["generator"](ctx)
    assert ctx.angular_to_px(0.2, 0.5) < ctx.min_white_space
    assert len(narrow.vectors) == 1 and narrow.vectors[0].closed

    wide_ctx = make_ctx(cell_kwargs, 7)
    wide_ctx.slot = slot_for(cell_kwargs)
    assert len(find_motif("leaf")["generator"](wide_ctx).vectors) == 2


def test_leaf_midrib_is_dropped_outside_a_slot_when_the_halves_are_too_thin(cell_kwargs):
    gen = find_motif("leaf")["generator"]
    thin = gen(make_ctx(cell_kwargs, 7, angular_limits=0.1))
    assert len(thin.vectors) == 1 and thin.vectors[0].closed
    assert len(gen(make_ctx(cell_kwargs, 7)).vectors) == 2


# ----- revision 2: side touch and ring fill ---------------------------------

SIDE_TOUCH_NAMES = {"petal", "leaf", "scallop", "ring_band", "botanical_safe_band"}


def has_vertex(inst, radial, angular, tol=1e-9):
    return any(
        abs(p.radial - radial) <= tol and abs(p.angular - angular) <= tol
        for p in inst.vectors[0].points
    )


def test_registry_declares_side_touch_on_every_entry():
    declared = {e["name"]: e["side_touch"] for e in all_entries()}
    assert declared == {
        "petal": True, "leaf": True, "scallop": True, "stem": False,
        "diamond": False, "ring_band": True, "botanical_safe_band": True,
    }


@pytest.mark.parametrize("name", ["petal", "leaf"])
def test_side_touch_puts_vertices_at_the_side_touch_radial(name, cell_kwargs):
    gen = find_motif(name)["generator"]
    for seed in range(15):
        for limit in (1.0, 0.6, 0.5):
            inst = gen(make_ctx(cell_kwargs, seed, complexity=1.0, angular_limits=limit, side_touch_radial=0.5))
            assert has_vertex(inst, 0.5, limit) and has_vertex(inst, 0.5, -limit)
            widest = max(abs(p.angular) for p in inst.vectors[0].points)
            assert widest <= limit + 1e-12


@pytest.mark.parametrize("entry", [e for e in all_entries() if e["side_touch"]], ids=lambda e: e["name"])
def test_every_side_touch_entry_meets_the_budget_at_the_side_touch_radial(entry, cell_kwargs):
    for seed in range(10):
        ctx = make_ctx(cell_kwargs, seed, complexity=1.0, angular_limits=0.5, side_touch_radial=0.5)
        inst = entry["generator"](ctx)
        assert has_vertex(inst, 0.5, 0.5) and has_vertex(inst, 0.5, -0.5)
        assert all(abs(p.angular) <= 0.5 + 1e-12 for v in inst.vectors for p in v.points)


def test_scallop_side_vertex_falls_back_to_the_nearest_end_of_its_side_edge(cell_kwargs):
    gen = find_motif("scallop")["generator"]
    for seed in range(10):
        plain = gen(make_ctx(cell_kwargs, seed)).vectors[0].points
        top = max(p.radial for p in plain)
        low_inst = gen(make_ctx(cell_kwargs, seed, side_touch_radial=0.05))
        high_inst = gen(make_ctx(cell_kwargs, seed, side_touch_radial=0.95))
        assert has_vertex(high_inst, top, 1.0) and has_vertex(high_inst, top, -1.0)
        assert has_vertex(low_inst, top - 0.2, 1.0) and has_vertex(low_inst, top - 0.2, -1.0)
        assert low_inst.vectors[0].points == plain and high_inst.vectors[0].points == plain


def test_petals_from_different_seeds_share_the_side_vertex(cell_kwargs):
    gen = find_motif("petal")["generator"]
    a = gen(make_ctx(cell_kwargs, 1, angular_limits=0.8, side_touch_radial=0.5))
    b = gen(make_ctx(cell_kwargs, 2, angular_limits=0.8, side_touch_radial=0.5))
    assert a.vectors[0].points != b.vectors[0].points
    for angular in (0.8, -0.8):
        assert has_vertex(a, 0.5, angular) and has_vertex(b, 0.5, angular)


def test_centre_and_divider_petals_meet_at_the_same_page_point(cell_kwargs):
    from motifs.geometry import cell_rotation_deg
    gen = find_motif("petal")["generator"]
    centre_ctx = make_ctx(cell_kwargs, 4, position="centre", angular_limits=0.6, side_touch_radial=0.5)
    divider_ctx = make_ctx(cell_kwargs, 8, position="divider", angular_limits=0.4, side_touch_radial=0.5)
    centre, divider = gen(centre_ctx), gen(divider_ctx)
    assert has_vertex(centre, 0.5, 0.6) and has_vertex(divider, 0.5, -0.4)
    right = centre_ctx.to_cartesian(CellPoint(0.5, 0.6), cell_rotation_deg(0, 12, "centre"))
    left = divider_ctx.to_cartesian(CellPoint(0.5, -0.4), cell_rotation_deg(0, 12, "divider"))
    assert math.hypot(right[0] - left[0], right[1] - left[1]) < 1e-6


def test_slot_children_ignore_side_touch(cell_kwargs):
    for name in ("petal", "leaf"):
        for seed in range(25):
            slot = parent_slot(cell_kwargs, seed)
            if slot is None:
                continue
            plain_ctx = make_ctx(cell_kwargs, seed, complexity=1.0)
            touch_ctx = make_ctx(cell_kwargs, seed, complexity=1.0, side_touch_radial=0.5)
            plain_ctx.slot = touch_ctx.slot = slot
            try:
                plain = find_motif(name)["generator"](plain_ctx)
            except MotifError:
                continue
            touched = find_motif(name)["generator"](touch_ctx)
            assert [v.points for v in plain.vectors] == [v.points for v in touched.vectors]


@pytest.mark.parametrize("entry", all_entries(), ids=lambda e: e["name"])
def test_side_touch_is_deterministic(entry, cell_kwargs):
    a = generate(entry, make_ctx(cell_kwargs, 11, side_touch_radial=0.45), cell_kwargs)
    b = generate(entry, make_ctx(cell_kwargs, 11, side_touch_radial=0.45), cell_kwargs)
    assert [v.points for v in a.vectors] == [v.points for v in b.vectors]


def test_petal_tips_reach_the_next_ring_with_default_limits(cell_kwargs):
    gen = find_motif("petal")["generator"]
    for seed in range(40):
        for touch in (None, 0.5):
            inst = gen(make_ctx(cell_kwargs, seed, side_touch_radial=touch))
            assert max(p.radial for p in inst.vectors[0].points) >= 0.95


def test_leaf_apex_reaches_the_ring_boundary_with_default_limits(cell_kwargs):
    gen = find_motif("leaf")["generator"]
    for seed in range(40):
        inst = gen(make_ctx(cell_kwargs, seed))
        assert max(p.radial for p in inst.vectors[0].points) >= 1.0 - 1e-12


def test_ring_fill_overflow_allowances():
    assert find_motif("petal")["max_overflow_inward"] == 0.5
    assert find_motif("petal")["max_overflow_outward"] == 0.3
    assert find_motif("leaf")["max_overflow_outward"] == 0.2
    assert find_motif("scallop")["max_overflow_inward"] == 0.4


def test_petal_and_scallop_dip_below_the_ring_with_room_to(cell_kwargs):
    wide = (-0.5, 1.3)
    petal_dips = [min(p.radial for p in find_motif("petal")["generator"](
        make_ctx(cell_kwargs, s, radial_limits=wide)).vectors[0].points) for s in range(60)]
    scallop_dips = [min(p.radial for p in find_motif("scallop")["generator"](
        make_ctx(cell_kwargs, s, radial_limits=wide)).vectors[0].points) for s in range(60)]
    assert min(petal_dips) < -0.25 and min(petal_dips) >= -0.5
    assert min(scallop_dips) < -0.3 and min(scallop_dips) >= -0.4


@pytest.mark.parametrize("name", ["petal", "diamond", "leaf"])
def test_slot_child_stays_within_radial_limits_when_the_slot_dips_below_them(name, cell_kwargs):
    # A deep-dipping petal declares a slot that reaches below radial 0, but its child is placed with (0, 1).
    for seed in range(10):
        ctx = make_ctx(cell_kwargs, seed)
        ctx.slot = [CellPoint(-0.2, -0.4), CellPoint(-0.2, 0.4), CellPoint(0.8, 0.4), CellPoint(0.8, -0.4)]
        inst = find_motif(name)["generator"](ctx)
        assert min(p.radial for v in inst.vectors for p in v.points) >= 0.0
