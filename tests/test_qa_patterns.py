import pytest
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


def test_overflow_and_reaches_touch_or_keep_pen_width_clear_of_other_rings():
    # Within a pen's width of ink a line either touches it or keeps clear. Every overflow part and every reach
    # stays at least 4px from every other-ring path, once both lose a 10px disc around each vertex the line's
    # path shares with any ink of that other ring.
    # Seed 3 (was the fixture seed 20260821 until touch heights re-drew every ring's side-touch radial):
    # the same stem/divider/contact job, with reaches and overflow runs, and rings touching at base height.
    import io
    from contextlib import redirect_stdout
    from shapely.geometry import LineString, MultiPoint
    from coloring_generator import DesignGenerator
    from placement import path_overflow
    with redirect_stdout(io.StringIO()):
        g = DesignGenerator(seed=3, num_rings=4, num_divisions=8, complexity=0.5, min_pattern_size=10,
                            categories=["botanical"], ring_divisions=[8, 8, 8, 12],
                            force_motif={"name": "stem", "position": "divider", "role": "contact"})
        g.generate()
    design = g.assembled
    lines = [(path, LineString(path.coords)) for path in design.paths if path.role == "reach"]
    runs = [(path, run) for path in design.paths for _, run in path_overflow(path, design.center)]
    assert lines and runs, "the scenario needs both reaches and overflow runs"
    assert any(r.touch_height == "base" for r in g.plan.rings)
    lines += runs
    ring_vertices = {}
    for path in design.paths:
        ring_vertices.setdefault(path.ring_index, set()).update(path.coords)
    for path, line in lines:
        for other in design.paths:
            if other.ring_index == path.ring_index or len(set(other.coords)) < 2:
                continue
            mine, ink = line, LineString(other.coords)
            shared = set(path.coords) & ring_vertices[other.ring_index]
            if shared:
                disc = MultiPoint(list(shared)).buffer(10.0)
                mine, ink = mine.difference(disc), ink.difference(disc)
            gap = float("inf") if mine.is_empty or ink.is_empty else mine.distance(ink)
            assert gap >= 4.0, (path.ring_index, path.cell_index, path.role, other.ring_index, other.cell_index, gap)


def test_forced_slot_motif_that_never_fits_fails():
    # At min size 25 no slot in the dense (24,24,24) fixture fits a diamond; the design still validates
    # without it, so the harness must check the forced motif was placed at all. The slot gate would SKIP
    # this fixture, so it runs as a probe (gates off) to reach the placement check.
    job = ("diamond", "geometric", (24, 24, 24), 0.5, 25, "centre", "slot", 20260821, True)
    outcome = run_case(job)
    assert outcome["status"] == "FAIL" and "never placed" in outcome["detail"]


def test_slot_job_is_gated_on_the_frames_measured_slot():
    # At min size 25 the petal frame drawn in each forced (24,24,24) ring declares no slot or one too small for a
    # diamond and two strokes. (The gate measures side-mode frames with their ring's side-touch radial, as the
    # assembler draws them; those span the whole cell, so at min size 10 the slot now admits the diamond.)
    job = ("diamond", "geometric", (24, 24, 24), 0.15, 25, "centre", "slot", 20260821, False)
    outcome = run_case(job)
    assert outcome["status"] == "SKIP" and "slot" in outcome["detail"]
    # The gate's verdict is the assembler's: run as a probe, the job never places the child.
    probe = run_case(job[:-1] + (True,))
    assert probe["status"] == "FAIL" and "never placed" in probe["detail"]


def test_case_label_carries_the_base_symmetry():
    # The base symmetry of an explicit division list is its gcd.
    assert "_B4_" in run_case(("diamond", "geometric", (8, 8, 8, 12), 0.5, 10, "centre", "base", 1, False))["label"]
    assert "_B1_" in run_case(("diamond", "geometric", (7, 12), 0.5, 10, "centre", "base", 1, False))["label"]


