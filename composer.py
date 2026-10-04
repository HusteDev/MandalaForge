"""Composer plan data model and seeded per-node random streams."""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class CellRecipe:
    motif: str
    category: str
    slot_child: Optional[CellRecipe] = None
    attachments: List[CellRecipe] = field(default_factory=list)
    is_fallback: bool = False
    provides_contact: bool = False
    dropped: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "motif": self.motif,
            "category": self.category,
            "slot_child": None if self.slot_child is None else self.slot_child.to_dict(),
            "attachments": [a.to_dict() for a in self.attachments],
            "is_fallback": self.is_fallback,
            "provides_contact": self.provides_contact,
            "dropped": self.dropped,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> CellRecipe:
        slot_child = d.get("slot_child")
        return cls(
            motif=d["motif"],
            category=d["category"],
            slot_child=None if slot_child is None else cls.from_dict(slot_child),
            attachments=[cls.from_dict(a) for a in d.get("attachments", [])],
            is_fallback=d.get("is_fallback", False),
            provides_contact=d.get("provides_contact", False),
            dropped=d.get("dropped", False),
        )


@dataclass
class CellEntry:
    centre: Optional[CellRecipe]
    divider: Optional[CellRecipe]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "centre": None if self.centre is None else self.centre.to_dict(),
            "divider": None if self.divider is None else self.divider.to_dict(),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> CellEntry:
        centre, divider = d.get("centre"), d.get("divider")
        return cls(
            centre=None if centre is None else CellRecipe.from_dict(centre),
            divider=None if divider is None else CellRecipe.from_dict(divider),
        )


@dataclass
class RingPlan:
    ring_index: int
    divisions: int
    centre_share: float
    sequence: List[CellEntry]
    ring_seed: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ring_index": self.ring_index,
            "divisions": self.divisions,
            "centre_share": self.centre_share,
            "sequence": [entry.to_dict() for entry in self.sequence],
            "ring_seed": self.ring_seed,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> RingPlan:
        return cls(
            ring_index=d["ring_index"],
            divisions=d["divisions"],
            centre_share=d["centre_share"],
            sequence=[CellEntry.from_dict(e) for e in d["sequence"]],
            ring_seed=d["ring_seed"],
        )


@dataclass
class DesignPlan:
    seed: int
    style: Dict[str, Any]
    rings: List[RingPlan]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "seed": self.seed,
            "style": self.style,
            "rings": [ring.to_dict() for ring in self.rings],
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> DesignPlan:
        return cls(
            seed=d["seed"],
            style=d["style"],
            rings=[RingPlan.from_dict(r) for r in d["rings"]],
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_json(cls, text: str) -> DesignPlan:
        return cls.from_dict(json.loads(text))


def node_rng(seed: int, ring_index: int, seq_pos: int, depth: int, position: str) -> random.Random:
    """Independent, reproducible stream for one node of the plan tree."""
    return random.Random(
        seed * 1_000_003
        + ring_index * 10_007
        + seq_pos * 101
        + depth * 11
        + (0 if position == "centre" else 1)
    )
