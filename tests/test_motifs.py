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
    if entry["seams"]:
        # A seam motif needs the full angular budget (spec 4.1); it refuses a narrower one.
        with pytest.raises(MotifError):
            generate(entry, ctx, cell_kwargs)
        return
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
    assert {e["name"] for e in motifs_for_categories(["geometric"])} == {"diamond", "band"}
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


@pytest.mark.parametrize("name", ["band", "scallop"])
def test_seam_ends_sit_on_the_cell_edges(name, cell_kwargs):
    inst = find_motif(name)["generator"](make_ctx(cell_kwargs, 4, ring_stream_seed=77))
    ends = [p for v in inst.vectors if not v.closed for p in (v.points[0], v.points[-1])]
    assert ends and all(abs(p.angular) == 1.0 for p in ends)


@pytest.mark.parametrize("name", ["band", "scallop"])
def test_every_cell_draws_the_same_seams(name, cell_kwargs):
    a = find_motif(name)["generator"](make_ctx(cell_kwargs, 1, ring_stream_seed=77))
    b = find_motif(name)["generator"](make_ctx(cell_kwargs, 2, ring_stream_seed=77))
    assert [v.points for v in a.vectors] == [v.points for v in b.vectors]


def test_ring_band_alias():
    assert find_motif("ring_band") is find_motif("band")


@pytest.mark.parametrize("name", ["band", "scallop"])
def test_seam_motifs_declare_seams_and_no_overflow(name):
    entry = find_motif(name)
    assert entry["seams"] and entry["spans_cell"] and entry["side_touch_heights"] == ()
    assert entry["max_overflow_inward"] == 0.0 and entry["max_overflow_outward"] == 0.0


def test_band_arcs_are_constant_radial_in_their_ranges(cell_kwargs):
    for stream in range(30):
        inst = find_motif("band")["generator"](make_ctx(cell_kwargs, 1, ring_stream_seed=stream))
        arcs = [v for v in inst.vectors if not v.closed]
        assert len(arcs) == 2
        (r1,), (r2,) = ({p.radial for p in arc.points} for arc in arcs)
        assert 0.25 <= r1 <= 0.45 and 0.55 <= r2 <= 0.75
        for arc in arcs:
            assert arc.points[0].angular == -1.0 and arc.points[-1].angular == 1.0


def test_band_lens_ties_the_arcs_at_exact_shared_vertices(cell_kwargs):
    for stream in range(30):
        ctx = make_ctx(cell_kwargs, 1, ring_stream_seed=stream)
        inst = find_motif("band")["generator"](ctx)
        inner, outer = (v for v in inst.vectors if not v.closed)
        (lens,) = (v for v in inst.vectors if v.closed)
        r1, r2 = inner.points[0].radial, outer.points[0].radial
        assert CellPoint(r1, 0.0) in inner.points and CellPoint(r1, 0.0) in lens.points
        assert CellPoint(r2, 0.0) in outer.points and CellPoint(r2, 0.0) in lens.points
        # Mirror-symmetric about the axis, and between the arcs.
        key = lambda sign: sorted((round(p.radial, 12), round(sign * p.angular, 12) + 0.0) for p in lens.points)
        assert key(1) == key(-1)
        assert all(r1 <= p.radial <= r2 for p in lens.points)


def test_band_lens_leaves_both_faces_colourable(cell_kwargs):
    for stream in range(30):
        ctx = make_ctx(cell_kwargs, 1, ring_stream_seed=stream)
        inst = find_motif("band")["generator"](ctx)
        (lens,) = (v for v in inst.vectors if v.closed)
        widest = max(lens.points, key=lambda p: p.angular)
        need = ctx.clearance_px()
        # Across the lens, and across the face between this lens and the next one over the seam.
        assert ctx.angular_to_px(2 * widest.angular, widest.radial) >= need - 1e-9
        assert ctx.angular_to_px(2 * (1.0 - widest.angular), widest.radial) >= need - 1e-9


