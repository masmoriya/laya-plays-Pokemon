"""FFmpeg process helpers. Stream key stays in environment, never argv/logs."""

import os
import subprocess


def command(width=1920, height=1080, fps=30):
    target = os.environ.get("TWITCH_CHANNEL", "")
    key = os.environ.get("TWITCH_STREAM_KEY", "")
    if not target or not key:
        raise RuntimeError("TWITCH_CHANNEL and TWITCH_STREAM_KEY required")
    return [
        "ffmpeg", "-loglevel", "warning", "-f", "rawvideo", "-pix_fmt", "rgb24",
        "-s", f"{width}x{height}", "-r", str(fps), "-i", "-", "-f", "flv",
        f"{target}/{key}",
    ]


def start(**kwargs):
    return subprocess.Popen(command(**kwargs), stdin=subprocess.PIPE)

