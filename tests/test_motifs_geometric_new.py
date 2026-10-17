"""Shape-specific tests for the Phase 3 geometric motifs (spec 7.3): bead and spike."""
import math
import random

import pytest
from shapely.geometry import Polygon

from motifs import find_motif
from motifs.contract import MotifError
from motifs.geometry import CellPoint, MotifContext, cell_rotation_deg
from qa_patterns import tangent_error_deg, turn_at


def make_ctx(cell_kwargs, seed=7, **over):
    return MotifContext(**{**cell_kwargs, "rng": random.Random(seed), **over})


# The side leaves the touch vertex along the divider (smooth touch, spec 3.3) before it turns inward, so the
# concavity is asserted past the first fifth of the corner-to-tip run only (controller ruling, Task 16 review).
CONCAVE_FROM = 0.2


def test_spike_sides_are_concave(cell_kwargs):
    ctx = make_ctx(cell_kwargs, 4, side_touch_radial=0.12)
    pts = find_motif("spike")["generator"](ctx).vectors[0].points
    tip = max(pts, key=lambda p: p.radial)
    corner = CellPoint(0.12, 1.0)
    start = corner.radial + CONCAVE_FROM * (tip.radial - corner.radial)
    right = [p for p in pts if p.angular > 0 and start < p.radial < tip.radial]
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
                start = radial + CONCAVE_FROM * (tip.radial - radial)
                right = [p for p in pts if p.angular > 0 and start < p.radial < tip.radial]
                assert right and all(p.angular < chord(p.radial) for p in right), (seed, limit, radial)
                # It still reads as concave: the side's midpoint radial sits well inside the chord.
                middle = min(right, key=lambda p: abs(p.radial - (radial + tip.radial) / 2.0))
                assert middle.angular < 0.8 * chord(middle.radial)


def test_spike_touch_vertex_has_no_visible_corner(cell_kwargs):
    gen = find_motif("spike")["generator"]
    for seed in range(40):
        for limit in (1.0, 0.5):
            for radial in (0.08, 0.12, 0.2):
                ctx = make_ctx(cell_kwargs, seed, angular_limits=limit, side_touch_radial=radial)
                pts = gen(ctx).vectors[0].points
                for side in (limit, -limit):
                    k = pts.index(CellPoint(radial, side))
                    assert turn_at(ctx, pts, k) <= 25.0, (seed, limit, radial)


def test_spike_tip_is_sharp(cell_kwargs):
    gen = find_motif("spike")["generator"]
    for seed in range(40):
        ctx = make_ctx(cell_kwargs, seed, side_touch_radial=0.12)
        pts = gen(ctx).vectors[0].points
        tip = max(range(len(pts)), key=lambda k: pts[k].radial)
        assert pts[tip].angular == 0.0 and turn_at(ctx, pts, tip) >= 90.0


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
                assert before.radial - radial == pytest.approx(radial - after.radial, abs=1e-12)
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


def test_bead_in_both_mode_meets_the_centre_motif_at_the_shared_vertices(cell_kwargs):
    # In `both` mode the centre motif's budget is centre_share and the divider bead's is 1 - centre_share
    # (spec 7.3): the bead's diameter ends are the side vertices it shares with the centre motifs either side.
    divisions = round(360.0 / cell_kwargs["wedge_angle"])
    for share in (0.45, 0.6, 0.75):
        for radial in (0.12, 0.45):
            centre_ctx = make_ctx(cell_kwargs, 3, angular_limits=share, side_touch_radial=radial)
            bead_ctx = make_ctx(cell_kwargs, 3, position="divider", angular_limits=1.0 - share,
                                side_touch_radial=radial)
            petal = find_motif("petal")["generator"](centre_ctx).vectors[0].points
            bead = _bead(bead_ctx)
            for cell in (0, 1):
                # The divider of cell 0 lies between centre cells 0 and 1.
                petal_side = share if cell == 0 else -share
                bead_side = -(1.0 - share) if cell == 0 else 1.0 - share
                assert CellPoint(radial, petal_side) in petal and CellPoint(radial, bead_side) in bead
                petal_xy = centre_ctx.to_cartesian(CellPoint(radial, petal_side),
                                                   cell_rotation_deg(cell, divisions, "centre"))
                bead_xy = bead_ctx.to_cartesian(CellPoint(radial, bead_side),
                                                cell_rotation_deg(0, divisions, "divider"))
                assert petal_xy == pytest.approx(bead_xy, abs=1e-9)


