from pathlib import Path
import re
import json

HERE = Path(__file__).parent
COMP = HERE / 'composition'

def svg_asset(filename, prefix):
    svg = (COMP / 'assets' / filename).read_text(encoding='utf-8')
    ids = re.findall(r'\bid="([^"]+)"', svg)
    for old in sorted(ids, key=len, reverse=True):
        svg = svg.replace(f'id="{old}"', f'id="{prefix}-{old}"')
        svg = svg.replace(f'"#{old}"', f'"#{prefix}-{old}"')
    svg = svg.replace('width="612"', 'width="100%"').replace('height="612"', 'height="100%"')
    return svg.replace('<svg ', '<svg viewBox="0 0 612 612" aria-hidden="true" ', 1)

template = r'''<!doctype html>
<html lang="en" data-resolution="landscape">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=1920, height=1080">
<title>MandalaForge — One seed. Your pattern.</title>
<script src="assets/gsap.min.js"></script>
<style>
@font-face{font-family:'Forge Sans';src:url('assets/fonts/segoeui.ttf') format('truetype');font-weight:400}
@font-face{font-family:'Forge Sans';src:url('assets/fonts/segoeuib.ttf') format('truetype');font-weight:700}
*{box-sizing:border-box}html,body{margin:0;width:1920px;height:1080px;overflow:hidden;background:#f0f2f5;color:#333}
body{font-family:'Forge Sans',sans-serif}#root{position:relative;width:100%;height:100%;overflow:hidden;background:#f0f2f5}
.clip{position:absolute;inset:0}.brand{position:absolute;left:112px;top:69px;display:flex;align-items:center;gap:18px;font-size:32px;font-weight:700;letter-spacing:-1px}
.brand-mark{width:38px;height:38px;border:2px solid #007bff;border-radius:50%;position:relative}
.brand-mark:before,.brand-mark:after{content:'';position:absolute;inset:6px;border:2px solid #007bff;border-radius:50%}.brand-mark:after{inset:13px;background:#007bff}
.edition{position:absolute;right:112px;top:80px;font-size:23px;color:#555e6a;letter-spacing:2px}
.bottom-rule{position:absolute;left:112px;right:112px;bottom:80px;height:2px;background:#cbd1d9}
.bottom-note{position:absolute;left:112px;bottom:32px;font-size:23px;color:#555e6a}
.scene-count{position:absolute;right:112px;bottom:32px;font-size:23px;color:#555e6a}
.blue{color:#0056b3}.eyebrow{font-size:25px;letter-spacing:3px;text-transform:uppercase;color:#0056b3;font-weight:700}
.hook-copy{position:absolute;left:112px;top:337px;width:750px}.headline{margin:24px 0 0;font-size:112px;font-weight:700;line-height:1.08;letter-spacing:-6px}
.headline span{display:block}.support{margin-top:32px;font-size:30px;line-height:1.45;color:#555e6a;max-width:650px}
.hero-drawing{position:absolute;left:941px;top:156px;width:817px;height:817px;transform-origin:center}
.hero-disc{position:absolute;inset:0;background:#fff;border-radius:50%;box-shadow:0 18px 56px #233a5210}
.hero-svg{position:absolute;inset:8px}.hero-svg svg{display:block;width:100%;height:100%}
.hook-label{position:absolute;right:162px;top:159px;font-size:22px;color:#555e6a}
.workspace-heading{position:absolute;left:112px;top:155px;font-size:65px;letter-spacing:-2.8px;font-weight:700;margin:0}
.workspace-sub{position:absolute;right:112px;top:185px;font-size:25px;color:#555e6a}
.workbench{position:absolute;left:112px;top:271px;width:1696px;height:688px;display:flex;border:2px solid #d7dce3;border-radius:16px;background:#e5e9ef;overflow:hidden;box-shadow:0 16px 36px #1c355010}
.control-panel{position:relative;width:434px;height:100%;padding:29px 32px;background:#fff;border-right:2px solid #d7dce3}
.app-title{font-size:27px;line-height:1.15;font-weight:700;color:#0056b3;padding-bottom:20px;border-bottom:2px solid #dde2e8;margin:0 0 21px}
.field{display:flex;justify-content:space-between;align-items:center;font-size:26px;margin:14px 0}.field b{font-size:29px;font-weight:700}
.slider{height:5px;background:#dbe1e8;position:relative;margin:7px 0 20px}.slider-fill{position:absolute;left:0;top:0;width:46%;height:5px;background:#007bff}.knob{position:absolute;left:44%;top:-7px;width:19px;height:19px;border-radius:50%;background:#007bff}
.settings-row{display:flex;gap:12px;margin:21px 0 18px}.seed-field{width:106px;border:2px solid #ccd4de;border-radius:6px;padding:8px 12px;font-size:25px;line-height:1.2}.seed-field span{display:block;font-size:19px;color:#555e6a;margin-bottom:4px}.category{display:flex;gap:9px;align-items:center;font-size:25px;padding-left:10px}.checkmark{width:22px;height:22px;background:#0056b3;color:#fff;border-radius:3px;font-size:19px;display:flex;justify-content:center;align-items:center}
.button{height:56px;display:flex;align-items:center;justify-content:center;background:#007bff;color:#fff;border-radius:6px;font-size:26px;font-weight:700;transform-origin:center}
.ring-buttons{display:flex;gap:8px;margin:22px 0 12px}.ring-button{flex:1;background:#f0f2f5;border:2px solid #d7dce3;border-radius:5px;color:#333;font-size:21px;text-align:center;padding:8px 0}
.secondary{background:#fff;border:2px solid #007bff;color:#0056b3;font-size:25px}.print{margin-top:12px;background:#f0f2f5;color:#333;height:45px;font-size:24px}
.canvas-area{position:relative;flex:1;display:flex;align-items:center;justify-content:center}.paper{width:618px;height:618px;background:#fff;box-shadow:0 8px 20px #172d4315;position:relative}
.drawing{position:absolute;inset:16px}.drawing svg{width:100%;height:100%;display:block}.paper-empty{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;color:#6d7682;font-size:26px}
.canvas-meta{position:absolute;right:23px;bottom:20px;color:#555e6a;font-size:19px}
.ring-overlay{position:absolute;inset:16px}.ring-overlay svg{width:100%;height:100%;display:block}
.ring-note{position:absolute;right:42px;top:44px;width:170px;color:#0056b3;font-size:25px;font-weight:700;line-height:1.3}
.cursor{position:absolute;left:0;top:0;width:44px;height:56px;z-index:10;filter:drop-shadow(0 3px 2px #11223322)}
.cursor svg{width:100%;height:100%}.click-pulse{position:absolute;width:66px;height:66px;border:3px solid #007bff;border-radius:50%;left:0;top:0;z-index:9}
.outro-copy{position:absolute;left:112px;top:325px;width:775px}.outro-headline{font-size:98px;line-height:1.08;letter-spacing:-4.5px;margin:24px 0 0;font-weight:700}.outro-headline span{display:block}
.outro-brand{font-size:52px;font-weight:700;letter-spacing:-2px;margin-top:40px;color:#0056b3}.outro-tagline{font-size:30px;margin-top:18px;color:#555e6a}
.print-sheet{position:absolute;left:1050px;top:189px;width:621px;height:713px;background:#fff;box-shadow:0 18px 55px #213e5726;transform-origin:50% 50%;padding:30px}
.print-sheet svg{width:561px;height:561px;display:block}.sheet-caption{position:absolute;left:30px;right:30px;bottom:38px;font-size:24px;color:#555e6a;text-align:center}
.sheet-back{position:absolute;left:1070px;top:206px;width:621px;height:713px;background:#fafbfc;border:1px solid #d7dce3;transform:rotate(5deg)}
</style></head>
<body><div id="root" data-composition-id="mandalaforge" data-width="1920" data-height="1080" data-start="0" data-duration="21">
<div class="brand"><span class="brand-mark"></span>MandalaForge</div><div class="edition">PATTERN / POSSIBILITY</div>
<div class="bottom-rule"></div>

<section class="clip" id="hook" data-start="0" data-duration="3.7" data-track-index="1">
  <div class="hook-copy"><div class="eyebrow">A coloring page, made by you</div><h1 class="headline"><span id="hook-line-one">One seed.</span><span id="hook-line-two" class="blue">Your pattern.</span></h1><div class="support">Procedural mandalas.<br>Room for your imagination.</div></div>
  <div class="hero-drawing"><div class="hero-disc"></div><div class="hero-svg">__HOOK_SVG__</div></div>
  <div class="bottom-note">GENERATE / REFINE / PRINT</div><div class="scene-count">01 / 04</div>
</section>

<section class="clip" id="workspace" data-start="3.7" data-duration="11.3" data-track-index="1">
 <h2 id="generate-heading" class="workspace-heading">Set the structure.</h2><h2 id="refine-heading" class="workspace-heading">Change one ring.</h2>
 <div class="workspace-sub" id="generate-sub">A few choices. A new design.</div><div class="workspace-sub" id="refine-sub">Keep the rest.</div>
 <div class="workbench">
  <div class="control-panel">
   <div class="app-title">Kristie's Coloring<br>Page Generator</div>
   <div class="field"><span>Rings</span><b>4</b></div><div class="slider"><div class="slider-fill"></div><div class="knob"></div></div>
   <div class="field"><span>Divisions</span><b>12</b></div><div class="slider"><div class="slider-fill"></div><div class="knob"></div></div>
   <div class="settings-row"><div class="seed-field"><span>Seed</span>42</div><div class="category"><span class="checkmark">✓</span>Botanical</div></div>
   <div class="button" id="generate-button">Generate</div>
   <div class="ring-buttons"><div class="ring-button">Ring 1</div><div class="ring-button">Ring 2</div><div class="ring-button" id="ring-three">Ring 3</div><div class="ring-button">Ring 4</div></div>
   <div class="button secondary" id="regenerate-button">Regenerate Ring</div>
   <div class="button print" id="print-button">Print</div>
  </div>
  <div class="canvas-area"><div class="paper"><div class="paper-empty">Your next coloring page</div><div class="drawing original-drawing">__ORIGINAL_SVG__</div><div class="drawing revised-drawing">__REVISED_SVG__</div><div class="ring-overlay"><svg viewBox="0 0 612 612"><circle cx="306" cy="306" r="189" stroke="#007bff" stroke-width="65" opacity=".15" fill="none"/><circle cx="306" cy="306" r="156" stroke="#007bff" stroke-width="2" stroke-dasharray="5 5" fill="none"/><circle cx="306" cy="306" r="222" stroke="#007bff" stroke-width="2" stroke-dasharray="5 5" fill="none"/></svg></div></div><div class="canvas-meta">12 repeating sections</div><div class="ring-note">Ring 3<br>selected</div></div>
 </div>
 <div class="click-pulse"></div><div class="cursor"><svg viewBox="0 0 44 56"><path d="M4 3 L4 43 L15 33 L24 51 L32 47 L23 29 L39 28 Z" fill="#333" stroke="#fff" stroke-width="3" stroke-linejoin="round"/></svg></div>
 <div class="bottom-note" id="work-note-one">YOUR SETTINGS → YOUR DESIGN</div><div class="bottom-note" id="work-note-two">ONE RING → A DIFFERENT RHYTHM</div><div class="scene-count">02—03 / 04</div>
</section>

<section class="clip" id="outro" data-start="15" data-duration="6" data-track-index="1">
 <div class="outro-copy"><div class="eyebrow">From possibility to paper</div><h2 class="outro-headline"><span>Made to be</span><span class="blue">colored.</span></h2><div class="outro-brand">MandalaForge</div><div class="outro-tagline">Generate. Refine. Print.</div></div>
 <div class="sheet-back"></div><div class="print-sheet">__PRINT_SVG__<div class="sheet-caption">Your pattern. Your palette.</div></div>
 <div class="bottom-note">PROCEDURAL MANDALA COLORING PAGES</div><div class="scene-count">04 / 04</div>
</section>
<audio id="music-bed" src="assets/music/happy-beats-business-moves-vol-11-by-ende-dot-app.mp3" data-start="0" data-duration="21" data-track-index="4" data-volume="0.28" data-automation="{&quot;version&quot;:1,&quot;lanes&quot;:[{&quot;target&quot;:&quot;volume&quot;,&quot;points&quot;:[{&quot;t&quot;:0,&quot;v&quot;:0},{&quot;t&quot;:0.45,&quot;v&quot;:0.28},{&quot;t&quot;:19.5,&quot;v&quot;:0.28},{&quot;t&quot;:21,&quot;v&quot;:0}]}]}"></audio>
<audio id="sfx-generate" src="assets/sfx/click2.ogg" data-start="5.8" data-duration="0.1" data-track-index="5" data-volume="0.34"></audio>
<audio id="sfx-select" src="assets/sfx/click2.ogg" data-start="10.54" data-duration="0.1" data-track-index="5" data-volume="0.30"></audio>
<audio id="sfx-regenerate" src="assets/sfx/click2.ogg" data-start="12.12" data-duration="0.1" data-track-index="5" data-volume="0.34"></audio>
<audio id="sfx-print" src="assets/sfx/card-slide-1.ogg" data-start="15" data-duration="0.5" data-track-index="5" data-volume="0.22"></audio>
</div>
<script>
const tl = gsap.timeline({paused:true});
// SVG stroke measurement adapted from the installed svg-stroke-trace primitive.
// The project's actual paths retain their geometry; no visual fill is added.
document.querySelectorAll('.hero-svg path, .hero-svg circle').forEach((path, i)=>{
  const length = path.getTotalLength();
  path.style.strokeDasharray = length+' '+length;
  path.style.strokeDashoffset = length;
  tl.to(path,{strokeDashoffset:0,duration:1.45,ease:'sine.inOut'},0.1+(i%7)*0.06);
});
tl.fromTo('.hero-drawing',{scale:0.92,rotation:-8},{scale:1,rotation:0,duration:2.4,ease:'power2.out'},0);
tl.fromTo('#hook-line-one',{y:30,opacity:0},{y:0,opacity:1,duration:0.45,ease:'power3.out'},0.05);
tl.fromTo('#hook-line-two',{y:36,opacity:0},{y:0,opacity:1,duration:0.5,ease:'power3.out'},0.22);
tl.fromTo('.hook-copy .eyebrow, .hook-copy .support',{opacity:0},{opacity:1,duration:0.45,stagger:0.16},0.28);
tl.to('.hook-copy, .hero-drawing',{opacity:0,duration:0.2},3.5);

tl.fromTo('.workbench',{y:30,opacity:0},{y:0,opacity:1,duration:0.5,ease:'power3.out'},3.7);
tl.fromTo('#generate-heading, #generate-sub',{y:16,opacity:0},{y:0,opacity:1,duration:0.42,ease:'power3.out'},3.7);
tl.set('#refine-heading, #refine-sub, #work-note-two, .revised-drawing, .ring-overlay, .ring-note',{opacity:0},0);
tl.set('.original-drawing',{opacity:0},0);
tl.set('.cursor',{x:644,y:874,opacity:0},0);
tl.set('.click-pulse',{opacity:0},0);
tl.to('.cursor',{opacity:1,duration:0.15},4.75);
tl.to('.cursor',{x:329,y:681,duration:0.68,ease:'power2.inOut'},4.95);
// beat-locked: Generate press at 5.80s.
tl.to('#generate-button',{scale:0.965,duration:0.10,yoyo:true,repeat:1,ease:'power2.inOut'},5.8);
tl.to('.paper-empty',{opacity:0,duration:0.18},5.8);
tl.to('.original-drawing',{opacity:1,duration:0.18},5.85);
// beat-grid: rings reveal at 5.80, 6.34, 6.86, 7.38s. These are geometry, not reading beats.
[5.80,6.34,6.86,7.38].forEach((time,i)=>tl.fromTo('#demo-ring-'+i,{opacity:0},{opacity:1,duration:0.38,ease:'power2.out'},time));
tl.to('.cursor',{opacity:0,duration:0.2},7.7);
tl.to('#generate-heading, #generate-sub, #work-note-one',{opacity:0,duration:0.18},8.82);
tl.fromTo('#refine-heading, #refine-sub',{opacity:0,y:18},{opacity:1,y:0,duration:0.4,ease:'power3.out',immediateRender:false},9);
tl.to('#work-note-two',{opacity:1,duration:0.3},9);
tl.set('.cursor',{x:329,y:681},9.5);
tl.to('.cursor',{opacity:1,duration:0.15},9.5);
tl.to('.cursor',{x:369,y:752,duration:0.5,ease:'power2.inOut'},9.85);
tl.to('#ring-three',{backgroundColor:'#007bff',color:'#fff',borderColor:'#007bff',duration:0.15},10.54);
tl.to('.ring-overlay, .ring-note',{opacity:1,duration:0.25},10.54);
tl.to('.cursor',{x:329,y:817,duration:0.5,ease:'power2.inOut'},11.48);
tl.to('#regenerate-button',{scale:0.965,duration:0.1,yoyo:true,repeat:1},12.12);
tl.to('.ring-overlay, .ring-note',{opacity:0,duration:0.22},12.25);
// beat-locked: real replacement fragment becomes visible at 12.65s.
tl.to('.revised-drawing',{opacity:1,duration:0.28,ease:'power2.out'},12.65);
tl.to('.original-drawing',{opacity:0,duration:0.28},12.65);
tl.to('.cursor',{opacity:0,duration:0.18},12.95);
tl.set('.cursor',{x:329,y:817},13.6);
tl.to('.cursor',{opacity:1,duration:0.1},13.6);
tl.to('.cursor',{x:329,y:880,duration:0.5,ease:'power2.inOut'},13.7);
tl.to('#print-button',{backgroundColor:'#dceaff',scale:0.975,duration:0.13,yoyo:true,repeat:1},14.22);
tl.to('.workbench, #refine-heading, #refine-sub, .cursor',{opacity:0,duration:0.2},14.8);

tl.fromTo('.print-sheet',{x:125,y:22,rotation:4,opacity:0},{x:0,y:0,rotation:-3,opacity:1,duration:0.85,ease:'power3.out'},15);
tl.fromTo('.sheet-back',{x:120,opacity:0},{x:0,opacity:1,duration:0.85,ease:'power3.out'},15.08);
tl.fromTo('.outro-copy .eyebrow, .outro-headline',{y:22,opacity:0},{y:0,opacity:1,duration:0.5,stagger:0.12,ease:'power3.out'},15.2);
// beat-locked: closing identity lands at 17.91s.
tl.fromTo('.outro-brand',{x:-22,opacity:0},{x:0,opacity:1,duration:0.42,ease:'power3.out'},17.91);
tl.fromTo('.outro-tagline',{opacity:0},{opacity:1,duration:0.4},18.1);
window.__timelines = window.__timelines || {};
window.__timelines['mandalaforge'] = tl;
</script></body></html>'''

