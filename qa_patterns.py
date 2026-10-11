"""
Per-motif coverage harness.

`qa_report.py --corpus` only exercises whichever motifs random selection happens
to pick, so a motif can ship untested. This harness forces each registered motif
in turn, in every position and role it supports, over a matrix of ring-division
fixtures, and drives the REAL generation pipeline. Forcing disables the fallback
chain (a rejection is a visible failure, not a silent substitution) and never
applies to ring 0.

It also runs each motif with each embellishment it accepts (forced onto every
node of the motif under test), and each layered front with each back motif in
forced layered rings. Across the matrix, every such embellishment must be drawn
somewhere and every front/back pair must keep its back somewhere, or the motif
fails: a pairing that is always dropped is not covered.

It checks eight properties of each motif's generator on a standard cell:
determinism, narrower radial limits never reaching further, angular containment,
an honest slot declaration, seam ends on the cell edges, smooth side touch, back
ends that are seam ends or front-outline vertices after the occlusion cut (CUT),
and determinism and monotony with every accepted embellishment (EMB).

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
from composer import (CellRecipe, Composer, ComposerSettings, node_rng, pick_embellishments, ring_stream_seed,
                      touch_heights_of)
from motifs import MOTIFS, find_motif, safe_motif
from motifs.contract import MotifError
from motifs.embellish import EMBELLISHMENT_ORDER, INTERIOR_FILLS
from motifs.geometry import CellPoint, MotifContext, SmartVector
from motifs.layering import LayeringError, compose_layered

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


def _fixture_composer(generator):
    """
    The composer `generate()` builds for this fixture, with the generator's own settings. The gates
    read each forced ring's division count, centre share, contact mode and side-touch radial from
    its plan, and the pairing jobs edit that plan before assembling it.
    """
    settings = ComposerSettings(
        num_divisions=generator.num_divisions, vary_divisions=generator.vary_divisions,
        ring_divisions=generator.ring_divisions, complexity=generator.complexity,
        min_pattern_size=generator.min_pattern_size, categories=generator.categories,
        force_motif=generator.force_motif, ring_seeds=generator.ring_seeds,
        force_position_mode=generator.force_position_mode,
        force_embellishments=generator.force_embellishments,
    )
    return Composer(generator.seed, generator.rings, settings)


def _fixture_plan(generator):
    """The plan `_fixture_composer` draws (planning draws nothing)."""
    return _fixture_composer(generator).plan()


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


# ------------------------------------------------------- pairing jobs (spec 11)

def layered_fronts():
    """The motifs a layered ring may draw in front: non-seam bases that touch at base height."""
    return [entry for entry in MOTIFS
            if 'base' in entry['roles'] and not entry.get('seams', False) and 'base' in touch_heights_of(entry)]


def layered_pairs():
    """Every (front, back) motif pair a layered ring can draw."""
    backs = [entry['name'] for entry in MOTIFS if 'back' in entry['roles']]
    return [(front['name'], back) for front in layered_fronts() for back in backs]


def _assemble_edited(generator, edit):
    """
    Plan as `generate()` does, let `edit(composer, plan)` change the plan, then assemble and validate it
    exactly as `generate()` would (a failing layered ring drops its back and assembles again). Returns
    what `edit` returns.
    """
    generator.composer = _fixture_composer(generator)
    generator.plan = generator.composer.plan()
    edited = edit(generator.composer, generator.plan)
    generator.assembled = generator._assemble()
    generator._validate()
    return edited


def _force_embellishment(name, embellishment):
    """A plan edit giving every base node of `name` past ring 0 exactly `[embellishment]`."""
    def edit(composer, plan):
        edited = 0
        for ring in plan.rings[1:]:
            for entry in ring.sequence:
                for node in (entry.centre, entry.divider):
                    if node is None or node.motif != name or node.is_fallback:
                        continue
                    node.embellishments = [embellishment]
                    if embellishment in INTERIOR_FILLS:  # an interior fill takes the slot (spec 6.4)
                        node.slot_child = None
                    edited += 1
        return edited
    return edit


def _force_layered_pair(front_name, back_name):
    """
    A plan edit drawing `front_name` in front of `back_name` in every layered ring past ring 0 where both
    pass the composer's own size gates. Fronts are composed as the composer composes them (embellishments
    and slot chain from the node's streams), keeping the planned node's contact flags; the back's
    embellishments are picked from the stream `_plan_back` uses. Returns the edited ring indices.
    """
    front, back = find_motif(front_name), find_motif(back_name)

    def edit(composer, plan):
        edited = []
        for ring in plan.rings[1:]:
            if ring.back is None:
                continue
            cell_width, ring_depth = composer._ring_metrics(ring.ring_index, ring.divisions)
            if not (composer._passes(front, cell_width, ring_depth) and composer._passes(back, cell_width, ring_depth)):
                continue
            for s, entry in enumerate(ring.sequence):
                old = entry.centre
                node = composer._compose(front, node_rng(ring.ring_seed, ring.ring_index, s, 0, 'centre'),
                                         ring.ring_index, ring.ring_seed, s, 'centre', cell_width, ring_depth, 0)
                node.provides_contact = old.provides_contact
                node.attachments = old.attachments
                entry.centre = node
            ring.back = CellRecipe(back['name'], back['category'])
            ring.back.embellishments = pick_embellishments(
                back, composer.settings.complexity,
                node_rng(ring.ring_seed, ring.ring_index, 0, 0, 'divider', 'pick:emb'))
            edited.append(ring.ring_index)
        return edited
    return edit


def _run_variant(entry, category, ring_divisions, complexity, min_white, position, seed, probe, variant, result):
    """
    One pairing job. `('emb', name)` forces the motif as a base with exactly that embellishment on every
    node; `drawn` counts the forced nodes that drew it, `dropped` those where it did not fit. `('back',
    name)` forces layered rings with the motif in front of that back; `drawn` counts the forced rings that
    kept their back, `dropped` those that dropped it (spec 5.4). A drop is legitimate in one case; the
    summary fails a pairing that is never drawn anywhere in the matrix.
    """
    kind, other = variant
    name = entry['name']
    try:
        with redirect_stdout(io.StringIO()):
            if kind == 'emb':
                generator = DesignGenerator(
                    seed=seed, num_rings=len(ring_divisions), num_divisions=ring_divisions[0],
                    complexity=complexity, min_pattern_size=min_white, categories=[category],
                    ring_divisions=list(ring_divisions),
                    force_motif={'name': name, 'position': position, 'role': 'base'},
                )
                if not probe:
                    reason = _gate_skip(entry, generator, position, 'base')
                    if reason:
                        return result('SKIP', reason)
                edited = _assemble_edited(generator, _force_embellishment(name, other))
            else:
                categories = sorted({category, find_motif(other)['category']})
                generator = DesignGenerator(
                    seed=seed, num_rings=len(ring_divisions), num_divisions=ring_divisions[0],
                    complexity=complexity, min_pattern_size=min_white, categories=categories,
                    ring_divisions=list(ring_divisions), force_position_mode='layered',
                )
                edited = _assemble_edited(generator, _force_layered_pair(name, other))
    except MotifError as exc:
        return result('CONTRACT', str(exc))
    except ValueError as exc:  # includes AssemblyError
        text = str(exc)
        if 'Invalid' in text or 'MotifError' in text:
            return result('CONTRACT', text)
        return result('ERROR', f"{type(exc).__name__}: {text}")
    except Exception as exc:
        return result('ERROR', f"{type(exc).__name__}: {exc}")

    if not edited:
        return result('SKIP', "no ring admits the pairing")
    report = generator.last_validation_result
    if kind == 'emb':
        forced = [node for node in generator.assembled.nodes
                  if node.parent is None and node.ring_index > 0 and node.recipe.motif == name
                  and node.recipe.embellishments == [other]]
        drawn = sum(1 for node in forced if node.instance.dropped_embellishments == 0)
        dropped = len(forced) - drawn
    else:
        rings = [ring for ring in generator.plan.rings if ring.ring_index in edited]
        drawn = sum(1 for ring in rings if ring.back is not None)
        dropped = sum(1 for ring in rings if ring.back_dropped)
    if not report.is_valid:
        return result('FAIL', report.issues[0] if report.issues else 'invalid', dropped, drawn)
    cells = sum(ring_divisions[1:])
    floor = REGION_FLOOR * cells
    regions = report.stats.get('num_regions', 0)
    if regions < floor:
        return result('FAIL', f"only {regions} regions for {cells} cells (floor {floor:.0f})", dropped, drawn)
    if kind == 'emb' and not forced:
        return result('FAIL', "forced motif never placed", dropped, drawn)
    noun = 'drawn' if kind == 'emb' else 'kept'
    return result('PASS', f"{drawn} {noun}, {dropped} dropped" if dropped else '', dropped, drawn)


def run_case(job):
    name, category, ring_divisions, complexity, min_white, position, role, seed, probe, *rest = job
    variant = rest[0] if rest else None
    # An explicit division list's base symmetry is its gcd (spec 13.1).
    symmetry = Composer.base_symmetry(ring_divisions[0], False, list(ring_divisions), None)
    label = (f"div{'-'.join(map(str, ring_divisions))}_B{symmetry}_c{complexity}"
             f"_mws{min_white}_{position}_{role}" + (f"_{variant[0]}-{variant[1]}" if variant else ''))

    def result(status, detail='', dropped=0, drawn=0):
        return {'name': name, 'label': label, 'status': status, 'detail': detail[:200], 'dropped': dropped,
                'variant': variant, 'drawn': drawn}

    if variant is not None:
        entry = find_motif(name)
        if entry is None:
            return result('ERROR', f"unknown motif {name}")
        if variant[0] == 'emb' and not _supports(entry, position, 'base'):
            return result('SKIP', f"{position}/base unsupported")
        return _run_variant(entry, category, ring_divisions, complexity, min_white, position, seed, probe,
                            variant, result)

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
    context = MotifContext(**dict(PROPERTY_CELL, rng=random.Random(seed), **over))
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


def turn_at(context: MotifContext, points: List[CellPoint], index: int) -> float:
    """
    The page-space turning angle, in degrees, at the vertex `points[index]` of a closed outline (indices
    wrap): the angle between the traced piece arriving at the vertex and the traced piece leaving it, each
    the last or first subdivision `polyline` draws, as `max_turn_deg` reads it. 0 is straight on.
    """
    count = len(points)
    here = points[index % count]
    before = next((points[(index - k) % count] for k in range(1, count) if points[(index - k) % count] != here), here)
    after = next((points[(index + k) % count] for k in range(1, count) if points[(index + k) % count] != here), here)
    arriving = context.polyline(SmartVector([before, here]))
    leaving = context.polyline(SmartVector([here, after]))
    incoming = (arriving[-1][0] - arriving[-2][0], arriving[-1][1] - arriving[-2][1])
    outgoing = (leaving[1][0] - leaving[0][0], leaving[1][1] - leaving[0][1])
    return _angle_between_deg(incoming, outgoing)


def _deterministic(entry, **over):
    first, second = _generate(entry, 11, **over), _generate(entry, 11, **over)
    return ([(v.points, v.closed, v.weight) for v in first.vectors]
            == [(v.points, v.closed, v.weight) for v in second.vectors])


def _monotone(entry, **over):
    wide = _points(_generate(entry, 5, radial_limits=(-0.25, 1.25), **over))
    narrow = _points(_generate(entry, 5, radial_limits=(-0.1, 1.1), **over))
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


# The front every back is cut against in the CUT check; the complexity the EMB check embellishes at, and
# the white spaces it tries for each embellishment alone.
CUT_FRONT = 'petal'
EMB_COMPLEXITY = 0.9
EMB_WHITE_SPACES = (10.0, 5.0)


def _cut(entry):
    """
    CUT (spec 11): for a motif with role "back", `compose_layered` with a `CUT_FRONT` front touching at base
    height and this back, at seeds 0 to 5, leaves every open back end either a seam end (angular exactly
    +-1.0) or exactly a vertex of a front outline, so every occlusion cut is a vertex of the front. A seed
    whose composite raises `LayeringError` is a legitimate drop (spec 5.4), but at least one seed must
    compose. A motif with no "back" role passes.
    """
    if 'back' not in entry['roles']:
        return True
    front = find_motif(CUT_FRONT)
    composed = 0
    for seed in range(6):
        front_context = MotifContext(**PROPERTY_CELL, rng=random.Random(seed), node_seed=seed,
                                     side_touch_radial=TOUCH_RADIALS['base'])
        back_seed = 1000 + seed
        back_context = MotifContext(**PROPERTY_CELL, rng=random.Random(back_seed), node_seed=back_seed,
                                    ring_stream_seed=back_seed, position='divider', angular_limits=1.0,
                                    radial_limits=(0.0, 1.0))
        try:
            instance = compose_layered(front_context, front, back_context, entry)
        except LayeringError:
            continue
        composed += 1
        vertices = {(p.radial, p.angular) for v in instance.vectors
                    if v.layer != 'back' and v.closed for p in v.points}
        for vector in instance.vectors:
            if vector.layer != 'back' or vector.closed:
                continue
            for end in (vector.points[0], vector.points[-1]):
                if abs(end.angular) != 1.0 and (end.radial, end.angular) not in vertices:
                    return False
    return composed > 0


def embellishment_sets(entry):
    """
    The largest embellishment sets the motif accepts together, in `EMBELLISHMENT_ORDER`: everything it
    accepts, with one interior fill at a time (spec 6.4 keeps at most one).
    """
    accepted = entry['embellishments']
    fills = [name for name in accepted if name in INTERIOR_FILLS] or [None]
    return [tuple(name for name in EMBELLISHMENT_ORDER
                  if name in accepted and (name not in INTERIOR_FILLS or name == fill))
            for fill in fills] if accepted else []


def _embellished(entry):
    """
    EMB (spec 11): DET and MONO hold at `EMB_COMPLEXITY` with each of the motif's `embellishment_sets` and
    with each accepted embellishment alone. So the check is never vacuous, each embellishment alone must
    also be drawn on the standard cell at one of `EMB_WHITE_SPACES` (a band's beads need more room between
    its arcs than 10px of white leaves on the standard cell), and DET and MONO hold there too.
    """
    base = dict(complexity=EMB_COMPLEXITY, node_seed=17, ring_stream_seed=23)
    for names in embellishment_sets(entry):
        if not (_deterministic(entry, embellishments=names, **base)
                and _monotone(entry, embellishments=names, **base)):
            return False
    for name in entry['embellishments']:
        drawn_at = [white for white in EMB_WHITE_SPACES
                    if _generate(entry, 11, embellishments=(name,), min_white_space=white,
                                 **base).dropped_embellishments == 0]
        if not drawn_at:
            return False
        over = dict(base, embellishments=(name,), min_white_space=drawn_at[0])
        if not (_deterministic(entry, **over) and _monotone(entry, **over)):
            return False
    return True


def property_checks(entry):
    """Run the generator property checks on the standard test cell."""
    checks = {'deterministic': _deterministic, 'monotone': _monotone,
              'angular': _angular, 'slot': _slot, 'seam': _seam, 'tangent': _tangent,
              'cut': _cut, 'embellished': _embellished}
    outcome = {}
    for key, check in checks.items():
        try:
            outcome[key] = bool(check(entry))
        except Exception:  # a crashing generator fails the property, it does not stop the run
            outcome[key] = False
    return outcome


# ------------------------------------------------------------------------ CLI

def _variants(entry, matrix):
    """
    The pairing jobs' (position, role, variant) triples for one motif: each accepted embellishment as a
    base in each single position, and, for a layered front, each back in a forced layered ring.
    """
    triples = [(position, 'base', ('emb', name))
               for name in entry['embellishments']
               for position in matrix['position'] if position != 'both']
    triples += [('layered', 'base', ('back', back))
                for front, back in layered_pairs() if front == entry['name']]
    return triples


def build_jobs(entries, matrix, seed, probe):
    """Every forced job, then every pairing job; a job's tenth field is its pairing variant (None for none)."""
    return [
        (entry['name'], entry['category'], ring_divisions, complexity, min_white,
         position, role, seed, probe, variant)
        for entry in entries
        for position, role, variant in (
            [(position, role, None) for position in matrix['position'] for role in matrix['role']]
            + _variants(entry, matrix))
        for ring_divisions in matrix['ring_divisions']
        for complexity in matrix['complexity']
        for min_white in matrix['min_white']
    ]


