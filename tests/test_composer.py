import pytest
from composer import Composer, ComposerSettings

GEOM = [dict(inner_radius=20 + 60 * i, outer_radius=80 + 60 * i) for i in range(4)]

def plan_for(seed=123, **over):
    settings = ComposerSettings(**{"categories": ["botanical", "geometric"], **over})
    return Composer(seed, GEOM, settings).plan()

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
            assert (r.divisions // p.base_symmetry) % n == 0 and n <= 4 and n < r.divisions

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

def test_force_motif_disables_fallback_but_keeps_the_stem_repair():
    c = Composer(1, GEOM, ComposerSettings(force_motif={"name": "petal", "position": "centre", "role": "base"}))
    ring = c.plan().rings[1]
    node = ring.sequence[0].centre
    assert node.attachments == []
    assert c.replace_node(ring, 0, "centre", "generation") is False
    assert node.motif == "petal" and node.attachments == []
    assert c.replace_node(ring, 0, "centre", "floating") is True
    assert [a.motif for a in node.attachments] == ["stem"]
    assert c.replace_node(ring, 0, "centre", "floating") is False
    assert node.motif == "petal" and len(node.attachments) == 1

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

def test_floating_node_gets_a_stem_first():
    from composer import CellRecipe, CellEntry, RingPlan
    c = Composer(1, GEOM, ComposerSettings(categories=["botanical", "geometric"]))
    ring = RingPlan(1, 12, 1.0, [CellEntry(CellRecipe("ring_band", "geometric"), None)], 1)
    assert c.replace_node(ring, 0, "centre", "floating") is True
    node = ring.sequence[0].centre
    assert node.motif == "ring_band"
    assert [a.motif for a in node.attachments] == ["stem"] and node.attachments[0].provides_contact


# ------------------------------------------------------- revision 2: symmetry and contact

def _base_nodes(ring):
    return [n for e in ring.sequence for n in (e.centre, e.divider) if n is not None]

def _stems_in_plan(ring):
    """Stem attachments in the ring's plan (its sequence), not repeated over its cells."""
    return [a for n in _base_nodes(ring) for a in n.attachments if a.motif == "stem"]

def test_base_symmetry_is_num_divisions_without_vary():
    assert plan_for(num_divisions=10).base_symmetry == 10

def test_explicit_ring_divisions_give_their_gcd_as_base_symmetry():
    assert plan_for(ring_divisions=[8, 8, 8, 12]).base_symmetry == 4
    assert plan_for(ring_divisions=[9, 7, 12, 6]).base_symmetry == 1

def test_base_symmetry_static_rule():
    import random
    rng = random.Random(0)
    assert Composer.base_symmetry(12, False, None, rng) == 12
    assert Composer.base_symmetry(12, True, [6, 9], rng) == 3
    for _ in range(50):
        assert Composer.base_symmetry(24, True, None, rng) in (3, 4, 6, 8)
    assert Composer.base_symmetry(11, True, None, rng) == 11

def test_vary_without_a_small_divisor_falls_back_to_the_largest_divisor_of_at_least_three():
    import random
    rng = random.Random(0)
    assert Composer.base_symmetry(22, True, None, rng) == 11
    for prime in (11, 13, 17, 19, 23):
        assert Composer.base_symmetry(prime, True, None, rng) == prime

def test_vary_twenty_two_gives_symmetry_eleven_and_multiples_of_eleven():
    for seed in range(10):
        p = Composer(seed, GEOM, ComposerSettings(num_divisions=22, vary_divisions=True,
                                                  categories=["botanical"])).plan()
        assert p.base_symmetry == 11
        for r in p.rings:
            assert 4 <= r.divisions <= 24 and r.divisions in (11, 22)

def test_vary_thirteen_gives_symmetry_thirteen():
    p = plan_for(num_divisions=13, vary_divisions=True)
    assert p.base_symmetry == 13
    assert all(r.divisions == 13 for r in p.rings)

def test_vary_twelve_draws_symmetry_weighted_by_value():
    import random
    from collections import Counter
    draws = Counter(Composer.base_symmetry(12, True, None, random.Random(seed)) for seed in range(50))
    assert set(draws) <= {3, 4, 6}
    assert draws.most_common(1)[0][0] == 6

def test_vary_counts_are_multiples_of_base_symmetry():
    symmetries = set()
    for num in (8, 9, 12, 16, 24):
        for seed in range(15):
            p = Composer(seed, GEOM, ComposerSettings(num_divisions=num, vary_divisions=True,
                                                      categories=["botanical"])).plan()
            assert 3 <= p.base_symmetry <= 8 and num % p.base_symmetry == 0
            symmetries.add(p.base_symmetry)
            for r in p.rings:
                assert 4 <= r.divisions <= 24
                assert r.divisions % p.base_symmetry == 0
    assert len(symmetries) > 1

def test_sequence_length_divides_the_wedge():
    for seed in range(20):
        p = Composer(seed, GEOM, ComposerSettings(complexity=1.0, vary_divisions=True,
                                                  categories=["botanical", "geometric"])).plan()
        for r in p.rings:
            n = len(r.sequence)
            assert (r.divisions // p.base_symmetry) % n == 0 and n <= 4 and n < r.divisions

def test_uniform_divisions_repeat_one_entry_per_cell():
    for seed in range(10):
        p = Composer(seed, GEOM, ComposerSettings(complexity=1.0, categories=["botanical", "geometric"])).plan()
        assert all(len(r.sequence) == 1 for r in p.rings)

def test_botanical_geometric_rings_are_side_mode_with_one_stem_per_wedge():
    from composer import touch_heights_of, CONTACT_OVERFLOW
    from motifs import find_motif, safe_motif
    stemmed = 0
    for vary in (False, True):
        for seed in range(20):
            p = Composer(seed, GEOM, ComposerSettings(complexity=0.8, vary_divisions=vary,
                                                      categories=["botanical", "geometric"])).plan()
            for r in p.rings:
                assert r.contact_mode == "side"
                entries = [find_motif(n.motif) or safe_motif(n.category) for n in _base_nodes(r)]
                stems = _stems_in_plan(r)
                if r.ring_index > 0 and not any(e["max_overflow_inward"] >= CONTACT_OVERFLOW for e in entries):
                    assert len(stems) == 1 and stems[0].once_per_wedge
                    stemmed += 1
                else:
                    assert stems == []
                for node in _base_nodes(r):
                    assert r.touch_height in touch_heights_of(find_motif(node.motif) or safe_motif(node.category))
                    assert node.provides_contact
    assert stemmed > 0

def test_side_ring_without_inward_overflow_gets_one_stem_on_its_first_node():
    from composer import CellRecipe, CellEntry
    c = Composer(1, GEOM, ComposerSettings(categories=["botanical", "geometric"]))
    seq = [CellEntry(CellRecipe("ring_band", "geometric"), CellRecipe("ring_band", "geometric")),
           CellEntry(CellRecipe("leaf", "botanical"), None)]
    c._ensure_contact(1, seq, "side")
    assert [a.motif for a in seq[0].centre.attachments] == ["stem"]
    assert seq[0].centre.attachments[0].once_per_wedge
    assert seq[0].divider.attachments == [] and seq[1].centre.attachments == []
    assert all(n.provides_contact for e in seq for n in (e.centre, e.divider) if n is not None)

def test_side_ring_with_inward_overflow_gets_no_stem():
    from composer import CellRecipe, CellEntry
    c = Composer(1, GEOM, ComposerSettings(categories=["botanical", "geometric"]))
    seq = [CellEntry(CellRecipe("leaf", "botanical"), CellRecipe("petal", "botanical"))]
    c._ensure_contact(1, seq, "side")
    assert seq[0].centre.attachments == [] and seq[0].divider.attachments == []
    assert seq[0].centre.provides_contact and seq[0].divider.provides_contact

def test_contact_mode_falls_back_to_overflow_then_stem(monkeypatch):
    import composer as composer_module
    from composer import CellRecipe, CellEntry
    real = composer_module.find_motif
    def fake(name):
        entry = real(name)
        if name in ("petal", "scallop"):
            return {**entry, "side_touch_heights": ()}
        return entry
    monkeypatch.setattr(composer_module, "find_motif", fake)
    c = Composer(1, GEOM, ComposerSettings(categories=["botanical", "geometric"]))
    overflow = [CellEntry(CellRecipe("petal", "botanical"), CellRecipe("scallop", "botanical"))]
    assert c._contact_mode(1, overflow) == "overflow"
    assert c._contact_mode(0, overflow) == "side"
    c._ensure_contact(1, overflow, "overflow")
    assert overflow[0].centre.attachments == [] and overflow[0].divider.attachments == []
    assert overflow[0].centre.provides_contact and overflow[0].divider.provides_contact
    stem = [CellEntry(CellRecipe("petal", "botanical"), None), CellEntry(CellRecipe("diamond", "geometric"), None)]
    assert c._contact_mode(1, stem) == "stem"

def test_forced_non_side_base_gives_stem_mode():
    p = plan_for(force_motif={"name": "diamond", "position": "centre", "role": "base"})
    assert p.rings[0].contact_mode == "side"
    for r in p.rings[1:]:
        assert r.contact_mode == "stem"
        for node in _base_nodes(r):
            assert [a.motif for a in node.attachments] == ["stem"]

def test_side_touch_radial_is_one_value_per_ring_in_range():
    from composer import BASE_TOUCH_RANGE, MID_TOUCH_RANGE
    seen = set()
    for seed in range(10):
        p = Composer(seed, GEOM, ComposerSettings(categories=["botanical"])).plan()
        for r in p.rings:
            low, high = BASE_TOUCH_RANGE if r.touch_height == "base" else MID_TOUCH_RANGE
            assert low <= r.side_touch_radial <= high
            seen.add(r.side_touch_radial)
    assert len(seen) > 1
    assert [r.side_touch_radial for r in plan_for().rings] == [r.side_touch_radial for r in plan_for().rings]

def test_plan_json_round_trips_the_revision_two_fields():
    from composer import DesignPlan
    p = Composer(5, GEOM, ComposerSettings(vary_divisions=True, categories=["botanical", "geometric"])).plan()
    d = p.to_dict()
    assert d["base_symmetry"] == p.base_symmetry
    assert all("contact_mode" in r and "side_touch_radial" in r and "touch_height" in r for r in d["rings"])
    assert DesignPlan.from_json(p.to_json()) == p

def test_once_per_wedge_round_trips_and_defaults_false():
    from composer import CellRecipe
    stem = CellRecipe("stem", "botanical", provides_contact=True, once_per_wedge=True)
    assert CellRecipe.from_dict(stem.to_dict()) == stem
    d = stem.to_dict()
    del d["once_per_wedge"]
    assert CellRecipe.from_dict(d).once_per_wedge is False

def test_stem_mode_and_floating_stems_are_per_cell():
    p = plan_for(force_motif={"name": "diamond", "position": "centre", "role": "base"})
    for r in p.rings[1:]:
        assert all(not a.once_per_wedge for n in _base_nodes(r) for a in n.attachments)

def test_partial_ring_divisions_list_includes_num_divisions_in_the_gcd():
    assert plan_for(ring_divisions=[8], num_divisions=12).base_symmetry == 4

def test_downgrade_from_side_mode_clears_once_per_wedge(monkeypatch):
    import composer as composer_module
    from composer import CellRecipe, CellEntry, RingPlan, CONTACT_OVERFLOW
    real = composer_module.find_motif
    def fake(name):
        entry = real(name)
        if name in ("petal", "ring_band"):
            return {**entry, "side_touch_heights": ()}
        return entry
    monkeypatch.setattr(composer_module, "find_motif", fake)
    c = Composer(1, GEOM, ComposerSettings(categories=["botanical", "geometric"]))
    seq = [CellEntry(CellRecipe("leaf", "botanical"), None), CellEntry(CellRecipe("leaf", "botanical"), None)]
    c._ensure_contact(1, seq, "side")
    ring = RingPlan(1, 12, 1.0, seq, 1, contact_mode="side")
    assert seq[0].centre.attachments[0].once_per_wedge
    assert c.replace_node(ring, 1, "centre", "generation") is True
    assert ring.sequence[1].centre.motif in ("petal", "ring_band")
    assert ring.contact_mode == "stem"
    nodes = _base_nodes(ring)
    assert not any(a.once_per_wedge for n in nodes for a in n.attachments)
    for node in nodes:
        entry = fake(node.motif)
        has_inward = entry["max_overflow_inward"] >= CONTACT_OVERFLOW
        assert entry["spans_cell"] or has_inward or node.attachments
        assert node.provides_contact or any(a.provides_contact for a in node.attachments)

def test_old_plan_json_loads_with_defaults():
    from composer import DesignPlan
    d = plan_for().to_dict()
    del d["base_symmetry"]
    for r in d["rings"]:
        del r["contact_mode"], r["side_touch_radial"], r["touch_height"]
    old = DesignPlan.from_dict(d)
    assert old.base_symmetry == 1
    assert all(r.contact_mode == "stem" and r.side_touch_radial == 0.5 and r.touch_height == "mid"
               for r in old.rings)

def test_floating_node_in_side_ring_tries_side_bases_before_a_stem():
    from composer import CellRecipe, CellEntry, RingPlan, touch_heights_of
    c = Composer(1, GEOM, ComposerSettings(categories=["botanical", "geometric"]))
    width, depth = c._ring_metrics(1, 12)
    side_names = {m["name"] for m in c._base_candidates(1, "centre", width, depth) if "mid" in touch_heights_of(m)}
    ring = RingPlan(1, 12, 1.0, [CellEntry(CellRecipe("petal", "botanical"), None)], 1, contact_mode="side")
    seen = ["petal"]
    while True:
        before = ring.sequence[0].centre
        assert c.replace_node(ring, 0, "centre", "floating") is True
        node = ring.sequence[0].centre
        if node is before or node.is_fallback:
            break
        assert node.motif not in seen and node.motif in side_names
        seen.append(node.motif)
    assert set(seen) == side_names and len(seen) > 1
    assert ring.contact_mode == "side"


def test_unsalted_node_seed_is_unchanged():
    from composer import node_seed
    assert node_seed(42, 1, 2, 0, "centre") == 42 * 1_000_003 + 1 * 10_007 + 2 * 101


def test_salt_changes_the_seed_and_is_stable():
    from composer import node_seed
    salted = node_seed(42, 1, 2, 0, "centre", salt="pick")
    assert salted != node_seed(42, 1, 2, 0, "centre")
    assert salted == node_seed(42, 1, 2, 0, "centre", salt="pick")


def test_salt_survives_a_new_process():
    import subprocess, sys
    from composer import node_seed
    code = "from composer import node_seed; print(node_seed(42, 1, 2, 0, 'centre', salt='pick'))"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout
    assert int(out) == node_seed(42, 1, 2, 0, "centre", salt="pick")


# ------------------------------------------------------- touch height and seam motifs

from composer import (BASE_TOUCH_RANGE, MID_TOUCH_RANGE, RingPlan, common_touch_heights,
                      touch_heights_of)


def test_touch_radial_matches_height():
    for seed in range(30):
        for ring in plan_for(seed=seed).rings:
            if ring.contact_mode == "side":
                low, high = BASE_TOUCH_RANGE if ring.touch_height == "base" else MID_TOUCH_RANGE
                assert low <= ring.side_touch_radial <= high


def test_disjoint_heights_are_not_side():
    assert common_touch_heights([{"side_touch_heights": ("base",), "seams": False},
                                 {"side_touch_heights": ("mid",), "seams": False}]) == ()


def test_revision_two_plan_loads_as_mid():
    d = plan_for(seed=3).rings[1].to_dict(); d.pop("touch_height")
    assert RingPlan.from_dict(d).touch_height == "mid"


def test_touch_height_constants():
    import composer
    assert composer.TOUCH_HEIGHTS == ("base", "mid")
    assert BASE_TOUCH_RANGE == (0.08, 0.2) and MID_TOUCH_RANGE == (0.35, 0.6)
    assert not hasattr(composer, "SIDE_TOUCH_RADIAL_RANGE")


def test_seam_motifs_are_side_capable_at_every_height():
    seam = {"side_touch_heights": (), "seams": True}
    petal = {"side_touch_heights": ("base", "mid"), "seams": False}
    band = {"side_touch_heights": ("mid",), "seams": False}
    assert touch_heights_of(seam) == ("base", "mid")
    assert common_touch_heights([seam, petal]) == ("base", "mid")
    assert common_touch_heights([band, petal]) == ("mid",)
    assert common_touch_heights([petal, {"side_touch_heights": (), "seams": False}]) == ()


def test_touch_height_is_drawn_from_the_common_heights_of_the_ring():
    from motifs import find_motif, safe_motif
    heights = set()
    for seed in range(30):
        for vary in (False, True):
            p = Composer(seed, GEOM, ComposerSettings(complexity=0.8, vary_divisions=vary,
                                                      categories=["botanical", "geometric"])).plan()
            for r in p.rings:
                entries = [find_motif(n.motif) or safe_motif(n.category) for n in _base_nodes(r)]
                assert r.contact_mode == "side" and r.touch_height in common_touch_heights(entries)
                heights.add(r.touch_height)
    assert heights == {"base", "mid"}


def test_disjoint_ring_falls_back_to_overflow_then_stem(monkeypatch):
    import composer as composer_module
    from composer import CellRecipe, CellEntry
    real = composer_module.find_motif
    def fake(name):
        entry = real(name)
        if name == "petal":
            return {**entry, "side_touch_heights": ("base",)}
        return entry
    monkeypatch.setattr(composer_module, "find_motif", fake)
    c = Composer(1, GEOM, ComposerSettings(categories=["botanical", "geometric"]))
    # petal (base only) and scallop (mid only) share no height, but both overflow inward.
    seq = [CellEntry(CellRecipe("petal", "botanical"), CellRecipe("scallop", "botanical"))]
    assert c._contact_mode(1, seq) == "overflow"
    seq = [CellEntry(CellRecipe("petal", "botanical"), CellRecipe("ring_band", "geometric"))]
    assert c._contact_mode(1, seq) == "stem"


def test_floating_node_in_base_height_ring_tries_only_base_capable_bases():
    from composer import CellRecipe, CellEntry
    # The first floating repair of a petal in a side ring substitutes another base touching at the
    # ring's height: only leaf at base height, while mid height also admits ring_band.
    picked = {"base": set(), "mid": set()}
    for ring_seed in range(30):
        for height in ("base", "mid"):
            c = Composer(1, GEOM, ComposerSettings(categories=["botanical", "geometric"]))
            ring = RingPlan(1, 12, 1.0, [CellEntry(CellRecipe("petal", "botanical"), None)], ring_seed,
                            contact_mode="side", touch_height=height)
            assert c.replace_node(ring, 0, "centre", "floating") is True
            picked[height].add(ring.sequence[0].centre.motif)
            assert ring.contact_mode == "side" and ring.touch_height == height
    assert picked == {"base": {"leaf"}, "mid": {"leaf", "ring_band"}}


def test_substitute_that_loses_the_ring_height_leaves_side_mode():
    from composer import CellRecipe, CellEntry
    c = Composer(1, GEOM, ComposerSettings(categories=["botanical", "geometric"]))
    ring = RingPlan(1, 12, 1.0, [CellEntry(CellRecipe("petal", "botanical"), None)], 1,
                    contact_mode="side", touch_height="base")
    for _ in range(4):
        c.replace_node(ring, 0, "centre", "generation")
        if "base" not in touch_heights_of(c._registry_entry(ring.sequence[0].centre)):
            assert ring.contact_mode != "side"
            return
    raise AssertionError("no substitute without the base height was reached")


@pytest.fixture
def seam_band(monkeypatch):
    """Registers ring_band as a seam motif, as Task 5 will."""
    import composer as composer_module
    real_find, real_for = composer_module.find_motif, composer_module.motifs_for_categories
    def as_seam(entry):
        if entry is not None and entry["name"] == "ring_band":
            return {**entry, "seams": True, "side_touch_heights": ()}
        return entry
    monkeypatch.setattr(composer_module, "find_motif", lambda name: as_seam(real_find(name)))
    monkeypatch.setattr(composer_module, "motifs_for_categories",
                        lambda cats: [as_seam(e) for e in real_for(cats)])


def _seam_plans():
    for seed in range(40):
        for vary in (False, True):
            yield Composer(seed, GEOM, ComposerSettings(complexity=1.0, vary_divisions=vary,
                                                        categories=["botanical", "geometric"])).plan()


def test_seam_motif_at_entry_zero_fills_its_whole_position(seam_band):
    copied = 0
    for p in _seam_plans():
        for r in p.rings:
            for position in ("centre", "divider"):
                nodes = [getattr(e, position) for e in r.sequence]
                if nodes[0] is None:
                    continue
                if nodes[0].motif == "ring_band":
                    assert all(n.motif == "ring_band" for n in nodes)
                    copied += len(nodes) > 1
                else:
                    assert all(n.motif != "ring_band" for n in nodes[1:])
    assert copied > 0


def test_seam_motifs_are_not_candidates_in_both_mode(seam_band):
    both = 0
    for p in _seam_plans():
        for r in p.rings:
            if r.centre_share < 1.0:
                both += 1
                assert all(n.motif != "ring_band" for n in _base_nodes(r))
    assert both > 0


def test_seam_ring_is_side_at_any_height(seam_band):
    heights = set()
    for p in _seam_plans():
        for r in p.rings[1:]:
            if {n.motif for n in _base_nodes(r)} == {"ring_band"}:
                assert r.contact_mode == "side"
                heights.add(r.touch_height)
    assert heights == {"base", "mid"}


def test_replace_node_on_a_seam_node_replaces_every_entry(seam_band):
    from composer import CellRecipe, CellEntry
    c = Composer(1, GEOM, ComposerSettings(categories=["botanical", "geometric"]))
    seq = [CellEntry(CellRecipe("ring_band", "geometric"), None) for _ in range(3)]
    ring = RingPlan(1, 12, 1.0, seq, 1, contact_mode="side", touch_height="mid")
    assert c.replace_node(ring, 1, "centre", "generation") is True
    names = [e.centre.motif for e in ring.sequence]
    assert names[0] != "ring_band" and len(set(names)) == 1
    assert len({id(e.centre) for e in ring.sequence}) == 3


def test_replace_node_falls_back_in_every_entry_of_a_seam_position(seam_band):
    from composer import CellRecipe, CellEntry
    c = Composer(1, GEOM, ComposerSettings(categories=["geometric"]))
    seq = [CellEntry(CellRecipe("ring_band", "geometric"), None) for _ in range(2)]
    ring = RingPlan(1, 12, 1.0, seq, 1, contact_mode="side", touch_height="mid")
    assert c.replace_node(ring, 0, "centre", "generation") is True
    assert all(e.centre.is_fallback for e in ring.sequence)


def test_non_seam_substitute_never_brings_a_seam_into_a_longer_sequence(seam_band):
    from composer import CellRecipe, CellEntry
    c = Composer(1, GEOM, ComposerSettings(categories=["botanical", "geometric"]))
    seq = [CellEntry(CellRecipe("petal", "botanical"), None), CellEntry(CellRecipe("leaf", "botanical"), None)]
    ring = RingPlan(1, 12, 1.0, seq, 1, contact_mode="side", touch_height="mid")
    steps = 0
    while c.replace_node(ring, 1, "centre", "generation") and not ring.sequence[1].centre.is_fallback:
        assert ring.sequence[1].centre.motif != "ring_band"
        assert ring.sequence[0].centre.motif == "petal"
        steps += 1
    assert steps > 0 and ring.sequence[1].centre.is_fallback
