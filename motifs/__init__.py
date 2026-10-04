"""Motif registry: every motif the engine can place, in category order."""

from __future__ import annotations

from typing import Dict, List, Optional

from motifs.botanical import BOTANICAL_MOTIFS
from motifs.fallback import safe_motif
from motifs.geometric import GEOMETRIC_MOTIFS

MOTIFS: List[Dict] = [*BOTANICAL_MOTIFS, *GEOMETRIC_MOTIFS]


def motifs_for_categories(categories: List[str]) -> List[Dict]:
    return [entry for entry in MOTIFS if entry["category"] in categories]


def find_motif(name: str) -> Optional[Dict]:
    return next((entry for entry in MOTIFS if entry["name"] == name), None)


__all__ = ["MOTIFS", "motifs_for_categories", "find_motif", "safe_motif"]
