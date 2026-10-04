import random
import pytest

@pytest.fixture
def cell_kwargs():
    # ring depth 60px, 30-degree wedge, cell ~68px wide at mid radius
    return dict(inner_radius=100.0, outer_radius=160.0, wedge_angle=30.0,
                center=(306.0, 306.0), stroke_width=1.5, complexity=0.5,
                min_white_space=10.0, rng=random.Random(7))
