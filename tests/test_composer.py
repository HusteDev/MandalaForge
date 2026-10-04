import pytest
from composer import Composer, ComposerSettings

GEOM = [dict(inner_radius=20 + 60 * i, outer_radius=80 + 60 * i) for i in range(4)]

def plan_for(**over):
    settings = ComposerSettings(**{"categories": ["botanical", "geometric"], **over})
    return Composer(123, GEOM, settings).plan()

def test_plan_is_deterministic():
    assert plan_for().to_json() == plan_for().to_json()

def test_uniform_divisions_by_default():
    assert [r.divisions for r in plan_for(num_divisions=10).rings] == [10, 10, 10, 10]

def test_ring_divisions_override():
    assert [r.divisions for r in plan_for(ring_divisions=[8, 8, 8, 12]).rings] == [8, 8, 8, 12]

def test_vary_divisions_stays_in_range_and_varies_somewhere():
    seen = set()
    for seed in range(10):
        p = Composer(seed, GEOM, ComposerSettings(vary_divisions=True, categories=["botanical"])).plan()
        for r in p.rings:
            assert 4 <= r.divisions <= 24
            seen.add(r.divisions)
    assert len(seen) > 1

def test_sequence_length_divides_count_and_is_bounded():
    for seed in range(10):
        p = Composer(seed, GEOM, ComposerSettings(complexity=1.0, ring_divisions=[9, 7, 12, 6],
                                                   categories=["botanical", "geometric"])).plan()
        for r in p.rings:
            n = len(r.sequence)
            assert r.divisions % n == 0 and n <= 4 and n < r.divisions

def test_complexity_zero_gives_single_entry_and_no_nesting():
    p = plan_for(complexity=0.0)
    for r in p.rings:
        assert len(r.sequence) == 1
        for e in r.sequence:
            for node in (e.centre, e.divider):
                assert node is None or node.slot_child is None

def test_every_base_has_a_contact_route():
    p = plan_for(complexity=0.8)
    for r in p.rings:
        for e in r.sequence:
            for node in (e.centre, e.divider):
                if node is not None:
                    assert node.provides_contact or any(a.provides_contact for a in node.attachments)

def test_innermost_ring_uses_spans_cell_bases():
    from motifs import find_motif, safe_motif
    p = plan_for()
    for e in p.rings[0].sequence:
        for node in (e.centre, e.divider):
            if node is not None:
                entry = find_motif(node.motif) or safe_motif(node.category)
                assert entry["spans_cell"]

def test_plan_ring_with_new_seed_leaves_other_rings_equal():
    c = Composer(123, GEOM, ComposerSettings(categories=["botanical"]))
    base = c.plan()
    again = c.plan()
    again.rings[2] = c.plan_ring(2, 999)
    assert again.rings[:2] == base.rings[:2]
    assert again.rings[3] == base.rings[3]
    assert again.rings[2] != base.rings[2]

def test_force_motif_as_slot_child():
    p = plan_for(force_motif={"name": "diamond", "position": "centre", "role": "slot"})
    assert p.rings[1].sequence[0].centre.slot_child.motif == "diamond"

def test_force_motif_disables_fallback():
    c = Composer(1, GEOM, ComposerSettings(force_motif={"name": "petal", "position": "centre", "role": "base"}))
    ring = c.plan().rings[1]
    assert c.replace_node(ring, 0, "centre", "test") is False

def test_style_weights_categories_instead_of_filtering_them():
    # Composer seed 2 gives ring 0 a scallop, so the variety filter leaves ring_band allowed in ring 1.
    c = Composer(2, GEOM, ComposerSettings(categories=["botanical", "geometric"]))
    c.style = {"categories": ["botanical"], "positions": "centre"}
    bases = set()
    for ring_seed in range(30):
        for e in c.plan_ring(1, ring_seed).sequence:
            for node in (e.centre, e.divider):
                if node is not None:
                    bases.add(node.motif)
    assert "ring_band" in bases

def test_regenerating_one_ring_does_not_reshuffle_its_neighbours():
    settings = dict(categories=["botanical", "geometric"])
    base = Composer(123, GEOM, ComposerSettings(**settings)).plan()
    for rs in range(1000, 1050):
        again = Composer(123, GEOM, ComposerSettings(ring_seeds={2: rs}, **settings)).plan()
        assert again.rings[3] == base.rings[3]
        assert again.rings[1] == base.rings[1]

def test_innermost_ring_never_falls_back_with_botanical_only():
    for seed in range(50):
        p = Composer(seed, GEOM, ComposerSettings(categories=["botanical"])).plan()
        for e in p.rings[0].sequence:
            for node in (e.centre, e.divider):
                assert node is None or not node.is_fallback

def test_explicit_division_counts_are_validated():
    with pytest.raises(ValueError, match="30"):
        Composer(1, GEOM, ComposerSettings(ring_divisions=[8, 30]))
    with pytest.raises(ValueError, match="3"):
        Composer(1, GEOM, ComposerSettings(num_divisions=3))
