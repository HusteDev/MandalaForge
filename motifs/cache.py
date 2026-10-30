"""
A memo of motif generator calls, scoped to one design (one `DesignGenerator.generate` or `generate_from_plan`).

Every cell of a ring that holds the same sequence entry draws the same motif from the same context (a node's
seed has no cell index), and every repair trial draws its unchanged rings again, so most generator calls
repeat one already made. `MotifCache.generate` answers a repeat from the memo instead of drawing again.

It relies on one invariant: a generator is a pure function of its context. Its result, or the error it
raises, and the states it leaves both random streams in depend only on the motif and the context's fields,
with `rng` and `ring_rng` read through their states, and a generator never changes its context's fields
(docs/motifs.md, "Adding a motif"). The key holds the generator, the motif name, every other field of the
context (pickled, so floats are compared bit for bit) and the exact states of both streams. A hit returns a
deep copy of the stored instance, or raises the stored error again (same type and args), and leaves both
streams in the states the real call left them in, so a caller cannot tell a hit from a call.

The memo is never module-global: each design makes its own, so tests and concurrent requests stay apart.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import fields
import pickle
from typing import Any, Callable, Dict, Optional, Tuple

from motifs.contract import MotifInstance
from motifs.geometry import MotifContext

# The context's two random streams: the key holds their states, not the stream objects.
STREAM_FIELDS = ("rng", "ring_rng")
_KEY_FIELDS: Optional[Tuple[str, ...]] = None


def _key_fields() -> Tuple[str, ...]:
    global _KEY_FIELDS
    if _KEY_FIELDS is None:
        _KEY_FIELDS = tuple(f.name for f in fields(MotifContext) if f.name not in STREAM_FIELDS)
    return _KEY_FIELDS


def context_key(context: MotifContext) -> bytes:
    """Every field of `context` other than its two streams, as exact bytes."""
    return pickle.dumps(tuple(getattr(context, name) for name in _key_fields()), protocol=pickle.HIGHEST_PROTOCOL)


def call_generator(entry: Dict, context: MotifContext) -> MotifInstance:
    """A registry entry's generator called directly: what a design without a memo does."""
    return entry["generator"](context)


class ContextMutated(AssertionError):
    """A generator changed its context's fields (checked only when `MotifCache.verify` is on)."""


class MotifCache:
    """
    The memo of one design's generator calls. `generate(entry, context)` stands in for
    `entry["generator"](context)` exactly. With `verify` on, every real call also checks that the generator
    left its context's fields unchanged and raises `ContextMutated` when it did not (tests use it).
    """

    def __init__(self, verify: bool = False) -> None:
        self.verify = verify
        self.hits = 0
        self.misses = 0
        # key -> (instance or None, (error type, error args) or None, rng state after, ring_rng state after)
        self._entries: Dict[Tuple, Tuple[Optional[MotifInstance], Optional[Tuple[type, tuple]], Any, Any]] = {}

    def __len__(self) -> int:
        return len(self._entries)

    def generate(self, entry: Dict, context: MotifContext) -> MotifInstance:
        generator: Callable[[MotifContext], MotifInstance] = entry["generator"]
        fields_key = context_key(context)
        key = (generator, entry["name"], fields_key, context.rng.getstate(), context.ring_rng.getstate())
        stored = self._entries.get(key)
        if stored is not None:
            self.hits += 1
            instance, error, rng_state, ring_state = stored
            context.rng.setstate(rng_state)
            context.ring_rng.setstate(ring_state)
            if error is not None:
                error_type, args = error
                raise error_type(*args)
            return deepcopy(instance)

        self.misses += 1
        try:
            instance = generator(context)
        except Exception as raised:
            self._check(context, fields_key, entry)
            if self._rebuilds(raised):
                self._entries[key] = (None, (type(raised), raised.args),
                                      context.rng.getstate(), context.ring_rng.getstate())
            raise
        self._check(context, fields_key, entry)
        self._entries[key] = (deepcopy(instance), None, context.rng.getstate(), context.ring_rng.getstate())
        return instance

    def wrap(self, entry: Dict) -> Dict:
        """A copy of registry `entry` whose generator answers through this memo (for `compose_layered`)."""
        return {**entry, "generator": lambda context: self.generate(entry, context)}

    def _check(self, context: MotifContext, before: bytes, entry: Dict) -> None:
        if self.verify and context_key(context) != before:
            raise ContextMutated(f"generator of {entry['name']} changed its context")

    @staticmethod
    def _rebuilds(error: Exception) -> bool:
        """Whether `error` can be raised again from its type and args alone (else it is not stored)."""
        try:
            again = type(error)(*error.args)
        except Exception:
            return False
        return type(again) is type(error) and again.args == error.args and str(again) == str(error)
