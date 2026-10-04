"""
Flask Application for Mandala Coloring Page Generator

Routes:
- GET / : Serve the main application page
- POST /generate : Generate a mandala SVG
"""

from flask import Flask, render_template, request, jsonify
from coloring_generator import DesignGenerator
import random

app = Flask(__name__)


def validation_to_summary(validation):
    if validation is None:
        return None

    return {
        'is_valid': validation.is_valid,
        'issue_count': len(validation.issues),
        'unconnected_shape_count': len(validation.unconnected_shapes),
        'tiny_region_count': len(validation.tiny_regions),
        'issues': validation.issues[:20]
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
        "categories": list of strings
    }

    Returns:
    {
        "svg": string (SVG markup),
        "params_string": string (human-readable parameters),
        "used_seed": int
    }
    """
    params = request.get_json()

    try:
        # Parse seed
        seed_val = params.get('seed')
        if seed_val is None or str(seed_val).strip() == '':
            seed = random.randint(0, 1000000)
        else:
            seed = int(seed_val)

        # Parse other parameters
        num_rings = int(params.get('num_rings', 4))
        num_divisions = int(params.get('num_divisions', 12))
        complexity = float(params.get('complexity', 0.5))
        min_pattern_size = float(params.get('min_pattern_size', 8))

        # Parse categories (list of enabled category names)
        categories = params.get('categories', ['botanical'])
        if not categories:
            categories = ['botanical']

        print(f"[API] Generate request:")
        print(f"  Seed: {seed}")
        print(f"  Rings: {num_rings}, Divisions: {num_divisions}")
        print(f"  Complexity: {complexity}")
        print(f"  Categories: {categories}")

        # Create generator
        generator = DesignGenerator(
            seed=seed,
            num_rings=num_rings,
            num_divisions=num_divisions,
            complexity=complexity,
            min_pattern_size=min_pattern_size,
            categories=categories
        )

        # Generate SVG
        svg_output = generator.generate()
        params_string = generator.get_params_as_string()
        validation_summary = validation_to_summary(generator.last_validation_result)

        print(f"[API] Generated SVG: {len(svg_output)} characters")

        return jsonify({
            'svg': svg_output,
            'params_string': params_string,
            'used_seed': seed,
            'validation': validation_summary,
            'pattern_usage': generator.pattern_usage
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/regenerate-ring', methods=['POST'])
def regenerate_ring():
    """
    Regenerate one ring from an existing mandala parameter set.

    The main seed preserves ring geometry. ring_seed changes only the selected
    ring pattern and its variation choices.
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
        num_rings = int(params.get('num_rings', 4))
        num_divisions = int(params.get('num_divisions', 12))
        complexity = float(params.get('complexity', 0.5))
        min_pattern_size = float(params.get('min_pattern_size', 8))

        categories = params.get('categories', ['botanical'])
        if not categories:
            categories = ['botanical']

        if ring_index < 0 or ring_index >= num_rings:
            return jsonify({'error': f'ring_index must be between 0 and {num_rings - 1}'}), 400

        print(f"[API] Regenerate ring request:")
        print(f"  Seed: {seed}")
        print(f"  Ring seed: {ring_seed}")
        print(f"  Ring index: {ring_index}")

        generator = DesignGenerator(
            seed=seed,
            num_rings=num_rings,
            num_divisions=num_divisions,
            complexity=complexity,
            min_pattern_size=min_pattern_size,
            categories=categories
        )

        fragment = generator.generate_ring_fragment(
            ring_index=ring_index,
            ring_seed=ring_seed
        )

        return jsonify({
            **fragment,
            'validation': validation_to_summary(generator.last_validation_result)
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