def test_band_lens_falls_back_to_an_even_split_when_the_cell_is_too_narrow(cell_kwargs):
    ctx = make_ctx(cell_kwargs, 1, ring_stream_seed=3, wedge_angle=6.0)
    assert ctx.cell_width_px(0.5) < 2 * ctx.clearance_px()
    (lens,) = (v for v in find_motif("band")["generator"](ctx).vectors if v.closed)
    assert max(p.angular for p in lens.points) == pytest.approx(0.5)


def test_scallop_lobe_is_a_page_space_circle_through_its_ends_and_apex(cell_kwargs):
    for stream in range(30):
        ctx = make_ctx(cell_kwargs, 1, ring_stream_seed=stream)
        (lobe,) = find_motif("scallop")["generator"](ctx).vectors
        rb = lobe.points[0].radial
        assert lobe.points[0] == CellPoint(rb, -1.0) and lobe.points[-1] == CellPoint(rb, 1.0)
        assert 0.3 <= rb <= 0.5
        apex = max(lobe.points, key=lambda p: abs(p.radial - rb))
        assert apex.angular == pytest.approx(0.0, abs=1e-9)
        assert 0.0 < abs(apex.radial - rb) <= 0.45 + 1e-9
        pts = [ctx.to_cartesian(p) for p in lobe.points]
        # The circle through the two ends and the apex; every sample lies on it.
        (ax, ay), (bx, by), (cx, cy) = pts[0], ctx.to_cartesian(apex), pts[-1]
        d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
        ux = ((ax**2 + ay**2) * (by - cy) + (bx**2 + by**2) * (cy - ay) + (cx**2 + cy**2) * (ay - by)) / d
        uy = ((ax**2 + ay**2) * (cx - bx) + (bx**2 + by**2) * (ax - cx) + (cx**2 + cy**2) * (bx - ax)) / d
        radius = math.hypot(ax - ux, ay - uy)
        assert all(abs(math.hypot(x - ux, y - uy) - radius) < 1e-6 for x, y in pts)


def test_scallop_draws_both_directions(cell_kwargs):
    directions = set()
    for stream in range(30):
        (lobe,) = find_motif("scallop")["generator"](make_ctx(cell_kwargs, 1, ring_stream_seed=stream)).vectors
        directions.add(max(p.radial for p in lobe.points) > lobe.points[0].radial + 1e-9)
    assert directions == {True, False}


def test_scallop_lobe_shrinks_to_stay_inside_a_narrow_cell(cell_kwargs):
    # 24 divisions on a ring-0-like geometry: an unclamped outward lobe overhangs the cell edge.
    for stream in range(30):
        ctx = make_ctx(cell_kwargs, 1, ring_stream_seed=stream, wedge_angle=15.0,
                       inner_radius=20.0, outer_radius=82.0)
        (lobe,) = find_motif("scallop")["generator"](ctx).vectors
        assert all(abs(p.angular) <= 1.0 + 1e-9 for p in lobe.points)


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

def has_vertex(inst, radial, angular, tol=1e-9):
    return any(
        abs(p.radial - radial) <= tol and abs(p.angular - angular) <= tol
        for p in inst.vectors[0].points
    )


def test_registry_declares_touch_heights_and_seams():
    for entry in MOTIFS + [safe_motif("botanical")]:
        assert set(entry["side_touch_heights"]) <= {"base", "mid"} and "side_touch" not in entry
        assert isinstance(entry["seams"], bool) and isinstance(entry["embellishments"], tuple)


def test_registry_phase_one_touch_heights():
    declared = {e["name"]: tuple(e["side_touch_heights"]) for e in all_entries()}
    assert declared == {
        "petal": ("base", "mid"), "leaf": ("base", "mid"), "scallop": (), "stem": (),
        "diamond": (), "band": (), "botanical_safe_band": ("mid",),
    }
    assert {e["name"] for e in all_entries() if e["seams"]} == {"band", "scallop"}
    assert all(e["embellishments"] == () for e in all_entries())


