# Video Watermark Removal

A Codex skill for removing visible watermarks from user-provided videos with localized, frame-aware repair while preserving resolution, timing, and audio.

## Install in Codex

Copy the skill folder into:

`%USERPROFILE%\.codex\skills\video-watermark-removal`

or install it from this repository with Codex's skill installer using the `video-watermark-removal` path.

Install Python dependencies:

```powershell
python -m pip install -r requirements.txt
```

The processing script also needs `ffmpeg` available on PATH (or pass `--ffmpeg`).

## Usage

Use the skill in Codex with a request such as:

> Remove the watermark from this video and preserve its audio.

For direct CLI use, see:

```text
python scripts/remove_watermark.py input.mp4 -o output.mp4 --operation x,y,width,height,start,end
```

The source video is never overwritten.