def test_slot_gate_draws_the_frame_the_assembler_draws():
    # The gate plans the fixture as the generator does and builds each forced ring's frame context from that plan:
    # the planned division count, centre share and, in a side-mode ring, the ring's side-touch radial.
    import io
    from contextlib import redirect_stdout
    from coloring_generator import DesignGenerator
    from qa_patterns import _fixture_plan, _frame_context
    with redirect_stdout(io.StringIO()):
        g = DesignGenerator(seed=20260821, num_rings=4, num_divisions=8, complexity=0.5, min_pattern_size=10,
                            categories=["geometric"], ring_divisions=[8, 8, 8, 12],
                            force_motif={"name": "diamond", "position": "both", "role": "slot"})
        plan = _fixture_plan(g)
        g.generate()
    # Assembly may replace nodes in the generator's plan; the ring-level draws are the plan's own.
    ring_fields = ("divisions", "centre_share", "side_touch_radial")
    assert ([[getattr(r, f) for f in ring_fields] for r in plan.rings]
            == [[getattr(r, f) for f in ring_fields] for r in g.plan.rings])
    assert any(r.centre_share < 1.0 for r in plan.rings[1:])
    assert any(r.contact_mode == "side" for r in plan.rings[1:])
    fields = ("wedge_angle", "position", "angular_limits", "side_touch_radial", "inner_radius", "outer_radius")
    for ring_plan in plan.rings[1:]:
        ours = _frame_context(g, ring_plan, "both")
        frame = next(n for n in g.assembled.nodes if n.ring_index == ring_plan.ring_index
                     and n.cell_index == 0 and n.position == "centre" and n.parent is None)
        assert [getattr(ours, f) for f in fields] == [getattr(frame.context, f) for f in fields]


def test_slot_gate_measures_every_forced_rings_real_frame():
    # At min size 30 the frames the assembler really draws in rings 1 to 3 (their own node streams) declare no
    # slot, one too narrow and one too shallow for a diamond and two strokes, so no ring admits it: SKIP, where
    # measuring one stand-in petal admitted it and the full tier reported "never placed". (Revision 2's longer
    # petals declare deeper slots, so min size 25 now admits a diamond in ring 2.)
    job = ("diamond", "geometric", (8, 8, 8, 12), 0.15, 30, "centre", "slot", 20260821, False)
    outcome = run_case(job)
    assert outcome["status"] == "SKIP" and "no forced ring admits" in outcome["detail"]
    # The gate's verdict is the assembler's: run as a probe, the job never places the child.
    probe = run_case(job[:-1] + (True,))
    assert probe["status"] == "FAIL" and "never placed" in probe["detail"]


def test_partial_slot_drops_pass_and_are_reported():
    # A forced ring's frame slot admits the child but some cells' real slots are smaller: the spec drops the
    # child there gracefully, so the job passes and carries its counts for the table's DROP column. With base
    # symmetry every cell of a uniform ring shares one recipe, so here one ring places and the other drops.
    # (Side-touching revision-2 petal frames span their whole cell, so (24, 24, 24) at min size 5 now fits
    # the child everywhere; (20, 20, 20) at min size 15 still drops it in one ring.)
    job = ("diamond", "geometric", (20, 20, 20), 0.9, 15, "centre", "slot", 1, False)
    outcome = run_case(job)
    assert outcome["status"] == "PASS"
    assert outcome["detail"] == "20 placed, 20 dropped" and outcome["dropped"] == 20


@pytest.mark.parametrize("job", [
    ("petal", "botanical", (24, 24, 24), 0.5, 25, "divider", "base", 20260821, False),
    ("stem", "botanical", (8, 8, 8, 12), 0.5, 25, "centre", "contact", 20260821, False),
    ("petal", "botanical", (8, 8, 8, 12), 0.15, 25, "divider", "base", 20260821, False),
])
def test_tips_nestled_into_each_others_rings_resolve_with_a_wide_touch_disc(job):
    # At min white space 25 the touch disc waives clearance around tips nestled across a ring boundary, so only the
    # crossing test judged them: pull-backs traded the crossing between the rings until both ran out ("still
    # crosses or crowds"), or left the tips beside each other in a slit no pen fits.
    assert run_case(job)["status"] == "PASS"


@pytest.mark.parametrize("name, category", [("band", "geometric"), ("scallop", "botanical")])
def test_seam_motifs_skip_both_mode(name, category):
    job = (name, category, (8, 8), 0.5, 10, "both", "base", 1, False)
    result = run_case(job)
    assert result["status"] == "SKIP" and "seam" in result["detail"]


def test_run_case_passes_for_band_base():
    job = ("band", "geometric", (8, 8, 8, 12), 0.5, 10, "centre", "base", 1, False)
    assert run_case(job)["status"] == "PASS"


@pytest.mark.parametrize("name", ["band", "scallop"])
def test_property_checks_pass_for_seam_motifs(name):
    assert all(property_checks(find_motif(name)).values())


