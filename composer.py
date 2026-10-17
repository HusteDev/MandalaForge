"""Composer plan data model and seeded per-node random streams."""

from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from motifs import find_motif, motifs_for_categories, safe_motif
from motifs.embellish import EMBELLISHMENT_ORDER, INTERIOR_FILLS
from motifs.geometry import salted_seed


@dataclass
class CellRecipe:
    motif: str
    category: str
    slot_child: Optional[CellRecipe] = None
    attachments: List[CellRecipe] = field(default_factory=list)
    is_fallback: bool = False
    provides_contact: bool = False
    dropped: bool = False
    # An attachment drawn in one cell per wedge only (cell_index % (divisions // base_symmetry) == 0):
    # the single stem of a side-touch ring, whose cells already form one connected band.
    once_per_wedge: bool = False
    # Embellishment names for this node, in EMBELLISHMENT_ORDER (spec 6.4); picked for base nodes only.
    embellishments: List[str] = field(default_factory=list)
    # Share of each size range below which the node's size draws never fall (max-region spec 5, step 2): 0.0
    # draws the whole range, REPAIR_SIZE_FLOOR its upper end.
    size_floor: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "motif": self.motif,
            "category": self.category,
            "slot_child": None if self.slot_child is None else self.slot_child.to_dict(),
            "attachments": [a.to_dict() for a in self.attachments],
            "is_fallback": self.is_fallback,
            "provides_contact": self.provides_contact,
            "dropped": self.dropped,
            "once_per_wedge": self.once_per_wedge,
            "embellishments": list(self.embellishments),
            "size_floor": self.size_floor,
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
            once_per_wedge=d.get("once_per_wedge", False),
            embellishments=list(d.get("embellishments", [])),
            size_floor=d.get("size_floor", 0.0),
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
    # Revision-2 plans touched at mid height only.
    touch_height: str = "mid"
    # Layered rings (spec 5.1): one back motif for the whole ring, drawn on every divider, and whether a
    # failing composite dropped it (spec 5.4).
    back: Optional[CellRecipe] = None
    back_dropped: bool = False
    # "centre", "divider", "both" or "layered"; plans saved before it was stored derive it from their entries.
    position_mode: str = ""

    def __post_init__(self) -> None:
        if not self.position_mode:
            self.position_mode = _derived_position_mode(self)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ring_index": self.ring_index,
            "divisions": self.divisions,
            "centre_share": self.centre_share,
            "sequence": [entry.to_dict() for entry in self.sequence],
            "ring_seed": self.ring_seed,
            "contact_mode": self.contact_mode,
            "side_touch_radial": self.side_touch_radial,
            "touch_height": self.touch_height,
            "back": None if self.back is None else self.back.to_dict(),
            "back_dropped": self.back_dropped,
            "position_mode": self.position_mode,
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
            touch_height=d.get("touch_height", "mid"),
            back=None if d.get("back") is None else CellRecipe.from_dict(d["back"]),
            back_dropped=d.get("back_dropped", False),
            position_mode=d.get("position_mode", ""),
        )


def _derived_position_mode(ring: RingPlan) -> str:
    """The position mode a ring's own content implies, for plans that do not store it."""
    if ring.back is not None:
        return "layered"
    if ring.centre_share < 1.0:
        return "both"
    if ring.sequence and all(entry.centre is None and entry.divider is not None for entry in ring.sequence):
        return "divider"
    return "centre"


