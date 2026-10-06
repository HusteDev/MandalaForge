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


def test_overflow_run_with_a_neighbour_touch_at_its_tip_passes():
    # Overflow runs were checked from interpolated ends off the drawn segment, so the validator
    # saw a ring-2 petal edge cross a run of ring-1 ink that was never drawn.
    job = ("stem", "botanical", (8, 8, 8, 12), 0.9, 10, "both", "contact", 20260821, False)
    assert run_case(job)["status"] == "PASS"


def test_stem_reach_does_not_close_a_slit_between_overflowing_petals():
    # A 2.6px stem reach from a ring-3 petal tip bridged a slit beside a ring-2 petal, closing it into a face no pen fits.
    job = ("stem", "botanical", (8, 8, 8, 12), 0.5, 10, "divider", "contact", 20260821, False)
    assert run_case(job)["status"] == "PASS"
