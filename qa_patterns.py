"""
Per-motif coverage harness.

`qa_report.py --corpus` only exercises whichever motifs random selection happens
to pick, so a motif can ship untested. This harness forces each registered motif
in turn, in every position and role it supports, over a matrix of ring-division
fixtures, and drives the REAL generation pipeline. Forcing disables the fallback
chain (a rejection is a visible failure, not a silent substitution) and never
applies to ring 0.

It also checks six properties of each motif's generator on a standard cell:
determinism, narrower radial limits never reaching further, angular containment,
an honest slot declaration, seam ends on the cell edges and smooth side touch.

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
from typing import List, Set

from assembler import stroke_width_for
from coloring_generator import DesignGenerator
from composer import Composer, ComposerSettings, node_rng, ring_stream_seed
from motifs import MOTIFS, find_motif, safe_motif
from motifs.contract import MotifError
from motifs.geometry import CellPoint, MotifContext, SmartVector

CATEGORIES = ['botanical', 'geometric', 'celtic', 'art_deco', 'abstract']
POSITIONS = ('centre', 'divider', 'both')
ROLES = ('base', 'slot', 'contact')
DEFAULT_SEED = 20260821

# (8, 8, 8, 12) is the fixture of the original sketch; (24, 24, 24) is the dense
# case where cells are narrowest. Ring count follows the tuple length, and the
# base symmetry B is the gcd of the counts (4, 1, 6 and 24), so the fixtures
# cover both a design with no rotational repetition and fully uniform rings.
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
# A design must carry at least this share of one face per cell outside ring 0.
REGION_FLOOR = 0.75

# Prefix of a SKIP detail for a slot job refused by the frames' final (post pull-back) slots.
FINAL_SLOT_TAG = '[final-slot]'
STATUSES = ('PASS', 'SKIP', 'FAIL', 'CONTRACT', 'ERROR')


def _supports(entry, position, role):
    needed = ('centre', 'divider') if position == 'both' else (position,)
    return (all(p in entry['positions'] for p in needed)
            and REGISTRY_ROLE[role] in entry['roles'])


# The frame a forced slot child nests in; the gate measures the slot it really declares.
SLOT_FRAME = 'petal'


def _fixture_plan(generator):
    """
    The plan the generator will draw for this fixture: a composer with the
    generator's own settings, as `generate()` builds it (planning draws
    nothing). The gates read each forced ring's division count, centre share,
    contact mode and side-touch radial from it.
    """
    settings = ComposerSettings(
        num_divisions=generator.num_divisions, vary_divisions=generator.vary_divisions,
        ring_divisions=generator.ring_divisions, complexity=generator.complexity,
        min_pattern_size=generator.min_pattern_size, categories=generator.categories,
        force_motif=generator.force_motif, ring_seeds=generator.ring_seeds,
    )
    return Composer(generator.seed, generator.rings, settings).plan()


def _gate_skip(entry, generator, position, role='base'):
    """
    Reason the declared gates exclude the fixture, or None. Ring 0 is never
    forced. A node's share of its cell is the planned ring's centre share (1.0
    unless centre and divider both carry a node). A slot child is gated on the
    slots the frame really declares in the forced rings (see `_frame_slot_px`),
    not on the whole cell.
    """
    plan = _fixture_plan(generator)
    if role == 'slot':
        return _slot_gate_skip(entry, generator, plan, position)
    cells, depths = [], []
    for ring, ring_plan in list(zip(generator.rings, plan.rings))[1:]:
        mid = (ring['inner_radius'] + ring['outer_radius']) / 2.0
        cells.append(mid * math.radians(360.0 / ring_plan.divisions) * ring_plan.centre_share)
        depths.append(ring['outer_radius'] - ring['inner_radius'])
    if not cells:
        return "no ring past the centre to force"
    cell, depth = min(cells), min(depths)
    if entry['min_cell_width_px'] > cell:
        return f"cell {cell:.0f}px < gate {entry['min_cell_width_px']:.0f}px"
    if entry['min_ring_depth_px'] > depth:
        return f"ring depth {depth:.0f}px < gate {entry['min_ring_depth_px']:.0f}px"
    return None


def _frame_context(generator, ring_plan, position):
    """
    The context the assembler gives the frame of the planned ring's first
    sequence entry in pass one: that ring's geometry and division count, the
    node stream `node_rng(ring_seed, ring_index, 0, 0, position)`, the ring's
    centre share as the angular budget, and, when the ring is in side mode,
    its side-touch radial (a side-touching frame spans its whole budget).
    """
    frame = find_motif(SLOT_FRAME)
    ring_index = ring_plan.ring_index
    ring = generator.rings[ring_index]
    # A divider frame has its cell to itself; a centre frame shares it in "both" mode.
    frame_position = 'divider' if position == 'divider' else 'centre'
    return MotifContext(
        inner_radius=ring['inner_radius'], outer_radius=ring['outer_radius'],
        wedge_angle=360.0 / ring_plan.divisions, center=generator.center,
        stroke_width=stroke_width_for(generator.complexity), complexity=generator.complexity,
        min_white_space=generator.min_pattern_size,
        rng=node_rng(ring_plan.ring_seed, ring_index, 0, 0, frame_position),
        position=frame_position, angular_limits=ring_plan.centre_share,
        radial_limits=(-frame['max_overflow_inward'], 1.0 + frame['max_overflow_outward']),
        side_touch_radial=ring_plan.side_touch_radial if ring_plan.contact_mode == 'side' else None,
    )


def _frame_slot_px(generator, ring_plan, position):
    """
    Width and depth in pixels of the slot the frame declares in the planned
    ring `ring_plan`, drawn with `_frame_context`. None when the frame
    declares no slot or cannot be drawn.
    """
    frame = find_motif(SLOT_FRAME)
    context = _frame_context(generator, ring_plan, position)
    try:
        slot = frame['generator'](context).declaration.slot
    except MotifError:
        return None
    if not slot:
        return None
    radials = [point.radial for point in slot]
    angulars = [point.angular for point in slot]
    mid = (min(radials) + max(radials)) / 2.0
    width = context.angular_to_px(max(angulars) - min(angulars), mid)
    depth = context.radial_to_px(max(radials) - min(radials))
    return width, depth, context.stroke_width


def _slot_refusal(entry, measured):
    """Why one ring's measured frame slot cannot take the child, or None when it can."""
    if measured is None:
        return f"{SLOT_FRAME} frame declares no slot"
    width, depth, stroke = measured
    need_width = entry['min_cell_width_px'] + 2.0 * stroke
    need_depth = entry['min_ring_depth_px'] + 2.0 * stroke
    if width < need_width:
        return f"slot {width:.2f}px < {need_width:.2f}px (gate + 2 strokes)"
    if depth < need_depth:
        return f"slot depth {depth:.2f}px < {need_depth:.2f}px (gate + 2 strokes)"
    return None


