"""
Topology-based QA validator for mandala coloring pages.

Rather than reasoning about proximity, this module builds the
TRUE planar arrangement of all linework using exact geometry (Shapely/GEOS) and
derives three ground-truth answers:

1. DANGLES  - after noding every real crossing, any line endpoint with graph
              degree 1 connects to nothing: a "line into nowhere".
2. REGIONS  - polygonizing the arrangement yields the actual faces a person
              would color. Faces below a minimum area, or too thin to fit a
              pen tip (negative-buffer erosion test), are un-colorable.
3. ISLANDS  - connected components of the linework graph. An OPEN component
              floating in space is a defect. Isolated CLOSED loops are allowed
              by default because concentric circles are normal mandala
              structure (they still produce colorable regions).
4. LANES    - radii at which a full circle around the centre crosses no ink at
              all. That is a corridor running the whole way around the design,
              so a colourist can travel around it without ever crossing a line
              and the "region" is a single uninterrupted band.

The report also carries every region polygon, so a debug overlay can fill each
face with a random pastel - a machine-made "coloring test" for visual QA.
"""

import math
import random
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import shapely as _shapely
from shapely import STRtree
from shapely.geometry import LineString, MultiLineString, Point as ShPoint, Polygon
from shapely.ops import polygonize_full, unary_union

Coord = Tuple[float, float]

# Coordinates are merged into one graph node when within this rounding grid.
# The union output shares exact coordinates at nodes, so this only guards
# against float noise.
_NODE_DECIMALS = 4

# A face must fit a pen tip of this radius somewhere, and be at least this large.
# The generator validates with these, and the engine checks the strokes it adds against them.
PEN_RADIUS_PX = 2.0
MIN_REGION_AREA_PX2 = 20.0

# The page prints at 72 px per inch. No colourable face may exceed a complexity-scaled print size.
PX_PER_INCH = 72.0


def max_region_in2(complexity: float) -> float:
    """The largest face allowed, in square inches: 1.25 at complexity 0 down to 0.6 at complexity 1."""
    return 1.25 - 0.65 * max(0.0, min(1.0, complexity))


def max_region_px2(complexity: float) -> float:
    """`max_region_in2` in square pixels."""
    return max_region_in2(complexity) * PX_PER_INCH * PX_PER_INCH


@dataclass
class RegionInfo:
    """One colorable face of the design."""
    polygon: Polygon          # true face (holes resolved)
    area: float
    is_tiny: bool             # below min_region_area
    is_too_thin: bool         # fails the pen-tip erosion test
    label_point: Coord        # a point guaranteed inside the face

    @property
    def is_uncolorable(self) -> bool:
        return self.is_tiny or self.is_too_thin


@dataclass
class ComponentInfo:
    """One connected component of the linework graph."""
    edge_indices: List[int]
    total_length: float
    bounds: Tuple[float, float, float, float]
    is_closed: bool           # no degree-1 endpoints anywhere in the component
    is_main: bool


@dataclass
class TopologyReport:
    """
    Result of topology analysis.

    Attribute names is_valid / issues / unconnected_shapes / tiny_regions match
    the legacy ValidationResult so existing callers (app.py, generation loop)
    keep working.
    """
    is_valid: bool
    issues: List[str]
    unconnected_shapes: List[Any]                 # dangling endpoints (ShPoint)
    tiny_regions: List[Tuple[Any, Any]]           # (polygon, ShPoint centroid)

    dangle_points: List[Coord] = field(default_factory=list)
    dangle_lines: List[LineString] = field(default_factory=list)
    floating_components: List[ComponentInfo] = field(default_factory=list)
    isolated_loops: List[ComponentInfo] = field(default_factory=list)
    regions: List[RegionInfo] = field(default_factory=list)
    free_lanes: List[Tuple[float, float]] = field(default_factory=list)
    encircling_regions: List[RegionInfo] = field(default_factory=list)
    # Faces above the print-size cap. Reported, never an issue: the repair ladder reads them.
    oversized_regions: List[RegionInfo] = field(default_factory=list)
    stats: Dict[str, Any] = field(default_factory=dict)


