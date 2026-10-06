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
    # Defaults keep revision-1 plans loadable: they used stems for contact and no side touch.
    contact_mode: str = "stem"
    side_touch_radial: float = 0.5

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ring_index": self.ring_index,
            "divisions": self.divisions,
            "centre_share": self.centre_share,
            "sequence": [entry.to_dict() for entry in self.sequence],
            "ring_seed": self.ring_seed,
            "contact_mode": self.contact_mode,
            "side_touch_radial": self.side_touch_radial,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> RingPlan:
        return cls(
            ring_index=d["ring_index"],
            divisions=d["divisions"],
            centre_share=d["centre_share"],
            sequence=[CellEntry.from_dict(e) for e in d["sequence"]],
            ring_seed=d["ring_seed"],
            contact_mode=d.get("contact_mode", "stem"),
            side_touch_radial=d.get("side_touch_radial", 0.5),
        )


@dataclass
class DesignPlan:
    seed: int
    style: Dict[str, Any]
    rings: List[RingPlan]
    base_symmetry: int = 1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "seed": self.seed,
            "style": self.style,
            "rings": [ring.to_dict() for ring in self.rings],
            "base_symmetry": self.base_symmetry,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> DesignPlan:
        return cls(
            seed=d["seed"],
            style=d["style"],
            rings=[RingPlan.from_dict(r) for r in d["rings"]],
            base_symmetry=d.get("base_symmetry", 1),
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_json(cls, text: str) -> DesignPlan:
        return cls.from_dict(json.loads(text))


def node_seed(seed: int, ring_index: int, seq_pos: int, depth: int, position: str) -> int:
    """Integer seed of one node's stream, kept so the node can be regenerated later."""
    return (
        seed * 1_000_003
        + ring_index * 10_007
        + seq_pos * 101
        + depth * 11
        + (0 if position == "centre" else 1)
    )


def node_rng(seed: int, ring_index: int, seq_pos: int, depth: int, position: str) -> random.Random:
    """Independent, reproducible stream for one node of the plan tree."""
    return random.Random(node_seed(seed, ring_index, seq_pos, depth, position))


BOTH_MIN_CELL_WIDTH_PX = 2 * 14.0
CONTACT_OVERFLOW = 0.1
MAX_NODE_DEPTH = 3
POSITION_MODES = ("centre", "divider", "both")
FORCE_ROLES = ("base", "slot", "contact")
MIN_DIVISIONS = 4
MAX_DIVISIONS = 24
# Ring contact modes, strongest first (spec 13.2).
CONTACT_MODES = ("side", "overflow", "stem")
SIDE_TOUCH_RADIAL_RANGE = (0.35, 0.6)
# Base symmetry drawn with `vary_divisions` is a divisor of `num_divisions` in this range.
SYMMETRY_MIN = 3
SYMMETRY_MAX = 8


def _side_touch_capable(entry: Dict) -> bool:
    """
    Whether a base motif can meet its ring neighbours at a shared side vertex.

    The registry gains a `side_touch` key in Task 18; until then the motifs that will support it
    are the cell-spanning bands (scallop, ring_band, the safe band) plus petal and leaf.
    """
    return bool(entry.get("side_touch", entry["spans_cell"] or entry["name"] in ("petal", "leaf")))


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
        counts = [settings.num_divisions, *(settings.ring_divisions or [])]
        for count in counts:
            if isinstance(count, bool) or not isinstance(count, int) or not MIN_DIVISIONS <= count <= MAX_DIVISIONS:
                raise ValueError(
                    f"division count must be an integer from {MIN_DIVISIONS} to {MAX_DIVISIONS}, got {count!r}"
                )
        self.seed = seed
        self.ring_geometry = ring_geometry
        self.settings = settings
        self._style: Optional[Dict[str, Any]] = None
        self._symmetry: Optional[int] = None
        self._canonical_names: Dict[int, Tuple[str, ...]] = {}
        self._tried: Dict[Tuple[int, int, int, str], List[str]] = {}

    # ------------------------------------------------------------------ public

    @staticmethod
    def divisor_candidates(count: int, symmetry: int = 1) -> List[int]:
        """Sequence lengths that repeat whole in every wedge of `count // symmetry` cells."""
        wedge = count // symmetry
        found = {1}
        found.update(d for d in range(1, 5) if wedge % d == 0 and d < count)
        return sorted(found)

    @staticmethod
    def base_symmetry(num_divisions: int, vary_divisions: bool,
                      ring_divisions: Optional[List[int]], rng: random.Random) -> int:
        """
        The design's base symmetry `B` (spec 13.1): every ring's count is a multiple of it.

        An explicit list gives its gcd (possibly 1); without vary every ring has `num_divisions`;
        with vary a divisor of `num_divisions` in 3..8, weighted by its value, or 1 when none exists.
        """
        if ring_divisions:
            return math.gcd(*ring_divisions)
        if not vary_divisions:
            return num_divisions
        candidates = [d for d in range(SYMMETRY_MIN, SYMMETRY_MAX + 1) if num_divisions % d == 0]
        if not candidates:
            return 1
        return rng.choices(candidates, weights=candidates)[0]

    @property
    def symmetry(self) -> int:
        """This design's base symmetry, drawn once from its own design-level stream."""
        if self._symmetry is None:
            settings = self.settings
            given = list(settings.ring_divisions or [])
            if given and len(given) < len(self.ring_geometry) and not settings.vary_divisions:
                given.append(settings.num_divisions)  # the rings past the list use num_divisions
            self._symmetry = self.base_symmetry(
                settings.num_divisions, settings.vary_divisions, given or None,
                node_rng(self.seed, -1, 0, 1, "centre"),
            )
        return self._symmetry

    @property
    def style(self) -> Dict[str, Any]:
        if self._style is None:
            rng = node_rng(self.seed, -1, 0, 0, "centre")
            chosen = [c for c in self.settings.categories if rng.random() < 0.7]
            if not chosen:
                chosen = list(self.settings.categories)
            self._style = {"categories": chosen, "positions": rng.choice(POSITION_MODES)}
        return self._style

    @style.setter
    def style(self, value: Dict[str, Any]) -> None:
        self._style = value
        self._canonical_names.clear()

    def _pick(self, candidates: List[Dict], rng: random.Random) -> Dict:
        """Style biases the pick: motifs in a style category weigh 3, others 1."""
        ordered = sorted(candidates, key=lambda m: m["name"])
        favoured = self.style["categories"]
        weights = [3 if m["category"] in favoured else 1 for m in ordered]
        return rng.choices(ordered, weights=weights)[0]

    def plan(self) -> DesignPlan:
        symmetry = self.symmetry
        ring_seeds = self.settings.ring_seeds or {}
        rings = [
            self.plan_ring(i, ring_seeds.get(i, self.seed))
            for i in range(len(self.ring_geometry))
        ]
        style = {**self.style, "categories": list(self.style["categories"])}
        return DesignPlan(self.seed, style, rings, symmetry)

    def plan_ring(self, ring_index: int, ring_seed: int) -> RingPlan:
        rng = node_rng(ring_seed, ring_index, 0, -1, "centre")
        divisions = self._division_count(ring_index, rng)
        seq_len = self._sequence_length(divisions, rng)
        mode, centre_share = self._position_mode(ring_index, divisions, rng)
        side_touch_radial = rng.uniform(*SIDE_TOUCH_RADIAL_RANGE)
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

        contact_mode = self._contact_mode(ring_index, sequence)
        if not (force and force["role"] == "contact"):
            self._ensure_contact(ring_index, sequence, contact_mode)
        plan = RingPlan(ring_index, divisions, centre_share, sequence, ring_seed,
                        contact_mode, side_touch_radial)
        if ring_seed == self.seed:
            self._canonical_names[ring_index] = self._base_names(plan)
        return plan

    def replace_node(self, ring: RingPlan, seq_pos: int, position: str, reason: str) -> bool:
        """
        Advance one node along the fallback chain in place; False when exhausted.

        A floating base in a side-touch ring first tries another side-touching base, then a stem;
        in other rings it gets the stem first. A stem is a contact repair that changes no motif,
        so it stays available under `force_motif`; substituting the motif or falling back to a
        safe band does not.
        """
        if not 0 <= seq_pos < len(ring.sequence):
            return False
        entry = ring.sequence[seq_pos]
        node = entry.centre if position == "centre" else entry.divider
        if node is None:
            return False
        can_substitute = not self.settings.force_motif and not node.is_fallback
        if (reason == "floating" and ring.contact_mode == "side" and can_substitute
                and self._substitute(ring, seq_pos, position, side_only=True)):
            return True
        if reason == "floating" and not node.attachments and ring.ring_index > 0:
            # A floating base gets a stem toward the ring inside it (the innermost ring has none).
            node.attachments.append(self._stem_recipe())
            return True
        if not can_substitute:
            return False
        if self._substitute(ring, seq_pos, position, side_only=False):
            return True
        safe = safe_motif(node.category)
        self._set_node(entry, position, CellRecipe(safe["name"], safe["category"], is_fallback=True))
        self._refresh_contact(ring)
        return True

    def _substitute(self, ring: RingPlan, seq_pos: int, position: str, side_only: bool) -> bool:
        """Swap the node for an untried base (side-touching only, if asked); False when none is left."""
        entry = ring.sequence[seq_pos]
        node = entry.centre if position == "centre" else entry.divider
        tried = self._tried.setdefault((ring.ring_index, ring.ring_seed, seq_pos, position), [])
        if node.motif not in tried:
            tried.append(node.motif)

        cell_width, ring_depth = self._ring_metrics(ring.ring_index, ring.divisions)
        mode = "both" if ring.centre_share < 1.0 else position
        cell_width *= self._budget(mode, ring.centre_share, position)

        candidates = [
            c for c in self._base_candidates(ring.ring_index, position, cell_width, ring_depth)
            if c["name"] not in tried and (not side_only or _side_touch_capable(c))
        ]
        if not candidates:
            return False
        offset = 3 * len(tried)
        rng = node_rng(ring.ring_seed, ring.ring_index, seq_pos, offset, position)
        chosen = self._pick(candidates, rng)
        tried.append(chosen["name"])
        new_node = self._compose(
            chosen, rng, ring.ring_index, ring.ring_seed, seq_pos, position,
            cell_width, ring_depth, offset,
        )
        self._set_node(entry, position, new_node)
        self._refresh_contact(ring)
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
            # A multiple of the base symmetry, with inner rings drawing smaller multipliers.
            symmetry = self.symmetry
            scale = 0.5 + 0.5 * (self._mid_radius(ring_index) / self._mid_radius(len(self.ring_geometry) - 1))
            raw = round(self.settings.num_divisions * scale * rng.triangular(0.7, 1.3, 1.0) / symmetry)
            count = symmetry * max(1, min(MAX_DIVISIONS // symmetry, raw))
            if count < MIN_DIVISIONS:
                count = symmetry * math.ceil(MIN_DIVISIONS / symmetry)
            return count
        return self.settings.num_divisions

    def _sequence_length(self, divisions: int, rng: random.Random) -> int:
        candidates = self.divisor_candidates(divisions, self.symmetry)
        weights = [1.0 if d == 1 else self.settings.complexity for d in candidates]
        return rng.choices(candidates, weights=weights)[0]

    def _position_mode(self, ring_index: int, divisions: int, rng: random.Random) -> Tuple[str, float]:
        force = self.settings.force_motif if ring_index > 0 else None
        cell_width = self._ring_metrics(ring_index, divisions)[0]
        if force:
            mode = force["position"]
        else:
            preferred = self.style["positions"]
            if ring_index == 0:
                # Only positions that an enabled spans_cell base supports; safe band when none does.
                ring_depth = self._ring_metrics(ring_index, divisions)[1]
                modes = tuple(
                    m for m in POSITION_MODES[:2]
                    if self._base_candidates(0, m, cell_width, ring_depth)
                ) or POSITION_MODES[:2]
            else:
                modes = POSITION_MODES
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

    @staticmethod
    def _base_names(plan: RingPlan) -> Tuple[str, ...]:
        names = {
            node.motif
            for entry in plan.sequence
            for node in (entry.centre, entry.divider)
            if node is not None
        }
        return tuple(sorted(names))

    def _inward_base_names(self, ring_index: int) -> Tuple[str, ...]:
        """Base names of the canonical (design-seed) ring just inside, so a ring's plan
        depends only on the design seed and its own ring seed."""
        if ring_index == 0:
            return ()
        inner = ring_index - 1
        if inner not in self._canonical_names:
            self.plan_ring(inner, self.seed)  # records the canonical names as it plans
        return self._canonical_names[inner]

    # ------------------------------------------------------------ node building

    @staticmethod
    def _passes(motif: Dict, cell_width: float, ring_depth: float) -> bool:
        return motif["min_cell_width_px"] <= cell_width and motif["min_ring_depth_px"] <= ring_depth

    def _base_candidates(self, ring_index: int, position: str, cell_width: float,
                         ring_depth: float) -> List[Dict]:
        return [
            m for m in motifs_for_categories(self.settings.categories)
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
            safe = safe_motif(self.settings.categories[0])
            return CellRecipe(safe["name"], safe["category"], is_fallback=True)
        chosen = self._pick(candidates, rng)
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
            m for m in motifs_for_categories(self.settings.categories)
            if "slot" in m["roles"]
            and self._passes(m, cell_width * width_fraction, ring_depth * depth_fraction)
        ]
        if not candidates:
            return
        child_rng = node_rng(ring_seed, ring_index, seq_pos, offset + depth + 1, position)
        child_motif = self._pick(candidates, child_rng)
        node.slot_child = CellRecipe(child_motif["name"], child_motif["category"])
        self._nest(node.slot_child, child_motif, child_rng, ring_index, ring_seed, seq_pos,
                   position, cell_width, ring_depth, offset, depth + 1, width_fraction,
                   depth_fraction)

    # ----------------------------------------------------------------- contact

    def _stem_recipe(self) -> CellRecipe:
        motif = next(
            (m for m in motifs_for_categories(self.settings.categories) if "attachment" in m["roles"]),
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

    def _contact_mode(self, ring_index: int, sequence: List[CellEntry]) -> str:
        """
        How the ring reaches the structure (spec 13.2): by side touch when every base supports it
        (always in the innermost ring), else by inward overflow when every base has it, else stems.
        """
        if ring_index == 0:
            return "side"
        entries = [self._registry_entry(n) for e in sequence for n in (e.centre, e.divider) if n is not None]
        if all(_side_touch_capable(entry) for entry in entries):
            return "side"
        if all(entry["max_overflow_inward"] >= CONTACT_OVERFLOW for entry in entries):
            return "overflow"
        return "stem"

    def _refresh_contact(self, ring: RingPlan) -> None:
        """
        Re-flag contact after a node changed. The ring keeps its mode unless its new bases no
        longer support it, so a revision-1 plan (mode "stem") keeps its revision-1 contact.
        """
        current = self._contact_mode(ring.ring_index, ring.sequence)
        ring.contact_mode = max(ring.contact_mode, current, key=CONTACT_MODES.index)
        self._ensure_contact(ring.ring_index, ring.sequence, ring.contact_mode)

    def _ensure_contact(self, ring_index: int, sequence: List[CellEntry], contact_mode: str) -> None:
        """Give the ring's bases a route to the inward neighbour, as its contact mode allows, and flag them."""
        nodes = [n for e in sequence for n in (e.centre, e.divider) if n is not None]
        if ring_index == 0:
            for node in nodes:
                node.provides_contact = True
            return

        def has_inward(node: CellRecipe) -> bool:
            return self._registry_entry(node)["max_overflow_inward"] >= CONTACT_OVERFLOW

        def spans(node: CellRecipe) -> bool:
            return bool(self._registry_entry(node)["spans_cell"])

        if contact_mode == "side":
            # The ring is one connected band, so one inward contact per sequence is enough:
            # overflow where a base has it, else a single stem on the first node.
            if nodes and not any(has_inward(n) or n.attachments for n in nodes):
                nodes[0].attachments.append(self._stem_recipe())
            for node in nodes:
                node.provides_contact = True
            return
        if contact_mode == "overflow":
            for node in nodes:
                node.provides_contact = has_inward(node)
            return

        if nodes and not any(has_inward(n) or n.attachments for n in nodes):
            nodes[0].attachments.append(self._stem_recipe())
        for node in nodes:
            if not spans(node) and not has_inward(node) and not node.attachments:
                node.attachments.append(self._stem_recipe())
        ring_has_contact = any(has_inward(n) or n.attachments for n in nodes)
        for node in nodes:
            node.provides_contact = has_inward(node) or (spans(node) and ring_has_contact)
