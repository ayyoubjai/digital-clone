#!/usr/bin/env python3

import argparse
from collections import deque
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path


PROTO = "@@CLONE@@"

ROOT = Path(
    __file__
).resolve().parent.parent


class StartupProgress:
    """Small dependency-free progress display for model initialization."""

    def __init__(self, total, enabled=True):
        self.total = total
        self.completed = 0
        self.label = "Preparing"
        self.enabled = enabled and sys.stdout.isatty()
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.thread = None
        self.tick = 0

    def start(self, label):
        with self.lock:
            self.label = label

        if not self.enabled:
            print(f"Initializing: {label}...")
            return

        if self.thread is None:
            self.thread = threading.Thread(
                target=self._animate,
                daemon=True,
            )
            self.thread.start()

    def complete(self, label):
        with self.lock:
            self.completed = min(self.completed + 1, self.total)
            self.label = label

        if not self.enabled:
            print(f"  ✓ {label}")

    def finish(self):
        with self.lock:
            self.completed = self.total
            self.label = "Digital clone ready"

        if self.enabled:
            self._render()
            self.stop_event.set()
            if self.thread is not None:
                self.thread.join(timeout=1)
            sys.stdout.write("\n")
            sys.stdout.flush()

    def close(self):
        if not self.enabled:
            return
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=1)
        sys.stdout.write("\n")
        sys.stdout.flush()

    def _animate(self):
        while not self.stop_event.wait(0.09):
            self._render()
            self.tick += 1

    def _render(self):
        width = 30
        with self.lock:
            completed = self.completed
            label = self.label

        filled = round(width * completed / self.total)
        cells = ["━"] * filled + ["─"] * (width - filled)

        # A moving highlight shows that a slow model load is still active.
        if completed < self.total and filled < width:
            pulse_width = max(width - filled, 1)
            cells[filled + self.tick % pulse_width] = "●"

        percent = round(completed / self.total * 100)
        sys.stdout.write(
            f"\r\033[2K  [{''.join(cells)}] {percent:3d}%  {label}"
        )
        sys.stdout.flush()


class Service:

    def __init__(
        self,
        name,
        command,
        env,
        verbose=False,
    ):

        self.name = name
        self.verbose = verbose
        self.diagnostics = deque(maxlen=80)

        self.messages = queue.Queue()

        self.proc = subprocess.Popen(
            command,

            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,

            text=True,
            bufsize=1,

            env=env,
        )

        self.reader = threading.Thread(
            target=self._reader,
            daemon=True,
        )

        self.reader.start()

        # stderr is only human-readable logs/progress.
        # Keeping it separate prevents tqdm from corrupting
        # @@CLONE@@ protocol messages on stdout.
        self.stderr_reader = threading.Thread(
            target=self._stderr_reader,
            daemon=True,
        )

        self.stderr_reader.start()


    def _reader(self):

        for raw in self.proc.stdout:

            line = raw.rstrip("\r\n")

            # Be defensive: even stdout from multiple threads
            # could theoretically prepend text to our marker.
            if PROTO in line:

                prefix, payload = line.split(
                    PROTO,
                    1,
                )

                if prefix.strip():
                    self._diagnostic(prefix.rstrip())

                try:

                    decoder = json.JSONDecoder()

                    obj, _ = decoder.raw_decode(
                        payload.lstrip()
                    )

                    self.messages.put(obj)

                except Exception:
                    self._diagnostic(f"bad protocol: {line}")

            else:
                self._diagnostic(line)


    def _diagnostic(self, line):

        line = line.strip()
        if not line:
            return

        self.diagnostics.append(line)
        if self.verbose:
            print(f"[{self.name}] {line}")


    def _stderr_reader(self):

        for raw in self.proc.stderr:

            line = raw.rstrip("\r\n")

            if line:
                self._diagnostic(line)


    def send(self, obj):

        if self.proc.poll() is not None:
            raise RuntimeError(
                f"{self.name} has stopped"
            )

        self.proc.stdin.write(
            json.dumps(obj) + "\n"
        )

        self.proc.stdin.flush()


    def wait_for(
        self,
        msg_type,
        request_id=None,
    ):

        while True:

            # Do not wait forever if the child crashed.
            if self.proc.poll() is not None:
                detail = ""
                if self.diagnostics:
                    detail = ": " + self.diagnostics[-1]
                raise RuntimeError(
                    f"{self.name} exited unexpectedly "
                    f"with code {self.proc.returncode}{detail}"
                )

            try:
                msg = self.messages.get(timeout=0.5)
            except queue.Empty:
                continue

            if msg.get("type") == "error":
                raise RuntimeError(
                    f"{self.name}: "
                    f"{msg.get('message')}"
                )

            if (
                msg.get("type") == msg_type
                and
                (
                    request_id is None
                    or
                    msg.get("id")
                    == request_id
                )
            ):
                return msg


    def quit(self):

        if self.proc.poll() is not None:
            return

        try:
            self.send({
                "cmd": "quit",
            })
        except Exception:
            pass

        # Ditto must drain its paced frame queue, finish the recording
        # encoder, and mux the session audio before exiting. Five seconds
        # is not sufficient for a long session or a high-resolution frame.
        try:
            self.proc.wait(timeout=60)
            return
        except subprocess.TimeoutExpired:
            pass

        print(
            f"[{self.name}] graceful shutdown timed out; terminating..."
        )

        try:
            self.proc.terminate()
            self.proc.wait(timeout=3)
            return
        except Exception:
            pass

        print(
            f"[{self.name}] forcing process shutdown..."
        )

        try:
            self.proc.kill()
            self.proc.wait(timeout=2)
        except Exception:
            pass