class TopologyValidator:
    """
    Exact planar-topology QA for coloring-page linework.

    The cleaning pipeline mirrors standard cartographic topology repair:
    node everything, prune short overshoot whiskers, bridge sub-stroke gaps,
    then measure. Whiskers and gaps smaller than a stroke width look connected
    on paper, so only larger defects are reported.

    Args:
        snap_tolerance: dangling endpoints within this distance of other
            linework are bridged onto it (treated as connected). Should be
            about the rendered stroke width.
        whisker_tolerance: dangling stubs shorter than this are pruned before
            analysis. Kept deliberately small: it exists to swallow the
            sub-pixel tails left by snap-rounding and by the gap-bridging pass,
            NOT to excuse visible overshoot. A 2px stub past a boundary arc is a
            loose line end on the printed page, so it must be reported.
        pen_radius: erosion radius for the pen-tip test. A face that vanishes
            when eroded by this radius is too thin to color anywhere. Covers
            half the stroke width plus a fine marker tip.
        min_region_area: faces smaller than this (px^2) are un-colorable.
        min_lane_px: a radial gap in the ink at least this wide counts as a
            free lane around the design. Below it the gap is thinner than a pen
            tip and reads as a join rather than a corridor.
        ink_radius: half the rendered stroke width. A face that vanishes when
            eroded by this radius lies entirely under the drawn ink (e.g. the
            sliver between two nearly-coincident arcs) - it is invisible when
            rendered, so it is dropped as an artifact rather than a defect.
        sliver_area: faces below this are dropped as numerical artifacts.
        fail_on_isolated_loops: treat isolated closed loops as errors instead
            of allowed structure.
    """

    def __init__(
        self,
        snap_tolerance: float = 2.5,
        whisker_tolerance: float = 1.0,
        pen_radius: float = PEN_RADIUS_PX,
        min_region_area: float = MIN_REGION_AREA_PX2,
        min_lane_px: float = 4.0,
        ink_radius: float = 0.75,
        sliver_area: float = 0.5,
        fail_on_isolated_loops: bool = False,
        check_tiny_regions: bool = True,
        max_region_px2: Optional[float] = None,
    ):
        self.snap_tolerance = snap_tolerance
        self.whisker_tolerance = whisker_tolerance
        self.pen_radius = pen_radius
        self.min_region_area = min_region_area
        self.min_lane_px = min_lane_px
        self.ink_radius = ink_radius
        self.sliver_area = sliver_area
        self.fail_on_isolated_loops = fail_on_isolated_loops
        self.check_tiny_regions = check_tiny_regions
        self.max_region_px2 = max_region_px2

    # ------------------------------------------------------------------ API

    def analyze(
        self,
        polylines: Sequence[Sequence[Coord]],
        exempt_dangle_fn=None,
        center: Optional[Coord] = None,
        divisions: Optional[int] = None,
        base_mask: Optional[Sequence[bool]] = None,
        overflow_parts: Optional[Sequence[Tuple[int, LineString]]] = None,
        ring_ids: Optional[Sequence[int]] = None,
    ) -> TopologyReport:
        """
        Args:
            polylines: linework as sequences of (x, y) coordinates.
            center: mandala centre. When given, the report also lists radii
                where a full circle crosses no ink - a corridor running all the
                way around the design.
            base_mask: optional per-polyline flags marking base motif linework.
                Base polylines outside the largest connected base group are
                reported as floating base motifs.
            overflow_parts / ring_ids: optional (ring, LineString) overflow
                segments and the ring id of every input polyline. An overflow
                segment may not cross ink belonging to any other ring.
            exempt_dangle_fn: optional (x, y) -> bool. Dangling endpoints for
                which this returns True are treated as connected to context
                outside the analyzed linework (e.g. ring boundaries when
                validating a single ring in isolation).
        """
        lines = self._build_lines(polylines)
        if not lines:
            return TopologyReport(
                is_valid=False,
                issues=["No valid linework to analyze"],
                unconnected_shapes=[],
                tiny_regions=[],
                stats={'num_floating_base': 0, 'num_overflow_crossings': 0,
                       'num_oversized_regions': 0, 'largest_region_in2': 0.0},
            )

        # unary_union nodes the arrangement: every crossing (including
        # self-intersections) becomes a shared vertex between edge pieces.
        # Snap-rounding to a 0.001px grid (invisible at page scale) makes
        # near-coincident coordinates exact so micro-gaps cannot survive.
        noded = _shapely.set_precision(unary_union(lines), 0.001)
        edges = self._as_line_list(noded)

        edges, num_whiskers = self._prune_whiskers(edges)
        edges, num_bridges = self._close_gaps(edges)
        if num_bridges:
            # bridges create new touch points that must be noded; snap-rounding
            # is required again or exact predicates may refuse the T-junction
            # (bridge foot within float epsilon of the target line)
            edges = self._as_line_list(_shapely.set_precision(unary_union(edges), 0.001))
            edges, more_whiskers = self._prune_whiskers(edges)
            num_whiskers += more_whiskers

        degree = self._node_degrees(edges)
        all_dangle_points = [key for key, deg in degree.items() if deg == 1]
        if exempt_dangle_fn is not None:
            dangle_points = [p for p in all_dangle_points if not exempt_dangle_fn(p[0], p[1])]
        else:
            dangle_points = all_dangle_points

        components = self._connected_components(edges, degree)
        polygons, cuts, dangles, invalids = polygonize_full(edges)
        regions = self._resolve_faces(list(polygons.geoms)) if self.check_tiny_regions else []

        issues: List[str] = []
        unconnected: List[ShPoint] = []
        tiny: List[Tuple[Polygon, ShPoint]] = []

        for (x, y) in dangle_points:
            issues.append(f"Dangling line end at ({x:.1f}, {y:.1f}) - connects to nothing")
            unconnected.append(ShPoint(x, y))

        def component_is_anchored(comp: ComponentInfo) -> bool:
            """Open component whose every dangling end is exempt - it is
            anchored to context outside the analyzed linework."""
            if exempt_dangle_fn is None:
                return False
            for i in comp.edge_indices:
                for key in (self._node_key(edges[i].coords[0]),
                            self._node_key(edges[i].coords[-1])):
                    if degree.get(key, 0) == 1 and not exempt_dangle_fn(key[0], key[1]):
                        return False
            return True

        floating = [
            c for c in components
            if not c.is_main and not c.is_closed and not component_is_anchored(c)
        ]
        loops = [c for c in components if not c.is_main and c.is_closed]

        for comp in floating:
            x0, y0, x1, y1 = comp.bounds
            issues.append(
                f"Floating open shape near ({(x0 + x1) / 2:.1f}, {(y0 + y1) / 2:.1f}) "
                f"- not connected to any other lines"
            )
        if self.fail_on_isolated_loops:
            for comp in loops:
                x0, y0, x1, y1 = comp.bounds
                issues.append(
                    f"Isolated closed loop near ({(x0 + x1) / 2:.1f}, {(y0 + y1) / 2:.1f})"
                )

        for region in regions:
            if region.is_tiny:
                x, y = region.label_point
                issues.append(
                    f"Un-colorable region at ({x:.1f}, {y:.1f}) - area {region.area:.1f}px² "
                    f"below minimum {self.min_region_area:.0f}px²"
                )
                tiny.append((region.polygon, ShPoint(x, y)))
            elif region.is_too_thin:
                x, y = region.label_point
                issues.append(
                    f"Un-colorable region at ({x:.1f}, {y:.1f}) - too thin to fit a "
                    f"{self.pen_radius:.1f}px pen tip anywhere"
                )
                tiny.append((region.polygon, ShPoint(x, y)))

        floating_base = self._floating_base(polylines, base_mask)
        for x, y in floating_base:
            issues.append(f"Floating base motif near ({x:.1f}, {y:.1f})")
        crossings = self._overflow_crossings(polylines, overflow_parts, ring_ids)
        for other_ring, (x, y) in crossings:
            issues.append(f"Overflow crosses ring {other_ring} near ({x:.1f}, {y:.1f})")

        bare = (
            self._bare_bands(lines, center, divisions)
            if center is not None and divisions else []
        )
        # Reported, not failed. A band whose only ink is radial spokes looks
        # sparse, but for a fan of rays or the safe-spoke fallback that IS the
        # pattern, and those produce perfectly colourable sectors. It is a
        # density signal for tuning patterns, not a correctness rule.

        lanes = self._free_lanes(lines, center) if center is not None else []
        encircling = self._encircling_regions(regions, center) if center is not None else []
        for region in encircling:
            x, y = region.label_point
            issues.append(
                f"Region at ({x:.0f}, {y:.0f}) of {region.area:.0f}px2 encircles the centre "
                "- it is one space a colourist can follow the whole way around the design"
            )
        for low, high in lanes:
            issues.append(
                f"Un-crossed lane from radius {low:.0f} to {high:.0f} "
                f"({high - low:.0f}px wide) - a circle drawn there never crosses a line, "
                "so that space runs all the way around the design"
            )

        # Reported, not failed: an oversized face never changes validity.
        oversized = (
            [r for r in regions if r.area > self.max_region_px2]
            if self.max_region_px2 is not None else []
        )

        report = TopologyReport(
            is_valid=len(issues) == 0,
            issues=issues,
            unconnected_shapes=unconnected,
            tiny_regions=tiny,
            free_lanes=lanes,
            encircling_regions=encircling,
            oversized_regions=oversized,
            dangle_points=list(dangle_points),
            dangle_lines=self._as_line_list(dangles),
            floating_components=floating,
            isolated_loops=loops,
            regions=regions,
            stats={
                'num_input_lines': len(lines),
                'num_noded_edges': len(edges),
                'num_components': len(components),
                'num_regions': len(regions),
                'num_dangles': len(dangle_points),
                'num_floating_open': len(floating),
                'num_isolated_loops': len(loops),
                'num_cut_edges': len(self._as_line_list(cuts)),
                'num_whiskers_pruned': num_whiskers,
                'num_gaps_bridged': num_bridges,
                'num_uncolorable_regions': sum(1 for r in regions if r.is_uncolorable),
                'num_free_lanes': len(lanes),
                'num_bare_bands': len(bare),
                'num_encircling_regions': len(encircling),
                'num_oversized_regions': len(oversized),
                'largest_region_in2': round(
                    max((r.area for r in regions), default=0.0) / (PX_PER_INCH * PX_PER_INCH), 3
                ),
                'num_floating_base': len(floating_base),
                'num_overflow_crossings': len(crossings),
                'widest_lane_px': round(max((h - l for l, h in lanes), default=0.0), 1),
            },
        )
        return report

    def faces(self, polylines: Sequence[Sequence[Coord]]) -> List[RegionInfo]:
        """
        The faces `polylines` enclose, noded and judged exactly as `analyze`
        judges them, without its whisker and gap repair (which only changes
        faces at dangling ends). Lets the engine test a stroke before adding it.
        """
        lines = self._build_lines(polylines)
        if not lines:
            return []
        edges = self._as_line_list(_shapely.set_precision(unary_union(lines), 0.001))
        polygons = polygonize_full(edges)[0]
        return self._resolve_faces(list(polygons.geoms))

    @staticmethod
    def _floating_base(polylines, base_mask) -> List[Coord]:
        """Centres of base polylines outside the largest connected base group."""
        if base_mask is None:
            return []
        ids = structural_components(polylines)
        base = [i for i in range(len(ids)) if i < len(base_mask) and base_mask[i]]
        if not base:
            return []
        counts: Dict[int, int] = {}
        for i in base:
            counts[ids[i]] = counts.get(ids[i], 0) + 1
        structure = min(counts, key=lambda c: (-counts[c], c))
        found = []
        for i in base:
            if ids[i] == structure:
                continue
            x0, y0, x1, y1 = LineString(polylines[i]).bounds
            found.append(((x0 + x1) / 2, (y0 + y1) / 2))
        return found

    @staticmethod
    def _overflow_crossings(polylines, overflow_parts, ring_ids) -> List[Tuple[int, Coord]]:
        """
        (other_ring, point) for each overflow line crossing another ring's ink, part by part and, within a
        part, in polyline order. One tree holds every polyline of two or more distinct points; each part's
        query keeps the hits on other rings' ink.
        """
        if overflow_parts is None or ring_ids is None:
            return []
        lines = [
            (i, LineString(pts)) for i, pts in enumerate(polylines)
            if len(set(map(tuple, pts))) >= 2
        ]
        if not lines:
            return []
        tree = STRtree([g for _, g in lines])
        found = []
        for ring, line in overflow_parts:
            ends = [ShPoint(line.coords[0]), ShPoint(line.coords[-1])]
            # Tree indices follow polyline order, so sorting them keeps the polyline order.
            for k in sorted(tree.query(line, predicate='intersects')):
                other_index, other = lines[int(k)]
                if ring_ids[other_index] == ring:
                    continue
                hit = line.intersection(other)
                if hit.is_empty:
                    continue
                parts = list(hit.geoms) if hasattr(hit, 'geoms') else [hit]
                # A point at either end of the overflow line is allowed, and so is a touch:
                # a point that is a vertex of both the overflow line and the other polyline.
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

    def _encircling_regions(self, regions, center) -> List["RegionInfo"]:
        """
        Faces you can travel all the way around the centre inside.

        A face contains a loop around the centre exactly when the centre sits
        inside the face's outer ring but not inside the face itself - i.e. the
        centre is in one of its holes. Unlike the radial-lane scan this also
        catches a corridor that WANDERS: it need not stay at one radius, so long
        as it closes on itself around the middle.
        """
        origin = ShPoint(center)
        found = []
        for region in regions:
            polygon = region.polygon
            if not polygon.interiors:
                continue
            try:
                if Polygon(polygon.exterior).contains(origin) and not polygon.contains(origin):
                    found.append(region)
            except Exception:
                continue
        return found

    def _bare_bands(self, lines, center, divisions) -> List[Tuple[float, float]]:
        """
        Radial bands whose only ink is the radial spokes.

        A spoke crossing a band stops it being a free corridor, but a wide band
        with nothing else in it still prints as one empty ring: there is nothing
        to colour and the eye follows it straight around. A band of width w
        crossed by n spokes holds about n*w of line, so anything close to that
        floor is bare.
        """
        cx, cy = center
        step = max(4.0, self.min_lane_px)
        segments = []
        for line in lines:
            coords = list(line.coords)
            for i in range(len(coords) - 1):
                a, b = coords[i], coords[i + 1]
                ra = math.hypot(a[0] - cx, a[1] - cy)
                rb = math.hypot(b[0] - cx, b[1] - cy)
                segments.append((min(ra, rb), max(ra, rb), math.dist(a, b)))
        if not segments:
            return []

        low_r = min(s[0] for s in segments)
        high_r = max(s[1] for s in segments)
        bands = []
        radius = low_r
        while radius < high_r:
            top = min(radius + step, high_r)
            ink = 0.0
            for s0, s1, length in segments:
                overlap = max(0.0, min(top, s1) - max(radius, s0))
                if overlap <= 0:
                    continue
                ink += length * (overlap / (s1 - s0)) if s1 > s0 else length
            width = top - radius
            # a purely radial fill would be divisions * width; allow 60% headroom
            bands.append((radius, top, ink <= divisions * width * 1.6))
            radius = top

        runs = []
        current = None
        for lo, hi, is_bare in bands:
            if is_bare:
                current = (lo, hi) if current is None else (current[0], hi)
            elif current is not None:
                runs.append(current)
                current = None
        if current is not None:
            runs.append(current)
        # only a band thick enough to notice counts
        return [r for r in runs if r[1] - r[0] >= 14.0]

    def _free_lanes(self, lines, center) -> List[Tuple[float, float]]:
        """
        Radial gaps in the ink, i.e. corridors running right around the design.

        A circle of radius r crosses a curve exactly when r lies between the
        curve's nearest and farthest distance from the centre, so the radii that
        ARE crossed are the union of each segment's [min, max] distance range.
        Whatever is left over inside the design's radial extent is a lane. That
        is exact and needs no sampling.
        """
        cx, cy = center
        spans: List[Tuple[float, float]] = []
        origin = ShPoint(cx, cy)
        for line in lines:
            coords = list(line.coords)
            for index in range(len(coords) - 1):
                segment = LineString([coords[index], coords[index + 1]])
                near = segment.distance(origin)
                far = max(
                    math.hypot(coords[index][0] - cx, coords[index][1] - cy),
                    math.hypot(coords[index + 1][0] - cx, coords[index + 1][1] - cy),
                )
                if far > near:
                    spans.append((near, far))
        if not spans:
            return []

        spans.sort()
        merged: List[List[float]] = [list(spans[0])]
        for low, high in spans[1:]:
            if low <= merged[-1][1] + 1e-9:
                merged[-1][1] = max(merged[-1][1], high)
            else:
                merged.append([low, high])

        lanes = []
        for index in range(len(merged) - 1):
            gap_low = merged[index][1]
            gap_high = merged[index + 1][0]
            if gap_high - gap_low >= self.min_lane_px:
                lanes.append((gap_low, gap_high))
        return lanes

    # ------------------------------------------------------- construction

    def _build_lines(self, polylines: Sequence[Sequence[Coord]]) -> List[LineString]:
        lines = []
        for pts in polylines:
            cleaned: List[Coord] = []
            for (x, y) in pts:
                if cleaned and abs(cleaned[-1][0] - x) < 1e-9 and abs(cleaned[-1][1] - y) < 1e-9:
                    continue
                cleaned.append((float(x), float(y)))
            if len(cleaned) < 2:
                continue
            # Force-close near-closed rings: a ring open by float noise (e.g.
            # sin(2*pi) != 0) makes GEOS discard the whole ring as a dangle.
            dx = cleaned[0][0] - cleaned[-1][0]
            dy = cleaned[0][1] - cleaned[-1][1]
            if 0 < math.hypot(dx, dy) < 1e-6:
                cleaned[-1] = cleaned[0]
            line = LineString(cleaned)
            if line.length > 1e-9:
                lines.append(line)
        return lines

    def _prune_whiskers(self, edges: List[LineString]) -> Tuple[List[LineString], int]:
        """
        Iteratively remove dangling edges shorter than whisker_tolerance -
        the stubs left when a line intentionally overshoots a junction.
        """
        if self.whisker_tolerance <= 0:
            return edges, 0

        removed = 0
        for _ in range(20):
            degree = self._node_degrees(edges)
            keep: List[LineString] = []
            changed = False
            for edge in edges:
                start = self._node_key(edge.coords[0])
                end = self._node_key(edge.coords[-1])
                start_degree = degree.get(start, 0)
                end_degree = degree.get(end, 0)
                # Only an overshoot PAST A JUNCTION may be pruned. Requiring the
                # attached end to be a real junction (degree >= 3) is what stops
                # the pass from nibbling a genuine dangling line away one short
                # segment at a time: densification makes segments tiny near the
                # centre, so without this a 40px loose end could vanish from the
                # analysis while still being drawn on the page.
                anchor_degree = (
                    end_degree if start_degree == 1
                    else start_degree if end_degree == 1
                    else 0
                )
                is_short_dangle = (
                    start != end
                    and edge.length <= self.whisker_tolerance
                    and (start_degree == 1 or end_degree == 1)
                    and anchor_degree >= 3
                )
                if is_short_dangle:
                    changed = True
                    removed += 1
                else:
                    keep.append(edge)
            edges = keep
            if not changed:
                break
        return edges, removed

    def _close_gaps(self, edges: List[LineString]) -> Tuple[List[LineString], int]:
        """
        For each remaining dangling endpoint within snap_tolerance of other
        linework, add a short bridge segment onto the nearest edge. Gaps
        smaller than a stroke width render as connected, so they are treated
        as intended junctions rather than defects.
        """
        if self.snap_tolerance <= 0 or not edges:
            return edges, 0

        degree = self._node_degrees(edges)
        tree = STRtree(edges)
        bridges: List[LineString] = []

        for idx, edge in enumerate(edges):
            coords = edge.coords
            for end in (0, -1):
                key = self._node_key(coords[end])
                if degree.get(key, 0) != 1:
                    continue
                endpoint = ShPoint(coords[end])
                best_dist = self.snap_tolerance
                best_proj: Optional[Coord] = None
                for cand_idx in tree.query(endpoint.buffer(self.snap_tolerance)):
                    if cand_idx == idx:
                        continue
                    other = edges[cand_idx]
                    dist = other.distance(endpoint)
                    if dist <= best_dist and dist > 1e-9:
                        proj = other.interpolate(other.project(endpoint))
                        best_dist = dist
                        best_proj = (proj.x, proj.y)
                if best_proj is not None:
                    # Overshoot slightly past the target so the bridge truly
                    # CROSSES it - a bridge ending exactly on the line may sit
                    # a float epsilon off it, and exact predicates then refuse
                    # to node the T-junction. The tiny stub past the crossing
                    # is removed by the whisker prune that follows.
                    tip = coords[end]
                    ux = (best_proj[0] - tip[0]) / best_dist
                    uy = (best_proj[1] - tip[1]) / best_dist
                    over = (best_proj[0] + ux * 0.05, best_proj[1] + uy * 0.05)
                    bridges.append(LineString([tip, over]))

        return edges + bridges, len(bridges)

    # ------------------------------------------------------------- graph

    @staticmethod
    def _as_line_list(geom) -> List[LineString]:
        if geom is None or geom.is_empty:
            return []
        if isinstance(geom, LineString):
            return [geom]
        return [g for g in getattr(geom, 'geoms', []) if isinstance(g, LineString)]

    @staticmethod
    def _node_key(coord: Coord) -> Coord:
        return (round(coord[0], _NODE_DECIMALS), round(coord[1], _NODE_DECIMALS))

    def _node_degrees(self, edges: List[LineString]) -> Dict[Coord, int]:
        """
        Degree of each node in the noded arrangement. A closed edge piece
        (ring) contributes degree 2 to its anchor node so an isolated circle
        does not read as dangling.
        """
        degree: Dict[Coord, int] = {}
        for edge in edges:
            coords = edge.coords
            start = self._node_key(coords[0])
            end = self._node_key(coords[-1])
            if start == end:
                degree[start] = degree.get(start, 0) + 2
            else:
                degree[start] = degree.get(start, 0) + 1
                degree[end] = degree.get(end, 0) + 1
        return degree

    def _connected_components(
        self,
        edges: List[LineString],
        degree: Dict[Coord, int],
    ) -> List[ComponentInfo]:
        parent = list(range(len(edges)))

        def find(a: int) -> int:
            while parent[a] != a:
                parent[a] = parent[parent[a]]
                a = parent[a]
            return a

        def union(a: int, b: int):
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[rb] = ra

        node_to_edge: Dict[Coord, int] = {}
        for idx, edge in enumerate(edges):
            for key in (self._node_key(edge.coords[0]), self._node_key(edge.coords[-1])):
                if key in node_to_edge:
                    union(idx, node_to_edge[key])
                else:
                    node_to_edge[key] = idx

        groups: Dict[int, List[int]] = {}
        for idx in range(len(edges)):
            groups.setdefault(find(idx), []).append(idx)

        components: List[ComponentInfo] = []
        for edge_indices in groups.values():
            total_length = sum(edges[i].length for i in edge_indices)
            xs0, ys0, xs1, ys1 = [], [], [], []
            has_dangle = False
            for i in edge_indices:
                b = edges[i].bounds
                xs0.append(b[0]); ys0.append(b[1]); xs1.append(b[2]); ys1.append(b[3])
                for key in (self._node_key(edges[i].coords[0]), self._node_key(edges[i].coords[-1])):
                    if degree.get(key, 0) == 1:
                        has_dangle = True
            components.append(ComponentInfo(
                edge_indices=edge_indices,
                total_length=total_length,
                bounds=(min(xs0), min(ys0), max(xs1), max(ys1)),
                is_closed=not has_dangle,
                is_main=False,
            ))

        if components:
            main = max(components, key=lambda c: c.total_length)
            main.is_main = True
        return components

    # ------------------------------------------------------------ regions

    def _resolve_faces(self, polygons: List[Polygon]) -> List[RegionInfo]:
        """
        polygonize returns maximal ring polygons: a face containing a nested
        loop comes back as the full disk, overlapping the inner one. Subtract
        directly-contained polygons to recover true faces (e.g. the annulus
        between concentric circles).
        """
        if not polygons:
            return []
        polygons = _valid_faces(polygons)

        order = sorted(range(len(polygons)), key=lambda i: polygons[i].area)
        tree = STRtree([polygons[i] for i in order])

        faces: List[RegionInfo] = []
        for rank, poly_idx in enumerate(order):
            poly = polygons[poly_idx]
            inner: List[Polygon] = []
            for cand_rank in tree.query(poly, predicate='contains'):
                if cand_rank < rank:  # strictly smaller area -> nested inside
                    inner.append(polygons[order[cand_rank]])
            face = poly
            if inner:
                face = poly.difference(unary_union(inner))
            if face.is_empty:
                continue

            # difference may split into pieces; evaluate each piece as a face
            pieces = [face] if isinstance(face, Polygon) else [
                g for g in getattr(face, 'geoms', []) if isinstance(g, Polygon)
            ]
            for piece in pieces:
                area = piece.area
                if area < self.sliver_area:
                    continue
                # Erode the same coordinates in floating precision: a face noded on the
                # 0.001px grid carries that grid, and GEOS can collapse a negative buffer
                # on gridded input to empty even where a pen fits with room to spare.
                exact = _shapely.set_precision(piece, 0.0)
                if exact.buffer(-self.ink_radius).is_empty:
                    # entirely covered by stroke ink - not a visible region
                    continue
                is_tiny = area < self.min_region_area
                is_too_thin = (not is_tiny) and exact.buffer(-self.pen_radius).is_empty
                label = piece.representative_point()
                faces.append(RegionInfo(
                    polygon=piece,
                    area=area,
                    is_tiny=is_tiny,
                    is_too_thin=is_too_thin,
                    label_point=(label.x, label.y),
                ))
        return faces


