from qa_report import run_one, corpus_jobs

def test_corpus_has_both_division_modes():
    jobs = corpus_jobs(out_dir="test_output", overlay_mode="never")
    assert {j[5] for j in jobs} == {False, True} and len(jobs) == 180

def test_run_one_reports_reaches(tmp_path):
    result = run_one((42, 3, 8, 0.5, ["botanical"], True, str(tmp_path), "always"))
    assert result["status"] == "PASS" and result["reaches"] >= 0
    assert any(p.name.startswith("qa_overlay_") for p in tmp_path.iterdir())