def _slot_gate_skip(entry, generator, plan, position):
    """
    SKIP reason only when no forced ring's real frame slot admits the child.
    The gate mirrors the FAIL rule: one admitting ring is enough for the child
    to be placed somewhere, so if any ring admits it the job runs and a child
    that is never placed is a genuine failure.
    """
    if len(plan.rings) < 2:
        return "no ring past the centre to force"
    refusals = []
    for ring_plan in plan.rings[1:]:
        measured = _frame_slot_px(generator, ring_plan, position)
        refusal = _slot_refusal(entry, measured)
        if refusal is None:
            return None
        refusals.append(f"ring {ring_plan.ring_index}: {refusal}")
    return "no forced ring admits the child; " + "; ".join(refusals)


def _placed_count(generator, name, role):
    """How many times the forced motif was actually placed in its role."""
    nodes = generator.assembled.nodes
    if role == 'contact':  # an attachment is no node of its own; count the nodes that carry it
        return sum(1 for node in nodes if any(att.motif == name for att in node.recipe.attachments))
    if role == 'slot':
        return sum(1 for node in nodes if node.parent is not None and node.recipe.motif == name)
    return sum(1 for node in nodes if node.parent is None and node.recipe.motif == name)


def _final_slot_refusals(entry, generator):
    """
    Why each placed frame's final slot refuses the child, in order. Frames that declare no slot are
    skipped; the list is empty when any frame's slot admits the child (so a child that is still
    missing is a genuine failure) or when no frame has a slot to measure.
    """
    reasons = []
    for node in generator.assembled.nodes:
        if node.parent is not None:
            continue
        slot = node.instance.declaration.slot
        if not slot:
            continue
        radials = [point.radial for point in slot]
        angulars = [point.angular for point in slot]
        context = node.context
        mid = (min(radials) + max(radials)) / 2.0
        measured = (context.angular_to_px(max(angulars) - min(angulars), mid),
                    context.radial_to_px(max(radials) - min(radials)), context.stroke_width)
        refusal = _slot_refusal(entry, measured)
        if refusal is None:
            return []
        reasons.append(f"ring {node.ring_index} cell {node.cell_index}: {refusal}")
    return reasons


