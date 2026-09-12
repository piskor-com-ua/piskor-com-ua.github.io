# Automation consistency and controls review

## Fixes

- Removed the brightness/tint filter from the entire scene container. It now affects the photograph only, avoiding colored rectangular letterboxing. Removed photograph borders and status overlays; status is displayed in the control panel.
- Climate uses a reference edit of the original living room, preserving its fireplace, sofa, chair, timber ceiling, glazing and forest view. No unrelated staircase or second storey is introduced.
- Security uses an additional view of the same low forest house with gate, camera and keypad. Gate control crossfades between closed/open photographic variants.
- Moved gate and entrance lock into Security. Drives links to that category, while curtains and window control use an interior image.
- Water/smoke/gas simulation selects the existing kitchen view; these concealed systems report their specific simulated response in text. No assertion that hidden sensors are physically visible in the photograph.
- Home integration uses the original house and garden; robot control selects the interior. All 15 toggles and four ranges now report their individual state, including previously missing ventilation, floor heating, media, volume, presence, biodynamic light, lock and window feedback.
- Curtains use the existing closed-curtain variant of the same living room. Day/evening images were visually checked against that room.

## Visual/control mapping and limits

| Controls | View | Feedback |
|---|---|---|
| Light/presence/biodynamic | Living room/day/evening | Brightness/tone and explicit states; presence is a demo state, no occupancy simulation |
| Temperature/humidity/ventilation/floor | Same living room with discreet equipment | Setpoints and individual on/off states; no fake heat/air geometry |
| Media/volume | Living room | Playback state and volume; no audio playback |
| Gate | Same house entrance | Actual open/closed image variants |
| Lock/perimeter | Same house entrance | Locked/unlocked and armed status; unlocking does not pretend to open the door |
| Leak/smoke/gas | Existing kitchen | Simulated shutoff/notification messages |
| Curtains/window | Living room | Curtain image variant; window state reported in text |
| Robot/irrigation/tariff | Living room/garden | Explicit run/schedule states; no physical equipment connection or animated robot claim |

## Validation

- 15 toggles × Ukrainian/English × 390px/1440px = 60 actual button interactions; checked pressed state and distinct feedback after each.
- Four ranges exercised with keyboard End in each combination; all-off, reset and curtains exercised. Gate asset verified open; curtains asset verified closed.
- Four automation stages × two languages × five screen sizes (320×568, 375×667, 390×844, 430×932, 1440×1000): 40 route/overflow/background/absence-of-geometry checks passed.
- Inspected mobile climate and security, mobile control panel, and desktop entry images. JavaScript syntax and whitespace checks pass; no browser JavaScript errors. Existing font-preload warning observed.
- Local Chromium evidence; not a physical iOS/Safari or production PageSpeed certification.

Asset prompts and generation provenance: `assets/automation/provenance.md`.