@pytest.mark.parametrize("name", ["petal", "leaf"])
def test_side_touch_puts_vertices_at_the_side_touch_radial(name, cell_kwargs):
    gen = find_motif(name)["generator"]
    for seed in range(15):
        for limit in (1.0, 0.6, 0.5):
            inst = gen(make_ctx(cell_kwargs, seed, complexity=1.0, angular_limits=limit, side_touch_radial=0.5))
            assert has_vertex(inst, 0.5, limit) and has_vertex(inst, 0.5, -limit)
            widest = max(abs(p.angular) for p in inst.vectors[0].points)
            assert widest <= limit + 1e-12


@pytest.mark.parametrize("entry", [e for e in all_entries() if e["side_touch_heights"]], ids=lambda e: e["name"])
def test_every_side_touch_entry_meets_the_budget_at_the_side_touch_radial(entry, cell_kwargs):
    for seed in range(10):
        ctx = make_ctx(cell_kwargs, seed, complexity=1.0, angular_limits=0.5, side_touch_radial=0.5)
        inst = entry["generator"](ctx)
        assert has_vertex(inst, 0.5, 0.5) and has_vertex(inst, 0.5, -0.5)
        assert all(abs(p.angular) <= 0.5 + 1e-12 for v in inst.vectors for p in v.points)


@pytest.mark.parametrize("name", ["botanical_safe_band"])
def test_band_side_edges_contain_the_side_touch_radial_strictly(name, cell_kwargs):
    # Spec 13.2 (fix round): every band's side edge contains the ring's side-touch radial, so bands drawn
    # from different sequence entries share the side vertex.
    entry = find_motif(name) or safe_motif("botanical")
    for radial in (0.35, 0.4, 0.45, 0.5, 0.55, 0.6):
        for seed in range(20):
            inst = entry["generator"](make_ctx(cell_kwargs, seed, side_touch_radial=radial))
            for limit in (1.0, -1.0):
                side = [p.radial for p in inst.vectors[0].points if abs(p.angular - limit) <= 1e-12]
                assert min(side) < radial < max(side), (radial, seed, side)
                assert has_vertex(inst, radial, limit)


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
    assert find_motif("scallop")["max_overflow_inward"] == 0.0


def test_petal_dips_below_the_ring_with_room_to(cell_kwargs):
    wide = (-0.5, 1.3)
    petal_dips = [min(p.radial for p in find_motif("petal")["generator"](
        make_ctx(cell_kwargs, s, radial_limits=wide)).vectors[0].points) for s in range(60)]
    assert min(petal_dips) < -0.25 and min(petal_dips) >= -0.5


@pytest.mark.parametrize("name", ["petal", "diamond", "leaf"])
def test_slot_child_stays_within_radial_limits_when_the_slot_dips_below_them(name, cell_kwargs):
    # A deep-dipping petal declares a slot that reaches below radial 0, but its child is placed with (0, 1).
    for seed in range(10):
        ctx = make_ctx(cell_kwargs, seed)
        ctx.slot = [CellPoint(-0.2, -0.4), CellPoint(-0.2, 0.4), CellPoint(0.8, 0.4), CellPoint(0.8, -0.4)]
        inst = find_motif(name)["generator"](ctx)
        assert min(p.radial for v in inst.vectors for p in v.points) >= 0.0


# ----- motif aesthetics: lotus petal, curved leaf, concave diamond ----------

from qa_patterns import max_turn_deg, tangent_error_deg


def test_tangent_error_is_zero_along_a_radial_line_and_ninety_across_it(cell_kwargs):
    ctx = make_ctx(cell_kwargs)
    radial_line = [CellPoint(0.2, 0.3), CellPoint(0.5, 0.3), CellPoint(0.8, 0.3)]
    across = [CellPoint(0.5, -0.2), CellPoint(0.5, 0.0), CellPoint(0.5, 0.2)]
    assert tangent_error_deg(ctx, radial_line, 1) == pytest.approx(0.0, abs=1e-9)
    assert tangent_error_deg(ctx, across, 1) == pytest.approx(90.0, abs=0.1)