@dataclass
class DesignPlan:
    seed: int
    style: Dict[str, Any]
    rings: List[RingPlan]
    base_symmetry: int = 1
    # Region-cap repairs kept by the ladder, in order: {"step", "kind", "ring", "change"} (max-region spec 5).
    repairs: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "seed": self.seed,
            "style": self.style,
            "rings": [ring.to_dict() for ring in self.rings],
            "base_symmetry": self.base_symmetry,
            "repairs": [dict(repair) for repair in self.repairs],
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> DesignPlan:
        return cls(
            seed=d["seed"],
            style=d["style"],
            rings=[RingPlan.from_dict(r) for r in d["rings"]],
            base_symmetry=d.get("base_symmetry", 1),
            repairs=[dict(repair) for repair in d.get("repairs", [])],
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_json(cls, text: str) -> DesignPlan:
        return cls.from_dict(json.loads(text))


def recipe_at(ring: RingPlan, position: str, node_path: Tuple[int, ...], on_back: bool = False) -> Optional[CellRecipe]:
    """
    The plan recipe behind a placed node: the ring's back when `on_back`, else the sequence entry
    `node_path[0]` at `position`, then its slot child once per further element. None where the chain ends.
    """
    if on_back:
        return ring.back
    if not node_path or not 0 <= node_path[0] < len(ring.sequence) or position not in ("centre", "divider"):
        return None
    recipe = getattr(ring.sequence[node_path[0]], position)
    for _ in node_path[1:]:
        if recipe is None:
            return None
        recipe = recipe.slot_child
    return recipe


def node_seed(seed: int, ring_index: int, seq_pos: int, depth: int, position: str, salt: str = "") -> int:
    """Integer seed of one node's stream, kept so the node can be regenerated later. A salt forks an independent stream."""
    base = (
        seed * 1_000_003
        + ring_index * 10_007
        + seq_pos * 101
        + depth * 11
        + (0 if position == "centre" else 1)
    )
    return salted_seed(base, salt) if salt else base


def node_rng(seed: int, ring_index: int, seq_pos: int, depth: int, position: str,
             salt: str = "") -> random.Random:
    """Independent, reproducible stream for one node of the plan tree."""
    return random.Random(node_seed(seed, ring_index, seq_pos, depth, position, salt))


def ring_stream_seed(ring_seed: int, ring_index: int, salt: str) -> int:
    """Seed of a ring-level stream shared by every cell of the ring that uses the same salt."""
    return node_seed(ring_seed, ring_index, 0, -2, "centre", salt)


MAX_EMBELLISHMENTS = 3


def pick_embellishments(entry: Dict, complexity: float, rng: random.Random) -> List[str]:
    """
    Embellishments for one node (spec 6.4): `n = clamp(floor(3 (complexity - 0.2) / 0.8 + u), 0, 3)` with
    `u` from `rng`, names drawn without replacement from the entry's accepted list, at most one interior
    fill, returned in `EMBELLISHMENT_ORDER`.
    """
    u = rng.random()
    count = max(0, min(MAX_EMBELLISHMENTS, math.floor(3.0 * (complexity - 0.2) / 0.8 + u)))
    pool = list(entry.get("embellishments", ()))
    picked: List[str] = []
    while len(picked) < count and pool:
        name = rng.choice(pool)
        picked.append(name)
        pool.remove(name)
        if name in INTERIOR_FILLS:
            pool = [other for other in pool if other not in INTERIOR_FILLS]
    return [name for name in EMBELLISHMENT_ORDER if name in picked]


BOTH_MIN_CELL_WIDTH_PX = 2 * 14.0
CONTACT_OVERFLOW = 0.1
MAX_NODE_DEPTH = 3
# The size floor a background repair gives a ring's bases (max-region spec 5, step 2).
REPAIR_SIZE_FLOOR = 0.7
POSITION_MODES = ("centre", "divider", "both", "layered")
# The modes a style may prefer: a layered ring is eligible only outside ring 0 and with a back motif that fits.
STYLE_POSITION_MODES = POSITION_MODES[:3]
FORCE_ROLES = ("base", "slot", "contact")
MIN_DIVISIONS = 4
MAX_DIVISIONS = 24
# Ring contact modes, strongest first (spec 13.2).
CONTACT_MODES = ("side", "overflow", "stem")
# Side-touch heights (spec 3.1) and the side_touch_radial range each one draws from.
TOUCH_HEIGHTS = ("base", "mid")
BASE_TOUCH_RANGE = (0.08, 0.2)
MID_TOUCH_RANGE = (0.35, 0.6)
TOUCH_RANGES = {"base": BASE_TOUCH_RANGE, "mid": MID_TOUCH_RANGE}
# Base symmetry drawn with `vary_divisions` is a divisor of `num_divisions` in this range.
SYMMETRY_MIN = 3
SYMMETRY_MAX = 8


def _weaker_mode(a: str, b: str) -> str:
    """The weaker of two contact modes, in the order side > overflow > stem."""
    return max(a, b, key=CONTACT_MODES.index)


def _base_nodes(sequence: List[CellEntry]) -> List[CellRecipe]:
    """The ring's base nodes in sequence order, centre before divider within an entry."""
    return [n for e in sequence for n in (e.centre, e.divider) if n is not None]


def touch_heights_of(entry: Dict) -> Tuple[str, ...]:
    """
    The heights at which a registry entry can meet its ring neighbours at a shared side vertex.
    A seam motif connects its ring through its seams, so it counts at every height (spec 3.1).
    """
    if entry.get("seams", False):
        return TOUCH_HEIGHTS
    return tuple(entry["side_touch_heights"])


def size_gates(entry: Dict, clearance_px: float) -> Tuple[float, float]:
    """
    The least mid-ring cell width and ring depth, in px, a motif needs: its `min_cell_width_px` and
    `min_ring_depth_px`, raised for a motif whose drawing scales with the white space (the curl, whose turns
    sit a clearance apart) to `min_cell_width_clearances` and `min_ring_depth_clearances` times the
    clearance between two outline strokes. A motif without those keys keeps its fixed gates.
    """
    return (max(entry["min_cell_width_px"], entry.get("min_cell_width_clearances", 0.0) * clearance_px),
            max(entry["min_ring_depth_px"], entry.get("min_ring_depth_clearances", 0.0) * clearance_px))


def common_touch_heights(entries: Sequence[Dict]) -> Tuple[str, ...]:
    """The heights every entry supports, in `TOUCH_HEIGHTS` order; empty when the ring cannot side-touch."""
    supported = [touch_heights_of(entry) for entry in entries]
    return tuple(h for h in TOUCH_HEIGHTS if all(h in heights for heights in supported))


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
    # Forces this position mode on every ring past the innermost where it is eligible. It cannot be combined
    # with force_motif, which forces its own position.
    force_position_mode: Optional[str] = None
    # Embellishments added to the picks of every base and back that accepts them (QA forcing, as
    # force_position_mode is). A forced interior fill replaces a picked one, and takes the slot.
    force_embellishments: Optional[Tuple[str, ...]] = None
    # Measure every face against the print-size cap and repair the oversized ones. Off reproduces the pre-cap engine.
    max_region_cap: bool = True


def force_embellishment_picks(entry: Dict, picked: List[str], forced: Sequence[str]) -> List[str]:
    """
    `picked` with every name of `forced` that `entry` accepts added, in `EMBELLISHMENT_ORDER`. A forced
    interior fill displaces a picked one, so a node keeps at most one. Draws nothing, so the streams and
    every unforced pick stay as they were.
    """
    accepted = entry.get("embellishments", ())
    added = [name for name in forced if name in accepted]
    if any(name in INTERIOR_FILLS for name in added):
        picked = [name for name in picked if name not in INTERIOR_FILLS]
    names = set(picked) | set(added)
    return [name for name in EMBELLISHMENT_ORDER if name in names]


class Composer:
    """Decides, deterministically and without drawing, what every ring contains."""

    def __init__(self, seed: int, ring_geometry: List[Dict[str, float]], settings: ComposerSettings):
        if not settings.categories:
            raise ValueError("at least one category must be enabled")
        force = settings.force_motif
        if force:
            if find_motif(force["name"]) is None:
                raise ValueError(f"unknown forced motif: {force['name']}")
            if force["position"] not in STYLE_POSITION_MODES:
                raise ValueError(f"unknown forced position: {force['position']}")
            if force["role"] not in FORCE_ROLES:
                raise ValueError(f"unknown forced role: {force['role']}")
            if force["position"] == "both" and find_motif(force["name"]).get("seams", False):
                # A seam motif needs its whole cell and position (spec 4.1), which `both` mode never gives.
                raise ValueError(f"seam motif {force['name']} cannot be forced in both mode")
        if settings.force_position_mode is not None and settings.force_position_mode not in POSITION_MODES:
            raise ValueError(f"unknown forced position mode: {settings.force_position_mode}")
        if settings.force_position_mode is not None and force:
            raise ValueError("force_position_mode cannot be combined with force_motif, which forces its own position")
        forced_names = list(settings.force_embellishments or ())
        unknown = [name for name in forced_names if name not in EMBELLISHMENT_ORDER]
        if unknown:
            raise ValueError(f"unknown forced embellishment(s): {unknown}")
        if len(set(forced_names)) != len(forced_names):
            raise ValueError(f"forced embellishments repeat a name: {forced_names}")
        if sum(1 for name in forced_names if name in INTERIOR_FILLS) > 1:
            raise ValueError(f"at most one interior fill may be forced, got {forced_names}")
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
        # The rings of the last plan, which a substitute reads its neighbours' current bases from.
        self._live_rings: Dict[int, RingPlan] = {}
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
        with vary a divisor of `num_divisions` in 3..8, weighted by its value. When none exists
        (11, 13, 17, 19, 22, 23) it is the largest proper divisor of at least 3 (11 for 22), or
        `num_divisions` itself for a prime, so the vary path never gives 1.
        """
        if ring_divisions:
            return math.gcd(*ring_divisions)
        if not vary_divisions:
            return num_divisions
        candidates = [d for d in range(SYMMETRY_MIN, SYMMETRY_MAX + 1) if num_divisions % d == 0]
        if not candidates:
            larger = [d for d in range(SYMMETRY_MIN, num_divisions) if num_divisions % d == 0]
            return max(larger) if larger else num_divisions
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
            self._style = {"categories": chosen, "positions": rng.choice(STYLE_POSITION_MODES)}
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
        self._live_rings = {ring.ring_index: ring for ring in rings}
        style = {**self.style, "categories": list(self.style["categories"])}
        return DesignPlan(self.seed, style, rings, symmetry)

    def plan_ring(self, ring_index: int, ring_seed: int) -> RingPlan:
        rng = node_rng(ring_seed, ring_index, 0, -1, "centre")
        divisions = self._division_count(ring_index, rng)
        seq_len = self._sequence_length(divisions, rng)
        mode, centre_share = self._position_mode(ring_index, divisions, rng)
        cell_width, ring_depth = self._ring_metrics(ring_index, divisions)
        avoid = set(self._inward_base_names(ring_index))
        # A regenerated ring also looks outward: the canonical ring there planned against the canonical ring
        # here, not this regeneration, so only this ring can keep the two from stacking seam rings.
        outward_seam = ring_seed != self.seed and self._outward_has_seam(ring_index)
        force = self.settings.force_motif if ring_index > 0 else None
        # A layered ring's fronts fill the centre position with the whole angular budget (spec 5.1).
        layered = mode == "layered"
        fill_mode = "centre" if layered else mode

        sequence: List[CellEntry] = []
        for s in range(seq_len):
            nodes: Dict[str, Optional[CellRecipe]] = {"centre": None, "divider": None}
            for position in ("centre", "divider"):
                if fill_mode not in (position, "both"):
                    continue
                width = cell_width * self._budget(fill_mode, centre_share, position)
                first = getattr(sequence[0], position) if sequence else None
                if first is not None and self._is_seam(first):
                    # A seam motif owns its whole position: every entry repeats it, freshly composed, with
                    # entry 0's embellishments so every cell draws the same seam ink.
                    nodes[position] = self._compose(
                        self._registry_entry(first), node_rng(ring_seed, ring_index, s, 0, position),
                        ring_index, ring_seed, s, position, width, ring_depth, 0,
                        embellishments=first.embellishments,
                    )
                    continue
                # Only entry 0 may pick a seam motif, and never in `both` mode (spec 4.1).
                nodes[position] = self._plan_node(
                    ring_index, ring_seed, s, position, width, ring_depth, avoid, force,
                    allow_seams=(s == 0 and fill_mode != "both" and not layered and not outward_seam),
                    layered=layered,
                )
            sequence.append(CellEntry(nodes["centre"], nodes["divider"]))

        contact_mode = self._contact_mode(ring_index, sequence)
        back = None
        if layered:
            # Layered rings always touch at base height (spec 3.2), so the fronts leave their tips free.
            touch_height, side_touch_radial = "base", rng.uniform(*BASE_TOUCH_RANGE)
            back = self._plan_back(ring_index, ring_seed, cell_width, ring_depth)
        else:
            touch_height, side_touch_radial = self._touch_height(ring_index, sequence, rng)
        if not (force and force["role"] == "contact"):
            self._ensure_contact(ring_index, sequence, contact_mode)
        plan = RingPlan(ring_index, divisions, centre_share, sequence, ring_seed,
                        contact_mode, side_touch_radial, touch_height, back=back, position_mode=mode)
        if ring_seed == self.seed:
            self._canonical_names[ring_index] = self._base_names(plan)
        return plan

    def replace_node(self, ring: RingPlan, seq_pos: int, position: str, reason: str) -> bool:
        """
        Advance one node along the fallback chain in place; False when exhausted.

        A floating base in a side-touch ring first tries another base that touches at the ring's
        height, then a stem; in other rings it gets the stem first. A stem is a contact repair that
        changes no motif, so it stays available under `force_motif`; substituting the motif or
        falling back to a safe band does not. A seam node owns its whole position, so a substitute
        or fallback for it replaces it in every sequence entry.
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
        if ring.back is not None:
            # The safe band has no fill to hide a back behind and touches at mid height only.
            self.drop_back(ring)
        safe = safe_motif(node.category)
        for target in (ring.sequence if self._is_seam(node) else [entry]):
            self._set_node(target, position, CellRecipe(safe["name"], safe["category"], is_fallback=True))
        self._refresh_contact(ring)
        return True

    def drop_back(self, ring: RingPlan) -> None:
        """
        Drop a layered ring's back for the whole ring (spec 5.4): the ring becomes a centre ring that keeps
        its front entries. Dropping it in one cell only would leave the neighbouring half's seam dangling.
        """
        ring.back = None
        ring.back_dropped = True
        ring.position_mode = "centre"

    # ---------------------------------------------------------- plan repairs

    def adopt(self, plan: DesignPlan) -> None:
        """
        Take `plan` as this composer's live plan, as `plan()` would have left it: a substitute reads its
        neighbours' current bases from its rings, and picks with its style and base symmetry.
        """
        self._live_rings = {ring.ring_index: ring for ring in plan.rings}
        self.style = {**plan.style, "categories": list(plan.style["categories"])}
        self._symmetry = plan.base_symmetry

    @staticmethod
    def _fill_allowed(node: CellRecipe, name: str) -> bool:
        """Whether `node` may take `name`: it accepts and lacks it, keeps one interior fill and no fill beside a slot child."""
        if name not in Composer._registry_entry(node).get("embellishments", ()) or name in node.embellishments:
            return False
        if name in INTERIOR_FILLS:
            return node.slot_child is None and not set(node.embellishments) & set(INTERIOR_FILLS)
        return True

    def add_embellishment(self, ring: RingPlan, position: str, node_path: Tuple[int, ...], on_back: bool,
                          name: str) -> bool:
        """
        Add embellishment `name` to the host behind a face (max-region spec 5, step 1); False when the host's
        registry entry does not accept it, the host has it, or it would give the host a second interior fill
        or a fill beside its slot child. A seam host owns its whole position, so every entry there gets it.
        """
        host = recipe_at(ring, position, node_path, on_back)
        if host is None or not self._fill_allowed(host, name):
            return False
        targets = [host]
        if not on_back and len(node_path) == 1 and self._is_seam(host):
            targets += [
                node for node in (getattr(entry, position) for entry in ring.sequence)
                if node is not None and node is not host and node.motif == host.motif
                and self._fill_allowed(node, name)
            ]
        for node in targets:
            names = set(node.embellishments) | {name}
            node.embellishments = [n for n in EMBELLISHMENT_ORDER if n in names]
        return True

    def add_slot_child(self, ring: RingPlan, position: str, node_path: Tuple[int, ...],
                       rng: random.Random) -> bool:
        """
        Give the host behind a face a slot child (max-region spec 5, step 1), picked with `rng` from the
        slot-role motifs that pass their gates at the host's `slot_estimate`, as planning nests one. False
        when the host has a slot child or an interior fill, offers no slot at its depth, or nothing fits.
        """
        host = recipe_at(ring, position, node_path)
        if host is None or host.slot_child is not None or set(host.embellishments) & set(INTERIOR_FILLS):
            return False
        depth = len(node_path) - 1
        if depth + 1 >= MAX_NODE_DEPTH:
            return False
        width_fraction = depth_fraction = 1.0
        for level in range(len(node_path)):
            estimate = self._registry_entry(recipe_at(ring, position, node_path[:level + 1]))["slot_estimate"]
            if estimate is None:
                return False
            width_fraction *= estimate[0]
            depth_fraction *= estimate[1]
        cell_width, ring_depth = self._ring_metrics(ring.ring_index, ring.divisions)
        mode = "both" if ring.centre_share < 1.0 else position
        cell_width *= self._budget(mode, ring.centre_share, position)
        candidates = [
            m for m in motifs_for_categories(self.settings.categories)
            if "slot" in m["roles"] and self._passes(m, cell_width * width_fraction, ring_depth * depth_fraction)
        ]
        if not candidates:
            return False
        chosen = self._pick(candidates, rng)
        host.slot_child = CellRecipe(chosen["name"], chosen["category"])
        return True

    def switch_to_both(self, ring: RingPlan, rng: random.Random) -> bool:
        """
        Give a centre ring a divider motif in every gap (max-region spec 5, step 2): `both` mode with a centre
        share drawn from `rng`, and a non-seam divider base per entry planned with the divider budget. False,
        changing nothing, when the ring is not in `centre` mode, is the innermost ring, has a seam base, any
        motif or position mode is forced, `both` is not eligible, a centre base no longer passes its gates at
        the narrower centre width, or no divider base fits.
        """
        if (ring.position_mode != "centre" or ring.ring_index == 0 or ring.back is not None
                or self.settings.force_motif or self.settings.force_position_mode is not None
                or any(self._is_seam(node) for node in _base_nodes(ring.sequence))
                or not self._mode_eligible("both", ring.ring_index, ring.divisions)):
            return False
        share = rng.uniform(0.45, 0.75)
        cell_width, ring_depth = self._ring_metrics(ring.ring_index, ring.divisions)
        centre_width = cell_width * self._budget("both", share, "centre")
        if any(entry.centre is None or not self._passes(self._registry_entry(entry.centre), centre_width, ring_depth)
               for entry in ring.sequence):
            return False
        divider_width = cell_width * self._budget("both", share, "divider")
        avoid = set(self._neighbour_base_names(ring.ring_index))
        dividers = [
            self._plan_node(ring.ring_index, ring.ring_seed, s, "divider", divider_width, ring_depth, avoid, None,
                            allow_seams=False)
            for s in range(len(ring.sequence))
        ]
        if any(node.is_fallback for node in dividers):
            return False
        ring.position_mode = "both"
        ring.centre_share = share
        for entry, node in zip(ring.sequence, dividers):
            entry.divider = node
        self._refresh_contact(ring)
        return True

    @staticmethod
    def raise_size_floor(ring: RingPlan) -> bool:
        """
        Redraw the ring's bases from the upper end of their size ranges (max-region spec 5, step 2): every base
        node's `size_floor` becomes `REPAIR_SIZE_FLOOR`. False when all of them already have it.
        """
        nodes = _base_nodes(ring.sequence)
        if all(node.size_floor == REPAIR_SIZE_FLOOR for node in nodes):
            return False
        for node in nodes:
            node.size_floor = REPAIR_SIZE_FLOOR
        return True

    def _substitute(self, ring: RingPlan, seq_pos: int, position: str, side_only: bool) -> bool:
        """
        Swap the node for an untried base (one touching at the ring's height, if asked); False when
        none is left.

        A seam node is the whole position, so its substitute goes into every entry, tracked and
        drawn as entry 0. A seam motif is a candidate only where it would fill the whole position
        too (a seam node, or a one-entry sequence) and never in `both` mode.
        """
        entry = ring.sequence[seq_pos]
        node = entry.centre if position == "centre" else entry.divider
        seam_position = self._is_seam(node)
        key_pos = 0 if seam_position else seq_pos
        tried = self._tried.setdefault((ring.ring_index, ring.ring_seed, key_pos, position), [])
        if node.motif not in tried:
            tried.append(node.motif)

        cell_width, ring_depth = self._ring_metrics(ring.ring_index, ring.divisions)
        mode = "both" if ring.centre_share < 1.0 else position
        cell_width *= self._budget(mode, ring.centre_share, position)
        layered = ring.back is not None
        allow_seams = mode != "both" and not layered and (seam_position or len(ring.sequence) == 1)

        candidates = self._avoiding(ring.ring_index, [
            c for c in self._base_candidates(ring.ring_index, position, cell_width, ring_depth, allow_seams)
            if c["name"] not in tried and (not side_only or ring.touch_height in touch_heights_of(c))
            and (not layered or "base" in touch_heights_of(c))
        ], self._neighbour_base_names(ring.ring_index))
        if not candidates:
            return False
        offset = 3 * len(tried)
        rng = node_rng(ring.ring_seed, ring.ring_index, key_pos, offset, position, "pick")
        chosen = self._pick(candidates, rng)
        tried.append(chosen["name"])
        targets = range(len(ring.sequence)) if seam_position or chosen.get("seams") else [seq_pos]
        # The tracked entry is composed first; a seam motif's copies carry its embellishments.
        key_node = self._compose(
            chosen, rng, ring.ring_index, ring.ring_seed, key_pos, position, cell_width, ring_depth, offset,
        )
        copied = key_node.embellishments if chosen.get("seams") else None
        for s in targets:
            new_node = key_node if s == key_pos else self._compose(
                chosen, node_rng(ring.ring_seed, ring.ring_index, s, offset, position, "pick"),
                ring.ring_index, ring.ring_seed, s, position, cell_width, ring_depth, offset,
                embellishments=copied,
            )
            self._set_node(ring.sequence[s], position, new_node)
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
                modes = STYLE_POSITION_MODES + (("layered",) if self._layered_eligible(ring_index, divisions) else ())
            weights = [0.6 if m == preferred else 0.2 for m in modes]
            mode = rng.choices(modes, weights=weights)[0]
            if mode == "both" and cell_width < BOTH_MIN_CELL_WIDTH_PX:
                mode = "centre"
            forced = self.settings.force_position_mode
            if forced and ring_index > 0 and self._mode_eligible(forced, ring_index, divisions):
                mode = forced
        centre_share = rng.uniform(0.45, 0.75) if mode == "both" else 1.0
        return mode, centre_share

    def _mode_eligible(self, mode: str, ring_index: int, divisions: int) -> bool:
        """Whether a ring past the innermost may take `mode`."""
        if mode == "layered":
            return self._layered_eligible(ring_index, divisions)
        if mode == "both":
            return self._ring_metrics(ring_index, divisions)[0] >= BOTH_MIN_CELL_WIDTH_PX
        return True

    def _layered_eligible(self, ring_index: int, divisions: int) -> bool:
        """
        A layered ring (spec 5.1) lies outside ring 0, has a back motif that passes its size gates at the
        whole cell, and a front that can touch at base height.
        """
        if ring_index == 0:
            return False
        cell_width, ring_depth = self._ring_metrics(ring_index, divisions)
        return bool(self._back_candidates(cell_width, ring_depth)
                    and self._layered_front_candidates(ring_index, cell_width, ring_depth))

    def _back_candidates(self, cell_width: float, ring_depth: float) -> List[Dict]:
        return [
            m for m in motifs_for_categories(self.settings.categories)
            if "back" in m["roles"] and self._passes(m, cell_width, ring_depth)
        ]

    def _layered_front_candidates(self, ring_index: int, cell_width: float, ring_depth: float) -> List[Dict]:
        """A layered ring's centre candidates: non-seam bases that touch at base height."""
        return [
            m for m in self._base_candidates(ring_index, "centre", cell_width, ring_depth, allow_seams=False)
            if "base" in touch_heights_of(m)
        ]

    def _plan_back(self, ring_index: int, ring_seed: int, cell_width: float, ring_depth: float) -> CellRecipe:
        """The ring's one back motif, from its own pick stream, with embellishments picked as a base's are."""
        chosen = self._pick(self._back_candidates(cell_width, ring_depth),
                            node_rng(ring_seed, ring_index, 0, 0, "divider", "pick:back"))
        back = CellRecipe(chosen["name"], chosen["category"])
        back.embellishments = self._embellishments(
            chosen, node_rng(ring_seed, ring_index, 0, 0, "divider", "pick:emb"))
        return back

    def _embellishments(self, motif: Dict, rng: random.Random) -> List[str]:
        """A node's picks (spec 6.4), with the settings' forced embellishments added where accepted."""
        picked = pick_embellishments(motif, self.settings.complexity, rng)
        return force_embellishment_picks(motif, picked, self.settings.force_embellishments or ())

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
        return tuple(sorted({node.motif for node in _base_nodes(plan.sequence)}))

    def _inward_base_names(self, ring_index: int) -> Tuple[str, ...]:
        """Base names of the canonical (design-seed) ring just inside. A ring's plan depends on the
        design seed, its own ring seed and the ring geometry; regenerating a ring can re-plan its neighbours
        because their widths absorb the change. Rebuilding from the seed plus ring_seeds is exact."""
        if ring_index == 0:
            return ()
        inner = ring_index - 1
        if inner not in self._canonical_names:
            self.plan_ring(inner, self.seed)  # records the canonical names as it plans
        return self._canonical_names[inner]

    def _outward_has_seam(self, ring_index: int) -> bool:
        """
        Whether the canonical (design-seed) ring just outside has a seam base. That ring looks only inward, at
        the canonical ring here, so planning it never recurses back, and a regeneration's plan still depends
        only on the design seed and its own ring seed. Ring 0 needs a seam base, so it never looks outward.
        """
        outer = ring_index + 1
        if ring_index == 0 or outer >= len(self.ring_geometry):
            return False
        if outer not in self._canonical_names:
            self.plan_ring(outer, self.seed)  # records the canonical names as it plans
        return any((find_motif(name) or {}).get("seams", False) for name in self._canonical_names[outer])

    def _neighbour_base_names(self, ring_index: int) -> Tuple[str, ...]:
        """
        Base names of the rings either side, for a substitute: their current bases when the composer planned
        them in its last `plan`, else the canonical names it recorded, else none.
        """
        names: set = set()
        for k in (ring_index - 1, ring_index + 1):
            if k in self._live_rings:
                names.update(self._base_names(self._live_rings[k]))
            else:
                names.update(self._canonical_names.get(k, ()))
        return tuple(sorted(names))

    @staticmethod
    def _avoiding(ring_index: int, candidates: List[Dict], avoid) -> List[Dict]:
        """
        The avoid rule. Beside a seam ring (a band or scallop), no seam motif is a candidate, even when that
        leaves none (the caller then takes its safe path): two seam rings in a row read as a stack of
        mechanical bands. A motif a neighbour uses is avoided only while another candidate is left. Ring 0
        avoids nothing: it needs a spans_cell base, and those are the seam motifs.
        """
        if ring_index == 0:
            return candidates
        if any((find_motif(name) or {}).get("seams", False) for name in avoid):
            candidates = [c for c in candidates if not c.get("seams", False)]
        return [c for c in candidates if c["name"] not in avoid] or candidates

    # ------------------------------------------------------------ node building

    def _passes(self, motif: Dict, cell_width: float, ring_depth: float) -> bool:
        width, depth = size_gates(motif, self._clearance_px())
        return width <= cell_width and depth <= ring_depth

    def _clearance_px(self) -> float:
        """The gap between two outline strokes' centrelines that leaves the white space between them."""
        # Imported here: the assembler imports this module, and owns the stroke width.
        from assembler import stroke_width_for
        return self.settings.min_pattern_size + stroke_width_for(self.settings.complexity)

    def _base_candidates(self, ring_index: int, position: str, cell_width: float,
                         ring_depth: float, allow_seams: bool = True) -> List[Dict]:
        return [
            m for m in motifs_for_categories(self.settings.categories)
            if "base" in m["roles"]
            and position in m["positions"]
            and (ring_index > 0 or m["spans_cell"])
            and (allow_seams or not m.get("seams", False))
            and self._passes(m, cell_width, ring_depth)
        ]

    def _plan_node(self, ring_index: int, ring_seed: int, seq_pos: int, position: str,
                   cell_width: float, ring_depth: float, avoid: set,
                   force: Optional[Dict[str, str]], allow_seams: bool = True, layered: bool = False) -> CellRecipe:
        rng = node_rng(ring_seed, ring_index, seq_pos, 0, position)
        if force:
            return self._forced_node(force, rng, ring_index, ring_seed, seq_pos, position,
                                     cell_width, ring_depth)
        if layered:
            candidates = self._layered_front_candidates(ring_index, cell_width, ring_depth)
        else:
            candidates = self._base_candidates(ring_index, position, cell_width, ring_depth, allow_seams)
        if ring_index > 0:
            candidates = self._avoiding(ring_index, candidates, avoid)
        if not candidates:
            safe = safe_motif(self.settings.categories[0])
            return CellRecipe(safe["name"], safe["category"], is_fallback=True)
        chosen = self._pick(candidates, node_rng(ring_seed, ring_index, seq_pos, 0, position, "pick"))
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
                 offset: int, embellishments: Optional[List[str]] = None) -> CellRecipe:
        """
        A base node: its embellishments, from their own stream so the base picks never shift, then its slot
        chain, unless an interior fill now fills the slot (spec 6.4). A seam motif's copy passes the
        `embellishments` of the entry it copies instead of picking its own.
        """
        node = CellRecipe(motif["name"], motif["category"])
        node.embellishments = list(embellishments) if embellishments is not None else self._embellishments(
            motif, node_rng(ring_seed, ring_index, seq_pos, offset, position, "pick:emb"))
        if set(node.embellishments) & set(INTERIOR_FILLS):
            return node
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
        child_rng = node_rng(ring_seed, ring_index, seq_pos, offset + depth + 1, position, "pick")
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

    def _is_seam(self, node: CellRecipe) -> bool:
        return bool(self._registry_entry(node).get("seams", False))

    def _touch_height(self, ring_index: int, sequence: List[CellEntry],
                      rng: random.Random) -> Tuple[str, float]:
        """
        The ring's touch height and side-touch radial (spec 3.2): the height drawn uniformly from
        the heights every base supports, then the radial from that height's range. A ring with no
        common height is not side-touching and keeps the mid defaults (the innermost ring included).
        """
        common = common_touch_heights([self._registry_entry(n) for n in _base_nodes(sequence)])
        if len(common) > 1:
            height = rng.choice(common)
        else:
            height = common[0] if common else "mid"
        return height, rng.uniform(*TOUCH_RANGES[height])

    def _contact_mode(self, ring_index: int, sequence: List[CellEntry],
                      height: Optional[str] = None) -> str:
        """
        How the ring reaches the structure (spec 13.2): by side touch when its bases share a touch
        height (`height` itself, when given; always in the innermost ring), else by inward overflow
        when every base has it, else stems.
        """
        if ring_index == 0:
            return "side"
        entries = [self._registry_entry(n) for n in _base_nodes(sequence)]
        common = common_touch_heights(entries)
        if (height in common) if height is not None else common:
            return "side"
        if all(entry["max_overflow_inward"] >= CONTACT_OVERFLOW for entry in entries):
            return "overflow"
        return "stem"

    def _refresh_contact(self, ring: RingPlan) -> None:
        """
        Re-flag contact after a node changed. The ring keeps its mode unless its new bases no
        longer support it (side touch at the ring's own touch height), so a revision-1 plan
        (mode "stem") keeps its revision-1 contact.

        Leaving side mode turns any once-per-wedge stem back into a per-cell one: without side
        touch the cells are no longer one band, so every repeat needs its own contact.
        """
        previous = ring.contact_mode
        current = self._contact_mode(ring.ring_index, ring.sequence, ring.touch_height)
        ring.contact_mode = _weaker_mode(previous, current)
        if previous == "side" and ring.contact_mode != "side":
            for node in _base_nodes(ring.sequence):
                for attachment in node.attachments:
                    attachment.once_per_wedge = False
        self._ensure_contact(ring.ring_index, ring.sequence, ring.contact_mode)

    def _ensure_contact(self, ring_index: int, sequence: List[CellEntry], contact_mode: str) -> None:
        """Give the ring's bases a route to the inward neighbour, as its contact mode allows, and flag them."""
        nodes = _base_nodes(sequence)
        if ring_index == 0:
            for node in nodes:
                node.provides_contact = True
            return

        def has_inward(node: CellRecipe) -> bool:
            return self._registry_entry(node)["max_overflow_inward"] >= CONTACT_OVERFLOW

        def spans(node: CellRecipe) -> bool:
            return bool(self._registry_entry(node)["spans_cell"])

        if contact_mode == "side":
            # A seam motif's open curves leave the space down to the inner ring one face per stem, so every
            # cell of a seam position gets its own stem, cutting that space into a face per cell.
            for node in nodes:
                if self._is_seam(node) and not has_inward(node) and not node.attachments:
                    node.attachments.append(self._stem_recipe())
            # Otherwise the ring is one connected band, so one inward contact per wedge is enough:
            # overflow where a base has it, else a single stem on the first node, drawn once per wedge.
            if nodes and not any(has_inward(n) or n.attachments for n in nodes):
                stem = self._stem_recipe()
                stem.once_per_wedge = True
                nodes[0].attachments.append(stem)
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
