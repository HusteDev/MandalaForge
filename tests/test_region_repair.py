"""The region-cap repair ladder (max-region-size spec 5): the engine, plan replay and each step."""

import pytest

from coloring_generator import DesignGenerator
from composer import CellEntry, CellRecipe, Composer, ComposerSettings, DesignPlan, RingPlan
from region_repair import classify_faces, face_sets, has_seam_base

# Seeds whose pre-cap design (max_region_cap=False, ring_divisions unset) has an oversized face set of each
# kind, found by scanning seeds 0 to 199 at complexity 0.5 and 0.85, botanical and geometric. Each is the
# only oversized set of its design: a ring 3 divider host, a ring 2 background in a `both` ring, and the open
# centre. The ring 2 background in a centre-mode ring (seed 4, 0.85) also has a small open-centre set: at 0.5
# every centre-mode background ring holds a curl, too wide for `both` mode, so step 2 cannot switch it.
HOST_SEED = {"seed": 16, "complexity": 0.5, "categories": ["botanical"]}
BACKGROUND_CENTRE_MODE_SEED = {"seed": 4, "complexity": 0.85, "categories": ["botanical"]}
BACKGROUND_BOTH_SEED = {"seed": 19, "complexity": 0.5, "categories": ["geometric"]}
CENTRE_SEED = {"seed": 3, "complexity": 0.5, "categories": ["botanical"]}


def gen(case, **over):
    """The pinned case's generator, with `over` applied."""
    return DesignGenerator(**{**case, **over})


def composer_for(seed, **settings):
    """A composer on the rings of seed `seed`'s default generator."""
    g = DesignGenerator(seed=seed)
    return Composer(seed, g.rings, ComposerSettings(**settings))


def plan_for(seed, **settings):
    return composer_for(seed, **settings).plan()


def oversized_regions(g):
    """The last design's faces over the cap, measured against the cap even when the generator has it off."""
    if g.max_region_cap:
        return g.last_validation_result.oversized_regions
    g.max_region_cap = True
    try:
        return g._validation_report(g.assembled)[0].oversized_regions
    finally:
        g.max_region_cap = False


def sets_of(g):
    return face_sets(classify_faces(oversized_regions(g), g.assembled.paths, g.rings, g.center))


def area_of(g, key):
    return next((s.area for s in sets_of(g) if s.key == key), 0.0)


def test_host_step_shrinks_the_set_and_records_it():
    off = gen(HOST_SEED, max_region_cap=False); off.generate()
    key = next(s.key for s in sets_of(off) if s.kind == "host")
    g = gen(HOST_SEED); g.generate()
    assert g.last_validation_result.is_valid
    assert any(r["step"] == 1 and r["change"].startswith(("embellishment:", "slot_child:")) for r in g.plan.repairs)
    assert area_of(g, key) < area_of(off, key)           # 0.0 once the set is under the cap


def test_step_one_respects_the_interior_fill_rule():
    ring = RingPlan(1, 8, 1.0, [CellEntry(CellRecipe("petal", "botanical", embellishments=["veins"]), None)], 0)
    c = composer_for(seed=3)
    assert not c.add_embellishment(ring, "centre", (0,), False, "fan")
    assert c.add_embellishment(ring, "centre", (0,), False, "echo")
    assert ring.sequence[0].centre.embellishments == ["echo", "veins"]
    assert not c.add_embellishment(ring, "centre", (0,), False, "beads")   # petal does not accept beads


def test_a_step_that_fails_validation_is_undone(monkeypatch):
    real = DesignGenerator._trial
    def failing(self, plan):
        trial = real(self, plan)
        if trial is not None and plan.repairs:
            trial.report.is_valid = False
        return trial
    monkeypatch.setattr(DesignGenerator, "_trial", failing)
    assert gen(HOST_SEED).generate() == gen(HOST_SEED, max_region_cap=False).generate()


def test_ladder_runs_without_validation():
    assert gen(HOST_SEED).generate(validate=False) == gen(HOST_SEED).generate()


def test_repaired_plan_replays_without_the_ladder():
    g = gen(HOST_SEED); svg = g.generate()
    plan = DesignPlan.from_json(g.source_plan.to_json())
    assert gen(HOST_SEED).generate_from_plan(plan) == svg


def test_old_plan_json_loads_without_repairs():
    d = plan_for(seed=3).to_dict(); d.pop("repairs")
    assert DesignPlan.from_dict(d).repairs == []


# ------------------------------------------------------------------ step 2, fill the background

def background_area(g, ring_index):
    return area_of(g, ("background", ring_index))


@pytest.mark.parametrize("case", [BACKGROUND_CENTRE_MODE_SEED, BACKGROUND_BOTH_SEED])
def test_background_step(case):
    g = gen(case); g.generate()
    assert g.last_validation_result.is_valid
    step2 = [r for r in g.plan.repairs if r["step"] == 2]
    assert step2 and step2[0]["change"] in ("position_mode:both", "size_floor")
    assert background_area(g, step2[0]["ring"]) < background_area(gen_done(case, max_region_cap=False), step2[0]["ring"])


def test_background_step_switches_a_centre_ring_to_both():
    g = gen(BACKGROUND_CENTRE_MODE_SEED); g.generate()
    step2 = next(r for r in g.plan.repairs if r["step"] == 2)
    ring = g.plan.rings[step2["ring"]]
    assert step2["change"] == "position_mode:both" and ring.position_mode == "both"
    assert all(entry.divider is not None for entry in ring.sequence)


def gen_done(case, **over):
    g = gen(case, **over); g.generate()
    return g


def test_background_step_skips_layered_and_seam_rings():
    g = gen(BACKGROUND_CENTRE_MODE_SEED, force_position_mode="layered"); g.generate()
    for r in g.plan.repairs:
        ring = g.plan.rings[r["ring"]]
        assert r["step"] != 2 or (ring.position_mode != "layered" and not has_seam_base(ring))


def test_background_step_never_switches_a_forced_mode():
    g = gen(BACKGROUND_CENTRE_MODE_SEED, force_position_mode="centre"); g.generate()
    assert all(r["change"] != "position_mode:both" for r in g.plan.repairs)


def test_background_repaired_plan_round_trips_and_replays():
    g = gen(BACKGROUND_CENTRE_MODE_SEED); svg = g.generate()
    plan = DesignPlan.from_json(g.source_plan.to_json())
    assert plan.to_json() == g.source_plan.to_json()
    assert gen(BACKGROUND_CENTRE_MODE_SEED).generate_from_plan(plan) == svg
