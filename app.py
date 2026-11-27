"""
Flask Application for Mandala Coloring Page Generator

Routes:
- GET / : Serve the main application page
- POST /generate : Generate a mandala SVG
- POST /regenerate-ring : Regenerate one ring of an existing design

The request parsing and responses live in coloring_api.py, which coloring.husted.dev's Cloud Functions
also use, so this file only adapts those handlers to Flask. See coloring_api.handle_generate and
coloring_api.handle_regenerate_ring for the request and response formats.
"""

import logging

from flask import Flask, render_template, request, jsonify

from coloring_api import handle_generate, handle_regenerate_ring

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')

app = Flask(__name__)


@app.route('/')
def index():
    """Serve the main application page."""
    return render_template('index.html')


@app.route('/generate', methods=['POST'])
def generate():
    """Generate a mandala design; see coloring_api.handle_generate."""
    status, body = handle_generate(request.get_json(silent=True))
    return jsonify(body), status


@app.route('/regenerate-ring', methods=['POST'])
def regenerate_ring():
    """Regenerate one ring of an existing design; see coloring_api.handle_regenerate_ring."""
    status, body = handle_regenerate_ring(request.get_json(silent=True))
    return jsonify(body), status


if __name__ == '__main__':
    # PORT is honoured so the app can run alongside anything already on 5000.
    import os

    app.run(debug=True, port=int(os.environ.get('PORT', 5000)))
