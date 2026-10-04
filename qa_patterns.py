"""
Per-pattern coverage harness.

`qa_report.py --corpus` only exercises whichever patterns random selection
happens to pick, so a pattern can ship untested — that is exactly how
`smart_resonance_ladder` stayed broken (rejected in ~70% of designs) while the
corpus reported 90/90.

This harness pins each registered pattern in turn and drives the REAL
generation pipeline over a parameter matrix, so every pattern is proven in
isolation. Forcing bypasses the ring-position and size gates (so a pattern is
probed outside its declared envelope) and disables the fallback chain (so a
rejection is a visible failure, not a silent substitution).

Usage:
    python qa_patterns.py                        # smoke tier, every pattern
    python qa_patterns.py --pattern smart_petal  # one pattern, verbose
    python qa_patterns.py --tier full
    python qa_patterns.py --list
"""

import argparse
import io
import math
import os
import random
import sys
from concurrent.futures import ProcessPoolExecutor
from contextlib import redirect_stdout

from coloring_generator import DesignGenerator
from smart_patterns import SMART_PATTERNS, get_safe_fallback_pattern

CATEGORIES = ['botanical', 'geometric', 'celtic', 'art_deco', 'abstract']

# divisions=6 with a large radius is the cell that reproduces the worst
# chord/arc error (~37px); it must stay in the smoke tier.
# ring_counts stay inside the UI's supported 2-7 range. rings=1 makes a pattern
# simultaneously first AND last, which the product cannot produce, so failures
# there would be chasing an unreachable configuration. rings=3 still covers
# first / middle / last plus two real ring interfaces.
SMOKE = {
    'divisions': (6, 12, 24),
    'ring_counts': (2, 3),
    'complexity': (0.15, 0.5, 0.9),
    'min_white': (10,),
}
FULL = {
    'divisions': (6, 8, 12, 16, 24),
    'ring_counts': (2, 3, 5),
    'complexity': (0.15, 0.35, 0.5, 0.7, 0.9),
    'min_white': (5, 10, 25),
}


def all_pattern_names():
    names = [(p['name'], p['category']) for p in SMART_PATTERNS]
    names += [(get_safe_fallback_pattern(c)['name'], c) for c in CATEGORIES]
    return names


def _declared_gate(name, category):
    for pattern in SMART_PATTERNS:
        if pattern['name'] == name:
            return (pattern.get('min_ring_width', 0),
                    pattern.get('min_cell_width_px', 0.0),
                    pattern.get('max_ring_aspect'))
    fallback = get_safe_fallback_pattern(category)
    return (fallback.get('min_ring_width', 0),
            fallback.get('min_cell_width_px', 0.0),
            fallback.get('max_ring_aspect'))


def run_case(job):
    name, category, divisions, rings, complexity, min_white, seed, probe = job
    label = f"div{divisions}_rings{rings}_c{complexity}_mws{min_white}"

    chatter = io.StringIO()
    try:
        with redirect_stdout(chatter):
            generator = DesignGenerator(
                seed=seed, num_rings=rings, num_divisions=divisions,
                complexity=complexity, min_pattern_size=min_white,
                categories=[category], force_pattern_name=name,
            )
            if not probe:
                # Respect the pattern's declared envelope. Forcing still
                # bypasses ring-position rules, but a pattern is not failed for
                # a cell size it explicitly says it does not fit.
                min_ring, min_cell, max_aspect = _declared_gate(name, category)
                for ring in generator.rings:
                    width = ring['outer_radius'] - ring['inner_radius']
                    mid = ring['inner_radius'] + width * 0.5
                    cell = mid * math.radians(360.0 / divisions)
                    if width < min_ring or cell < min_cell:
                        return {'name': name, 'label': label,
                                'status': 'SKIP', 'detail': f"cell {cell:.0f}px < gate {min_cell:.0f}px"}
                    if max_aspect and cell > 0 and width / cell > max_aspect:
                        return {'name': name, 'label': label, 'status': 'SKIP',
                                'detail': f"ring aspect {width / cell:.1f} > {max_aspect}"}
            generator.generate()
    except ValueError as exc:
        text = str(exc)
        # A cell-contract break and a topology failure have different fixes,
        # so they are reported in different columns.
        kind = 'CONTRACT' if 'Invalid smart pattern' in text else 'REJECTED'
        return {'name': name, 'label': label, 'status': kind, 'detail': text[:200]}
    except Exception as exc:
        return {'name': name, 'label': label, 'status': 'ERROR',
                'detail': f"{type(exc).__name__}: {exc}"[:200]}

    report = generator.last_validation_result
    stats = report.stats
    problems = []

    if not report.is_valid:
        problems.append(report.issues[0] if report.issues else 'invalid')

    # H6: the pattern must actually subdivide its ring. The bar is deliberately
    # below one face per cell - faces legitimately merge across cells - but it
    # still catches a pattern that draws only concentric loops.
    floor = int(divisions * 0.75)
    if stats.get('num_regions', 0) < floor:
        problems.append(f"only {stats.get('num_regions', 0)} regions for {divisions} cells (floor {floor})")

    # H7: forcing disables fallback, so any fallback use is a bug in the harness wiring
    if any(u.get('is_safe_fallback') for u in generator.pattern_usage) and 'safe_spoke' not in name:
        problems.append('fell back despite forcing')

    if problems:
        return {'name': name, 'label': label, 'status': 'FAIL', 'detail': '; '.join(problems)[:200]}
    return {'name': name, 'label': label, 'status': 'PASS', 'detail': ''}


