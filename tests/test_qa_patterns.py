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


def test_overflow_keeps_pen_width_clearance_outside_its_touch_disc():
    # Overflow may narrow to neighbour ink only within the touch disc around the run's extreme vertex
    # (and around any shared vertex); elsewhere it stays a pen's width clear, so no flank slides along a neighbour.
    # Disc 10px = max(min_white_space 10, 2 x 4px clearance).
    import io
    from contextlib import redirect_stdout
    import numpy as np
    import shapely
    from shapely.geometry import LineString, MultiPoint
    from coloring_generator import DesignGenerator
    from placement import path_overflow
    with redirect_stdout(io.StringIO()):
        g = DesignGenerator(seed=20260821, num_rings=4, num_divisions=8, complexity=0.5, min_pattern_size=10,
                            categories=["botanical"], ring_divisions=[8, 8, 8, 12],
                            force_motif={"name": "stem", "position": "divider", "role": "contact"})
        g.generate()
    design = g.assembled
    for path in design.paths:
        if path.role == "reach":
            continue
        for side, run in path_overflow(path, design.center):
            coords = shapely.get_coordinates(run)
            radii = np.hypot(coords[:, 0] - design.center[0], coords[:, 1] - design.center[1])
            extreme = coords[int(np.argmin(radii) if side == "inward" else np.argmax(radii))]
            for other in design.paths:
                if other.ring_index == path.ring_index or other.role == "reach":
                    continue
                shared = set(path.coords) & set(other.coords)
                disc = MultiPoint([tuple(extreme), *shared]).buffer(10.0)
                rest, ink = run.difference(disc), LineString(other.coords).difference(disc)
                assert rest.is_empty or ink.is_empty or rest.distance(ink) >= 4.0, (path.ring_index, path.cell_index, side)
