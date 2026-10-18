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
    python qa_report.py --corpus         # pinned regression corpus (180 designs) with its quotas
    python qa_report.py --force-mode layered  # force a position mode on every ring past the innermost

Exits non-zero if any design fails validation, so it can gate CI. A corpus run
also exits non-zero when it misses a quota (spec 11): at least a quarter of the
rings of its botanical and geometric designs layered (kept their back),
every embellishment drawn in at least ten rings, and no more designs keeping an
oversized region than OVERSIZED_DESIGN_CEILING.
"""

import argparse
import io
import os
import random
import sys
from concurrent.futures import ProcessPoolExecutor
from contextlib import redirect_stdout
from dataclasses import replace

from coloring_generator import DesignGenerator
from composer import ring_stream_seed
from motifs import find_motif
from motifs.contract import MotifError
from motifs.embellish import EMBELLISHMENT_ORDER
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
# The corpus forces the layered position mode on every eligible ring of the jobs with these seeds, because
# the natural rate of layered rings is far below the quota (spec 11). Forcing only makes a ring layered where
# a back motif fits; categories with no back motifs keep their natural modes.
CORPUS_LAYERED_SEEDS = CORPUS_SEEDS[:5]
# Jobs among the layered seeds that keep their natural position modes, keyed by (category, complexity, seed,
# vary). Beads draw only on a band past the innermost ring (the innermost ring is too narrow for a bead row),
# and forcing layered turns every eligible geometric ring past the innermost into a layered ring, so no band
# is left to carry beads. These are the fewest jobs whose natural plans draw enough beaded bands to meet the
# beads quota (spec 11); the layered quota keeps a wide margin without them. The region-cap repair ladder re-rolls
# some beaded band rings away (their background faces are oversized), so two more jobs keep their natural modes
# (complexity 0.5 on seed 12345 and 0.85 on seed 254302, uniform divisions), each drawing a beaded band that stays.
CORPUS_UNLAYERED_JOBS = {
    ('geometric', 0.5, 777, False),
    ('geometric', 0.5, 777, True),
    ('geometric', 0.5, 254302, False),
    ('geometric', 0.5, 12345, False),
    ('geometric', 0.85, 777, False),
    ('geometric', 0.85, 254302, False),
    ('geometric', 0.85, 254302, True),
}

# The corpus forces embellishments on these jobs, keyed by (category, complexity, seed, vary), because unforced
# picks draw too few fans and dots (spec 11): a fan is accepted by petals only and seldom picked, and at
# complexity 0.6 and above two echoes leave no room for a dot. Forcing adds the names to the picks of every
# host that accepts them (`ComposerSettings.force_embellishments`); these are the fewest jobs found that meet
# the quota. Beads are forced on one natural geometric job, whose band then keeps its beads through the region-cap
# repair ladder.
CORPUS_EMBELLISHMENT_JOBS = {
    ('botanical', 0.15, 42, False): ('dot',),
    ('botanical', 0.15, 42, True): ('dot',),
    ('botanical', 0.15, 777, False): ('fan', 'dot'),
    ('geometric', 0.15, 984322, False): ('beads',),
}

# Corpus quotas (spec 11): the share of the rings of botanical and geometric designs that are layered (and
# kept their back), and the rings each embellishment must be drawn in, across the corpus.
LAYERED_CATEGORIES = ('botanical', 'geometric')
LAYERED_SHARE = 0.25
EMBELLISHMENT_MIN = 10
# The most corpus designs that may keep an oversized region after the repair ladder (max-region-size spec 8):
# the count measured when the cap landed, pinned so that a regression which leaves more designs oversized fails.
# 93 of the 103 are celtic, art_deco and abstract designs, drawn only from safe bands, which take no embellishments
# and leave the ladder little to add; botanical keeps 7 and geometric 3.
OVERSIZED_DESIGN_CEILING = 103


def corpus_jobs(out_dir, overlay_mode, num_rings=CORPUS_RINGS, num_divisions=CORPUS_DIVISIONS,
                layered_seeds=CORPUS_LAYERED_SEEDS, embellishment_jobs=None, unlayered_jobs=None):
    """
    The pinned corpus as run_one jobs: 5 categories x 3 complexities x 6 seeds x 2 division modes, each with
    its forced position mode (`layered` for the seeds in `layered_seeds`, except the jobs in `unlayered_jobs`,
    else None) and its forced embellishments (from `embellishment_jobs`, else None); both tables are keyed by
    `(category, complexity, seed, vary)`.
    """
    embellishment_jobs = CORPUS_EMBELLISHMENT_JOBS if embellishment_jobs is None else embellishment_jobs
    unlayered_jobs = CORPUS_UNLAYERED_JOBS if unlayered_jobs is None else unlayered_jobs
    return [
        (seed, num_rings, num_divisions, complexity, [category], vary, out_dir, overlay_mode,
         'layered' if seed in layered_seeds and (category, complexity, seed, vary) not in unlayered_jobs else None,
         embellishment_jobs.get((category, complexity, seed, vary)))
        for category in CORPUS_CATEGORIES
        for complexity in CORPUS_COMPLEXITIES
        for seed in CORPUS_SEEDS
        for vary in (False, True)
    ]


def corpus_quota_failures(rows):
    """
    Each corpus quota the result `rows` miss, as a sentence (empty when both hold): fewer than
    `LAYERED_SHARE` of the rings of the botanical and geometric designs layered, and each embellishment
    drawn in fewer than `EMBELLISHMENT_MIN` rings, and more than `OVERSIZED_DESIGN_CEILING` designs keeping an
    oversized region. A ring counts as layered only if it kept its back.
    """
    failures = []
    layered_rows = [row for row in rows if set(row['categories']) & set(LAYERED_CATEGORIES)]
    layered = sum(row['layered_rings'] for row in layered_rows)
    rings = sum(row['rings'] for row in layered_rows)
    if rings and layered < LAYERED_SHARE * rings:
        failures.append(f"layered rings {layered}/{rings} = {layered / rings:.1%} (< {LAYERED_SHARE:.0%})")
    for name in EMBELLISHMENT_ORDER:
        count = sum(row['embellishments'].get(name, 0) for row in rows)
        if count < EMBELLISHMENT_MIN:
            failures.append(f"embellishment {name} appears {count} times (< {EMBELLISHMENT_MIN})")
    oversized = sum(1 for row in rows if row.get('oversized', 0) > 0)
    if oversized > OVERSIZED_DESIGN_CEILING:
        failures.append(f"oversized regions in {oversized} designs (> {OVERSIZED_DESIGN_CEILING})")
    return failures


def drawn_names(generate, context, names):
    """
    Which of `names` (in `EMBELLISHMENT_ORDER`) the generator draws in `context`. An instance counts drops,
    not names, but the pipeline runs the names in order, each from its own stream, so a run with the first
    k names is the full run up to its k-th name: the k-th name was drawn when adding it adds no drop.
    """
    drawn, before = [], 0
    for k in range(1, len(names) + 1):
        try:
            dropped = generate(replace(context, rng=random.Random(context.node_seed),
                                       embellishments=tuple(names[:k]))).dropped_embellishments
        except MotifError:
            return drawn
        if dropped == before:
            drawn.append(names[k - 1])
        before = dropped
    return drawn


def _back_context(ring, front_context):
    """The context the assembler draws a layered ring's back in (`Assembler._back_context`)."""
    seed = ring_stream_seed(ring.ring_seed, ring.ring_index, "back")
    return replace(front_context, rng=random.Random(seed), node_seed=seed, ring_stream_seed=seed,
                   position="divider", angular_limits=1.0, radial_limits=(0.0, 1.0), slot=None,
                   side_touch_radial=None, embellishments=tuple(ring.back.embellishments))