class OfflinePlayer:

    def __init__(self):
        try:
            import gi
            gi.require_version("Gst", "1.0")
            from gi.repository import Gst
        except Exception as exc:
            raise RuntimeError(
                "Offline playback requires GStreamer Python bindings"
            ) from exc

        Gst.init(None)
        self.Gst = Gst
        self.player = Gst.ElementFactory.make(
            "playbin3",
            "digital-clone-player",
        )
        if self.player is None:
            raise RuntimeError("GStreamer playbin3 is unavailable")

        # GStreamer 1.22+ can replace the URI while playbin3 remains PLAYING,
        # which preserves one native window between responses. Ubuntu 22.04's
        # GStreamer 1.20 does not expose this property, so detect it instead of
        # failing during startup and use a READY transition between clips.
        self.instant_uri = (
            self.player.find_property("instant-uri") is not None
        )
        if self.instant_uri:
            self.player.set_property("instant-uri", True)
        self.bus = self.player.get_bus()
        self.started = False


    def play(self, path, duration):
        del duration  # GStreamer waits for the file's real EOS instead.

        Gst = self.Gst
        if self.started and not self.instant_uri:
            state_result = self.player.set_state(Gst.State.READY)
            if state_result == Gst.StateChangeReturn.FAILURE:
                raise RuntimeError(
                    "GStreamer could not prepare the next offline video"
                )
            self.player.get_state(Gst.SECOND * 3)

        self.player.set_property(
            "uri",
            Path(path).resolve().as_uri(),
        )

        # playbin3's instant-uri mode replaces the media while its playsink
        # remains in PLAYING. Avoiding READY/PAUSED is what keeps the native
        # video window alive between completed files.
        state_result = Gst.StateChangeReturn.SUCCESS
        if not self.started or not self.instant_uri:
            state_result = self.player.set_state(Gst.State.PLAYING)
            self.started = True

        if state_result == Gst.StateChangeReturn.FAILURE:
            raise RuntimeError("GStreamer could not start offline playback")

        message = self.bus.timed_pop_filtered(
            Gst.CLOCK_TIME_NONE,
            Gst.MessageType.EOS | Gst.MessageType.ERROR,
        )
        if message.type == Gst.MessageType.ERROR:
            error, debug = message.parse_error()
            raise RuntimeError(
                f"Offline playback failed: {error}"
                + (f" ({debug})" if debug else "")
            )

        # With instant-uri, stay in PLAYING at EOS so the sink retains its
        # native window and final frame. Older GStreamer releases transition
        # through READY only when the next clip is assigned above.


    def close(self):
        if self.player is None:
            return
        self.player.set_state(self.Gst.State.NULL)
        self.player.get_state(self.Gst.SECOND * 3)
        self.player = None


parser = argparse.ArgumentParser()

parser.add_argument(
    "--mode",
    choices=("live", "offline"),
    default="live",
    help=(
        "live streams generated frames; offline renders a complete video "
        "for each message and then plays it"
    ),
)

parser.add_argument(
    "--verbose",
    action="store_true",
    help="Show Qwen and Ditto diagnostic output.",
)

parser.add_argument(
    "--no-progress",
    action="store_true",
    help="Disable the animated startup progress bar.",
)

parser.add_argument(
    "--style",
    choices=("natural", "cinematic", "warm", "cool", "noir"),
    default="cinematic",
    help="Offline video color treatment (default: cinematic).",
)

parser.add_argument(
    "--video-filter",
    help=(
        "Custom FFmpeg video-filter chain for offline output. "
        "Overrides --style."
    ),
)

parser.add_argument(
    "--no-playback",
    action="store_true",
    help="Render and save offline videos without opening a media window.",
)

parser.add_argument(
    "--avatar",
    default=str(
        ROOT / "inputs/avatar_face.png"
    ),
)

