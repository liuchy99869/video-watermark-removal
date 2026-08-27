---
name: video-watermark-removal
description: Remove visible watermarks from user-provided videos with localized, frame-aware repair while preserving resolution, timing, and audio.
---

# Video Watermark Removal

Use this skill when the user asks to remove, hide, or clean a watermark or logo from a video they provide.

## Workflow

1. Locate the actual input file if the path is stale or points to a temporary download. Never overwrite the source.
2. Use `ffmpeg` to inspect duration, dimensions, frame rate, codecs, and audio. Extract representative frames at the start, middle, end, and around scene changes to identify the watermark's bounding box and whether its position changes over time.
3. Choose the smallest practical repair region. For water, sky, walls, or other directional textures, prefer the script's `scanline` method. For irregular backgrounds, try `telea` or `ns` and compare stills. Use separate operations when a watermark moves between corners or appears only during intervals.
4. Run [scripts/remove_watermark.py](scripts/remove_watermark.py) with one `--operation x,y,width,height,start,end` argument per region/time interval. Use `--method scanline` unless visual checks show that a different method is better. Supply `--ffmpeg` when the executable is not on `PATH`.
5. Extract verification frames from the output at every edited interval and at untouched timestamps. Confirm that the watermark is gone, repair edges are unobtrusive, duration and frame rate are stable, and audio is present. Run an `ffmpeg -v error` decode check before delivery.

## Operational Constraints

- Keep the original file unchanged and write the result to a workspace path such as `<stem>_no_watermark.mp4`.
- Preserve the original frame size, frame rate, and audio stream where possible. Re-encode only the video stream; copy audio with `-c:a copy`.
- Do not process a whole corner for the entire video when the watermark only appears during a subset of frames; time-bound the operation to avoid unnecessary artifacts.
- A watermark can overlap important foreground content. When a clean result cannot be inferred from neighboring pixels, show a preview and report the tradeoff rather than silently destroying subject detail.
- The script needs Python with `numpy` and `opencv-python`; it uses `ffmpeg` for decode/encode. Do not download dependencies or binaries without user authorization.

## Script Reference

`--operation x,y,width,height,start,end` may be repeated. Times are seconds; use `end=-1` for the rest of the video. Example:

```text
python scripts/remove_watermark.py input.mp4 -o output.mp4 \
  --operation 35,27,143,37,3.5,8.25 \
  --operation 796,657,142,37,0,3.95 \
  --operation 796,657,142,37,8,12 \
  --method scanline
```

Use `--dry-run` to print the probed media properties and parsed operations without creating an output.
