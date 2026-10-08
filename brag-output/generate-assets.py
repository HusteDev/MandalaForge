"""Capture genuine project output for the launch film; no application edits."""
import contextlib
import io
import json
import sys
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import app

OUT = Path(__file__).parent / 'composition' / 'assets'
OUT.mkdir(parents=True, exist_ok=True)
client = app.test_client()
records = []
for seed, categories in [(42, ['botanical']), (2025, ['botanical', 'geometric']), (108, ['art_deco', 'botanical'])]:
    params = dict(seed=seed, num_rings=4, num_divisions=12, complexity=0.5,
                  min_pattern_size=10, categories=categories)
    log = io.StringIO()
    with contextlib.redirect_stdout(log):
        response = client.post('/generate', json=params)
    (OUT / f'generate-{seed}.log').write_text(log.getvalue(), encoding='utf-8')
    if response.status_code != 200:
        raise RuntimeError(response.get_json())
    data = response.get_json()
    (OUT / f'mandala-{seed}.svg').write_text(data['svg'], encoding='utf-8')
    # Base motif per ring: the first sequence entry's centre recipe, else its divider.
    pattern_usage = []
    for ring in data['plan']['rings']:
        entry = ring['sequence'][0]
        recipe = entry['centre'] or entry['divider']
        pattern_usage.append(dict(ring_index=ring['ring_index'], variation_index=0,
                                  name=recipe['motif'], category=recipe['category'],
                                  is_fallback=recipe['is_fallback']))
    record = dict(params=params, validation=data['validation'], pattern_usage=pattern_usage)
    records.append(record)
    print(json.dumps(dict(seed=seed, validation=data['validation'])))
    if seed == 42:
        with contextlib.redirect_stdout(log):
            replacement = client.post('/regenerate-ring', json={**params, 'ring_index': 2, 'ring_seed': 2026})
        if replacement.status_code != 200:
            raise RuntimeError(replacement.get_json())
        fragment = replacement.get_json()
        (OUT / 'ring-response.json').write_text(json.dumps(fragment, indent=2), encoding='utf-8')
        ns = {'s': 'http://www.w3.org/2000/svg'}
        ET.register_namespace('', ns['s'])
        ET.register_namespace('xlink', 'http://www.w3.org/1999/xlink')
        root = ET.fromstring(data['svg'])
        defs = root.find('s:defs', ns)
        wrap = ET.fromstring('<svg xmlns="http://www.w3.org/2000/svg">' + fragment['defs_svg'] + '</svg>')
        replacement_ids = {el.get('id') for el in wrap}
        for el in list(defs):
            if el.get('id') in replacement_ids:
                defs.remove(el)
        for el in wrap:
            defs.append(el)
        parent = root.find("s:g[@id='mandala']", ns)
        old = parent.find("s:g[@id='ring-2']", ns)
        idx = list(parent).index(old)
        parent.remove(old)
        fragment_wrapper = ET.fromstring('<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">' + fragment['ring_svg'] + '</svg>')
        parent.insert(idx, fragment_wrapper[0])
        (OUT / 'mandala-42-reroll.svg').write_text(ET.tostring(root, encoding='unicode'), encoding='utf-8')
        record['ring_regeneration'] = dict(index=2, seed=2026, status=replacement.status_code)

(OUT / 'source-evidence.json').write_text(json.dumps(records, indent=2), encoding='utf-8')
