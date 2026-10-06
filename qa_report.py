"""
QA harness for MandalaForge designs.

Generates designs, runs topology validation, and writes a visual QA overlay per
design into test_output/: every colorable region filled with a random pastel,
defects marked in red (dangling ends get crosshairs, floating shapes and floating
base motifs get dashed boxes, un-colorable regions are filled solid red). Reaches
are traced in green on top.

Usage:
    python qa_report.py                  # 5 random seeds, default params
    python qa_report.py --seeds 1 2 3    # specific seeds
    python qa_report.py --rings 5 --divisions 8 --complexity 0.7 --vary
    python qa_report.py --corpus         # pinned regression corpus (180 designs)

Exits non-zero if any design fails validation, so it can gate CI.
"""

import argparse
import io
import os
import random
import sys
from concurrent.futures import ProcessPoolExecutor
from contextlib import redirect_stdout

from coloring_generator import DesignGenerator
from topology_validator import debug_overlay_svg, structural_components


# Pinned regression corpus: categories x complexities x seeds x division modes
# (uniform and varied). Complexity tiers matter because several motif code paths
# are complexity-gated, so a single tier misses most of them. Categories with no
# motifs yet (celtic, art_deco, abstract) stay in: the composer falls back to the
# per-category safe band, which is a legitimate case to keep passing.
CORPUS_CATEGORIES = ['botanical', 'geometric', 'celtic', 'art_deco', 'abstract']
CORPUS_SEEDS = [42, 777, 12345, 254302, 955789, 984322]
CORPUS_COMPLEXITIES = [0.15, 0.5, 0.85]
CORPUS_RINGS = 4
CORPUS_DIVISIONS = 12


def corpus_jobs(out_dir, overlay_mode, num_rings=CORPUS_RINGS, num_divisions=CORPUS_DIVISIONS):
    """The pinned corpus as run_one jobs: 5 categories x 3 complexities x 6 seeds x 2 division modes."""
    return [
        (seed, num_rings, num_divisions, complexity, [category], vary, out_dir, overlay_mode)
        for category in CORPUS_CATEGORIES
        for complexity in CORPUS_COMPLEXITIES
        for seed in CORPUS_SEEDS
        for vary in (False, True)
    ]


def floating_base_boxes(assembled):
    """
    Bounding boxes of the base paths the validator flags as floating: those
    outside the largest touching group of base paths (the same structural
    components over the assembled polylines and base mask the report counts).
    """
    polylines = assembled.polylines()
    mask = assembled.base_mask()
    ids = structural_components(polylines)
    base = [i for i in range(len(polylines)) if mask[i]]
    if not base:
        return []
    counts = {}
    for i in base:
        counts[ids[i]] = counts.get(ids[i], 0) + 1
    structure = min(counts, key=lambda c: (-counts[c], c))
    boxes = []
    for i in base:
        if ids[i] != structure:
            xs = [x for x, _ in polylines[i]]
            ys = [y for _, y in polylines[i]]
            boxes.append((min(xs), min(ys), max(xs), max(ys)))
    return boxes


def _plan_nodes(plan):
    return [
        node
        for ring in plan.rings
        for entry in ring.sequence
        for node in (entry.centre, entry.divider)
        if node is not None
    ]


def run_one(job):
    """Generate + validate one design. Runs in a worker process."""
    seed, num_rings, num_divisions, complexity, categories, vary, out_dir, overlay_mode = job
    label = f"{'-'.join(categories)}_c{complexity}_v{int(vary)}_s{seed}"

    chatter = io.StringIO()
    try:
        with redirect_stdout(chatter):
            generator = DesignGenerator(
                seed=seed,
                num_rings=num_rings,
                num_divisions=num_divisions,
                complexity=complexity,
                categories=categories,
                vary_divisions=vary,
            )
            svg = generator.generate()
    except Exception as exc:
        return {
            'label': label, 'seed': seed, 'complexity': complexity,
            'categories': categories, 'vary': vary, 'status': 'ERROR',
            'error': f"{type(exc).__name__}: {exc}"[:300],
            'stats': {}, 'issues': [], 'fallbacks': 0, 'patterns': [], 'reaches': 0,
        }

    report = generator.last_validation_result
    status = 'PASS' if report.is_valid else 'FAIL'
    assembled = generator.assembled
    nodes = _plan_nodes(generator.plan)

    if overlay_mode == 'always' or (overlay_mode == 'failures' and status != 'PASS'):
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, f"design_{label}.svg"), 'w', encoding='utf-8') as handle:
            handle.write(svg)
        overlay = debug_overlay_svg(
            report,
            generator.last_validation_polylines or [],
            size=(generator.width, generator.height),
            reach_lines=[path.coords for path in assembled.reaches],
            floating_base_boxes=floating_base_boxes(assembled),
        )
        with open(os.path.join(out_dir, f"qa_overlay_{label}.svg"), 'w', encoding='utf-8') as handle:
            handle.write(overlay)

    return {
        'label': label, 'seed': seed, 'complexity': complexity,
        'categories': categories, 'vary': vary, 'status': status, 'error': None,
        'stats': report.stats, 'issues': report.issues[:5],
        'fallbacks': sum(1 for node in nodes if node.is_fallback),
        'patterns': sorted({node.motif for node in nodes}),
        'reaches': len(assembled.reaches),
    }


