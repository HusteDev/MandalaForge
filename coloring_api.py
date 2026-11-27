"""
Request handling for the MandalaForge /generate and /regenerate-ring endpoints, independent of any web framework.

Both front ends call these handlers with the parsed JSON body and send back the (status, body) pair they
return: app.py (the local Flask server) and the coloring.husted.dev Cloud Functions, which copy this file
from MandalaForge main together with the engine. Parameter parsing lives here and only here, so the two
can never disagree about what a request means.
"""

import logging
import random
import traceback

from coloring_generator import DesignGenerator

logger = logging.getLogger(__name__)
LOG_KEYWORD = "LOGGING"

MIN_RING_DIVISIONS = 4
MAX_RING_DIVISIONS = 24
FORCE_MOTIF_KEYS = ('name', 'position', 'role')


def _parse_ring_divisions(raw, num_rings):
    """Validate the optional per-ring division list; raises ValueError on bad input."""
    if raw is None:
        return None
    if not isinstance(raw, list) or len(raw) != num_rings:
        raise ValueError('ring_divisions must have num_rings entries')
    for count in raw:
        if (isinstance(count, bool) or not isinstance(count, int)
                or not MIN_RING_DIVISIONS <= count <= MAX_RING_DIVISIONS):
            raise ValueError(
                f'ring_divisions entries must be integers from {MIN_RING_DIVISIONS} to {MAX_RING_DIVISIONS}'
            )
    return raw


