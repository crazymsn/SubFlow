# CPU default: no GPU driver or NVIDIA container toolkit required.
FROM python:3.11-slim-bookworm
LABEL org.opencontainers.image.title="SubFlow" \
      org.opencontainers.image.source="https://github.com/crazymsn/SubFlow"
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    SUBFLOW_RUNTIME_DIR=/opt/subflow/runtime SUBFLOW_GPTSOVITS_HOME=/opt/GPT-SoVITS \
    SUBFLOW_TORCH_BACKEND=cpu SUBFLOW_GPTSOVITS_DEVICE=cpu
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg libgomp1 ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml README.md LICENSE LICENSE-fonts.txt ./
COPY src ./src
COPY config ./config
COPY fonts ./fonts
COPY assets/brand ./assets/brand
COPY scripts ./scripts
COPY third_party/GPT-SoVITS /opt/GPT-SoVITS
RUN pip install --no-cache-dir . \
    && python scripts/prepare-runtime.py asr \
    && python scripts/prepare-runtime.py gptsovits --skip-models
WORKDIR /data
ENTRYPOINT ["subflow"]
CMD ["--help"]