parser.add_argument(
    "--reference",
    default=str(
        ROOT
        / "inputs/voice_refs/english_full.wav"
    ),
)

parser.add_argument(
    "--reference-text-file",
    default=str(
        ROOT
        / "inputs/voice_refs/english_full.txt"
    ),
)

parser.add_argument(
    "--qwen-gpu-mib",
    type=int,
    default=3200,
)

parser.add_argument(
    "--qwen-model",
    default=os.environ.get(
        "QWEN_MODEL",
        "Qwen/Qwen3-TTS-12Hz-1.7B-Base",
    ),
)

parser.add_argument(
    "--ditto-data-root",
    default=str(
        ROOT / "vendors/Ditto/checkpoints/ditto_trt_Ampere_Plus"
    ),
    help="TensorRT engine directory for this GPU architecture.",
)

parser.add_argument(
    "--ditto-online-cfg",
    default=str(
        ROOT
        / "vendors/Ditto/checkpoints/ditto_cfg/"
          "v0.4_hubert_cfg_trt_online.pkl"
    ),
)

parser.add_argument(
    "--ditto-offline-cfg",
    default=str(
        ROOT
        / "vendors/Ditto/checkpoints/ditto_cfg/"
          "v0.4_hubert_cfg_trt.pkl"
    ),
)

parser.add_argument(
    "--audio-delay-ms",
    type=int,
    default=0,
)

parser.add_argument(
    "--prebuffer-frames",
    type=int,
    default=10,
)

parser.add_argument(
    "--record-video",
    default=str(
        ROOT / "outputs/ditto/ditto_live_session.mp4"
    ),
    help="Record the live session to this MP4 path.",
)

args = parser.parse_args()


qwen_python = (
    Path(
        os.environ.get(
            "QWEN_PYTHON",
            ROOT / ".venv-qwen-tts/bin/python",
        )
    )
)

ditto_python = (
    Path(
        os.environ.get(
            "DITTO_PYTHON",
            ROOT / ".venv-ditto/bin/python",
        )
    )
)

qwen_service_py = (
    ROOT
    / "tools/qwen_live_service.py"
)

ditto_service_py = (
    ROOT
    / "tools/ditto_live_service.py"
)

ditto_offline_service_py = (
    ROOT
    / "tools/ditto_offline_service.py"
)

ditto_root = (
    ROOT
    / "vendors/Ditto"
)

ditto_data = (
    Path(args.ditto_data_root).resolve()
)

ditto_cfg = (
    Path(args.ditto_online_cfg).resolve()
)

ditto_offline_cfg = (
    Path(args.ditto_offline_cfg).resolve()
)

cudnn8 = (
    Path(
        os.environ.get(
            "DITTO_CUDNN_LIB",
            ROOT / ".deps/cudnn8/nvidia/cudnn/lib",
        )
    )
)

live_output = (
    ROOT
    / "outputs/live"
)

live_output.mkdir(
    parents=True,
    exist_ok=True,
)


required = [
    Path(args.avatar),
    Path(args.reference),
    Path(args.reference_text_file),

    qwen_python,
    ditto_python,

    qwen_service_py,
    (
        ditto_service_py
        if args.mode == "live"
        else ditto_offline_service_py
    ),

    ditto_data,
    (
        ditto_cfg
        if args.mode == "live"
        else ditto_offline_cfg
    ),

    cudnn8,
]

for executable in ("ffmpeg",):
    if shutil.which(executable) is None:
        required.append(Path(f"missing executable: {executable}"))

if args.mode == "live" and shutil.which("ffplay") is None:
    required.append(Path("missing executable: ffplay"))


missing = [
    str(p)
    for p in required
    if not p.exists()
]

if missing:

    print("Missing required paths:")

    for p in missing:
        print("  ", p)

    sys.exit(1)


#
# Each model gets its OWN library environment.
#

base_env = os.environ.copy()


qwen_env = base_env.copy()

# Never allow Ditto's explicit cuDNN 8 override into Qwen, but retain paths
# injected by the NVIDIA container runtime (notably its driver libraries).
qwen_library_paths = [
    path
    for path in base_env.get("LD_LIBRARY_PATH", "").split(os.pathsep)
    if path and Path(path) != cudnn8
]
if qwen_library_paths:
    qwen_env["LD_LIBRARY_PATH"] = os.pathsep.join(qwen_library_paths)
else:
    qwen_env.pop("LD_LIBRARY_PATH", None)


ditto_env = base_env.copy()

# Exactly the approach that already works
# with your Ditto TensorRT installation.
ditto_library_paths = [str(cudnn8)]
ditto_library_paths.extend(
    path
    for path in base_env.get("LD_LIBRARY_PATH", "").split(os.pathsep)
    if path and Path(path) != cudnn8
)
ditto_env["LD_LIBRARY_PATH"] = os.pathsep.join(ditto_library_paths)


