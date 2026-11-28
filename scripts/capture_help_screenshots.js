/**
 * Re-captures the screenshots used by the "How to use" slideshow (static/help/).
 *
 * Start the app first (python app.py), then run:
 *   node scripts/capture_help_screenshots.js [http://localhost:5000/]
 *
 * Needs Node with the playwright package. Firebase is stubbed so the page
 * takes its localhost path and the shots do not show a signed-in email.
 */
const path = require('path');
const { chromium } = require('playwright');
const OUT = path.join(__dirname, '..', 'static', 'help') + path.sep;
const URL = process.argv[2] || 'http://localhost:5000/';
const STUB = `window.firebase={initializeApp(){},auth(){return{onAuthStateChanged(cb){setTimeout(()=>cb(null),0)},signOut(){return Promise.resolve()}}}};`;

(async () => {
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: 1280, height: 960 }, deviceScaleFactor: 1 });
  await p.route('https://www.gstatic.com/**', r => r.fulfill({ contentType: 'text/javascript',
    body: r.request().url().includes('firebase-app-compat') ? STUB : '' }));
  await p.route('https://shared-public.web.app/**', r => r.fulfill({ status: 404, body: '' }));
  const gen = () => p.waitForResponse(r => /generate|regenerate-ring/.test(r.url()), { timeout: 180000 });

  const first = gen();
  await p.goto(URL);
  // Wait out the check-result note that pops up over the preview after each design
  await first; await p.waitForTimeout(2400);

  // Draw an orange outline around each element (selector strings or handles)
  const box = (targets) => p.evaluate((targets) => {
    document.querySelectorAll('.__hl').forEach(e => e.parentNode.removeChild(e));
    for (const t of targets) {
      const el = typeof t === 'string' ? document.querySelector(t) : t;
      if (!el) { console.log('missing', t); continue; }
      const r = el.getBoundingClientRect();
      const d = document.createElement('div'); d.className = '__hl';
      Object.assign(d.style, { position: 'fixed', left: (r.left - 5) + 'px', top: (r.top - 5) + 'px',
        width: (r.width + 10) + 'px', height: (r.height + 10) + 'px', border: '3px solid #ff7a00',
        borderRadius: '8px', boxShadow: '0 0 0 4px rgba(255,122,0,0.25)', pointerEvents: 'none',
        zIndex: 99999, boxSizing: 'border-box' });
      document.body.appendChild(d);
    }
  }, targets);
  const shot = async (name) => { await p.waitForTimeout(300); await p.screenshot({ path: OUT + name, type: 'jpeg', quality: 82 }); };
  const scrollCtl = (y) => p.evaluate(y => { document.querySelector('.controls-container').scrollTop = y; }, y);
  const scrollTo = (sel) => p.evaluate(sel => {
    const c = document.querySelector('.controls-container'); const el = document.querySelector(sel);
    const stickyBottom = document.querySelector('.sticky-actions').getBoundingClientRect().bottom;
    c.scrollTop += el.getBoundingClientRect().top - stickyBottom - 14;
  }, sel);
  const setRings = (v) => p.evaluate(v => { const s = document.getElementById('num-rings'); s.value = v; s.dispatchEvent(new Event('input', { bubbles: true })); }, v);

  await box([]); await shot('step-1-overview.jpg');

  await setRings(5);
  await scrollTo('[data-section="size"]');
  await box(['[data-section="size"]']); await shot('step-2-settings.jpg');

  await setRings(4);
  await p.check('#cat-geometric');
  await scrollTo('[data-section="categories"]');
  await box(['[data-section="categories"]']); await shot('step-3-categories.jpg');

  await scrollCtl(0); await box([]);
  const g = gen(); await p.click('#generate-btn'); await g; await p.waitForTimeout(400);
  await box(['.action-row']); await shot('step-4-generate.jpg');

  await box([]);
  await p.click('.ring-select-btn:nth-child(2)'); await p.waitForTimeout(300);
  await box(['[data-section="rings"]']); await shot('step-5-ring.jpg');

  await box([]);
  await p.click('#zoom-in'); await p.click('#zoom-in'); await p.waitForTimeout(300);
  await box(['.preview-controls']); await shot('step-6-zoom.jpg');

  await box([]); await p.click('#fit-to-page');
  await p.click('#save-btn'); await p.waitForTimeout(1300);
  await p.evaluate(() => { const c = document.querySelector('.controls-container'); c.scrollTop = c.scrollHeight; });
  await p.hover('.gallery-item');
  await box(['#save-btn', '.gallery']); await shot('step-7-save.jpg');

  await scrollCtl(0); await p.check('#include-params-check');
  await box(['#print-btn', '.sticky-actions .checkbox-group']); await shot('step-8-print.jpg');

  await b.close();
})();