for marker, filename, prefix in [
    ('__HOOK_SVG__', 'mandala-42.svg', 'hook'),
    ('__ORIGINAL_SVG__', 'mandala-42.svg', 'demo'),
    ('__REVISED_SVG__', 'mandala-42-reroll.svg', 'revised'),
    ('__PRINT_SVG__', 'mandala-42-reroll.svg', 'print'),
]:
    template = template.replace(marker, svg_asset(filename, prefix))
# Explicit block lines preserve deliberate headline/UI wrapping without body <br>.
template = template.replace('Procedural mandalas.<br>Room for your imagination.', 'Procedural mandalas.<div>Room for your imagination.</div>')
template = template.replace("Kristie's Coloring<br>Page Generator", "<div>Kristie's Coloring</div><div>Page Generator</div>")
template = template.replace('Ring 3<br>selected', 'Ring 3<div>selected</div>')
(COMP / 'index.html').write_text(template, encoding='utf-8')
(COMP / 'index.motion.json').write_text(json.dumps({
    'duration': 21,
    'assertions': [
        {'kind': 'appearsBy', 'selector': '#hook-line-one', 'bySec': 0.6},
        {'kind': 'staysInFrame', 'selector': '.hero-drawing'},
        {'kind': 'staysInFrame', 'selector': '.workbench'},
        {'kind': 'staysInFrame', 'selector': '.print-sheet'},
    ]
}, indent=2), encoding='utf-8')
print('Composition built from fresh MandalaForge SVG output.')
