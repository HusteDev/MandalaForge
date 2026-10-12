import pytest
from app import app

@pytest.fixture
def client():
    app.testing = True
    return app.test_client()

BASE = {"seed": 42, "num_rings": 3, "num_divisions": 8, "complexity": 0.5,
        "min_pattern_size": 10, "categories": ["botanical", "geometric"]}

def test_generate_returns_plan_and_summary(client):
    data = client.post("/generate", json=BASE).get_json()
    assert data["plan"]["rings"][0]["divisions"] == 8
    assert "floating_base_count" in data["validation"]
    assert "pattern_usage" not in data

def test_ring_divisions_wrong_length_is_400(client):
    r = client.post("/generate", json={**BASE, "ring_divisions": [8, 8]})
    assert r.status_code == 400 and "ring_divisions" in r.get_json()["error"]

def test_ring_divisions_out_of_range_is_400(client):
    r = client.post("/generate", json={**BASE, "ring_divisions": [8, 8, 30]})
    assert r.status_code == 400

def test_regenerate_ring_round_trips_prior_seeds(client):
    first = client.post("/regenerate-ring", json={**BASE, "ring_index": 1, "ring_seed": 5}).get_json()
    second = client.post("/regenerate-ring", json={**BASE, "ring_index": 2, "ring_seed": 9,
                                                   "ring_seeds": first["ring_seeds"]}).get_json()
    assert second["ring_seeds"] == {"1": 5, "2": 9}
    assert second["plan"]["rings"][1] == first["plan"]["rings"][1]

def test_regenerate_ring_index_out_of_range_is_400(client):
    r = client.post("/regenerate-ring", json={**BASE, "ring_index": 7})
    assert r.status_code == 400

def test_stale_ring_seeds_key_is_dropped(client):
    r = client.post("/generate", json={**BASE, "ring_seeds": {"7": 3}})
    assert r.status_code == 200
    assert r.get_json()["ring_seeds"] == {}

@pytest.mark.parametrize("bad", [{"1": None}, {"1": 1.5}, {"1": [3]}, {"1": {"a": 1}}, {"1": True}, {"x": 3}, "nope"])
def test_malformed_ring_seeds_is_400(client, bad):
    r = client.post("/generate", json={**BASE, "ring_seeds": bad})
    assert r.status_code == 400 and "ring_seeds" in r.get_json()["error"]

def test_regenerate_ring_without_ring_index_is_400(client):
    r = client.post("/regenerate-ring", json=BASE)
    assert r.status_code == 400 and "ring_index" in r.get_json()["error"]

def test_regenerate_ring_without_seed_is_400(client):
    body = {k: v for k, v in BASE.items() if k != "seed"}
    r = client.post("/regenerate-ring", json={**body, "ring_index": 1})
    assert r.status_code == 400 and "seed" in r.get_json()["error"]

def test_regenerate_ring_wrong_length_ring_divisions_is_400(client):
    r = client.post("/regenerate-ring", json={**BASE, "ring_index": 1, "ring_divisions": [8, 8]})
    assert r.status_code == 400 and "ring_divisions" in r.get_json()["error"]


VARY_BASE = {**BASE, "num_rings": 4, "num_divisions": 12}

@pytest.mark.parametrize("off", ["false", "0", "", "FALSE", False, 0])
def test_vary_divisions_false_strings_give_uniform_rings(client, off):
    r = client.post("/generate", json={**VARY_BASE, "vary_divisions": off})
    assert r.status_code == 200
    assert all(ring["divisions"] == 12 for ring in r.get_json()["plan"]["rings"])

@pytest.mark.parametrize("on", ["true", "1", True, 1])
def test_vary_divisions_true_values_vary_the_rings(client, on):
    r = client.post("/generate", json={**VARY_BASE, "vary_divisions": on})
    assert r.status_code == 200
    assert any(ring["divisions"] != 12 for ring in r.get_json()["plan"]["rings"])

@pytest.mark.parametrize("bad", ["maybe", 1.5, [], {}])
def test_malformed_vary_divisions_is_400(client, bad):
    r = client.post("/generate", json={**VARY_BASE, "vary_divisions": bad})
    assert r.status_code == 400 and "vary_divisions" in r.get_json()["error"]

def test_generate_accepts_force_motif_naming_ring_band(client):
    r = client.post("/generate", json={**BASE, "force_motif": {"name": "ring_band", "position": "centre", "role": "base"}})
    assert r.status_code == 200, r.get_json()
    data = r.get_json()
    assert data["validation"]["is_valid"]
    assert all(e["centre"]["motif"] == "band" for ring in data["plan"]["rings"][1:] for e in ring["sequence"])

def test_generate_rejects_a_malformed_force_motif(client):
    r = client.post("/generate", json={**BASE, "force_motif": {"name": "nope", "position": "centre", "role": "base"}})
    assert r.status_code == 400
    r = client.post("/generate", json={**BASE, "force_motif": "band"})
    assert r.status_code == 400


def _has_seam_motif(ring):
    from motifs import find_motif
    return any((find_motif(n["motif"]) or {}).get("seams")
               for e in ring["sequence"] for n in (e["centre"], e["divider"]) if n)


# The seam case regenerates ring 2: ring 1 sits on ring 0, always a seam ring, so it never takes a seam motif.
@pytest.mark.parametrize("seed, ring_index, ring_seed, kind", [(22, 2, 9, "layered"), (20, 2, 13, "seam")])
def test_regenerate_ring_with_a_new_ring_seed_keeps_seams_meeting(client, seed, ring_index, ring_seed, kind):
    # Every cell of the regenerated ring takes the new ring stream together: a back layer's halves and a seam
    # motif's ends still meet across every divider, so nothing dangles and the design validates.
    body = {**BASE, "categories": ["botanical", "geometric"], "seed": seed,
            "ring_index": ring_index, "ring_seed": ring_seed}
    data = client.post("/regenerate-ring", json=body).get_json()
    ring = data["plan"]["rings"][ring_index]
    assert ring["ring_seed"] == ring_seed
    if kind == "layered":
        assert ring["position_mode"] == "layered" and ring["back"] is not None
    else:
        assert _has_seam_motif(ring)
    assert data["validation"]["is_valid"], data["validation"]["issues"][:5]
    assert data["validation"]["dangling_end_count"] == 0
