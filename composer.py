"""Composer plan data model and seeded per-node random streams."""

from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from motifs import find_motif, motifs_for_categories, safe_motif


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


BOTH_MIN_CELL_WIDTH_PX = 2 * 14.0
CONTACT_OVERFLOW = 0.1
MAX_NODE_DEPTH = 3
POSITION_MODES = ("centre", "divider", "both")
FORCE_ROLES = ("base", "slot", "contact")


@dataclass
class ComposerSettings:
    num_divisions: int = 12
    vary_divisions: bool = False
    ring_divisions: Optional[List[int]] = None
    complexity: float = 0.5
    min_pattern_size: float = 10.0
    categories: List[str] = field(default_factory=lambda: ["botanical"])
    force_motif: Optional[Dict[str, str]] = None
    ring_seeds: Optional[Dict[int, int]] = None


class Composer:
    """Decides, deterministically and without drawing, what every ring contains."""

    def __init__(self, seed: int, ring_geometry: List[Dict[str, float]], settings: ComposerSettings):
        if not settings.categories:
            raise ValueError("at least one category must be enabled")
        force = settings.force_motif
        if force:
            if find_motif(force["name"]) is None:
                raise ValueError(f"unknown forced motif: {force['name']}")
            if force["position"] not in POSITION_MODES:
                raise ValueError(f"unknown forced position: {force['position']}")
            if force["role"] not in FORCE_ROLES:
                raise ValueError(f"unknown forced role: {force['role']}")
        self.seed = seed
        self.ring_geometry = ring_geometry
        self.settings = settings
        self._style: Optional[Dict[str, Any]] = None
        self._base_name_memo: Dict[Tuple[int, int], Tuple[str, ...]] = {}
        self._tried: Dict[Tuple[int, int, int, str], List[str]] = {}

    # ------------------------------------------------------------------ public

    @staticmethod
    def divisor_candidates(count: int) -> List[int]:
        found = {1}
        found.update(d for d in range(1, 5) if count % d == 0 and d < count)
        return sorted(found)

    @property
    def style(self) -> Dict[str, Any]:
        if self._style is None:
            rng = node_rng(self.seed, -1, 0, 0, "centre")
            chosen = [c for c in self.settings.categories if rng.random() < 0.7]
            if not chosen:
                chosen = list(self.settings.categories)
            self._style = {"categories": chosen, "positions": rng.choice(POSITION_MODES)}
        return self._style

    def plan(self) -> DesignPlan:
        ring_seeds = self.settings.ring_seeds or {}
        rings = [
            self.plan_ring(i, ring_seeds.get(i, self.seed))
            for i in range(len(self.ring_geometry))
        ]
        return DesignPlan(self.seed, {**self.style, "categories": list(self.style["categories"])}, rings)

    def plan_ring(self, ring_index: int, ring_seed: int) -> RingPlan:
        rng = node_rng(ring_seed, ring_index, 0, -1, "centre")
        divisions = self._division_count(ring_index, rng)
        seq_len = self._sequence_length(divisions, rng)
        mode, centre_share = self._position_mode(ring_index, divisions, rng)
        cell_width, ring_depth = self._ring_metrics(ring_index, divisions)
        avoid = set(self._inward_base_names(ring_index))
        force = self.settings.force_motif if ring_index > 0 else None

        sequence: List[CellEntry] = []
        for s in range(seq_len):
            nodes: Dict[str, Optional[CellRecipe]] = {"centre": None, "divider": None}
            for position in ("centre", "divider"):
                if mode not in (position, "both"):
                    continue
                budget = self._budget(mode, centre_share, position)
                nodes[position] = self._plan_node(
                    ring_index, ring_seed, s, position, cell_width * budget, ring_depth, avoid, force
                )
            sequence.append(CellEntry(nodes["centre"], nodes["divider"]))

        if not (force and force["role"] == "contact"):
            self._ensure_contact(ring_index, sequence)
        return RingPlan(ring_index, divisions, centre_share, sequence, ring_seed)

    def replace_node(self, ring: RingPlan, seq_pos: int, position: str, reason: str) -> bool:
        """Advance one node along the fallback chain in place; False when exhausted."""
        if self.settings.force_motif:
            return False
        if not 0 <= seq_pos < len(ring.sequence):
            return False
        entry = ring.sequence[seq_pos]
        node = entry.centre if position == "centre" else entry.divider
        if node is None or node.is_fallback:
            return False

        tried = self._tried.setdefault((ring.ring_index, ring.ring_seed, seq_pos, position), [])
        if node.motif not in tried:
            tried.append(node.motif)

        cell_width, ring_depth = self._ring_metrics(ring.ring_index, ring.divisions)
        mode = "both" if ring.centre_share < 1.0 else position
        cell_width *= self._budget(mode, ring.centre_share, position)

        candidates = [
            c for c in self._base_candidates(ring.ring_index, position, cell_width, ring_depth)
            if c["name"] not in tried
        ]
        if candidates:
            offset = 3 * len(tried)
            rng = node_rng(ring.ring_seed, ring.ring_index, seq_pos, offset, position)
            chosen = rng.choice(candidates)
            tried.append(chosen["name"])
            new_node = self._compose(
                chosen, rng, ring.ring_index, ring.ring_seed, seq_pos, position,
                cell_width, ring_depth, offset,
            )
            self._set_node(entry, position, new_node)
            self._ensure_contact(ring.ring_index, ring.sequence)
            return True

        if reason == "floating" and not node.attachments:
            node.attachments.append(self._stem_recipe())
            return True

        safe = safe_motif(node.category)
        self._set_node(entry, position, CellRecipe(safe["name"], safe["category"], is_fallback=True))
        self._ensure_contact(ring.ring_index, ring.sequence)
        return True

    # ----------------------------------------------------------- ring decisions

    def _mid_radius(self, ring_index: int) -> float:
        geometry = self.ring_geometry[ring_index]
        return (geometry["inner_radius"] + geometry["outer_radius"]) / 2.0

    def _division_count(self, ring_index: int, rng: random.Random) -> int:
        given = self.settings.ring_divisions
        if given is not None and ring_index < len(given):
            return given[ring_index]
        if self.settings.vary_divisions:
            scale = 0.5 + 0.5 * (self._mid_radius(ring_index) / self._mid_radius(len(self.ring_geometry) - 1))
            raw = round(self.settings.num_divisions * scale * rng.triangular(0.7, 1.3, 1.0))
            return max(4, min(24, raw))
        return self.settings.num_divisions

    def _sequence_length(self, divisions: int, rng: random.Random) -> int:
        candidates = self.divisor_candidates(divisions)
        weights = [1.0 if d == 1 else self.settings.complexity for d in candidates]
        return rng.choices(candidates, weights=weights)[0]

    def _position_mode(self, ring_index: int, divisions: int, rng: random.Random) -> Tuple[str, float]:
        force = self.settings.force_motif if ring_index > 0 else None
        cell_width = self._ring_metrics(ring_index, divisions)[0]
        if force:
            mode = force["position"]
        else:
            preferred = self.style["positions"]
            modes = POSITION_MODES[:2] if ring_index == 0 else POSITION_MODES
            weights = [0.6 if m == preferred else 0.2 for m in modes]
            mode = rng.choices(modes, weights=weights)[0]
            if mode == "both" and cell_width < BOTH_MIN_CELL_WIDTH_PX:
                mode = "centre"
        centre_share = rng.uniform(0.45, 0.75) if mode == "both" else 1.0
        return mode, centre_share

    def _ring_metrics(self, ring_index: int, divisions: int) -> Tuple[float, float]:
        geometry = self.ring_geometry[ring_index]
        cell_width = self._mid_radius(ring_index) * math.radians(360.0 / divisions)
        return cell_width, geometry["outer_radius"] - geometry["inner_radius"]

    @staticmethod
    def _budget(mode: str, centre_share: float, position: str) -> float:
        if mode != "both":
            return 1.0
        return centre_share if position == "centre" else 1.0 - centre_share

    def _inward_base_names(self, ring_index: int) -> Tuple[str, ...]:
        """Base motif names of the ring just inside, planned with that ring's own seed."""
        if ring_index == 0:
            return ()
        inner = ring_index - 1
        inner_seed = (self.settings.ring_seeds or {}).get(inner, self.seed)
        key = (inner, inner_seed)
        if key not in self._base_name_memo:
            names = set()
            for entry in self.plan_ring(inner, inner_seed).sequence:
                for node in (entry.centre, entry.divider):
                    if node is not None:
                        names.add(node.motif)
            self._base_name_memo[key] = tuple(sorted(names))
        return self._base_name_memo[key]

    # ------------------------------------------------------------ node building

    @staticmethod
    def _passes(motif: Dict, cell_width: float, ring_depth: float) -> bool:
        return motif["min_cell_width_px"] <= cell_width and motif["min_ring_depth_px"] <= ring_depth

    def _base_candidates(self, ring_index: int, position: str, cell_width: float,
                         ring_depth: float) -> List[Dict]:
        return [
            m for m in motifs_for_categories(self.style["categories"])
            if "base" in m["roles"]
            and position in m["positions"]
            and (ring_index > 0 or m["spans_cell"])
            and self._passes(m, cell_width, ring_depth)
        ]

    def _plan_node(self, ring_index: int, ring_seed: int, seq_pos: int, position: str,
                   cell_width: float, ring_depth: float, avoid: set,
                   force: Optional[Dict[str, str]]) -> CellRecipe:
        rng = node_rng(ring_seed, ring_index, seq_pos, 0, position)
        if force:
            return self._forced_node(force, rng, ring_index, ring_seed, seq_pos, position,
                                     cell_width, ring_depth)
        candidates = self._base_candidates(ring_index, position, cell_width, ring_depth)
        if ring_index > 0:
            candidates = [c for c in candidates if c["name"] not in avoid] or candidates
        if not candidates:
            safe = safe_motif(self.style["categories"][0])
            return CellRecipe(safe["name"], safe["category"], is_fallback=True)
        chosen = rng.choice(candidates)
        return self._compose(chosen, rng, ring_index, ring_seed, seq_pos, position,
                             cell_width, ring_depth, 0)

    def _forced_node(self, force: Dict[str, str], rng: random.Random, ring_index: int,
                     ring_seed: int, seq_pos: int, position: str, cell_width: float,
                     ring_depth: float) -> CellRecipe:
        forced = find_motif(force["name"])
        if force["role"] == "base":
            return self._compose(forced, rng, ring_index, ring_seed, seq_pos, position,
                                 cell_width, ring_depth, 0)
        petal = find_motif("petal")
        node = CellRecipe(petal["name"], petal["category"])
        if force["role"] == "slot":
            node.slot_child = CellRecipe(forced["name"], forced["category"])
        else:
            node.attachments.append(
                CellRecipe(forced["name"], forced["category"], provides_contact=True)
            )
        return node

    def _compose(self, motif: Dict, rng: random.Random, ring_index: int, ring_seed: int,
                 seq_pos: int, position: str, cell_width: float, ring_depth: float,
                 offset: int) -> CellRecipe:
        node = CellRecipe(motif["name"], motif["category"])
        self._nest(node, motif, rng, ring_index, ring_seed, seq_pos, position,
                   cell_width, ring_depth, offset, 0, 1.0, 1.0)
        return node

    def _nest(self, node: CellRecipe, motif: Dict, rng: random.Random, ring_index: int,
              ring_seed: int, seq_pos: int, position: str, cell_width: float,
              ring_depth: float, offset: int, depth: int, width_fraction: float,
              depth_fraction: float) -> None:
        estimate = motif["slot_estimate"]
        if estimate is None or depth + 1 >= MAX_NODE_DEPTH:
            return
        if not rng.random() < self.settings.complexity * (0.5 ** depth):
            return
        width_fraction *= estimate[0]
        depth_fraction *= estimate[1]
        candidates = [
            m for m in motifs_for_categories(self.style["categories"])
            if "slot" in m["roles"]
            and self._passes(m, cell_width * width_fraction, ring_depth * depth_fraction)
        ]
        if not candidates:
            return
        child_rng = node_rng(ring_seed, ring_index, seq_pos, offset + depth + 1, position)
        child_motif = child_rng.choice(candidates)
        node.slot_child = CellRecipe(child_motif["name"], child_motif["category"])
        self._nest(node.slot_child, child_motif, child_rng, ring_index, ring_seed, seq_pos,
                   position, cell_width, ring_depth, offset, depth + 1, width_fraction,
                   depth_fraction)

    # ----------------------------------------------------------------- contact

    def _stem_recipe(self) -> CellRecipe:
        motif = next(
            (m for m in motifs_for_categories(self.style["categories"]) if "attachment" in m["roles"]),
            None,
        ) or find_motif("stem")
        return CellRecipe(motif["name"], motif["category"], provides_contact=True)

    @staticmethod
    def _set_node(entry: CellEntry, position: str, node: CellRecipe) -> None:
        if position == "centre":
            entry.centre = node
        else:
            entry.divider = node

    @staticmethod
    def _registry_entry(node: CellRecipe) -> Dict:
        return find_motif(node.motif) or safe_motif(node.category)

    def _ensure_contact(self, ring_index: int, sequence: List[CellEntry]) -> None:
        """Give every base a route to its inward neighbour and flag it."""
        nodes = [n for e in sequence for n in (e.centre, e.divider) if n is not None]
        if ring_index == 0:
            for node in nodes:
                node.provides_contact = True
            return

        def has_inward(node: CellRecipe) -> bool:
            return self._registry_entry(node)["max_overflow_inward"] >= CONTACT_OVERFLOW

        def spans(node: CellRecipe) -> bool:
            return bool(self._registry_entry(node)["spans_cell"])

        if nodes and not any(has_inward(n) or n.attachments for n in nodes):
            nodes[0].attachments.append(self._stem_recipe())
        for node in nodes:
            if not spans(node) and not has_inward(node) and not node.attachments:
                node.attachments.append(self._stem_recipe())
        ring_has_contact = any(has_inward(n) or n.attachments for n in nodes)
        for node in nodes:
            node.provides_contact = has_inward(node) or (spans(node) and ring_has_contact)