if args.mode == "live":
    ditto_cmd = [
        str(ditto_python),
        str(ditto_service_py),
        "--ditto-root", str(ditto_root),
        "--source", str(Path(args.avatar).resolve()),
        "--data-root", str(ditto_data),
        "--cfg", str(ditto_cfg),
        "--output-dir", str(live_output),
        "--audio-delay-ms", str(args.audio_delay_ms),
        "--prebuffer-frames", str(args.prebuffer_frames),
        "--record-video", str(Path(args.record_video).resolve()),
    ]
else:
    ditto_cmd = [
        str(ditto_python),
        str(ditto_offline_service_py),
        "--ditto-root", str(ditto_root),
        "--source", str(Path(args.avatar).resolve()),
        "--data-root", str(ditto_data),
        "--cfg", str(ditto_offline_cfg),
        "--output-dir", str(ROOT / "outputs/ditto/offline"),
        "--style", args.style,
    ]
    if args.video_filter:
        ditto_cmd.extend([
            "--video-filter",
            args.video_filter,
        ])


qwen_cmd = [
    str(qwen_python),

    str(qwen_service_py),

    "--model",
    args.qwen_model,

    "--gpu-memory-mib",
    str(args.qwen_gpu_mib),

    "--reference",
    str(Path(args.reference).resolve()),

    "--reference-text-file",
    str(
        Path(
            args.reference_text_file
        ).resolve()
    ),

    "--output-dir",
    str(live_output),
]


ditto = None
qwen = None
startup = StartupProgress(
    total=2,
    enabled=not args.verbose and not args.no_progress,
)
offline_player = (
    OfflinePlayer()
    if args.mode == "offline" and not args.no_playback
    else None
)


try:

    #
    # Ditto first.
    #
    # This leaves its real VRAM allocation visible
    # before Accelerate places Qwen.
    #

    print(f"Starting digital clone ({args.mode} mode)...")
    startup.start("Loading avatar model")

    ditto = Service(
        "ditto",
        ditto_cmd,
        ditto_env,
        verbose=args.verbose,
    )

    ditto.wait_for("ready")

    startup.complete("Avatar model ready")
    startup.start("Loading voice model")

    qwen = Service(
        "qwen",
        qwen_cmd,
        qwen_env,
        verbose=args.verbose,
    )

    qwen.wait_for("ready")

    startup.complete("Voice model ready")
    startup.finish()


    print("=" * 60)
    print(f"DIGITAL CLONE READY — {args.mode.upper()}")
    print()
    print("Type a sentence and press Enter.")
    if args.mode == "live":
        print("The clone will speak it in the live window.")
    else:
        if args.no_playback:
            print("Each reply is rendered completely and saved.")
        else:
            print("Each reply is rendered completely, then played.")
    print()
    print("Commands:")
    print("  /quit")
    print("=" * 60)
    print()


    request_id = 0


    while True:

        try:

            text = input(
                "you> "
            ).strip()

        except (
            EOFError,
            KeyboardInterrupt,
        ):

            print()
            break


        if not text:
            continue


        if text.lower() in {
            "/quit",
            "/exit",
        }:
            break


        request_id += 1

        rid = request_id


        print("Generating voice...")


        qwen.send({
            "cmd": "speak",
            "id": rid,
            "text": text,
        })


        result = qwen.wait_for(
            "audio",
            request_id=rid,
        )


        duration = result[
            "duration"
        ]

        gen_s = result[
            "generation_seconds"
        ]

        rtf = result.get(
            "rtf"
        )


        print(
            f"  ✓ Audio: {duration:.2f}s "
            f"(generated in {gen_s:.2f}s)"
        )

        if rtf is not None:

            if args.verbose:
                print(f"  Voice RTF: {rtf:.2f}x")


        if args.mode == "live":
            ditto.send({
                "cmd": "play",
                "id": rid,
                "path": result["path"],
            })
            ditto.wait_for("accepted", request_id=rid)
            print("Rendering avatar; playback starts when buffered.")
            print()
        else:
            print("Rendering complete video...")
            ditto.send({
                "cmd": "render",
                "id": rid,
                "path": result["path"],
            })
            video = ditto.wait_for("video", request_id=rid)
            print(
                f"  ✓ Video rendered in "
                f"{video['generation_seconds']:.2f}s"
            )
            if offline_player is not None:
                print("Playing...")
                offline_player.play(
                    video["path"],
                    video["duration"],
                )
            print(f"  ✓ Saved: {video['path']}")
            print()


finally:

    if startup.completed < startup.total:
        startup.close()

    print()
    print("Stopping digital clone...")

    if offline_player is not None:
        offline_player.close()

    if qwen is not None:
        qwen.quit()

    if ditto is not None:
        ditto.quit()
