# 语幕 SubFlow — CPU image for docker compose
FROM python:3.11-slim-bookworm

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

RUN pip install --no-cache-dir . \
    && pip install --no-cache-dir openai-whisper \
    && pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

WORKDIR /data
ENTRYPOINT ["subflow"]
CMD ["--help"]