# ---------------------------------------------------------------- adapters

def _valid_faces(polygons: Sequence[Polygon]) -> List[Polygon]:
    """
    The faces with any invalid one repaired. Snap-rounded linework can still
    polygonize into a self-intersecting face, which the containment and
    difference steps cannot measure (GEOS raises a side location conflict).
    `make_valid` repairs it; every polygon part it yields is kept, largest
    first, so no face is lost. Valid faces pass through unchanged.
    """
    found: List[Polygon] = []
    for polygon in polygons:
        if polygon.is_valid:
            found.append(polygon)
            continue
        parts: List[Polygon] = []
        pending = [_shapely.make_valid(polygon)]
        while pending:
            geometry = pending.pop()
            if isinstance(geometry, Polygon):
                if not geometry.is_empty:
                    parts.append(geometry)
            elif hasattr(geometry, 'geoms'):
                pending.extend(geometry.geoms)
        found.extend(sorted(parts, key=lambda part: -part.area))
    return found


def _near_vertex(point: ShPoint, coords, tolerance: float = 1e-6) -> bool:
    return any(math.hypot(point.x - x, point.y - y) <= tolerance for x, y in coords)


def structural_components(
    polylines: Sequence[Sequence[Coord]], touch_tolerance: float = 0.01
) -> List[int]:
    """
    Component id per input polyline, before any noding. Two polylines share a
    component when they lie within touch_tolerance of each other. Ids are
    assigned in first-seen order, so the result is deterministic. A polyline
    with fewer than two distinct points forms its own singleton component.
    """
    count = len(polylines)
    parent = list(range(count))

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    geoms: List[LineString] = []
    owners: List[int] = []
    for i, pts in enumerate(polylines):
        if len(set((float(x), float(y)) for x, y in pts)) >= 2:
            geoms.append(LineString(pts))
            owners.append(i)

    if geoms:
        tree = STRtree(geoms)
        left, right = tree.query(geoms, predicate='dwithin', distance=touch_tolerance)
        for a, b in zip(left.tolist(), right.tolist()):
            ra, rb = find(owners[a]), find(owners[b])
            if ra != rb:
                parent[max(ra, rb)] = min(ra, rb)

    ids: Dict[int, int] = {}
    return [ids.setdefault(find(i), len(ids)) for i in range(count)]


