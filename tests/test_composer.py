import random

import pytest
from composer import CellRecipe, Composer, ComposerSettings, pick_embellishments
from motifs import find_motif
from motifs.embellish import EMBELLISHMENT_ORDER, INTERIOR_FILLS

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
    # Ring 0 is always a seam ring, so ring 1 avoids band; ring 2 sits on a non-seam ring 1 (composer seed 2), so
    # the variety filter leaves band allowed there.
    c = Composer(2, GEOM, ComposerSettings(categories=["botanical", "geometric"]))
    c.style = {"categories": ["botanical"], "positions": "centre"}
    assert not set(c._inward_base_names(2)) & SEAM_NAMES
    bases = set()
    for ring_seed in range(30):
        for e in c.plan_ring(2, ring_seed).sequence:
            for node in (e.centre, e.divider):
                if node is not None:
                    bases.add(node.motif)
    assert "band" in bases

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
                entries = [find_motif(n.motif) or safe_motif(n.category) for n in _base_nodes(r)]
                if r.ring_index > 0 and not common_touch_heights(entries):
                    # Phase 3 bases touch at one height only (spike: base; heart, curl: mid), so a ring mixing
                    # them shares no height and falls back to overflow or stems (spec 3.2).
                    assert r.contact_mode != "side"
                    continue
                assert r.contact_mode == "side"
                stems = _stems_in_plan(r)
                if r.ring_index > 0 and all(e["seams"] for e in entries):
                    # A seam ring's stems are per cell, one on every node.
                    assert len(stems) == len(entries) and not any(stem.once_per_wedge for stem in stems)
                    stemmed += 1
                elif r.ring_index > 0 and not any(e["max_overflow_inward"] >= CONTACT_OVERFLOW for e in entries):
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
    # Non-seam bases without inward overflow (band is a seam motif now, whose cells each get a stem).
    seq = [CellEntry(CellRecipe("botanical_safe_band", "botanical"), CellRecipe("botanical_safe_band", "botanical")),
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
        if name == "petal":
            return {**entry, "side_touch_heights": ()}
        return entry
    monkeypatch.setattr(composer_module, "find_motif", fake)
    c = Composer(1, GEOM, ComposerSettings(categories=["botanical", "geometric"]))
    overflow = [CellEntry(CellRecipe("petal", "botanical"), CellRecipe("petal", "botanical"))]
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
        # Every base but the leaf loses side touch, so any substitute for a leaf leaves side mode.
        if entry is not None and name != "leaf" and not entry["seams"]:
            return {**entry, "side_touch_heights": ()}
        return entry
    monkeypatch.setattr(composer_module, "find_motif", fake)
    c = Composer(1, GEOM, ComposerSettings(categories=["botanical", "geometric"]))
    seq = [CellEntry(CellRecipe("leaf", "botanical"), None), CellEntry(CellRecipe("leaf", "botanical"), None)]
    c._ensure_contact(1, seq, "side")
    ring = RingPlan(1, 12, 1.0, seq, 1, contact_mode="side")
    assert seq[0].centre.attachments[0].once_per_wedge
    assert c.replace_node(ring, 1, "centre", "generation") is True
    # Band is a seam motif, never a substitute in a two-entry sequence, so the substitute is a non-touching base.
    substitute = ring.sequence[1].centre.motif
    assert substitute != "leaf" and not fake(substitute)["side_touch_heights"]
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
        assert node.motif not in seen
        seen.append(node.motif)
    # Every side base is tried before any other repair; after them, a non-touching base (spike, at base height
    # only) may still be substituted, with a stem, before the safe band.
    tried_side = seen[:len(side_names)]
    assert set(tried_side) == side_names and len(tried_side) > 1
    assert not set(seen[len(side_names):]) & side_names


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
                if r.ring_index > 0 and not common_touch_heights(entries):
                    # Bases with no common height (spike beside a heart or curl) leave side mode (spec 3.2).
                    assert r.contact_mode != "side"
                    continue
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
        if name == "leaf":
            return {**entry, "side_touch_heights": ("mid",), "max_overflow_inward": 0.2}
        return entry
    monkeypatch.setattr(composer_module, "find_motif", fake)
    c = Composer(1, GEOM, ComposerSettings(categories=["botanical", "geometric"]))
    # petal (base only) and leaf (made mid only, with inward overflow) share no height, but both overflow inward.
    seq = [CellEntry(CellRecipe("petal", "botanical"), None), CellEntry(CellRecipe("leaf", "botanical"), None)]
    assert c._contact_mode(1, seq) == "overflow"
    # The safe band touches at mid height only and has no inward overflow.
    seq = [CellEntry(CellRecipe("petal", "botanical"), CellRecipe("botanical_safe_band", "botanical"))]
    assert c._contact_mode(1, seq) == "stem"


def test_floating_node_in_base_height_ring_tries_only_base_capable_bases():
    from composer import CellRecipe, CellEntry
    # The first floating repair of a petal in a side ring substitutes another base touching at the
    # ring's height. Band is a seam motif, so it qualifies at either height; it is a candidate because the
    # sequence has one entry (a seam motif fills its whole position).
    picked = {"base": set(), "mid": set()}
    for ring_seed in range(30):
        for height in ("base", "mid"):
            c = Composer(1, GEOM, ComposerSettings(categories=["botanical", "geometric"]))
            ring = RingPlan(1, 12, 1.0, [CellEntry(CellRecipe("petal", "botanical"), None)], ring_seed,
                            contact_mode="side", touch_height=height)
            assert c.replace_node(ring, 0, "centre", "floating") is True
            picked[height].add(ring.sequence[0].centre.motif)
            assert ring.contact_mode == "side" and ring.touch_height == height
    # Each pick touches at the ring's height: the base-only spike appears only at base height, the mid-only heart
    # only at mid height (the curl's gates exclude it from this cell).
    assert picked == {"base": {"leaf", "band", "teardrop", "rounded_petal", "spike"},
                      "mid": {"leaf", "band", "teardrop", "rounded_petal", "heart"}}
    for height, names in picked.items():
        assert all(height in touch_heights_of(find_motif(name)) for name in names)


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


SEAM_NAMES = {"band", "scallop"}


def _seam_plans():
    for seed in range(40):
        for vary in (False, True):
            yield Composer(seed, GEOM, ComposerSettings(complexity=1.0, vary_divisions=vary,
                                                        categories=["botanical", "geometric"])).plan()


def test_seam_motif_at_entry_zero_fills_its_whole_position():
    copied = 0
    for p in _seam_plans():
        for r in p.rings:
            for position in ("centre", "divider"):
                nodes = [getattr(e, position) for e in r.sequence]
                if nodes[0] is None:
                    continue
                if nodes[0].motif in SEAM_NAMES:
                    assert all(n.motif == nodes[0].motif for n in nodes)
                    copied += len(nodes) > 1
                else:
                    assert all(n.motif not in SEAM_NAMES for n in nodes[1:])
    assert copied > 0


def test_seam_motifs_are_not_candidates_in_both_mode():
    both = 0
    for p in _seam_plans():
        for r in p.rings:
            if r.centre_share < 1.0:
                both += 1
                assert all(n.motif not in SEAM_NAMES for n in _base_nodes(r))
    assert both > 0


def test_seam_ring_is_side_at_any_height():
    heights = set()
    for p in _seam_plans():
        for r in p.rings[1:]:
            if {n.motif for n in _base_nodes(r)} <= SEAM_NAMES:
                assert r.contact_mode == "side"
                heights.add(r.touch_height)
    assert heights == {"base", "mid"}


def test_replace_node_on_a_seam_node_replaces_every_entry():
    from composer import CellRecipe, CellEntry
    c = Composer(1, GEOM, ComposerSettings(categories=["botanical", "geometric"]))
    seq = [CellEntry(CellRecipe("band", "geometric"), None) for _ in range(3)]
    ring = RingPlan(1, 12, 1.0, seq, 1, contact_mode="side", touch_height="mid")
    assert c.replace_node(ring, 1, "centre", "generation") is True
    names = [e.centre.motif for e in ring.sequence]
    assert names[0] != "band" and len(set(names)) == 1
    assert len({id(e.centre) for e in ring.sequence}) == 3


def test_replace_node_falls_back_in_every_entry_of_a_seam_position(monkeypatch):
    import composer as composer_module
    from composer import CellRecipe, CellEntry
    # Geometric now has other bases (bead, spike); keep the registry of the original case, where the band has
    # no substitute, so the repair has to fall back to the safe band.
    real = composer_module.motifs_for_categories
    monkeypatch.setattr(composer_module, "motifs_for_categories",
                        lambda cats: [m for m in real(cats) if m["name"] not in ("bead", "spike")])
    c = Composer(1, GEOM, ComposerSettings(categories=["geometric"]))
    seq = [CellEntry(CellRecipe("band", "geometric"), None) for _ in range(2)]
    ring = RingPlan(1, 12, 1.0, seq, 1, contact_mode="side", touch_height="mid")
    assert c.replace_node(ring, 0, "centre", "generation") is True
    assert all(e.centre.is_fallback for e in ring.sequence)


def test_non_seam_substitute_never_brings_a_seam_into_a_longer_sequence():
    from composer import CellRecipe, CellEntry
    c = Composer(1, GEOM, ComposerSettings(categories=["botanical", "geometric"]))
    seq = [CellEntry(CellRecipe("petal", "botanical"), None), CellEntry(CellRecipe("leaf", "botanical"), None)]
    ring = RingPlan(1, 12, 1.0, seq, 1, contact_mode="side", touch_height="mid")
    steps = 0
    while c.replace_node(ring, 1, "centre", "generation") and not ring.sequence[1].centre.is_fallback:
        assert ring.sequence[1].centre.motif not in SEAM_NAMES
        assert ring.sequence[0].centre.motif == "petal"
        steps += 1
    assert steps > 0 and ring.sequence[1].centre.is_fallback


@pytest.mark.parametrize("role", ["base", "slot", "contact"])
def test_forced_seam_motif_is_rejected_in_both_mode(role):
    for name in ("band", "ring_band", "scallop"):
        with pytest.raises(ValueError, match="both"):
            Composer(1, GEOM, ComposerSettings(force_motif={"name": name, "position": "both", "role": role}))


def test_forced_seam_base_fills_its_whole_position():
    for seed in range(10):
        p = plan_for(seed, complexity=1.0, force_motif={"name": "band", "position": "centre", "role": "base"})
        for r in p.rings[1:]:
            assert all(e.centre.motif == "band" and e.divider is None for e in r.sequence)
            assert r.contact_mode == "side"


def test_every_cell_of_a_seam_ring_carries_a_stem():
    # A seam motif's open curves leave the space down to the inner ring one face per stem; a stem in every cell
    # (not once per wedge) cuts it into a face per cell.
    seen = 0
    for p in _seam_plans():
        for r in p.rings[1:]:
            nodes = _base_nodes(r)
            if nodes and {n.motif for n in nodes} <= SEAM_NAMES:
                seen += 1
                for n in nodes:
                    assert [a.motif for a in n.attachments] == ["stem"] and not n.attachments[0].once_per_wedge
    assert seen > 0


def test_embellishment_count_follows_complexity():
    entry = find_motif("petal")
    assert pick_embellishments(entry, 0.2, random.Random(1)) == []
    picks = [pick_embellishments(entry, 1.0, random.Random(s)) for s in range(50)]
    assert all(len(p) == 3 and sum(n in INTERIOR_FILLS for n in p) <= 1 for p in picks)


def test_embellishment_picks_are_ordered_unique_and_accepted():
    for name in ("petal", "leaf", "band"):
        entry = find_motif(name)
        for s in range(30):
            picks = pick_embellishments(entry, 0.7, random.Random(s))
            assert len(set(picks)) == len(picks) <= len(entry["embellishments"])
            assert set(picks) <= set(entry["embellishments"])
            assert picks == [n for n in EMBELLISHMENT_ORDER if n in picks]


def test_registry_embellishments():
    assert find_motif("petal")["embellishments"] == ("echo", "veins", "fan", "dot")
    assert find_motif("leaf")["embellishments"] == ("echo", "veins")
    assert find_motif("band")["embellishments"] == ("beads",)


def test_interior_fill_excludes_slot_child():
    seen = False
    for seed in range(40):
        for ring in plan_for(seed=seed, complexity=1.0).rings:
            for e in ring.sequence:
                for node in (e.centre, e.divider):
                    if node and set(node.embellishments) & set(INTERIOR_FILLS):
                        seen = True
                        assert node.slot_child is None
    assert seen, "some node picked an interior fill"


def test_base_nodes_get_embellishments_and_slot_children_do_not():
    # At complexity 0.7 some base nodes draw embellishments; slot children never do (spec 6.4 picks base nodes).
    nodes = [n for seed in range(20) for ring in plan_for(seed=seed, complexity=0.7).rings
             for e in ring.sequence for n in (e.centre, e.divider) if n]
    assert any(n.embellishments for n in nodes)
    children = [n.slot_child for n in nodes if n.slot_child]
    assert children and all(c.embellishments == [] for c in children)


def test_low_complexity_plans_carry_no_embellishments():
    for seed in range(10):
        for ring in plan_for(seed=seed, complexity=0.2).rings:
            for e in ring.sequence:
                assert all(not n.embellishments for n in (e.centre, e.divider) if n)


def test_embellishments_round_trip_and_default_empty():
    recipe = CellRecipe("petal", "botanical", embellishments=["echo", "dot"])
    assert CellRecipe.from_dict(recipe.to_dict()).embellishments == ["echo", "dot"]
    d = recipe.to_dict()
    del d["embellishments"]
    assert CellRecipe.from_dict(d).embellishments == []


# ------------------------------------------------------------------ layered rings (spec 5.1, 5.4)

def layered_plan(seed=123, **over):
    return plan_for(seed=seed, **{"categories": ["botanical"], "force_position_mode": "layered", **over})


def test_layered_is_never_ring_zero():
    for seed in range(30):
        for force in (None, "layered"):
            p = plan_for(seed=seed, categories=["botanical"], force_position_mode=force)
            assert p.rings[0].back is None and p.rings[0].position_mode != "layered"


def test_layered_rings_use_base_touch():
    seen = 0
    for seed in range(20):
        for ring in layered_plan(seed=seed).rings[1:]:
            assert ring.back is not None and ring.position_mode == "layered"
            seen += 1
            assert ring.touch_height == "base" and ring.contact_mode == "side"
            assert BASE_TOUCH_RANGE[0] <= ring.side_touch_radial <= BASE_TOUCH_RANGE[1]
            assert ring.centre_share == 1.0
            assert "back" in find_motif(ring.back.motif)["roles"]
            for entry in ring.sequence:
                assert entry.divider is None and entry.centre is not None
                front = find_motif(entry.centre.motif)
                assert "base" in touch_heights_of(front) and not front.get("seams", False)
    assert seen


def test_layered_mode_is_drawn_without_forcing():
    modes = {ring.position_mode for seed in range(40) for ring in plan_for(seed=seed, categories=["botanical"]).rings[1:]}
    assert "layered" in modes


def test_back_round_trips_and_defaults_off():
    from composer import DesignPlan
    p = layered_plan()
    assert DesignPlan.from_json(p.to_json()) == p
    d = p.rings[1].to_dict()
    assert d["back"]["motif"] == p.rings[1].back.motif and d["back_dropped"] is False
    for key in ("back", "back_dropped", "position_mode"):
        d.pop(key)
    loaded = RingPlan.from_dict(d)
    assert loaded.back is None and loaded.back_dropped is False and loaded.position_mode == "centre"


def test_back_is_picked_from_its_own_stream(monkeypatch):
    # The back pick never shifts the fronts: with the back pick stubbed out, the centre entries are the same.
    p = layered_plan(seed=5, complexity=0.9)
    assert any(ring.back.embellishments for seed in range(20) for ring in layered_plan(seed=seed, complexity=0.9).rings[1:])
    monkeypatch.setattr(Composer, "_plan_back", lambda self, *args: CellRecipe("leaf", "botanical"))
    stubbed = layered_plan(seed=5, complexity=0.9)
    assert [[e.to_dict() for e in r.sequence] for r in p.rings] == [[e.to_dict() for e in r.sequence] for r in stubbed.rings]
    assert [r.side_touch_radial for r in p.rings] == [r.side_touch_radial for r in stubbed.rings]


def test_force_position_mode_cannot_combine_with_force_motif():
    with pytest.raises(ValueError):
        Composer(1, GEOM, ComposerSettings(force_position_mode="layered",
                                           force_motif={"name": "petal", "position": "centre", "role": "base"}))


def test_drop_back_keeps_the_centre_entries_and_sets_centre_mode():
    settings = ComposerSettings(categories=["botanical"], force_position_mode="layered")
    c = Composer(123, GEOM, settings)
    p = c.plan()
    ring = p.rings[1]
    before = [entry.to_dict() for entry in ring.sequence]
    c.drop_back(ring)
    assert ring.back is None and ring.back_dropped is True and ring.position_mode == "centre"
    assert [entry.to_dict() for entry in ring.sequence] == before


def test_forced_position_mode_is_validated():
    with pytest.raises(ValueError):
        Composer(1, GEOM, ComposerSettings(force_position_mode="sideways"))


def test_safe_fallback_in_a_layered_ring_drops_its_back():
    settings = ComposerSettings(categories=["botanical"], force_position_mode="layered")
    c = Composer(123, GEOM, settings)
    ring = c.plan().rings[1]
    while c.replace_node(ring, 0, "centre", "generation"):
        if ring.sequence[0].centre.is_fallback:
            break
    assert ring.sequence[0].centre.is_fallback
    assert ring.back is None and ring.back_dropped and ring.position_mode == "centre"


# ---------------------------------------------------------------- forced embellishments

def _base_recipes(plan):
    return [node for ring in plan.rings for entry in ring.sequence
            for node in (entry.centre, entry.divider) if node is not None]


@pytest.mark.parametrize("forced", [("dot",), ("fan", "dot"), ("veins",), ("beads",)])
def test_forced_embellishments_join_every_accepting_base(forced):
    for seed in (1, 2, 3):
        plain = plan_for(seed=seed, complexity=0.5)
        plan = plan_for(seed=seed, complexity=0.5, force_embellishments=forced)
        for before, node in zip(_base_recipes(plain), _base_recipes(plan)):
            accepted = find_motif(node.motif)["embellishments"] if find_motif(node.motif) else ()
            for name in forced:
                assert (name in node.embellishments) == (name in accepted), (node.motif, node.embellishments)
            fills = [name for name in node.embellishments if name in INTERIOR_FILLS]
            assert len(fills) <= 1
            if fills:
                assert node.slot_child is None
            # Forcing only adds: picks that do not clash with a forced interior fill are kept, in order.
            kept = [n for n in before.embellishments
                    if not (n in INTERIOR_FILLS and any(f in INTERIOR_FILLS and f != n for f in forced))]
            assert set(kept) <= set(node.embellishments)
            assert node.embellishments == [n for n in EMBELLISHMENT_ORDER if n in node.embellishments]


def test_forced_embellishments_reach_a_layered_back():
    backs = [ring.back for seed in range(1, 9)
             for ring in plan_for(seed=seed, categories=["botanical"], force_position_mode="layered",
                                  force_embellishments=("echo", "dot")).rings if ring.back is not None]
    assert backs and all("echo" in back.embellishments for back in backs)
    assert all("dot" in back.embellishments for back in backs if back.motif == "petal")
    assert any(back.motif == "petal" for back in backs)


def test_no_forced_embellishments_leaves_the_plan_unchanged():
    assert plan_for(seed=9).to_json() == plan_for(seed=9, force_embellishments=()).to_json()


@pytest.mark.parametrize("bad", [("sparkle",), ("veins", "fan"), ("dot", "dot")])
def test_forced_embellishments_are_validated(bad):
    with pytest.raises(ValueError):
        Composer(1, GEOM, ComposerSettings(force_embellishments=bad))


# ----- seam rings never stack (user feedback: bands joined by spokes look mechanical) -----

def _has_seam_base(ring):
    return any((find_motif(n.motif) or {}).get("seams", False) for n in _base_nodes(ring))


def test_a_ring_after_a_seam_ring_plans_no_seam_base():
    seen = 0
    for seed in range(60):
        for vary in (False, True):
            for complexity in (0.3, 0.9):
                p = Composer(seed, GEOM, ComposerSettings(complexity=complexity, vary_divisions=vary,
                                                          categories=["botanical", "geometric"])).plan()
                for inner, outer in zip(p.rings, p.rings[1:]):
                    if _has_seam_base(inner):
                        seen += 1
                        assert not _has_seam_base(outer), (seed, vary, complexity, outer.ring_index)
    assert seen > 100  # ring 0 is a seam ring in every plan, so the rule is exercised


def test_ring_zero_still_gets_a_spans_cell_seam_base():
    for seed in range(20):
        p = plan_for(seed)
        assert _has_seam_base(p.rings[0]) and not any(n.is_fallback for n in _base_nodes(p.rings[0]))


def test_substitute_avoids_a_seam_base_beside_a_seam_ring():
    from composer import CellEntry
    c = Composer(1, GEOM, ComposerSettings(categories=["botanical", "geometric"]))
    plan = c.plan()
    assert _has_seam_base(plan.rings[0])
    ring = plan.rings[1]
    ring.sequence = [CellEntry(CellRecipe("petal", "botanical"), None)]
    ring.contact_mode, ring.touch_height, ring.back, ring.centre_share = "side", "mid", None, 1.0
    picked = []
    while c.replace_node(ring, 0, "centre", "generation") and not ring.sequence[0].centre.is_fallback:
        picked.append(ring.sequence[0].centre.motif)
    assert picked and not set(picked) & SEAM_NAMES
    assert ring.sequence[0].centre.is_fallback


def test_substitute_avoids_a_seam_base_inside_a_seam_ring():
    # The outward neighbour counts too: a ring under a seam ring never substitutes a seam motif.
    from composer import CellEntry
    c = Composer(1, GEOM, ComposerSettings(categories=["botanical", "geometric"]))
    plan = c.plan()
    outer = plan.rings[2]
    outer.sequence = [CellEntry(CellRecipe("scallop", "botanical"), None)]
    ring = plan.rings[1]
    ring.sequence = [CellEntry(CellRecipe("petal", "botanical"), None)]
    ring.contact_mode, ring.touch_height, ring.back, ring.centre_share = "side", "mid", None, 1.0
    plan.rings[0].sequence = [CellEntry(CellRecipe("petal", "botanical"), None)]
    picked = []
    while c.replace_node(ring, 0, "centre", "generation") and not ring.sequence[0].centre.is_fallback:
        picked.append(ring.sequence[0].centre.motif)
    assert picked and not set(picked) & SEAM_NAMES


def test_substitute_prefers_a_base_its_neighbours_do_not_use():
    # The base both neighbours use is avoided while another candidate is left, whatever the ring seed.
    from composer import CellEntry
    c = Composer(1, GEOM, ComposerSettings(categories=["botanical", "geometric"]))
    plan = c.plan()
    ring = plan.rings[1]
    for used, current in (("leaf", "band"), ("petal", "leaf")):
        category = find_motif(used)["category"]
        plan.rings[0].sequence = [CellEntry(CellRecipe(used, category), None)]
        plan.rings[2].sequence = [CellEntry(CellRecipe(used, category), None)]
        picked = set()
        for ring_seed in range(1000, 1012):
            ring.ring_seed = ring_seed
            ring.sequence = [CellEntry(CellRecipe(current, find_motif(current)["category"]), None)]
            ring.contact_mode, ring.touch_height, ring.back, ring.centre_share = "side", "mid", None, 1.0
            assert c.replace_node(ring, 0, "centre", "generation") is True
            picked.add(ring.sequence[0].centre.motif)
        assert used not in picked and current not in picked, (used, picked)


# ----- regenerated rings look outward too (a regeneration never stacks under a canonical seam ring) -----

def _stacked(plan):
    return [(a.ring_index, b.ring_index) for a, b in zip(plan.rings, plan.rings[1:])
            if _has_seam_base(a) and _has_seam_base(b)]


def test_regenerated_ring_never_takes_a_seam_base_under_a_canonical_seam_ring():
    # Reported case: seed 11 with ring 2 regenerated (ring seed 1001) planned a band under the canonical band.
    p = plan_for(11, ring_seeds={2: 1001})
    assert _has_seam_base(p.rings[3])
    assert not _has_seam_base(p.rings[2])
    assert _stacked(p) == []


def test_single_ring_regenerations_never_stack_seam_rings():
    for seed in range(25):
        for ring in range(len(GEOM)):
            for k in range(9):
                p = plan_for(seed, ring_seeds={ring: 1000 + k})
                assert _stacked(p) == [], (seed, ring, 1000 + k)


def test_regenerated_ring_plan_depends_only_on_the_design_seed_and_its_ring_seed():
    # Looking outward reads only the canonical outer ring, so the other rings' seeds never leak in.
    alone = plan_for(11, ring_seeds={2: 1001}).rings[2]
    with_inner = plan_for(11, ring_seeds={1: 77, 2: 1001}).rings[2]
    with_both = plan_for(11, ring_seeds={1: 77, 2: 1001, 3: 5}).rings[2]
    assert alone.to_dict() == with_inner.to_dict() == with_both.to_dict()
