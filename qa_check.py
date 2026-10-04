"""
Standalone topology QA for any SVG coloring page.

Flattens the SVG (transforms, <use>, arcs, beziers all resolved via
svgelements), runs topology_validator, prints a report, and optionally writes
a visual overlay where every colorable region is filled with a random pastel
and defects are marked in red.

Usage:
    python qa_check.py design.svg
    python qa_check.py design.svg --overlay qa.svg
    python qa_check.py generated_designs\\*.svg
    python qa_check.py design.svg --snap 2.5 --pen 2.0 --min-area 20
"""

import argparse
import glob
import sys

from svgelements import SVG, Path, Shape, Line, Close

from topology_validator import TopologyValidator, debug_overlay_svg


def svg_to_polylines(path: str, curve_segments: int = 16):
    """Flatten an SVG file into polylines in root coordinates."""
    svg = SVG.parse(path, reify=True)
    polylines = []

    for element in svg.elements():
        if not isinstance(element, Shape):
            continue
        try:
            shape_path = Path(element)
        except (TypeError, ValueError):
            continue
        if len(shape_path) == 0:
            continue

        current = []
        for segment in shape_path.segments():
            seg_name = segment.__class__.__name__
            if seg_name == 'Move':
                if len(current) >= 2:
                    polylines.append(current)
                current = [(segment.end.x, segment.end.y)] if segment.end else []
                continue
            if segment.start is None or segment.end is None:
                continue
            if not current:
                current = [(segment.start.x, segment.start.y)]
            if isinstance(segment, (Line, Close)):
                current.append((segment.end.x, segment.end.y))
            else:
                # curve: sample by parameter
                for i in range(1, curve_segments + 1):
                    pt = segment.point(i / curve_segments)
                    current.append((pt.x, pt.y))
        if len(current) >= 2:
            polylines.append(current)

    width = float(svg.width) if svg.width else 612.0
    height = float(svg.height) if svg.height else 612.0
    return polylines, (width, height)


def main():
    parser = argparse.ArgumentParser(description="Topology QA for SVG coloring pages")
    parser.add_argument('files', nargs='+', help="SVG file(s), globs allowed")
    parser.add_argument('--overlay', help="write visual QA overlay SVG (single input only)")
    parser.add_argument('--snap', type=float, default=2.5, help="gap tolerance px")
    parser.add_argument('--whisker', type=float, default=5.0, help="overshoot stub tolerance px")
    parser.add_argument('--pen', type=float, default=2.0, help="pen tip radius px")
    parser.add_argument('--min-area', type=float, default=20.0, help="min colorable region px^2")
    parser.add_argument('--ink', type=float, default=0.75, help="half stroke width px")
    parser.add_argument('--max-issues', type=int, default=15, help="issues to print per file")
    args = parser.parse_args()

    files = []
    for pattern in args.files:
        matched = glob.glob(pattern)
        files.extend(matched if matched else [pattern])

    validator = TopologyValidator(
        snap_tolerance=args.snap,
        whisker_tolerance=args.whisker,
        pen_radius=args.pen,
        min_region_area=args.min_area,
        ink_radius=args.ink,
    )

    any_failed = False
    for file_path in files:
        polylines, size = svg_to_polylines(file_path)
        report = validator.analyze(polylines)
        s = report.stats

        status = "PASS" if report.is_valid else "FAIL"
        print(f"\n[{status}] {file_path}")
        print(f"  {s.get('num_regions', 0)} colorable regions, "
              f"{s.get('num_components', 0)} linework components, "
              f"{s.get('num_isolated_loops', 0)} isolated loops (allowed)")
        print(f"  {s.get('num_whiskers_pruned', 0)} overshoot whiskers pruned, "
              f"{s.get('num_gaps_bridged', 0)} sub-stroke gaps bridged")
        if not report.is_valid:
            any_failed = True
            print(f"  {s.get('num_dangles', 0)} dangling ends, "
                  f"{s.get('num_floating_open', 0)} floating shapes, "
                  f"{s.get('num_uncolorable_regions', 0)} un-colorable regions:")
            for issue in report.issues[:args.max_issues]:
                print(f"    - {issue}")
            if len(report.issues) > args.max_issues:
                print(f"    ... and {len(report.issues) - args.max_issues} more")

        if args.overlay and len(files) == 1:
            overlay = debug_overlay_svg(report, polylines, size=size)
            with open(args.overlay, 'w', encoding='utf-8') as f:
                f.write(overlay)
            print(f"  Overlay written to {args.overlay}")

    sys.exit(1 if any_failed else 0)


if __name__ == '__main__':
    main()
