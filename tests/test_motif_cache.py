"""The per-design motif memo (`motifs/cache.py`): byte-identical designs, exact streams, cached errors, purity."""

import hashlib
import random
from dataclasses import replace

import pytest

from coloring_generator import DesignGenerator
from composer import DesignPlan
from motifs import find_motif
from motifs.cache import ContextMutated, MotifCache, call_generator
from motifs.contract import MotifError
from motifs.layering import compose_layered
from tests.test_motifs import make_ctx

SIX_RING = {"seed": 7, "num_rings": 6, "complexity": 0.85, "categories": ["botanical", "geometric"],
            "vary_divisions": True}
LAYERED = {"seed": 42, "force_position_mode": "layered"}
LAYERED_MIXED = {"seed": 11, "force_position_mode": "layered", "complexity": 0.85,
                 "categories": ["botanical", "geometric"]}
VARIED = {"seed": 23, "vary_divisions": True, "categories": ["botanical", "geometric"]}
ROSETTE = {"seed": 3}          # its open centre is repaired with a rosette (step 3)

DESIGNS = {"six": SIX_RING, "layered": LAYERED, "layered_mixed": LAYERED_MIXED, "varied": VARIED, "rosette": ROSETTE}

# (SVG sha256, source_plan JSON sha256) of designs from the engine before the memo (commit c2cd833).
PINNED = {
    ("six", True): ("ccba2be0368ed99eb2485d1996d6c4d7313d53551398e9b8279413ecc0de82a5",
                    "bab3b1c6f91548c0153ee56f977d372d3ca47ada0c3e701a9a79d018d70f0a7e"),
    ("rosette", True): ("cffe4dc40a6cfffe0a67b071fc7c4774c2c9e8407ead9dcfba7b84e839a50d1b",
                        "3181da3b88d994ba05da9ef9967278cfbdce4929bb476a9f8c3ec61d2e8a3838"),
    ("layered", True): ("c479704d49f62b27c534df6c4060bf378dcb9e0fe305a25078d413e59292eb92",
                        "a1cebeb6fdc0dea761229010754253a71035d41563150e3ceacb53bbfc464498"),
    ("varied", True): ("7ab5c10e9075097159b14f0ea1c7c8aa54aa9fafe448a9457443fdfb1c74a435",
                       "c7e96f4851501e7fbe85cd1cbdf33271dbbe308a1e7169652437b0fb7c2f086c"),
    ("varied", False): ("6ebb9f3f688cdcf710337e3aa17ab0a1e64e1bf6bf0d570672d2a639a0cb7787",
                        "71886f7de0c00ef98d98ce9359e8c582c7d947a9cf207f90c3df4d37bc8095bd"),
}


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build(case, cap, cache, verify=False):
    g = DesignGenerator(**case, max_region_cap=cap)
    g.use_motif_cache = cache
    g.motif_cache_verify = verify
    svg = g.generate()
    return g, svg


def outputs(g, svg):
    report = g.last_validation_result
    return (sha(svg), g.source_plan.to_json(), report.is_valid, report.issues, len(report.regions),
            len(report.oversized_regions))


# ------------------------------------------------------------------ whole designs


@pytest.mark.parametrize("key", sorted(PINNED), ids=lambda key: f"{key[0]}-cap-{'on' if key[1] else 'off'}")
def test_designs_match_the_engine_before_the_memo(key):
    """These pins were taken before the memo existed, so they pass with it and without it."""
    case, cap = DESIGNS[key[0]], key[1]
    g, svg = build(case, cap, cache=True)
    assert (sha(svg), sha(g.source_plan.to_json())) == PINNED[key]


@pytest.mark.parametrize("name,cap", [("rosette", True), ("layered", True), ("layered", False), ("varied", True),
                                      ("varied", False), ("layered_mixed", True), ("six", False)])
def test_memo_on_and_off_give_identical_designs(name, cap):
    case = DESIGNS[name]
    on, on_svg = build(case, cap, cache=True, verify=True)       # verify: no generator changes its context
    off, off_svg = build(case, cap, cache=False)
    assert outputs(on, on_svg) == outputs(off, off_svg)
    replay = DesignGenerator(**case, max_region_cap=cap).generate_from_plan(DesignPlan.from_json(on.source_plan.to_json()))
    assert replay == on_svg


def test_each_design_gets_its_own_memo_shared_by_its_trials(monkeypatch):
    made = []
    real_init = MotifCache.__init__

    def init(self, *args, **kwargs):
        real_init(self, *args, **kwargs)
        made.append(self)

    monkeypatch.setattr(MotifCache, "__init__", init)
    g = DesignGenerator(**ROSETTE, max_region_cap=True)
    g.generate()
    assert g.plan.repairs                                        # trials ran, all on the one memo
    assert len(made) == 1 and g._motif_cache is None
    assert made[0].hits > made[0].misses > 0                     # repeats across cells and trials hit
    g.generate_from_plan(DesignPlan.from_json(g.source_plan.to_json()))
    assert len(made) == 2 and made[1] is not made[0] and g._motif_cache is None


def test_the_memo_off_makes_none(monkeypatch):
    made = []
    monkeypatch.setattr(MotifCache, "__init__", lambda self, *a, **k: made.append(self))
    g = DesignGenerator(seed=5)
    g.use_motif_cache = False
    g.generate()
    assert made == []


# ------------------------------------------------------------------ one call