def run_case(job):
    name, category, ring_divisions, complexity, min_white, position, role, seed, probe = job
    # An explicit division list's base symmetry is its gcd (spec 13.1).
    symmetry = Composer.base_symmetry(ring_divisions[0], False, list(ring_divisions), None)
    label = (f"div{'-'.join(map(str, ring_divisions))}_B{symmetry}_c{complexity}"
             f"_mws{min_white}_{position}_{role}")

    def result(status, detail='', dropped=0):
        return {'name': name, 'label': label, 'status': status, 'detail': detail[:200], 'dropped': dropped}

    entry = find_motif(name)
    if entry is None:
        return result('ERROR', f"unknown motif {name}")
    if position == 'both' and entry.get('seams', False):
        return result('SKIP', "seam motif never placed in both mode")
    if not _supports(entry, position, role):
        return result('SKIP', f"{position}/{role} unsupported")
    name = entry['name']  # a retired alias (ring_band) is placed under its current name

    try:
        with redirect_stdout(io.StringIO()):
            generator = DesignGenerator(
                seed=seed, num_rings=len(ring_divisions), num_divisions=ring_divisions[0],
                complexity=complexity, min_pattern_size=min_white, categories=[category],
                ring_divisions=list(ring_divisions),
                force_motif={'name': name, 'position': position, 'role': role},
            )
            if not probe:
                reason = _gate_skip(entry, generator, position, role)
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
    # Only a slot job forces the motif as a child; elsewhere it may nest of its own accord and is not counted.
    dropped = 0 if role != 'slot' else sum(
        1 for node in generator.assembled.nodes
        if node.child_dropped and node.recipe.slot_child is not None and node.recipe.slot_child.motif == name)
    # The design must be valid and meet the region floor whether or not the motif was placed.
    report = generator.last_validation_result
    if not report.is_valid:
        return result('FAIL', report.issues[0] if report.issues else 'invalid', dropped)
    cells = sum(ring_divisions[1:])
    floor = REGION_FLOOR * cells
    regions = report.stats.get('num_regions', 0)
    if regions < floor:
        return result('FAIL', f"only {regions} regions for {cells} cells (floor {floor:.0f})", dropped)
    if placed == 0 and role == 'slot' and not probe:
        # The gate measured pass one; pull-backs and nestling reshape a frame afterwards. When the slot
        # every frame really ended with refuses the child, nothing could have been placed. Only a design
        # that is otherwise sound gets here, and the skip carries its own tag so shrinkage stays visible.
        refusals = _final_slot_refusals(entry, generator)
        if refusals:
            return result('SKIP', f"{FINAL_SLOT_TAG} no final frame slot admits the child; " + refusals[0], dropped)
    if placed == 0:
        return result('FAIL', f"forced motif never placed ({dropped} dropped)", dropped)
    # A child that does not fit its cell's real slot is dropped gracefully: reported, not failed.
    partial = f"{placed} placed, {dropped} dropped" if dropped else ''
    return result('PASS', partial, dropped)


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


