# Gesture transition review — 2026-09-13

Replaced the competing scroll-linked blend and manual animation with one decoded-image dissolve (1000ms). Repeated requests for the current asset no longer cancel the dissolve. Source position/zoom and mobile visual-area changes ease between scenes; markers are hidden until framing settles and are then reprojected.

Within the pinned story, a vertical wheel gesture advances one frame after a 24px threshold. Momentum is consumed until a 220ms quiet gap; there is also a 1100ms transition lock. A touch swipe advances once after 35px and cannot queue additional frames. Arrow/Page/Space keys step once per press; native control keys, pinch zoom, horizontal gestures and scrolling control panels remain available. At the first/last frame an outward gesture leaves the story. Direct chapter and detail navigation remain available. Scrollbar dragging and external page navigation retain native position handling.

Validation in Chromium:
- Desktop wheel 3500px followed by ten momentum events: frame 12 → 13 only. Fresh gesture → 14.
- Mid-dissolve opacity observed at 0.31, settled incoming opacity 0: transition is not cut off by scroll updates.
- Mobile CDP touch gestures: frame 14 → 15 → 16, one frame per complete swipe; automation resolves to the interior image.
- Reverse wheel 17 → 16; outward gestures leave both boundaries.
- Scrolling the automation panel changes panel scrollTop without changing the scene.
- Reduced-motion setting leaves no running image animation.
- JavaScript syntax, local artifact build and whitespace checks pass.

These are local browser-emulation checks, not a physical iPhone/Safari certification. Visual design approval is recorded in `docs/final-concept.md`.
