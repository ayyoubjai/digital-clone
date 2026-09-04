# Digital Clone

An interactive talking-head clone built from two model families only:

- **Qwen3-TTS** clones a reference voice and generates a complete WAV file.
- **Ditto Talking Head** animates a source portrait from that WAV file.

The default offline mode renders a complete synchronized MP4, applies a visual
style, and plays each response in one persistent window. A lower-latency live
mode is included for experimentation.

## What is in the repository

Application orchestration and service code is in `tools/`. Ditto is pinned as a
Git submodule under `vendors/Ditto`. Qwen is installed as a Python package and
its model is downloaded from Hugging Face on first use.

Large checkpoints, generated output, Python environments, and face/voice inputs
are deliberately excluded from Git.

## Requirements

- Linux x86-64
- An NVIDIA GPU supported by the selected Ditto TensorRT engines
- A compatible NVIDIA driver
- Docker Engine with the NVIDIA Container Toolkit
- Git and Git LFS
- Roughly 30 GB of free disk space for the image, checkpoints, and model cache

The supplied Ditto engines target **Ampere or newer** GPUs. Other architectures
must generate compatible TensorRT engines from Ditto's ONNX checkpoints; see
`vendors/Ditto/README.md`.

Docker isolates the Python/CUDA user-space dependencies. It cannot replace the
host NVIDIA driver or make TensorRT engines portable across unsupported GPU
architectures.

## Quick start

Clone with the pinned Ditto source:

```bash
git clone --recurse-submodules <your-github-repository-url>
cd digital-clone
```

Download the Ditto configuration and Ampere+ TensorRT engines:

```bash
./scripts/download-models.sh
```

Add private input files locally:

```text
inputs/
├── avatar_face.png
└── voice_refs/
    ├── english_full.wav
    └── english_full.txt
```

`english_full.txt` must contain the exact transcript spoken in
`english_full.wav`. These files are ignored by Git.

Run the desktop container:

```bash
./scripts/run-docker.sh --mode offline
```

The first run builds the image and downloads the Qwen model into
`.cache/huggingface`. Later runs reuse both caches.

If Docker reports permission denied for `/var/run/docker.sock`, configure your
normal user for Docker daemon access using Docker's official post-installation
instructions, then sign out and back in. The runner intentionally does not
silently elevate itself with `sudo`.

To force an image rebuild after changing dependencies:

```bash
./scripts/run-docker.sh --build --mode offline
```

## Rendering modes

Offline mode is the recommended synchronized path:

```bash
./scripts/run-docker.sh --mode offline
```

The full audio duration determines Ditto's exact 25 FPS frame count. Only after
Ditto finishes are the untouched audio timeline and rendered frames muxed into
one MP4. Playback waits for the file's real end-of-stream.

Live mode streams raw audio and frames through FFmpeg/FFplay:

```bash
./scripts/run-docker.sh --mode live
```

Live mode has lower initial latency, but its timing also depends on real-time
generation throughput, buffering, desktop scheduling, and GPU contention.

For a machine without a desktop display, render files without playback:

```bash
docker compose run --rm digital-clone
```

Generated files are written under `outputs/`.

## Visual styles

Offline output defaults to the `cinematic` treatment. Built-in options are:

```bash
./scripts/run-docker.sh --mode offline --style natural
./scripts/run-docker.sh --mode offline --style cinematic
./scripts/run-docker.sh --mode offline --style warm
./scripts/run-docker.sh --mode offline --style cool
./scripts/run-docker.sh --mode offline --style noir
```

`natural` preserves Ditto's video stream without re-encoding it. Other presets
apply color, contrast, and optional vignette layers while retaining the same
audio timestamps.

Advanced compositions can supply any FFmpeg single-input video filter chain:

```bash
./scripts/run-docker.sh --mode offline \
  --video-filter "eq=contrast=1.1:saturation=0.85,vignette=PI/4"
```

The custom chain overrides `--style`.

## Startup interface

The CLI displays one animated initialization bar while Ditto and Qwen load:

```text
Starting digital clone (offline mode)...
  [━━━━━━━━━━━━━━━ ● ──────────────]  50%  Loading voice model
```

Use `--no-progress` for plain CI logs or `--verbose` to expose the complete
Qwen and Ditto diagnostic streams.

## Desktop playback from Docker

`scripts/run-docker.sh` forwards the current X11 display and PulseAudio/PipeWire
runtime socket, then runs the container with your host UID. On a Wayland-only
session, XWayland must be enabled. If `DISPLAY` is unavailable, the script adds
`--no-playback` and still saves complete videos.

If X11 rejects the local container connection, authorize the current local user
according to your distribution's X11 policy and run the command again. Avoid
globally disabling X server access control.

## Architecture and synchronization

```text
terminal text
    │
    ▼
Qwen3-TTS ── complete WAV ──► Ditto ── 25 FPS frames
                                      │
                                      ▼
                             aesthetic FFmpeg stage
                                      │
                                      ▼
                           synchronized MP4 + playback
```

Qwen and Ditto run in separate Python environments. This is intentional: Ditto
uses TensorRT 8.6 and cuDNN 8, while the Qwen process uses its own PyTorch CUDA
libraries. The launcher removes Ditto's explicit cuDNN override from Qwen but
retains NVIDIA runtime driver paths.

## Useful commands

```bash
make init          # initialize the Ditto submodule
make models        # download Ditto configs and Ampere+ engines
make build         # build the local image
make run           # synchronized desktop/offline mode
make run-live      # experimental live mode
make run-headless  # offline rendering without a media window
```

Type `/quit` or `/exit` in the application to shut down both model services.

## Privacy and publication

Voice recordings and face images are biometric data. Confirm `.gitignore` is in
effect and inspect `git status` before every public push. Do not publish generated
media without the subject's consent.

This repository does not currently choose a license for its original integration
code. Select one before public release. Ditto and model/runtime components retain
their own terms; see `THIRD_PARTY_NOTICES.md`.
