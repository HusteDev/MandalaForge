"""The drop tip ornament (roadmap Phase A): a teardrop hung from the host's tip vertex."""
import random

import pytest

from motifs import find_motif
from motifs.embellish import EMBELLISHMENT_ORDER
from motifs.geometry import MotifContext

HOSTS = ["petal", "teardrop", "spike", "kite"]


def make_ctx(cell_kwargs, seed=7, **over):
    return MotifContext(**{**cell_kwargs, "rng": random.Random(seed), **over})


def with_drop(cell_kwargs, name, seed, embellishments=("drop",), **over):
    ctx = make_ctx(cell_kwargs, seed, min_white_space=6.0, embellishments=list(embellishments), **over)
    return ctx, find_motif(name)["generator"](ctx)


def test_drop_sits_after_dot_and_before_beads():
    assert EMBELLISHMENT_ORDER == ("echo", "veins", "fan", "dot", "drop", "beads")


@pytest.mark.parametrize("name", HOSTS)
def test_hosts_accept_the_drop(name):
    assert "drop" in find_motif(name)["embellishments"]


@pytest.mark.parametrize("name", HOSTS)
def test_drop_point_is_the_host_tip(name, cell_kwargs):
    drawn = 0
    for seed in range(10):
        _ctx, bare = with_drop(cell_kwargs, name, seed, embellishments=(), radial_limits=(-0.5, 1.6))
        _ctx, inst = with_drop(cell_kwargs, name, seed, radial_limits=(-0.5, 1.6))
        if inst.dropped_embellishments:
            continue
        drawn += 1
        assert len(inst.vectors) == len(bare.vectors) + 1
        drop = inst.vectors[-1]
        tip = inst.declaration.anatomy.tip
        assert drop.closed and drop.points[0] == tip and tip in inst.vectors[0].points
        assert all(p.radial > tip.radial for p in drop.points[1:])
    assert drawn >= 5


@pytest.mark.parametrize("name", HOSTS)
def test_drop_is_outline_weight(name, cell_kwargs):
    _ctx, inst = with_drop(cell_kwargs, name, 3, radial_limits=(-0.5, 1.6))
    assert inst.dropped_embellishments == 0 and inst.vectors[-1].weight == "outline"


@pytest.mark.parametrize("name", HOSTS)
def test_drop_is_dropped_without_room(name, cell_kwargs):
    checked = 0
    for seed in range(10):
        _ctx, bare = with_drop(cell_kwargs, name, seed, embellishments=(), radial_limits=(0.0, 1.0))
        _ctx, inst = with_drop(cell_kwargs, name, seed, radial_limits=(0.0, 1.0))
        top = max(p.radial for p in bare.vectors[0].points)
        if top < 0.99:
            continue
        checked += 1
        assert inst.dropped_embellishments == 1 and len(inst.vectors) == len(bare.vectors)
    assert checked > 0


@pytest.mark.parametrize("name", HOSTS)
def test_drop_is_deterministic_and_monotone(name, cell_kwargs):
    for seed in range(10):
        _ctx, a = with_drop(cell_kwargs, name, seed, radial_limits=(-0.5, 1.6))
        _ctx, b = with_drop(cell_kwargs, name, seed, radial_limits=(-0.5, 1.6))
        assert [v.points for v in a.vectors] == [v.points for v in b.vectors]
        reach = lambda inst: max(p.radial for v in inst.vectors for p in v.points)
        wide = reach(a)
        for high in (1.4, 1.2, 1.05):
            _ctx, narrow = with_drop(cell_kwargs, name, seed, radial_limits=(-0.5, high))
            assert reach(narrow) <= min(wide, high) + 1e-9
            wide = reach(narrow)


def test_drop_keeps_its_draws_when_another_embellishment_is_added(cell_kwargs):
    _ctx, alone = with_drop(cell_kwargs, "teardrop", 4, radial_limits=(-0.5, 1.6))
    _ctx, mixed = with_drop(cell_kwargs, "teardrop", 4, embellishments=("echo", "drop"), radial_limits=(-0.5, 1.6))
    assert alone.vectors[-1].points == mixed.vectors[-1].points