def drawn_embellishments(generator):
    """
    For each embellishment, the number of rings of the design in which some base node drew it (a layered
    ring's back included). A node that dropped none of its embellishments drew them all; otherwise each
    name is checked by regenerating the node with the names up to it (`drawn_names`).
    """
    rings_by_index = {ring.ring_index: ring for ring in generator.plan.rings}
    found = {}
    for node in generator.assembled.nodes:
        if node.parent is not None:
            continue
        credited = {name for name, rings in found.items() if node.ring_index in rings}
        names = [name for name in node.recipe.embellishments if name not in credited]
        ring = rings_by_index.get(node.ring_index)
        back_names = []
        if node.back_seed is not None and ring is not None and ring.back is not None:
            back_names = [name for name in ring.back.embellishments if name not in credited]
        if not names and not back_names:
            continue
        if node.instance.dropped_embellishments == 0:
            drawn = names + back_names
        else:
            entry = find_motif(node.recipe.motif)
            drawn = drawn_names(entry['generator'], node.context, list(node.recipe.embellishments)) if entry else []
            if back_names:
                back_context = _back_context(ring, node.context)
                drawn += drawn_names(find_motif(ring.back.motif)['generator'], back_context,
                                     list(ring.back.embellishments))
        for name in drawn:
            found.setdefault(name, set()).add(node.ring_index)
    return {name: len(found[name]) for name in EMBELLISHMENT_ORDER if name in found}


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
    """
    Generate + validate one design. Runs in a worker process. A job is `(seed, num_rings, num_divisions,
    complexity, categories, vary, out_dir, overlay_mode)`, optionally followed by a forced position mode.
    """
    seed, num_rings, num_divisions, complexity, categories, vary, out_dir, overlay_mode, *rest = job
    force_mode = rest[0] if rest else None
    force_embellishments = rest[1] if len(rest) > 1 else None
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
                force_position_mode=force_mode,
                force_embellishments=force_embellishments,
            )
            svg = generator.generate()
    except Exception as exc:
        return {
            'label': label, 'seed': seed, 'complexity': complexity,
            'categories': categories, 'vary': vary, 'status': 'ERROR',
            'error': f"{type(exc).__name__}: {exc}"[:300],
            'stats': {}, 'issues': [], 'fallbacks': 0, 'patterns': [], 'reaches': 0,
            'base_symmetry': None, 'side_touch_rings': 0, 'layered_rings': 0, 'back_dropped_rings': 0,
            'rings': num_rings, 'embellishments': {}, 'oversized': 0, 'largest_in2': 0.0,
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
        'base_symmetry': generator.plan.base_symmetry,
        'side_touch_rings': sum(1 for ring in generator.plan.rings if ring.contact_mode == 'side'),
        'layered_rings': sum(1 for ring in generator.plan.rings if ring.back is not None),
        'back_dropped_rings': sum(1 for ring in generator.plan.rings if ring.back_dropped),
        'rings': len(generator.plan.rings),
        'embellishments': drawn_embellishments(generator),
        'oversized': report.stats.get('num_oversized_regions', 0),
        'largest_in2': report.stats.get('largest_region_in2', 0.0),
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
    parser.add_argument('--force-mode', choices=['centre', 'divider', 'both', 'layered'], default=None,
                        help="force this position mode on every ring past the innermost where it is eligible "
                             "(the corpus and seed runs force no motif, so it always applies)")
    parser.add_argument('--out', default='test_output')
    parser.add_argument('--jobs', type=int, default=max(1, (os.cpu_count() or 2) // 2))
    parser.add_argument('--overlays', choices=['always', 'failures', 'never'], default=None,
                        help="when to write overlay SVGs (default: always, or failures for --corpus)")
    args = parser.parse_args()

    if args.corpus:
        overlay_mode = args.overlays or 'failures'
        jobs = corpus_jobs(args.out, overlay_mode, args.rings, args.divisions)
        if args.force_mode:  # an explicit mode replaces the corpus's own forcing on every job
            jobs = [job[:8] + (args.force_mode,) + job[9:] for job in jobs]
    else:
        overlay_mode = args.overlays or 'always'
        seeds = args.seeds if args.seeds else [random.randint(0, 1000000) for _ in range(args.count)]
        jobs = [
            (seed, args.rings, args.divisions, args.complexity, args.categories, args.vary, args.out, overlay_mode,
             args.force_mode)
            for seed in seeds
        ]

    os.makedirs(args.out, exist_ok=True)
    print(f"Running {len(jobs)} design(s) on {args.jobs} worker(s)...\n")

    if args.jobs > 1 and len(jobs) > 1:
        with ProcessPoolExecutor(max_workers=args.jobs) as pool:
            results = list(pool.map(run_one, jobs))
    else:
        results = [run_one(job) for job in jobs]

    print(f"{'DESIGN':38} {'STATUS':6} {'VARY':>4} {'B':>3} {'REGIONS':>7} {'DANGL':>6} {'FLOAT':>5} "
          f"{'UNCOL':>5} {'LANE':>4} {'REACH':>5} {'FB':>3} {'LAYR':>4} {'BDRP':>4}  EMBELLISHMENTS")
    print("-" * 124)
    for result in results:
        stats = result['stats']
        symmetry = result['base_symmetry'] if result['base_symmetry'] is not None else '-'
        print(f"{result['label']:38} {result['status']:6} {int(result['vary']):>4} {symmetry:>3} "
              f"{stats.get('num_regions', 0):>7} {stats.get('num_dangles', 0):>6} "
              f"{stats.get('num_floating_open', 0):>5} "
              f"{stats.get('num_uncolorable_regions', 0):>5} "
              f"{stats.get('num_free_lanes', 0):>4} {result['reaches']:>5} {result['fallbacks']:>3} "
              f"{result['layered_rings']:>4} {result['back_dropped_rings']:>4}  "
              + " ".join(f"{name}={count}" for name, count in result['embellishments'].items()))

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
    print("-" * 124)
    print(f"{len(results) - len(bad)}/{len(results)} designs passed. "
          f"Reaches: {reach_total}. Safe-fallback cells used: {fallback_total}.")
    print(f"Layered rings: {sum(r['layered_rings'] for r in results)}; "
          f"back layers dropped: {sum(r['back_dropped_rings'] for r in results)}.")
    quota_failures = []
    if args.corpus:
        layered_rows = [r for r in results if set(r['categories']) & set(LAYERED_CATEGORIES)]
        layered = sum(r['layered_rings'] for r in layered_rows)
        rings = sum(r['rings'] for r in layered_rows)
        print(f"layered rings: {layered}/{rings} botanical+geometric rings (>= {LAYERED_SHARE:.0%})")
        print("embellishments: " + " ".join(
            f"{name}={sum(r['embellishments'].get(name, 0) for r in results)}" for name in EMBELLISHMENT_ORDER)
            + f" (rings drawn in, each >= {EMBELLISHMENT_MIN})")
        oversized = sum(1 for r in results if r.get('oversized', 0) > 0)
        largest = max((r.get('largest_in2', 0.0) for r in results), default=0.0)
        print(f"oversized regions: {oversized} of {len(results)} designs; largest region {largest:.2f} in²")
        quota_failures = corpus_quota_failures(results)
        for failure in quota_failures:
            print(f"QUOTA MISSED: {failure}")
    if overlay_mode != 'never':
        scope = "failing designs" if overlay_mode == 'failures' else "all designs"
        print(f"Overlays for {scope} written to {args.out}/qa_overlay_<design>.svg")

    sys.exit(1 if bad or quota_failures else 0)


if __name__ == '__main__':
    main()