def debug_overlay_svg(
    report: TopologyReport,
    polylines: Sequence[Sequence[Coord]],
    size: Tuple[float, float] = (612, 612),
    seed: int = 0,
    *,
    reach_lines: Sequence[Sequence[Coord]] = (),
    floating_base_boxes: Sequence[Tuple[float, float, float, float]] = (),
) -> str:
    """
    Render a visual QA overlay:
      - every detected region filled with a random pastel (the "coloring test")
      - un-colorable regions filled solid red
      - original linework in dark gray
      - dangling endpoints as red circles with crosshairs
      - floating open shapes outlined with a dashed red box
      - reach lines (connectors between motifs) traced 1px in green
      - floating base motifs (floating_base_boxes) boxed in dashed red
    """
    rng = random.Random(seed)
    width, height = size
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">',
        f'<rect width="{width}" height="{height}" fill="white"/>',
    ]

    def poly_to_path(poly: Polygon) -> str:
        def ring_d(coords):
            return 'M ' + ' L '.join(f'{x:.2f} {y:.2f}' for x, y in coords) + ' Z'
        d = ring_d(poly.exterior.coords)
        for interior in poly.interiors:
            d += ' ' + ring_d(interior.coords)
        return d

    encircling = {id(r) for r in report.encircling_regions}
    for region in report.regions:
        if id(region) in encircling:
            fill = '#fb8c00'          # corridor: colourable right around the design
        elif region.is_uncolorable:
            fill = '#e53935'
        else:
            hue = rng.randint(0, 359)
            fill = f'hsl({hue}, 70%, 85%)'
        parts.append(
            f'<path d="{poly_to_path(region.polygon)}" fill="{fill}" '
            f'fill-rule="evenodd" stroke="none"/>'
        )

    for pts in polylines:
        d = 'M ' + ' L '.join(f'{x:.2f} {y:.2f}' for x, y in pts)
        parts.append(f'<path d="{d}" fill="none" stroke="#333" stroke-width="1"/>')

    for pts in reach_lines:
        d = 'M ' + ' L '.join(f'{x:.2f} {y:.2f}' for x, y in pts)
        parts.append(f'<path d="{d}" fill="none" stroke="#0a7" stroke-width="1"/>')

    for x0, y0, x1, y1 in floating_base_boxes:
        parts.append(
            f'<rect x="{x0 - 4:.1f}" y="{y0 - 4:.1f}" width="{x1 - x0 + 8:.1f}" '
            f'height="{y1 - y0 + 8:.1f}" fill="none" stroke="red" stroke-dasharray="4,2"/>'
        )

    for comp in report.floating_components:
        x0, y0, x1, y1 = comp.bounds
        parts.append(
            f'<rect x="{x0 - 4:.1f}" y="{y0 - 4:.1f}" width="{x1 - x0 + 8:.1f}" '
            f'height="{y1 - y0 + 8:.1f}" fill="none" stroke="#e53935" '
            f'stroke-width="1.5" stroke-dasharray="5,3"/>'
        )

    for low, high in report.free_lanes:
        mid = (low + high) / 2.0
        parts.append(
            f'<circle cx="{width / 2:.1f}" cy="{height / 2:.1f}" r="{mid:.1f}" '
            f'fill="none" stroke="#fb8c00" stroke-width="{max(1.0, high - low):.1f}" '
            f'stroke-opacity="0.45" stroke-dasharray="10,6"/>'
        )

    for (x, y) in report.dangle_points:
        parts.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="6" fill="none" '
            f'stroke="#e53935" stroke-width="1.5"/>'
        )
        parts.append(
            f'<path d="M {x - 9:.1f} {y:.1f} H {x + 9:.1f} M {x:.1f} {y - 9:.1f} '
            f'V {y + 9:.1f}" stroke="#e53935" stroke-width="1"/>'
        )

    parts.append('</svg>')
    return '\n'.join(parts)
