"""Motif registry: every motif the engine can place, in category order."""

from __future__ import annotations

from typing import Dict, List, Optional

from motifs.botanical import BOTANICAL_MOTIFS
from motifs.fallback import safe_motif
from motifs.fillers import FILLER_MOTIFS
from motifs.geometric import GEOMETRIC_MOTIFS
from motifs.trims import TRIM_MOTIFS

MOTIFS: List[Dict] = [*BOTANICAL_MOTIFS, *GEOMETRIC_MOTIFS, *FILLER_MOTIFS, *TRIM_MOTIFS]

# Retired names that still resolve, so older plans and requests keep working.
MOTIF_ALIASES: Dict[str, str] = {"ring_band": "band"}


def motifs_for_categories(categories: List[str]) -> List[Dict]:
    return [entry for entry in MOTIFS if entry["category"] in categories]


def find_motif(name: str) -> Optional[Dict]:
    name = MOTIF_ALIASES.get(name, name)
    return next((entry for entry in MOTIFS if entry["name"] == name), None)


__all__ = ["MOTIFS", "MOTIF_ALIASES", "motifs_for_categories", "find_motif", "safe_motif"]
