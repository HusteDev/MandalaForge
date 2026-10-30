"""`TopologyValidator._overflow_crossings` with one spatial tree for every overflow part, against the old one."""

from typing import List, Tuple

import pytest
from shapely.geometry import LineString
from shapely.geometry import Point as ShPoint
from shapely.strtree import STRtree

from coloring_generator import DesignGenerator
from topology_validator import TopologyValidator, _near_vertex


def old_overflow_crossings(polylines, overflow_parts, ring_ids) -> List[Tuple[int, Tuple[float, float]]]:
    """The implementation before the shared tree (commit c2cd833), kept as the oracle: one tree per part."""
    if overflow_parts is None or ring_ids is None:
        return []
    found = []
    for ring, line in overflow_parts:
        others = [
            (i, LineString(pts)) for i, pts in enumerate(polylines)
            if ring_ids[i] != ring and len(set(map(tuple, pts))) >= 2
        ]
        if not others:
            continue
        tree = STRtree([g for _, g in others])
        ends = [ShPoint(line.coords[0]), ShPoint(line.coords[-1])]
        for k in sorted(tree.query(line, predicate='intersects')):
            other_index, other = others[int(k)]
            hit = line.intersection(other)
            if hit.is_empty:
                continue
            parts = list(hit.geoms) if hasattr(hit, 'geoms') else [hit]
            if all(
                part.geom_type == 'Point' and (
                    any(e.distance(part) <= 1e-6 for e in ends)
                    or (_near_vertex(part, line.coords) and _near_vertex(part, other.coords))
                )
                for part in parts
            ):
                continue
            at = hit.centroid
            found.append((ring_ids[other_index], (at.x, at.y)))
    return found


DESIGNS = [
    {"seed": 7, "num_rings": 6, "complexity": 0.85, "categories": ["botanical", "geometric"], "vary_divisions": True},
    {"seed": 42, "force_position_mode": "layered"},
    {"seed": 23, "vary_divisions": True, "categories": ["botanical", "geometric"]},
    {"seed": 4, "complexity": 0.85},
    {"seed": 19, "categories": ["geometric"]},
    {"seed": 777, "complexity": 0.85, "categories": ["geometric"]},
]


@pytest.fixture(scope="module")
def design_inputs():
    inputs = []
    for case in DESIGNS:
        g = DesignGenerator(**case)
        g.generate(validate=False)
        a = g.assembled
        inputs.append((a.polylines(), a.overflow_parts(), a.ring_ids()))
    return inputs


def test_real_designs_give_the_same_crossings(design_inputs):
    parts = 0
    for polylines, overflow_parts, ring_ids in design_inputs:
        parts += len(overflow_parts)
        assert TopologyValidator._overflow_crossings(polylines, overflow_parts, ring_ids) == \
            old_overflow_crossings(polylines, overflow_parts, ring_ids)
    assert parts > 0


def test_many_crossings_and_touches_come_in_the_same_order(design_inputs):
    """Every path of each ring stands in as an overflow part of the next ring out, so most parts cross or touch."""
    found = 0
    for polylines, _, ring_ids in design_inputs:
        parts = [(ring + 1, LineString(pts)) for pts, ring in zip(polylines, ring_ids) if len(set(map(tuple, pts))) >= 2]
        new = TopologyValidator._overflow_crossings(polylines, parts, ring_ids)
        assert new == old_overflow_crossings(polylines, parts, ring_ids)
        found += len(new)
    assert found > 100


def test_edge_cases_match():
    square = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0), (0.0, 0.0)]
    polylines = [square, [(5.0, 5.0), (5.0, 5.0)], [(-5.0, 5.0), (15.0, 5.0)], [(5.0, -5.0), (5.0, 0.0)]]
    ring_ids = [0, 1, 1, 2]
    cases = [
        [(0, LineString([(-5.0, 5.0), (15.0, 5.0)]))],              # its own ring's ink is skipped
        [(1, LineString([(5.0, -5.0), (5.0, 15.0)]))],              # crosses the square twice, the line once
        [(2, LineString([(5.0, -5.0), (5.0, 0.0)]))],               # ends on the square
        [(0, LineString([(20.0, 20.0), (30.0, 30.0)]))],            # touches nothing
        [(5, LineString([(0.0, 5.0), (10.0, 5.0)])), (1, LineString([(2.0, -1.0), (2.0, 11.0)]))],
        [],
    ]
    for parts in cases:
        assert TopologyValidator._overflow_crossings(polylines, parts, ring_ids) == \
            old_overflow_crossings(polylines, parts, ring_ids)
    lone = [(1, LineString([(0.0, 0.0), (1.0, 1.0)]))]
    assert TopologyValidator._overflow_crossings([[(0.0, 0.0), (2.0, 2.0)]], lone, [1]) == []
    assert TopologyValidator._overflow_crossings(polylines, None, ring_ids) == []
    assert TopologyValidator._overflow_crossings(polylines, cases[1], None) == []
