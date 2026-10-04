import random
import pytest
from motifs import MOTIFS, find_motif, safe_motif, motifs_for_categories
from motifs.geometry import MotifContext, CellPoint
from motifs.contract import MotifInstance, MotifError

def make_ctx(cell_kwargs, seed=7, **over):
    kw = {**cell_kwargs, "rng": random.Random(seed), **over}
    return MotifContext(**kw)

def slot_for(cell_kwargs):
    return [CellPoint(0.2, -0.4), CellPoint(0.2, 0.4), CellPoint(0.8, 0.4), CellPoint(0.8, -0.4)]

def all_entries():
    return MOTIFS + [safe_motif("botanical")]

def generate(entry, ctx, cell_kwargs):
    if "base" not in entry["roles"]:
        ctx.slot = slot_for(cell_kwargs)
    return entry["generator"](ctx)

@pytest.mark.parametrize("entry", all_entries(), ids=lambda e: e["name"])
def test_motif_is_deterministic(entry, cell_kwargs):
    a = generate(entry, make_ctx(cell_kwargs, 11), cell_kwargs)
    b = generate(entry, make_ctx(cell_kwargs, 11), cell_kwargs)
    assert [v.points for v in a.vectors] == [v.points for v in b.vectors]

@pytest.mark.parametrize("entry", all_entries(), ids=lambda e: e["name"])
def test_motif_respects_narrow_limits(entry, cell_kwargs):
    ctx = make_ctx(cell_kwargs, 3, radial_limits=(0.0, 1.0), angular_limits=0.5)
    inst = generate(entry, ctx, cell_kwargs)
    assert all(-0.03 <= p.radial <= 1.03 and abs(p.angular) <= 0.53 for v in inst.vectors for p in v.points)

@pytest.mark.parametrize("entry", all_entries(), ids=lambda e: e["name"])
def test_narrower_radial_limits_never_reach_further(entry, cell_kwargs):
    wide = generate(entry, make_ctx(cell_kwargs, 5, radial_limits=(-0.25, 1.25)), cell_kwargs)
    narrow = generate(entry, make_ctx(cell_kwargs, 5, radial_limits=(-0.1, 1.1)), cell_kwargs)
    hi = lambda inst: max(p.radial for v in inst.vectors for p in v.points) if inst.vectors else 0
    lo = lambda inst: min(p.radial for v in inst.vectors for p in v.points) if inst.vectors else 0
    assert hi(narrow) <= hi(wide) + 1e-9 and lo(narrow) >= lo(wide) - 1e-9

@pytest.mark.parametrize("entry", [e for e in all_entries() if e["slot_estimate"]], ids=lambda e: e["name"])
def test_declared_slot_is_present_at_default_size(entry, cell_kwargs):
    inst = generate(entry, make_ctx(cell_kwargs, 9), cell_kwargs)
    assert inst.declaration.slot is not None

def test_registry_lookup():
    assert find_motif("petal")["category"] == "botanical"
    assert find_motif("nope") is None
    assert {e["name"] for e in motifs_for_categories(["geometric"])} == {"diamond"}
    assert safe_motif("celtic")["name"] == "celtic_safe_band"

def test_diamond_requires_slot(cell_kwargs):
    with pytest.raises(MotifError):
        find_motif("diamond")["generator"](make_ctx(cell_kwargs))

def test_safe_band_spans_angular_limits(cell_kwargs):
    inst = safe_motif("botanical")["generator"](make_ctx(cell_kwargs, angular_limits=0.7))
    angs = {round(p.angular, 6) for p in inst.vectors[0].points}
    assert angs == {-0.7, 0.7}
