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
    import io
    from contextlib import redirect_stdout
    from shapely.geometry import LineString, MultiPoint
    from coloring_generator import DesignGenerator
    from placement import path_overflow
    with redirect_stdout(io.StringIO()):
        g = DesignGenerator(seed=20260821, num_rings=4, num_divisions=8, complexity=0.5, min_pattern_size=10,
                            categories=["botanical"], ring_divisions=[8, 8, 8, 12],
                            force_motif={"name": "stem", "position": "divider", "role": "contact"})
        g.generate()
    design = g.assembled
    lines = [(path, LineString(path.coords)) for path in design.paths if path.role == "reach"]
    lines += [(path, run) for path in design.paths for _, run in path_overflow(path, design.center)]
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