def _parse_ring_seeds(raw, num_rings):
    """Convert the JSON {"ring": seed} object to {int: int}, dropping keys outside 0..num_rings-1."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError('ring_seeds must be an object')
    message = 'ring_seeds must map ring indexes to integer seeds'
    seeds = {}
    for key, value in raw.items():
        if isinstance(key, str) and key.isascii() and key.isdigit():
            key = int(key)
        elif isinstance(key, bool) or not isinstance(key, int):
            raise ValueError(message)
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(message)
        seeds[key] = value
    return {key: value for key, value in seeds.items() if 0 <= key < num_rings}


def _parse_bool(raw, name):
    """An optional boolean: a bool, an int, or "true", "1", "false", "0", "" (any case)."""
    if raw is None:
        return False
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, int):
        return raw != 0
    if isinstance(raw, str):
        text = raw.strip().lower()
        if text in ('false', '0', ''):
            return False
        if text in ('true', '1'):
            return True
    raise ValueError(f'{name} must be a boolean')


def _parse_force_motif(raw):
    """Validate the shape of the optional {"name", "position", "role"} object."""
    if raw is None:
        return None
    if (not isinstance(raw, dict) or set(raw) != set(FORCE_MOTIF_KEYS)
            or not all(isinstance(raw[key], str) for key in FORCE_MOTIF_KEYS)):
        raise ValueError('force_motif must be an object with string name, position and role')
    return {key: raw[key] for key in FORCE_MOTIF_KEYS}


def _required_int(params, name):
    """Read a required integer field; a missing or malformed value raises ValueError."""
    try:
        return int(params.get(name))
    except (TypeError, ValueError):
        raise ValueError(f'{name} is required and must be an integer')


def _optional_seed(value):
    """An integer seed, or a random one when the value is missing or blank."""
    if value is None or str(value).strip() == '':
        return random.randint(0, 1000000)
    return int(value)


def _generator_kwargs(params, seed):
    """Parse the design parameters shared by both endpoints into DesignGenerator kwargs."""
    num_rings = int(params.get('num_rings', 4))
    categories = params.get('categories', ['botanical']) or ['botanical']
    return {
        'seed': seed,
        'num_rings': num_rings,
        'num_divisions': int(params.get('num_divisions', 12)),
        'complexity': float(params.get('complexity', 0.5)),
        'min_pattern_size': float(params.get('min_pattern_size', 8)),
        'categories': categories,
        'vary_divisions': _parse_bool(params.get('vary_divisions'), 'vary_divisions'),
        'max_region_cap': _parse_bool(params.get('max_region_cap'), 'max_region_cap'),
        'ring_divisions': _parse_ring_divisions(params.get('ring_divisions'), num_rings),
        'ring_seeds': _parse_ring_seeds(params.get('ring_seeds'), num_rings),
        'force_motif': _parse_force_motif(params.get('force_motif')),
    }


def handle_generate(params):
    """
    POST /generate. Returns (200, body), (400, {"error": string}) or (500, {"error": string}).

    Generate a mandala design based on provided parameters.

    Expected JSON body:
    {
        "seed": int or null,
        "num_rings": int (2-7),
        "num_divisions": int (4-24),
        "complexity": float (0.0-1.0),
        "min_pattern_size": float,
        "categories": list of strings,
        "vary_divisions": bool (optional, default false; also 0/1 or the strings
                          "true", "1", "false", "0", ""),
        "max_region_cap": bool (optional, default false, parsed as vary_divisions;
                          limits large regions: oversized faces are repaired so
                          each prints small enough to colour, at several times
                          the generation time),
        "ring_divisions": list of num_rings ints from 4 to 24, or null (optional),
        "ring_seeds": {"<ring index>": int} or null (optional; applies earlier
                      per-ring regenerations, keys outside the ring range are ignored),
        "force_motif": {"name": str, "position": "centre" | "divider" | "both",
                        "role": "base" | "slot" | "contact"} or null (optional; forces the
                       motif on every ring past the innermost; a retired name such as
                       "ring_band" resolves to its current motif)
    }

    Returns:
    {
        "svg": string (SVG markup),
        "params_string": string (human-readable parameters),
        "used_seed": int,
        "validation": object (validation counts and issues) or null,
        "plan": object (the design plan: rings, cells, motifs),
        "ring_seeds": {"<ring index>": int}
    }

    Invalid parameters (including bad ring_divisions) return 400 with {"error": string}.
    """
    params = params or {}
    try:
        seed = _optional_seed(params.get('seed'))
        kwargs = _generator_kwargs(params, seed)
        logger.info(
            f"[{LOG_KEYWORD}] coloring generate request: seed={seed}, num_rings={kwargs['num_rings']}, "
            f"num_divisions={kwargs['num_divisions']}, complexity={kwargs['complexity']}, "
            f"categories={kwargs['categories']}, vary_divisions={kwargs['vary_divisions']}, "
            f"max_region_cap={kwargs['max_region_cap']}"
        )
        generator = DesignGenerator(**kwargs)
        svg_output = generator.generate()
        logger.info(f"[{LOG_KEYWORD}] coloring generate succeeded: seed={seed}, svg_length={len(svg_output)}")
        return 200, {
            'svg': svg_output,
            'params_string': generator.get_params_as_string(),
            'used_seed': seed,
            'validation': generator.validation_summary(),
            'plan': generator.plan.to_dict(),
            'ring_seeds': dict(generator.ring_seeds),
        }
    except ValueError as e:
        logger.warning(f"[{LOG_KEYWORD}] coloring generate rejected parameters: {e}")
        return 400, {'error': str(e)}
    except Exception as e:
        logger.error(f"[{LOG_KEYWORD}] coloring generate failed: {e}\n{traceback.format_exc()}")
        return 500, {'error': str(e)}


def handle_regenerate_ring(params):
    """
    POST /regenerate-ring. Returns (200, body), (400, {"error": string}) or (500, {"error": string}).

    Regenerate one ring from an existing mandala parameter set.

    The main seed preserves the design. ring_seed re-plans the selected ring;
    ring_seeds carries the seeds of rings regenerated earlier so the design is
    rebuilt exactly. The selected ring's new width also moves its neighbours,
    and with the region cap on (max_region_cap, as in /generate) the repair
    ladder runs again over the whole design, so other rings' repairs
    (embellishments, size floors, re-rolls) can change too. A ring in ring_seeds is never re-rolled by the ladder.

    Expected JSON body: the /generate keys (seed is required) plus
    {
        "ring_index": int (0 to num_rings - 1),
        "ring_seed": int or null (optional; random when omitted)
    }

    Returns:
    {
        "ring_index": int,
        "ring_seed": int,
        "svg": string (the whole design, since a ring change moves its neighbours),
        "plan": object (the design plan),
        "ring_seeds": {"<ring index>": int} (prior seeds plus this one),
        "validation": object (validation counts and issues) or null
    }

    An out-of-range ring_index or invalid parameters return 400 with {"error": string}.
    """
    params = params or {}
    try:
        seed = _required_int(params, 'seed')
        ring_seed = _optional_seed(params.get('ring_seed'))
        ring_index = _required_int(params, 'ring_index')
        kwargs = _generator_kwargs(params, seed)
        num_rings = kwargs['num_rings']
        if ring_index < 0 or ring_index >= num_rings:
            raise ValueError(f'ring_index must be between 0 and {num_rings - 1}')
        logger.info(
            f"[{LOG_KEYWORD}] coloring regenerate-ring request: seed={seed}, ring_index={ring_index}, "
            f"ring_seed={ring_seed}, num_rings={num_rings}"
        )
        generator = DesignGenerator(**kwargs)
        fragment = generator.generate_ring_fragment(ring_index=ring_index, ring_seed=ring_seed)
        logger.info(
            f"[{LOG_KEYWORD}] coloring regenerate-ring succeeded: seed={seed}, ring_index={ring_index}, "
            f"svg_length={len(fragment['svg'])}"
        )
        return 200, {
            'ring_index': fragment['ring_index'],
            'ring_seed': fragment['ring_seed'],
            'svg': fragment['svg'],
            'plan': fragment['plan'].to_dict(),
            'ring_seeds': fragment['ring_seeds'],
            'validation': generator.validation_summary(),
        }
    except ValueError as e:
        logger.warning(f"[{LOG_KEYWORD}] coloring regenerate-ring rejected parameters: {e}")
        return 400, {'error': str(e)}
    except Exception as e:
        logger.error(f"[{LOG_KEYWORD}] coloring regenerate-ring failed: {e}\n{traceback.format_exc()}")
        return 500, {'error': str(e)}
