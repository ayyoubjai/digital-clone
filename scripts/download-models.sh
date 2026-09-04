#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
checkpoint_dir="${repo_root}/vendors/Ditto/checkpoints"

if ! command -v git-lfs >/dev/null 2>&1 && ! git lfs version >/dev/null 2>&1; then
    echo "git-lfs is required to download Ditto checkpoints." >&2
    exit 1
fi

if [[ -d "${checkpoint_dir}/.git" ]]; then
    echo "Updating the existing Ditto checkpoint checkout..."
    git -C "${checkpoint_dir}" fetch origin main
    git -C "${checkpoint_dir}" checkout main
    GIT_LFS_SKIP_SMUDGE=1 git -C "${checkpoint_dir}" pull --ff-only
else
    if [[ -e "${checkpoint_dir}" ]] && find "${checkpoint_dir}" -mindepth 1 -print -quit | grep -q .; then
        echo "Refusing to replace non-empty ${checkpoint_dir}." >&2
        exit 1
    fi

    mkdir -p "${checkpoint_dir}"
    rmdir "${checkpoint_dir}"
    GIT_LFS_SKIP_SMUDGE=1 git clone \
        https://huggingface.co/digital-avatar/ditto-talkinghead \
        "${checkpoint_dir}"
fi

echo "Downloading Ditto configuration and Ampere+ TensorRT engines..."
git -C "${checkpoint_dir}" lfs pull \
    --include="ditto_cfg/*,ditto_trt_Ampere_Plus/*"

echo "Ditto models are ready in ${checkpoint_dir}."
echo "Qwen weights download automatically into .cache/huggingface on first run."