@pytest.mark.parametrize("divisions", [(8, 8, 8, 12), (7, 12)])
def test_forced_scallop_meets_the_faces_per_cell_floor(divisions):
    job = ("scallop", "botanical", divisions, 0.5, 10, "divider", "base", 20260821, False)
    assert run_case(job)["status"] == "PASS"


def test_property_checks_include_seam_and_tangent():
    from motifs import MOTIFS
    for entry in MOTIFS:
        outcome = property_checks(entry)
        assert {"seam", "tangent"} <= set(outcome) and all(outcome.values()), (entry["name"], outcome)


def test_seam_check_fails_a_motif_whose_open_end_is_off_the_edge():
    from qa_patterns import _seam
    from motifs.geometry import CellPoint
    entry = dict(find_motif("band"))
    good = entry["generator"]

    def off_edge(context):
        instance = good(context)
        for vector in instance.vectors:
            if not vector.closed:
                vector.points[0] = CellPoint(vector.points[0].radial, 0.9)
        return instance

    assert _seam(entry)
    entry["generator"] = off_edge
    assert not _seam(entry)



def test_seam_check_accepts_an_open_end_on_another_vectors_vertex_only():
    from qa_patterns import _seam
    from motifs.geometry import CellPoint
    entry = dict(find_motif("rosette"))
    good = entry["generator"]

    def lobe_off_the_arc(context):
        instance = good(context)
        lobe = instance.vectors[1]
        lobe.points[0] = CellPoint(lobe.points[0].radial + 0.01, lobe.points[0].angular)
        return instance

    # The rosette's lobe ends rest on vertices of its dot arc, so they are accounted for; moved off, they dangle.
    assert _seam(entry)
    entry["generator"] = lobe_off_the_arc
    assert not _seam(entry)

def test_tangent_check_fails_a_motif_with_a_kinked_touch_vertex():
    from qa_patterns import _tangent
    from motifs.geometry import CellPoint
    entry = dict(find_motif("petal"))
    good = entry["generator"]

    def kinked(context):
        instance = good(context)
        pts = instance.vectors[0].points
        i = next(k for k, p in enumerate(pts) if p.angular == 1.0 and p.radial == context.side_touch_radial)
        pts[i - 1] = CellPoint(pts[i].radial, 0.6)
        pts[(i + 1) % len(pts)] = CellPoint(pts[i].radial, 0.9)
        return instance

    assert _tangent(entry)
    entry["generator"] = kinked
    assert not _tangent(entry)


def test_slot_job_whose_frames_are_pulled_back_below_the_gate_is_skipped():
    # The lotus petal's slot is deep enough in pass one, but pull-backs against the ring inside leave
    # every final slot shallower than the diamond's gate, so nothing could be placed: SKIP, not FAIL.
    job = ("diamond", "geometric", (8, 8, 8, 12), 0.15, 25, "centre", "slot", 20260821, False)
    result = run_case(job)
    assert result["status"] == "SKIP" and "final" in result["detail"], result


def _slot_job_generator(monkeypatch, valid):
    """Run the pulled-back diamond slot job (every final slot refuses it), optionally with an invalid report."""
    import coloring_generator
    if not valid:
        real = coloring_generator.DesignGenerator.generate

        def generate(self, *args, **kwargs):
            out = real(self, *args, **kwargs)
            self.last_validation_result.is_valid = False
            self.last_validation_result.issues = ["Un-colorable region at (1.0, 1.0) - injected"]
            return out
        monkeypatch.setattr(coloring_generator.DesignGenerator, "generate", generate)
    return ("diamond", "geometric", (8, 8, 8, 12), 0.15, 25, "centre", "slot", 20260821, False)


def test_refused_slot_job_with_an_invalid_design_fails(monkeypatch):
    result = run_case(_slot_job_generator(monkeypatch, valid=False))
    assert result["status"] == "FAIL" and "Un-colorable" in result["detail"], result


def test_final_slot_skip_is_tagged_in_the_detail():
    result = run_case(_slot_job_generator(None, valid=True))
    assert result["status"] == "SKIP" and result["detail"].startswith("[final-slot]"), result


def test_slot_job_with_an_admitting_final_slot_and_no_child_fails(monkeypatch):
    import qa_patterns
    monkeypatch.setattr(qa_patterns, "_final_slot_refusals", lambda entry, generator: [])
    result = run_case(_slot_job_generator(None, valid=True))
    assert result["status"] == "FAIL" and "never placed" in result["detail"], result


