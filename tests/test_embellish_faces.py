"""Regression: an embellishment's face check must see every face the validator sees, in any frame."""
import random

import shapely
from shapely.geometry import LineString
from shapely.ops import polygonize, unary_union

from motifs import find_motif
from motifs.embellish import MIN_REGION_AREA_PX2, _face_holds_pen
from motifs.geometry import MotifContext, cell_rotation_deg

# Ring 2, cell 3 of the smoke case div24-24-24_B24_c0.9_mws10_layered_base_back-petal (seed 20260821): a spike
# with echo and fan whose two outer fan wedges were 19.8px2. In the cell's own frame snap-rounding turned them
# into invalid rings that `polygonize` dropped, so the fan's check passed; on the page the validator found them.
SPIKE_CELL = dict(
    inner_radius=177.93756007630557, outer_radius=286.0, wedge_angle=15.0, center=(306.0, 306.0),
    stroke_width=1.8250000000000002, complexity=0.9, min_white_space=10, position="centre",
    angular_limits=1.0, radial_limits=(-0.0, 1.2), side_touch_radial=0.19771129288467298,
    ring_stream_seed=628088869873424, node_seed=20260881802477, embellishments=("echo", "fan"),
)


def _faces(context, vectors, rotation_deg):
    lines = [LineString(context.polyline(vector, rotation_deg)) for vector in vectors]
    return list(polygonize(unary_union(lines)))


def test_fan_never_leaves_a_face_below_the_pen_floor_in_any_frame():
    context = MotifContext(**SPIKE_CELL, rng=random.Random(SPIKE_CELL["node_seed"]))
    instance = find_motif("spike")["generator"](context)
    for rotation in (0.0, cell_rotation_deg(3, 24, "centre")):
        faces = _faces(context, instance.vectors, rotation)
        assert faces and all(_face_holds_pen(face) for face in faces), (
            rotation, sorted(round(face.area, 2) for face in faces if face.area < MIN_REGION_AREA_PX2))