def main():
    parser = argparse.ArgumentParser(description="Topology QA over generated designs")
    parser.add_argument('--corpus', action='store_true',
                        help="run the pinned regression corpus (categories x seeds x complexity)")
    parser.add_argument('--seeds', type=int, nargs='*', default=None)
    parser.add_argument('--count', type=int, default=5, help="random seeds if --seeds omitted")
    parser.add_argument('--rings', type=int, default=CORPUS_RINGS)
    parser.add_argument('--divisions', type=int, default=CORPUS_DIVISIONS,
                        help="divisions per ring (the base count when --vary)")
    parser.add_argument('--vary', action='store_true',
                        help="let each ring pick its own division count (non-corpus runs)")
    parser.add_argument('--complexity', type=float, default=0.5)
    parser.add_argument('--categories', nargs='*', default=['botanical'])
    parser.add_argument('--out', default='test_output')
    parser.add_argument('--jobs', type=int, default=max(1, (os.cpu_count() or 2) // 2))
    parser.add_argument('--overlays', choices=['always', 'failures', 'never'], default=None,
                        help="when to write overlay SVGs (default: always, or failures for --corpus)")
    args = parser.parse_args()

    if args.corpus:
        overlay_mode = args.overlays or 'failures'
        jobs = corpus_jobs(args.out, overlay_mode, args.rings, args.divisions)
    else:
        overlay_mode = args.overlays or 'always'
        seeds = args.seeds if args.seeds else [random.randint(0, 1000000) for _ in range(args.count)]
        jobs = [
            (seed, args.rings, args.divisions, args.complexity, args.categories, args.vary, args.out, overlay_mode)
            for seed in seeds
        ]

    os.makedirs(args.out, exist_ok=True)
    print(f"Running {len(jobs)} design(s) on {args.jobs} worker(s)...\n")

    if args.jobs > 1 and len(jobs) > 1:
        with ProcessPoolExecutor(max_workers=args.jobs) as pool:
            results = list(pool.map(run_one, jobs))
    else:
        results = [run_one(job) for job in jobs]

    print(f"{'DESIGN':38} {'STATUS':6} {'VARY':>4} {'REGIONS':>7} {'DANGL':>6} {'FLOAT':>5} "
          f"{'UNCOL':>5} {'LANE':>4} {'REACH':>5} {'FB':>3}")
    print("-" * 94)
    for result in results:
        stats = result['stats']
        print(f"{result['label']:38} {result['status']:6} {int(result['vary']):>4} "
              f"{stats.get('num_regions', 0):>7} {stats.get('num_dangles', 0):>6} "
              f"{stats.get('num_floating_open', 0):>5} "
              f"{stats.get('num_uncolorable_regions', 0):>5} "
              f"{stats.get('num_free_lanes', 0):>4} {result['reaches']:>5} {result['fallbacks']:>3}")

    bad = [r for r in results if r['status'] != 'PASS']
    if bad:
        print("\nFailures:")
        for result in bad:
            print(f"\n  {result['label']} [{result['status']}]")
            if result['error']:
                print(f"    {result['error']}")
            for issue in result['issues']:
                print(f"    - {issue}")

    fallback_total = sum(r['fallbacks'] for r in results)
    reach_total = sum(r['reaches'] for r in results)
    print("-" * 94)
    print(f"{len(results) - len(bad)}/{len(results)} designs passed. "
          f"Reaches: {reach_total}. Safe-fallback cells used: {fallback_total}.")
    if overlay_mode != 'never':
        scope = "failing designs" if overlay_mode == 'failures' else "all designs"
        print(f"Overlays for {scope} written to {args.out}/qa_overlay_<design>.svg")

    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
