# 语幕 SubFlow — CPU image (Docker Hub: crazymsn/subflow)
FROM python:3.11-slim-bookworm

LABEL org.opencontainers.image.title="SubFlow" \
      org.opencontainers.image.description="SubFlow 语幕 — AI 视频语音识别、自动翻译、字幕生成" \
      org.opencontainers.image.source="https://github.com/crazymsn/SubFlow" \
      org.opencontainers.image.vendor="深度云创科技"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md LICENSE LICENSE-fonts.txt ./
COPY src ./src
COPY config ./config
COPY fonts ./fonts
COPY assets/brand ./assets/brand

RUN pip install --no-cache-dir . \
    && pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch \
    && pip install --no-cache-dir more-itertools numba numpy tiktoken tqdm \
    && pip install --no-cache-dir --no-deps openai-whisper

WORKDIR /data
ENTRYPOINT ["subflow"]
CMD ["--help"]
