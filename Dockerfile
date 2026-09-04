FROM nvidia/cuda:12.1.1-cudnn8-devel-ubuntu22.04

ARG DEBIAN_FRONTEND=noninteractive
ARG PYTHON_VERSION=3.10

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1 \
    QWEN_PYTHON=/opt/venvs/qwen/bin/python \
    DITTO_PYTHON=/opt/venvs/ditto/bin/python \
    DITTO_CUDNN_LIB=/usr/lib/x86_64-linux-gnu \
    HF_HOME=/cache/huggingface \
    NVIDIA_VISIBLE_DEVICES=all \
    NVIDIA_DRIVER_CAPABILITIES=compute,utility,video,graphics,display

RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        git \
        git-lfs \
        gir1.2-gstreamer-1.0 \
        gstreamer1.0-libav \
        gstreamer1.0-plugins-bad \
        gstreamer1.0-plugins-base \
        gstreamer1.0-plugins-good \
        gstreamer1.0-plugins-ugly \
        gstreamer1.0-pulseaudio \
        gstreamer1.0-tools \
        libgl1 \
        libglib2.0-0 \
        libsm6 \
        libsndfile1 \
        libxext6 \
        libxrender1 \
        python3-gi \
        python${PYTHON_VERSION} \
        python${PYTHON_VERSION}-dev \
        python${PYTHON_VERSION}-venv \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements-ditto.txt requirements-qwen.txt ./

RUN python${PYTHON_VERSION} -m venv /opt/venvs/ditto \
    && /opt/venvs/ditto/bin/pip install --upgrade pip setuptools wheel \
    && /opt/venvs/ditto/bin/pip install \
        torch==2.5.1 torchvision==0.20.1 torchaudio==2.5.1 \
        --index-url https://download.pytorch.org/whl/cu121 \
    && /opt/venvs/ditto/bin/pip install \
        --extra-index-url https://pypi.nvidia.com \
        -r requirements-ditto.txt

RUN python${PYTHON_VERSION} -m venv /opt/venvs/qwen \
    && /opt/venvs/qwen/bin/pip install --upgrade pip setuptools wheel \
    && /opt/venvs/qwen/bin/pip install \
        torch==2.5.1 torchaudio==2.5.1 \
        --index-url https://download.pytorch.org/whl/cu121 \
    && /opt/venvs/qwen/bin/pip install -r requirements-qwen.txt

COPY . /app

RUN chmod +x /app/docker/entrypoint.sh /app/scripts/*.sh \
    && test -f /app/vendors/Ditto/stream_pipeline_offline.py \
    && test -f /usr/lib/x86_64-linux-gnu/libcudnn.so.8

ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["--mode", "offline"]
