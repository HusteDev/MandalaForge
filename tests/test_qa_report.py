import pytest

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


def test_corpus_quotas_are_checked():
    from qa_report import corpus_quota_failures
    rows = [{"categories": ["botanical"], "layered_rings": 0, "rings": 4, "embellishments": {}}]
    failures = corpus_quota_failures(rows)
    assert failures   # names the layered share and each missing embellishment
    assert any("layered" in failure for failure in failures)
    for name in ("echo", "veins", "fan", "dot", "beads"):
        assert any(name in failure for failure in failures), (name, failures)


def test_corpus_quotas_pass_when_both_are_met():
    from qa_report import corpus_quota_failures
    counts = {name: 10 for name in ("echo", "veins", "fan", "dot", "drop", "beads")}
    rows = [
        {"categories": ["botanical"], "layered_rings": 1, "rings": 4, "embellishments": counts},
        {"categories": ["celtic"], "layered_rings": 0, "rings": 4, "embellishments": {}},
    ]
    assert corpus_quota_failures(rows) == []
    rows[0]["embellishments"] = dict(counts, dot=9)
    assert corpus_quota_failures(rows) == ["embellishment dot appears 9 times (< 10)"]


def test_corpus_forces_layered_on_the_layered_seeds():
    from qa_report import CORPUS_SEEDS, corpus_jobs
    jobs = corpus_jobs(out_dir="test_output", overlay_mode="never")
    forced = {job[0] for job in jobs if job[8] == "layered"}
    assert forced and forced <= set(CORPUS_SEEDS)
    assert set(CORPUS_SEEDS[:3]) <= forced


def test_corpus_keeps_natural_modes_only_on_its_unlayered_jobs():
    from qa_report import CORPUS_LAYERED_SEEDS, CORPUS_UNLAYERED_JOBS, corpus_jobs
    jobs = corpus_jobs(out_dir="test_output", overlay_mode="never")
    natural = {(job[4][0], job[3], job[0], job[5]) for job in jobs if job[0] in CORPUS_LAYERED_SEEDS and job[8] is None}
    assert natural == set(CORPUS_UNLAYERED_JOBS)


def test_run_one_counts_rings_and_drawn_embellishments(tmp_path):
    result = run_one((42, 4, 12, 0.85, ["botanical"], False, str(tmp_path), "never"))
    assert result["rings"] == 4
    assert sum(result["embellishments"].values()) >= 1, result["embellishments"]


def test_run_one_forces_embellishments(tmp_path):
    job = (42, 4, 12, 0.15, ["botanical"], False, str(tmp_path), "never", None, ("dot",))
    result = run_one(job)
    assert result["status"] == "PASS" and result["embellishments"].get("dot", 0) >= 1, result["embellishments"]


def test_corpus_forces_embellishments_only_on_its_chosen_jobs():
    from qa_report import CORPUS_EMBELLISHMENT_JOBS
    jobs = corpus_jobs(out_dir="test_output", overlay_mode="never")
    forced = [job for job in jobs if job[9]]
    assert forced and all((job[4][0], job[3], job[0], job[5]) in CORPUS_EMBELLISHMENT_JOBS for job in forced)
    assert len(jobs) == 180


def test_run_one_reports_oversized_regions(tmp_path):
    from topology_validator import max_region_in2
    row = run_one((42, 4, 12, 0.5, ["botanical"], False, str(tmp_path), "never"))
    # Seed 42 keeps no oversized face: its largest face (0.835 in2) is under the 0.925 in2 cap at complexity 0.5.
    assert isinstance(row["oversized"], int) and row["oversized"] == 0
    assert 0.0 < row["largest_in2"] <= max_region_in2(0.5) and row["largest_in2"] == pytest.approx(0.835, abs=0.001)


def test_oversized_ceiling_is_a_quota():
    from qa_report import corpus_quota_failures, OVERSIZED_DESIGN_CEILING
    counts = {name: 10 for name in ("echo", "veins", "fan", "dot", "beads")}
    rows = [{"categories": ["celtic"], "layered_rings": 0, "rings": 4, "embellishments": counts, "oversized": 1}
            for _ in range(OVERSIZED_DESIGN_CEILING + 1)]
    assert corpus_quota_failures(rows) == [
        f"oversized regions in {OVERSIZED_DESIGN_CEILING + 1} designs (> {OVERSIZED_DESIGN_CEILING})"]
