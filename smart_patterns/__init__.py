"""
Smart pattern registry.

This package exposes the same public functions that the old `smart_patterns.py`
module exposed, while storing category-specific generators in separate files.
"""

from typing import Any, Callable, Dict, List

from .abstract import ABSTRACT_SMART_PATTERNS
from .art_deco import ART_DECO_SMART_PATTERNS
from .botanical import BOTANICAL_SMART_PATTERNS
from .celtic import CELTIC_SMART_PATTERNS
from .fallback import get_safe_fallback_pattern
from .geometric import GEOMETRIC_SMART_PATTERNS


PatternFunc = Callable[..., List[Dict[str, Any]]]


SMART_PATTERNS: List[Dict[str, Any]] = []
SMART_PATTERNS.extend(BOTANICAL_SMART_PATTERNS)
SMART_PATTERNS.extend(GEOMETRIC_SMART_PATTERNS)
SMART_PATTERNS.extend(CELTIC_SMART_PATTERNS)
SMART_PATTERNS.extend(ART_DECO_SMART_PATTERNS)
SMART_PATTERNS.extend(ABSTRACT_SMART_PATTERNS)


def get_smart_patterns_for_categories(categories: List[str]) -> List[Dict[str, Any]]:
    selected = {category.lower() for category in categories}
    return [pattern for pattern in SMART_PATTERNS if pattern["category"] in selected]
