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

## Boundary and desktop correction

Wheel and touch now use the same entry/step function. Removed the time lock that discarded a fresh desktop gesture while an image transition was running; continued momentum stays latched, while a quiet interval or deliberate direction reversal starts a new gesture. Entering from below lands on Integration (frame 19), including oversized wheel deltas and touch inertia crossing the pin boundary after touchend. Entering from above lands on frame 0. Control panels remain native scroll regions.

Regression checks: desktop from the services boundary with a -4000px wheel event plus six momentum events stays at 19; fresh gesture advances to 18. CDP mobile return swipe also stays at 19, with a second swipe reaching 18. Initial test placement using smooth scroll was corrected to an instant services-boundary position before checking desktop input.
