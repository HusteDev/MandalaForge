"""
Flask Application for Mandala Coloring Page Generator

Routes:
- GET / : Serve the main application page
- POST /generate : Generate a mandala SVG
- POST /regenerate-ring : Regenerate one ring of an existing design
"""

from flask import Flask, render_template, request, jsonify
from coloring_generator import DesignGenerator
import random

app = Flask(__name__)

MIN_RING_DIVISIONS = 4
MAX_RING_DIVISIONS = 24


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
    """
    Convert the JSON {"ring": seed} object to {int: int}.

    Keys outside 0..num_rings-1 are dropped so a stale map from a larger
    earlier design does not break the request.
    """
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError('ring_seeds must be an object')
    seeds = {int(key): int(value) for key, value in raw.items()}
    return {key: value for key, value in seeds.items() if 0 <= key < num_rings}


def _generator_kwargs(params, seed):
    """Parse the design parameters shared by both routes into DesignGenerator kwargs."""
    num_rings = int(params.get('num_rings', 4))

    categories = params.get('categories', ['botanical'])
    if not categories:
        categories = ['botanical']

    return {
        'seed': seed,
        'num_rings': num_rings,
        'num_divisions': int(params.get('num_divisions', 12)),
        'complexity': float(params.get('complexity', 0.5)),
        'min_pattern_size': float(params.get('min_pattern_size', 8)),
        'categories': categories,
        'vary_divisions': bool(params.get('vary_divisions', False)),
        'ring_divisions': _parse_ring_divisions(params.get('ring_divisions'), num_rings),
        'ring_seeds': _parse_ring_seeds(params.get('ring_seeds'), num_rings),
    }


@app.route('/')
def index():
    """Serve the main application page."""
    return render_template('index.html')


@app.route('/generate', methods=['POST'])
def generate():
    """
    Generate a mandala design based on provided parameters.

    Expected JSON body:
    {
        "seed": int or null,
        "num_rings": int (2-7),
        "num_divisions": int (4-30, even),
        "complexity": float (0.0-1.0),
        "min_pattern_size": float,
        "categories": list of strings,
        "vary_divisions": bool (optional, default false),
        "ring_divisions": list of num_rings ints from 4 to 24, or null (optional),
        "ring_seeds": {"<ring index>": int} or null (optional; applies earlier
                      per-ring regenerations, keys outside the ring range are ignored)
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
    params = request.get_json()

    try:
        # Parse seed
        seed_val = params.get('seed')
        if seed_val is None or str(seed_val).strip() == '':
            seed = random.randint(0, 1000000)
        else:
            seed = int(seed_val)

        kwargs = _generator_kwargs(params, seed)

        print(f"[API] Generate request:")
        print(f"  Seed: {seed}")
        print(f"  Rings: {kwargs['num_rings']}, Divisions: {kwargs['num_divisions']}")
        print(f"  Complexity: {kwargs['complexity']}")
        print(f"  Categories: {kwargs['categories']}")

        generator = DesignGenerator(**kwargs)

        # Generate SVG
        svg_output = generator.generate()

        print(f"[API] Generated SVG: {len(svg_output)} characters")

        return jsonify({
            'svg': svg_output,
            'params_string': generator.get_params_as_string(),
            'used_seed': seed,
            'validation': generator.validation_summary(),
            'plan': generator.plan.to_dict(),
            'ring_seeds': dict(generator.ring_seeds)
        })

    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/regenerate-ring', methods=['POST'])
def regenerate_ring():
    """
    Regenerate one ring from an existing mandala parameter set.

    The main seed preserves the design. ring_seed changes only the selected
    ring's plan; ring_seeds carries the seeds of rings regenerated earlier so
    the design is rebuilt exactly.

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
    params = request.get_json()

    try:
        seed = int(params.get('seed'))
        ring_seed_val = params.get('ring_seed')
        if ring_seed_val is None or str(ring_seed_val).strip() == '':
            ring_seed = random.randint(0, 1000000)
        else:
            ring_seed = int(ring_seed_val)

        ring_index = int(params.get('ring_index'))
        kwargs = _generator_kwargs(params, seed)
        num_rings = kwargs['num_rings']

        if ring_index < 0 or ring_index >= num_rings:
            return jsonify({'error': f'ring_index must be between 0 and {num_rings - 1}'}), 400

        print(f"[API] Regenerate ring request:")
        print(f"  Seed: {seed}")
        print(f"  Ring seed: {ring_seed}")
        print(f"  Ring index: {ring_index}")

        generator = DesignGenerator(**kwargs)

        fragment = generator.generate_ring_fragment(
            ring_index=ring_index,
            ring_seed=ring_seed
        )

        return jsonify({
            'ring_index': fragment['ring_index'],
            'ring_seed': fragment['ring_seed'],
            'svg': fragment['svg'],
            'plan': fragment['plan'].to_dict(),
            'ring_seeds': fragment['ring_seeds'],
            'validation': generator.validation_summary()
        })

    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    # PORT is honoured so the app can run alongside anything already on 5000.
    import os

    app.run(debug=True, port=int(os.environ.get('PORT', 5000)))