def counting(generator):
    calls = []

    def wrapped(context):
        calls.append(context)
        return generator(context)

    return wrapped, calls


def test_a_hit_returns_a_private_copy_and_the_streams_of_a_real_call(cell_kwargs):
    petal = find_motif("petal")
    generator, calls = counting(petal["generator"])
    entry = {**petal, "generator": generator}
    plain_context = make_ctx(cell_kwargs, 11)
    plain = petal["generator"](plain_context)

    cache = MotifCache(verify=True)
    first_context, second_context = make_ctx(cell_kwargs, 11), make_ctx(cell_kwargs, 11)
    first = cache.generate(entry, first_context)
    second = cache.generate(entry, second_context)
    assert len(calls) == 1 and (cache.hits, cache.misses) == (1, 1)
    for context in (first_context, second_context):
        assert context.rng.getstate() == plain_context.rng.getstate()
        assert context.ring_rng.getstate() == plain_context.ring_rng.getstate()
    assert first == plain and second == plain and second is not first
    second.vectors.clear()
    second.declaration.reach_ends.append(None)
    assert cache.generate(entry, make_ctx(cell_kwargs, 11)) == plain       # a caller's edits never reach the memo


def test_every_context_field_and_both_streams_are_in_the_key(cell_kwargs):
    petal = find_motif("petal")
    generator, calls = counting(petal["generator"])
    entry = {**petal, "generator": generator}
    cache = MotifCache()
    base = make_ctx(cell_kwargs, 11)

    def draw(e, context):
        try:
            cache.generate(e, context)
        except MotifError:
            pass

    draw(entry, replace(base, rng=random.Random(11)))
    variants = [
        replace(base, rng=random.Random(12)),                                   # another rng state
        replace(base, rng=random.Random(11), ring_stream_seed=5),               # another ring stream
        replace(base, rng=random.Random(11), radial_limits=(0.0, 0.9)),
        replace(base, rng=random.Random(11), complexity=0.5000000000000001),    # bit-exact floats
        replace(base, rng=random.Random(11), embellishments=("echo",)),
        replace(base, rng=random.Random(11), size_floor=0.7),
    ]
    advanced = replace(base, rng=random.Random(11))
    advanced.ring_rng.random()                                                # same seed, advanced stream
    for context in variants + [advanced]:
        draw(entry, context)
    assert len(calls) == 1 + len(variants) + 1 and cache.hits == 0
    draw(find_motif("leaf"), replace(base, rng=random.Random(11)))                # another motif, same context
    assert cache.hits == 0


def test_a_cached_error_is_raised_again_with_its_streams(cell_kwargs):
    calls = []

    def failing(context):
        calls.append(context)
        context.rng.random()
        context.ring_rng.random()
        context.ring_rng.random()
        raise MotifError("no room for the drop", 3)

    entry = {"name": "failing", "generator": failing}
    plain_context = make_ctx(cell_kwargs, 4)
    with pytest.raises(MotifError):
        failing(plain_context)
    calls.clear()

    cache = MotifCache()
    raised = []
    for _ in range(2):
        context = make_ctx(cell_kwargs, 4)
        with pytest.raises(MotifError) as info:
            cache.generate(entry, context)
        raised.append(info.value)
        assert context.rng.getstate() == plain_context.rng.getstate()
        assert context.ring_rng.getstate() == plain_context.ring_rng.getstate()
    assert len(calls) == 1 and cache.hits == 1
    assert type(raised[1]) is MotifError and raised[1].args == ("no room for the drop", 3)
    assert raised[1] is not raised[0]


def test_a_layering_error_keeps_its_type(cell_kwargs):
    from motifs.layering import LayeringError

    def failing(context):
        raise LayeringError("back leaf failed: too narrow")

    cache = MotifCache()
    for _ in range(2):
        with pytest.raises(LayeringError, match="too narrow"):
            cache.generate({"name": "failing", "generator": failing}, make_ctx(cell_kwargs, 4))
    assert cache.hits == 1


def test_verify_catches_a_generator_that_changes_its_context(cell_kwargs):
    petal = find_motif("petal")

    def sloppy(context):
        context.radial_limits = (0.0, 0.5)
        return petal["generator"](context)

    with pytest.raises(ContextMutated):
        MotifCache(verify=True).generate({"name": "sloppy", "generator": sloppy}, make_ctx(cell_kwargs, 4))
    MotifCache().generate({"name": "sloppy", "generator": sloppy}, make_ctx(cell_kwargs, 4))   # unchecked: no error


def test_layered_composites_are_unchanged_by_the_memo(cell_kwargs):
    front, back = find_motif("petal"), find_motif("leaf")

    def contexts():
        f = make_ctx(cell_kwargs, 3, side_touch_radial=0.12)
        b = replace(f, rng=random.Random(9), node_seed=9, position="divider", radial_limits=(0.0, 1.0),
                    side_touch_radial=None)
        return f, b

    plain = compose_layered(contexts()[0], front, contexts()[1], back)
    cache = MotifCache(verify=True)
    first = compose_layered(contexts()[0], cache.wrap(front), contexts()[1], cache.wrap(back))
    second = compose_layered(contexts()[0], cache.wrap(front), contexts()[1], cache.wrap(back))
    assert first == plain and second == plain and cache.hits == 2 and cache.misses == 2
    assert call_generator(front, contexts()[0]) == front["generator"](contexts()[0])