def test_max_turn_reads_corners_on_the_traced_polyline_and_honours_skip(cell_kwargs):
    ctx = make_ctx(cell_kwargs)
    square = [CellPoint(0.2, -0.3), CellPoint(0.2, 0.3), CellPoint(0.8, 0.3), CellPoint(0.8, -0.3)]
    assert 80.0 < max_turn_deg(ctx, square, True, set()) < 100.0
    # An open run never turns at its ends; skipping every corner leaves only the gentle subdivision bends.
    assert max_turn_deg(ctx, square, True, {0, 1, 2, 3}) < 10.0
    assert max_turn_deg(ctx, square[:2], False, set()) < 10.0


@pytest.mark.parametrize("name", ["petal", "leaf"])
@pytest.mark.parametrize("radial", [0.12, 0.45])
def test_side_touch_vertex_is_smooth(name, radial, cell_kwargs):
    for seed in range(12):
        ctx = make_ctx(cell_kwargs, seed, side_touch_radial=radial)
        outline = find_motif(name)["generator"](ctx).vectors[0].points
        i = next(k for k, p in enumerate(outline) if p.radial == radial and p.angular == 1.0)
        assert tangent_error_deg(ctx, outline, i) <= 10.0


@pytest.mark.parametrize("name", ["petal", "leaf"])
def test_outline_has_no_corners_but_its_tip_and_base(name, cell_kwargs):
    for seed in range(12):
        ctx = make_ctx(cell_kwargs, seed, side_touch_radial=0.12)
        pts = find_motif(name)["generator"](ctx).vectors[0].points
        tip = max(range(len(pts)), key=lambda k: pts[k].radial)
        base = min(range(len(pts)), key=lambda k: (pts[k].radial, abs(pts[k].angular)))
        assert max_turn_deg(ctx, pts, True, {tip, base}) <= 35.0


@pytest.mark.parametrize("name", ["petal", "leaf"])
@pytest.mark.parametrize("touch", [None, 0.45])
def test_plain_and_mid_touch_outlines_have_no_corners_but_tip_and_base(name, touch, cell_kwargs):
    for seed in range(12):
        ctx = make_ctx(cell_kwargs, seed, complexity=1.0, side_touch_radial=touch)
        pts = find_motif(name)["generator"](ctx).vectors[0].points
        tip = max(range(len(pts)), key=lambda k: pts[k].radial)
        base = min(range(len(pts)), key=lambda k: (pts[k].radial, abs(pts[k].angular)))
        assert max_turn_deg(ctx, pts, True, {tip, base}) <= 35.0


def test_base_touch_narrows_above_the_vertex(cell_kwargs):
    ctx = make_ctx(cell_kwargs, 3, side_touch_radial=0.12)
    pts = find_motif("petal")["generator"](ctx).vectors[0].points
    assert all(abs(p.angular) < 1.0 for p in pts if p.radial > 0.12 + 1e-9)


def test_petal_belly_is_its_widest_vertex_at_a_drawn_fraction_of_its_length(cell_kwargs):
    fractions = []
    for seed in range(40):
        pts = find_motif("petal")["generator"](make_ctx(cell_kwargs, seed)).vectors[0].points
        base, tip = min(p.radial for p in pts), max(p.radial for p in pts)
        belly = max(pts, key=lambda p: (p.angular, -p.radial))
        fractions.append((belly.radial - base) / (tip - base))
    assert all(0.3 - 1e-9 <= f <= 0.6 + 1e-9 for f in fractions)
    assert max(fractions) - min(fractions) > 0.15


def test_diamond_has_both_variants(cell_kwargs):
    kinds = set()
    for seed in range(20):
        ctx = make_ctx(cell_kwargs, seed); ctx.slot = slot_for(cell_kwargs)
        kinds.add(len(find_motif("diamond")["generator"](ctx).vectors[0].points) > 4)
    assert kinds == {True, False}


