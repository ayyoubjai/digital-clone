import argparse
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path

import librosa


PROTO = "@@CLONE@@"


STYLE_FILTERS = {
    "natural": None,
    "cinematic": (
        "eq=contrast=1.08:saturation=0.92:brightness=-0.01,"
        "colorbalance=rs=0.025:bs=0.035,vignette=PI/5"
    ),
    "warm": (
        "eq=contrast=1.04:saturation=1.08,"
        "colorbalance=rs=0.05:gs=0.015:bs=-0.035"
    ),
    "cool": (
        "eq=contrast=1.05:saturation=0.95,"
        "colorbalance=rs=-0.035:bs=0.055"
    ),
    "noir": "hue=s=0,eq=contrast=1.18:brightness=-0.025,vignette=PI/4",
}


def emit(obj):
    print(PROTO + json.dumps(obj), flush=True)


parser = argparse.ArgumentParser()
parser.add_argument("--ditto-root", required=True)
parser.add_argument("--source", required=True)
parser.add_argument("--data-root", required=True)
parser.add_argument("--cfg", required=True)
parser.add_argument("--output-dir", required=True)
parser.add_argument(
    "--style",
    choices=tuple(STYLE_FILTERS),
    default="cinematic",
)
parser.add_argument(
    "--video-filter",
    help="Custom FFmpeg -vf chain; overrides the selected style.",
)
args = parser.parse_args()


ditto_root = Path(args.ditto_root).resolve()
source_path = Path(args.source).resolve()
data_root = Path(args.data_root).resolve()
cfg_path = Path(args.cfg).resolve()
output_dir = Path(args.output_dir).resolve()
output_dir.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(ditto_root))
os.chdir(ditto_root)

from stream_pipeline_offline import StreamSDK


print("Loading Ditto offline...", flush=True)
sdk = StreamSDK(str(cfg_path), str(data_root))

emit({
    "type": "ready",
    "service": "ditto",
})


counter = 0

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue

    try:
        msg = json.loads(line)
    except Exception as exc:
        emit({
            "type": "error",
            "service": "ditto",
            "message": f"Invalid command: {exc}",
        })
        continue

    command = msg.get("cmd")
    if command == "quit":
        break
    if command != "render":
        continue

    request_id = msg.get("id")
    audio_path = Path(msg["path"]).resolve()
    counter += 1
    output_path = output_dir / f"ditto_offline_{counter:05d}.mp4"

    started = time.perf_counter()

    try:
        audio, _ = librosa.load(
            audio_path,
            sr=16000,
            mono=True,
        )
        frame_count = max(
            math.ceil(len(audio) / 16000 * 25),
            1,
        )

        sdk.setup(
            str(source_path),
            str(output_path),
        )
        sdk.setup_Nd(N_d=frame_count)

        audio_features = sdk.wav2feat.wav2feat(
            audio,
            sr=16000,
        )
        sdk.audio2motion_queue.put(audio_features)
        sdk.close()

        video_filter = args.video_filter or STYLE_FILTERS[args.style]
        mux_command = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel", "error",
                "-y",
                "-i", sdk.tmp_output_path,
                "-i", str(audio_path),
                "-map", "0:v:0",
                "-map", "1:a:0",
        ]

        if video_filter:
            mux_command.extend([
                "-vf", video_filter,
                "-c:v", "libx264",
                "-preset", "medium",
                "-crf", "18",
                "-pix_fmt", "yuv420p",
            ])
        else:
            mux_command.extend(["-c:v", "copy"])

        mux_command.extend([
                # This workstation's GStreamer install has mpg123 but no AAC
                # decoder. MP3-in-MP4 keeps one synchronized, broadly playable
                # file and allows the persistent playbin to output sound.
                "-c:a", "libmp3lame",
                "-b:a", "128k",
                "-movflags", "+faststart",
                str(output_path),
        ])

        mux = subprocess.run(
            mux_command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )

        if mux.returncode != 0:
            raise RuntimeError(
                mux.stderr.strip()
                or f"FFmpeg exited with code {mux.returncode}"
            )

        Path(sdk.tmp_output_path).unlink(missing_ok=True)

        emit({
            "type": "video",
            "service": "ditto",
            "id": request_id,
            "path": str(output_path),
            "duration": len(audio) / 16000,
            "frames": frame_count,
            "style": args.style,
            "video_filter": video_filter,
            "generation_seconds": time.perf_counter() - started,
        })

    except Exception as exc:
        emit({
            "type": "error",
            "service": "ditto",
            "id": request_id,
            "message": repr(exc),
        })


emit({
    "type": "stopped",
    "service": "ditto",
})