def _angle_between_deg(a, b):
    """Angle in degrees between two page-space direction vectors, 0 to 180."""
    norm = math.hypot(*a) * math.hypot(*b)
    if norm == 0:
        return 0.0
    cosine = (a[0] * b[0] + a[1] * b[1]) / norm
    return math.degrees(math.acos(max(-1.0, min(1.0, cosine))))


def tangent_error_deg(context: MotifContext, points: List[CellPoint], index: int) -> float:
    """
    Angle in degrees, 0 to 90, between the page-space tangent at `points[index]` and the radial
    direction there. The tangent is the chord between the vertex's two neighbours (wrapping round,
    so it suits a closed outline); a side-touch vertex whose tangent is parallel to the divider reads 0.
    """
    before = context.to_cartesian(points[(index - 1) % len(points)])
    after = context.to_cartesian(points[(index + 1) % len(points)])
    x, y = context.to_cartesian(points[index])
    tangent = (after[0] - before[0], after[1] - before[1])
    radial = (x - context.center[0], y - context.center[1])
    angle = _angle_between_deg(tangent, radial)
    return min(angle, 180.0 - angle)


def max_turn_deg(context: MotifContext, points: List[CellPoint], closed: bool, skip: Set[int]) -> float:
    """
    The largest page-space turning angle, in degrees, at any vertex of the traced polyline except the
    vertices in `skip` (indices into `points`). Each cell-space segment is traced as `polyline` draws
    it, so the bends of its subdivisions count too; an open run's two ends never turn.
    """
    count = len(points)
    coords, owners = [], []
    for index in range(count if closed else count - 1):
        segment = context.polyline(SmartVector([points[index], points[(index + 1) % count]]))
        coords.extend(segment[:-1])
        owners.extend([index] + [None] * (len(segment) - 2))
    if not closed:
        coords.append(context.to_cartesian(points[-1]))
        owners.append(count - 1)
    # Zero-length pieces have no direction: drop repeated coordinates, keeping the first owner.
    kept = []
    for coord, owner in zip(coords, owners):
        if kept and math.dist(kept[-1][0], coord) < 1e-12:
            continue
        kept.append((coord, owner))
    if closed and len(kept) > 1 and math.dist(kept[0][0], kept[-1][0]) < 1e-12:
        kept.pop()
    total = len(kept)
    worst = 0.0
    for k in range(total):
        if not closed and (k == 0 or k == total - 1):
            continue
        if kept[k][1] in skip:
            continue
        previous, here, following = kept[k - 1][0], kept[k][0], kept[(k + 1) % total][0]
        incoming = (here[0] - previous[0], here[1] - previous[1])
        outgoing = (following[0] - here[0], following[1] - here[1])
        worst = max(worst, _angle_between_deg(incoming, outgoing))
    return worst


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
    if entry.get('seams', False):
        # A seam motif only ever has the full budget (spec 4.1): it must end on the edges, never past them.
        inst = _generate(entry, 3, radial_limits=(0.0, 1.0))
        return all(-0.03 <= p.radial <= 1.03 and abs(p.angular) <= 1.0 for p in _points(inst))
    inst = _generate(entry, 3, radial_limits=(0.0, 1.0), angular_limits=0.5)
    return all(-0.03 <= p.radial <= 1.03 and abs(p.angular) <= 0.53 for p in _points(inst))


def _slot(entry):
    if not entry['slot_estimate']:
        return True
    return _generate(entry, 9).declaration.slot is not None


def _seam(entry):
    """
    A seam motif's open ends sit at angular exactly +-1.0, and two cells of one ring (seeds 11 and 12,
    one `ring_stream_seed`) draw identical vectors, so neighbours meet along the shared edge.
    """
    if not entry.get('seams', False):
        return True
    ring_seed = ring_stream_seed(7, 1, f"ring:{entry['name']}:divider")
    first = _generate(entry, 11, ring_stream_seed=ring_seed)
    second = _generate(entry, 12, ring_stream_seed=ring_seed)
    ends = [vector.points[k] for vector in first.vectors if not vector.closed for k in (0, -1)]
    return (all(abs(point.angular) == 1.0 for point in ends)
            and [(v.points, v.closed) for v in first.vectors] == [(v.points, v.closed) for v in second.vectors])


