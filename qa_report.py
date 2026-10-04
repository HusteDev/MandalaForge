"""
QA harness for MandalaForge designs.

Generates designs, runs topology validation, and writes a visual QA overlay per
design into test_output/: every colorable region filled with a random pastel,
defects marked in red (dangling ends get crosshairs, floating shapes get dashed
boxes, un-colorable regions are filled solid red).

Usage:
    python qa_report.py                  # 5 random seeds, default params
    python qa_report.py --seeds 1 2 3    # specific seeds
    python qa_report.py --rings 5 --divisions 8 --complexity 0.7
    python qa_report.py --corpus         # pinned regression corpus (90 designs)

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
from topology_validator import debug_overlay_svg


# Pinned regression corpus. Complexity tiers matter because several pattern
# code paths are complexity-gated (petal port splitting >=0.7, wavy edges
# >=0.82, stepped second band >=0.55), so a single tier misses most of them.
CORPUS_CATEGORIES = ['botanical', 'geometric', 'celtic', 'art_deco', 'abstract']
CORPUS_SEEDS = [42, 777, 12345, 254302, 955789, 984322]
CORPUS_COMPLEXITIES = [0.15, 0.5, 0.85]


def run_one(job):
    """Generate + validate one design. Runs in a worker process."""
    seed, num_rings, num_divisions, complexity, categories, out_dir, overlay_mode = job
    label = f"{'-'.join(categories)}_c{complexity}_s{seed}"

    chatter = io.StringIO()
    try:
        with redirect_stdout(chatter):
            generator = DesignGenerator(
                seed=seed,
                num_rings=num_rings,
                num_divisions=num_divisions,
                complexity=complexity,
                categories=categories,
            )
            svg = generator.generate()
    except Exception as exc:
        return {
            'label': label, 'seed': seed, 'complexity': complexity,
            'categories': categories, 'status': 'ERROR',
            'error': f"{type(exc).__name__}: {exc}"[:300],
            'stats': {}, 'issues': [], 'fallbacks': 0, 'patterns': [],
        }

    report = generator.last_validation_result
    status = 'PASS' if report.is_valid else 'FAIL'

    if overlay_mode == 'always' or (overlay_mode == 'failures' and status != 'PASS'):
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, f"design_{label}.svg"), 'w', encoding='utf-8') as handle:
            handle.write(svg)
        overlay = debug_overlay_svg(
            report,
            generator.last_validation_polylines or [],
            size=(generator.width, generator.height),
        )
        with open(os.path.join(out_dir, f"qa_overlay_{label}.svg"), 'w', encoding='utf-8') as handle:
            handle.write(overlay)

    return {
        'label': label, 'seed': seed, 'complexity': complexity,
        'categories': categories, 'status': status, 'error': None,
        'stats': report.stats, 'issues': report.issues[:5],
        'fallbacks': sum(1 for u in generator.pattern_usage if u.get('is_safe_fallback')),
        'patterns': sorted({u['name'] for u in generator.pattern_usage}),
    }


def main():
    parser = argparse.ArgumentParser(description="Topology QA over generated designs")
    parser.add_argument('--corpus', action='store_true',
                        help="run the pinned regression corpus (categories x seeds x complexity)")
    parser.add_argument('--seeds', type=int, nargs='*', default=None)
    parser.add_argument('--count', type=int, default=5, help="random seeds if --seeds omitted")
    parser.add_argument('--rings', type=int, default=4)
    parser.add_argument('--divisions', type=int, default=12)
    parser.add_argument('--complexity', type=float, default=0.5)
    parser.add_argument('--categories', nargs='*', default=['botanical'])
    parser.add_argument('--out', default='test_output')
    parser.add_argument('--jobs', type=int, default=max(1, (os.cpu_count() or 2) // 2))
    parser.add_argument('--overlays', choices=['always', 'failures', 'never'], default=None,
                        help="when to write overlay SVGs (default: always, or failures for --corpus)")
    args = parser.parse_args()

    if args.corpus:
        overlay_mode = args.overlays or 'failures'
        jobs = [
            (seed, args.rings, args.divisions, complexity, [category], args.out, overlay_mode)
            for category in CORPUS_CATEGORIES
            for complexity in CORPUS_COMPLEXITIES
            for seed in CORPUS_SEEDS
        ]
    else:
        overlay_mode = args.overlays or 'always'
        seeds = args.seeds if args.seeds else [random.randint(0, 1000000) for _ in range(args.count)]
        jobs = [
            (seed, args.rings, args.divisions, args.complexity, args.categories, args.out, overlay_mode)
            for seed in seeds
        ]

    os.makedirs(args.out, exist_ok=True)
    print(f"Running {len(jobs)} design(s) on {args.jobs} worker(s)...\n")

    if args.jobs > 1 and len(jobs) > 1:
        with ProcessPoolExecutor(max_workers=args.jobs) as pool:
            results = list(pool.map(run_one, jobs))
    else:
        results = [run_one(job) for job in jobs]

    print(f"{'DESIGN':38} {'STATUS':6} {'REGIONS':>7} {'DANGL':>6} {'FLOAT':>5} {'UNCOL':>5} {'LANE':>4} {'FB':>3}")
    print("-" * 82)
    for result in results:
        stats = result['stats']
        print(f"{result['label']:38} {result['status']:6} "
              f"{stats.get('num_regions', 0):>7} {stats.get('num_dangles', 0):>6} "
              f"{stats.get('num_floating_open', 0):>5} "
              f"{stats.get('num_uncolorable_regions', 0):>5} "
              f"{stats.get('num_free_lanes', 0):>4} {result['fallbacks']:>3}")

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
    print("-" * 82)
    print(f"{len(results) - len(bad)}/{len(results)} designs passed. "
          f"Safe-fallback cells used: {fallback_total}.")
    if overlay_mode != 'never':
        scope = "failing designs" if overlay_mode == 'failures' else "all designs"
        print(f"Overlays for {scope} written to {args.out}/qa_overlay_<design>.svg")

    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
