# MandalaForge launch film

Status: exported successfully through Studio on 2026-09-16 after resolving its stale FFmpeg lookup. Final delivery: brag.mp4 and brag.jpg.

Preview: http://localhost:3017/#project/composition

21 seconds, 1920×1080 landscape. Instrumental music, restrained interaction sounds, no narration. Story: One seed. Your pattern. → Set the structure. → Change one ring. → Made to be colored.

## Verified
- Fresh Flask test-client requests generated seeds 42, 2025, and 108. Each returned HTTP 200 and zero built-in validation issues.
- The film uses seed 42, 4 rings, 12 divisions, botanical category, detail 0.5, minimum pattern size 10.
- Ring 3 replacement uses /regenerate-ring with ring_seed 2026; returned HTTP 200 and zero ring-validation issues. This is not a claim of whole-composite revalidation after replacement.
- Source UI labels and product behavior were traced to the current template, script, Flask routes and generator.
- HyperFrames 0.8.44 check: passed; zero lint/runtime/layout/motion/contrast findings. 9 layout samples, 300 motion samples, 72 text contrast checks.
- Visual snapshots inspected: opening, generated output, selected ring, regenerated output and final held frame at 20.967 seconds. Cursor click positions adjusted against the rendered UI.
- Local preview returned HTTP 200.

## Export and FFmpeg diagnosis
- FFmpeg and FFprobe 9.0.1 were installed and executable from a fresh Node process.
- The original MandalaForge preview process started at 19:48:30 local time. Windows' FFmpeg/FFprobe command links were created at 19:51:42.
- HyperFrames 0.8.44 caches unsuccessful executable lookup results in `pathLookupCache` for the process lifetime (`dist/cli.js`, `lookupOnSystem`). The old preview returned `FFmpeg not found` while a fresh doctor process and all four other active previews detected FFmpeg.
- Restarted only the MandalaForge preview on port 3017. Its `/api/environment/ffmpeg` response changed from `ok: false` to `ok: true` without reinstalling FFmpeg or changing application code.
- Retried the actual Studio export endpoint at high quality and 30 fps; the job completed. Capture used hardware GPU and screenshots, with six workers.
- Final delivery is 1920×1080 H.264, 21 seconds, 630 frames at 30 fps, with stereo AAC audio. The settled opening at 2.8 seconds supplies brag.jpg and replaces only frame zero in the final delivery.
- Original Studio exports remain in composition/renders/. Final media evidence is in composition/final-media-report.json.

## Assets and provenance
- Mandala SVGs: generated from this repository, not reference artwork from examples/.
- UI: faithful enlarged reconstruction for video; interactions and generation timing are staged.
- Instrumental: brag skill bundled happy-beats-business-moves-vol-11-by-ende-dot-app.mp3; bundled music README identifies ende.app. This file does not assert additional music licensing terms.
- SFX: brag skill bundled Kenney click2.ogg and card-slide-1.ogg; skill identifies the SFX as CC0.
- Type: local Windows Segoe UI regular/bold, embedded in the local composition.
- GSAP 3.14.2: local copy from jsDelivr; no network-dependent animation assets at playback.
- SVG stroke animation adapted from installed HyperFrames svg-stroke-trace primitive.

Application source files were not edited. Film artifacts and reproducible asset/build helpers are contained in brag-output/.
