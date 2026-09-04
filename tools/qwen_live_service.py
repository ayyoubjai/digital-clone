import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf
import torch
from qwen_tts import Qwen3TTSModel


PROTO = "@@CLONE@@"


def emit(obj):
    print(PROTO + json.dumps(obj), flush=True)


def trim_generated_silence(wav, sample_rate, padding_seconds=0.12):
    """Remove Qwen's variable low-level lead-in without clipping speech."""

    samples = np.asarray(wav)
    if samples.ndim != 1 or len(samples) == 0:
        return samples, 0.0

    frame_size = max(round(sample_rate * 0.02), 1)
    hop_size = max(round(sample_rate * 0.01), 1)
    starts = range(0, max(len(samples) - frame_size + 1, 1), hop_size)
    rms = np.asarray([
        np.sqrt(
            np.mean(
                np.square(
                    samples[start:start + frame_size],
                    dtype=np.float64,
                )
            )
        )
        for start in starts
    ])

    if len(rms) == 0 or float(rms.max()) == 0:
        return samples, 0.0

    # Relative gating adapts to quiet voices while rejecting the low-level
    # noise Qwen sometimes emits for a second or more before actual speech.
    active = np.flatnonzero(rms >= float(rms.max()) * 0.04)
    if len(active) == 0:
        return samples, 0.0

    padding = round(sample_rate * padding_seconds)
    first_sample = max(active[0] * hop_size - padding, 0)
    last_sample = min(
        active[-1] * hop_size + frame_size + padding,
        len(samples),
    )

    return samples[first_sample:last_sample], first_sample / sample_rate


parser = argparse.ArgumentParser()
parser.add_argument("--reference", required=True)
parser.add_argument("--reference-text-file", required=True)
parser.add_argument("--output-dir", required=True)

parser.add_argument(
    "--model",
    default="Qwen/Qwen3-TTS-12Hz-1.7B-Base",
)

parser.add_argument(
    "--gpu-memory-mib",
    type=int,
    default=3200,
)

parser.add_argument(
    "--language",
    default="English",
)

args = parser.parse_args()


if not torch.cuda.is_available():
    raise RuntimeError("CUDA is unavailable to Qwen.")


dtype = (
    torch.bfloat16
    if torch.cuda.is_bf16_supported()
    else torch.float16
)


print("Loading Qwen:", args.model, flush=True)
print("dtype:", dtype, flush=True)
print(
    "GPU placement budget:",
    f"{args.gpu_memory_mib} MiB",
    flush=True,
)


print("Loading Qwen 1.7B in native BF16 on CUDA...", flush=True)

model = Qwen3TTSModel.from_pretrained(
    args.model,
    device_map="cuda:0",
    dtype=dtype,
    attn_implementation="sdpa",
)


ref_text = Path(
    args.reference_text_file
).read_text(
    encoding="utf-8"
).strip()


print("Building cloned-voice prompt...", flush=True)

voice_prompt = model.create_voice_clone_prompt(
    ref_audio=args.reference,
    ref_text=ref_text,
    x_vector_only_mode=False,
)


output_dir = Path(args.output_dir)
output_dir.mkdir(parents=True, exist_ok=True)


counter = 0

emit({
    "type": "ready",
    "service": "qwen",
})


for line in sys.stdin:
    line = line.strip()

    if not line:
        continue

    try:
        msg = json.loads(line)
    except Exception as e:
        emit({
            "type": "error",
            "service": "qwen",
            "message": str(e),
        })
        continue

    cmd = msg.get("cmd")

    if cmd == "quit":
        break

    if cmd != "speak":
        continue

    text = str(msg.get("text", "")).strip()
    request_id = msg.get("id")

    if not text:
        continue

    counter += 1

    output = output_dir / f"speech_{counter:05d}.wav"

    print(
        f"Generating: {text!r}",
        flush=True,
    )

    t0 = time.perf_counter()

    try:
        wavs, sr = model.generate_voice_clone(
            text=text,
            language=args.language,
            voice_clone_prompt=voice_prompt,

            # Huge enough for normal conversation while
            # preventing pathological endless generation.
            max_new_tokens=1024,
        )

        elapsed = time.perf_counter() - t0

        wav, trimmed_leading = trim_generated_silence(
            wavs[0],
            sr,
        )

        if trimmed_leading > 0:
            print(
                f"Trimmed {trimmed_leading:.2f}s "
                "of generated leading silence",
                flush=True,
            )

        sf.write(
            output,
            wav,
            sr,
        )

        duration = len(wav) / sr

        # Release temporary generation allocations.
        torch.cuda.empty_cache()

        emit({
            "type": "audio",
            "service": "qwen",
            "id": request_id,
            "path": str(output.resolve()),
            "sample_rate": sr,
            "duration": duration,
            "generation_seconds": elapsed,
            "rtf": (
                elapsed / duration
                if duration > 0
                else None
            ),
        })

    except Exception as e:
        emit({
            "type": "error",
            "service": "qwen",
            "id": request_id,
            "message": repr(e),
        })


emit({
    "type": "stopped",
    "service": "qwen",
})
