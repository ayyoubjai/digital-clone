#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
checkpoint_dir="${DITTO_CHECKPOINT_DIR:-${repo_root}/vendors/Ditto/checkpoints}"
model_revision="e4a2f60328ee7c32af585ac4b3cce299e4c8e254"
model_base_url="https://huggingface.co/digital-avatar/ditto-talkinghead/resolve/${model_revision}"

if ! command -v curl >/dev/null 2>&1; then
    echo "curl is required to download Ditto checkpoints." >&2
    echo "On Ubuntu/Debian: sudo apt-get install curl" >&2
    exit 1
fi

if ! command -v sha256sum >/dev/null 2>&1; then
    echo "sha256sum is required to verify Ditto checkpoints." >&2
    exit 1
fi

# relative path | byte size | SHA-256
model_files=(
    "ditto_cfg/v0.4_hubert_cfg_trt.pkl|30924|be6729ca19e25269c4447d8ff4062e18de053b0f6dd38fdb6ef8166de6e8f3e3"
    "ditto_cfg/v0.4_hubert_cfg_trt_online.pkl|30924|7f82e1e383b3a29f390921846dd4b9a22794d96d8d835391e6cfda87782b7044"
    "ditto_trt_Ampere_Plus/appearance_extractor_fp16.engine|2182172|8aac43f36a5a8c28b73504422063a3f5e4e3f4e1eb753b41404c5efcd12d0d34"
    "ditto_trt_Ampere_Plus/blaze_face_fp16.engine|1090452|0da1dd976fadc55cf58291d49a567f031f208eab05de1fad4270deafc70daed2"
    "ditto_trt_Ampere_Plus/decoder_fp16.engine|113774428|e63716e70e28f10beab571fd96ba68d4af67c669a4a493c128a54f4f205c02a5"
    "ditto_trt_Ampere_Plus/face_mesh_fp16.engine|9238932|488dba7cc5e5d3e69fa72696cf7a691e8b8c2b7c67044506c8b0d259f70c8d21"
    "ditto_trt_Ampere_Plus/hubert_fp32.engine|1460129364|b05f0d13db35e064d78242d9f5e5269d4fab45808a67fe57b823550929278dec"
    "ditto_trt_Ampere_Plus/insightface_det_fp16.engine|9662916|43b7989a62445c2d3b0f82c2fc18bf9eea3f82a66158c4f0d804eea0ee9a0aac"
    "ditto_trt_Ampere_Plus/landmark106_fp16.engine|4255388|0c17c706c774525cf4d8b995a6af47e09d3b644dcdc5d22c87be11141b082a06"
    "ditto_trt_Ampere_Plus/landmark203_fp16.engine|58135076|314e53dff4591e37c495e59b852bf6a081446cf9c9e12d0b033de772cccc98b9"
    "ditto_trt_Ampere_Plus/lmdm_v0.4_hubert_fp32.engine|195143300|a49ab8eb962ac4f1c9a8741540df5ab4f3d534fc2d0b6c86402f49e134dfd8a7"
    "ditto_trt_Ampere_Plus/motion_extractor_fp32.engine|119783260|e43f744d73da1a3d9576a6def56d72f8ac22795cc958be44cab64ede9c46150d"
    "ditto_trt_Ampere_Plus/stitch_network_fp16.engine|381356|14b87de206a7b4228971543fadf939f7bba4803726e76583bbd79c1e5f415fca"
    "ditto_trt_Ampere_Plus/warp_network_fp16.engine|106624028|1e791b7bffa8c0e987ec251a649b6cfbc54af559de9466de566251768956ba89"
)

verify_file() {
    local path="$1"
    local expected_size="$2"
    local expected_hash="$3"

    [[ -f "${path}" ]] || return 1
    [[ "$(stat -c '%s' "${path}")" == "${expected_size}" ]] || return 1
    printf '%s  %s\n' "${expected_hash}" "${path}" | sha256sum --check --status
}

mkdir -p "${checkpoint_dir}"

echo "Downloading pinned Ditto Ampere+ checkpoints..."

for entry in "${model_files[@]}"; do
    IFS='|' read -r relative_path expected_size expected_hash <<<"${entry}"
    destination="${checkpoint_dir}/${relative_path}"
    partial="${destination}.part"

    mkdir -p "$(dirname "${destination}")"

    if verify_file "${destination}" "${expected_size}" "${expected_hash}"; then
        echo "  ✓ ${relative_path}"
        continue
    fi

    echo "  ↓ ${relative_path}"
    curl \
        --fail \
        --location \
        --retry 5 \
        --retry-all-errors \
        --continue-at - \
        --output "${partial}" \
        "${model_base_url}/${relative_path}?download=true"

    if ! verify_file "${partial}" "${expected_size}" "${expected_hash}"; then
        echo "Checksum verification failed for ${relative_path}." >&2
        echo "Remove ${partial} and retry the command." >&2
        exit 1
    fi

    mv -f "${partial}" "${destination}"
done

echo "Ditto models are ready in ${checkpoint_dir}."
echo "Qwen weights download automatically into .cache/huggingface on first run."
