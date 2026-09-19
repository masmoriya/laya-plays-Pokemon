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

The three clips below came out at 409 KB, 259 KB and 118 KB, and the GIF at 522 KB. The
5 MB ceiling is not close. Raise `-crf` only if a longer cut needs it.

## Stand-in rows never reach a frame

A bar drawn from a hash looks exactly like a bar drawn from an answer, and nothing on
screen tells them apart, so rows tagged `"source": "fake"` are dropped before rendering.
`--include-stand-ins` puts them back and must never be used for a clip. The current run is
40 rows, 20 of them real, so the master is 20 decisions and 13.3 seconds.

Publish the number from the same rows the clip shows, or the tweet and the video disagree:

```
uv run python -c 'import json; rows=[json.loads(l) for l in open("fixtures/runs/sample.jsonl")]; \
  open("/tmp/real.jsonl","w").write("".join(json.dumps(r)+chr(10) for r in rows if r.get("source")!="fake"))'
uv run measure /tmp/real.jsonl
```

## Shot list

Render the master once, then cut from it. All three clips are frame ranges of the same
dump, so they cannot drift from each other.

```
SDL_VIDEODRIVER=dummy uv run jpp overlay --replay fixtures/runs/sample.jsonl \
  --demo --frames /tmp/master --seconds 13.3
```

| clip | seconds | frames | file |
|------|---------|--------|------|
| a. rival battle, bars flipping as HP drops | 12 | 0-359 | `demo/clip-a-battle.mp4` |
| b. overworld tie, two directions and the pick | 8 | 120-359 | `demo/clip-b-overworld.mp4` |
| c. ticker close-up, cropped to the bottom 300px | 6 | 219-398 | `demo/clip-c-ticker.mp4` |

Cut b and c with `-start_number` and `-frames:v`, and c with `-vf "crop=1080:300:0:1046"`.

Stills, committed because the README and the thread use them: `still-bars.png` (five bars
mid battle), `still-payload.png` (the payload card mid reveal), `still-measure.txt` (the
measure line as text).

## Before any of this is posted

- The feed panel says `live feed needs  jpp play --rom` until a ROM exists. A clip with an
  empty panel is not the clip. Get the ROM in first.
- The gateway free tier rate-limits `typesafe-ai/jev` after about five requests regardless
  of credit balance, and the window refills over hours. A 40 row run costs roughly half its
  rows to stand-ins. Paid credits, re-run `fixtures/make_run.py`, re-render.
- Label the clip a replay in the post whenever the feed panel is empty. Never imply live.
