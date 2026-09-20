# Jev sprite sheets

These are original transparent pixel-art assets for the playable Jev robot trainer. The
atlas keeps four frames for every state in `config/jev_animations.json`; the runtime
loader is `src/jpp/character/sprites.py`.

The current idle loop keeps Jev on one baseline and shared boot anchor while she tosses
a Poké Ball through four hand positions. The revised design uses a compact neck band
instead of a cape.

- `jev-turnaround-sheet.png` — front, back, left, and right reference views.
- `jev-spritesheet.png` — runtime atlas, 4 × 9 frames at 96 × 112 pixels per cell.
- `states/*.png` — one horizontal sheet per animation state for editing or tooling.
- `jev-atlas.png` — the high-resolution source atlas used to derive the runtime sheets.

All PNGs preserve transparent alpha and use nearest-neighbour scaling in the PyBoy HUD
and stream compositor.
