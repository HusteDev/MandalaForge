"""Layered rings (spec section 5): the composite, its failure path, and regeneration."""

import random
from dataclasses import replace

import pytest
from shapely.geometry import LineString, Polygon

from coloring_generator import DesignGenerator
from composer import ring_stream_seed
from motifs import find_motif
from motifs.layering import LayeringError, compose_layered
from tests.test_motifs import make_ctx


def layered_design(**over):
    return DesignGenerator(**{"seed": 42, "num_rings": 4, "ring_divisions": [8, 8, 8, 12],
                              "categories": ["botanical"], "force_position_mode": "layered", **over})


def test_layered_design_validates_and_has_back_ink():
    g = layered_design(); g.generate()
    assert g.last_validation_result.is_valid, g.last_validation_result.issues[:5]
    assert any(r.back is not None for r in g.plan.rings[1:])
    assert any(p.role == "back" for p in g.assembled.paths)


def test_back_never_crosses_the_front_and_cut_points_are_front_vertices(cell_kwargs):
    front, back = find_motif("petal"), find_motif("leaf")
    fctx = make_ctx(cell_kwargs, 3, side_touch_radial=0.12)
    bctx = replace(fctx, rng=random.Random(9), node_seed=9, position="divider", radial_limits=(0.0, 1.0),
                   side_touch_radial=None)
    inst = compose_layered(fctx, front, bctx, back)
    front_outline = inst.vectors[0].points
    fill = Polygon([(p.angular, p.radial) for p in front_outline])
    backs = [v for v in inst.vectors if v.layer == "back"]
    assert backs
    for v in backs:
        assert not LineString([(p.angular, p.radial) for p in v.points]).crosses(fill.exterior)
        for end in (v.points[0], v.points[-1]):
            assert abs(end.angular) == 1.0 or end in front_outline


def test_composite_is_deterministic_and_keeps_the_front_declaration(cell_kwargs):
    front, back = find_motif("petal"), find_motif("leaf")
    fctx = make_ctx(cell_kwargs, 3, side_touch_radial=0.12)

    def build():
        f = replace(fctx, rng=random.Random(3))
        b = replace(f, rng=random.Random(9), node_seed=9, position="divider", radial_limits=(0.0, 1.0),
                    side_touch_radial=None)
        return compose_layered(f, front, b, back)

    first, second = build(), build()
    assert [v.points for v in first.vectors] == [v.points for v in second.vectors]
    plain = front["generator"](replace(fctx, rng=random.Random(3)))
    assert first.declaration.slot == plain.declaration.slot
    assert first.declaration.base_point == plain.declaration.base_point
    assert first.declaration.seams


def test_a_back_the_front_never_covers_raises_layering_error(cell_kwargs):
    # A tiny front leaves the back halves uncut: they would float, so the composite refuses them.
    front, back = find_motif("petal"), find_motif("petal")
    fctx = make_ctx(cell_kwargs, 3, angular_limits=0.15, radial_limits=(0.0, 0.2))
    bctx = replace(fctx, rng=random.Random(9), node_seed=9, position="divider", angular_limits=1.0,
                   radial_limits=(0.0, 1.0), side_touch_radial=None)
    with pytest.raises(LayeringError):
        compose_layered(fctx, front, bctx, back)


def test_dense_layered_ring_drops_its_back_and_still_validates(monkeypatch):
    # Seed 1 at 24 divisions: rings 1 and 2 have backs too thin to survive the cut, so pass one drops them.
    import coloring_generator
    assemblies = []

    class Counting(coloring_generator.Assembler):
        def __init__(self, *args, **kwargs):
            assemblies.append(1)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(coloring_generator, "Assembler", Counting)
    g = layered_design(seed=1, ring_divisions=[24, 24, 24, 24], complexity=0.9); g.generate()
    assert g.last_validation_result.is_valid, g.last_validation_result.issues[:5]
    dropped = [r for r in g.plan.rings if r.back_dropped]
    assert dropped, "the scenario needs a back too thin to survive the cut"
    assert len(assemblies) == 1, "dropped in pass one, without assembling again"
    assert all(r.back is None and r.position_mode == "centre" for r in dropped)
    # Ring-wide: no cell of a dropped ring keeps back ink.
    assert not any(p.role == "back" for p in g.assembled.paths if p.ring_index in {r.ring_index for r in dropped})


def test_pass_two_layering_failure_drops_the_back(monkeypatch):
    import motifs.layering as layering
    real = layering.compose_layered
    failed = []

    def fragile(front_context, front_entry, back_context, back_entry):
        if front_context.radial_limits[1] < 1.0 + front_entry["max_overflow_outward"]:
            failed.append(front_context.inner_radius)
            raise LayeringError("pulled back")
        return real(front_context, front_entry, back_context, back_entry)

    monkeypatch.setattr(layering, "compose_layered", fragile)
    g = layered_design(); g.generate()
    assert failed, "the scenario needs a pull-back of a layered composite"
    assert g.last_validation_result.is_valid, g.last_validation_result.issues[:5]
    dropped = [r for r in g.plan.rings if r.back_dropped]
    assert dropped and all(r.back is None and r.position_mode == "centre" for r in dropped)


def _back_seeds(g, ring_index):
    return {node.back_seed for node in g.assembled.nodes if node.ring_index == ring_index and node.parent is None}


def test_regenerated_ring_keeps_its_seams_meeting():
    g = layered_design(); g.generate()
    assert g.plan.rings[2].back is not None, "the scenario needs a layered ring 2"
    frag = g.generate_ring_fragment(2, 999)
    assert g.last_validation_result.is_valid and g.validation_summary()["dangling_end_count"] == 0
    ring = frag["plan"].rings[2]
    assert ring.ring_seed == 999
    if ring.back is not None:
        # Every cell of the ring draws its back from the new ring stream together.
        assert _back_seeds(g, 2) == {ring_stream_seed(999, 2, "back")}
        assert any(p.role == "back" and p.ring_index == 2 for p in g.assembled.paths)


def test_regenerated_seam_ring_keeps_its_seams_meeting():
    # A band (seam motif) forced on every ring: a new ring seed redraws all its cells from the new ring stream.
    g = DesignGenerator(seed=42, num_rings=4, ring_divisions=[8, 8, 8, 12], categories=["botanical", "geometric"],
                        force_motif={"name": "band", "position": "centre", "role": "base"})
    g.generate()
    assert g.last_validation_result.is_valid, g.last_validation_result.issues[:5]
    g.generate_ring_fragment(2, 999)
    assert g.last_validation_result.is_valid, g.last_validation_result.issues[:5]
    assert g.validation_summary()["dangling_end_count"] == 0
    bands = [n for n in g.assembled.nodes if n.ring_index == 2 and n.parent is None and n.recipe.motif == "band"]
    assert bands and len({n.context.ring_stream_seed for n in bands}) == 1
    assert bands[0].context.ring_stream_seed == ring_stream_seed(999, 2, "ring:band:centre")
