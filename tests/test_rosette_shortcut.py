"""The rosette trial shortcut: a step 3 trial places its rosette on a copy of the stored pre-rosette assembly."""

import copy

import pytest

from assembler import Assembler, ROSETTE_NODE
from coloring_generator import DesignGenerator
from composer import CellRecipe, DesignPlan

CENTRE_SEED = {"seed": 2}                 # its only oversized set is the open centre: step 3 adds a rosette
LAYERED = {"seed": 42, "force_position_mode": "layered"}
VARIED = {"seed": 23, "vary_divisions": True, "categories": ["botanical", "geometric"]}
# A varied design whose first assembly leaves its plan unchanged, so it is kept for a rosette trial.
VARIED_KEPT = {"seed": 22, "vary_divisions": True, "categories": ["botanical", "geometric"]}
LAYERED_MIXED = {"seed": 11, "force_position_mode": "layered", "complexity": 0.85,
                 "categories": ["botanical", "geometric"]}
# Designs whose step 3 trial is shortcut: the plan it adds the rosette to was assembled unchanged. (Seed 7's six
# rings and default seed 42 layered are not: their first assembly adds stems or drops a back, so a full trial runs.)
SHORTCUT_CASES = [CENTRE_SEED, {"seed": 10}, {"seed": 4, "complexity": 0.85}, LAYERED_MIXED]


def gen(case, **over):
    return DesignGenerator(**{**case, "max_region_cap": True, **over})


def assembler_state(a):
    """Everything pass one and pass two leave behind, as plain values."""
    paths = [(p.ring_index, p.cell_index, p.position, tuple(p.node_path), p.role, list(p.coords), list(p.radials),
              p.closed, p.stroke_width) for p in a.paths]
    nodes = [(n.ring_index, n.cell_index, n.position, n.node_path, n.rng_seed, n.instance, n.attachment_seeds,
              n.child_dropped, sorted(n.resolved_sides), n.pull_backs, n.back_seed, n.recipe.to_dict()) for n in a.nodes]
    reaches = [list(p.coords) for p in a.reaches]
    pending = [(n.ring_index, n.cell_index, n.position, n.node_path, end, point, rotation)
               for n, end, point, rotation in a.pending_reaches]
    return paths, nodes, reaches, pending, a.dropped_children, a.dropped_attachments


def strip(plan_dict, rosette=True):
    """A plan's dict without its repairs, `dropped` flags and (with `rosette`) the innermost ring's rosette."""
    def walk(value):
        if isinstance(value, dict):
            return {k: walk(v) for k, v in value.items() if k != "dropped"}
        if isinstance(value, list):
            return [walk(v) for v in value]
        return value
    d = walk(plan_dict)
    d.pop("repairs")
    if rosette:
        min(d["rings"], key=lambda r: r["ring_index"])["rosette"] = None
    return d


@pytest.mark.parametrize("case", [CENTRE_SEED, LAYERED, VARIED, {"seed": 777, "complexity": 0.85,
                                                                 "categories": ["geometric"]}])
def test_pass_one_and_two_never_read_rosette_repairs_or_dropped(case):
    g = gen(case, max_region_cap=False)
    plain_plan = g._new_composer().plan()
    marked_plan = copy.deepcopy(plain_plan)
    min(marked_plan.rings, key=lambda r: r.ring_index).rosette = CellRecipe("rosette", "geometric")
    marked_plan.repairs.append({"step": 3, "kind": "centre", "ring": 0, "change": "rosette"})
    def mark(recipe):
        if recipe is None:
            return
        recipe.dropped = True
        mark(recipe.slot_child)
        for attachment in recipe.attachments:
            mark(attachment)

    for ring in marked_plan.rings:
        for entry in ring.sequence:
            mark(entry.centre)
            mark(entry.divider)
        mark(ring.back)
        mark(ring.rosette)
    assert any(ring.back is not None for ring in marked_plan.rings) or case is not LAYERED
    states = []
    for plan in (plain_plan, marked_plan):
        composer = g._new_composer()
        composer.adopt(plan)
        a = Assembler(plan, g.rings, g.center, g.complexity, g.min_pattern_size, composer)
        a.pass_one()
        a.pass_two()
        states.append((assembler_state(a), strip(plan.to_dict())))
    plain, marked = states
    assert plain[1] == marked[1]
    # Node recipes differ only in the flags set above.
    assert [n[:-1] for n in plain[0][1]] == [n[:-1] for n in marked[0][1]]
    assert plain[0][0] == marked[0][0] and plain[0][2:] == marked[0][2:]


def trial_outputs(trial):
    report = trial.report
    return (trial.source_plan.to_json(), trial.plan.to_json(), trial.polylines, [p.role for p in trial.assembled.paths],
            report.is_valid, report.issues, report.stats, [(s.key, s.area) for s in trial.sets],
            trial.assembled.rosette_dropped, trial.assembled.dropped_children, trial.assembled.dropped_embellishments,
            assembler_state_of(trial.assembled))


