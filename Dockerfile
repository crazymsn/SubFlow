# syntax=docker/dockerfile:1
# CPU builds work on native Linux amd64 and arm64 without GPU drivers.
FROM python:3.11-slim-bookworm AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    SUBFLOW_RUNTIME_DIR=/opt/subflow/runtime SUBFLOW_GPTSOVITS_HOME=/opt/GPT-SoVITS \
    SUBFLOW_TORCH_BACKEND=cpu SUBFLOW_GPTSOVITS_DEVICE=cpu UV_LINK_MODE=copy
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg libgomp1 ca-certificates \
    && rm -rf /var/lib/apt/lists/*

FROM base AS builder
RUN apt-get update && apt-get install -y --no-install-recommends build-essential cmake pkg-config \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml README.md LICENSE LICENSE-fonts.txt ./
# Keep ordinary application dependency installation independent of source edits.
RUN --mount=type=cache,target=/root/.cache/pip \
    python -c "import pathlib,tomllib; pathlib.Path('/tmp/requirements.txt').write_text('\n'.join(tomllib.load(open('pyproject.toml','rb'))['project']['dependencies']))" \
    && pip install -r /tmp/requirements.txt
COPY src ./src
COPY config ./config
COPY fonts ./fonts
COPY assets/brand ./assets/brand
COPY scripts ./scripts
COPY third_party/GPT-SoVITS /opt/GPT-SoVITS
RUN --mount=type=cache,target=/root/.cache/pip \
    --mount=type=cache,target=/opt/subflow/runtime/download-cache \
    pip install --no-deps . \
    && python scripts/prepare-runtime.py asr \
    && python scripts/prepare-runtime.py whisperx \
    && python scripts/prepare-runtime.py gptsovits --skip-models \
    && python scripts/prepare-runtime.py qwentts

FROM base AS final
ARG VERSION=1.3.60
ARG REVISION=unknown
LABEL org.opencontainers.image.title="SubFlow" \
      org.opencontainers.image.source="https://github.com/crazymsn/SubFlow" \
      org.opencontainers.image.version=$VERSION \
      org.opencontainers.image.revision=$REVISION
# Compilers and package download caches remain outside the final image.
COPY --from=builder /usr/local /usr/local
COPY --from=builder /opt/subflow/runtime /opt/subflow/runtime
COPY --from=builder /opt/GPT-SoVITS /opt/GPT-SoVITS
COPY --from=builder /app /app
WORKDIR /data
ENTRYPOINT ["subflow"]
CMD ["--help"]