def check_port_stability(name, category):
    """
    H2 — regression test for the rule-4 bug that shipped once already.

    Side-port radials must come from the ring-stable `port_rng`. Generating with
    the same port_rng seed but different per-variation rng seeds must produce
    identical side-boundary radials; otherwise cells drawn from different
    variations of one ring cannot meet.
    """
    from smart_patterns.core import boundary_side

    pattern = next((p for p in SMART_PATTERNS if p['name'] == name), None)
    if pattern is None:
        pattern = get_safe_fallback_pattern(category)

    signatures = []
    for extension in (0.0, 0.137, 0.291):     # different per-variation streams
        rng = random.Random(9001 + int(extension * 1000))
        port_rng = random.Random(9001)        # identical ring-stable stream
        try:
            with redirect_stdout(io.StringIO()):
                elements = pattern['generator'](
                    inner_radius=120.0, outer_radius=180.0, wedge_angle=30.0,
                    center=(306.0, 306.0), complexity=0.75, stroke_width=1.5,
                    ring_index=1, is_first_ring=False, is_last_ring=False,
                    rng=rng, port_rng=port_rng, min_white_space=10.0,
                )
        except ValueError:
            return None                       # cannot judge; the case matrix covers it
        radials = []
        for element in elements:
            vector = element.get('smart_vector')
            if vector is None:
                continue
            radials += [round(p.radial, 6) for p in vector.points
                        if boundary_side(p) in ('left', 'right')]
        signatures.append(tuple(sorted(radials)))

    return all(sig == signatures[0] for sig in signatures)


def main():
    parser = argparse.ArgumentParser(description="Per-pattern coverage harness")
    parser.add_argument('--pattern', help="run only this pattern")
    parser.add_argument('--tier', choices=['smoke', 'full'], default='smoke')
    parser.add_argument('--list', action='store_true', help="list registered patterns and exit")
    parser.add_argument('--jobs', type=int, default=max(1, (os.cpu_count() or 2) // 2))
    parser.add_argument('--seed', type=int, default=20260821)
    parser.add_argument('--probe', action='store_true',
                        help="ignore declared min_ring_width / min_cell_width_px gates "
                             "(use to recalibrate them, not as a pass/fail gate)")
    args = parser.parse_args()

    patterns = all_pattern_names()
    if args.list:
        for name, category in patterns:
            print(f"  {category:10} {name}")
        print(f"\n{len(patterns)} patterns registered "
              f"({len(SMART_PATTERNS)} real + {len(CATEGORIES)} fallbacks)")
        return

    if args.pattern:
        patterns = [(n, c) for n, c in patterns if n == args.pattern]
        if not patterns:
            print(f"No such pattern: {args.pattern}")
            sys.exit(2)

    matrix = SMOKE if args.tier == 'smoke' else FULL
    jobs = [
        (name, category, divisions, rings, complexity, min_white, args.seed, args.probe)
        for name, category in patterns
        for divisions in matrix['divisions']
        for rings in matrix['ring_counts']
        for complexity in matrix['complexity']
        for min_white in matrix['min_white']
    ]

    print(f"{len(patterns)} pattern(s) x {len(jobs)//max(1,len(patterns))} cases "
          f"= {len(jobs)} runs ({args.tier} tier, {args.jobs} workers)\n")

    if args.jobs > 1 and len(jobs) > 1:
        with ProcessPoolExecutor(max_workers=args.jobs) as pool:
            results = list(pool.map(run_case, jobs, chunksize=4))
    else:
        results = [run_case(job) for job in jobs]

    by_pattern = {}
    for result in results:
        by_pattern.setdefault(result['name'], []).append(result)

    print(f"{'PATTERN':30} {'PASS':>5} {'SKIP':>5} {'FAIL':>5} {'CONTR':>6} {'ERR':>4} {'PORTS':>6}")
    print("-" * 68)
    failed_patterns = []
    for name, category in patterns:
        rows = by_pattern.get(name, [])
        counts = {k: sum(1 for r in rows if r['status'] == k)
                  for k in ('PASS', 'FAIL', 'CONTRACT', 'REJECTED', 'ERROR', 'SKIP')}
        stable = check_port_stability(name, category)
        ports = 'ok' if stable else ('n/a' if stable is None else 'BAD')
        bad = counts['FAIL'] + counts['ERROR'] + counts['REJECTED'] + counts['CONTRACT']
        if bad or ports == 'BAD':
            failed_patterns.append(name)
        print(f"{name:30} {counts['PASS']:>5} {counts['SKIP']:>5} "
              f"{counts['FAIL'] + counts['REJECTED']:>5} {counts['CONTRACT']:>6} "
              f"{counts['ERROR']:>4} {ports:>6}")

    if failed_patterns:
        print("\nFailing cases:")
        for name in failed_patterns:
            for result in by_pattern.get(name, []):
                if result['status'] not in ('PASS', 'SKIP'):
                    print(f"  {result['name']:28} {result['label']:26} "
                          f"[{result['status']}] {result['detail']}")

    print("-" * 68)
    total_pass = sum(1 for r in results if r['status'] == 'PASS')
    print(f"{total_pass}/{len(results)} cases passed across "
          f"{len(patterns) - len(failed_patterns)}/{len(patterns)} patterns.")
    sys.exit(1 if failed_patterns else 0)


if __name__ == '__main__':
    main()
