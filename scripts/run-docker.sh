#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
image_name="digital-clone:local"
force_build=0

if [[ "${1:-}" == "--build" ]]; then
    force_build=1
    shift
fi

mkdir -p \
    "${repo_root}/inputs/voice_refs" \
    "${repo_root}/outputs" \
    "${repo_root}/.cache/huggingface" \
    "${repo_root}/.runtime/home" \
    "${repo_root}/vendors/Ditto/checkpoints"

if [[ "${force_build}" == "1" ]] || ! docker image inspect "${image_name}" >/dev/null 2>&1; then
    docker build -t "${image_name}" "${repo_root}"
fi

host_uid="$(id -u)"
host_gid="$(id -g)"

docker_args=(
    --rm
    -it
    --gpus all
    --ipc host
    --user "${host_uid}:${host_gid}"
    -e HOME=/home/digital-clone
    -e HF_HOME=/cache/huggingface
    -v "${repo_root}/inputs:/app/inputs:ro"
    -v "${repo_root}/outputs:/app/outputs"
    -v "${repo_root}/vendors/Ditto/checkpoints:/app/vendors/Ditto/checkpoints:ro"
    -v "${repo_root}/.cache/huggingface:/cache/huggingface"
    -v "${repo_root}/.runtime/home:/home/digital-clone"
)

if [[ -n "${DISPLAY:-}" ]]; then
    docker_args+=(
        -e DISPLAY
        -v /tmp/.X11-unix:/tmp/.X11-unix:ro
    )

    xauthority_path="${XAUTHORITY:-${HOME}/.Xauthority}"
    if [[ -f "${xauthority_path}" ]]; then
        docker_args+=(
            -e XAUTHORITY=/tmp/.Xauthority
            -v "${xauthority_path}:/tmp/.Xauthority:ro"
        )
    fi
else
    requested_args=" $* "
    if [[ "${requested_args}" == *" --mode live "* || "${requested_args}" == *" --mode=live "* ]]; then
        echo "Live mode requires a desktop DISPLAY; use offline --no-playback here." >&2
        exit 1
    fi
    echo "No DISPLAY detected; offline output will be saved without playback." >&2
    set -- --no-playback "$@"
fi

if [[ -n "${XDG_RUNTIME_DIR:-}" && -d "${XDG_RUNTIME_DIR}" ]]; then
    docker_args+=(
        -e XDG_RUNTIME_DIR
        -e "PULSE_SERVER=unix:${XDG_RUNTIME_DIR}/pulse/native"
        -v "${XDG_RUNTIME_DIR}:${XDG_RUNTIME_DIR}"
    )
else
    echo "No desktop audio runtime detected; playback may be silent." >&2
fi

exec docker run "${docker_args[@]}" "${image_name}" "$@"
