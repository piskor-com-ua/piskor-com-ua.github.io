# Scene interaction review

- Mobile hotspots now use source-image coordinates projected through image fit and zoom. Removed viewport clamping that moved annotations away from their subjects. Portrait layouts display the complete image in a dedicated visual area; cropped markers are hidden rather than moved onto another object. Revised façade, material and interior anchors after inspecting source images.
- Automation has four distinct source scenes: living room, kitchen, façade and house model. Each has a dedicated system diagram and reactive states. Choosing a control category also changes to the relevant scene. Presets preserve the selected category.
- The mobile control dialog mirrors the active scene with a sticky interactive preview. Climate flow, heating, audio, security sensors, perimeter, access, robot, irrigation and tariff states update the diagram and status. Illustrations are conceptual, not drawings or a connected smart-home interface.

Validation: Chromium, Ukrainian and English, 320×568 / 390×844 / 430×932 / 1440×1000; 16 architecture-through-automation frames at each size/language (128 checks), no horizontal overflow or visual-area/text overlap. Four automation backgrounds verified, category-to-scene selection checked through actual buttons; security/robot/irrigation/gate controls exercised. Mobile façade, climate, security dialog, integration dialog and desktop climate screenshots inspected. JavaScript syntax and browser console checked. Physical iOS/Safari and production performance are not covered by this local review.

## Review correction: remove abstract geometry

Removed all four wireframe system diagrams from the scenes and control preview at the owner's request. Retained four distinct photographic scenes, controls and textual state feedback. Brightness, warmth and the photographic curtain preview remain; diagram-only movement effects have been removed. Checked all four automation stages at 390px and 1440px: no diagram/SVG remains in either visualization host, and each stage retains its distinct image. JavaScript syntax and whitespace checks pass.