def uncovered_pairings(results):
    """
    The pairing variants, per motif, that ran but were never drawn anywhere in `results`: an embellishment
    no forced node drew, or a back no forced layered ring kept. Each is a coverage failure of its motif.
    """
    ran, drawn = {}, set()
    for result in results:
        variant = result.get('variant')
        if variant is None or result['status'] == 'SKIP':
            continue
        ran.setdefault(result['name'], set()).add(variant)
        if result.get('drawn', 0):
            drawn.add((result['name'], variant))
    return {name: sorted(v for v in variants if (name, v) not in drawn)
            for name, variants in ran.items() if any((name, v) not in drawn for v in variants)}


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
    pairing = sum(1 for job in jobs if job[9] is not None)
    print(f"{len(entries)} motif(s): {len(jobs) - pairing} forced + {pairing} pairing "
          f"= {len(jobs)} runs ({args.tier} tier, {args.jobs} workers)\n")

    if args.jobs > 1 and len(jobs) > 1:
        with ProcessPoolExecutor(max_workers=args.jobs) as pool:
            results = list(pool.map(run_case, jobs, chunksize=4))
    else:
        results = [run_case(job) for job in jobs]

    by_motif = {}
    for result in results:
        by_motif.setdefault(result['name'], []).append(result)

    uncovered = uncovered_pairings(results)
    header = (f"{'MOTIF':16} {'PASS':>5} {'SKIP':>5} {'FAIL':>5} {'CONTR':>6} {'ERR':>4} {'DROP':>5} "
              f"{'DET':>5} {'MONO':>5} {'ANG':>5} {'SLOT':>5} {'SEAM':>5} {'TANG':>5} {'CUT':>5} {'EMB':>5}")
    print(header)
    print("-" * len(header))
    failed = []
    for entry in entries:
        name = entry['name']
        rows = by_motif.get(name, [])
        counts = {k: sum(1 for r in rows if r['status'] == k) for k in STATUSES}
        # Slot children, embellishments and back layers dropped where they did not fit.
        dropped = sum(r.get('dropped', 0) for r in rows)
        props = property_checks(entry)
        mark = {True: 'ok', False: 'BAD'}
        if (counts['FAIL'] or counts['CONTRACT'] or counts['ERROR'] or not all(props.values())
                or name in uncovered):
            failed.append(name)
        print(f"{name:16} {counts['PASS']:>5} {counts['SKIP']:>5} {counts['FAIL']:>5} "
              f"{counts['CONTRACT']:>6} {counts['ERROR']:>4} {dropped:>5} "
              f"{mark[props['deterministic']]:>5} {mark[props['monotone']]:>5} "
              f"{mark[props['angular']]:>5} {mark[props['slot']]:>5} "
              f"{mark[props['seam']]:>5} {mark[props['tangent']]:>5} "
              f"{mark[props['cut']]:>5} {mark[props['embellished']]:>5}")

    if failed:
        print("\nFailing cases:")
        for name in failed:
            for result in by_motif.get(name, []):
                if result['status'] not in ('PASS', 'SKIP'):
                    print(f"  {result['name']:14} {result['label']:48} "
                          f"[{result['status']}] {result['detail']}")
            for kind, other in uncovered.get(name, []):
                what = 'embellishment' if kind == 'emb' else 'back'
                print(f"  {name:14} {what} {other} was never drawn in any case of the matrix")

    final_slot = sum(1 for r in results if r['detail'].startswith(FINAL_SLOT_TAG))
    if final_slot:
        print(f"\n{final_slot} slot job(s) skipped because pull-backs left every frame's slot too small "
              f"({FINAL_SLOT_TAG}); a rising count means frames are shrinking.")
    print("-" * len(header))
    total_pass = sum(1 for r in results if r['status'] == 'PASS')
    print(f"{total_pass}/{len(results)} cases passed across "
          f"{len(entries) - len(failed)}/{len(entries)} motifs.")
    pairings = {}
    for result in results:
        if result.get('variant') is not None and result['status'] == 'PASS':
            tally = pairings.setdefault((result['name'], result['variant']), [0, 0])
            tally[0] += result['drawn']
            tally[1] += result['dropped']
    if pairings:
        print("Pairings drawn/dropped: " + ", ".join(
            f"{name}+{kind}:{other}={drawn}/{dropped}" for (name, (kind, other)), (drawn, dropped) in sorted(pairings.items())))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
