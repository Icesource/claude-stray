# pet sprites

Small pixel-art pets shown in the dashboard tips bubble (DD-006 v3).

## cat-walk.png

6-frame walk cycle, 72×60 per frame (sheet: 432×60), horizontally
flipped so the cat faces right (toward the speech bubble it stands
next to). Background is chroma-keyed transparent.

- **Source**: <https://opengameart.org/content/cat-sprites>
- **Original author**: nicolae-berbece
- **License**: CC0 (Creative Commons Zero / public domain)
- **Post-processing**: the original 2014 GIFs use a purple background
  (`#a475a0`) with an unreliable transparency index. The asset here
  was chroma-keyed to alpha and the walk cycle was mirrored so the
  cat faces the bubble.

Render-time, `bin/render-html.py` base64-encodes this PNG into the
generated HTML as a `data:` URL — so the sprite ships inline with
the page and there is no extra HTTP fetch (or path-resolution
headache between static `file://` mode and `mindmap --serve` mode).
