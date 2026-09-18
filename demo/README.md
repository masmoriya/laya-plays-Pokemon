# The clip

The frame is 1080x1350, four to five, because the tweet is watched muted on a phone. The
Game Boy is on top at 5x, the bars are the middle third, and the ticker is one line of
42px tabular mono at the bottom. Nothing in the frame moves except the game, the bars,
the request ring beside the REPLAY badge, and the payload card typing itself in.

No screen recorder is involved. `--frames` walks the same draw calls on a fake clock and
writes one PNG per frame, so a clip is exactly as long as it says, has no cursor in it,
and re-renders identically after a code change.

## Render

```
SDL_VIDEODRIVER=dummy uv run jpp overlay --replay fixtures/runs/sample.jsonl \
  --demo --frames /tmp/frames --seconds 12
```

`--demo` paces the replay at 1.5 decisions a second, which is watchable. It does not touch
the ticker: `dec/s` and `$/hr` come from the recorded call latencies, so the playback speed
can never print itself as a measurement. A run with no timed rows shows `dec/s not
measured` rather than a number.

`--skip N` starts at decision N, which is how the three clips below are cut.

## Encode

X, H.264, plays inline:

```
ffmpeg -y -framerate 30 -i /tmp/frames/f%05d.png -c:v libx264 -preset slow -crf 23 \
  -pix_fmt yuv420p -an -movflags +faststart demo/overlay.mp4
```

README GIF, two-pass palette, half size:

```
ffmpeg -y -framerate 30 -i /tmp/frames/f%05d.png \
  -vf "fps=15,scale=540:-1:flags=lanczos,palettegen=stats_mode=diff" /tmp/pal.png
ffmpeg -y -framerate 30 -i /tmp/frames/f%05d.png -i /tmp/pal.png \
  -lavfi "fps=15,scale=540:-1:flags=lanczos[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=3" \
  demo/overlay.gif
```

A 6 second draft came out at 186 KB of MP4 and 298 KB of GIF, so the 5 MB ceiling is not
close. Raise `-crf` only if a longer cut needs it.

Stills come out of the frame dump directly. Pick the frame number and copy the PNG.

## Shot list

| clip | seconds | how |
|------|---------|-----|
| a. rival battle, bars flipping as HP drops | 12 | `--skip 0 --seconds 12` |
| b. overworld tie, two directions and the pick | 8 | `--skip 9 --seconds 8` |
| c. ticker close-up | 6 | `--skip 30 --seconds 6`, crop to the bottom 300px |

Stills: a mid-battle frame with five bars, a frame mid-reveal on the payload card, and the
`uv run measure` output as terminal text.

## Before any of this is posted

- The feed panel says `no emulator attached: recorded run` until `ROM_PATH` exists. A clip
  with an empty panel is not the clip. Get the ROM in first.
- `fixtures/runs/sample.jsonl` is still mostly `"source": "fake"` and carries no latency,
  because the gateway free tier rate-limits `typesafe-ai/jev` after about five requests
  regardless of credit balance. Paid credits, then re-run `fixtures/make_run.py`, then
  re-render.
- Label the clip a replay in the post whenever the feed panel is empty. Never imply live.
