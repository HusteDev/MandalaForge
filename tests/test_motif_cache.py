"""The per-design motif memo (`motifs/cache.py`): byte-identical designs, exact streams, cached errors, purity."""

import hashlib
import random
from dataclasses import fields, replace

import pytest

from coloring_generator import DesignGenerator
from composer import DesignPlan
from motifs import find_motif
from motifs.cache import ContextMutated, MotifCache, _key_fields, call_generator
from motifs.contract import MotifError
from motifs.geometry import CellPoint, MotifContext
from motifs.layering import compose_layered
from tests.test_motifs import make_ctx

SIX_RING = {"seed": 7, "num_rings": 6, "complexity": 0.85, "categories": ["botanical", "geometric"],
            "vary_divisions": True}
LAYERED = {"seed": 42, "force_position_mode": "layered"}
LAYERED_MIXED = {"seed": 11, "force_position_mode": "layered", "complexity": 0.85,
                 "categories": ["botanical", "geometric"]}
VARIED = {"seed": 23, "vary_divisions": True, "categories": ["botanical", "geometric"]}
ROSETTE = {"seed": 2}          # its open centre is repaired with a rosette (step 3)

DESIGNS = {"six": SIX_RING, "layered": LAYERED, "layered_mixed": LAYERED_MIXED, "varied": VARIED, "rosette": ROSETTE}

# (SVG sha256, source_plan JSON sha256) of designs drawn with the memo off, re-pinned after the motif roadmap B
# merge changed the designs (the originals came from the engine before the memo, commit c2cd833).
PINNED = {
    ("six", True): ("fc6a74f8288c46f189c8b3920484b8f3fbcffec5b6396989354a735b880f706f",
                    "c6523dfb5a94c7c1c65712ac9c6e77a44e4c0a3a4224750e16f938a9e3cebed8"),
    ("rosette", True): ("11144a402797d5302660f7e7ad17c473040e770db61e75cd7a2b16147752d323",
                        "9f97d5f6477744553f2537abb81b1237f08ca8404761552eb92423ca04c31a47"),
    ("layered", True): ("f94df0046d49b77b414abc08461fb0f8ec23e37f3b938f9d0c7a0cc2ddd9b008",
                        "b43c3a5d67156df970c7aa9fcc4d85e31343e6f551dc33d3796869adc22d577c"),
    ("varied", True): ("046b61dc3c00cdbe77947b20d06a7798553a14b9af8d4a02db474c3dd53460e4",
                       "57a233e7cd3df98e2b1b694f886659a61d27a737a82757fc9f8bd7c689574831"),
    ("varied", False): ("25f282f57cfa5fbaa48a46c976c3ac8f75e80a0dea8ff90c61ef246b02d6e6c9",
                        "d9a8d392050548ae79e7eebd045f1eac5711e19e015dd956615310f39706f0c3"),
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
    """These pins were drawn with the memo off, so they pass with it and without it."""
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


# A different valid value for every non-stream field of MotifContext (the cell_kwargs fixture's context).
CHANGED_FIELDS = {
    "inner_radius": 101.0,
    "outer_radius": 161.0,
    "wedge_angle": 31.0,
    "center": (307.0, 306.0),
    "stroke_width": 1.6,
    "complexity": 0.5000000000000001,            # bit-exact floats
    "min_white_space": 10.5,
    "position": "divider",
    "angular_limits": 0.9,
    "radial_limits": (0.0, 0.9),
    "slot": [CellPoint(0.2, -0.4), CellPoint(0.2, 0.4), CellPoint(0.8, 0.4), CellPoint(0.8, -0.4)],
    "side_touch_radial": 0.3,
    "ring_stream_seed": 5,
    "node_seed": 6,
    "embellishments": ("echo",),
    "size_floor": 0.7,
}


def test_the_key_holds_every_field_but_the_streams():
    names = {f.name for f in fields(MotifContext)} - {"rng", "ring_rng"}
    assert set(_key_fields()) == names
    assert set(CHANGED_FIELDS) == names            # a new context field must be added to CHANGED_FIELDS


def test_every_context_field_and_both_streams_are_in_the_key(cell_kwargs):
    calls = []

    def recording(context):
        calls.append(context)
        return "instance"

    entry = {"name": "recording", "generator": recording}
    cache = MotifCache()
    base = make_ctx(cell_kwargs, 11)
    cache.generate(entry, replace(base, rng=random.Random(11)))
    for name in sorted({f.name for f in fields(MotifContext)} - {"rng", "ring_rng"}):
        changed = replace(base, rng=random.Random(11), **{name: CHANGED_FIELDS[name]})
        assert getattr(changed, name) != getattr(base, name), name
        misses = cache.misses
        cache.generate(entry, changed)
        assert cache.misses == misses + 1 and cache.hits == 0, f"{name} is not in the key"
    cache.generate(entry, replace(base, rng=random.Random(12)))              # another rng state
    advanced = replace(base, rng=random.Random(11))
    advanced.ring_rng.random()                                               # same seed, advanced ring stream
    cache.generate(entry, advanced)
    cache.generate({"name": "other", "generator": recording}, replace(base, rng=random.Random(11)))
    assert cache.hits == 0 and len(calls) == cache.misses
    cache.generate(entry, replace(base, rng=random.Random(11)))              # the first context again: a hit
    assert cache.hits == 1


def test_transient_errors_are_never_stored(cell_kwargs):
    calls = []

    def flaky(context):
        calls.append(context)
        raise (RecursionError if len(calls) == 1 else MemoryError)("deep")

    cache = MotifCache()
    with pytest.raises(RecursionError):
        cache.generate({"name": "flaky", "generator": flaky}, make_ctx(cell_kwargs, 4))
    with pytest.raises(MemoryError):
        cache.generate({"name": "flaky", "generator": flaky}, make_ctx(cell_kwargs, 4))
    assert len(calls) == 2 and cache.hits == 0 and len(cache) == 0


def test_verify_catches_a_generator_that_replaces_a_stream(cell_kwargs):
    petal = find_motif("petal")

    def swapping(context):
        context.ring_rng = random.Random(1)
        return petal["generator"](context)

    with pytest.raises(ContextMutated, match="replaced a stream"):
        MotifCache(verify=True).generate({"name": "swapping", "generator": swapping}, make_ctx(cell_kwargs, 4))


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