# The rosette fills ring 0's open middle: inner radius 0, the touch distance as the outer radius, one lobe per
# wedge. The brief's 30-degree wedge on a 60px free radius cannot hold a lobe at this fixture's 10px white
# space (neighbouring lobes come closer than a clearance on the dot arc), so the default is a 90-degree wedge
# (four lobes) on 55px, inside the 35px to 67px free radii the corpus's oversized centres measure.
def rosette_ctx(cell_kwargs, seed=7, **over):
    return make_ctx(cell_kwargs, seed, **{"inner_radius": 0.0, "outer_radius": 55.0, "wedge_angle": 90.0,
                                          "ring_stream_seed": 31, **over})


def test_rosette_is_never_picked_by_the_composer():
    entry = find_motif("rosette")
    assert not {"base", "slot", "back", "attachment"} & set(entry["roles"])


def test_rosette_cells_draw_the_same_ink(cell_kwargs):
    a = find_motif("rosette")["generator"](rosette_ctx(cell_kwargs, 1))
    b = find_motif("rosette")["generator"](rosette_ctx(cell_kwargs, 2))
    assert [v.points for v in a.vectors] == [v.points for v in b.vectors]


def test_rosette_tip_reaches_the_outer_edge_and_lobe_rests_on_the_dot(cell_kwargs):
    dot, lobe = find_motif("rosette")["generator"](rosette_ctx(cell_kwargs)).vectors
    assert all(v.weight == "detail" for v in (dot, lobe))
    assert abs(dot.points[0].angular) == 1.0 and abs(dot.points[-1].angular) == 1.0
    assert CellPoint(1.0, 0.0) in lobe.points
    assert lobe.points[0] in dot.points and lobe.points[-1] in dot.points


def test_rosette_lobe_is_mirror_symmetric_with_a_stem_to_the_touch_point(cell_kwargs):
    from motifs.geometric import rosette_stem_px
    gen = find_motif("rosette")["generator"]
    for ring_seed in range(30):
        ctx = rosette_ctx(cell_kwargs, ring_stream_seed=ring_seed)
        dot, lobe = gen(ctx).vectors
        neck = lobe.points[-1].angular
        assert not dot.closed and not lobe.closed
        assert all(p.radial == dot.points[0].radial for p in dot.points)
        assert lobe.points[0] == CellPoint(lobe.points[-1].radial, -neck)
        assert lobe.points == [CellPoint(p.radial, -p.angular) for p in reversed(lobe.points)]
        assert all(abs(p.angular) < 1.0 and p.radial <= 1.0 for p in lobe.points)
        # The body ends a stem's length short of the touch point; the stem runs out to it on the axis and back.
        body_tip = 1.0 - ctx.px_to_radial(rosette_stem_px(ctx))
        k = lobe.points.index(CellPoint(1.0, 0.0))
        assert lobe.points[k - 1] == lobe.points[k + 1] == CellPoint(pytest.approx(body_tip), 0.0)
        assert max(p.radial for p in lobe.points if p.angular != 0.0) < body_tip
        assert neighbour_gap_px(ctx, lobe, 0.0, ctx.wedge_angle) >= ctx.clearance_px("detail", "detail")


def neighbour_gap_px(ctx, lobe, rotation, next_rotation):
    """The page distance between a lobe traced at `rotation` and the same lobe at `next_rotation`."""
    from shapely.geometry import LineString
    return LineString(ctx.polyline(lobe, rotation)).distance(LineString(ctx.polyline(lobe, next_rotation)))


def test_rosette_tip_stops_at_the_radial_limit(cell_kwargs):
    _dot, lobe = find_motif("rosette")["generator"](rosette_ctx(cell_kwargs, radial_limits=(0.0, 0.9))).vectors
    assert CellPoint(0.9, 0.0) in lobe.points and max(p.radial for p in lobe.points) == 0.9


def test_rosette_refuses_a_small_free_radius(cell_kwargs):
    with pytest.raises(MotifError):
        find_motif("rosette")["generator"](rosette_ctx(cell_kwargs, outer_radius=12.0))


def test_rosette_refuses_crowded_lobes(cell_kwargs):
    with pytest.raises(MotifError):
        find_motif("rosette")["generator"](rosette_ctx(cell_kwargs, wedge_angle=15.0, outer_radius=25.0))