# Radial of the shared side vertex per touch height; both sit inside the ranges the composer draws from.
TOUCH_RADIALS = {'base': 0.12, 'mid': 0.45}
TANGENT_LIMIT_DEG = 10.0


def _tangent(entry):
    """
    At each declared touch height the outline's side-touch vertex runs along the divider: the tangent
    there is within `TANGENT_LIMIT_DEG` of radial for seeds 0 to 5. A missing touch vertex fails.
    """
    for height in entry.get('side_touch_heights', ()):
        radial = TOUCH_RADIALS[height]
        for seed in range(6):
            context = MotifContext(**PROPERTY_CELL, rng=random.Random(seed), side_touch_radial=radial)
            instance = entry['generator'](context)
            found = [(vector.points, k) for vector in instance.vectors if vector.closed
                     for k, p in enumerate(vector.points) if p.radial == radial and abs(p.angular) == 1.0]
            sides = {points[k].angular for points, k in found}
            if sides != {1.0, -1.0}:  # both touch vertices must exist
                return False
            if any(tangent_error_deg(context, points, k) > TANGENT_LIMIT_DEG for points, k in found):
                return False
    return True


def property_checks(entry):
    """Run the generator property checks on the standard test cell."""
    checks = {'deterministic': _deterministic, 'monotone': _monotone,
              'angular': _angular, 'slot': _slot, 'seam': _seam, 'tangent': _tangent}
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

    header = (f"{'MOTIF':16} {'PASS':>5} {'SKIP':>5} {'FAIL':>5} {'CONTR':>6} {'ERR':>4} {'DROP':>5} "
              f"{'DET':>5} {'MONO':>5} {'ANG':>5} {'SLOT':>5} {'SEAM':>5} {'TANG':>5}")
    print(header)
    print("-" * len(header))
    failed = []
    for entry in entries:
        name = entry['name']
        rows = by_motif.get(name, [])
        counts = {k: sum(1 for r in rows if r['status'] == k) for k in STATUSES}
        dropped = sum(r.get('dropped', 0) for r in rows)  # slot children dropped where they did not fit
        props = property_checks(entry)
        mark = {True: 'ok', False: 'BAD'}
        if counts['FAIL'] or counts['CONTRACT'] or counts['ERROR'] or not all(props.values()):
            failed.append(name)
        print(f"{name:16} {counts['PASS']:>5} {counts['SKIP']:>5} {counts['FAIL']:>5} "
              f"{counts['CONTRACT']:>6} {counts['ERROR']:>4} {dropped:>5} "
              f"{mark[props['deterministic']]:>5} {mark[props['monotone']]:>5} "
              f"{mark[props['angular']]:>5} {mark[props['slot']]:>5} "
              f"{mark[props['seam']]:>5} {mark[props['tangent']]:>5}")

    if failed:
        print("\nFailing cases:")
        for name in failed:
            for result in by_motif.get(name, []):
                if result['status'] not in ('PASS', 'SKIP'):
                    print(f"  {result['name']:14} {result['label']:48} "
                          f"[{result['status']}] {result['detail']}")

    final_slot = sum(1 for r in results if r['detail'].startswith(FINAL_SLOT_TAG))
    if final_slot:
        print(f"\n{final_slot} slot job(s) skipped because pull-backs left every frame's slot too small "
              f"({FINAL_SLOT_TAG}); a rising count means frames are shrinking.")
    print("-" * len(header))
    total_pass = sum(1 for r in results if r['status'] == 'PASS')
    print(f"{total_pass}/{len(results)} cases passed across "
          f"{len(entries) - len(failed)}/{len(entries)} motifs.")
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
