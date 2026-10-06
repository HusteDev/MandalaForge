from qa_patterns import run_case, property_checks, MATRIX_SMOKE
from motifs import find_motif

def test_property_checks_pass_for_petal():
    assert all(property_checks(find_motif("petal")).values())

def test_run_case_passes_for_ring_band_base():
    job = ("ring_band", "geometric", (8, 8), 0.5, 10, "centre", "base", 1, False)
    assert run_case(job)["status"] == "PASS"

def test_run_case_skips_unsupported_role():
    job = ("diamond", "geometric", (8, 8), 0.5, 10, "centre", "base", 1, False)
    assert run_case(job)["status"] == "SKIP"

def test_smoke_matrix_contains_sketch_fixture():
    assert (8, 8, 8, 12) in MATRIX_SMOKE["ring_divisions"]
