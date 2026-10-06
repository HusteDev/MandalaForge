"""
Per-motif coverage harness.

`qa_report.py --corpus` only exercises whichever motifs random selection happens
to pick, so a motif can ship untested. This harness forces each registered motif
in turn, in every position and role it supports, over a matrix of ring-division
fixtures, and drives the REAL generation pipeline. Forcing disables the fallback
chain (a rejection is a visible failure, not a silent substitution) and never
applies to ring 0.

It also checks four properties of each motif's generator on a standard cell:
determinism, narrower radial limits never reaching further, angular containment
and an honest slot declaration.

Usage:
    python qa_patterns.py                        # smoke tier, every motif
    python qa_patterns.py --motif petal          # one motif
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
from motifs import MOTIFS, find_motif, safe_motif
from motifs.contract import MotifError
from motifs.geometry import CellPoint, MotifContext

CATEGORIES = ['botanical', 'geometric', 'celtic', 'art_deco', 'abstract']
POSITIONS = ('centre', 'divider', 'both')
ROLES = ('base', 'slot', 'contact')
DEFAULT_SEED = 20260821

# (8, 8, 8, 12) is the fixture of the original sketch; (24, 24, 24) is the dense
# case where cells are narrowest. Ring count follows the tuple length.
RING_DIVISIONS = ((8, 8, 8, 12), (7, 12), (6, 6), (24, 24, 24))
MATRIX_SMOKE = {
    'ring_divisions': RING_DIVISIONS,
    'complexity': (0.15, 0.5, 0.9),
    'min_white': (10,),
    'position': POSITIONS,
    'role': ROLES,
}
MATRIX_FULL = {
    'ring_divisions': RING_DIVISIONS,
    'complexity': (0.15, 0.35, 0.5, 0.7, 0.9),
    'min_white': (5, 10, 25),
    'position': POSITIONS,
    'role': ROLES,
}

# A job role and the role name the registry uses for it.
REGISTRY_ROLE = {'base': 'base', 'slot': 'slot', 'contact': 'attachment'}
# Share of a cell a node gets when centre and divider both carry one (the
# composer's share varies per ring; this is the middle of its range).
BOTH_BUDGET = 0.6
# A design must carry at least this share of one face per cell outside ring 0.
REGION_FLOOR = 0.75

STATUSES = ('PASS', 'SKIP', 'FAIL', 'CONTRACT', 'ERROR')


def _supports(entry, position, role):
    needed = ('centre', 'divider') if position == 'both' else (position,)
    return (all(p in entry['positions'] for p in needed)
            and REGISTRY_ROLE[role] in entry['roles'])


# The frame a forced slot child nests in, whose slot estimate sizes the room it gets.
SLOT_FRAME = 'petal'


def _gate_skip(entry, generator, ring_divisions, position, role='base'):
    """
    Reason the declared gates exclude the fixture, or None. Ring 0 is never
    forced. A slot child is gated on the frame's slot as the composer
    estimates it when nesting: the cell and ring depth scaled by the frame's
    `slot_estimate`.
    """
    budget = BOTH_BUDGET if position == 'both' else 1.0
    cells, depths = [], []
    for ring, divisions in list(zip(generator.rings, ring_divisions))[1:]:
        mid = (ring['inner_radius'] + ring['outer_radius']) / 2.0
        cells.append(mid * math.radians(360.0 / divisions) * budget)
        depths.append(ring['outer_radius'] - ring['inner_radius'])
    if not cells:
        return "no ring past the centre to force"
    cell, depth = min(cells), min(depths)
    room = 'cell'
    if role == 'slot':
        width_fraction, depth_fraction = find_motif(SLOT_FRAME)['slot_estimate']
        cell, depth, room = cell * width_fraction, depth * depth_fraction, 'slot'
    if entry['min_cell_width_px'] > cell:
        return f"{room} {cell:.1f}px < gate {entry['min_cell_width_px']:.0f}px"
    if entry['min_ring_depth_px'] > depth:
        return f"{room} depth {depth:.1f}px < gate {entry['min_ring_depth_px']:.0f}px"
    return None


def _placed_count(generator, name, role):
    """How many times the forced motif was actually placed in its role."""
    nodes = generator.assembled.nodes
    if role == 'contact':  # an attachment is no node of its own; count the nodes that carry it
        return sum(1 for node in nodes if any(att.motif == name for att in node.recipe.attachments))
    if role == 'slot':
        return sum(1 for node in nodes if node.parent is not None and node.recipe.motif == name)
    return sum(1 for node in nodes if node.parent is None and node.recipe.motif == name)


def run_case(job):
    name, category, ring_divisions, complexity, min_white, position, role, seed, probe = job
    label = f"div{'-'.join(map(str, ring_divisions))}_c{complexity}_mws{min_white}_{position}_{role}"

    def result(status, detail=''):
        return {'name': name, 'label': label, 'status': status, 'detail': detail[:200]}

    entry = find_motif(name)
    if entry is None:
        return result('ERROR', f"unknown motif {name}")
    if not _supports(entry, position, role):
        return result('SKIP', f"{position}/{role} unsupported")

    try:
        with redirect_stdout(io.StringIO()):
            generator = DesignGenerator(
                seed=seed, num_rings=len(ring_divisions), num_divisions=ring_divisions[0],
                complexity=complexity, min_pattern_size=min_white, categories=[category],
                ring_divisions=list(ring_divisions),
                force_motif={'name': name, 'position': position, 'role': role},
            )
            if not probe:
                reason = _gate_skip(entry, generator, ring_divisions, position, role)
                if reason:
                    return result('SKIP', reason)
            generator.generate()
    except MotifError as exc:
        return result('CONTRACT', str(exc))
    except ValueError as exc:  # includes AssemblyError
        text = str(exc)
        if 'Invalid' in text or 'MotifError' in text:
            return result('CONTRACT', text)
        return result('ERROR', f"{type(exc).__name__}: {text}")
    except Exception as exc:
        return result('ERROR', f"{type(exc).__name__}: {exc}")

    # A design can validate without the motif under test: a slot child that never fits is dropped.
    placed = _placed_count(generator, name, role)
    dropped = sum(1 for node in generator.assembled.nodes
                  if node.child_dropped and node.recipe.slot_child is not None
                  and node.recipe.slot_child.motif == name)
    if placed == 0:
        return result('FAIL', f"forced motif never placed ({dropped} dropped)")
    if role == 'slot' and not probe and dropped > placed:
        return result('FAIL', f"forced slot motif dropped in most cells ({placed} placed, {dropped} dropped)")

    report = generator.last_validation_result
    if not report.is_valid:
        return result('FAIL', report.issues[0] if report.issues else 'invalid')
    cells = sum(ring_divisions[1:])
    floor = REGION_FLOOR * cells
    regions = report.stats.get('num_regions', 0)
    if regions < floor:
        return result('FAIL', f"only {regions} regions for {cells} cells (floor {floor:.0f})")
    return result('PASS')


# ------------------------------------------------------------ property checks

PROPERTY_CELL = dict(inner_radius=100.0, outer_radius=160.0, wedge_angle=30.0,
                     center=(306.0, 306.0), stroke_width=1.5, complexity=0.5,
                     min_white_space=10.0)


def _generate(entry, seed, **over):
    context = MotifContext(**PROPERTY_CELL, rng=random.Random(seed), **over)
    if 'base' not in entry['roles']:
        # A motif that cannot stand alone needs a slot to sit in.
        context.slot = [CellPoint(0.2, -0.4), CellPoint(0.2, 0.4),
                        CellPoint(0.8, 0.4), CellPoint(0.8, -0.4)]
    return entry['generator'](context)


def _points(instance):
    return [p for vector in instance.vectors for p in vector.points]


def _deterministic(entry):
    first, second = _generate(entry, 11), _generate(entry, 11)
    return [v.points for v in first.vectors] == [v.points for v in second.vectors]


def _monotone(entry):
    wide = _points(_generate(entry, 5, radial_limits=(-0.25, 1.25)))
    narrow = _points(_generate(entry, 5, radial_limits=(-0.1, 1.1)))
    if not narrow:
        return True
    high = max(p.radial for p in wide) if wide else 0
    low = min(p.radial for p in wide) if wide else 0
    return (max(p.radial for p in narrow) <= high + 1e-9
            and min(p.radial for p in narrow) >= low - 1e-9)


def _angular(entry):
    inst = _generate(entry, 3, radial_limits=(0.0, 1.0), angular_limits=0.5)
    return all(-0.03 <= p.radial <= 1.03 and abs(p.angular) <= 0.53 for p in _points(inst))


def _slot(entry):
    if not entry['slot_estimate']:
        return True
    return _generate(entry, 9).declaration.slot is not None


def property_checks(entry):
    """Run the four generator property checks on the standard test cell."""
    checks = {'deterministic': _deterministic, 'monotone': _monotone,
              'angular': _angular, 'slot': _slot}
    outcome = {}
    for key, check in checks.items():
        try:
            outcome[key] = bool(check(entry))
        except Exception:  # a crashing generator fails the property, it does not stop the run
            outcome[key] = False
    return outcome


# ------------------------------------------------------------------------ CLI

def build_jobs(entries, matrix, seed, probe):
    return [
        (entry['name'], entry['category'], ring_divisions, complexity, min_white,
         position, role, seed, probe)
        for entry in entries
        for ring_divisions in matrix['ring_divisions']
        for complexity in matrix['complexity']
        for min_white in matrix['min_white']
        for position in matrix['position']
        for role in matrix['role']
    ]


def main():
    parser = argparse.ArgumentParser(description="Per-motif coverage harness")
    parser.add_argument('--motif', help="run only this motif")
    parser.add_argument('--tier', choices=['smoke', 'full'], default='smoke')
    parser.add_argument('--list', action='store_true', help="list registered motifs and exit")
    parser.add_argument('--jobs', type=int, default=max(1, (os.cpu_count() or 2) // 2))
    parser.add_argument('--seed', type=int, default=DEFAULT_SEED)
    parser.add_argument('--probe', action='store_true',
                        help="ignore declared min_cell_width_px / min_ring_depth_px gates "
                             "(use to recalibrate them, not as a pass/fail gate)")
    args = parser.parse_args()

    if args.list:
        for entry in MOTIFS:
            print(f"  {entry['category']:10} {entry['name']}")
        for category in CATEGORIES:
            print(f"  {category:10} {safe_motif(category)['name']} (safe band)")
        print(f"\n{len(MOTIFS)} motifs registered + {len(CATEGORIES)} safe bands")
        return 0

    entries = MOTIFS
    if args.motif:
        entries = [e for e in MOTIFS if e['name'] == args.motif]
        if not entries:
            print(f"No such motif: {args.motif}")
            return 2

    matrix = MATRIX_SMOKE if args.tier == 'smoke' else MATRIX_FULL
    jobs = build_jobs(entries, matrix, args.seed, args.probe)
    print(f"{len(entries)} motif(s) x {len(jobs) // len(entries)} cases "
          f"= {len(jobs)} runs ({args.tier} tier, {args.jobs} workers)\n")

    if args.jobs > 1 and len(jobs) > 1:
        with ProcessPoolExecutor(max_workers=args.jobs) as pool:
            results = list(pool.map(run_case, jobs, chunksize=4))
    else:
        results = [run_case(job) for job in jobs]

    by_motif = {}
    for result in results:
        by_motif.setdefault(result['name'], []).append(result)

    header = (f"{'MOTIF':16} {'PASS':>5} {'SKIP':>5} {'FAIL':>5} {'CONTR':>6} {'ERR':>4} "
              f"{'DET':>5} {'MONO':>5} {'ANG':>5} {'SLOT':>5}")
    print(header)
    print("-" * len(header))
    failed = []
    for entry in entries:
        name = entry['name']
        rows = by_motif.get(name, [])
        counts = {k: sum(1 for r in rows if r['status'] == k) for k in STATUSES}
        props = property_checks(entry)
        mark = {True: 'ok', False: 'BAD'}
        if counts['FAIL'] or counts['CONTRACT'] or counts['ERROR'] or not all(props.values()):
            failed.append(name)
        print(f"{name:16} {counts['PASS']:>5} {counts['SKIP']:>5} {counts['FAIL']:>5} "
              f"{counts['CONTRACT']:>6} {counts['ERROR']:>4} "
              f"{mark[props['deterministic']]:>5} {mark[props['monotone']]:>5} "
              f"{mark[props['angular']]:>5} {mark[props['slot']]:>5}")

    if failed:
        print("\nFailing cases:")
        for name in failed:
            for result in by_motif.get(name, []):
                if result['status'] not in ('PASS', 'SKIP'):
                    print(f"  {result['name']:14} {result['label']:44} "
                          f"[{result['status']}] {result['detail']}")

    print("-" * len(header))
    total_pass = sum(1 for r in results if r['status'] == 'PASS')
    print(f"{total_pass}/{len(results)} cases passed across "
          f"{len(entries) - len(failed)}/{len(entries)} motifs.")
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