def test_rosette_refuses_lobes_too_close_on_the_dot_arc(cell_kwargs):
    # The brief's one lobe per 30-degree cell on 60px passes the size floor but crowds the dot arc even with
    # the dot grown to its largest.
    with pytest.raises(MotifError, match="crowded"):
        find_motif("rosette")["generator"](rosette_ctx(cell_kwargs, wedge_angle=30.0, outer_radius=60.0))


def ring_zero_ink(center, radius, divisions, cusp=0.0):
    """A ring-0 inner edge around `center`: a circle, or with `cusp` px, arcs bulging out between inward cusps."""
    from shapely.geometry import LineString
    cx, cy = center
    points = []
    for k in range(divisions * 24 + 1):
        theta = 2.0 * math.pi * k / (divisions * 24)
        bulge = cusp * abs(math.sin(divisions * theta / 2.0))
        points.append((cx + (radius + bulge) * math.cos(theta), cy + (radius + bulge) * math.sin(theta)))
    return LineString(points)


def fit_ctx(cell_kwargs, divisions, **over):
    return make_ctx(cell_kwargs, 3, **{"inner_radius": 0.0, "outer_radius": 1.0, "wedge_angle": 360.0 / divisions,
                                       "min_white_space": 8.0, "stroke_width": 2.0, "ring_stream_seed": 17,
                                       **over})


@pytest.mark.parametrize("cusp", [0.0, 8.0])
def test_fit_rosette_touches_ring_zero_and_keeps_clear_of_it(cell_kwargs, cusp):
    from shapely.geometry import LineString, Point
    from motifs.geometric import fit_rosette, rosette_stem_px
    ctx = fit_ctx(cell_kwargs, 12)
    ink = ring_zero_ink(ctx.center, 42.0, 12, cusp)
    fit = fit_rosette(ctx, ink)
    count = len(fit.rotations)
    assert count >= 3 and 12 % count == 0 and fit.cells_per_lobe * count == 12
    assert fit.rotations == [k * 360.0 / count + fit.rotations[0] for k in range(count)]
    keep = ctx.clearance_px("detail", "outline")
    for rotation in fit.rotations:
        tip = Point(fit.context.to_cartesian(CellPoint(1.0, 0.0), rotation))
        assert tip.distance(ink) < 1e-6
        for vector in fit.instance.vectors:
            line = LineString(fit.context.polyline(vector, rotation)).difference(tip.buffer(rosette_stem_px(ctx)))
            assert line.distance(ink) >= keep
    # The same ring stream and ink fit the same rosette.
    again = fit_rosette(ctx, ink)
    assert (again.rotations, [v.points for v in again.instance.vectors]) == (
        fit.rotations, [v.points for v in fit.instance.vectors])


def test_fit_rosette_touches_the_nearer_axis(cell_kwargs):
    from motifs.geometric import fit_rosette
    ctx = fit_ctx(cell_kwargs, 12)
    # Inward cusps on the dividers (half a wedge on): the cusp is the nearest ink, so the lobes touch it there.
    ink = ring_zero_ink(ctx.center, 42.0, 12, 8.0)
    from shapely import affinity
    turned = affinity.rotate(ink, 15.0, origin=ctx.center)
    assert fit_rosette(ctx, ink).axis == "cell" and fit_rosette(ctx, turned).axis == "divider"


def test_fit_rosette_refuses_a_centre_too_small(cell_kwargs):
    from motifs.geometric import fit_rosette
    ctx = fit_ctx(cell_kwargs, 12)
    with pytest.raises(MotifError):
        fit_rosette(ctx, ring_zero_ink(ctx.center, 20.0, 12))


@pytest.mark.parametrize("divisions", [6, 8, 12])
def test_fitted_rosette_lobes_keep_a_clearance_from_their_neighbours(cell_kwargs, divisions):
    # Free radii across the 29px to 67px the corpus's oversized centres measure, including the review case
    # (8 divisions, a 35px circle, ring seed 17).
    from motifs.geometric import fit_rosette
    for radius in (30.0, 35.0, 42.0, 50.0, 58.0, 67.0):
        for ring_seed in (17, 3, 29, 41):
            ctx = fit_ctx(cell_kwargs, divisions, ring_stream_seed=ring_seed)
            try:
                fit = fit_rosette(ctx, ring_zero_ink(ctx.center, radius, divisions))
            except MotifError:
                continue
            lobe = fit.instance.vectors[1]
            gap = neighbour_gap_px(fit.context, lobe, fit.rotations[0], fit.rotations[1])
            assert gap >= ctx.clearance_px("detail", "detail"), (divisions, radius, ring_seed, gap)
