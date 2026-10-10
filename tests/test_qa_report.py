from qa_report import run_one, corpus_jobs

def test_corpus_has_both_division_modes():
    jobs = corpus_jobs(out_dir="test_output", overlay_mode="never")
    assert {j[5] for j in jobs} == {False, True} and len(jobs) == 180

def test_run_one_reports_reaches(tmp_path):
    result = run_one((42, 3, 8, 0.5, ["botanical"], True, str(tmp_path), "always"))
    assert result["status"] == "PASS" and result["reaches"] >= 0
    assert any(p.name.startswith("qa_overlay_") for p in tmp_path.iterdir())

def test_run_one_reports_base_symmetry_and_side_touch_rings(tmp_path):
    # Vary off: every ring has num_divisions cells, so B is num_divisions; botanical rings are side mode.
    result = run_one((42, 4, 12, 0.5, ["botanical"], False, str(tmp_path), "never"))
    assert result["base_symmetry"] == 12
    assert 1 <= result["side_touch_rings"] <= 4
    varied = run_one((42, 4, 12, 0.5, ["botanical"], True, str(tmp_path), "never"))
    assert varied["base_symmetry"] in (3, 4, 6)


def test_run_one_forces_a_position_mode_and_counts_layered_rings(tmp_path):
    result = run_one((42, 4, 8, 0.5, ["botanical"], False, str(tmp_path), "never", "layered"))
    assert result["status"] == "PASS"
    assert result["layered_rings"] + result["back_dropped_rings"] == 3
    assert result["layered_rings"] >= 1