def test_concave_diamond_edges_bow_inside_the_straight_diamond(cell_kwargs):
    for seed in range(20):
        ctx = make_ctx(cell_kwargs, seed); ctx.slot = slot_for(cell_kwargs)
        pts = find_motif("diamond")["generator"](ctx).vectors[0].points
        if len(pts) == 4:
            continue
        hull = Polygon([(p.angular, p.radial) for p in pts]).convex_hull
        shape = Polygon([(p.angular, p.radial) for p in pts])
        assert shape.is_valid and shape.area < 0.9 * hull.area
        # Every sample keeps to its own side of the axis, so the two sides never cross.
        tips = [k for k, p in enumerate(pts) if p.angular == 0.0]
        assert len(tips) == 2


def test_concave_diamond_bow_is_a_drawn_share_of_its_half_width(cell_kwargs):
    from motifs.geometric import DIAMOND_BOW_RANGE, _diamond
    for bow in (DIAMOND_BOW_RANGE[0], 0.25, DIAMOND_BOW_RANGE[1]):
        pts = _diamond(0.5, 0.3, 0.4, bow)
        lower = [p for p in pts if p.angular >= 0 and p.radial <= 0.5]
        # Interpolate the lower-right edge at the radial halfway from the tip (0.2) to the side vertex (0.5).
        a, b = next((p, q) for p, q in zip(lower, lower[1:]) if p.radial <= 0.35 <= q.radial)
        angular = a.angular + (b.angular - a.angular) * (0.35 - a.radial) / (b.radial - a.radial)
        assert (0.2 - angular) / 0.4 == pytest.approx(bow, abs=0.02)


def test_stems_are_never_drawn_straight_by_choice(cell_kwargs):
    stem = find_motif("stem")["generator"]
    styles = {stem(make_ctx(cell_kwargs, s)).declaration.reach_ends[0].style for s in range(40)}
    assert styles == {"bow", "s", "wavy"}


# ----- a placed diamond leaves room for the pen --------------------------------

from topology_validator import MIN_REGION_AREA_PX2, PEN_RADIUS_PX
import motifs.geometric as geometric_module


def _colourable(ctx, instance):
    """The validator's own face rule: area at least the floor, and non-empty eroded by the pen radius."""
    polygon = Polygon(ctx.polyline(instance.vectors[0]))
    return polygon.area >= MIN_REGION_AREA_PX2 and not polygon.buffer(-PEN_RADIUS_PX).is_empty


@pytest.mark.parametrize("depth", [(0.4, 0.6), (0.38, 0.62), (0.35, 0.65)])
def test_a_drawn_diamond_is_wide_enough_to_colour(depth, cell_kwargs):
    drawn = 0
    for seed in range(80):
        ctx = make_ctx(cell_kwargs, seed, stroke_width=2.0)
        ctx.slot = [CellPoint(depth[0], -0.25), CellPoint(depth[0], 0.25),
                    CellPoint(depth[1], 0.25), CellPoint(depth[1], -0.25)]
        try:
            inst = find_motif("diamond")["generator"](ctx)
        except MotifError:
            continue
        drawn += 1
        assert _colourable(ctx, inst), (seed, Polygon(ctx.polyline(inst.vectors[0])).bounds)
    assert drawn > 0 or depth == (0.4, 0.6)  # the smallest slot may refuse every diamond


def test_a_thin_concave_diamond_falls_back_to_the_straight_one(cell_kwargs, monkeypatch):
    calls = []
    real = geometric_module._holds_pen
    monkeypatch.setattr(geometric_module, "_holds_pen", lambda ctx, outline: calls.append(real(ctx, outline)) or calls[-1])
    fell_back = 0
    for half_width in (0.2, 0.21, 0.22):  # a slot just big enough for a straight diamond, too small for a bowed one
        for seed in range(60):
            ctx = make_ctx(cell_kwargs, seed, stroke_width=2.5)
            ctx.slot = [CellPoint(0.39, -half_width), CellPoint(0.39, half_width),
                        CellPoint(0.61, half_width), CellPoint(0.61, -half_width)]
            calls.clear()
            try:
                inst = find_motif("diamond")["generator"](ctx)
            except MotifError:
                continue
            if calls[:2] == [False, True]:  # the bowed outline failed and the straight one passed
                fell_back += 1
                assert len(inst.vectors[0].points) == 4 and _colourable(ctx, inst)
    assert fell_back > 0