def assembler_state_of(assembled):
    return [(n.ring_index, n.cell_index, n.position, n.node_path, n.instance) for n in assembled.nodes]


def spy_shortcut(monkeypatch):
    used = []
    real = DesignGenerator._reuse_pre_rosette

    def spy(self, plan, composer):
        result = real(self, plan, composer)
        used.append(result is not None)
        return result

    monkeypatch.setattr(DesignGenerator, "_reuse_pre_rosette", spy)
    return used


@pytest.mark.parametrize("case", SHORTCUT_CASES)
def test_shortcut_and_full_trial_give_identical_designs(case, monkeypatch):
    used = spy_shortcut(monkeypatch)
    fast = gen(case)
    fast_svg = fast.generate()
    assert any(used)
    slow = gen(case)
    slow.use_rosette_shortcut = False
    used.clear()
    slow_svg = slow.generate()
    assert not any(used)
    assert fast_svg == slow_svg and fast.source_plan.to_json() == slow.source_plan.to_json()
    fr, sr = fast.last_validation_result, slow.last_validation_result
    assert (fr.is_valid, fr.issues, fr.stats) == (sr.is_valid, sr.issues, sr.stats)
    assert any(p.node_path == (ROSETTE_NODE,) for p in fast.assembled.paths)
    replay = gen(case).generate_from_plan(DesignPlan.from_json(fast.source_plan.to_json()))
    assert replay == fast_svg


@pytest.mark.parametrize("case", [CENTRE_SEED, LAYERED_MIXED, VARIED_KEPT])
def test_a_shortcut_trial_equals_the_full_trial(case):
    """Straight through `_trial`: the first design's plan with a rosette, with and without the stored state."""
    g = gen(case, max_region_cap=True)
    with g._design_scope():
        g.composer = g._new_composer()
        g.plan = g.composer.plan()
        g._assemble()
        assert len(g._pre_rosette) == 1
        plan = copy.deepcopy(g.plan)
        min(plan.rings, key=lambda r: r.ring_index).rosette = CellRecipe("rosette", "geometric")
        plan.repairs.append({"step": 3, "kind": "centre", "ring": 0, "change": "rosette"})
        assert g._reuse_pre_rosette(copy.deepcopy(plan), g._new_composer()) is not None
        fast = g._trial(plan)
        stored = dict(g._pre_rosette)
        g._pre_rosette.clear()
        slow = g._trial(plan)
        g._pre_rosette.update(stored)
        again = g._trial(plan)                          # the stored state is copied, never spent
    assert trial_outputs(fast) == trial_outputs(slow) == trial_outputs(again)


def test_an_assembly_that_changes_its_plan_is_not_kept():
    g = gen(LAYERED)                                   # its first assembly adds stems and drops ring 2's back
    with g._design_scope():
        g.composer = g._new_composer()
        g.plan = g.composer.plan()
        g._assemble()
        assert g._pre_rosette == {}


def test_a_changed_plan_is_never_shortcut():
    g = gen(CENTRE_SEED)
    with g._design_scope():
        g.composer = g._new_composer()
        g.plan = g.composer.plan()
        g._assemble()
        base = copy.deepcopy(g.plan)
        min(base.rings, key=lambda r: r.ring_index).rosette = CellRecipe("rosette", "geometric")

        def reused(edit):
            plan = copy.deepcopy(base)
            edit(plan)
            return g._reuse_pre_rosette(plan, g._new_composer()) is not None

        assert reused(lambda p: None)
        assert reused(lambda p: p.repairs.append({"step": 3}))
        assert not reused(lambda p: setattr(p.rings[-1], "ring_seed", p.rings[-1].ring_seed + 1))
        assert not reused(lambda p: p.rings[1].sequence[0].centre.embellishments.append("echo")
                          if p.rings[1].sequence[0].centre else p.rings[1].sequence[0].divider.embellishments.append("echo"))
        assert not reused(lambda p: setattr(min(p.rings, key=lambda r: r.ring_index), "rosette", None))
        flipped = next(r for ring in base.rings for e in ring.sequence for r in (e.centre, e.divider) if r is not None)
        assert not reused(lambda p: setattr(next(r for ring in p.rings for e in ring.sequence
                                                 for r in (e.centre, e.divider) if r is not None),
                                            "dropped", not flipped.dropped))


def test_the_store_is_dropped_with_the_design():
    g = gen(CENTRE_SEED)
    g.generate()
    assert g._pre_rosette is None
    off = gen(CENTRE_SEED, max_region_cap=False)
    with off._design_scope():
        off.composer = off._new_composer()
        off.plan = off.composer.plan()
        off._assemble()
        assert off._pre_rosette is None              # nothing is kept without the cap: no trial could use it
