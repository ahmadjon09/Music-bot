# syntax=docker/dockerfile:1
# ── Music Bot — single-container image (bot + Gradio + Admin Mini App) ──────
FROM node:current-slim AS node

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=7860 \
    DATA_DIR=/data

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg \
 && rm -rf /var/lib/apt/lists/*

# Node is used by yt-dlp to solve YouTube JS challenges (EJS).
COPY --from=node /usr/local/bin/node /usr/local/bin/node

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app.py .
COPY src ./src

VOLUME ["/data"]
EXPOSE 7860

# One process only — no supervisors, no zombies.
CMD ["python", "app.py"]
