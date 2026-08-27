#!/usr/bin/env python3
"""Localized video watermark repair with audio-preserving ffmpeg muxing."""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


@dataclass(frozen=True)
class Operation:
    x: int
    y: int
    width: int
    height: int
    start: float
    end: float

    def active(self, timestamp: float) -> bool:
        return timestamp >= self.start and (self.end < 0 or timestamp < self.end)


def find_ffmpeg(explicit: str | None) -> str:
    if explicit:
        return explicit
    found = shutil.which("ffmpeg")
    if found:
        return found
    candidates = [
        r"D:\Program Files\剪映\JianyingPro\11.3.0.14362\ffmpeg.exe",
        r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
    ]
    for candidate in candidates:
        if Path(candidate).is_file():
            return candidate
    raise FileNotFoundError("ffmpeg was not found; pass --ffmpeg with its executable path")


def probe(ffmpeg: str, source: str) -> tuple[int, int, float, bool]:
    result = subprocess.run(
        [ffmpeg, "-hide_banner", "-i", source],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    text = result.stderr
    video_line = next((line for line in text.splitlines() if "Video:" in line), "")
    size = re.search(r"(\d{2,5})x(\d{2,5})", video_line)
    fps = re.search(r"([0-9]+(?:\.[0-9]+)?)\s+fps", video_line)
    if not size or not fps:
        raise RuntimeError("could not probe video dimensions or frame rate")
    has_audio = any("Audio:" in line for line in text.splitlines())
    return int(size.group(1)), int(size.group(2)), float(fps.group(1)), has_audio


def parse_operation(raw: str) -> Operation:
    values = [item.strip() for item in raw.split(",")]
    if len(values) != 6:
        raise argparse.ArgumentTypeError("operation must be x,y,width,height,start,end")
    try:
        x, y, width, height = (int(value) for value in values[:4])
        start, end = (float(value) for value in values[4:])
    except ValueError as exc:
        raise argparse.ArgumentTypeError("operation values must be numeric") from exc
    if width <= 0 or height <= 0 or x < 0 or y < 0 or start < 0:
        raise argparse.ArgumentTypeError("coordinates and dimensions must be positive")
    if end >= 0 and end <= start:
        raise argparse.ArgumentTypeError("end must be after start, or -1")
    return Operation(x, y, width, height, start, end)


def fill_scanline(frame: np.ndarray, operation: Operation, context: int, feather: int) -> None:
    height, width = frame.shape[:2]
    x0 = max(0, operation.x)
    y0 = max(0, operation.y)
    x1 = min(width, operation.x + operation.width)
    y1 = min(height, operation.y + operation.height)
    if x1 <= x0 or y1 <= y0:
        return

    left_start = max(0, x0 - context)
    right_end = min(width, x1 + context)
    if left_start == x0 or right_end == x1:
        raise ValueError("scanline repair needs pixels on both sides of the region")
    left = frame[y0:y1, left_start:x0].astype(np.float32).mean(axis=1)
    right = frame[y0:y1, x1:right_end].astype(np.float32).mean(axis=1)
    replacement = np.empty((y1 - y0, x1 - x0, 3), dtype=np.float32)
    for offset in range(x1 - x0):
        weight = (offset + 0.5) / (x1 - x0)
        replacement[:, offset] = left * (1.0 - weight) + right * weight

    yy, xx = np.mgrid[y0:y1, x0:x1]
    distance = np.minimum.reduce([xx - x0, x1 - 1 - xx, yy - y0, y1 - 1 - yy])
    alpha = np.clip(distance.astype(np.float32) / max(feather, 1), 0.0, 1.0)[..., None]
    original = frame[y0:y1, x0:x1].astype(np.float32)
    frame[y0:y1, x0:x1] = np.clip(
        original * (1.0 - alpha) + replacement * alpha, 0, 255
    ).astype(np.uint8)


def inpaint(frame: np.ndarray, operation: Operation, radius: float, method: str) -> None:
    mask = np.zeros(frame.shape[:2], dtype=np.uint8)
    x0 = max(0, operation.x)
    y0 = max(0, operation.y)
    x1 = min(frame.shape[1], operation.x + operation.width)
    y1 = min(frame.shape[0], operation.y + operation.height)
    mask[y0:y1, x0:x1] = 255
    algorithm = cv2.INPAINT_NS if method == "ns" else cv2.INPAINT_TELEA
    frame[:] = cv2.inpaint(frame, mask, radius, algorithm)


def choose_encoder(ffmpeg: str) -> str:
    result = subprocess.run(
        [ffmpeg, "-hide_banner", "-encoders"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    encoders = result.stdout
    if " h264_nvenc " in encoders:
        return "nvenc"
    if " libx264 " in encoders:
        return "x264"
    return "mpeg4"


def encode_command(
    ffmpeg: str,
    source: str,
    output: str,
    width: int,
    height: int,
    fps: float,
    has_audio: bool,
    encoder: str,
) -> list[str]:
    command = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{width}x{height}",
        "-r", str(fps), "-i", "pipe:0", "-i", source,
        "-vf", "format=yuv420p", "-map", "0:v:0",
    ]
    if has_audio:
        command += ["-map", "1:a:0?"]
    if encoder == "nvenc":
        command += [
            "-c:v", "h264_nvenc", "-preset", "p5", "-tune", "hq",
            "-rc", "vbr", "-cq", "20", "-b:v", "0", "-spatial-aq", "1",
        ]
    elif encoder == "x264":
        command += ["-c:v", "libx264", "-preset", "medium", "-crf", "18"]
    else:
        command += ["-c:v", "mpeg4", "-q:v", "3"]
    if has_audio:
        command += ["-c:a", "copy", "-shortest"]
    command += ["-movflags", "+faststart", output]
    return command


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Remove localized video watermarks while preserving audio"
    )
    parser.add_argument("input", help="input video path")
    parser.add_argument("-o", "--output", required=True, help="output video path")
    parser.add_argument(
        "--operation", action="append", type=parse_operation, required=True,
        help="x,y,width,height,start,end; repeat for multiple regions",
    )
    parser.add_argument("--method", choices=["scanline", "telea", "ns"], default="scanline")
    parser.add_argument("--context", type=int, default=12, help="scanline border sample width")
    parser.add_argument("--feather", type=int, default=5, help="scanline edge feather")
    parser.add_argument("--radius", type=float, default=3.0, help="OpenCV inpaint radius")
    parser.add_argument("--ffmpeg", help="path to ffmpeg executable")
    parser.add_argument("--dry-run", action="store_true", help="print settings only")
    args = parser.parse_args()

    source = str(Path(args.input).resolve())
    output = str(Path(args.output).resolve())
    if not Path(source).is_file():
        parser.error(f"input file does not exist: {source}")
    if Path(source) == Path(output):
        parser.error("output must differ from input")
    ffmpeg = find_ffmpeg(args.ffmpeg)
    width, height, fps, has_audio = probe(ffmpeg, source)
    encoder = choose_encoder(ffmpeg)
    print(
        f"input={source}\nsize={width}x{height} fps={fps:g} "
        f"audio={has_audio}\nmethod={args.method} encoder={encoder}"
    )
    for operation in args.operation:
        print(f"operation={operation}")
    if args.dry_run:
        return 0

    Path(output).parent.mkdir(parents=True, exist_ok=True)
    frame_bytes = width * height * 3
    decoder = subprocess.Popen(
        [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-i", source, "-an",
            "-f", "rawvideo", "-pix_fmt", "bgr24", "-vsync", "0", "pipe:1",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    encoder_process = subprocess.Popen(
        encode_command(ffmpeg, source, output, width, height, fps, has_audio, encoder),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    frame_index = 0
    try:
        while True:
            raw = decoder.stdout.read(frame_bytes)
            if not raw:
                break
            if len(raw) != frame_bytes:
                raise RuntimeError("decoder returned a partial video frame")
            frame = np.frombuffer(raw, dtype=np.uint8).reshape((height, width, 3)).copy()
            timestamp = frame_index / fps
            for operation in args.operation:
                if operation.active(timestamp):
                    if args.method == "scanline":
                        fill_scanline(frame, operation, args.context, args.feather)
                    else:
                        inpaint(frame, operation, args.radius, args.method)
            encoder_process.stdin.write(frame.tobytes())
            frame_index += 1
    finally:
        if encoder_process.stdin:
            encoder_process.stdin.close()

    decoder.wait()
    encoder_process.wait()
    decoder_error = decoder.stderr.read().decode("utf-8", errors="replace")
    encoder_error = encoder_process.stderr.read().decode("utf-8", errors="replace")
    if decoder.returncode != 0:
        raise RuntimeError(f"ffmpeg decode failed:\n{decoder_error}")
    if encoder_process.returncode != 0:
        raise RuntimeError(f"ffmpeg encode failed:\n{encoder_error}")
    if not Path(output).is_file() or Path(output).stat().st_size == 0:
        raise RuntimeError("ffmpeg produced no output file")
    print(f"wrote {output} ({frame_index} frames)")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