def test_tangent_check_needs_both_touch_vertices():
    from qa_patterns import _tangent
    entry = dict(find_motif("petal"))
    good = entry["generator"]

    def one_sided(context):
        instance = good(context)
        vector = instance.vectors[0]
        vector.points = [p for p in vector.points if not (p.angular == -1.0 and p.radial == context.side_touch_radial)]
        return instance

    entry["generator"] = one_sided
    assert not _tangent(entry)


def test_property_checks_include_cut_and_embellished():
    from motifs import MOTIFS
    for entry in MOTIFS:
        outcome = property_checks(entry)
        assert {"cut", "embellished"} <= set(outcome) and all(outcome.values()), (entry["name"], outcome)


def test_cut_check_fails_a_back_end_that_is_neither_a_seam_end_nor_a_front_vertex(monkeypatch):
    import qa_patterns
    from motifs.geometry import CellPoint
    real = qa_patterns.compose_layered

    def stray_end(front_context, front_entry, back_context, back_entry):
        instance = real(front_context, front_entry, back_context, back_entry)
        back = next(v for v in instance.vectors if v.layer == "back")
        back.points[-1] = CellPoint(back.points[-1].radial + 0.01, back.points[-1].angular * 0.5)
        return instance

    entry = find_motif("leaf")
    assert qa_patterns._cut(entry)
    monkeypatch.setattr(qa_patterns, "compose_layered", stray_end)
    assert not qa_patterns._cut(entry)


def test_cut_check_passes_a_motif_with_no_back_role():
    from qa_patterns import _cut
    assert _cut(find_motif("scallop"))


def test_embellished_check_fails_a_generator_whose_embellished_output_is_not_deterministic():
    import random
    from qa_patterns import _embellished
    entry = dict(find_motif("petal"))
    good = entry["generator"]
    noise = random.Random()

    def wobbly(context):
        instance = good(context)
        if context.embellishments:
            from motifs.geometry import CellPoint
            p = instance.vectors[-1].points[0]
            instance.vectors[-1].points[0] = CellPoint(p.radial, p.angular + noise.random() * 1e-3)
        return instance

    assert _embellished(entry)
    entry["generator"] = wobbly
    assert not _embellished(entry)


def test_embellishment_sets_keep_at_most_one_interior_fill():
    from qa_patterns import embellishment_sets
    assert embellishment_sets(find_motif("petal")) == [("echo", "veins", "dot"), ("echo", "fan", "dot")]
    assert embellishment_sets(find_motif("band")) == [("beads",)]
    assert embellishment_sets(find_motif("scallop")) == []


def test_matrix_covers_each_accepted_embellishment_and_each_front_back_pair():
    from qa_patterns import build_jobs, layered_pairs
    from motifs import MOTIFS
    jobs = build_jobs(MOTIFS, MATRIX_SMOKE, 1, False)
    variants = {(job[0], job[9]) for job in jobs if len(job) > 9 and job[9] is not None}
    for entry in MOTIFS:
        for name in entry["embellishments"]:
            assert (entry["name"], ("emb", name)) in variants
    assert ("petal", ("back", "leaf")) in variants and ("leaf", ("back", "petal")) in variants
    # Every non-seam base that touches at base height is a front; every back-role motif is a back.
    fronts = {"petal", "leaf", "teardrop", "rounded_petal", "bead", "spike"}
    backs = {"petal", "leaf", "teardrop", "rounded_petal", "spike"}
    assert set(layered_pairs()) == {(front, back) for front in fronts for back in backs}


def test_run_case_draws_a_forced_embellishment():
    job = ("petal", "botanical", (8, 8, 8, 12), 0.9, 10, "centre", "base", 20260821, False, ("emb", "veins"))
    result = run_case(job)
    assert result["status"] == "PASS" and "veins" in result["label"], result
    assert result["drawn"] >= 1, result


def test_run_case_runs_a_forced_front_and_back_in_a_layered_ring():
    job = ("leaf", "botanical", (8, 8, 8, 12), 0.5, 10, "layered", "base", 20260821, False, ("back", "petal"))
    result = run_case(job)
    assert result["status"] == "PASS" and "back-petal" in result["label"], result
    assert result["drawn"] + result["dropped"] >= 1, result


def test_slot_child_too_thin_for_a_pen_is_dropped_not_drawn():
    # A petal with a dot cut its slot shallow, and the leaf fitted into it could not hold a pen.
    job = ("petal", "botanical", (8, 8, 8, 12), 0.9, 5, "centre", "base", 20260821, False)
    assert run_case(job)["status"] == "PASS"
