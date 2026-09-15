# Briukhovychi portfolio case

Confirmed by the owner: 2026; Briukhovychi, Lviv region; 397.88 m².

Sources reviewed: the 64-page visualization album and 82-page technical album supplied privately in this task. Source PDFs, drawings and contact sheets are not public assets. Images are original embedded renders, extracted without document frames and exported to responsive WebP sizes. They are not photographs of a completed building.

The client brief and design rationale are editorial interpretations of the documents. On 2026-09-15 the owner explicitly requested presentation as a completed interior with all described automation installed and operational. Public copy follows that owner-supplied status; it is not an independent commissioning audit. The source images remain renders and must not be described as actual photographs. No equipment brands, savings, guarantees or client quotes have been added.

Private security layouts and access details must not be added to the gallery.

The localized narrative is in concept/_data/briukhovychi.json. Both project collection entries share one story include and existing portfolio typography, palette, gallery and navigation. The catalog groups by project_year, newest first: Briukhovychi 2026 and Lviv apartment 2025, both supplied by the owner. Year navigation uses native anchors; undated projects remain supported.

Validation: scripts/build-site.py and scripts/check-briukhovychi-browser.js (run through Playwright CLI). Browser checks cover both catalogs and languages, year ordering, image decoding, anchors, widths 320/390/1440, gallery keyboard navigation, focus return and removal of the FAQ and concept labels.

The owner requested publication on 2026-09-15 after local review. Release through a pull request and the Pages workflow. Indexing remains disabled. The release includes the reviewed catalog heading/title changes, shared portfolio grid, year navigation and corrected terrace/perimeter images.
